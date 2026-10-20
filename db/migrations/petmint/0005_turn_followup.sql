-- 0005_turn_followup.sql — 멀티턴(09번 5절). 후속 질문을 어떻게 처리했는지와 되묻기로 고른 특약을 턴에 남긴다.
-- rewritten_question(0001부터 있음)에는 기준 질문을 둔다 — 사내규정은 베이스 모델이 재작성한 질문,
-- 업무특화는 앞 턴 기준 질문에 이번 후속의 통원/입원·등급·유형 낱말을 갈아 끼운 것. 다음 후속 턴이 이 값을 이어 쓴다.
-- follow_up: 후속으로 본 규칙(지시어·생략 꼬리·금액만·짧음). NULL이면 단독 질문
-- context_kind: rewrite(사내규정) / concat(업무특화, 앞 질문과 이어 붙여 검색) / history(일반, 이력 전달). context_turns: 이력 턴 수
-- chosen_section: 되묻기로 고르거나 앞 턴에서 이어 쓴 특약 — 다음 후속 턴이 다시 묻지 않게

ALTER TABLE turns
    ADD COLUMN follow_up VARCHAR(20) NULL AFTER rewritten_question,
    ADD COLUMN context_kind ENUM('rewrite', 'concat', 'history') NULL AFTER follow_up,
    ADD COLUMN context_turns SMALLINT NULL AFTER context_kind,
    ADD COLUMN chosen_section VARCHAR(200) NULL AFTER clarified;
