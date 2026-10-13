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
    return min(int((treatment_cost - copay) * rate), daily_limit)
