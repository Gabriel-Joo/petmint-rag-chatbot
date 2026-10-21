"""
test_code_cards.py
한도·법률비용 카드 턴의 코드 답과 가정 등급·유형 질문(2026-10-21, rebuild5 직전 6·7번).
"""

import unittest

from tests.test_stage4 import DOG, DUBU, HAPPY, ON, pet
from app.services import payout

CAT = "펫퍼민트 반려묘 "
KAMI = pet("까미", (CAT + "통원의료비Ⅱ보장 특별약관", "실속형", 50000), (CAT + "입원의료비Ⅱ보장 특별약관", "실속형", 50000), species="고양이")
CHOCO = pet("초코", (DOG + "통원의료비Ⅱ보장 특별약관", "고급형", 30000), (DOG + "입원의료비Ⅱ보장 특별약관", "고급형", 30000))
LEGAL = pet("보리", (DOG + "통원의료비보장 특별약관", "고급형", 30000), ("민사소송법률비용Ⅱ보장 특별약관", None, None))


class LimitAnswer(unittest.TestCase):
    def test_annual_remaining(self):
        card = payout.limit_card("입원 하루 한도가 얼마예요?", HAPPY, on=ON)
        self.assertEqual(card.rows[0].annual_remaining, 5_000_000 - 4_745_000)
        self.assertIn("남은 25만 5,000원", payout.limit_answer(card, HAPPY, "입원 하루 한도가 얼마예요?"))

    def test_new_words(self):
        for q in ("보상비율이 몇 퍼센트예요?", "자기부담금이 얼마예요?"):
            self.assertIsNotNone(payout.limit_card(q, CHOCO, on=ON), q)
        self.assertIn("**70%**", payout.limit_answer(payout.limit_card("보상비율이 몇 퍼센트예요?", CHOCO, on=ON), CHOCO, "보상비율이 몇 퍼센트예요?"))
        self.assertIsNone(payout.limit_card("보험료가 얼마예요?", CHOCO, on=ON))

    def test_surgery_lead(self):
        q = "수술하면 하루 얼마까지 나와요?"
        self.assertTrue(payout.limit_answer(payout.limit_card(q, CHOCO, on=ON), CHOCO, q).startswith("수술한 날은 1일 **250만원**"))

    def test_references(self):
        card = payout.limit_card("통원 하루 한도가 얼마예요?", CHOCO, on=ON)
        self.assertEqual([(r.section_name, r.article_num) for r in payout.code_references(card, CHOCO, "")],
                         [(DOG + "통원의료비Ⅱ보장 특별약관", 1)])


class Hypothetical(unittest.TestCase):
    def test_other_grade(self):
        q = "기본형이었으면 통원 하루 한도가 얼마였어요?"
        card = payout.hypothetical_card(q, pet("별이", (DOG + "통원의료비보장 특별약관", "고급형", 30000)))
        self.assertTrue(card.hypothetical)
        self.assertEqual((card.rows[0].coverage_type, card.rows[0].non_surgery), ("기본형", 150_000))

    def test_rate_compare(self):
        q = "고급형으로 바꾸면 보상비율이 올라가요?"
        a = payout.limit_answer(payout.hypothetical_card(q, KAMI), KAMI, q)
        self.assertIn("보상비율 50%", a)
        self.assertIn("**70%**", a)

    def test_other_type_mri(self):
        q = "Ⅲ유형이었으면 MRI는 따로 한도가 있었어요?"
        card = payout.hypothetical_card(q, CHOCO)
        self.assertTrue(all(r.type == "Ⅲ" and r.mri_1st for r in card.rows))
        self.assertEqual(payout.code_references(card, CHOCO, q), [])

    def test_same_as_enrolled_is_not_hypothetical(self):
        self.assertIsNone(payout.hypothetical_card("고급형 통원 하루 한도가 얼마예요?", CHOCO))
        self.assertIsNone(payout.hypothetical_card("통원 하루 한도가 얼마예요?", CHOCO))
        self.assertIsNone(payout.hypothetical_card("기본형이었으면 통원 치료비 50만원은 얼마 나와요?", CHOCO))

    def test_missing_setting_left_to_not_enrolled(self):
        self.assertIsNone(payout.limit_card("입원하면 하루에 얼마까지 나와요?", DUBU))


class LegalAnswer(unittest.TestCase):
    def test_no_won_amount(self):
        card = payout.legal_card("1억짜리 소송이면 인지액이 얼마예요?", LEGAL)
        self.assertEqual((card.claim_value, card.stamp), (100_000_000, 455_000))
        self.assertIn("소송목적의 값이 1억원", payout.legal_answer(card))

    def test_lawyer(self):
        card = payout.legal_card("소송 금액이 3천만원이면 변호사비는 얼마까지예요?", LEGAL)
        a = payout.legal_answer(card)
        self.assertIn("**280만원**", a)
        self.assertEqual([r.citation_label for r in payout.code_references(card, LEGAL, "")][:2],
                         ["제3조(보험금 지급에 관한 세부규정)", "【별표3】 소송목적의 값에 따른 변호사비용"])

    def test_service(self):
        self.assertIn("**13만 2,000원**", payout.legal_answer(payout.legal_card("항소하면 송달료는요?", LEGAL)))


if __name__ == "__main__":
    unittest.main()
