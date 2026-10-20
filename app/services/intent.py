"""
intent.py
금액 되묻기 ① "받을 금액을 묻는가" — 금액 낱말 + 임베딩(KURE, search-service /embed). payout.needs_amount가 쓴다.

규칙(표현 목록 정규식)은 "보상받을 수 있는 금액은?", "얼마 정도 돌려받을 수 있을까요?", "청구하면 얼마 들어와요?"처럼
조금만 달라도 놓쳤다. 임베딩만 쓰면 반대로 주제가 같은 "되나요" 질문("중성화 수술도 수술비로 나오나요?")을 잡았다 —
임베딩은 주제는 잘 잡지만 "얼마냐"와 "되냐"를 거의 가르지 못한다. 그래서 둘을 겹친다:
1. 금액 낱말(얼마·금액·액수·몇 만원)이 있어야 한다 — 넓게 거른다
2. 받을 금액을 묻는 예시(POSITIVE)와 금액 낱말이 있어도 다른 것을 묻는 예시(NEGATIVE)에 대한 최대 유사도 차이가
   THRESHOLD보다 커야 한다

2026-10-21 측정(예시와 겹치지 않는 시험 문장, CPU KURE): 되물어야 14 중 14(규칙 9), 되물으면 안 될 20 중 0(규칙 1),
단독 약관 질문 114 중 0(규칙 0). 임계값은 금액 낱말이 있는 음성 최대(+0.003, "부담보 걸리면 그 병은 얼마 동안 보장이
안 돼요?")와 양성 최소(+0.045, "MRI 찍었는데 보험금 얼마예요?")의 가운데 — 양쪽 여유가 0.02로 얇다.
search-service에 닿지 않으면 규칙(payout._ASK_MONEY)으로 돌아간다.
"""

import logging
import re
from typing import Callable

log = logging.getLogger(__name__)

AMOUNT_WORD = re.compile(r"얼마|금액|액수|몇\s*(?:십|백|천)?\s*만\s*원")
POSITIVE = ["보험금 얼마나 나와요?", "얼마 받을 수 있어요?", "보상받을 금액이 얼마예요?", "보험 처리하면 얼마 나와요?",
            "치료받았는데 보험금 얼마나 돼요?", "병원비 중에 얼마를 돌려받을 수 있어요?", "수술했는데 얼마나 보상돼요?",
            "청구하면 얼마 받아요?"]
NEGATIVE = ["이것도 보장되나요?", "한도가 얼마예요?", "보험료가 얼마예요?", "해지하면 환급금이 얼마예요?", "자기부담금이 얼마예요?",
            "보험금은 언제 들어와요?", "보상비율이 몇 퍼센트예요?", "청구 서류는 뭐가 필요해요?", "몇 번까지 청구할 수 있어요?",
            "며칠까지 보장돼요?"]
THRESHOLD = 0.025

Embed = Callable[[list[str]], list[list[float]]]
_protos: tuple[list[list[float]], list[list[float]]] | None = None   # 예시 벡터 — 처음 한 번 받아 둔다


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def amount_score(question: str, embed: Embed) -> float:
    """(받을 금액을 묻는 예시와의 최대 유사도) − (다른 것을 묻는 예시와의 최대 유사도). 벡터는 정규화돼 있어 내적 = 코사인"""
    global _protos
    if _protos is None:
        vecs = embed(POSITIVE + NEGATIVE)
        _protos = (vecs[:len(POSITIVE)], vecs[len(POSITIVE):])
    q = embed([question])[0]
    pos, neg = _protos
    return max(_dot(q, p) for p in pos) - max(_dot(q, n) for n in neg)


def asks_amount(question: str, embed: Embed | None) -> bool | None:
    """받을 금액을 묻는가. 금액 낱말이 없으면 False(임베딩을 부르지 않는다). 임베딩을 못 쓰면 None — 부르는 쪽이 규칙으로 판단"""
    if not AMOUNT_WORD.search(question):
        return False
    if embed is None:
        return None
    try:
        return amount_score(question, embed) > THRESHOLD
    except Exception:
        log.warning("금액 의도 임베딩 실패 — 규칙으로 판단한다", exc_info=True)
        return None
