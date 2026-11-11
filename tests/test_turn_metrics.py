"""
test_turn_metrics.py
turns.refused · turns.search_ms(0009, 2026-11-11) — Grafana 거절률 · 검색 지연 패널이 읽는 두 칸.

- refused: ok 턴만 data/refusal.refused(평가와 같은 판정), cancelled · error는 None
- search_ms: TimedRetriever가 턴마다 search-service 시간을 더한다. 부르지 않은 턴은 None, 실패한 호출도 기다린 시간은 더한다
- 리트리버를 함께 써도 턴끼리 섞이지 않는다(턴마다 껍데기를 씌운다)
"""

import time
import unittest
from types import SimpleNamespace

import httpx

from app.services import answer


class FakeRetriever:
    expand = True

    def search(self, query, scope, top_k=5, candidate_k=20):
        time.sleep(0.02)
        return [{"q": query}]

    def embed(self, texts):
        time.sleep(0.01)
        return [[0.0] for _ in texts]


class Failing(FakeRetriever):
    def search(self, *a, **k):
        time.sleep(0.01)
        raise httpx.ConnectError("x")


class TimedRetrieverTest(unittest.TestCase):
    def test_sums_search_and_embed(self):
        ctx = SimpleNamespace(search_s=None)
        t = answer.TimedRetriever(FakeRetriever(), ctx)
        self.assertEqual(t.search("q", None), [{"q": "q"}])
        t.embed(["a", "b"])
        self.assertGreaterEqual(ctx.search_s, 0.03)
        self.assertLess(ctx.search_s, 0.5)

    def test_untouched_turn_stays_none(self):
        ctx = SimpleNamespace(search_s=None)
        answer.TimedRetriever(FakeRetriever(), ctx)
        self.assertIsNone(ctx.search_s)

    def test_turns_do_not_mix(self):
        shared = FakeRetriever()
        a, b = SimpleNamespace(search_s=None), SimpleNamespace(search_s=None)
        answer.TimedRetriever(shared, a).search("q", None)
        self.assertIsNone(b.search_s)

    def test_failed_call_still_counted(self):
        ctx = SimpleNamespace(search_s=None)
        with self.assertRaises(httpx.ConnectError):
            answer.TimedRetriever(Failing(), ctx).search("q", None)
        self.assertGreater(ctx.search_s, 0)

    def test_passes_other_attributes(self):
        self.assertTrue(answer.TimedRetriever(FakeRetriever(), SimpleNamespace(search_s=None)).expand)


class TurnLogFieldsTest(unittest.TestCase):
    def ctx(self, ans, search_s=None):
        session = SimpleNamespace(session_id="S", mode="일반")
        return answer.TurnContext(turn_id="T", session=session, pet=None, scope=None, question="q", agent="a",
                                  answer=ans, search_s=search_s)

    def test_refused_only_for_ok(self):
        refuse = "제공된 약관 발췌에서는 확인되지 않는 내용입니다."
        self.assertIs(answer._turn_log(self.ctx(refuse), "ok", [], [], []).refused, True)
        self.assertIs(answer._turn_log(self.ctx("통원 1일 한도는 15만 원입니다."), "ok", [], [], []).refused, False)
        self.assertIsNone(answer._turn_log(self.ctx(refuse), "cancelled", [], [], []).refused)
        self.assertIsNone(answer._turn_log(self.ctx(refuse), "error", [], [], []).refused)

    def test_search_ms(self):
        self.assertIsNone(answer._turn_log(self.ctx("a"), "ok", [], [], []).search_ms)
        self.assertEqual(answer._turn_log(self.ctx("a", 0.1234), "ok", [], [], []).search_ms, 123)


if __name__ == "__main__":
    unittest.main()
