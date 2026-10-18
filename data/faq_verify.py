"""
faq_verify.py
의료비 특약 계산형 FAQ 검증 — 05번(FAQ 생성)이 import한다.
7B 생성 모델은 산수를 자주 틀린다(2026-10-12 측정: 계산형 QA 74개 중 19개 오류, 26%).
답변의 계산식·적용 한도·최종 금액을 limit_table(01번이 원문 대조로 확정한 진실의 원천)로 다시 계산해 대조한다.
측정: 사람이 확인한 오류 19건 중 19건 검출, 오탐 0.
"""
import re

try:
    from data import limit_table as LT
    from data.limit_table import LIMIT_TABLE, LIMIT_TABLE_TYPE3, calculate_payout
except ImportError:          # data/ 폴더에서 직접 실행할 때
    import limit_table as LT
    from limit_table import LIMIT_TABLE, LIMIT_TABLE_TYPE3, calculate_payout

MAN = r"(\d+(?:\.\d+)?)\s*만\s*원"
def unit_type(section_name):
    m = re.search(r"의료비(Ⅱ|Ⅲ)?보장", section_name or "")
    return (m.group(1) or "Ⅰ") if m else None

_NO_SURGERY = re.compile(r"수술(을|은|이)?(하지|받지|안하|안한|안받)|수술(이|은)?없|수술없|수술안|비수술")


def normalize_amounts(text: str) -> str:
    """'8만 4천원' → '8.4만원', '4천원' → '0.4만원' — 모델이 쓰는 금액 표기를 '만원' 단위 소수로 맞춘다"""
    text = re.sub(r"(\d+)\s*만\s*(\d)\s*천\s*원", r"\1.\2만원", text)
    return re.sub(r"(?<![\d.만])(\d)\s*천\s*원", r"0.\1만원", text)


def scenario_of(question, type_):
    q = re.sub(r"\s+", "", question)
    if "수술" in q and not _NO_SURGERY.search(q):
        return "surgery"
    if type_ == "Ⅲ" and re.search(r"MRI|CT|내시경", q):
        if re.search(r"(MRI|CT|내시경)[^?]{0,20}받지않", q):
            return "non_surgery_no_mri"
        if re.search(r"두번째|2번째|두번째이상|2회|두번", q):
            return "non_surgery_mri_2nd_plus"
        return "non_surgery_mri_1st"
    return "non_surgery_no_mri" if type_ == "Ⅲ" else "non_surgery"

def limits_for(coverage, type_):
    if not coverage or not type_:
        return None
    return LIMIT_TABLE_TYPE3[coverage] if type_ == "Ⅲ" else LIMIT_TABLE[(coverage, type_)]

def is_calc(qa):
    return bool(re.search(MAN + r"\s*[-－]\s*" + MAN, qa["answer"]) or re.search(r"[×x\*]\s*(0\.\d+|\d+\s*%)", qa["answer"])) \
        and bool(re.search(MAN, qa["question"]))

def verify(qa, coverage, section_name):
    """계산형 QA면 (통과 여부, 문제 목록), 계산형이 아니면 None.
    검사: ① 중간 계산 (A-C)×R% = X ② 대괄호 한도 [ … , L만원]가 질문 상황(수술/MRI 1회차·2회차 이상/그 외)의 한도와 같은지
    ③ 질문의 치료비·자기부담금으로 calculate_payout 한 정답 금액이 답변에 있는지"""
    if not is_calc(qa):
        return None
    type_ = unit_type(section_name)
    ent = limits_for(coverage, type_)
    a = normalize_amounts(qa["answer"]); q = normalize_amounts(qa["question"])
    problems = []
    # 1) 중간 계산: (A만원 - C만원) × R% … = X만원  /  N만원 × 0.7 = X만원
    for m in re.finditer(MAN + r"\s*[-－]\s*" + MAN + r"\s*\)?\s*[×x\*]\s*(\d+(?:\.\d+)?)\s*%\s*\]?\s*\)?\s*=\s*" + MAN, a):
        A, C, R, X = map(float, m.groups())
        if abs((A - C) * R / 100 - X) > 0.05:
            problems.append(f"중간계산 ({A:g}-{C:g})×{R:g}%={X:g} (정답 {(A-C)*R/100:g})")
    for m in re.finditer(MAN + r"\s*[×x\*]\s*(0\.\d+)\s*\)?\s*=\s*" + MAN, a):
        N, R, X = map(float, m.groups())
        if abs(N * R - X) > 0.05:
            problems.append(f"중간계산 {N:g}×{R:g}={X:g} (정답 {N*R:g})")
    if ent:
        scen = scenario_of(q, type_)
        limit = ent[scen] / 10_000
        rate = ent["rate"]
        # 2) 대괄호 한도 [ … , L만원] 가 상황의 한도와 같은가
        for m in re.finditer(r",\s*" + MAN + r"\s*\]", a):
            L = float(m.group(1))
            if abs(L - limit) > 0.01:
                problems.append(f"한도 {L:g}만원 ≠ {coverage}{type_} {scen} 한도 {limit:g}만원")
        # 3) 최종 금액: 질문의 치료비·자기부담금으로 calculate_payout
        # 치료비: '치료비 … N만원'을 우선. 없으면 자기부담금·연간 한도(연간/총 보상한도 뒤의 금액)를 뺀 나머지 중 최대
        # '410만원의 치료비' / '치료비가 410만원' 형태만 (치료비 뒤에 오는 '자기부담금이 3만원'을 집지 않게)
        treat = re.search(MAN + r"\s*(?:의|을|를)?\s*(?:수술\s*당일\s*)?치료비", q) or \
            re.search(r"치료비(?:가|는|로|를|이|으로)?\s*(?:총\s*)?" + MAN, q)
        annual = {float(m.group(1)) for m in re.finditer(r"(?:연간|총\s*보상\s*한도)[^0-9]{0,15}" + MAN, q)}
        costs = [float(x) for x in re.findall(MAN, q)]
        copays = [c for c in costs if c in (3.0, 5.0)]
        others = [c for c in costs if c not in (3.0, 5.0) and c not in annual]
        T = float(treat.group(1)) if treat else (max(others) if others else None)
        if copays and T:
            C = copays[0]
            exp = calculate_payout(int(T * 10_000), int(C * 10_000), rate, ent[scen]) / 10_000
            # 결론 금액: 대괄호 [ … ] 안(계산식·한도)과 한도를 다시 말하는 금액('1일당 30만원', '한도 15만원')을 뺀 뒤
            # 마지막으로 나오는 금액. 여러 날·연간 합계를 묻는 질문은 1일 계산과 비교할 수 없어 건너뛴다
            outside = re.sub(r"\[[^\]]*\]", " ", a)
            outside = re.sub(r"(?:1일당|한도(?:액)?(?:가|는|은|인|로|를)?)\s*(?:최대\s*)?" + MAN, " ", outside)
            outside = re.sub(MAN + r"\s*(?:의|이|을|를)?\s*(?:지급\s*)?한도", " ", outside)
            concl = [float(x) for x in re.findall(MAN, outside)]
            multi_day = re.search(r"\d+\s*일\s*(?:이고|간|동안|분)|각\s*날|매일|1년\s*동안|한\s*해\s*동안|총\s*보험금|합계|누적", q)
            if multi_day:
                pass
            elif concl and abs(concl[-1] - exp) >= 0.05:
                problems.append(f"결론 금액 {concl[-1]:g}만원 ≠ 정답 {exp:g}만원 ({coverage}{type_} {scen}, 보상비율 {rate:.0%})")
            elif not concl and not any(abs(float(x) - exp) < 0.05 for x in re.findall(MAN, a)):
                problems.append(f"정답 {exp:g}만원이 답변에 없음 ({coverage}{type_} {scen}, 보상비율 {rate:.0%})")
    return (not problems, problems)


# ===== 별표3(소송목적의 값에 따른 변호사비용)·별표4(민사소송 인지액)·별표5(송달료) 계산 검증 =====
# 2026-10-12 2차 검수: 구간 공식을 잘못 고르거나(2억~2억5천만원에 1억5천~2억 구간 공식) 덧셈을 틀린(55,000+600,000=645,000) 사례.
# 2026-10-18(rebuild4): 구간표·계산은 limit_table(lawyer_fee_limit·stamp_fee·service_fee, tests/test_legal_fees.py가 원문 [표]와
# 대조)을 쓴다 — 여기 따로 두던 부동소수 표를 없앴다. 대조를 셋 더했다(사용자 지시 2026-10-18 "LLM 심판보다 정확하다"):
#   ③ 질문의 소송목적의 값보다 윗구간의 비율(예: 2억5천만원에 5억 초과 구간 0.5%)  ④ 표·계산 어디에도 없는 금액
#   ⑤ 별표5 송달료: 송달료표에 없는 금액, 민사단독·합의를 말하면서 165,000원이 없음(R044: 셋 다 110,000원)
_UNIT = {"억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "만": 10_000, "천": 1_000}
_MONEY = re.compile(r"((?:\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|만|천)\s*)+(?:\d[\d,]*\s*)?원|\d[\d,]*(?:\.\d+)?\s*원)")
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_won(expr: str) -> float:
    """'1억 5천만원' → 150,000,000 / '655,000원' → 655,000 / '64만 5천원' → 645,000"""
    total = 0.0
    for num, unit in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|만|천)?", expr):
        total += float(num.replace(",", "")) * _UNIT.get(unit, 1)
    return total


def money_values(text: str) -> list[float]:
    return [parse_won(m.group(1)) for m in _MONEY.finditer(text)]


def lawyer_fee(value: float) -> tuple[float, tuple]:
    """(변호사비용 한도, (기본액, 구간 하한, 비율)) — limit_table.lawyer_fee_limit"""
    v = int(round(value))
    for low, high, base, permille in LT.LAWYER_FEE_BRACKETS:
        if high is None or v <= high:
            return float(LT.lawyer_fee_limit(v)), (base, low, permille / 1000)


def stamp_fee(value: float) -> tuple[float, tuple]:
    """(인지액, (정액, 비율)) — limit_table.stamp_fee"""
    v = int(round(value))
    for low, high, base, bp in LT.STAMP_FEE_BRACKETS:
        if high is None or v < high:
            return float(LT.stamp_fee(v)), (base, bp / 10000)


def _table_amounts() -> set[float]:
    """별표3·4·5와 법률비용 특약 한도표에 적힌 금액 — 답변이 표를 옮겨 적는 것은 정상"""
    out = {float(x) for low, high, base, _ in LT.LAWYER_FEE_BRACKETS for x in (low, high, base) if x is not None}
    out |= {float(x) for low, high, base, _ in LT.STAMP_FEE_BRACKETS for x in (low, high, base) if x is not None}
    out |= {float(v) for v in LT.SERVICE_FEE.values()} | {float(v) for v in LT.LEGAL_COST.values()}
    return out


def _bracket_rates(kind: str) -> list[tuple[float, float]]:
    """(구간 하한, 비율 %) — 윗구간 비율 대조용"""
    if kind == "lawyer":
        return [(low, pm / 10) for low, _h, _b, pm in LT.LAWYER_FEE_BRACKETS]
    return [(low, bp / 100) for low, _h, _b, bp in LT.STAMP_FEE_BRACKETS]


def verify_service_fee(qa) -> tuple[bool, list] | None:
    """별표5 송달료 — 답변이 송달료를 말할 때만"""
    a = qa["answer"]
    if "송달료" not in a:
        return None
    fees = {float(v) for v in LT.SERVICE_FEE.values()}
    vals = [v for v in money_values(a) if v < 1_000_000]          # 송달료 자리 금액(소송 금액·한도 1,000만원은 제외)
    problems = [f"송달료표에 없는 금액 {v:,.0f}원" for v in vals if v not in fees and v not in _table_amounts()]
    if re.search(r"민사\s*(단독|합의)", a) and 165_000.0 not in vals and vals:
        problems.append("민사단독·합의를 말하면서 165,000원이 없음(1심 단독·합의는 165,000원)")
    return (not problems, problems)


def verify_byeopyo(qa, section_name):
    """별표3·별표4 계산형 QA면 (통과 여부, 문제 목록), 아니면 None.
    질문의 소송목적의 값(구간으로 물으면 구간 하한 바로 위)으로 정답을 계산해 ① 답변의 최종 금액, 없으면 ② 답변 공식의 기본액·기준액을 대조한다."""
    name = section_name or ""
    kind = "lawyer" if "별표3" in name else ("stamp" if "별표4" in name else None)
    if not kind:
        return None
    service = verify_service_fee(qa) if "별표5" in name else None
    q, a = qa["question"], qa["answer"]
    vals = money_values(re.sub(r"\(.*?\)", "", q))
    if not vals:
        return service
    ranged = bool(re.search(r"(사이|초과|부터|에서)", q)) and len(vals) >= 2
    above_one = not ranged and bool(re.search(r"(넘는|넘을|넘으면|넘어|초과|이상)", q))   # "5억원을 넘는·이상" = 그 위 구간
    value = (min(vals) + 1) if ranged or above_one else vals[0]
    exp, bracket = lawyer_fee(value) if kind == "lawyer" else stamp_fee(value)
    problems = []
    # 결론 금액: '=' 뒤 금액 중 마지막 (계산식 안의 금액 제외)
    finals = [parse_won(m.group(1)) for m in re.finditer(r"=\s*" + _MONEY.pattern, a)]
    if not ranged and finals:
        if abs(finals[-1] - exp) > 1:
            problems.append(f"결론 금액 {finals[-1]:,.0f}원 ≠ 정답 {exp:,.0f}원 ({'변호사비용' if kind == 'lawyer' else '인지액'}, 값 {value:,.0f}원)")
    else:
        # 공식만 있는 답: '[X만원 + (소송목적의 값 - Y) x …]' 또는 'X원 + 소송목적의 값 X r%'의 기본액 대조
        base_m = re.search(_MONEY.pattern + r"\s*\+", a)
        if base_m:
            got_base = parse_won(base_m.group(1))
            if abs(got_base - bracket[0]) > 1:
                problems.append(f"공식 기본액 {got_base:,.0f}원 ≠ 해당 구간 기본액 {bracket[0]:,.0f}원 (값 {value:,.0f}원)")
        elif not ranged and not any(abs(v - exp) <= 1 for v in money_values(a)):
            problems.append(f"정답 {exp:,.0f}원이 답변에 없음")
    # ③ 윗구간 비율 — 소송목적의 값이 들어가는 구간보다 위 구간의 비율을 썼다(아래 구간 비율은 누진 설명으로 나올 수 있다)
    if not ranged:
        above = {pct for low, pct in _bracket_rates(kind) if low >= value and pct > 0}
        cur = next(pct for low, pct in reversed(_bracket_rates(kind)) if low < value or low == 0)
        used = {float(x) for x in _PCT.findall(a)}
        wrong = sorted(used & (above - {cur}))
        if wrong:
            problems.append(f"윗구간 비율 {wrong}% (값 {value:,.0f}원의 구간 비율 {cur:g}%)")
    # ④ 표·계산 어디에도 없는 금액 — 질문 금액, 표 금액, 정답, 해당 구간 계산의 중간값만 허용
    if not ranged:
        base, low = bracket[0], (bracket[1] if kind == "lawyer" else 0)
        rate = bracket[-1]
        allowed = _table_amounts() | set(vals) | {exp, value - low, (value - low) * rate, value * rate, base}
        extra = [v for v in money_values(a) if not any(abs(v - x) <= 1 for x in allowed)]
        if extra:
            problems.append(f"표·계산에 없는 금액 {[f'{v:,.0f}원' for v in extra]} (값 {value:,.0f}원, 정답 {exp:,.0f}원)")
    if service is not None and not service[0]:
        problems += service[1]
    return (not problems, problems)
