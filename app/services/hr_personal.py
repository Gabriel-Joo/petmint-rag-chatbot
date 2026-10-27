"""
hr_personal.py
사내규정 개인화(2026-10-28, PETMINT_HR_PERSONAL) — 상담원이 자기 연차 잔여·퇴직금·자격수당·승진 시점을 물으면 코드가 답한다.
업무특화가 고객 원장으로 보험금을 계산하듯(payout), 인사 원장(insurance_core 0003)과 인사규정의 계산 규칙으로 계산한다.
모델은 직원 정보를 받지 않는다 — 베이스 모델은 새 숫자를 계산하지 못하고(업무특화와 같은 판단), 남의 급여가 프롬프트에 섞이면 안 된다.

범위를 좁게 잡는다(2026-10-24 이후 원칙) — 세 조건이 다 맞아야 코드가 답한다:
  1. 지금 질문에 본인 지칭이 있다(내·제·저·나 + 조사, 제가·저는…). "연차는 몇 개 나와요?" 같은 일반 질문은 모델이 규정으로 답한다
  2. 주제 낱말이 있다 — 연차(남은·잔여·몇·며칠) / 퇴직금 / 자격수당 / 승진·진급. 경조·병가·출산·육아·재택이 있으면 연차가 아니다
  3. 로그인한 상담원이 인사 원장에 있다(access 모드의 dev@local은 없다 → 모델)
자격수당은 "따면·취득하면·있으면"(가정)이면 답하지 않는다 — 지금 받는 액수가 아니라 규정을 묻는 것이다.

규정이 정하지 않은 것은 가정을 답에 적는다: 연차 근속은 입사일부터(휴직 차감 여부 미정), 출근율 80% 이상·1년 미만 월 개근 가정,
평균임금은 최근 3개월(완료된 급여 달) 임금총액 ÷ 그 기간 총일수, 휴직 기간을 승진 체류연수에서 빼는지는 규정에 없다.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import Engine, text

from app.schemas import ReferenceItem, SourceItem
from data.rag_context import graph_key

CERT_PAY = {"손해사정사": 200_000, "보험계리사": 200_000, "공인회계사": 300_000, "변호사": 400_000,
            "손해평가사": 100_000, "정보처리기사": 50_000}                       # 제27조 ① 표
PROMOTION_YEARS = {"사원": ("대리", 4), "대리": ("과장", 4), "과장": ("차장", 5), "차장": ("부장", 5)}   # 제33조 ②
COUNTED_ABSENCE = ("육아휴직", "병역휴직")                                         # 제22조 ④ 근속 산입
ARTICLES = {17: "연차유급휴가", 18: "연차휴가의 사용", 2: "적용범위", 3: "용어의 정의", 22: "휴직", 27: "자격수당",
            28: "퇴직금", 32: "인사평가", 33: "승진", 41: "퇴직의 사유", 11: "근무시간"}

_SELF = re.compile(r"(?:^|[\s,])(?:내|제|저|나)(?:\s|가|는|도|의)|저희\s*직원으로서|본인")
_LEAVE = re.compile(r"연차|휴가")
_LEAVE_ASK = re.compile(r"남|잔여|몇\s*(?:일|개)|며칠|얼마")
_NOT_LEAVE = re.compile(r"경조|병가|출산|육아|특별휴가|재택|휴직")
_UNUSED = re.compile(r"미사용|수당")
_AMOUNT = re.compile(r"얼마|금액|받|나와|나오")
_SEVERANCE = re.compile(r"퇴직금")
_GRADE = re.compile(r"사원|대리|과장|차장|부장")
MONTHLY_HOURS = 209                     # 월 소정근로시간 — 주 40시간(제11조 ①) + 주휴, 통상임금 시급 환산의 통상 기준
DAILY_HOURS = 8                         # 1일 소정근로시간(제11조 ①)
_CERT = re.compile(r"자격\s*수당")
_CERT_IF = re.compile(r"따면|취득하면|있으면|생기면|붙으면")
_PROMO = re.compile(r"승진|진급|(?:대리|과장|차장|부장)\s*(?:이|가)?\s*(?:되|될|돼|달)")


@dataclass
class Facts:
    """한 직원의 인사 원장 — EmployeeStore.load"""
    employee_id: str
    name: str
    team: str | None
    grade: str
    grade_since: date
    employment_type: str
    hire_date: date
    birth_date: date
    retired_on: date | None
    career_hire: bool = False                                                         # 경력직 — 수습 면제(제7조 ⑤)
    certificates: list[tuple[str, date, date | None]] = field(default_factory=list)   # (자격, 취득일, 사본 제출일)
    payroll: list[tuple[date, int, int]] = field(default_factory=list)                # (급여 달 1일, 임금총액, 월 통상임금)
    leaves: list[tuple[str, date, float]] = field(default_factory=list)               # (종류, 시작일, 일수)
    absences: list[tuple[str, date, date]] = field(default_factory=list)              # (휴직 종류, 시작, 끝)
    evaluations: list[tuple[str, str]] = field(default_factory=list)                  # (기간, 등급) 오래된 것부터


class EmployeeStore:
    """인사 원장 읽기(기간계, SELECT만). 원장은 앱 밖에서 바뀌므로 캐시하지 않는다(고객 원장과 같다)"""

    def __init__(self, core: Engine):
        self.core = core

    def load(self, email: str) -> Facts | None:
        with self.core.connect() as c:
            e = c.execute(text("SELECT employee_id, name, team, grade, grade_since, employment_type, hire_date, birth_date,"
                               " retired_on, career_hire FROM employees WHERE email = :m"), dict(m=email.lower())).first()
            if e is None:
                return None
            eid = dict(e=e[0])
            f = Facts(*e)
            f.certificates = [tuple(r) for r in c.execute(text(
                "SELECT cert_name, acquired_on, submitted_on FROM employee_certificates WHERE employee_id = :e"), eid)]
            f.payroll = [(r[0], int(r[1]), int(r[2])) for r in c.execute(text(
                "SELECT pay_month, total_pay, ordinary_wage FROM employee_payroll WHERE employee_id = :e ORDER BY pay_month"), eid)]
            f.leaves = [(r[0], r[1], float(r[2])) for r in c.execute(text(
                "SELECT leave_type, start_date, days FROM employee_leaves WHERE employee_id = :e"), eid)]
            f.absences = [tuple(r) for r in c.execute(text(
                "SELECT kind, start_date, end_date FROM employee_absences WHERE employee_id = :e ORDER BY start_date"), eid)]
            f.evaluations = [tuple(r) for r in c.execute(text(
                "SELECT period, grade FROM employee_evaluations WHERE employee_id = :e ORDER BY period"), eid)]
        return f


# ----- 날짜·숫자

def _years(a: date, b: date) -> int:
    """만 년수"""
    return b.year - a.year - ((b.month, b.day) < (a.month, a.day))


def _add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:                                  # 2월 29일
        return d.replace(year=d.year + n, day=28)


def _months(a: date, b: date) -> int:
    """a부터 b까지 다 채운 달 수"""
    return (b.year - a.year) * 12 + b.month - a.month - (b.day < a.day)


def _ymd(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일"


def _batchim(word: str) -> bool:
    ch = word[-1]
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0


def _won(n: int) -> str:
    return f"{n:,}원"


def _days(x: float) -> str:
    return f"{x:g}일"


# ----- 계산(규정 조문 그대로)

def annual_leave(f: Facts, today: date) -> dict:
    """제17조 — 지금 연차 기간(입사 기념일부터 1년)의 부여·사용·잔여. 1년 미만은 다 채운 달마다 1일"""
    n = _years(f.hire_date, today)
    if n >= 1:
        start = _add_years(f.hire_date, n)
        extra = (n - 1) // 2 if n >= 3 else 0
        grant, basis = min(25, 15 + extra), (f"15일 + 근속 가산 {extra}일" + (", 한도 25일" if 15 + extra > 25 else "")
                                             if extra else "15일")
    else:
        start = f.hire_date
        grant, basis = _months(f.hire_date, today), "1년 미만 — 다 채운 달마다 1일"
    used = sum(d for kind, s, d in f.leaves if kind == "연차" and start <= s <= today)
    return dict(start=start, end=_add_years(start, 1) - timedelta(days=1), years=n, grant=grant, basis=basis, used=used, left=grant - used)


def tenure_days(f: Facts, today: date) -> tuple[int, int]:
    """제3조 5호·제22조 ④ — (근속 일수, 뺀 휴직 일수). 육아·병역휴직은 넣고 나머지 휴직은 뺀다"""
    excluded = sum((min(e, today) - s).days + 1 for kind, s, e in f.absences if kind not in COUNTED_ABSENCE and s <= today)
    return (today - f.hire_date).days - excluded, excluded


def average_wage(f: Facts, today: date) -> tuple[float, list[date], int, int] | None:
    """제3조 4호 — 최근 다 끝난 급여 달 3개의 임금총액 ÷ 그 기간 총일수. 3개월치가 없으면 None"""
    done = [(m, t) for m, t, _ in f.payroll if (m.year, m.month) < (today.year, today.month)][-3:]
    if len(done) < 3:
        return None
    first, last = done[0][0], done[-1][0]
    end = date(last.year + (last.month == 12), last.month % 12 + 1, 1)
    days = (end - first).days
    total = sum(t for _, t in done)
    return total / days, [m for m, _ in done], total, days


def cert_allowance(f: Facts, today: date) -> dict:
    """제27조 — 이번 달 자격수당(사본 낸 다음 달부터, 둘 이상이면 큰 것 하나)과 아직 안 나오는 자격"""
    paid, pending = [], []
    for name, _, submitted in f.certificates:
        amount = CERT_PAY.get(name)
        if amount is None:
            continue
        if submitted is not None and (submitted.year, submitted.month) < (today.year, today.month):
            paid.append((amount, name))
        else:
            start = None if submitted is None else date(submitted.year + (submitted.month == 12), submitted.month % 12 + 1, 1)
            pending.append((name, amount, start))
    return dict(amount=max(paid)[0] if paid else 0, cert=max(paid)[1] if paid else None, held=[n for _, n in sorted(paid)],
                pending=pending)


def promotion(f: Facts, today: date) -> dict:
    """제33조 — 다음 직급 최소 체류연수가 차는 날, 최근 2회 연속 D면 제외"""
    nxt = PROMOTION_YEARS.get(f.grade)
    grades = [g for _, g in f.evaluations]
    overlap = [(k, s, e) for k, s, e in f.absences if e >= f.grade_since]
    if nxt is None:
        return dict(next=None, overlap=overlap)
    target, years = nxt
    eligible = _add_years(f.grade_since, years)
    return dict(next=target, years=years, eligible=eligible, met=eligible <= today, dd=grades[-2:] == ["D", "D"],
                last=f.evaluations[-2:], overlap=overlap)


# ----- 답

def _who(f: Facts) -> str:
    """답 머리 — 팀은 쓰지 않는다(상담원 전용 도구라 팀이 하나, 2026-10-28). 직급은 계산(승진·수습·정년)에 걸리므로 쓴다"""
    return f"{f.name}님({f.grade}, 입사 {_ymd(f.hire_date)})"


def _leave_text(f: Facts, today: date) -> tuple[str, list[int]]:
    a = annual_leave(f, today)
    head = (f"{_who(f)}의 이번 연차 기간({_ymd(a['start'])} ~ {_ymd(a['end'])}) 연차는 {_days(a['grant'])}({a['basis']})이고, "
            f"지금까지 {_days(a['used'])}을 써서 **{_days(a['left'])} 남았습니다.**")
    notes = ["1년간 80% 이상 출근했다고 보고 계산했습니다." if a["years"] >= 1 else
             "다 채운 달마다 개근했다고 보고 계산했습니다(1년 미만은 1개월 개근 시 1일).",
             "반차는 0.5일로 셉니다. 남은 연차는 이 기간이 끝나면 소멸하고, 미사용분은 통상임금 기준 수당으로 받습니다."]
    if any(k not in COUNTED_ABSENCE for k, _, _ in f.absences):
        notes.append("휴직 기간을 연차 근속에서 빼는지는 규정에 따로 없어 입사일부터 셌습니다.")
    return head + "\n" + "\n".join(f"- {n}" for n in notes), [17, 18]


def ordinary_daily(f: Facts, today: date) -> tuple[int, date, float] | None:
    """하루 통상임금 — 가장 최근 끝난 급여 달의 월 통상임금 ÷ 209시간 × 8시간. (월 통상임금, 그 달, 하루) 또는 None"""
    done = [(m, o) for m, _, o in f.payroll if (m.year, m.month) < (today.year, today.month)]
    if not done:
        return None
    month, monthly = done[-1]
    return monthly, month, monthly / MONTHLY_HOURS * DAILY_HOURS


def _unused_leave_text(f: Facts, today: date) -> tuple[str, list[int]]:
    a, d = annual_leave(f, today), ordinary_daily(f, today)
    if d is None:
        return f"{_who(f)}의 급여 기록이 없어 통상임금을 계산할 수 없습니다. 인사팀에 확인하세요.", [17]
    monthly, month, daily = d
    amount = round(a["left"] * daily)
    lines = [f"{_who(f)}이 남은 연차 {_days(a['left'])}을 이번 연차 기간({_ymd(a['end'])}까지)에 다 쓰지 않으면, "
             f"미사용 연차수당은 **약 {_won(amount)}**입니다.",
             f"- 하루 통상임금: 월 통상임금 {_won(monthly)}({month.month}월) ÷ {MONTHLY_HOURS}시간 × {DAILY_HOURS}시간 = {_won(round(daily))}",
             f"- {_won(round(daily))} × {_days(a['left'])}. 남은 기간에 연차를 쓰면 그만큼 줄어듭니다.",
             f"- 규정은 '통상임금을 기준으로' 지급한다고만 정해, 하루치는 1일 소정근로 {DAILY_HOURS}시간·주 40시간(제11조)과 "
             f"월 {MONTHLY_HOURS}시간 환산으로 계산했습니다. 실제 금액은 인사팀 정산을 따릅니다."]
    return "\n".join(lines), [17, 11]


def _severance_text(f: Facts, today: date) -> tuple[str, list[int]]:
    days, excluded = tenure_days(f, today)
    if days < 365:
        one = _add_years(f.hire_date, 1)
        return (f"{_who(f)}은 계속 근로기간이 1년이 되지 않아 지금 퇴직하면 **퇴직금이 없습니다.** "
                f"퇴직금은 계속 근로기간이 1년 이상인 직원에게 지급합니다({_ymd(one)}부터)."), [28]
    avg = average_wage(f, today)
    if avg is None:
        return f"{_who(f)}의 최근 3개월 급여 기록이 없어 평균임금을 계산할 수 없습니다. 인사팀에 확인하세요.", [3, 28]
    per_day, months, total, period = avg
    amount = round(per_day * 30 * days / 365)
    span = f"{months[0].month}~{months[-1].month}월"
    lines = [f"{_who(f)}이 오늘({_ymd(today)}) 퇴직한다고 보면 퇴직금은 **약 {_won(amount)}**입니다.",
             f"- 평균임금: 최근 3개월({span}) 임금총액 {_won(total)} ÷ {period}일 = 하루 {_won(round(per_day))}",
             f"- 근속: {days:,}일" + (f"(근속에 넣지 않는 휴직 {excluded}일 뺌)" if excluded else "")
             + f" → 하루 평균임금 × 30일 × {days:,} ÷ 365",
             "- 규정은 '30일분 이상'이라 이 금액이 최소 기준입니다. 실제 지급은 퇴직연금제도로 하므로 정확한 금액은 퇴직연금규정과 인사팀 정산을 따릅니다."]
    return "\n".join(lines), [3, 22, 28] if excluded else [3, 28]


def _cert_text(f: Facts, today: date) -> tuple[str, list[int]]:
    c = cert_allowance(f, today)
    if c["amount"]:
        head = f"{_who(f)}의 이번 달 자격수당은 **{_won(c['amount'])}**({c['cert']})입니다."
        if len(c["held"]) > 1:
            head += f" 수당 대상 자격이 {len(c['held'])}개({', '.join(c['held'])})라 금액이 큰 하나만 받습니다."
    else:
        head = f"{_who(f)}은 지금 받는 자격수당이 **없습니다.**"
    lines = [head]
    for name, amount, start in c["pending"]:
        lines.append(f"- {name}({_won(amount)}): 자격증 사본을 아직 내지 않았습니다. 내면 그다음 달부터 받습니다." if start is None
                     else f"- {name}({_won(amount)}): 사본을 냈으므로 {start.year}년 {start.month}월분부터 받습니다.")
    return "\n".join(lines), [27]


def _promotion_text(f: Facts, today: date) -> tuple[str, list[int]]:
    p = promotion(f, today)
    if p["next"] is None:
        return (f"{_who(f)}은 {f.grade}입니다. 인사규정의 최소 체류연수 표는 차장 → 부장까지라, 그 위 직급으로의 승진 요건은 "
                f"규정에 나와 있지 않습니다."), [33]
    since = f"{_ymd(f.grade_since)}에 {f.grade}{'이' if _batchim(f.grade) else '가'} 되어"
    if p["met"]:
        head = f"{_who(f)}은 {since}, {p['next']} 승진 최소 체류연수 {p['years']}년을 {_ymd(p['eligible'])}에 채웠습니다."
    else:
        left = _months(today, p["eligible"])
        rest = f"약 {left // 12}년 {left % 12}개월" if left >= 12 else f"약 {left}개월"
        head = (f"{_who(f)}은 {since}, {p['next']} 승진 최소 체류연수 {p['years']}년은 **{_ymd(p['eligible'])}**에 찹니다"
                f"({rest} 남음).")
    lines = [head]
    if p["dd"]:
        lines.append(f"- 다만 최근 2회 평가가 연속 D({', '.join(per for per, _ in p['last'])})라 **승진 대상에서 제외됩니다.**")
    elif p["met"]:
        lines.append("- 승진은 체류연수만이 아니라 인사평가 결과·근속연수·자격요건을 종합해 정합니다.")
    for kind, s, e in p["overlap"]:
        lines.append(f"- {kind}({_ymd(s)} ~ {_ymd(e)}) 기간을 체류연수에서 빼는지는 규정에 따로 없습니다.")
    return "\n".join(lines), [32, 33] if p["dd"] else [33]


TOPICS = ("연차", "연차수당", "퇴직금", "자격수당", "승진")
FAMILY = {"연차": {"연차", "연차수당"}, "연차수당": {"연차", "연차수당"}}


def topics_of(question: str, assume_self: bool = False) -> list[str]:
    """본인 지칭 + 주제 낱말 — 걸리는 주제(질문 순서 아님, TOPICS 순서). 본인 지칭이 없으면 [](assume_self면 지칭 없이 본다)"""
    q = question.strip()
    if not assume_self and not _SELF.search(" " + q):
        return []
    out = []
    if _LEAVE.search(q) and _UNUSED.search(q) and _AMOUNT.search(q) and not _NOT_LEAVE.search(q):
        out.append("연차수당")                  # 미사용 연차 수당 금액 — 잔여 일수 × 하루 통상임금
    elif _LEAVE.search(q) and _LEAVE_ASK.search(q) and not _NOT_LEAVE.search(q):
        out.append("연차")
    if _SEVERANCE.search(q):
        out.append("퇴직금")
    if _CERT.search(q) and not _CERT_IF.search(q):
        out.append("자격수당")
    if _PROMO.search(q):
        out.append("승진")
    return out


def inherited_topics(question: str, prior_question: str | None, short_follow_up: bool) -> list[str]:
    """본인 지칭이 없는 질문이 바로 앞의 개인화 질문을 이어받는가(2026-10-28 운영: "연차 미사용분은 얼마 받나요?").
    앞 질문이 개인화 질문이고, 지금 질문이 같은 주제 갈래(연차 ↔ 연차수당)이거나 짧은 후속("그럼 퇴직금은요?")일 때만.
    직급 이름이 든 승진 질문("과장은 몇 년 있어야 차장 돼요?")은 앞 주제가 승진일 때만 — 아니면 일반 질문이다"""
    prior = topics_of(prior_question or "")
    if not prior:
        return []
    q = question.strip()
    now = topics_of(q, assume_self=True)
    if not now and "연차" in {t for p in prior for t in FAMILY.get(p, {p})} and _UNUSED.search(q):
        now = ["연차수당"]                      # "미사용분은요?"·"그럼 수당은 얼마예요?" — 앞이 연차
    family = {t for p in prior for t in FAMILY.get(p, {p})}
    if "승진" in now and "승진" not in family and _GRADE.search(q):
        now = [t for t in now if t != "승진"]
    return [t for t in now if t in family or short_follow_up]


def may_inherit(question: str) -> bool:
    """앞 턴을 읽어 볼 만한가 — 본인 지칭 없이 주제 낱말(또는 미사용·수당)만 있는 질문. chat_ws가 이때만 앞 턴을 DB에서 읽는다"""
    return bool(topics_of(question, assume_self=True) or _UNUSED.search(question)) and not topics_of(question)


def answer(question: str, f: Facts | None, today: date, prior_question: str | None = None,
           short_follow_up: bool = False) -> tuple[str, list[int]] | None:
    """(답 글, 근거 조 번호) 또는 None(모델이 답한다). prior_question: 같은 세션 바로 앞 질문"""
    topics = topics_of(question) or inherited_topics(question, prior_question, short_follow_up)
    if not topics or f is None:
        return None
    if f.retired_on is not None and f.retired_on <= today:
        return f"{f.name}님은 {_ymd(f.retired_on)} 퇴직한 직원으로 기록되어 있어 재직 기준 계산을 하지 않습니다. 인사팀에 확인하세요.", [41]
    if f.employment_type != "정규직":
        money = [t for t in topics if t in ("퇴직금", "자격수당")]
        return (f"{_who(f)}은 {f.employment_type} 직원입니다. {f.employment_type} 직원의 급여 및 퇴직에 관한 사항은 "
                f"이 규정이 아니라 **개별근로계약**에 따릅니다(복무에 관한 사항만 이 규정을 준용합니다)."
                + (" " + "·".join(money) + "은 근로계약서를 확인하세요." if money else
                   " 연차·승진도 근로계약서에서 정한 바를 확인하세요.")), [2]
    parts, arts = [], []
    for t in topics:
        body, a = {"연차": _leave_text, "연차수당": _unused_leave_text, "퇴직금": _severance_text, "자격수당": _cert_text,
                   "승진": _promotion_text}[t](f, today)
        parts.append(body)
        arts += [x for x in a if x not in arts]
    return "\n\n".join(parts), arts


def references(articles: list[int], hr_chunks: list[dict]) -> list[ReferenceItem]:
    """근거 조항 — 인사규정 청크에서 그 조의 장(section_name)을 찾는다"""
    chapter = {c.get("article_num"): (c.get("section"), c.get("section_name")) for c in hr_chunks
               if c.get("section") == "본칙" and c.get("article_num") is not None}
    return [ReferenceItem(citation_label=f"제{n}조({ARTICLES.get(n, '')})" if ARTICLES.get(n) else f"제{n}조",
                          species="인사규정", section=chapter[n][0], section_name=chapter[n][1], article_num=n)
            for n in articles if n in chapter]


def sources(articles: list[int], hr_chunks: list[dict]) -> list[SourceItem]:
    """근거 조항 패널 — 코드가 쓴 조항 원문(조마다 청크를 잇는다). 검색 점수가 없으므로 score는 1"""
    out = []
    for n in articles:
        rows = sorted((c for c in hr_chunks if c.get("section") == "본칙" and c.get("article_num") == n),
                      key=lambda c: c.get("chunk_index") or 0)
        if not rows:
            continue
        c = rows[0]
        out.append(SourceItem(graph_key=graph_key(c), species="인사규정", section=c["section"], section_name=c.get("section_name"),
                              article_num=n, article_title=c.get("article_title"), coverage_type=None, score=1.0,
                              content="\n".join(r["content"] for r in rows)))
    return out


def profile(f: Facts, today: date) -> dict:
    """사내규정 본인 정보 블록(EmployeeProfile) — 답과 같은 계산을 쓴다. 급여·평균임금·수당 금액·평가는 넣지 않는다"""
    days, excluded = tenure_days(f, today)
    start = f.hire_date + timedelta(days=excluded)        # 뺀 휴직만큼 입사일을 미룬 날부터 센다
    years, months = _years(start, today), _months(start, today) % 12
    regular = f.employment_type == "정규직"
    a = annual_leave(f, today) if regular else None
    p = promotion(f, today) if regular else None
    probation = None
    if regular and not f.career_hire:
        end = _add_months(f.hire_date, 3) - timedelta(days=1)
        probation = end if end >= today else None
    sixty = _add_years(f.birth_date, 60)
    retire = _add_months(date(sixty.year, sixty.month, 1), 1) - timedelta(days=1)
    return dict(employee_id=f.employee_id, name=f.name, team=f.team, grade=f.grade, employment_type=f.employment_type,
                hire_date=f.hire_date, tenure_years=years, tenure_months=months, tenure_excluded_days=excluded,
                leave_start=a and a["start"], leave_end=a and a["end"], leave_total=a and a["grant"],
                leave_used=a and a["used"], leave_left=a and a["left"],
                certificates=[dict(name=n, acquired_on=acq, submitted=sub is not None) for n, acq, sub in
                              sorted(f.certificates, key=lambda c: c[1])],
                next_grade=p and p["next"], promotion_eligible_on=p and p.get("eligible"),
                probation_end=probation, retirement_on=retire)


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1) if d.day == 1 else _clamp(d.year + m // 12, m % 12 + 1, d.day)


def _clamp(y: int, m: int, day: int) -> date:
    import calendar
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))
