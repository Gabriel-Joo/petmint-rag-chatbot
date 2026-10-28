"""병명 없이 보장을 묻는 질문 → 원칙 + 병명 되묻기(customer_facts.disease_ask, 2026-10-28). 범위는 좁게"""

import json
import unittest
from datetime import date
from pathlib import Path

from app.services.customer_facts import disease_ask
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


if __name__ == "__main__":
    unittest.main()
