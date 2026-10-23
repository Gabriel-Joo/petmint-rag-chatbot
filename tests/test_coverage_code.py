"""
test_coverage_code.py
3안(2026-10-23) — 보장 여부 질문에서 부담보·대기기간 안은 코드가 답한다. 부담보는 기간이 원장에 없어 약관 범위만 말한다.
"""

import json
import unittest
from datetime import date
from pathlib import Path

from app.schemas import Pet
from app.services import customer_facts as cf

FX = json.loads((Path(__file__).resolve().parent.parent / "app/fixtures/customers.json").read_text(encoding="utf-8"))
PETS = {p["name"]: Pet(**p) for c in (FX if isinstance(FX, list) else FX["customers"]) for p in c["pets"]}
TODAY = date(2026, 10, 23)


class ExclusionTest(unittest.TestCase):
    def test_leo_urinary(self):
        a = cf.exclusion_answer("비뇨기 질환도 보장 돼요?", PETS["레오"])
        self.assertIn("레오는 비뇨기과질환이 부담보", a)
        self.assertIn("1개월부터 5년 또는 계약의 보험기간", a)       # 영구도 90일도 아니다
        self.assertIn("대기기간과는 별개", a)
        self.assertNotIn("영구", a)

    def test_with_waiting_note(self):
        a = cf.exclusion_answer("초코 슬관절 탈구는 언제부터 보장돼요?", PETS["초코"])
        self.assertIn("부담보", a)
        self.assertIn("1년 이내", a)                                    # 대기기간도 함께(C27)

    def test_classification_question_goes_to_model(self):
        self.assertIsNone(cf.exclusion_answer("무릎뼈 빠지는 것도 특정질병이에요?", PETS["초코"]))   # P49

    def test_not_matched(self):
        self.assertIsNone(cf.exclusion_answer("레오가 감기에 걸려서 입원했는데 보장이 되나요?", PETS["레오"]))
        self.assertIsNone(cf.exclusion_answer("방광염 보장돼요?", PETS["나비"]))   # 나비는 부담보 없음


class WaitingTest(unittest.TestCase):
    def test_within_30_days(self):
        a = cf.waiting_answer("별이가 어제 장염으로 통원했는데 보장되나요?", PETS["별이"], TODAY)
        self.assertTrue(a.startswith("별이는 2026-10-01 가입이라 보장개시일부터 30일 이내"))

    def test_after_waiting_goes_to_model(self):
        self.assertIsNone(cf.waiting_answer("레오가 감기에 걸려서 입원했는데 보장이 되나요?", PETS["레오"], TODAY))

    def test_not_coverage_question(self):
        self.assertIsNone(cf.waiting_answer("장염은 어떤 병이에요?", PETS["별이"], TODAY))


if __name__ == "__main__":
    unittest.main()
