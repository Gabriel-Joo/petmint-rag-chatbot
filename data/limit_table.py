"""
펫퍼민트 반려견/반려묘 약관 — 통원/입원 Ⅰ·Ⅱ·Ⅲ 지급한도 기준표
01번 전처리 단계에서 원문 대조로 확정 (강아지/고양이 동일 구조 확인됨)
04번(RAG)과 06번(품질 검증)이 공유해서 참조하는 "진실의 원천" 파일
"""

# 자기부담금: 통원/입원 Ⅰ·Ⅱ·Ⅲ 전부 공통, 비수술일/수술일 구분 없이 동일 적용
# 3만원 또는 5만원 중 "보험증권에 기재된" 값 — 가입 시 선택에 따라 결정되므로 단일 확정값 아님
COPAY_OPTIONS = [30_000, 50_000]

LIMIT_TABLE = {
    # (coverage_type, type_): {non_surgery, surgery, rate, annual_total}  -- Ⅰ·Ⅱ 유형용 (통원/입원 공통)
    # non_surgery/surgery 공통 계산식: (실제 치료비 - 자기부담금) × rate, 1일당 한도까지
    # non_surgery: 수술을 하지 않은 날, 1일당 / surgery: 수술을 한 날(당일에 한함), 1일당
    ("기본형", "Ⅰ"): {"non_surgery": 150_000,  "surgery": 2_000_000, "rate": 0.7, "annual_total": 5_000_000},
    ("고급형", "Ⅰ"): {"non_surgery": 300_000,  "surgery": 2_000_000, "rate": 0.7, "annual_total": 7_500_000},
    ("실속형", "Ⅰ"): {"non_surgery": 100_000,  "surgery": 1_500_000, "rate": 0.5, "annual_total": 3_500_000},
    ("기본형", "Ⅱ"): {"non_surgery": 150_000,  "surgery": 2_500_000, "rate": 0.7, "annual_total": 10_000_000},
    ("고급형", "Ⅱ"): {"non_surgery": 300_000,  "surgery": 2_500_000, "rate": 0.7, "annual_total": 15_000_000},
    ("실속형", "Ⅱ"): {"non_surgery": 100_000,  "surgery": 2_000_000, "rate": 0.5, "annual_total": 7_000_000},
}

LIMIT_TABLE_TYPE3 = {
    # coverage_type: {...}  -- Ⅲ 유형용 (통원/입원 공통)
    # 자기부담금(COPAY_OPTIONS)은 아래 모든 scenario에 공통 적용, rate(보상비율)도 공통 적용
    # 상위 조건 1) 수술을 하지 않은 날 — 그 안에서 다시 3가지로 세분화됨:
    #   non_surgery_mri_1st:      수술 안 한 날 중, MRI·CT·내시경처치 받은 날의 "연간 첫 번째"
    #   non_surgery_mri_2nd_plus: 수술 안 한 날 중, MRI·CT·내시경처치 받은 날의 "연간 두 번째 이상"
    #   non_surgery_no_mri:       수술 안 한 날 중, MRI·CT·내시경처치를 받지 않은 날
    # 상위 조건 2) 수술을 한 날 — 수술당일에 한하여 적용되는 단일 한도:
    #   surgery:                  수술을 한 날(당일에 한함), 1일당
    # 중요: MRI/CT/내시경처치와 수술이 "같은 날" 동시에 발생하면,
    #       MRI 한도가 아니라 surgery(수술) 한도가 우선 적용된다 (원문 예시로 확인됨)
    "기본형": {"non_surgery_mri_1st": 500_000,   "non_surgery_mri_2nd_plus": 150_000, "non_surgery_no_mri": 150_000, "surgery": 2_500_000, "rate": 0.7, "annual_total": 10_000_000},
    "고급형": {"non_surgery_mri_1st": 1_000_000, "non_surgery_mri_2nd_plus": 300_000, "non_surgery_no_mri": 300_000, "surgery": 2_500_000, "rate": 0.7, "annual_total": 15_000_000},
    "실속형": {"non_surgery_mri_1st": 300_000,   "non_surgery_mri_2nd_plus": 100_000, "non_surgery_no_mri": 100_000, "surgery": 2_000_000, "rate": 0.5, "annual_total": 7_000_000},
}

# 자기부담금(3만원/5만원 선택)이 공통 적용되지 않는 별도 담보 — 건별로 고정 금액
OTHER_COPAY = {
    "갱신형 펫퍼민트 반려견 배상책임": {"copay": 30_000, "basis": "매 사고당"},
    "민사소송법률비용Ⅱ": {"copay": 100_000, "basis": "자기부담금"},
}


def get_limit(coverage_type: str, type_: str, scenario: str) -> dict:
    """
    coverage_type: "기본형"/"고급형"/"실속형"
    type_: "Ⅰ"/"Ⅱ"/"Ⅲ"
    scenario:
      Ⅰ·Ⅱ용: "non_surgery"(수술 안 한 날) / "surgery"(수술한 날)
      Ⅲ용: "non_surgery_mri_1st" / "non_surgery_mri_2nd_plus" / "non_surgery_no_mri" / "surgery"
            (MRI와 수술이 같은 날 겹치면 반드시 "surgery"를 사용할 것)

    반환값에 copay_options(자기부담금 선택지, 통원/입원Ⅰ·Ⅱ·Ⅲ 공통)도 함께 포함.
    """
    if type_ in ("Ⅰ", "Ⅱ"):
        entry = LIMIT_TABLE[(coverage_type, type_)]
    elif type_ == "Ⅲ":
        entry = LIMIT_TABLE_TYPE3[coverage_type]
    else:
        raise ValueError(f"알 수 없는 유형: {type_}")

    return {
        "limit": entry[scenario],
        "rate": entry["rate"],
        "annual_total": entry["annual_total"],
        "copay_options": COPAY_OPTIONS,
    }


def calculate_payout(treatment_cost: int, copay: int, rate: float, daily_limit: int) -> int:
    """
    보험금 지급금액 산출 공식 (약관 요약서 21쪽 원문 그대로):
    = min[ (치료비 - 자기부담금) × 보상비율 , 1일당 지급한도 ]

    검증 예시(원문 그대로, 전부 일치 확인됨):
      calculate_payout(230_000, 30_000, 0.7, 150_000) == 140_000     (기본형Ⅰ 비수술)
      calculate_payout(4_000_000, 30_000, 0.7, 2_000_000) == 2_000_000  (기본형Ⅰ 수술)
      calculate_payout(4_100_000, 30_000, 0.7, 2_500_000) == 2_500_000  (기본형Ⅱ 수술)
      calculate_payout(130_000, 30_000, 0.5, 100_000) == 50_000       (실속형Ⅰ 비수술)
      calculate_payout(330_000, 30_000, 0.7, 300_000) == 210_000      (고급형Ⅲ 비수술·MRI없음)
      calculate_payout(1_030_000, 30_000, 0.7, 1_000_000) == 700_000  (고급형Ⅲ 비수술·MRI 1회차)
      calculate_payout(4_100_000, 30_000, 0.7, 2_500_000) == 2_500_000  (고급형Ⅲ MRI+수술 동시 → 수술한도)
    """
    # 보상비율을 백분율 정수로 곱한다 — 0.7을 실수로 곱하면 원 단위가 1원 모자라게 잘렸다
    # (치료비 4천원~300만원 1천원 간격 5,922개 중 722개, 예: 41,000원 → 7,699원. 2026-10-21)
    pct = round(rate * 100)
    return min((treatment_cost - copay) * pct // 100, daily_limit)


# ===== 민사소송법률비용Ⅱ 특약 — 【별표3】 변호사비용 · 【별표4】 인지액 · 【별표5】 송달료 (강아지·고양이 같은 표) =====
# 약관만으로 금액이 나오는 표 셋(2026-10-18 조사). 97문항 판정에서 어댑터가 틀린 R043(변호사 보수 280만원을 30만원으로)·
# R032·R044(송달료)가 여기 속한다 — 의료비 한도처럼 코드가 계산하고 모델은 계산에 손대지 않는다.
# 표는 원문 그대로 옮겼다. 원문에 계산 예시가 없어 검증은 표에 적힌 구간별 기준액과의 일치로 한다(tests/test_legal_fees.py).

# 【별표3】 소송목적의 값에 따른 변호사비용 — (구간 하한, 구간 상한, 기준액, 초과분 비율 ‰). 상한 None = 끝없음
# 비율은 천분율 정수 — 부동소수로 곱하면 원 단위가 1원 모자라게 잘린다(예: 0.0045 × 2,500만 = 112,499.99…)
# "300만원까지 부분 30만원 / 300만원을 초과하여 2,000만원까지 부분 [30만원 + (소송목적의 값 - 300만원) x 10%] / …"
LAWYER_FEE_BRACKETS = [
    (0,             3_000_000,   300_000,    0),       # 300만원까지 부분: 30만원
    (3_000_000,     20_000_000,  300_000,    100),     # 10%
    (20_000_000,    50_000_000,  2_000_000,  80),      # 8%
    (50_000_000,    100_000_000, 4_400_000,  60),      # 6%
    (100_000_000,   150_000_000, 7_400_000,  40),      # 4%
    (150_000_000,   200_000_000, 9_400_000,  20),      # 2%
    (200_000_000,   500_000_000, 10_400_000, 10),      # 1%
    (500_000_000,   None,        13_400_000, 5),       # 0.5%
]

# 【별표4】 민사소송 등 인지법에 정한 인지액 — (구간 하한 이상, 구간 상한 미만, 정액, 소송목적의 값 전체에 곱하는 비율 ‱)
# 원문: "1천만원 미만: 소송목적의 값 X 0.5% / 1천만원이상 ~ 1억원 미만: 5,000원 + 소송목적의 값 X 0.45% / …"
# 인지법 본문의 원 단위 절사·최저액은 약관 별표에 없어 넣지 않는다(원 미만만 버린다)
STAMP_FEE_BRACKETS = [
    (0,             10_000_000,    0,       50),     # 0.5%
    (10_000_000,    100_000_000,   5_000,   45),     # 0.45%
    (100_000_000,   1_000_000_000, 55_000,  40),     # 0.4%
    (1_000_000_000, None,          555_000, 35),     # 0.35%
]

# 【별표5】 송달료 규칙에 정한 송달료(민사소송) — 조회형. 1심은 사건 종류별, 항소심·상고심은 하나
SERVICE_FEE = {
    ("1심", "민사소액"): 110_000,
    ("1심", "민사단독"): 165_000,
    ("1심", "민사합의"): 165_000,
    ("항소심", None): 132_000,
    ("상고심", None): 88_000,
}

# 민사소송법률비용Ⅱ 특약 제1조 한도표 · 제3조 ②항 — 1소송당, 심급별
LEGAL_COST = {"lawyer_limit": 20_000_000, "lawyer_copay": 100_000, "stamp_service_limit": 10_000_000}


def lawyer_fee_limit(claim_value: int) -> int:
    """【별표3】 소송목적의 값에 따른 변호사비용(소송비용에 산입되는 한도) = 기준액 + (값 - 구간 하한) × 비율.
    300만원까지는 30만원(정액)."""
    if claim_value < 0:
        raise ValueError(f"소송목적의 값이 음수: {claim_value}")
    for low, high, base, permille in LAWYER_FEE_BRACKETS:
        if high is None or claim_value <= high:
            return base + (claim_value - low) * permille // 1000
    raise AssertionError("구간표가 끝없이 닫혀 있어야 한다")


def lawyer_fee_bracket(claim_value: int) -> tuple[int, int | None, int, int]:
    """【별표3】에서 소송목적의 값이 속한 구간 (하한, 상한, 기준액, 천분율) — 계산 카드의 '적용 구간' 표시용"""
    for row in LAWYER_FEE_BRACKETS:
        if row[1] is None or claim_value <= row[1]:
            return row
    raise AssertionError("구간표가 끝없이 닫혀 있어야 한다")


def stamp_fee(claim_value: int) -> int:
    """【별표4】 인지액 = 정액 + 소송목적의 값 × 비율(구간 하한 이상 ~ 상한 미만)"""
    if claim_value < 0:
        raise ValueError(f"소송목적의 값이 음수: {claim_value}")
    for low, high, base, basis_points in STAMP_FEE_BRACKETS:
        if high is None or claim_value < high:
            return base + claim_value * basis_points // 10000
    raise AssertionError("구간표가 끝없이 닫혀 있어야 한다")


def service_fee(instance: str, case_kind: str | None = None) -> int:
    """【별표5】 송달료. instance: "1심"/"항소심"/"상고심". 1심이면 case_kind "민사소액"/"민사단독"/"민사합의"가 있어야 한다"""
    key = (instance, case_kind if instance == "1심" else None)
    if key not in SERVICE_FEE:
        raise ValueError(f"별표5에 없는 사건: {instance} {case_kind}")
    return SERVICE_FEE[key]


def legal_cost_payout(claim_value: int, lawyer_paid: int, stamp_paid: int, service_paid: int,
                      instance: str, case_kind: str | None = None) -> dict:
    """민사소송법률비용Ⅱ 특약 제3조 ②항 — 한 심급의 보험금.
    ① 변호사 보수: 실제 부담액 중 자기부담금 10만원을 넘는 금액, 【별표3】 한도와 1소송당 2,000만원 중 작은 쪽까지
    ② 인지액: 【별표4】 한도 내 실제 부담액   ③ 송달료: 【별표5】 한도 내 실제 부담액   (②+③ 1소송당 1,000만원 한도)"""
    lawyer = min(max(lawyer_paid - LEGAL_COST["lawyer_copay"], 0), lawyer_fee_limit(claim_value), LEGAL_COST["lawyer_limit"])
    stamp = min(stamp_paid, stamp_fee(claim_value))
    service = min(service_paid, service_fee(instance, case_kind))
    stamp_service = min(stamp + service, LEGAL_COST["stamp_service_limit"])
    return {"lawyer": lawyer, "stamp": stamp, "service": service, "stamp_service": stamp_service,
            "total": lawyer + stamp_service}
