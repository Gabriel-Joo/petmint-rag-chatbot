-- 0004_turn_payout.sql — 계산 카드(09번 2-3절) 결과를 턴에 저장할 자리. 지금은 NULL, WS 메시지와 계산 로직을 붙일 때 채운다.
-- 재계산이 아니라 저장인 이유(12번 2-2절 스냅샷): limit_table이나 약관이 개정되면 같은 scope로도 다른 숫자가 나온다 —
-- "그때 5만원이라고 안내했다"가 재현되어야 한다. 모양이 아직 정해지지 않아 JSON으로 둔다.

ALTER TABLE turns
    ADD COLUMN payout JSON NULL AFTER answer;
