-- petmint 0006_accounts.sql — 앱 자체 로그인(2026-10-28, 13번 2-1절). 직원 신원(이름·이메일·재직)은 기간계 insurance_core.employees에 있고
-- 앱은 그것을 읽기만 한다. 여기에는 앱이 쓰는 값만 둔다 — 역할·비밀번호 해시·잠금·로그인 세션.
-- employee_id는 다른 데이터베이스라 외래키를 걸지 않는다(customer_id와 같은 경계, 12번 4절).
-- sessions.agent_email은 그대로다 — 로그인한 직원의 이메일이 들어간다. 퇴직자의 상담 기록이 남아야 하므로 외래키를 걸지 않는다.

CREATE TABLE accounts (
    employee_id           VARCHAR(16)  NOT NULL,     -- insurance_core.employees.employee_id(사번)
    role                  ENUM('상담원', '관리자') NOT NULL DEFAULT '상담원',
    password_hash         VARCHAR(255) NULL,         -- argon2id. NULL이면 초기 비밀번호 전이라 로그인할 수 없다
    must_change_password  BOOLEAN      NOT NULL DEFAULT TRUE,   -- 관리자가 준 비밀번호는 첫 로그인 때 바꾼다
    failed_count          SMALLINT     NOT NULL DEFAULT 0,      -- 연속 실패. 성공하면 0
    locked_until          DATETIME(3)  NULL,         -- 5회 실패 → 15분 잠금
    disabled_at           DATETIME(3)  NULL,         -- 앱 접근만 끊는다(기간계 퇴직과 별개)
    password_changed_at   DATETIME(3)  NULL,
    last_login_at         DATETIME(3)  NULL,
    created_at            DATETIME(3)  NOT NULL,
    PRIMARY KEY (employee_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 로그인 세션. 쿠키에는 난수 토큰을, 여기에는 그 SHA-256만 둔다(DB가 새도 쿠키를 만들 수 없다). 지우면 즉시 로그아웃
CREATE TABLE auth_sessions (
    token_hash    CHAR(64)     NOT NULL,
    employee_id   VARCHAR(16)  NOT NULL,
    created_at    DATETIME(3)  NOT NULL,
    last_seen_at  DATETIME(3)  NOT NULL,             -- 미사용 2시간이면 만료
    expires_at    DATETIME(3)  NOT NULL,             -- 절대 만료(로그인 후 12시간)
    ip            VARCHAR(45)  NULL,
    user_agent    VARCHAR(255) NULL,
    PRIMARY KEY (token_hash),
    KEY ix_auth_sessions_employee (employee_id),
    CONSTRAINT fk_auth_sessions_account FOREIGN KEY (employee_id) REFERENCES accounts (employee_id) ON DELETE CASCADE
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
