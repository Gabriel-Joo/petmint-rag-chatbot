-- petmint 0008_turn_code_rule.sql — 턴마다 답한 코드 규칙을 남긴다(2026-10-29, docs/16 5절 1단계).
-- 운영 질문 글을 밖으로 내지 않고 규칙별 발동·거절·👎를 숫자로만 세려고(scripts.rule_report, 클러스터 안에서 돈다).
-- code_rule: code_rules.Rule.key(reply_turn·not_enrolled·…·disease_ask) 또는 hr_personal. NULL이면 모델이 답한 턴.
-- 이 마이그레이션 전의 턴도 NULL이다 — 집계는 배포 시각 이후 턴만 본다(모델 답과 구분되지 않으므로).

ALTER TABLE turns
    ADD COLUMN code_rule VARCHAR(32) NULL AFTER clarified;
