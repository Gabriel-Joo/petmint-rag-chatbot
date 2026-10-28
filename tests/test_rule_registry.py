"""코드 답 규칙 등록부(code_rules) — 순서, 규칙끼리 겹침(알려진 것 말고 새로 생기면 실패), 다음 턴이 알아보는 문구.
겹침 표는 docs/16_code_answers.md 3-1절과 같아야 한다 — 규칙을 바꾸다 새 겹침이 생기면 순서를 정하고 표와 KNOWN을 같이 고친다"""

import json
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import config
from app.services import code_rules, customer_facts, lexicon, payout
from scripts.eval_serving import pets

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["reply_turn", "not_enrolled", "annual", "needs_amount", "hypothetical", "legal", "question_turn", "limit", "age",
         "exclusion", "proviso", "named_cover", "injury_followup", "disease_ask"]
NEEDS_HISTORY = {"reply_turn", "injury_followup"}          # 앞 턴이 있어야 발동 — 단독 질문 겹침 검사에서 뺀다
KNOWN = {("올해 남은 입원 한도가 얼마예요?", ("annual", "limit")),
         ("슬개골 탈구로 입원했는데 보험금 얼마나 나와요?", ("needs_amount", "exclusion"))}   # docs/16 3-1절


def questions():
    out = []
    for c in json.loads((ROOT / "data/eval/eval220.json").read_text(encoding="utf-8"))["cases"]:
        out += [(c["pet_id"], t["query"]) for t in (c.get("turns") or [c])]
    d = json.loads((ROOT / "data/eval/disease_ask_probe.json").read_text(encoding="utf-8"))
    out += [(x["pet_id"], x["query"]) for k in ("ask", "negatives") for x in d[k]]
    out += [(x["pet_id"], t) for x in d["sequences"] for t in x["turns"]]
    return out


class Registry(unittest.TestCase):
    def test_order(self):
        self.assertEqual([r.key for r in code_rules.RULES], ORDER)

    @mock.patch.multiple(config, CUSTOMER_FACTS=True, AGE_CODE=True, COVERAGE_CODE=True, PROVISO_CODE=True, ASK_DISEASE=True,
                         NAMED_COVER=True)
    def test_overlaps_are_known(self):
        pm = pets()
        stub = SimpleNamespace(after_amount_ask=False, follow_up=None, prior_question=None, prior_answer=None)
        found = set()
        with mock.patch.object(payout, "today", return_value=date(2026, 10, 21)), \
             mock.patch.object(customer_facts.payout, "today", return_value=date(2026, 10, 21)):
            for pid, q in questions():
                inp = code_rules.Inputs(mode="업무특화", question=q, card=q, pet=pm[pid], resolved=stub, results=[], chosen=None, embed=None)
                hit = tuple(r.key for r in code_rules.RULES
                            if r.key not in NEEDS_HISTORY and r.key != "question_turn" and r.enabled(inp) and r.call(inp) is not None)
                if len(hit) > 1:
                    found.add((q, hit))
        self.assertEqual(found, KNOWN)


class Markers(unittest.TestCase):
    """다음 턴이 앞 답을 문구로 알아본다 — 문구가 바뀌면 다음 턴이 끊긴다"""

    def test_disease_ask_carries_mark(self):
        t = customer_facts.disease_ask("초코가 입원했어요. 보장되나요?", pets()["P001"], date(2026, 10, 21))
        self.assertIn(lexicon.ASKED_MARK, t)

    def test_amount_ask_text_is_known(self):
        pet = pets()["P001"]
        for q in ("입원하면 보험금 얼마 나와요?", "통원 보험금 얼마예요?"):
            self.assertIn(payout.ask_text(q, pet, None), payout.ASKS, q)


if __name__ == "__main__":
    unittest.main()
