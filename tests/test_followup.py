"""
test_followup.py
followup.follow_up_reason — 후속 질문 규칙. 혼자서 이해되는 질문은 하나도 후속으로 잡히면 안 된다(평가·검증 질문 전부).
"""

import json
import unittest
from pathlib import Path

from app.services.followup import follow_up_reason

ROOT = Path(__file__).resolve().parent.parent

FOLLOW = {"그럼 입원은요?": "지시어", "1년 지나면요?": "생략 꼬리", "치료비는 35만원 나왔어요": "금액만", "언제 들어와요?": "짧음",
          "그 다음엔요?": "지시어", "그럼 언제 튜플을 써?": "지시어", "수술하면요?": "생략 꼬리", "고양이는요?": "생략 꼬리",
          "그건 얼마예요?": "지시어", "기본형이면요?": "생략 꼬리", "그것도 보장돼요?": "지시어", "50만원이요": "금액만"}
TOPIC_CHANGE = ["해외에서 다친 것도 나오나요?", "보험료는 언제 빠져나가요?", "회사 주차장은 몇 시까지 쓸 수 있나요?"]
KNOWN_MISSES = ["신청은 언제까지 해야 돼요?", "언제까지 써야 해요?"]   # 받아들인 한계 — 단독 처리


def standalone_questions(names: tuple[str, ...] = ("search_regression.json", "search_regression_hr.json"),
                         modes: tuple[str, ...] = ("hr", "general", "rag")) -> list[str]:
    qs = []
    for name in names:
        qs += [c["query"] for c in json.loads((ROOT / "data" / "eval" / name).read_text(encoding="utf-8"))["cases"]]
    from scripts.verify_cases import MODES
    # 일부러 만든 후속 질문(expect_context가 있는 것 — G4·HR20·R12·R13·R15)은 뺀다
    qs += [c.question for k, m in MODES.items() if k in modes for c in m.cases if not c.expect_context]
    return qs


class FollowUp(unittest.TestCase):
    def test_follow_ups(self):
        for q, why in FOLLOW.items():
            self.assertEqual(follow_up_reason(q), why, q)

    def test_standalone_never_follow_up(self):
        wrong = [(q, follow_up_reason(q)) for q in standalone_questions() + TOPIC_CHANGE if follow_up_reason(q)]
        self.assertEqual(wrong, [])

    def test_known_misses(self):
        for q in KNOWN_MISSES:
            self.assertIsNone(follow_up_reason(q))

    def test_g4_is_follow_up(self):
        self.assertEqual(follow_up_reason("그럼 언제 튜플을 써?"), "지시어")


if __name__ == "__main__":
    unittest.main()
