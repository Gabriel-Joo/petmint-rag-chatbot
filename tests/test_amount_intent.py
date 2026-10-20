"""
test_amount_intent.py
intent.asks_amount — 금액 낱말 + 임베딩. 실제 KURE 대신 가짜 임베딩으로 흐름만 본다(낱말이 없으면 부르지 않음,
임계값, 실패하면 None → payout이 규칙으로). 실제 점수 측정은 intent.py 머리말(2026-10-21).
"""

import unittest

from app.services import intent, payout
from tests.test_ask_amount import CHEESE


def fake_embed(dim_of):
    """문장 → 한 축만 1인 벡터. 같은 축이면 유사도 1, 다르면 0"""
    calls = []
    def embed(texts):
        calls.append(list(texts))
        out = []
        for t in texts:
            v = [0.0] * 4
            v[dim_of(t)] = 1.0
            out.append(v)
        return out
    embed.calls = calls
    return embed


def axis(t: str) -> int:
    if t in intent.POSITIVE or "받" in t:
        return 0
    if t in intent.NEGATIVE or "기간" in t:
        return 1
    return 2


class AmountIntent(unittest.TestCase):
    def setUp(self):
        intent._protos = None                    # 예시 벡터 캐시를 시험마다 비운다

    def test_no_amount_word_skips_embedding(self):
        e = fake_embed(axis)
        self.assertFalse(intent.asks_amount("슬개골 수술도 보험금 나오나요?", e))
        self.assertEqual(e.calls, [])

    def test_threshold(self):
        e = fake_embed(axis)
        self.assertTrue(intent.asks_amount("보상받을 수 있는 금액은?", e))      # 양성 축 — 차이 1
        self.assertFalse(intent.asks_amount("보장 기간이 얼마나 돼요?", e))     # 음성 축 — 차이 -1
        self.assertFalse(intent.asks_amount("얼마예요?", e))                     # 어느 쪽도 아님 — 차이 0 < 임계값

    def test_failure_falls_back_to_rule(self):
        def broken(texts):
            raise RuntimeError("search-service down")
        self.assertIsNone(intent.asks_amount("보상받을 수 있는 금액은?", broken))
        self.assertFalse(payout.needs_amount("보상받을 수 있는 금액은?", CHEESE, broken))          # 규칙은 이 표현을 놓친다
        self.assertTrue(payout.needs_amount("보험금 얼마나 받을 수 있어요?", CHEESE, broken))     # 규칙이 잡는 표현

    def test_gates_before_embedding(self):
        """②~⑤(치료비 금액·한도·법률·다른 돈)는 규칙 — 걸리면 임베딩을 부르지 않는다"""
        e = fake_embed(axis)
        for q in ["치료비 50만원인데 얼마 받아요?", "하루 한도가 얼마예요?", "보험료 얼마예요?", "소송하면 얼마 받아요?"]:
            self.assertFalse(payout.needs_amount(q, CHEESE, e), q)
        self.assertEqual(e.calls, [])


if __name__ == "__main__":
    unittest.main()
