"""
test_named_cover.py
병명 보장 대조(app/services/named_cover.py, PETMINT_NAMED_COVER).

- 면책 항목의 약관 글(quote)이 그 종의 의료비 특약 제2조 원문에 있다 — Ⅱ·Ⅲ에 없는 항목(type1_only)은 Ⅱ·Ⅲ 원문에 없다
- 발동은 좁게: 한 항목 · 보장 질문 · 금액·한도·접종·면책 사실·상해 없음 · 부담보 아님
- 금액 되묻기 뒤 "감기도 돼요?"는 금액 되묻기를 되풀이하지 않는다(code_rules._cover_switch)
"""

import json
import re
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import config
from app.services import code_rules, customer_facts, named_cover, payout
from scripts.eval_serving import pets

ROOT = Path(__file__).resolve().parent.parent
CHUNKS = ROOT / "data/chunks/v3"
TODAY = date(2026, 10, 21)


def flat(t: str) -> str:
    return re.sub(r"\s", "", t)


@unittest.skipUnless(CHUNKS.exists(), "청크 v3 필요")
class QuotesInPolicy(unittest.TestCase):
    def test_quotes(self):
        for sp in ("강아지", "고양이"):
            rows = json.loads((CHUNKS / f"petmint_{sp}.json").read_text(encoding="utf-8"))
            art2: dict[str, str] = {}
            for r in rows:
                if r["section_name"] and "의료비" in r["section_name"] and r["article_num"] == 2:
                    art2.setdefault(r["section_name"], "")
                    if r["content"] not in art2[r["section_name"]]:
                        art2[r["section_name"]] += r["content"]
            self.assertEqual(len(art2), 6, sp)
            for name, text in art2.items():
                type1 = not re.search(r"Ⅱ|Ⅲ", name)
                for t in named_cover.EXCLUDED:
                    if sp not in t.species:
                        continue
                    present = flat(t.quote) in flat(text)
                    self.assertEqual(present, type1 or not t.type1_only, f"{sp} {name} {t.key}")


def run(q, pid="P001", card=None, prior=None, follow_up=None):
    stub = SimpleNamespace(after_amount_ask=False, follow_up=follow_up, prior_question=None, prior_answer=prior)
    inp = code_rules.Inputs(mode="업무특화", question=q, card=card or q, pet=pets()[pid], resolved=stub, results=[], chosen=None,
                            embed=None)
    for r in code_rules.RULES:
        if r.key == "disease_ask":                       # 모델 ⑤를 부르지 않는다
            continue
        if r.enabled(inp) and (o := r.call(inp)) is not None:
            return r.key, o.text
    return None, None


@mock.patch.multiple(config, CUSTOMER_FACTS=True, AGE_CODE=True, COVERAGE_CODE=True, PROVISO_CODE=True, ASK_DISEASE=True,
                     NAMED_COVER=True)
@mock.patch.object(payout, "today", return_value=TODAY)
class Fires(unittest.TestCase):
    def test_not_on_list(self, _):
        key, text = run("감기도 보장되나요?")
        self.assertEqual(key, "named_cover")
        self.assertIn("면책 목록에 없어", text)
        self.assertIn("예방접종 기록", text)                 # 감기 — 파라인플루엔자 등으로 진단되면
        self.assertIn("상병명", text)

    def test_on_list(self, _):
        self.assertIn("보상하지 않습니다", run("콩이 중성화 수술도 보장되나요?", "P005")[1])
        self.assertIn("예방접종 기록", run("초코가 파보 걸렸는데 보장돼요?")[1])
        self.assertEqual(run("고양이 백혈병인데 보장되나요?", "P001"), (None, None))      # 반려견에는 없는 항목

    def test_type1_only(self, _):
        self.assertEqual(run("콩이 서혜부 탈장 수술 보장되나요?", "P005")[0], "named_cover")   # Ⅰ 특약
        self.assertIsNone(run("초코 서혜부 탈장 수술 보장되나요?", "P001")[0])               # Ⅱ 특약에는 없다 → 모델

    def test_waiting_first(self, _):
        text = run("별이가 장염으로 입원했어요 보험 되나요?", "P013")[1]
        self.assertIn("대기기간이 지난 뒤 발생했다면", text.split("\n")[0])
        self.assertIn("30일", text.split("\n")[1])

    def test_not_fired(self, _):
        for q in ("감기로 3일 입원했고 50만원 나왔는데 얼마 받아요?", "감기 걸리면 통원 몇 번까지 보장돼요?",
                  "태풍 때 비 맞고 감기 걸렸는데 보장되나요?", "감기 치료비 청구는 어떻게 해요?", "초코 장염이랑 피부염 둘 다 보장되나요?",
                  "감기 예방접종 비용도 보장되나요?", "감기 걸렸어요", "산책하다 다쳐서 감기도 걸렸는데 보장돼요?"):
            self.assertNotEqual(run(q)[0], "named_cover", q)

    def test_others_first(self, _):
        self.assertEqual(run("슬개골 탈구도 보장되나요?")[0], "exclusion")                          # 부담보
        self.assertEqual(run("파보 예방접종 6개월 전에 했는데 파보 걸리면 보장돼요?")[0], "proviso")

    def test_reply_after_disease_ask(self, _):
        prior = customer_facts.disease_ask("치즈가 입원했는데 보험 되나요?", pets()["P004"], TODAY)
        key, text = run("감기예요", "P004", card="치즈가 입원했는데 보험 되나요? 감기예요", prior=prior, follow_up="짧음")
        self.assertEqual(key, "named_cover")
        self.assertIn("입원의료비", text)
        self.assertNotIn("통원의료비", text)
        self.assertIsNone(run("감기예요", "P004")[0])                                              # 앞 턴이 되묻기가 아니면

    def test_after_amount_ask(self, _):
        q0 = "초코가 입원했는데 보험금 얼마나 나와요?"
        ask = payout.ask_text(q0, pets()["P001"], None)
        key, text = run("감기도 돼요?", card=f"{q0} 감기도 돼요?", prior=ask, follow_up="짧음")
        self.assertEqual(key, "named_cover")
        self.assertIn("입원의료비", text)
        key, _ = run("치료비는 50만원이에요", card=f"{q0} 치료비는 50만원이에요", prior=ask, follow_up="금액만")
        self.assertNotEqual(key, "named_cover")

    def test_off_by_default(self, _):
        with mock.patch.object(config, "NAMED_COVER", False):
            q0 = "초코가 입원했는데 보험금 얼마나 나와요?"
            ask = payout.ask_text(q0, pets()["P001"], None)
            self.assertEqual(run("감기도 돼요?", card=f"{q0} 감기도 돼요?", prior=ask, follow_up="짧음")[0], "needs_amount")
            self.assertIsNone(run("감기도 보장되나요?")[0])


if __name__ == "__main__":
    unittest.main()
