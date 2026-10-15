-- 0003_graph_score.sql — 그래프 확장분에는 검색 점수가 없다(검색 결과가 아니다). 0을 넣으면 없는 값을 지어내게 된다.
-- score를 NULL 허용으로 바꾸고, 검색 행에서는 CHECK로 필수로 묶는다(0002의 ck_retrieved_kind에 score를 더한다).

ALTER TABLE retrieved
    DROP CHECK ck_retrieved_kind,
    MODIFY COLUMN score DOUBLE NULL,                          -- 검색 점수. 그래프 확장분은 NULL
    ADD CONSTRAINT ck_retrieved_kind CHECK (
        (via_graph = FALSE AND `rank` IS NOT NULL AND graph_key IS NOT NULL AND section IS NOT NULL
         AND score IS NOT NULL)
        OR (via_graph = TRUE AND `rank` IS NULL)
    );
