"""병명 없이 보장을 묻는 질문 → 원칙 + 병명 되묻기(customer_facts.disease_ask, 2026-10-28). 범위는 좁게"""

import json
import unittest
from datetime import date
from pathlib import Path

from app.services.customer_facts import disease_ask, injury_followup
from scripts.eval_serving import pets

ROOT = Path(__file__).resolve().parent.parent
PM = pets()
ON = date(2026, 10, 21)


class Trigger(unittest.TestCase):
    def test_probe_set(self):
        d = json.loads((ROOT / "data/eval/disease_ask_probe.json").read_text(encoding="utf-8"))
        for c in d["ask"]:
            self.assertIsNotNone(disease_ask(c["query"], PM[c["pet_id"]], ON), c["query"])
        for c in d["negatives"]:
            self.assertIsNone(disease_ask(c["query"], PM[c["pet_id"]], ON), c["query"])

    def test_eval220_only_l02_l14(self):
        cs = json.loads((ROOT / "data/eval/eval220.json").read_text(encoding="utf-8"))["cases"]
        hit = sorted(t["id"] for c in cs for t in (c.get("turns") or [c]) if disease_ask(t["query"], PM[c["pet_id"]], ON))
        self.assertEqual(hit, ["L02", "L14"])


class Text(unittest.TestCase):
    def test_rider_and_question(self):
        t = disease_ask("초코가 입원했어요. 보험이 되나요?", PM["P001"], ON)
        self.assertIn("입원의료비Ⅱ 고급형 특약으로 보상됩니다", t)
        self.assertIn("어떤 질병이나 상해로 입원했는지", t)
        self.assertNotIn("통원", t)

    def test_waiting_period_note(self):
        t = disease_ask("솜이 다쳐서 병원 갔는데 보상되나요?", PM["P015"], ON)
        self.assertIn("발병일도 함께", t)
        self.assertIn("어떤 질병이나 상해로 치료받았는지", t)


class ModelNameCheck(unittest.TestCase):
    """B안(2026-10-28) — ⑤를 모델(name_check)로. 모델이 없으면 정규식, 면책 사실은 코드가 막는다"""
    Q = "초코가 입원했는데 보험 보장되는지 확인 부탁드려요."      # 정규식 ⑤는 '확인·부탁'이 남아 되묻지 않는다

    def test_model_no_name_asks(self):
        self.assertIsNone(disease_ask(self.Q, PM["P001"], ON))
        self.assertIsNotNone(disease_ask(self.Q, PM["P001"], ON, name_check=lambda q, n: False))

    def test_model_says_name(self):
        self.assertIsNone(disease_ask("초코가 입원했어요. 보장되나요?", PM["P001"], ON, name_check=lambda q, n: True))

    def test_model_unavailable_falls_back_to_regex(self):
        self.assertIsNotNone(disease_ask("초코가 입원했어요. 보장되나요?", PM["P001"], ON, name_check=lambda q, n: None))
        self.assertIsNone(disease_ask(self.Q, PM["P001"], ON, name_check=lambda q, n: None))

    def test_exempt_fact_blocks(self):
        for q in ("달이 데리고 일본 갔다가 거기서 다쳤어요. 병원 갔는데 보장되나요?", "태풍 때 다쳐서 입원했는데 보상되나요?"):
            self.assertIsNone(disease_ask(q, PM["P014"], ON, name_check=lambda q, n: False), q)


class InjuryFollowUp(unittest.TestCase):
    """되물은 뒤 상해로 답한 턴(2026-10-28) — 탐침 DS3 "산책하다 다리를 다쳤어요"는 따로 검색돼 장해분류표를 받고 거절했다"""

    def reply(self, pid, q1, q2):
        return injury_followup(q2, q1, disease_ask(q1, PM[pid], ON) or "(되묻기 아님)", PM[pid], ON)

    def test_fires(self):
        for pid, q1, q2 in [("P015", "솜이 다쳐서 병원 갔는데 보상되나요?", "산책하다 다리를 다쳤어요"),
                            ("P001", "초코가 입원했어요. 보장되나요?", "계단에서 떨어져서 다리가 부러졌어요"),
                            ("P004", "치즈 입원했는데 보험 되나요?", "다른 고양이한테 물렸어요"),
                            ("P013", "별이가 입원했어요 보장되나요?", "뜨거운 물에 화상 입었어요")]:
            self.assertIsNotNone(self.reply(pid, q1, q2), q2)

    def test_does_not_fire(self):
        for pid, q1, q2 in [("P004", "치즈 입원했는데 보험 되나요?", "감기예요"),
                            ("P001", "초코가 입원했어요. 보장되나요?", "슬개골이 빠졌어요"),
                            ("P005", "콩이가 통원 치료 받았는데 보장돼요?", "산책하다 넘어져서 슬개골 탈구됐어요"),
                            ("P015", "솜이 다쳐서 병원 갔는데 보상되나요?", "태풍 때 날아온 물건에 다쳤어요"),
                            ("P015", "솜이 다쳐서 병원 갔는데 보상되나요?", "다쳤는데 치료비 30만원이에요"),
                            ("P001", "초코 슬개골 수술했는데 보장되나요?", "산책하다 다쳤어요")]:      # 앞 답이 되묻기 아님
            self.assertIsNone(self.reply(pid, q1, q2), q2)

    def test_text(self):
        t = self.reply("P013", "별이가 입원했어요 보장되나요?", "뜨거운 물에 화상 입었어요")
        self.assertIn("입원의료비", t)
        self.assertIn("30일이 지나지 않았지만", t)
        self.assertIn("입원 일수와 치료비 총액을 알려", t)


if __name__ == "__main__":
    unittest.main()
