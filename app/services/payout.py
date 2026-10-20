"""
payout.py
계산 카드(09번 2-3절) — 치료비가 들어간 질문이면 limit_table로 예상 지급액을 낸다. 모델은 계산에 손대지 않는다.

- 금액: 질문의 첫 'N원'(23만원, 3만 5천원, 230,000원). 자기부담금·한도·보험료 바로 뒤의 금액은 치료비가 아니라 건너뛴다.
- 특약: 고른 쪽(되묻기) → 질문의 '통원'/'입원'에 맞는 가입 특약 → 상위 검색 결과 중 가입한 의료비 특약 →
  가입한 의료비 특약이 모두 같은 (유형, 등급)이면 그것. 정할 수 없으면 카드를 내지 않는다.
- 상황: '수술'이면 수술한 날 한도, 아니면 수술하지 않은 날. Ⅲ은 MRI·CT·내시경이면 그 한도(연간 첫 번째 기준,
  '두 번째'가 있으면 두 번째 이상). 수술과 MRI가 겹치면 수술 한도(limit_table 주석).
- 자기부담금은 가입 정보(policies.copay)다. 없으면 카드를 내지 않는다(3만/5만 중 어느 쪽인지 모른다).

민사소송법률비용 — legal_estimate(question): 질문 속 소송 금액(소송목적의 값)으로 【별표3】 변호사비용 한도·【별표4】 인지액,
심급·사건 종류가 있으면 【별표5】 송달료까지 낸다(limit_table). 소송 금액 없이 심급만 말하면 송달료만.
legal_card(question, pet): 민사소송법률비용 특약 가입자에게만 법률비용 카드(LegalCalc).
limit_card(question, pet, chosen): 치료비 금액 없이 한도를 물으면 가입한 의료비 특약의 한도표(LimitsCalc).
답변 흐름의 순서는 법률비용 → 의료비(금액 있음) → 한도. 카드만 붙이고 답변 문장은 건드리지 않는다.
"""

import re
from dataclasses import dataclass

from data.limit_table import LEGAL_COST, calculate_payout, get_limit, lawyer_fee_bracket, lawyer_fee_limit, service_fee, stamp_fee
from data.rag_context import infer_type_from_section_name
from data.search_scope import MEDICAL_SECTIONS, mentioned_grade, mentioned_type

from app.schemas import LegalCalc, LimitRow, LimitsCalc, MedicalCalc, Pet
from app.services import intent

_UNIT = {"억": 10 ** 8, "천만": 10 ** 7, "백만": 10 ** 6, "만": 10 ** 4, "천": 10 ** 3, "백": 100}
_NUM = r"\d[\d,]*(?:\.\d+)?"
_UNIT_RE = "|".join(sorted(_UNIT, key=len, reverse=True))
_AMOUNT = re.compile(rf"((?:{_NUM}\s*(?:{_UNIT_RE})\s*)*(?:{_NUM}\s*(?:{_UNIT_RE})?)?)\s*원")
_PART = re.compile(rf"({_NUM})\s*({_UNIT_RE})?")
_NOT_COST = re.compile(r"(자기\s*부담금?|한도|보험료|공제)\s*(은|는|이|가|을|를|도|로)?\s*$")
_COST_WORD = re.compile(r"치료비|진료비|병원비|수술비|검사비|입원비|통원비|의료비|청구|나왔|나오|들었|냈")
_NO_SURGERY = re.compile(r"수술\s*(을|은)?\s*(안|하지\s*않|없이|없는)|비수술")
_MRI = re.compile(r"MRI|CT|내시경|엠알아이", re.I)
_SECOND = re.compile(r"두\s*번째|2\s*번째|두\s*번|2\s*회|이번이\s*두|또\s*찍")

_SCENARIO_LABEL = {
    "non_surgery": "수술하지 않은 날", "surgery": "수술한 날",
    "non_surgery_mri_1st": "MRI·CT·내시경(연간 첫 번째)", "non_surgery_mri_2nd_plus": "MRI·CT·내시경(연간 두 번째 이상)",
    "non_surgery_no_mri": "수술하지 않은 날(MRI·CT·내시경 없음)",
}


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


def scenario(question: str, type_: str) -> str:
    surgery = "수술" in question and not _NO_SURGERY.search(question)
    if surgery:
        return "surgery"
    if type_ != "Ⅲ":
        return "non_surgery"
    if _MRI.search(question):
        return "non_surgery_mri_2nd_plus" if _SECOND.search(question) else "non_surgery_mri_1st"
    return "non_surgery_no_mri"


def _section(question: str, pet: Pet, results: list[dict], chosen: str | None) -> str | None:
    medical = {p.section_name: p for p in pet.policies if p.section_name in MEDICAL_SECTIONS[pet.species]}
    if chosen in medical:
        return chosen
    for word in ("통원", "입원"):
        hits = [name for name in medical if word in name]
        if word in question and len(hits) == 1:
            return hits[0]
    for r in results:
        if r.get("section_name") in medical:
            return r["section_name"]
    combos = {(p.type, p.coverage_type) for p in medical.values()}
    return next(iter(medical)) if len(combos) == 1 else None


def estimate(question: str, pet: Pet | None, results: list[dict], chosen: str | None = None,
             cost: int | None = None) -> MedicalCalc | None:
    """계산 카드 하나. 업무특화(가입 정보가 있을 때)만 — 일반·사내규정은 pet이 None.
    cost: 치료비를 이미 안다(금액 되묻기 직후 턴 — 상담원이 말한 금액은 치료비다). 없으면 질문에서 찾는다"""
    if pet is None:
        return None
    cost = cost if cost is not None else treatment_cost(question)
    if cost is None:
        return None
    name = _section(question, pet, results, chosen)
    if name is None:
        return None
    policy = next(p for p in pet.policies if p.section_name == name)
    if policy.coverage_type is None or policy.copay is None:
        return None
    type_ = infer_type_from_section_name(name)
    sc = scenario(question, type_)
    lim = get_limit(policy.coverage_type, type_, sc)
    paid = max(calculate_payout(cost, policy.copay, lim["rate"], lim["limit"]), 0)
    note = (f"{_SCENARIO_LABEL[sc]} 1일 한도 기준 · 보상비율 {round(lim['rate'] * 100)}% · "
            f"연간 총 한도 {lim['annual_total']:,}원은 따로 본다. 실제 지급액은 보험금 심사로 정해진다")
    return MedicalCalc(rate_pct=round(lim["rate"] * 100), section_name=name, coverage_type=policy.coverage_type, claimed=cost, copay=policy.copay,
                      limit=lim["limit"], payout=paid, note=note)


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
_NOT_MEDICAL = re.compile(r"소송|변호사|인지액|송달료|배상|법률")   # 법률비용·배상책임 질문 — 의료비 한도표가 아니다
# 치료비·보험금이 아닌 돈 이야기 — 한도 카드와 금액 되묻기에서 뺀다("중도인출 하면 얼마까지 돼요?"에 의료비 한도 카드가 떴다)
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
                medical = [p for p in medical if word in p.section_name] or medical
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
ASK_AMOUNT_TEXT = "치료비가 얼마인가요? 동물병원 영수증 금액을 알려 주시면 예상 보험금을 계산해 드립니다."


def needs_amount(question: str, pet: Pet | None, embed: "intent.Embed | None" = None) -> bool:
    """보험금 금액을 묻는데 치료비 금액이 없다 — 모델은 계산할 수 없어 거절한다. 되물어 다음 턴(멀티턴)에 금액을 받는다.
    ① '받을 금액을 묻는가'는 금액 낱말 + 임베딩(intent.asks_amount, embed = Retriever.embed). embed가 없거나 실패하면 규칙.
    ②~⑤(치료비 금액·한도·법률·다른 돈)는 다른 카드로 보내는 갈림길이라 규칙 그대로"""
    if pet is None or not any(p.section_name in MEDICAL_SECTIONS[pet.species] and p.coverage_type for p in pet.policies):
        return False
    if (treatment_cost(question) is not None or _LIMIT_WORD.search(question) or _NOT_MEDICAL.search(question)
            or OTHER_MONEY.search(question)):
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
    """질문(기준 질문 포함)에 걸리는 부담보 질병 — 화면 배너(ExclusionBanner.matchExclusions)와 같은 글자 대조:
    공백을 무시한 전체 일치, 또는 3글자 이상 낱말 일치. 동의어("무릎" ↔ "슬개골")는 못 잡는다"""
    if pet is None:
        return []
    flat = re.sub(r"\s+", "", text)
    conds = [c for p in pet.policies for c in p.excluded_conditions]
    return [c for c in dict.fromkeys(conds)
            if re.sub(r"\s+", "", c) in flat or any(len(w) >= 3 and w in flat for w in c.split())]


def amount_answer(card: MedicalCalc, pet: Pet, text: str) -> str:
    """금액 되묻기 직후 턴의 답 — 카드 값으로 계산 과정과 예상 보험금, 부담보, 보장 여부 단서"""
    setting = "입원" if "입원" in card.section_name else "통원"
    rate = card.rate_pct if card.rate_pct is not None else 70
    after_copay = max(card.claimed - card.copay, 0)
    base = after_copay * rate // 100
    if card.claimed <= card.copay:
        body = (f"{setting} 치료비 {_won(card.claimed)}이 자기부담금 {_won(card.copay)} 이하라 "
                f"예상 보험금은 **{_won(card.payout)}**입니다.")
    else:
        body = f"{setting} 치료비 {_won(card.claimed)}에서 자기부담금 {_won(card.copay)}을 뺀 {_won(after_copay)}의 {rate}%는 {_won(base)}입니다."
        if card.payout < base:
            body += f" 1일 지급 한도가 {_won(card.limit)}이라 예상 보험금은 **{_won(card.payout)}**입니다."
        else:
            body += f" 1일 지급 한도({_won(card.limit)}) 안이라 예상 보험금은 **{_won(card.payout)}**입니다."
    lines = [body]
    excl = matched_exclusions(text, pet)
    if excl:
        lines.append(f"다만 {pet.name}{'은' if _has_batchim(pet.name) else '는'} {', '.join(excl)}{'이' if _has_batchim(excl[-1]) else '가'} 부담보 대상이라 "
                     f"해당 치료는 보험금이 지급되지 않습니다.")
    lines.append(COVERAGE_NOTE)
    return "\n".join(lines)


def _has_batchim(word: str) -> bool:
    ch = word.strip()[-1]
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0
