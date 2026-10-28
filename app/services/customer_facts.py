"""
customer_facts.py
고객 고유 사실을 코드가 답에 넣는다(2026-10-21, rebuild5 준비 4d단계). 모델은 고객 정보를 받지 않는다(09번 5절 — 학습 형식이
2턴이라 넣으면 형식이 바뀐다). 그래서 기준선에서 이 변수들은 모두 실패했다: 미가입 0/21, 연간 잔여 0/9, 나이 0/9, 대기기간 6/15.

- not_enrolled: 가입하지 않은 특약을 물었다 — 모델 대신 코드가 "가입하지 않았다"고 답한다(그 특약 조항은 검색 범위에서 빠져 있다)
- annual_answer: 올해(보험연도) 받은 보험금·남은 연간 한도 — 청구 이력으로 코드가 답한다
- notes: 답 끝에 붙일 고객 사실 — 가입 30일 이내 질병, 반려견 1년 이내 슬관절·고관절 / 반려묘 90일 이내 비뇨기계질환·전염성복막염,
  반려동물 나이
- exclusion_answer · waiting_answer(2026-10-23 3안, PETMINT_COVERAGE_CODE): 보장 여부 질문에서 코드가 확실히 아는 부정 사실 —
  그 반려동물의 부담보에 걸린 질문, 대기기간 안의 질병 — 은 모델 대신 코드가 답한다. 모델은 부담보(고객 데이터)를 모르고
  90일 대기기간 조항과 섞어 "90일 지나면 된다"로 답했다(레오 비뇨기과질환). "보장됩니다"는 코드가 말하지 않는다(면책 사유를 모른다)
"""

import re
from datetime import date, timedelta

from data.rag_context import infer_type_from_section_name
from data.search_scope import MEDICAL_SECTIONS

from app.schemas import Pet
from app.services.lexicon import (DISEASE_NOTE as _DISEASE,
                                  INJURY_EXCLUDE as _INJURY_NOT,
                                  NO_NAME_FILLER as _ASK_FILLER,
                                  INJURY as _INJURY,
                                  EVENT_HAPPENED as _ASK_EVENT,
                                  LIABILITY as _LIAB_WORDS,
                                  AMOUNT_UPSELL as _ASK_AMOUNT,
                                  COVERAGE_Q as _COVERAGE_Q,
                                  COVERAGE_Q_STRICT as _ASK_COVER,
                                  MEDICAL_INTENT as _MEDICAL_INTENT,
                                  KNEE as _KNEE,
                                  URINARY as _URINARY,
                                  GUM as _GUM,
                                  TOOTH as _TOOTH,
                                  AGE_TALK as _AGE,
                                  AGE_NUM as _AGE_NUM,
                                  NEW_JOIN as _NEW_JOIN,
                                  NOT_NEW_JOIN as _NOT_NEW,
                                  ACUPUNCTURE as _ACU,
                                  NOT_ACUPUNCTURE as _NOT_ACU,
                                  FOLLOW_TAIL as _FOLLOW,
                                  VACCINE as _VAC_WORD,
                                  VACCINE_NONE as _VAC_NONE,
                                  VACCINE_WHEN as _VAC_TIME,
                                  LEGAL as _LEGAL_WORDS,
                                  ASKED_MARK)
from app.services import daycalc, payout

LIAB = "갱신형 펫퍼민트 반려견 배상책임보장 특별약관"
LEGAL = "민사소송법률비용Ⅱ보장 특별약관"


def _josa(word: str, pair: str) -> str:
    return pair[0] if payout._has_batchim(word) else pair[1]


def short_name(p) -> str:
    """'펫퍼민트 반려견 통원의료비Ⅱ보장 특별약관' 고급형 → '통원의료비Ⅱ 고급형'"""
    m = re.search(r"(통원|입원)의료비(Ⅱ|Ⅲ)?", p.section_name)
    base = m.group(0) if m else p.section_name.replace(" 특별약관", "").replace("갱신형 펫퍼민트 반려견 ", "")
    return f"{base} {p.coverage_type}" if p.coverage_type else base


def not_enrolled(question: str, pet: Pet | None) -> str | None:
    """가입하지 않은 특약을 물었으면 그 안내(코드 답). 아니면 None"""
    if pet is None:
        return None
    names = {p.section_name for p in pet.policies}
    missing = None
    if _LEGAL_WORDS.search(question) and LEGAL not in names:
        missing = "민사소송법률비용Ⅱ보장"
    elif pet.species == "강아지" and _LIAB_WORDS.search(question) and LIAB not in names:
        missing = "배상책임보장"
    else:
        said = [w for w in ("통원", "입원") if w in question]
        medical = [p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type]
        if len(said) == 1 and _MEDICAL_INTENT.search(question) and medical and not any(said[0] in p.section_name for p in medical):
            missing = f"{said[0]}의료비보장"
    if missing is None:
        return None
    have = ", ".join(short_name(p) for p in pet.policies if p.coverage_type or "배상" in p.section_name or "법률" in p.section_name)
    return (f"{pet.name}{_josa(pet.name, '은는')} {missing} 특약에 가입하지 않아 이 보험으로는 보장되지 않습니다. "
            f"가입한 특약: {have or '의료비 특약 없음'}.")


def annual_answer(question: str, pet: Pet | None, on: date | None = None) -> str | None:
    """올해 받은 보험금·남은 연간 한도를 물으면 청구 이력으로 답한다(코드 답). 아니면 None"""
    if pet is None or not payout.ANNUAL_ASK.search(question):
        return None
    on = on or payout.today()
    medical = [p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type]
    said = [w for w in ("통원", "입원") if w in question]
    if len(said) == 1:
        medical = [p for p in medical if said[0] in p.section_name] or medical
    if not medical:
        return None
    lines = []
    for p in medical:
        t = infer_type_from_section_name(p.section_name)
        lim = daycalc.DayLimits.of(p.coverage_type, t, p.copay or 0)
        a = payout.annual_usage(pet, p, lim.annual_total, on)
        lines.append(f"{short_name(p)}: 올해(보험연도 {a.year_start}부터) 받은 보험금 {payout._won(a.used)}"
                     f"{f'(청구 {a.claims}건)' if a.claims else ''}, 연간 총 한도 {payout._won(a.total)} 중 "
                     f"남은 한도 **{payout._won(a.remaining)}**입니다.")
    return "\n".join(lines) + "\n청구 이력은 지급이 끝난 건 기준입니다."


def notes(question: str, pet: Pet | None, on: date | None = None) -> list[str]:
    """답 끝에 붙일 고객 사실 — 가입일 대기기간(질병 30일, 슬관절·고관절 1년)과 나이"""
    if pet is None:
        return []
    on = on or payout.today()
    out = []
    medical = [p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type]
    starts = sorted({p.contract_date for p in medical})
    if starts:
        start = starts[-1]                        # 가장 늦은 가입일 기준(특약마다 같으면 하나)
        if _DISEASE.search(question) and (on - start).days < 30:
            end = start + timedelta(days=29)
            out.append(f"참고: {pet.name}{_josa(pet.name, '은는')} {start.isoformat()} 가입이라 보장개시일부터 30일 이내"
                       f"({end.month}월 {end.day}일까지)에 발생한 질병은 보상하지 않습니다(의료비 특약 제1조 ③). 상해는 해당하지 않습니다.")
        # 종마다 다르다 — 반려견 제1조 ④ 1년 이내 슬관절·고관절 / 반려묘 제1조 ④ 90일 이내 비뇨기계질환·전염성복막염
        # (반려묘 약관에는 슬관절 규칙이 없다 — 2026-10-21 4d 측정에서 고양이에게 반려견 규칙을 붙이던 것을 고침)
        if pet.species == "강아지" and _KNEE.search(question) and (on - start).days < 365:
            end = start + timedelta(days=364)
            out.append(f"참고: 보장개시일부터 1년 이내({end.isoformat()}까지)에 발생한 슬관절탈구·고관절탈구·슬관절형성부전·"
                       f"고관절형성부전 등은 보상하지 않습니다(의료비 특약 제1조 ④).")
        if pet.species == "고양이" and _URINARY.search(question) and (on - start).days < 90:
            end = start + timedelta(days=89)
            out.append(f"참고: 보장개시일부터 90일 이내({end.isoformat()}까지)에 발생한 비뇨기계질환·전염성복막염 등은 "
                       f"보상하지 않습니다(의료비 특약 제1조 ④).")
    if _AGE.search(question) and pet.age is not None:
        out.append(f"참고: {pet.name}{_josa(pet.name, '은는')} 원장 기준 {pet.age}세입니다. 새로 가입할 수 있는 나이는 만 8세(실속형은 "
                   f"만 10세)까지이고, 재가입은 회사가 정한 재가입 나이 범위 안이어야 합니다(구체 나이는 약관에 없음).")
    return out


# "특정질병이에요?"(분류 질문, P49)는 넣지 않는다 — 모델이 분류표로 답한다


def exclusion_answer(question: str, pet: Pet | None) -> str | None:
    """질문이 그 반려동물의 부담보에 걸리면(배너와 같은 대조 — payout.matched_exclusions) 코드가 답한다. 부담보 기간은 원장에
    없어 약관(반려동물 특정 질병 보장제한부 인수 특별약관 제2조) 그대로 범위만 말한다 — "영구"도 "N일 뒤"도 아니다"""
    excl = payout.matched_exclusions(question, pet)
    if not excl or pet is None or not _COVERAGE_Q.search(question):
        return None
    names = ", ".join(excl)
    who = f"{pet.name}{_josa(pet.name, '은는')}"
    return "\n".join([
        f"{who} {names}{_josa(excl[-1], '이가')} 부담보(반려동물 특정 질병 보장제한부 인수 특별약관)라, 부담보 기간 동안 "
        f"{names}{_josa(excl[-1], '을를')} 직접적인 원인으로 한 치료비는 보상하지 않습니다(제2조 ①).",
        "부담보 기간은 특정질병의 상태에 따라 1개월부터 5년 또는 계약의 보험기간 중에서 회사가 정합니다(제2조 ②). "
        "고객 원장에는 기간이 없어 보험증권에서 확인해야 합니다.",
        "가입 후 30일·90일 같은 대기기간과는 별개입니다 — 대기기간이 지나도 부담보 기간에는 보상하지 않습니다.",
        "다만 상해가 직접적인 원인이거나, 특정질병의 합병증으로 다른 질병이 진단 확정된 경우는 보상합니다(제2조 ④).",
    ] + notes(question, pet))       # 대기기간이 함께 걸리면(초코 슬관절 1년 — C27) 그 줄도


# 2026-10-24 가입 나이(PETMINT_AGE_CODE) — 신규 가입 나이를 숫자로 묻는 질문만. 조건 셋이 모두 맞아야 한다:
# 나이(숫자+살·세) · 신규 가입 · 재가입·갱신 아님. 평가 220·검색 회귀·답변 평가 307문장 중 P09·C51·C52만 걸린다.
# 모델은 정답(일반조항 제2조 '반려동물' 1호)이 표 칸 안에 있어도 나이 비교를 못 해 거절했다(3/3). 재가입(C50 — 약관에 구체 나이 없음)·
# 가입 대상(S42 경찰견)·"가입 나이 제한이 있어요?"(숫자 없음)는 넣지 않는다
_NUM_WORDS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
              "열한": 11, "열두": 12, "열세": 13, "열네": 14, "열다섯": 15}
_GRADES = ("고급형", "기본형", "실속형")
AGE_LIMIT = {"고급형": 8, "기본형": 8, "실속형": 10}      # 일반조항 제2조 '반려동물' 1호 — 이 나이를 '초과'하면 가입 대상 아님


def enrollment_age_answer(question: str, pet: Pet | None) -> str | None:
    """신규 가입 나이 질문이면 원장·질문의 나이와 약관 기준(만 8세, 실속형 만 10세 초과는 가입 대상 아님)을 코드가 비교해 답한다"""
    m = _AGE_NUM.search(question)
    if pet is None or m is None or not _NEW_JOIN.search(question) or _NOT_NEW.search(question):
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS[m.group(1)]
    over = bool(m.group(2))                       # "열 살 넘은" — n살보다 많다
    species = "고양이" if "고양이" in question else "강아지" if re.search(r"강아지|개", question) else pet.species
    animal = "고양이(猫)" if species == "고양이" else "개(犬)"
    named = pet.name in question
    who = f"{pet.name}{_josa(pet.name, '은는')} {n}살" if named else f"{n}살{' 넘은' if over else ''} {species}"
    grades = [g for g in _GRADES if g in question] or list(_GRADES)

    def verdict(g: str) -> tuple[str, str]:
        lim = AGE_LIMIT[g]
        if n > lim or (over and n >= lim):
            return f"만 {lim}세를 넘어 새로 가입할 수 없습니다", "no"
        if over:
            return f"만 {lim}세 이하이면 새로 가입할 수 있습니다(정확한 나이 확인 필요)", "maybe"
        return f"만 {lim}세를 '초과'해야 가입 대상에서 빠지므로 만 {n}세면 새로 가입할 수 있습니다", "yes"

    groups: dict[str, list[str]] = {}            # 같은 결론의 등급끼리 묶는다 — "고급형·기본형은 …"
    for g in grades:
        groups.setdefault(verdict(g)[0], []).append(g)
    parts = [f"{'·'.join(gs)}은 {text}" for text, gs in groups.items()]
    lines = [f"{who}{'이라' if payout._has_batchim(who) else '라'} " + ", ".join(parts) + "."]
    if len(grades) == 1 and grades[0] != "실속형" and verdict(grades[0])[1] == "no" and verdict("실속형")[1] == "yes":
        lines.append("실속형은 만 10세까지라 실속형으로는 가입할 수 있습니다.")
    lines.append(f"약관(반려동물 비용손해 관련 특별약관 일반조항 제2조 '반려동물' 1호): 보험가입 당시의 연령이 생후 60일 이하 또는 "
                 f"만 8세(단, 실속형의 경우 만 10세)를 초과하는 {animal}는 이 보험의 가입 대상이 아닙니다.")
    if named and pet.age is not None and pet.age != n:
        lines.append(f"참고: 원장의 {pet.name} 나이는 {pet.age}세입니다.")
    lines.append("나이는 만 나이 기준입니다. 생년월일로 가입 당시 만 나이를 확인해 주세요.")
    return "\n".join(lines)


# 2026-10-24 면책 단서(PETMINT_PROVISO_CODE) — 의료비 특약 제2조 면책 항목에 붙은 단서가 질문의 경우를 보장 쪽으로 빼 주는데 모델이 그 결론을
# 못 냈다(탐침: 침술 직접 정답 0/12, 접종 사실 대입 0/6, Ⅰ 유형 잇몸 거절 3/3 — data/review/proviso_carveout_probe.md).
# 병명·치료 말은 지금 질문(current)에 있어야 걸린다 — 앞 질문에서 이어 온 말로는 걸리지 않는다("한약은요?"·"이빨 뽑는 건요?"는 모델에게).
# 보장을 묻는 뜻은 앞 질문까지 합친 글(card)에서 본다
# ② 면책 대상 감염병(의료비 특약 제2조 ② ② — 반려견 10, 반려묘는 6 더). 이름은 약관 그대로
_VAC_DISEASES = [(r"파보", "파보 바이러스 감염"), (r"디스템퍼", "디스템퍼 바이러스 감염"), (r"파라\s*인플루엔자", "파라 인플루엔자 감염"),
                 (r"전염성\s*간염", "전염성 간염"), (r"아데노", "아데노 바이러스 2형 감염"), (r"광견병", "광견병"),
                 (r"코로나", "코로나 바이러스 감염"), (r"렙토스피라", "렙토스피라 감염"), (r"필라리아|심장사상충", "필라리아(심장사상충) 감염"),
                 (r"인플루엔자", "인플루엔자 감염")]
_VAC_DISEASES_CAT = [(r"범백", "고양이범백혈구감소증"), (r"칼리시", "고양이칼리시바이러스 감염증"), (r"비기관지염", "고양이바이러스성비기관지염"),
                     (r"고양이\s*백혈병", "고양이백혈병 바이러스감염증"), (r"헤르페스", "고양이헤르페스바이러스감염증"),
                     (r"클라미디아", "고양이클라미디아감염증")]


def _medical(pet: Pet) -> list:
    return [p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type]


def _vaccine_months(m: re.Match) -> tuple[float, bool]:
    """(개월 수, '안·이내'처럼 기간 안이라는 말인가)"""
    n = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS[m.group(1)]
    months = {"개월": n, "달": n, "년": n * 12, "주": n / 4.345, "일": n / 30.4}[m.group(2)]
    return months, m.group(3) in ("안", "이내")


def proviso_answer(current: str, card: str, pet: Pet | None) -> str | None:
    """면책 단서 셋(⑫ 침술 · ② 예방접종 · ⑲ 구강질환) 중 걸리는 것의 코드 답. 고객 사실 줄(대기기간)을 붙인다"""
    if pet is None or not _medical(pet):
        return None
    lines = None
    if _ACU.search(current) and not _NOT_ACU.search(current) and (_COVERAGE_Q.search(card) or _FOLLOW.search(current)):
        lines = ["침술은 한의학 면책(의료비 특약 제2조 ⑫ \"한의학(단, 침술을 제외합니다.)\")에서 빠져 있어, 침 치료라는 이유로는 "
                 "보험금이 거절되지 않습니다. 동물병원에서 수의사에게 받은 침 치료라면 의료비 특약 제1조에 따라 보상합니다.",
                 "다만 한약, 허브요법·아로마테라피 같은 다른 대체의료와 재활치료는 보상하지 않습니다(제2조 ⑫)."]
    if lines is None:
        found = next((name for pat, name in _VAC_DISEASES_CAT + _VAC_DISEASES
                      if re.search(pat, card) and (pet.species == "고양이" or (pat, name) in _VAC_DISEASES)), None)
        none = _VAC_NONE.search(current)
        t = _VAC_TIME.search(current) if _VAC_WORD.search(current) else None
        if found and (none or t):
            rule = (f"{found}{_josa(found, '은는')} 면책 대상 감염병이지만, 질병 발생일로부터 과거 1년 이내의 예방접종 기록이 있으면 "
                    f"보상합니다(의료비 특약 제2조 ②).")
            if none:
                verdict = "예방접종을 하지 않았다면 이 면책에 해당해 보상하지 않습니다."
            else:
                months, inside = _vaccine_months(t)
                said = t.group(0)
                if inside and months <= 12:
                    verdict = f"말씀하신 대로 {said}에 접종했다면 1년 이내라 이 면책에 해당하지 않아 보상 대상입니다."
                elif months < 12:
                    verdict = f"말씀하신 대로 {said} 접종했다면 1년 이내라 이 면책에 해당하지 않아 보상 대상입니다."
                elif months == 12:
                    verdict = f"{said} 접종이면 1년 경계라, 질병이 발생한 날을 기준으로 접종일이 1년 안인지 확인해야 합니다."
                else:
                    verdict = f"{said} 접종이면 1년이 지나 이 면책에 해당해 보상하지 않습니다."
            lines = [rule, verdict, "청구할 때 동물병원의 접종 기록으로 확인합니다."]
    if lines is None:
        type1 = [p for p in _medical(pet) if not re.search(r"Ⅱ|Ⅲ", p.section_name)]
        if type1 and _GUM.search(current) and not _TOOTH.search(current) and _COVERAGE_Q.search(card):
            lines = ["치아를 제외한 구강질환(잇몸 염증·구내염 등)은 보장합니다(의료비 특약 제2조 ⑲ 단서).",
                     "다만 구강질환 치료 목적이라도 치아에 하는 치료(스케일링·발치 등)는 보장하지 않습니다."]
    if lines is None:
        return None
    return "\n".join(lines + notes(card, pet))


def waiting_answer(question: str, pet: Pet | None, on: date | None = None) -> str | None:
    """보장 여부를 묻는 질문이고 대기기간 안이면(notes가 대기기간 줄을 낸다) 그 사실을 결론으로 코드가 답한다.
    대기기간이 지났으면 None — 원칙상 보장 여부는 모델이 발췌로 답한다(1안: 원칙을 본문으로).
    2026-10-23 측정(3안): 쓰지 않는다 — 가입 30일 안의 반려동물이면 질병 질문이 모두 이 답으로 넘어가 면책(유전병·치과·예방접종)을
    묻는 질문의 모델 정답을 덮었다(S09·S10·S27 정확 → 실패), "다음 달에 걸리면요?"에도 30일만 되풀이했다(M19-2)"""
    if pet is None or not _COVERAGE_Q.search(question):
        return None
    lines = [n.removeprefix("참고: ") for n in notes(question, pet, on) if "이내" in n and "보상하지 않습니다" in n]
    if not lines:
        return None
    return "\n".join(lines + ["이 기간에 발생한 것인지는 진단일로 판단합니다. 기간이 지난 뒤 발생한 질병은 다른 면책 사유가 없으면 "
                               "약관에 따라 보상 대상입니다."])


# 2026-10-28 병명 없이 보장을 묻는 질문(PETMINT_ASK_DISEASE) — "○○가 입원했어요. 보장되나요?"는 제1조·제2조가 발췌에 다 와도 모델이 거절했다
# (평가 L02·L14 3/3, 탐침). 병명을 모르면 면책·부담보·대기기간을 볼 수 없으니 거절이 아주 틀린 것은 아니지만 상담원이 막힌다 →
# 가입 의료비 특약으로 '질병·상해 치료면 보상' 원칙을 말하고 병명을 되묻는다. 범위를 좁게 — 다섯 조건이 다 맞아야 한다:
#   ① 실제로 겪은 일(입원했·통원했·수술했·다쳤·병원 갔…) ② 보장을 묻는다(보장·보상·보험 되나요·처리·나와요)
#   ③ 금액·숫자 없음(금액은 payout 되묻기) ④ 후속 아님(앞 턴에 병명이 있을 수 있다 — 호출하는 쪽이 본다)
#   ⑤ 반려동물 이름·①②의 말을 지우면 한글이 하나도 남지 않는다 — 병명·상해·치료 이름("침"·"눈 수술"·"중성화")이 있으면 걸리지 않는다




def _riders(question: str, pet: Pet):
    """(가입 의료비 특약 전부, 입원/통원/None, 질문에 맞는 특약) — 입원이면 입원의료비, 통원이면 통원의료비, 아니면 둘 다"""
    medical = [p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type]
    kind = "입원" if re.search(r"입원", question) else "통원" if re.search(r"통원", question) else None
    return medical, kind, [p for p in medical if kind is None or kind in p.section_name]


def disease_ask(question: str, pet: Pet | None, on: date | None = None) -> str | None:
    """병명 없이 보장을 묻는 질문 → 가입 의료비 특약의 원칙 + 병명 되묻기. 아니면 None"""
    if pet is None or not (_ASK_EVENT.search(question) and _ASK_COVER.search(question)) or _ASK_AMOUNT.search(question):
        return None
    rest = re.sub(re.escape(pet.name) + r"(?:이|가|는|은|를|을|도|의)?", " ", question)
    if re.search(r"[가-힣]", _ASK_FILLER.sub(" ", rest)):
        return None
    medical, kind, riders = _riders(question, pet)
    if not riders:
        return None                                   # 그 특약이 없으면 not_enrolled가 먼저 답한다 — 여기서는 지어내지 않는다
    names = ", ".join(short_name(p) for p in riders)              # short_name에 등급이 들어 있다
    treat, did = {"입원": ("입원 치료를", "입원했는지"), "통원": ("통원 치료를", "통원했는지")}.get(kind, ("치료를", "치료받았는지"))
    lines = [f"질병이나 상해로 {treat} 받았다면 {pet.name}{_josa(pet.name, '은는')} {names} 특약으로 보상됩니다"
             f"(1일 지급 한도·자기부담금·보상비율 적용, 제1조).",
             f"다만 질병에 따라 보상하지 않는 경우(제2조 면책·부담보·대기기간)가 있어, **어떤 질병이나 상해로 {did}** 알려 주시면 "
             f"보장 여부를 확인해 드릴게요."]
    on = on or payout.today()
    start = max((p.contract_date for p in medical), default=None)
    if start is not None and (on - start).days < 30:
        end = start + timedelta(days=29)
        lines.append(f"참고: {pet.name}{_josa(pet.name, '은는')} {start.isoformat()} 가입이라 {end.month}월 {end.day}일까지 발생한 질병은 "
                     f"보상하지 않습니다(제1조 ③) — 발병일도 함께 알려 주세요. 상해는 해당하지 않습니다.")
    return "\n".join(lines)


# 2026-10-28 되물은 뒤 상해로 답한 턴 — "산책하다 다리를 다쳤어요"는 후속 규칙에 안 걸려 따로 검색됐고(별표2 장해분류표 셋), 모델이 거절했다
# (탐침 DS3 0/3). 앞 답이 disease_ask(ASKED_MARK)이고 이번 말이 상해를 말하면 코드가 답한다 — 범위:
#   상해 낱말(다쳤·떨어졌·넘어졌·물렸·부러졌·화상·차에 치였…) · 금액·숫자 없음 · 다음은 빼고 모델·다른 코드 답으로:
#   슬관절·고관절·탈구(반려견 제1조 ④ 1년 이내는 상해도 보상하지 않는다) · 그 반려동물 부담보 · 제2조 ① 면책 사유(고의·자연재해·전쟁…) · 질병 낱말


def maybe_injury_reply(question: str) -> bool:
    """앞 턴을 읽어 볼 만한가(chat_ws) — 상해 낱말이 있다. 후속 규칙에 안 걸리는 온전한 문장("산책하다 다리를 다쳤어요")도"""
    return bool(_INJURY.search(question))


def injury_followup(question: str, prior_question: str | None, prior_answer: str | None, pet: Pet | None,
                    on: date | None = None) -> str | None:
    """disease_ask 뒤 상해로 답한 턴 → 상해 보상 원칙(대기기간 없음) + 금액 되묻기. 아니면 None"""
    if pet is None or not prior_answer or ASKED_MARK not in prior_answer or not _INJURY.search(question):
        return None
    if _INJURY_NOT.search(question) or _ASK_AMOUNT.search(question) or payout.matched_exclusions(question, pet):
        return None
    medical, kind, riders = _riders(prior_question or "", pet)
    if not riders:
        return None
    names = ", ".join(short_name(p) for p in riders)
    how = {"입원": "입원 일수와 치료비 총액", "통원": "통원 횟수와 치료비"}.get(kind, "입원·통원 여부와 치료비")
    lines = [f"상해(다친 것)라면 {pet.name}{_josa(pet.name, '은는')} {names} 특약으로 보상됩니다(1일 지급 한도·자기부담금·보상비율 적용, 제1조)."]
    on = on or payout.today()
    start = max((p.contract_date for p in medical), default=None)
    if start is not None and (on - start).days < 30:
        lines.append(f"- {start.isoformat()} 가입이라 30일이 지나지 않았지만, 가입 후 30일 대기기간은 질병에만 적용되어 상해는 해당하지 않습니다(제1조 ③).")
    else:
        lines.append("- 가입 후 30일 대기기간은 질병에만 적용되어 상해는 해당하지 않습니다(제1조 ③).")
    if pet.species == "강아지" and start is not None and (on - start).days < 365:
        lines.append("- 다만 슬관절·고관절 탈구 등은 가입 후 1년 이내면 상해여도 보상하지 않습니다(제1조 ④) — 무릎·고관절을 다쳤다면 알려 주세요.")
    lines.append("- 고의나 자연재해 등 보험금을 지급하지 않는 사유(제2조)에 해당하면 보상하지 않습니다.")
    lines.append(f"보상 금액은 {how}{_josa(how, '을를')} 알려 주시면 계산해 드릴게요.")
    return "\n".join(lines)
