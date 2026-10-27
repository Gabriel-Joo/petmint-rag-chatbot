-- insurance_core 0003_employees.sql — 인사 원장(2026-10-28). 회사 기간계의 인사 쪽을 흉내 낸다. 직원은 전부 가상이다(db/fixtures/employees.json).
-- 챗봇(petmint)은 고객 원장과 같이 읽기만 한다 — 로그인 신원(이름·이메일·재직)과, 다음 단계의 사내규정 개인화
-- (퇴직금·연차 잔여·자격수당·승진 체류연수)가 이 사실을 쓴다. 계산 규칙은 저장하지 않는다 — 인사규정(약관처럼 청크)에 있다.
-- 비밀번호·로그인 세션은 여기 두지 않는다 — 앱이 쓰는 값이라 petmint 데이터베이스(0006_accounts)에 있다.

-- 직원 한 명. 근속연수는 입사일과 휴직 이력으로 계산한다(제3조 5호·제22조 ④)
CREATE TABLE employees (
    employee_id      VARCHAR(16)  NOT NULL,          -- 사번(로그인 ID)
    name             VARCHAR(50)  NOT NULL,
    email            VARCHAR(255) NOT NULL,          -- 소문자. 상담 기록(petmint.sessions.agent_email)에 이 값이 남는다
    team             VARCHAR(50)  NULL,
    grade            ENUM('사원', '대리', '과장', '차장', '부장') NOT NULL,   -- 직급(제33조 승진, 별표1 출장비)
    grade_since      DATE         NOT NULL,          -- 지금 직급에 오른 날 — 승진 최소 체류연수(제33조 ②)
    employment_type  ENUM('정규직', '계약직', '파견직') NOT NULL,          -- 계약직·파견직은 급여·퇴직이 개별근로계약(제2조 ③)
    hire_date        DATE         NOT NULL,          -- 입사일 — 근속·연차·퇴직금·수습(제7·17·28조)
    career_hire      BOOLEAN      NOT NULL DEFAULT FALSE,   -- 경력직 채용 — 수습 면제 가능(제7조 ⑤)
    birth_date       DATE         NOT NULL,          -- 정년 만 60세(제43조)
    retired_on       DATE         NULL,              -- 퇴직일. 있으면 로그인할 수 없다
    PRIMARY KEY (employee_id),
    UNIQUE KEY uq_employees_email (email)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 자격증. 수당은 사본을 낸 달의 다음 달부터, 둘 이상이면 큰 것 하나(제27조 ②③). 수당표에 없는 자격도 담는다
CREATE TABLE employee_certificates (
    employee_id   VARCHAR(16)  NOT NULL,
    cert_name     VARCHAR(50)  NOT NULL,
    acquired_on   DATE         NOT NULL,
    submitted_on  DATE         NULL,                 -- 자격증 사본 제출일. NULL이면 아직 안 냈다(수당 없음)
    PRIMARY KEY (employee_id, cert_name),
    CONSTRAINT fk_certificates_employee FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 월 급여. 평균임금 = 사유 발생일 이전 3개월 임금총액 ÷ 총일수(제3조 4호), 미사용 연차수당·가산수당은 통상임금(제3조 3호·제12조·제17조 ⑤)
CREATE TABLE employee_payroll (
    employee_id       VARCHAR(16)  NOT NULL,
    pay_month         DATE         NOT NULL,         -- 그 달 1일(산정기간 1일~말일, 제25조 ①)
    base_pay          INT          NOT NULL,         -- 기본급(수습 중이면 90% — 제7조 ②)
    fixed_allowances  INT          NOT NULL,         -- 정기·일률 수당(식대·교통비·직책·자격수당)
    overtime_pay      INT          NOT NULL DEFAULT 0,   -- 연장·야간·휴일근로수당
    bonus             INT          NOT NULL DEFAULT 0,   -- 상여금
    ordinary_wage     INT          NOT NULL,         -- 월 통상임금(기본급 + 정기·일률 수당)
    total_pay         INT AS (base_pay + fixed_allowances + overtime_pay + bonus) STORED,   -- 그 달 임금총액
    PRIMARY KEY (employee_id, pay_month),
    CONSTRAINT fk_payroll_employee FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 휴가 사용(연차·병가·경조·특별). 연차 잔여 = 부여(제17조) − 그 연차 기간의 연차 사용. 반차는 0.5(제18조 ②)
CREATE TABLE employee_leaves (
    leave_id     BIGINT        NOT NULL AUTO_INCREMENT,
    employee_id  VARCHAR(16)   NOT NULL,
    leave_type   ENUM('연차', '병가', '경조', '특별') NOT NULL,
    start_date   DATE          NOT NULL,
    end_date     DATE          NOT NULL,
    days         DECIMAL(4, 1) NOT NULL,             -- 사용 일수(근무일 기준)
    note         VARCHAR(100)  NULL,
    PRIMARY KEY (leave_id),
    KEY ix_leaves_employee (employee_id, start_date),
    CONSTRAINT fk_leaves_employee FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 휴직. 육아·병역휴직은 근속에 넣고 나머지는 뺀다(제22조 ④)
CREATE TABLE employee_absences (
    absence_id   BIGINT       NOT NULL AUTO_INCREMENT,
    employee_id  VARCHAR(16)  NOT NULL,
    kind         ENUM('질병휴직', '육아휴직', '가족돌봄휴직', '학업휴직', '병역휴직') NOT NULL,
    start_date   DATE         NOT NULL,
    end_date     DATE         NOT NULL,
    PRIMARY KEY (absence_id),
    KEY ix_absences_employee (employee_id, start_date),
    CONSTRAINT fk_absences_employee FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 인사평가(연 2회, S~D — 제32조). 최근 2회 연속 D면 승진 제외(제33조 ③)
CREATE TABLE employee_evaluations (
    employee_id  VARCHAR(16)  NOT NULL,
    period       CHAR(7)      NOT NULL,              -- '2026-H1'(7월 평가) · '2026-H2'(다음 해 1월 평가)
    grade        ENUM('S', 'A', 'B', 'C', 'D') NOT NULL,
    PRIMARY KEY (employee_id, period),
    CONSTRAINT fk_evaluations_employee FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
