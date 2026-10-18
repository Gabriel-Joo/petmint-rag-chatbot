"""
payout.py
계산 카드(09번 2-3절) — 치료비가 들어간 질문이면 limit_table로 예상 지급액을 낸다. 모델은 계산에 손대지 않는다.

- 금액: 질문의 첫 'N원'(23만원, 3만 5천원, 230,000원). 자기부담금·한도·보험료 바로 뒤의 금액은 치료비가 아니라 건너뛴다.
- 특약: 고른 쪽(되묻기) → 질문의 '통원'/'입원'에 맞는 가입 특약 → 상위 검색 결과 중 가입한 의료비 특약 →
  가입한 의료비 특약이 모두 같은 (유형, 등급)이면 그것. 정할 수 없으면 카드를 내지 않는다.
- 상황: '수술'이면 수술한 날 한도, 아니면 수술하지 않은 날. Ⅲ은 MRI·CT·내시경이면 그 한도(연간 첫 번째 기준,
  '두 번째'가 있으면 두 번째 이상). 수술과 MRI가 겹치면 수술 한도(limit_table 주석).
- 자기부담금은 가입 정보(policies.copay)다. 없으면 카드를 내지 않는다(3만/5만 중 어느 쪽인지 모른다).
"""

import re

from data.limit_table import calculate_payout, get_limit
from data.rag_context import infer_type_from_section_name
from data.search_scope import MEDICAL_SECTIONS

from app.schemas import CalcResult, Pet

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


def estimate(question: str, pet: Pet | None, results: list[dict], chosen: str | None = None) -> CalcResult | None:
    """계산 카드 하나. 업무특화(가입 정보가 있을 때)만 — 일반·사내규정은 pet이 None"""
    if pet is None:
        return None
    cost = treatment_cost(question)
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
    return CalcResult(section_name=name, coverage_type=policy.coverage_type, claimed=cost, copay=policy.copay,
                      limit=lim["limit"], payout=paid, note=note)
