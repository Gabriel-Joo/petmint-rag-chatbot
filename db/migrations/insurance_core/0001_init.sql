-- insurance_core 0001_init.sql — 보험사 기간계를 흉내 낸 고객 원장(09번 6-1절 JSON을 그대로 편다).
-- 챗봇(petmint)은 이 데이터베이스를 읽기만 한다(petmint_app = SELECT). 적재·수정은 insurance_seed 계정.
-- petmint 쪽에서 여기로 외래키를 걸지 않는다 — 데이터베이스가 다르고, 그것이 경계다(12번 4절: customer_id는 문자열).
-- 유형(Ⅰ/Ⅱ/Ⅲ)은 저장하지 않는다 — section_name에서 계산한다(09번 6-1절). 약관 시행일·종료일도 복사하지 않는다(청크 메타에서 조회).

CREATE TABLE customers (
    customer_id VARCHAR(32)  NOT NULL,
    name        VARCHAR(100) NOT NULL,
    phone       VARCHAR(32)  NOT NULL,
    PRIMARY KEY (customer_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE TABLE pets (
    pet_id      VARCHAR(32)  NOT NULL,
    customer_id VARCHAR(32)  NOT NULL,
    seq         SMALLINT     NOT NULL,              -- 고객 안에서의 순서(상담 화면의 첫 반려동물)
    name        VARCHAR(100) NOT NULL,
    species     ENUM('강아지', '고양이') NOT NULL,
    breed       VARCHAR(100) NULL,
    age         SMALLINT     NULL,
    PRIMARY KEY (pet_id),
    UNIQUE KEY uq_pets_customer_seq (customer_id, seq),
    CONSTRAINT fk_pets_customer FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 특약 단위. 등급은 특약마다 따로 정의되므로 특약 한 줄에 둔다
CREATE TABLE policies (
    pet_id              VARCHAR(32)  NOT NULL,
    seq                 SMALLINT     NOT NULL,      -- 반려동물 안에서의 순서
    doc_id              VARCHAR(64)  NOT NULL,      -- 청크 doc_id(약관 개정판 구별)
    product_name        VARCHAR(200) NOT NULL,
    policy_version      VARCHAR(32)  NOT NULL,
    section_name        VARCHAR(200) NOT NULL,      -- 그 약관 청크의 section_name과 같은 문자열(앱이 기동 때 검증)
    coverage_type       ENUM('고급형', '기본형', '실속형') NULL,   -- 의료비 특약만
    copay               INT          NULL,          -- 자기부담금(원)
    contract_date       DATE         NOT NULL,      -- 약관 effective_date 이후여야 한다(앱이 검증)
    renewal             VARCHAR(50)  NULL,
    excluded_conditions JSON         NOT NULL,      -- 부담보 문자열 배열. 없으면 []
    PRIMARY KEY (pet_id, seq),
    UNIQUE KEY uq_policies_pet_section (pet_id, section_name),
    CONSTRAINT fk_policies_pet FOREIGN KEY (pet_id) REFERENCES pets (pet_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
