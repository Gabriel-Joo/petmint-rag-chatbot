-- insurance_core 0002_claims.sql — 청구 이력(2026-10-21). 계산 카드가 연간 총 한도에서 올해 이미 받은 보험금을 빼고,
-- Ⅲ 유형 MRI·CT·내시경이 올해 몇 번째인지 센다(payout.annual_usage). 보험연도는 가입일 기준 계약해당일부터 1년(약관 【보험연도】).
-- 특약은 section_name 문자열로 둔다 — policies와 같은 문자열이어야 한다(시드와 앱 로더가 검증). 치료 유형(통원/입원)은
-- section_name에서도 알 수 있지만 청구 서류의 구분 그대로 둔다.

CREATE TABLE claims (
    claim_id        VARCHAR(32)  NOT NULL,
    pet_id          VARCHAR(32)  NOT NULL,
    section_name    VARCHAR(200) NOT NULL,          -- 청구한 의료비 특약
    claim_date      DATE         NOT NULL,          -- 청구일
    treatment_date  DATE         NOT NULL,          -- 치료(첫날) — 보험연도는 이 날짜로 가른다
    treatment_type  ENUM('통원', '입원') NOT NULL,
    days            SMALLINT     NOT NULL,          -- 치료 일수(통원 횟수)
    treatment_cost  INT          NOT NULL,          -- 치료비 합계(원)
    paid            INT          NOT NULL,          -- 지급액(원)
    surgery         BOOLEAN      NOT NULL DEFAULT FALSE,   -- 수술한 날이 있었다
    mri             BOOLEAN      NOT NULL DEFAULT FALSE,   -- MRI·CT·내시경을 받은 날이 있었다(수술하지 않은 날, 1일로 센다)
    PRIMARY KEY (claim_id),
    KEY ix_claims_pet (pet_id, section_name, treatment_date),
    CONSTRAINT fk_claims_pet FOREIGN KEY (pet_id) REFERENCES pets (pet_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
