-- petmint 0011_admin_views.sql — 관리자 화면 열람 기록(2026-11-12, docs/13 2-5절).
-- 관리자 화면은 다른 상담원의 상담을 연다. 누가 언제 무엇을 봤는지 남긴다 — 상담 목록(제목에 첫 질문 요약이 보인다)과 대화 둘 다.
-- 이 기록을 보는 화면은 없다(사용자 결정). 조회 SQL은 docs/12 1-6절. 지우지 않는다 — 하루 수십 줄이다.

CREATE TABLE admin_views (
    id                  BIGINT       NOT NULL AUTO_INCREMENT,
    viewer_employee_id  VARCHAR(16)  NOT NULL,       -- 연 관리자(사번)
    demo                BOOLEAN      NOT NULL,       -- 체험 로그인 세션으로 열었나(auth_sessions.demo)
    kind                ENUM('sessions', 'session') NOT NULL,   -- 상담 목록 / 대화 하나
    target_agent_email  VARCHAR(255) NOT NULL,       -- 그 상담을 맡은 상담원(sessions.agent_email)
    session_id          CHAR(36)     NULL,           -- kind = 'session'만
    date_from           DATE         NULL,           -- kind = 'sessions'만 — 고른 기간(KST)
    date_to             DATE         NULL,
    ip                  VARCHAR(45)  NULL,
    viewed_at           DATETIME(3)  NOT NULL,
    PRIMARY KEY (id),
    KEY ix_admin_views_viewed (viewed_at),
    KEY ix_admin_views_target (target_agent_email, viewed_at)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
