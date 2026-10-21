"""
payout.py
계산 카드(09번 2-3절) — 치료비가 들어간 질문이면 limit_table로 예상 지급액을 낸다. 모델은 계산에 손대지 않는다.

- 금액: 'N원'(23만원, 3만 5천원, 230,000원)과 '30만'. 자기부담금·한도·보험료 바로 뒤의 금액은 치료비가 아니라 건너뛴다.
  총액·일수(횟수)·날짜별 금액·수술한 날 금액을 읽는다(dayparse, read_costs).
- 특약: 고른 쪽(되묻기) → 질문의 '통원'/'입원'에 맞는 가입 특약 → 상위 검색 결과 중 가입한 의료비 특약 →
  가입한 의료비 특약이 모두 같은 (유형, 등급)이면 그것. 정할 수 없으면 카드를 내지 않는다.
- 계산은 하루 단위(daycalc): 날마다 자기부담금을 빼고 보상비율을 곱해 그날 한도(수술한 날·MRI 날·그 밖의 날)까지,
  합계에 연간 남은 한도(청구 이력으로 올해 받은 보험금을 뺀 것). Ⅲ MRI가 올해 몇 번째인지도 청구 이력으로 센다.
  날짜별 금액을 모르면 범위(최소~최대)와 고르게 나뉘었다면의 추정. 일수를 모르면 하루로 계산하고 그렇다고 적는다.
- 자기부담금은 가입 정보(policies.copay)다. 없으면 카드를 내지 않는다(3만/5만 중 어느 쪽인지 모른다).

민사소송법률비용 — legal_estimate(question): 질문 속 소송 금액(소송목적의 값)으로 【별표3】 변호사비용 한도·【별표4】 인지액,
심급·사건 종류가 있으면 【별표5】 송달료까지 낸다(limit_table). 소송 금액 없이 심급만 말하면 송달료만.
legal_card(question, pet): 민사소송법률비용 특약 가입자에게만 법률비용 카드(LegalCalc).
limit_card(question, pet, chosen): 치료비 금액 없이 한도를 물으면 가입한 의료비 특약의 한도표(LimitsCalc).
답변 흐름의 순서는 법률비용 → 의료비(금액 있음) → 한도. 의료비 카드가 뜨면 답도 카드 값으로 코드가 만든다(question_turn·reply_turn) —
모델은 치료비를 받아 계산하는 답을 못 했다. 법률비용·한도 카드는 카드만 붙이고 답변은 모델이 쓴다.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from data.limit_table import LEGAL_COST, get_limit, lawyer_fee_bracket, lawyer_fee_limit, service_fee, stamp_fee
from data.rag_context import infer_type_from_section_name
from data.search_scope import MEDICAL_SECTIONS, mentioned_grade, mentioned_type

from app.schemas import DayInput, DayRow, DaysAskCalc, LegalCalc, LimitRow, LimitsCalc, MedicalCalc, Pet, ReferenceItem
from app.services import daycalc, dayparse, intent

_UNIT = {"억": 10 ** 8, "천만": 10 ** 7, "백만": 10 ** 6, "만": 10 ** 4, "천": 10 ** 3, "백": 100}
_NUM = r"\d[\d,]*(?:\.\d+)?"
_UNIT_RE = "|".join(sorted(_UNIT, key=len, reverse=True))
_AMOUNT = re.compile(rf"((?:{_NUM}\s*(?:{_UNIT_RE})\s*)*(?:{_NUM}\s*(?:{_UNIT_RE})?)?)\s*원")
_PART = re.compile(rf"({_NUM})\s*({_UNIT_RE})?")
_NOT_COST = re.compile(r"(자기\s*부담금?|한도|보험료|공제)\s*(은|는|이|가|을|를|도|로)?\s*$")
_COST_WORD = re.compile(r"치료비|진료비|병원비|수술비|검사비|입원비|통원비|의료비|청구|나왔|나오|들었|냈")
_NO_SURGERY = re.compile(r"수술\s*(을|은)?\s*(안|하지\s*않|없이|없는)|비수술")
_MRI = re.compile(r"MRI|CT|내시경|엠알아이", re.I)
KST = ZoneInfo("Asia/Seoul")
_SECOND = re.compile(r"두\s*번째|2\s*번째|두\s*번|2\s*회|이번이\s*두|또\s*찍")

def treatment_cost(question: str) -> int | None:
    """질문 속 치료비(원). 치료비를 말하는 낱말이 없거나 금액이 없으면 None"""
    if not _COST_WORD.search(question):
        return None
    for m in _AMOUNT.finditer(question):
        if not re.search(r"\d", m.group(1)) or _NOT_COST.search(question[:m.start()]):
            continue
        total = 0.0
        for num, unit in _PART.findall(m.group(1)):
            total += float(num.replace(",", "")) * _UNIT.get(unit, 1)
        if total >= 1000:
            return int(total)
    return None


def _section(question: str, pet: Pet, results: list[dict], chosen: str | None) -> str | None:
    medical = {p.section_name: p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species]}
    if chosen in medical:
        return chosen
    said = [w for w in ("통원", "입원") if w in question]
    if len(said) == 1 and not any(said[0] in name for name in medical):
        return None              # 가입하지 않은 쪽을 물었다 — 다른 특약으로 계산하면 틀린 금액이다(4f: 모모 통원→입원 카드)
    for word in ("통원", "입원"):
        hits = [name for name in medical if word in name]
        if word in question and len(hits) == 1:
            return hits[0]
    for r in results:
        if r.get("section_name") in medical:
            return r["section_name"]
    combos = {(p.type, p.coverage_type) for p in medical.values()}
    return next(iter(medical)) if len(combos) == 1 else None


@dataclass
class Costs:
    """문장에서 읽은 치료비 — 총액·일수·날짜별 금액(다 알면 per_day)·금액을 아는 일부 날(fixed, 수술한 날 등)"""
    total: int | None = None
    n: int | None = None                       # 일수(통원 횟수). 못 읽으면 None
    unit: str | None = None                    # "일" / "번"
    per_day: list[daycalc.DayIn] | None = None
    fixed: list[daycalc.DayIn] = field(default_factory=list)
    surgery: bool = False                      # 수술했다(어느 날인지는 모를 수 있다)
    mri: bool = False
    same_day: bool = False                     # "같은 날 두 번" — 하루로 셌다


def read_costs(text: str) -> Costs:
    """총액·일수·날짜별 금액을 읽는다(dayparse). '총·합계' 뒤 금액이 총액, 나머지는 금액을 아는 날.
    총액 표시 없이 금액이 둘 이상이면 날짜별 금액 — 다만 일수와 개수가 다르고 수술·MRI 표시 없는 금액이 하나면 그것이 총액
    ("3일 입원 70만원, 수술한 날 40만원")"""
    r = dayparse.read(text)
    c = Costs(n=r.days, unit=r.unit, surgery=r.surgery, mri=r.mri, same_day=r.same_day)
    day = lambda a: daycalc.DayIn(a.value, a.surgery, a.mri)
    am = r.amounts
    totals = [a for a in am if a.total]
    if totals:
        c.total = totals[0].value
        rest = [day(a) for a in am if a is not totals[0]]
        if rest and c.n and len(rest) == c.n:
            c.per_day = rest
        else:
            c.fixed = rest
    elif len(am) == 1:
        c.total = am[0].value
    elif len(am) >= 2:
        plain = [a for a in am if not a.surgery and not a.mri]
        if c.n and len(am) != c.n and len(plain) == 1:
            c.total = plain[0].value
            c.fixed = [day(a) for a in am if a is not plain[0]]
        else:
            c.per_day = [day(a) for a in am]
    return c


def today() -> date:
    return datetime.now(KST).date()


def policy_year_start(contract: date, on: date) -> date:
    """보험연도 시작일 — 가입일의 계약해당일 중 on 이전의 가장 늦은 날(약관 【보험연도】: 계약해당일부터 차년도 계약해당일 전일까지)"""
    def anniv(year: int) -> date:
        try:
            return contract.replace(year=year)
        except ValueError:                       # 2월 29일 가입 — 평년은 2월 28일
            return date(year, 2, 28)
    start = anniv(on.year)
    return start if start <= on else anniv(on.year - 1)


def annual_usage(pet: Pet, policy, annual_total: int, on: date) -> daycalc.Annual:
    """올해(보험연도) 이 특약으로 받은 보험금·MRI 날 수 — 청구 이력(insurance_core.claims)에서 센다"""
    contract = getattr(policy, "contract_date", None)
    if contract is None:
        return daycalc.Annual(total=annual_total, used=0, year_start=None)
    start = policy_year_start(contract, on)
    claims = [c for c in getattr(pet, "claims", None) or []
              if c.section_name == policy.section_name and start <= c.treatment_date <= on]
    return daycalc.Annual(total=annual_total, used=sum(c.paid for c in claims), year_start=start.isoformat(),
                          claims=len(claims), mri_before=sum(1 for c in claims if c.mri))


MAX_FORM_DAYS = 5          # 날짜별 금액 입력칸을 띄우는 최대 일수 — 6일 이상은 칸 대신 범위 + 쉼표로 이어 보내기


def _unit_word(setting: str) -> str:
    return "일" if setting == "입원" else "번"


def medical_card(text: str, pet: Pet | None, results: list[dict], chosen: str | None, c: Costs, *,
                 section: str | None = None, allow_ask: bool = False, flow: str = "question",
                 on: date | None = None) -> MedicalCalc | DaysAskCalc | None:
    """의료비 카드 — 날마다 계산하고 합계에 연간 남은 한도. 날짜별 금액을 알면 정확한 값, 총액과 일수만 알면
    allow_ask(되묻기 흐름)이고 2~5일이면 날짜별 금액 입력 카드(DaysAskCalc), 아니면 범위. 일수를 모르면 하루로 보고 그렇다고 적는다"""
    if pet is None:
        return None
    name = section if section in {p.section_name for p in pet.policies} else _section(text, pet, results, chosen)
    if name is None:
        return None
    policy = next(p for p in pet.policies if p.section_name == name)
    if policy.coverage_type is None or policy.copay is None:
        return None
    type_ = infer_type_from_section_name(name)
    lim = daycalc.DayLimits.of(policy.coverage_type, type_, policy.copay)
    ann = annual_usage(pet, policy, lim.annual_total, on or today())
    # Ⅲ MRI 회차는 청구 이력으로 센다. 상담원이 "두 번째"라고 하면(아직 청구 안 한 MRI) 그 말도 따른다
    mri_before = max(ann.mri_before, 1 if _SECOND.search(text) and _MRI.search(text) else 0)
    setting = "입원" if "입원" in name else "통원"
    unit = _unit_word(setting)
    notes: list[str] = []
    common = dict(section_name=name, coverage_type=policy.coverage_type, copay=policy.copay, rate_pct=lim.pct,
                  setting=setting, annual_total=lim.annual_total, annual_used=ann.used, annual_remaining=ann.remaining,
                  year_start=ann.year_start, mri_before=mri_before if type_ == "Ⅲ" else None, flow=flow)
    note = (f"날마다 자기부담금 {policy.copay:,}원을 빼고 보상비율 {lim.pct}%를 곱해 그날 한도까지 · 합계는 연간 남은 한도까지. "
            "실제 지급액은 보험금 심사로 정해진다")

    def exact_card(days: list[daycalc.DayIn], n_known: bool = True) -> MedicalCalc:
        rows = daycalc.exact(days, lim, mri_before)
        mri_days = [r for r in rows if r.mri and not r.surgery]
        if type_ == "Ⅲ" and mri_days:
            notes.append(_mri_note(mri_before + 1, lim))
        raw = sum(r.payout for r in rows)
        paid = ann.cap(raw)
        return MedicalCalc(**common, claimed=sum(d.cost for d in days),
                           limit=rows[0].limit if len(rows) == 1 else lim.non_surgery, payout=paid, note=note,
                           days=len(rows), days_known=n_known, exact=True, capped=paid < raw,
                           day_rows=[DayRow(**vars(r)) for r in rows] if len(rows) > 1 else [], assumptions=notes)

    if c.same_day:
        notes.append("같은 날 여러 번 통원한 것은 하루로 계산했습니다(약관 단위가 1일당입니다).")
    if c.per_day:
        days = c.per_day
        if c.n and c.n != len(days):
            notes.append(f"앞서 말씀하신 {c.n}{unit}과 날짜별 금액 개수({len(days)}개)가 달라 날짜별 금액으로 계산했습니다.")
        if c.total and c.total != sum(d.cost for d in days):
            notes.append(f"앞서 말씀하신 총액 {_won(c.total)}과 날짜별 합계 {_won(sum(d.cost for d in days))}이 달라 "
                         "날짜별 금액으로 계산했습니다.")
        return exact_card(days)
    if c.total is None:
        return None
    n = c.n
    if n is None:
        notes.append(f"{'입원 일수' if setting == '입원' else '통원 횟수'}를 말씀하지 않아 하루 치료비로 계산했습니다. "
                     f"여러 {'날' if setting == '입원' else '번'}이면 금액이 달라지니 '3{unit} 총 70만원'처럼 알려 주세요.")
        return exact_card([daycalc.DayIn(c.total, c.surgery, c.mri)], n_known=False)
    if c.unit == "번" and n >= 2:
        notes.append(f"통원 {n}번은 서로 다른 {n}일로 보고 계산했습니다(같은 날 두 번 간 것은 하루로 칩니다).")
    if n == 1:
        return exact_card([daycalc.DayIn(c.total, c.surgery, c.mri)])
    fixed = c.fixed
    rest_n, rest_total = n - len(fixed), c.total - sum(d.cost for d in fixed)
    if rest_n < 1 or rest_total < 0:              # 금액을 아는 날이 일수·총액과 안 맞는다 — 총액과 일수만 쓴다
        fixed, rest_n, rest_total = [], n, c.total
    surgery_unknown = c.surgery and not any(d.surgery for d in fixed)
    mri_unknown = type_ == "Ⅲ" and c.mri and not any(d.mri for d in fixed)
    if rest_n == 1:                               # 하루만 모르면 총액에서 뺀 값이 그날 금액이다
        return exact_card([*fixed, daycalc.DayIn(rest_total, surgery_unknown, mri_unknown)])
    if allow_ask and n <= MAX_FORM_DAYS:
        return DaysAskCalc(section_name=name, coverage_type=policy.coverage_type, setting=setting, days=n, total=c.total,
                           type=type_, surgery_mentioned=surgery_unknown,
                           prefill=[DayInput(cost=d.cost, surgery=d.surgery, mri=d.mri) for d in fixed]
                           + [DayInput() for _ in range(rest_n)],
                           note="진료비 세부내역서에 일자별로 나와 있습니다")
    # 범위 — 금액을 모르는 날 중 수술한 날·MRI 날(말했으면)은 그날 한도로 둔다
    template = ([daycalc.DayIn(0, surgery=True)] if surgery_unknown else []) + ([daycalc.DayIn(0, mri=True)] if mri_unknown else [])
    template = (template + [daycalc.DayIn(0)] * rest_n)[:rest_n]
    fixed_rows = daycalc.exact(fixed, lim, mri_before)
    seen = mri_before + sum(1 for d in fixed if d.mri and not d.surgery)
    limits = [r.limit for r in daycalc.exact(template, lim, seen)]
    lo, hi = daycalc.bounds(rest_total, limits, policy.copay, lim.pct)
    known = sum(r.payout for r in fixed_rows)
    even_raw = known + daycalc.even_value(rest_total, limits, policy.copay, lim.pct)
    notes.append(f"범위는 날마다 치료비가 {_won(daycalc.DAY_FLOOR)} 이상이라고 보고 계산했습니다.")
    if surgery_unknown:
        notes.append("수술한 날 금액을 몰라 하루를 수술한 날 한도로 두고 계산했습니다.")
    if mri_unknown:
        notes.append(_mri_note(seen + 1, lim))
    return MedicalCalc(**common, claimed=c.total, limit=lim.non_surgery, payout=ann.cap(even_raw), note=note, days=n,
                       exact=False, range_min=ann.cap(known + lo), range_max=ann.cap(known + hi), even=ann.cap(even_raw),
                       capped=ann.cap(known + hi) < known + hi, day_rows=[DayRow(**vars(r)) for r in fixed_rows],
                       assumptions=notes)


def _mri_note(nth: int, lim: daycalc.DayLimits) -> str:
    """Ⅲ MRI 날의 회차 — 청구 이력으로 센 값을 답에 밝힌다(한도가 100만원/30만원처럼 크게 갈린다)"""
    before = nth - 1
    if before == 0:
        return f"청구 이력상 올해 MRI·CT·내시경은 이번이 첫 번째라 그날 한도는 {_won(lim.mri_1st)}입니다."
    return (f"청구 이력상 올해 이미 MRI·CT·내시경을 {before}번 받아 이번은 {nth}번째라 그날 한도는 {_won(lim.mri_2nd)}입니다"
            f"(첫 번째는 {_won(lim.mri_1st)}).")


def _question_costs(question: str) -> Costs | None:
    """단독 질문의 치료비 — 치료비 낱말과 금액이 있어야 한다(treatment_cost). 일수·날짜별 금액도 읽는다"""
    if treatment_cost(question) is None:
        return None
    c = read_costs(question)
    if c.total is None and not c.per_day:
        c.total = treatment_cost(question)
    return c


def estimate(question: str, pet: Pet | None, results: list[dict], chosen: str | None = None,
             on: date | None = None) -> MedicalCalc | None:
    """단독 질문의 의료비 카드만(입력 카드로 되묻지 않는다). 업무특화(가입 정보가 있을 때)만 — 일반·사내규정은 pet이 None"""
    c = _question_costs(question) if pet is not None else None
    card = medical_card(question, pet, results, chosen, c, on=on) if c else None
    return card if isinstance(card, MedicalCalc) else None


def question_turn(question: str, pet: Pet | None, results: list[dict], chosen: str | None = None,
                  on: date | None = None) -> tuple[MedicalCalc | DaysAskCalc, str] | None:
    """치료비가 든 단독 질문 — 의료비 카드가 뜨면 답도 카드 값으로 코드가 만든다(2026-10-21: 카드는 맞는데 모델이 거절했다,
    검증 R2·R26·R29). 되묻기 뒤 턴(reply_turn)과 같다 — 2~5일 총액이면 날짜별 입력 카드, 6일 이상은 범위.
    flow="ask"라 다음 턴의 일수·날짜별 금액을 이어 받는다. 카드가 안 뜨면 None(모델이 답한다)"""
    c = _question_costs(question) if pet is not None else None
    card = medical_card(question, pet, results, chosen, c, allow_ask=True, flow="ask", on=on) if c else None
    if card is None:
        return None
    if isinstance(card, DaysAskCalc):
        return card, days_ask_answer(card)
    return card, amount_answer(card, pet, question, hint=not card.exact and card.days > MAX_FORM_DAYS)


# ===== 민사소송법률비용 — 별표3·4·5 =====
_CLAIM_WORD = re.compile(r"소송\s*(?:금액|가액|목적의?\s*값)|소가|청구\s*(?:금액|액)|소송\s*걸|소송을?\s*(?:하|제기|낸|내)")
_INSTANCE = (("상고심", re.compile(r"상고|대법원|3심")), ("항소심", re.compile(r"항소|2심")), ("1심", re.compile(r"1심|일심|첫\s*재판")))
_CASE_KIND = (("민사소액", re.compile(r"소액")), ("민사합의", re.compile(r"합의부|민사\s*합의")), ("민사단독", re.compile(r"단독")))


@dataclass
class LegalEstimate:
    claim_value: int | None       # 질문 속 소송 금액(소송목적의 값) — 심급만 말했으면 None
    lawyer_limit: int | None      # 【별표3】 소송비용에 산입되는 변호사비용(보험금은 실제 보수 - 자기부담금 10만원, 이 값까지)
    stamp: int | None             # 【별표4】 인지액
    instance: str | None          # 1심/항소심/상고심 — 질문에 없으면 None
    case_kind: str | None         # 민사소액/민사단독/민사합의(1심만)
    service: int | None           # 【별표5】 송달료 — 심급(1심이면 사건 종류까지)을 알 때만


def amounts_in(text: str) -> list[int]:
    """문장 속 'N원' 금액들(원). treatment_cost와 같은 단위 해석"""
    out = []
    for m in _AMOUNT.finditer(text):
        if not re.search(r"\d", m.group(1)):
            continue
        total = sum(float(num.replace(",", "")) * _UNIT.get(unit, 1) for num, unit in _PART.findall(m.group(1)))
        if total >= 1000:
            out.append(int(total))
    return out


def legal_estimate(question: str) -> LegalEstimate | None:
    """소송 금액을 말한 질문이면 별표3·4(·5) 값. 소송 금액 없이 심급(1심이면 사건 종류까지)만 말했으면 송달료만.
    둘 다 아니면 None. 변호사 보수 금액만 말한 질문("변호사비 300만원 냈는데")을 소송목적의 값으로 오인하지 않게,
    금액은 소송 금액 낱말 뒤 첫 금액만 쓴다"""
    m = _CLAIM_WORD.search(question)
    amounts = amounts_in(question[m.start():]) if m else []
    instance = next((name for name, pat in _INSTANCE if pat.search(question)), None)
    kind = next((name for name, pat in _CASE_KIND if pat.search(question)), None) if instance in (None, "1심") else None
    service = None
    if instance in ("항소심", "상고심"):
        service = service_fee(instance)
    elif instance == "1심" and kind:
        service = service_fee("1심", kind)
    if amounts:
        value = amounts[0]
        return LegalEstimate(claim_value=value, lawyer_limit=lawyer_fee_limit(value), stamp=stamp_fee(value),
                             instance=instance, case_kind=kind, service=service)
    if service is not None:
        return LegalEstimate(claim_value=None, lawyer_limit=None, stamp=None, instance=instance, case_kind=kind, service=service)
    return None


LEGAL_SECTION_WORD = "민사소송법률비용"


def _man(n: int) -> str:
    """구간 표시용 금액 — 1억 이상은 억, 그 아래는 만원(별표3 원문 표기)"""
    eok, rest = divmod(n, 10 ** 8)
    man = rest // 10 ** 4
    if eok and man:
        return f"{eok}억 {man:,}만원"
    return f"{eok}억원" if eok else f"{man:,}만원"


def bracket_text(claim_value: int) -> str:
    """【별표3】 적용 구간 — "2,000만원 초과 5,000만원까지 · 200만원 + 초과분 × 8%" """
    low, high, base, permille = lawyer_fee_bracket(claim_value)
    if permille == 0:
        return f"{_man(high)}까지 · 정액 {_man(base)}"
    rng = f"{_man(low)} 초과 {_man(high)}까지" if high is not None else f"{_man(low)} 초과"
    return f"{rng} · {_man(base)} + 초과분 × {permille / 10:g}%"


def legal_card(question: str, pet: Pet | None) -> LegalCalc | None:
    """법률비용 계산 카드 — 반려동물이 민사소송법률비용 특약에 가입했고 legal_estimate가 값을 낼 때만"""
    if pet is None:
        return None
    name = next((p.section_name for p in pet.policies if LEGAL_SECTION_WORD in p.section_name), None)
    if name is None:
        return None
    e = legal_estimate(question)
    if e is None:
        return None
    lawyer_max = None if e.lawyer_limit is None else min(e.lawyer_limit, LEGAL_COST["lawyer_limit"])
    note = ("심급별로 실제 부담한 금액을 한도 안에서 지급한다 · 변호사 보수는 실제 보수에서 자기부담금을 뺀 금액. "
            "실제 지급액은 보험금 심사로 정해진다")
    return LegalCalc(section_name=name, claim_value=e.claim_value,
                     bracket=None if e.claim_value is None else bracket_text(e.claim_value),
                     lawyer_limit=e.lawyer_limit, lawyer_max=lawyer_max, lawyer_copay=LEGAL_COST["lawyer_copay"],
                     lawyer_cap=LEGAL_COST["lawyer_limit"], stamp=e.stamp, instance=e.instance, case_kind=e.case_kind,
                     service=e.service, stamp_service_cap=LEGAL_COST["stamp_service_limit"], note=note)


# ===== 한도 카드 — 금액 없이 한도만 물을 때 =====
# "보장 얼마나 돼요?"도 한도를 묻는 것 — 사고 뒤 받을 금액이 아니다(평가 R070 "MRI 찍으면 보장 얼마나 돼요?"가 금액 되묻기에 걸렸다)
_LIMIT_WORD = re.compile(r"한도|얼마까지|최대\s*(?:얼마|로|금액)|최고\s*얼마|보장\s*(?:은|이|금액)?\s*얼마")
_NOT_MEDICAL = re.compile(r"소송|변호사|인지액|송달료|배상|법률|피해자|합의|약정")   # 법률비용·배상책임 질문 — 의료비 한도표가 아니다
# 치료비·보험금이 아닌 돈 이야기 — 한도 카드와 금액 되묻기에서 뺀다("중도인출 하면 얼마까지 돼요?"에 의료비 한도 카드가 떴다)
# 올해 받은·남은 보험금을 묻는다 — 치료비를 되물을 질문이 아니다(4f: "올해 얼마 더 받을 수 있어요?"에 되묻기가 걸렸다)
ANNUAL_ASK = re.compile(r"(?:올해|이번\s*해|올\s*한\s*해|금년).*(?:받았|받은|더\s*받|남은|남았|남아|사용|썼)")
OTHER_MONEY = re.compile(r"보험료|환급|자기\s*부담|가입\s*금액|연체|이자|위약|해지|해약|공제|중도\s*인출|대출|적립")


def limit_card(question: str, pet: Pet | None, chosen: str | None = None) -> LimitsCalc | None:
    """한도표 카드. 한도 낱말이 있고 치료비 금액·법률 낱말이 없을 때, 가입한 의료비 특약(되묻기로 고른 쪽이 있으면 그것,
    질문에 '통원'/'입원'이 있으면 그쪽, 질문이 등급·유형을 말하면 그에 맞는 쪽)만. 맞는 가입 특약이 없으면 None"""
    if (pet is None or not _LIMIT_WORD.search(question) or _NOT_MEDICAL.search(question) or OTHER_MONEY.search(question)
            or treatment_cost(question) is not None):
        return None
    medical = [p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type]
    if chosen:
        medical = [p for p in medical if p.section_name == chosen]
    else:
        for word in ("통원", "입원"):
            if word in question:
                medical = [p for p in medical if word in p.section_name]   # 가입하지 않은 쪽이면 카드 없음(4f: 두부 입원)
    # 질문이 등급·유형을 말하면 그에 맞는 가입 특약만 — 맞는 것이 없으면(가입과 다른 등급) 이 고객의 한도가 아니라 내지 않는다
    grade, type_ = mentioned_grade(question), mentioned_type(question)
    if grade:
        medical = [p for p in medical if p.coverage_type == grade]
    if type_:
        medical = [p for p in medical if infer_type_from_section_name(p.section_name) == type_]
    if not medical:
        return None
    rows = []
    for p in medical:
        t = infer_type_from_section_name(p.section_name)
        base = get_limit(p.coverage_type, t, "non_surgery_no_mri" if t == "Ⅲ" else "non_surgery")
        rows.append(LimitRow(section_name=p.section_name, coverage_type=p.coverage_type, type=t, copay=p.copay,
                             rate_pct=round(base["rate"] * 100), non_surgery=base["limit"],
                             surgery=get_limit(p.coverage_type, t, "surgery")["limit"],
                             mri_1st=get_limit(p.coverage_type, t, "non_surgery_mri_1st")["limit"] if t == "Ⅲ" else None,
                             mri_2nd_plus=get_limit(p.coverage_type, t, "non_surgery_mri_2nd_plus")["limit"] if t == "Ⅲ" else None,
                             annual_total=base["annual_total"]))
    if _MRI.search(question):
        highlight = "mri"
    elif "수술" in question:
        highlight = "non_surgery" if _NO_SURGERY.search(question) else "surgery"
    else:
        highlight = None
    note = ("1일 한도는 그날 치료비에서 자기부담금을 빼고 보상비율을 곱한 금액에 적용한다. 연간 총 한도는 특약마다 따로다. "
            "실제 지급액은 보험금 심사로 정해진다")
    return LimitsCalc(pet_name=pet.name, rows=rows, highlight=highlight, note=note)


# ===== 금액 되묻기 — 보험금이 얼마냐고 묻는데 치료비 금액이 없을 때 =====
# 다섯 조건(2026-10-21). ①은 금액 낱말 + 임베딩(intent.py) — 아래 _ASK_MONEY는 임베딩을 못 쓸 때의 규칙:
# ① 금액을 묻는다 ② 치료비 금액이 없다 ③ 한도·얼마까지·최대가 없다(→ 한도 카드) ④ 소송·변호사·배상이 없다(→ 법률비용)
# ⑤ 보험료·환급·해지·중도인출 같은 다른 돈 이야기가 아니다. 그리고 의료비 특약에 가입한 반려동물이어야 한다
_ASK_MONEY = re.compile(r"얼마(?:나|를|가)?\s*(?:나오|나와|받|지급|보상|줘|주나|줍|돼|될)|보험금\s*(?:은|이)?\s*얼마|몇\s*만\s*원")
# 되묻기 문장 — 앞 질문이 입원인지 통원인지에 따라. 약관 단위가 하루라 총액과 함께 일수(횟수)를 받는다(2026-10-21)
ASK_TEXTS = {
    "입원": "치료비 총액과 입원 일수를 알려 주세요. 수술한 날이 있으면 그날 치료비도요.",
    "통원": "치료비 총액과 통원 횟수를 알려 주세요. 수술한 날이 있으면 그날 치료비도요.",
    None: "치료비 총액과 입원 일수(통원이면 횟수)를 알려 주세요. 수술한 날이 있으면 그날 치료비도요.",
}
ASK_AMOUNT_TEXT = "치료비가 얼마인가요? 동물병원 영수증 금액을 알려 주시면 예상 보험금을 계산해 드립니다."   # 10-21 이전 턴
# 총액 없이 일수나 '모르겠어요'만 답했을 때 — 이것도 되묻기라 다음 턴의 금액을 이어 받는다
NEED_COST_TEXT = "치료비 총액을 알아야 예상 보험금을 계산할 수 있습니다. 동물병원 영수증이나 진료비 세부내역서의 합계를 알려 주세요."
ASKS = frozenset([*ASK_TEXTS.values(), ASK_AMOUNT_TEXT, NEED_COST_TEXT])


def ask_setting(text: str, pet: Pet | None, chosen: str | None) -> str | None:
    """되묻기 문장을 고를 입원/통원 — 고른 특약 → 질문 낱말 → 가입한 의료비 특약이 한쪽뿐이면 그쪽. 모르면 None"""
    if chosen:
        return "입원" if "입원" in chosen else "통원"
    for word in ("입원", "통원"):
        if word in text:
            return word
    if pet is None:
        return None
    settings = {"입원" if "입원" in p.section_name else "통원" for p in pet.policies
                if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type}
    return settings.pop() if len(settings) == 1 else None


def ask_text(text: str, pet: Pet | None, chosen: str | None) -> str:
    return ASK_TEXTS[ask_setting(text, pet, chosen)]


def needs_amount(question: str, pet: Pet | None, embed: "intent.Embed | None" = None) -> bool:
    """보험금 금액을 묻는데 치료비 금액이 없다 — 모델은 계산할 수 없어 거절한다. 되물어 다음 턴(멀티턴)에 금액을 받는다.
    ① '받을 금액을 묻는가'는 금액 낱말 + 임베딩(intent.asks_amount, embed = Retriever.embed). embed가 없거나 실패하면 규칙.
    ②~⑤(치료비 금액·한도·법률·다른 돈)는 다른 카드로 보내는 갈림길이라 규칙 그대로"""
    if pet is None or not any(p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type for p in pet.policies):
        return False
    if (treatment_cost(question) is not None or _LIMIT_WORD.search(question) or _NOT_MEDICAL.search(question)
            or OTHER_MONEY.search(question) or ANNUAL_ASK.search(question)):
        return False
    asks = intent.asks_amount(question, embed)
    return bool(_ASK_MONEY.search(question)) if asks is None else asks



# ===== 금액 되묻기 직후 턴 — 모델 대신 카드 값으로 답 문장 =====
# 업무특화 모델은 치료비를 받아 보험금을 계산하는 답을 못 한다 — 질문을 어떻게 넘기든, 계산 결과를 발췌·질문에 넣든
# 약관 예시(33만원 → 21만원)를 옮기거나 거절했다(2026-10-21, 다섯 사례 × 일곱 안 × 10회 — data/review/amount_turn_20261021.md).
# 그래서 이 턴은 카드와 같은 계산 결과로 코드가 답한다 — 화면의 카드와 답 숫자가 어긋날 수 없다.
COVERAGE_NOTE = "보장 여부는 약관 조건에 따라 달라집니다."   # 면책(선천성·미용 등)은 판단하지 않으니 늘 붙인다


def _won(n: int) -> str:
    """금액을 말로 — 35만원 · 22만 4,000원 · 4,900원"""
    man, rest = divmod(n, 10_000)
    if man and rest:
        return f"{man:,}만 {rest:,}원"
    return f"{man:,}만원" if man else f"{rest:,}원"


def matched_exclusions(text: str, pet: Pet | None) -> list[str]:
    """질문(기준 질문 포함)에 걸리는 부담보 질병. 세 가지로 대조한다(공백 무시):
    ① 부담보 이름 그대로 또는 3글자 이상 낱말(예전 화면 규칙) ② 특정질병 분류표(별첨)에서 그 분류에 든 질병 이름
    ("비뇨기과질환" ← 방광염·요로 결석증, "뒷다리근골격계질환" ← 고관절 이형성증) ③ 같은 부위 다른 이름(SYNONYMS — 무릎뼈·슬관절 ↔ 슬개골).
    2026-10-21 기준선: 방광염·무릎·고관절 이형성증으로 물으면 배너가 안 떴다(부담보 0/9). 서버가 이 결과를 화면에 보낸다(ExclusionsMsg)"""
    if pet is None:
        return []
    flat = re.sub(r"\s+", "", text)
    conds = [c for p in pet.policies for c in p.excluded_conditions]
    table = disease_table(pet.species)
    out = []
    for c in dict.fromkeys(conds):
        key = re.sub(r"\s+", "", c)
        terms = {key} | {w for w in c.split() if len(w) >= 3}
        if key in table:                                   # 분류 이름 — 그 분류의 질병 이름 전부
            terms |= table[key]
        else:                                              # 질병 이름 — 같은 낱말이 든 분류표 질병 이름
            head = re.sub(r"\(.*?\)", "", c).split()[0]
            terms |= {t for names in table.values() for t in names if head in t}
        for word, alias in SYNONYMS.items():
            if word in key:
                terms |= set(alias)
        if any(t in flat for t in terms):
            out.append(c)
    return out


# 같은 부위의 다른 이름 — 분류표에 없는 일상어. 잘못 걸려도 배너(확인 안내)라 비용이 작다
SYNONYMS = {"슬개골": ("무릎뼈", "무릎", "슬관절"), "비뇨기": ("방광", "요로", "소변", "오줌")}
_TABLE_STOP = ("신생물", "기타", "원인불명", "불확실")
_TABLES: dict[str, dict[str, set[str]]] = {}


def disease_table(species: str) -> dict[str, set[str]]:
    """특정질병 분류표(별첨 청크) — 분류 이름(공백 없이) → 그 분류의 질병 이름(공백·괄호 없이, 3글자 이상, 신생물·기타 제외)"""
    if species in _TABLES:
        return _TABLES[species]
    import json
    from app import config
    path = config.CHUNKS_DIR / f"petmint_{species}.json"
    table: dict[str, set[str]] = {}
    if path.exists():
        for ch in json.loads(path.read_text(encoding="utf-8")):
            if ch.get("section") != "별첨":
                continue
            t = re.sub(r"\s+", " ", ch["content"])
            m = re.match(r"\s*(.+?)\s*\(관련 질병코드", t)
            if not m:
                continue
            names = re.findall(r"[A-Z]{3}\d{3}:\s*(.+?)(?=\s+-\s+[A-Z]{3}\d{3}:|$)", t)
            terms = set()
            for n in names:
                core = re.sub(r"\s+", "", re.sub(r"\(.*?\)", "", n))
                if len(core) >= 3 and not any(s in core for s in _TABLE_STOP):
                    terms.add(core)
            table[re.sub(r"\s+", "", m.group(1))] = terms
    _TABLES[species] = table
    return table


def _day_name(setting: str, i: int) -> str:
    return f"{i}일째" if setting == "입원" else f"{i}번째 통원"


def _tag(r: DayRow) -> str:
    return "(수술한 날)" if r.surgery else "(MRI 등)" if r.mri else ""


EXACT_NEEDS = "정확한 금액은 진료비 세부내역서의 날짜별 치료비가 있어야 계산됩니다."
LIST_HINT = "날짜별 치료비를 '30만, 30만, 10만…'처럼 쉼표로 이어 보내 주시면 정확히 계산합니다."


def amount_answer(card: MedicalCalc, pet: Pet, text: str, hint: bool = False) -> str:
    """코드가 답하는 턴의 답 — 카드와 같은 계산 결과로 쓴다(숫자가 어긋날 수 없다). 굵은 글씨는 예상 보험금(범위면 범위와
    고르게 나뉜 추정). 이어서 연간 한도, 계산에 둔 가정, 부담보, 보장 여부 단서. hint: 범위일 때 쉼표로 이어 보내기 안내"""
    setting = card.setting or ("입원" if "입원" in card.section_name else "통원")
    unit = _unit_word(setting)
    rate = card.rate_pct if card.rate_pct is not None else 70
    rem = card.annual_remaining
    lines = []
    if card.exact and card.days == 1:
        after_copay = max(card.claimed - card.copay, 0)
        base = after_copay * rate // 100
        day_paid = max(min(base, card.limit), 0)
        if card.claimed <= card.copay:
            body = (f"{setting} 치료비 {_won(card.claimed)}이 자기부담금 {_won(card.copay)} 이하라 "
                    f"예상 보험금은 **{_won(card.payout)}**입니다.")
        else:
            body = f"{setting} 치료비 {_won(card.claimed)}에서 자기부담금 {_won(card.copay)}을 뺀 {_won(after_copay)}의 {rate}%는 {_won(base)}입니다."
            reason = f"1일 지급 한도가 {_won(card.limit)}이라" if day_paid < base else f"1일 지급 한도({_won(card.limit)}) 안이라"
            if card.capped:
                body += (f" {reason} {_won(day_paid)}이지만, 올해 남은 연간 한도가 {_won(rem)}이라 "
                         f"예상 보험금은 **{_won(card.payout)}**입니다.")
            else:
                body += f" {reason} 예상 보험금은 **{_won(card.payout)}**입니다."
        lines.append(body)
    elif card.exact:
        lines.append(f"{setting} {card.days}{unit} 치료비를 날짜별로 계산했습니다.")
        for i, r in enumerate(card.day_rows, 1):
            limit = f" (그날 한도 {_won(r.limit)})" if r.payout == r.limit and r.payout > 0 else ""
            lines.append(f"- {_day_name(setting, i)} {_won(r.cost)}{_tag(r)} → {_won(r.payout)}{limit}")
        raw = sum(r.payout for r in card.day_rows)
        head = f"날마다 자기부담금 {_won(card.copay)}을 빼고 {rate}%를 곱해 그날 한도까지 더하면 "
        if card.capped:
            lines.append(head + f"{_won(raw)}이지만, 올해 남은 연간 한도가 {_won(rem)}이라 예상 보험금은 **{_won(card.payout)}**입니다.")
        else:
            lines.append(head + f"예상 보험금은 **{_won(card.payout)}**입니다.")
    else:
        rng = (f"**{_won(card.range_min)}**" if card.range_min == card.range_max
               else f"**{_won(card.range_min)} ~ {_won(card.range_max)}**")
        lines.append(f"날짜별 치료비를 몰라 정확한 금액은 계산할 수 없습니다. {setting} {card.days}{unit} 총 {_won(card.claimed)}이면 "
                     f"날짜별로 나뉜 금액에 따라 {rng}이고, 날마다 고르게 나뉘었다면 **{_won(card.even)}**입니다.")
        if card.day_rows:
            known = ", ".join(f"{_won(r.cost)}{_tag(r)} → {_won(r.payout)}" for r in card.day_rows)
            lines.append(f"금액을 아는 날은 그대로 계산했습니다({known}).")
        if card.capped:
            lines.append(f"올해 남은 연간 한도 {_won(rem)}까지로 줄인 금액입니다.")
        lines.append(EXACT_NEEDS + (" " + LIST_HINT if hint else ""))
    if card.annual_used and not card.capped:
        lines.append(f"올해 이미 받은 보험금 {_won(card.annual_used)}을 빼면 남은 연간 한도는 {_won(rem)}입니다.")
    lines += card.assumptions
    excl = matched_exclusions(text, pet)
    if excl:
        lines.append(f"다만 {pet.name}{'은' if _has_batchim(pet.name) else '는'} {', '.join(excl)}{'이' if _has_batchim(excl[-1]) else '가'} 부담보 대상이라 "
                     f"해당 치료는 보험금이 지급되지 않습니다.")
    lines.append(COVERAGE_NOTE)
    return "\n".join(lines)


def days_ask_answer(card: DaysAskCalc) -> str:
    """날짜별 금액 되묻기 턴의 답 — 화면은 이 아래 카드에 일수만큼 입력칸을 띄운다"""
    unit = _unit_word(card.setting)
    lines = [f"{card.setting} {card.days}{unit}, 총 {_won(card.total)}으로 받았습니다. 자기부담금과 한도가 하루 단위라 "
             "날짜별 치료비가 있어야 정확히 계산됩니다. 진료비 세부내역서에 일자별로 나와 있습니다."]
    known = [d for d in card.prefill if d.cost]
    if known:
        lines.append("말씀하신 " + ", ".join(f"{_won(d.cost)}{'(수술한 날)' if d.surgery else '(MRI 등)' if d.mri else ''}"
                                          for d in known) + "은 칸에 넣어 두었습니다.")
    lines.append("아래 칸에 날짜별 금액을 넣거나 '30만, 30만, 10만'처럼 보내 주세요. 모르면 [잘 모르겠어요]를 누르면 범위로 안내합니다.")
    return "\n".join(lines)


# ===== 되묻기에 답한 턴 — 앞 턴 상태(되묻기 문장·카드)로 어디까지 왔는지 본다 =====
def reply_stage(prior_answer: str, prior_payout: dict | None) -> str | None:
    """앞 턴이 코드가 무엇을 물은 턴인가 — ask: 금액 되묻기 / days: 날짜별 금액 입력 카드 /
    again: 코드가 답했지만 일수를 몰랐거나 범위였다(일수·날짜별 금액을 이어 받는다). 아니면 None"""
    if prior_answer in ASKS:
        return "ask"
    p = prior_payout or {}
    if p.get("kind") == "days_ask":
        return "days"
    if p.get("kind", "medical") == "medical" and p.get("flow") == "ask" and (not p.get("exact", True) or not p.get("days_known", True)):
        return "again"
    return None


def reply_turn(question: str, card_text: str, stage: str, prior_payout: dict | None, pet: Pet, results: list[dict],
               chosen: str | None, on: date | None = None) -> tuple[MedicalCalc | DaysAskCalc | None, str] | None:
    """되묻기에 답한 턴을 코드가 계산하고 답한다 — (카드, 답 문장). 계산할 수 없으면 None(모델이 답한다).
    금액은 이번 답에서만 읽는다(앞 질문의 금액은 이미 쓴 것). 일수·수술·MRI는 앞 질문까지(card_text) 본다"""
    whole = dayparse.read(card_text)
    if stage == "days":
        prior = DaysAskCalc.model_validate(prior_payout)
        r = dayparse.read(question)
        filled = [daycalc.DayIn(d.cost, d.surgery, d.mri) for d in prior.prefill if d.cost]
        if r.amounts:
            got = [daycalc.DayIn(a.value, a.surgery, a.mri) for a in r.amounts]
            days = [*filled, *got] if filled and len(got) == prior.days - len(filled) else got
            c = Costs(total=prior.total, n=prior.days, unit=_unit_word(prior.setting), per_day=days)
        elif r.unknown:
            c = Costs(total=prior.total, n=prior.days, unit=_unit_word(prior.setting), fixed=filled,
                      surgery=prior.surgery_mentioned or any(d.surgery for d in filled), mri=whole.mri)
        else:
            return None
        card = medical_card(card_text, pet, results, chosen, c, section=prior.section_name, flow="ask", on=on)
        return (card, amount_answer(card, pet, card_text)) if isinstance(card, MedicalCalc) else None

    c = read_costs(question)
    c.surgery = c.surgery or whole.surgery
    c.mri = c.mri or whole.mri
    section = None
    if c.n is None:                              # 일수는 앞 질문에 있을 수 있다("3일 입원했는데 얼마 나와요?")
        c.n, c.unit, c.same_day = dayparse.day_count(card_text)
    if stage == "again":
        prior = MedicalCalc.model_validate(prior_payout)
        section = chosen or prior.section_name
        if c.total is None and not c.per_day:     # "3일이요" — 일수만 더 말했다
            c.total = prior.claimed
        if c.n is None and prior.days_known and prior.days > 1:
            c.n, c.unit = prior.days, _unit_word(prior.setting or "")
        if c.per_day and c.total is None:
            c.total = prior.claimed
    if c.total is None and not c.per_day:
        return (None, NEED_COST_TEXT) if stage == "ask" else None
    card = medical_card(card_text, pet, results, chosen, c, section=section, allow_ask=True, flow="ask", on=on)
    if card is None:
        return None
    if isinstance(card, DaysAskCalc):
        return card, days_ask_answer(card)
    return card, amount_answer(card, pet, card_text, hint=not card.exact and card.days > MAX_FORM_DAYS)


def code_references(card, pet: Pet | None, text: str) -> list[ReferenceItem]:
    """코드가 쓴 답의 근거 조항(2026-10-21, 4c단계) — 계산의 근거인 그 특약 제1조(보험금의 지급사유: 1일 한도·자기부담금·보상비율 표).
    부담보에 걸리면 부담보 특약 제2조(특별면책조건의 내용). 모델 답처럼 글자 대조(used_references)로 찾을 수 없다 — 계산이 표에서 나왔다"""
    if pet is None or card is None or getattr(card, "kind", "medical") not in ("medical", "days_ask"):
        return []
    refs = [ReferenceItem(citation_label="제1조(보험금의 지급사유)", species=pet.species, section="특별약관",
                          section_name=card.section_name, article_num=1)]
    if matched_exclusions(text, pet):
        refs.append(ReferenceItem(citation_label="제2조(특별면책조건의 내용)", species=pet.species, section="특별약관",
                                  section_name=EXCLUSION_SECTION_NAME, article_num=2))
    return refs


EXCLUSION_SECTION_NAME = "반려동물 특정 질병 보장제한부 인수 특별약관"


def _has_batchim(word: str) -> bool:
    ch = word.strip()[-1]
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0
