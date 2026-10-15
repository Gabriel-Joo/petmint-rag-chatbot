-- 0002_graph_clarified.sql — 12번 1-1절 보완(2026-10-15).
-- retrieved: 그래프로 따라간 조문(참조 조문·법령 박스)도 남긴다. 검색 결과가 아니므로 rank가 없다 → 대리키 id.
--   그래프 확장분은 청크가 아니다(여러 청크를 이은 본문이거나 약관 밖 법령) — graph_key·section을 강제하지 않는다.
--   검색 행의 보장(rank·graph_key·section 필수)은 CHECK로 DB가 지킨다. content는 두 쪽 다 NOT NULL(재현의 핵심).
--   그래프 행은 content·article_title·citation_label로 읽는다. 법령 박스는 citation_label로 식별한다.
-- turns: clarified(09번 4절 되묻기). 기록 경로는 되묻기 구현 때 붙인다.
-- 테이블이 비어 있을 때 적용했다(이관 없음).

ALTER TABLE retrieved
    DROP PRIMARY KEY,
    ADD COLUMN id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY FIRST,
    MODIFY COLUMN `rank` SMALLINT NULL,                      -- 검색 순위. 그래프 확장분은 NULL
    MODIFY COLUMN graph_key VARCHAR(512) NULL,
    MODIFY COLUMN section VARCHAR(100) NULL,
    ADD COLUMN via_graph BOOLEAN NOT NULL DEFAULT FALSE AFTER `rank`,
    ADD KEY ix_retrieved_turn_rank (turn_id, `rank`),
    ADD CONSTRAINT ck_retrieved_kind CHECK (
        (via_graph = FALSE AND `rank` IS NOT NULL AND graph_key IS NOT NULL AND section IS NOT NULL)
        OR (via_graph = TRUE AND `rank` IS NULL)
    );

ALTER TABLE turns
    ADD COLUMN clarified BOOLEAN NOT NULL DEFAULT FALSE AFTER is_hypothetical;
