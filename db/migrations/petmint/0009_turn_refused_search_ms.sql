-- petmint 0009_turn_refused_search_ms.sql — 턴마다 거절 여부와 search-service 시간을 남긴다(2026-11-11, docs/12 1-1절).
-- Grafana 「거절률」·「검색 지연」 패널이 읽는다(읽기 계정 grafana_ro는 이 두 칸에 컬럼 SELECT — 답 본문은 읽지 않는다).
-- refused: 답이 거절 문구인가(data/refusal.refused — 평가와 같은 판정). status=ok 턴만 0/1, cancelled·error는 NULL.
-- search_ms: 그 턴에서 search-service(/search · /embed)를 부르며 기다린 시간의 합. 부르지 않은 턴(일반 모드 · 사내규정 개인화)은 NULL.
-- 이 마이그레이션 전의 턴은 둘 다 NULL이다 — 다시 계산해 채우지 않는다(기존 행을 고치지 않는다).
-- ALGORITHM=INSTANT: 메타데이터만 바꾼다(테이블을 다시 쓰지 않는다). INSTANT로 안 되면 실패한다 — 몰래 복사로 넘어가지 않는다.

ALTER TABLE turns
    ADD COLUMN refused TINYINT(1) NULL AFTER code_rule,
    ADD COLUMN search_ms INT UNSIGNED NULL AFTER latency_ms,
    ALGORITHM=INSTANT;
