"""
test_proviso_code.py
면책 단서 코드 답(2026-10-24, PETMINT_PROVISO_CODE) — ⑫ 침술 · ② 1년 이내 예방접종 · ⑲ 치아 외 구강질환(Ⅰ 유형).
병명·치료 말은 지금 질문에 있어야 하고, 보장을 묻는 뜻은 앞 질문까지 본다. 평가 220 밖에서 쓴 문장을 섞었다.
"""

import json
import unittest
from pathlib import Path
from unittest import mock

from app import config
from app.schemas import Pet
from app.services import customer_facts as cf

FX = json.loads((Path(__file__).resolve().parent.parent / "app/fixtures/customers.json").read_text(encoding="utf-8"))
PETS = {p["name"]: Pet(**p) for c in (FX if isinstance(FX, list) else FX["customers"]) for p in c["pets"]}


def ans(cur, pet, base=""):
    return cf.proviso_answer(cur, f"{base} {cur}".strip(), PETS[pet])


class ProvisoTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(config, "TODAY", "2026-10-21")
        p.start()
        self.addCleanup(p.stop)

    def test_acupuncture(self):
        a = ans("초코가 허리를 아파서 침을 맞았는데 보장될까요?", "초코")
        self.assertIn("침 치료라는 이유로는 보험금이 거절되지 않습니다", a)
        self.assertIn("보상합니다", a)
        self.assertIn("한약", a)                                         # 다른 대체의료는 아님
        a2 = ans("침술이면요?", "초코", "초코가 허리를 아파서 침을 맞았는데 보장될까요?")
        self.assertIn("침술은 한의학 면책", a2)

    def test_acupuncture_not(self):
        self.assertIsNone(ans("한약은요?", "보리", "보리가 관절이 안 좋아서 침 치료 받았어요. 병원비 나와요?"))
        self.assertIsNone(ans("재활치료나 한방 치료 받은 것도 병원비 보장돼요?", "보리"))
        self.assertIsNone(ans("침이 자꾸 흘러요. 병원 가야 하나요?", "보리"))
        self.assertIsNone(ans("약침 맞았는데 보장돼요?", "보리"))

    def test_vaccine_within(self):
        a = ans("초코가 파보에 걸렸는데 예방접종은 5개월 전에 했어요. 보장되나요?", "초코")
        self.assertIn("파보 바이러스 감염은 면책 대상 감염병", a)
        self.assertIn("5개월 전 접종했다면 1년 이내라 이 면책에 해당하지 않아 보상 대상입니다", a)
        a = ans("치즈가 칼리시 감염증 진단받았는데 1년 안에 접종했어요. 보상돼요?", "치즈")
        self.assertIn("고양이칼리시바이러스 감염증", a)
        self.assertIn("1년 안에 접종했다면 1년 이내라", a)

    def test_vaccine_out_or_none(self):
        a = ans("접종을 안 했으면요?", "초코", "초코가 파보에 걸렸는데 예방접종은 5개월 전에 했어요. 보장되나요?")
        self.assertIn("하지 않았다면 이 면책에 해당해 보상하지 않습니다", a)
        a = ans("디스템퍼인데 접종은 2년 전에 했어요. 보장돼요?", "보리")
        self.assertIn("1년이 지나", a)
        a = ans("파보인데 접종은 1년 전에 했어요. 보장돼요?", "보리")
        self.assertIn("1년 경계", a)

    def test_vaccine_needs_fact(self):
        self.assertIsNone(ans("파보 걸렸는데 보장돼요?", "보리"))                 # 접종 사실이 없으면 걸리지 않는다
        self.assertIsNone(ans("고양이 파보 바이러스도 특정질병 목록에 들어 있어요?", "나비"))
        self.assertIsNone(ans("칼리시인데 접종은 3개월 전에 했어요. 보장돼요?", "보리"))  # 칼리시는 반려묘 목록만

    def test_oral_type1(self):
        a = ans("콩이가 잇몸이 부어서 치료받았는데 보장돼요?", "콩이")
        self.assertTrue(a.startswith("치아를 제외한 구강질환(잇몸 염증·구내염 등)은 보장합니다"))
        self.assertIsNotNone(ans("나비 구내염 치료비 나와요?", "나비"))

    def test_oral_not(self):
        self.assertIsNone(ans("이빨 뽑는 건요?", "콩이", "콩이가 잇몸이 부어서 치료받았는데 보장돼요?"))
        self.assertIsNone(ans("보리 잇몸 치료 보장돼요?", "보리"))                  # Ⅲ 유형 — 면책 목록에 치과 항목이 없다
        self.assertIsNone(ans("잇몸 염증에 스케일링도 했는데 보장돼요?", "콩이"))

    def test_waiting_line_added(self):
        a = ans("잇몸에 염증이 생겨서 치료받았어요. 이것도 치과라 안 되나요?", "별이")
        self.assertIn("30일 이내", a)                                    # 별이는 10-01 가입 — 기준일 10-21에 대기기간 안


if __name__ == "__main__":
    unittest.main()
