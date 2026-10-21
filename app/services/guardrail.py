"""
guardrail.py
숫자 가드레일(2026-10-21, rebuild5 준비 4b단계) — 모델 답에 나온 금액이 모델이 본 발췌·계산 카드 어디에도 없으면 표시한다.

숫자는 코드가 계산하고 모델은 조항을 설명한다는 원칙인데, 모델 답에는 여전히 금액이 나온다(한도 질문의 30만원, 법률비용 R6의
'30만원' 같은 틀린 값). 모델이 발췌에서 옮긴 금액은 발췌에 있다 — 없으면 지어냈거나 직접 계산한 것이다.
답 스트리밍이 끝난 뒤 검사해 걸리면 한 줄을 덧붙인다(이미 보낸 글자는 고칠 수 없다). 업무특화만.

금액은 'N원'(payout.amounts_in과 같은 해석, 1,000원 이상)만 본다 — 비율·일수는 보지 않는다.
"""

from app.services import payout

NOTE = "※ 답변의 {amounts}은 제공된 약관 발췌·계산 카드에서 확인되지 않는 금액입니다. 약관 원문과 계산 카드를 확인하세요."


def _card_values(card) -> set[int]:
    """계산 카드 안의 모든 금액(정수 필드, 1,000 이상) — 중첩된 줄(한도 카드 rows, 날짜별 day_rows)까지"""
    out: set[int] = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, int) and v >= 1000:
            out.add(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    if card is not None:
        walk(card.model_dump() if hasattr(card, "model_dump") else card)
    return out


def unknown_amounts(answer: str, seen_texts: list[str], card=None) -> list[int]:
    """답의 금액 중 모델이 본 글(시스템·발췌·질문)과 카드에 없는 것 — 답에 나온 순서"""
    allowed = set(_card_values(card))
    for t in seen_texts:
        allowed.update(payout.amounts_in(t))
    return [a for a in dict.fromkeys(payout.amounts_in(answer)) if a not in allowed]


def note(amounts: list[int]) -> str:
    return NOTE.format(amounts=", ".join(payout._won(a) for a in amounts))
