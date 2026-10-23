"""
test_age_code.py
신규 가입 나이 코드 답(2026-10-24, PETMINT_AGE_CODE) — 조건 셋(나이 숫자 · 신규 가입 · 재가입 아님)이 모두 맞을 때만 답한다.
걸려야 할 문장과 걸리면 안 되는 문장은 평가 220 밖에서 새로 쓴 것을 섞었다.
"""

import json
import unittest
from pathlib import Path

from app.schemas import Pet
from app.services import customer_facts as cf

FX = json.loads((Path(__file__).resolve().parent.parent / "app/fixtures/customers.json").read_text(encoding="utf-8"))
PETS = {p["name"]: Pet(**p) for c in (FX if isinstance(FX, list) else FX["customers"]) for p in c["pets"]}


class FireTest(unittest.TestCase):
    def test_c51_nine_premium(self):
        a = cf.enrollment_age_answer("까미가 9살인데 고급형으로 새로 가입할 수 있어요?", PETS["까미"])
        self.assertTrue(a.startswith("까미는 9살이라 고급형은 만 8세를 넘어 새로 가입할 수 없습니다."))
        self.assertIn("실속형으로는 가입할 수 있습니다", a)
        self.assertIn("고양이(猫)", a)

    def test_c52_eight_is_allowed(self):
        a = cf.enrollment_age_answer("보리가 8살인데 새로 가입하는 거면 고급형도 돼요?", PETS["보리"])
        self.assertIn("만 8세면 새로 가입할 수 있습니다", a)          # '초과'해야 빠진다
        self.assertNotIn("없습니다", a.split("\n")[0])

    def test_p09_over_ten(self):
        a = cf.enrollment_age_answer("열 살 넘은 강아지도 새로 가입돼요?", PETS["별이"])
        self.assertTrue(a.startswith("10살 넘은 강아지라 고급형·기본형은 만 8세를 넘어"))
        self.assertIn("실속형은 만 10세를 넘어 새로 가입할 수 없습니다", a)
        self.assertNotIn("원장의 별이", a)                          # 별이 이야기가 아니다

    def test_new_sentences(self):
        a = cf.enrollment_age_answer("두 살 강아지 신규 가입 돼요?", PETS["보리"])
        self.assertIn("만 2세면 새로 가입할 수 있습니다", a)
        a = cf.enrollment_age_answer("고양이 11살인데 실속형 가입할 수 있나요?", PETS["나비"])
        self.assertTrue(a.startswith("11살 고양이라 실속형은 만 10세를 넘어"))

    def test_ledger_age_differs(self):
        a = cf.enrollment_age_answer("까미가 7살인데 새로 가입할 수 있어요?", PETS["까미"])
        self.assertIn("원장의 까미 나이는 9세입니다", a)


class NoFireTest(unittest.TestCase):
    def test_not_new_enrollment(self):
        for q in ("망고가 10살인데 내년에도 재가입 되나요?",                  # C50
                  "10살이면 갱신 되나요?", "9살인데 계속 이어서 가입돼요?", "8살 되면 만기 연장 가입 되나요?"):
            self.assertIsNone(cf.enrollment_age_answer(q, PETS["망고"]), q)

    def test_no_age_number(self):
        for q in ("경찰견으로 일하는 개도 가입할 수 있어요?",                # S42
                  "고급형도 가입 나이 제한이 있어요?",                         # 검색 회귀 R064
                  "나이 많은 강아지도 가입되나요?"):
            self.assertIsNone(cf.enrollment_age_answer(q, PETS["별이"]), q)

    def test_age_but_not_enrollment(self):
        for q in ("9살인데 보험료 얼마예요?", "8살인데 입원비 보장돼요?", "까미가 9살인데 슬개골 수술비 나와요?"):
            self.assertIsNone(cf.enrollment_age_answer(q, PETS["까미"]), q)

    def test_no_pet(self):
        self.assertIsNone(cf.enrollment_age_answer("9살 강아지 새로 가입 돼요?", None))


if __name__ == "__main__":
    unittest.main()
