"""
test_ask_amount.py
payout.needs_amount — 금액 되묻기 다섯 조건. 평가·검증 질문은 하나도 걸리면 안 된다(그 질문들은 금액을 묻지 않거나 금액이 있다).
"""

import unittest

from app.schemas import Pet, Policy
from app.services import payout
from tests.test_followup import standalone_questions

CAT = "펫퍼민트 반려묘 "
CHEESE = Pet.model_construct(pet_id="P004", name="치즈", species="고양이", breed=None, age=None, policies=[
    Policy.model_construct(section_name=CAT + "통원의료비Ⅱ보장 특별약관", coverage_type="고급형", copay=30000, excluded_conditions=[]),
    Policy.model_construct(section_name=CAT + "입원의료비Ⅱ보장 특별약관", coverage_type="고급형", copay=30000, excluded_conditions=[])])
LEGAL_ONLY = Pet.model_construct(pet_id="P", name="x", species="고양이", breed=None, age=None, policies=[
    Policy.model_construct(section_name="민사소송법률비용Ⅱ보장 특별약관", coverage_type=None, copay=None, excluded_conditions=[])])

ASK = ["저희 고양이가 감기로 입원했는데 보험금 얼마나 나올 수 있나요?", "수술했는데 얼마 받을 수 있어요?", "MRI 찍었는데 보험금 얼마예요?",
       "입원 3일 했는데 얼마 나와요?", "통원 치료 받았는데 얼마 보상돼요?", "다리 골절로 병원 다녀왔는데 얼마나 받아요?",
       "보험금 얼마나 받을 수 있어요?"]
DONT = ["보험료 얼마예요?", "해지하면 얼마 돌려받아요?", "자기부담금 얼마예요?", "수술 한도 얼마예요?", "통원하면 얼마까지 나와요?",
        "MRI는 몇 번까지 돼요?", "입원 며칠까지 보장돼요?", "보상비율이 몇 %예요?", "치료비 50만원인데 얼마 받아요?",
        "슬개골 수술도 보험금 나오나요?", "감기로 입원해도 보장되나요?", "입원하면 하루에 최대 얼마예요?", "중도인출 하면 얼마까지 돼요?",
        "연간 몇 번까지 청구할 수 있어요?", "입원비 30만원 나왔어요 얼마 받죠?", "보험금은 언제 들어와요?",
        "소송 걸리면 변호사비는 한 건에 얼마나 나와요?"]


class AskAmount(unittest.TestCase):
    def test_ask(self):
        for q in ASK:
            self.assertTrue(payout.needs_amount(q, CHEESE), q)

    def test_dont(self):
        self.assertEqual([q for q in DONT if payout.needs_amount(q, CHEESE)], [])

    def test_eval_and_verify_questions(self):
        """약관 질문(회귀 103 + 업무특화 검증) — 금액 되묻기는 반려동물이 있는 업무특화에서만 돈다"""
        from scripts.verify_cases import RAG
        # 일부러 되묻게 만든 질문(R14·R16·R18·R21·R24·R27) — 되묻기 문장의 "입원 일수"를 정답으로 둔 것
        meant = {c.question for c in RAG.cases if any("입원 일수" in w for group in c.must_include for w in group)}
        qs = [q for q in standalone_questions(names=("search_regression.json",), modes=("rag",)) if q not in meant]
        self.assertEqual([q for q in qs if payout.needs_amount(q, CHEESE)], [])
        self.assertEqual([q for q in meant if not payout.needs_amount(q, CHEESE)], [])

    def test_coverage_amount_is_limit(self):
        """'보장 얼마나'는 한도 질문 — 되묻지 않고 한도 카드"""
        q = "MRI 찍으면 보장 얼마나 돼요?"
        self.assertFalse(payout.needs_amount(q, CHEESE))
        self.assertIsNotNone(payout.limit_card(q, CHEESE))

    def test_no_medical_policy(self):
        self.assertFalse(payout.needs_amount(ASK[0], LEGAL_ONLY))
        self.assertFalse(payout.needs_amount(ASK[0], None))

    def test_follow_up_with_amount(self):
        """멀티턴 — 다음 턴 '치료비는 35만원 나왔어요'는 기준 질문과 이어 붙어(card_text) 금액이 생기니 다시 묻지 않는다"""
        self.assertFalse(payout.needs_amount(ASK[0] + " 치료비는 35만원 나왔어요", CHEESE))


if __name__ == "__main__":
    unittest.main()
