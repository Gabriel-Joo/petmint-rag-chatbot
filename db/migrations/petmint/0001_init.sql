-- 0001_init.sql — 12번 1-1절 테이블 다섯.
-- 문서와 다른 점(2026-10-15 결정): sessions.pinned·deleted_at, turns.first_token_ms·status,
-- retrieved의 식별·복원 칼럼(graph_key·corpus·section·article_title·coverage_type·paragraph_num·citation_label).
-- 시각은 전부 UTC(DATETIME(3), 앱이 접속 시 time_zone='+00:00'로 맞춘다).
-- 외래키에 CASCADE를 걸지 않는다 — 로그는 지우지 않는다(지난 채팅 "제거"는 sessions.deleted_at).

CREATE TABLE sessions (
    session_id   CHAR(36)     NOT NULL,
    mode         ENUM('일반', '사내규정', '업무특화') NOT NULL,
    customer_id  VARCHAR(32)  NULL,                -- 업무특화만. 고객 데이터가 아직 픽스처라 외래키 없이 문자열
    agent_email  VARCHAR(255) NOT NULL,            -- Cf-Access-Authenticated-User-Email(13번). 로컬은 기본값
    title        VARCHAR(200) NULL,                -- 지난 채팅 목록 제목. 첫 질문을 요약해 세션당 한 번
    pinned       BOOLEAN      NOT NULL DEFAULT FALSE,
    started_at   DATETIME(3)  NOT NULL,
    ended_at     DATETIME(3)  NULL,                -- 업무특화만 채운다. 일반·사내규정은 NULL = 이어 쓸 수 있다
    deleted_at   DATETIME(3)  NULL,                -- 목록에서 제거. 로그(turns 이하)는 그대로 남는다
    PRIMARY KEY (session_id),
    KEY ix_sessions_customer (customer_id),
    KEY ix_sessions_started (started_at),
    KEY ix_sessions_agent_mode (agent_email, mode, deleted_at, started_at)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

CREATE TABLE turns (
    turn_id            CHAR(36)     NOT NULL,
    session_id         CHAR(36)     NOT NULL,
    question           TEXT         NOT NULL,
    rewritten_question TEXT         NULL,
    answer             MEDIUMTEXT   NOT NULL,
    -- 그 턴의 반려동물 스냅샷(12번 2-2절). 고객 데이터가 바뀌어도 그대로. pet_id는 연결용
    pet_id             VARCHAR(32)  NULL,
    pet_name           VARCHAR(100) NULL,
    species            ENUM('강아지', '고양이') NULL,
    breed              VARCHAR(100) NULL,
    pet_age            SMALLINT     NULL,
    is_hypothetical    BOOLEAN      NOT NULL DEFAULT FALSE,
    model              VARCHAR(100) NOT NULL,
    prompt_version     VARCHAR(50)  NOT NULL,
    index_version      VARCHAR(50)  NOT NULL,
    first_token_ms     INT          NULL,
    latency_ms         INT          NOT NULL,
    status             ENUM('ok', 'cancelled', 'error') NOT NULL DEFAULT 'ok',
    created_at         DATETIME(3)  NOT NULL,
    PRIMARY KEY (turn_id),
    KEY ix_turns_session (session_id),
    KEY ix_turns_created (created_at),
    CONSTRAINT fk_turns_session FOREIGN KEY (session_id) REFERENCES sessions (session_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 그 턴에 적용된 가입 내용 스냅샷. 특약 하나당 한 줄
CREATE TABLE turn_scope (
    id                  BIGINT       NOT NULL AUTO_INCREMENT,
    turn_id             CHAR(36)     NOT NULL,
    section_name        VARCHAR(200) NOT NULL,
    coverage_type       ENUM('고급형', '기본형', '실속형') NULL,
    copay               INT          NULL,
    excluded_conditions JSON         NOT NULL,     -- 부담보 문자열 배열. 없으면 []
    PRIMARY KEY (id),
    KEY ix_turn_scope_turn (turn_id),
    CONSTRAINT fk_turn_scope_turn FOREIGN KEY (turn_id) REFERENCES turns (turn_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 그 턴에 검색된 조문. 재색인 뒤에도 "그때 무엇을 봤는가"가 남도록 식별값과 본문을 통째로 박는다
CREATE TABLE retrieved (
    turn_id        CHAR(36)     NOT NULL,
    `rank`         SMALLINT     NOT NULL,          -- 0부터. RANK는 MySQL 8 예약어라 따옴표가 필요하다
    graph_key      VARCHAR(512) NOT NULL,          -- 조문 식별 기준 키(rag_context.graph_key, 09번 6-3절)
    corpus         VARCHAR(20)  NOT NULL,          -- 강아지 / 고양이 / 인사규정. 리트리버가 늘면 값만 늘린다(앱이 검증)
    section        VARCHAR(100) NOT NULL,
    section_name   VARCHAR(200) NULL,              -- 보통약관은 NULL
    article_num    INT          NULL,              -- 별표 등은 NULL
    article_title  VARCHAR(300) NULL,
    coverage_type  ENUM('고급형', '기본형', '실속형') NULL,
    paragraph_num  INT          NULL,
    score          DOUBLE       NOT NULL,
    content        MEDIUMTEXT   NOT NULL,
    used           BOOLEAN      NOT NULL DEFAULT FALSE,   -- 답변이 실제로 쓴 근거(08 평가)
    citation_label VARCHAR(300) NULL,              -- used 행에만
    PRIMARY KEY (turn_id, `rank`),                 -- turn_id 조회는 이 키의 앞부분이 맡는다
    CONSTRAINT fk_retrieved_turn FOREIGN KEY (turn_id) REFERENCES turns (turn_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;

-- 상담원 평가. 원본 로그는 고치지 않고 따로 쌓는다. 턴당 0~1줄(다시 누르면 덮어쓴다)
CREATE TABLE feedback (
    turn_id    CHAR(36)    NOT NULL,
    rating     ENUM('up', 'down') NOT NULL,
    comment    TEXT        NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (turn_id),
    CONSTRAINT fk_feedback_turn FOREIGN KEY (turn_id) REFERENCES turns (turn_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci;
