"""
test_stage4.py
rebuild5 준비 4단계(2026-10-21) — 숫자 가드레일(4b), 코드 답 근거(4c), 고객 사실(4d), 등급 되묻기 줄이기(4e), 되묻기·미가입 오발동(4f).
"""

import unittest
from datetime import date

from app.schemas import Claim, MedicalCalc, Pet, Policy
from app.services import answer, customer_facts, guardrail, payout
from tests.test_amount_answer import BYEOL, KONG

DOG = "펫퍼민트 반려견 "
ON = date(2026, 10, 21)


def pet(name, *pols, age=5, joined=date(2026, 10, 1), excl=(), claims=(), species="강아지"):
    return Pet.model_construct(pet_id="P", name=name, species=species, breed=None, age=age, claims=list(claims), policies=[
        Policy.model_construct(section_name=n, coverage_type=g, copay=c, contract_date=joined, excluded_conditions=list(excl))
        for n, g, c in pols])


DUBU = pet("두부", (DOG + "통원의료비Ⅱ보장 특별약관", "기본형", 30000))
HAPPY = pet("해피", (DOG + "입원의료비보장 특별약관", "기본형", 30000), (DOG + "통원의료비보장 특별약관", "기본형", 30000), age=7,
            joined=date(2026, 8, 27), claims=[Claim.model_construct(claim_id="X", section_name=DOG + "입원의료비보장 특별약관",
                                                                     claim_date=date(2026, 9, 3), treatment_date=date(2026, 9, 3),
                                                                     treatment_type="입원", days=6, treatment_cost=1, paid=4_745_000,
                                                                     surgery=False, mri=False)])
MANGO = pet("망고", ("반려동물 특정 질병 보장제한부 인수 특별약관", None, None), excl=("슬개골 탈구", "뒷다리근골격계질환"))


class Guardrail(unittest.TestCase):
    def test_copied_amount_passes(self):
        self.assertEqual(guardrail.unknown_amounts("1일 한도는 30만원입니다.", ["1일당 30만원"]), [])

    def test_computed_amount_flagged(self):
        self.assertEqual(guardrail.unknown_amounts("27만원의 70%인 18만 9,000원", ["1일당 30만원"]), [270_000, 189_000])

    def test_card_values_allowed(self):
        card = MedicalCalc(section_name="x", coverage_type="고급형", claimed=500_000, copay=30_000, limit=300_000, payout=300_000, note="")
        self.assertEqual(guardrail.unknown_amounts("예상 보험금은 30만원, 치료비 50만원", [], card), [])


class CodeReferences(unittest.TestCase):
    def test_medical_card_cites_article_1(self):
        card = payout.estimate("통원 치료비가 50만원 나왔는데 얼마예요?", BYEOL, [], on=ON)
        refs = payout.code_references(card, BYEOL, "통원 치료비가 50만원")
        self.assertEqual([(r.section_name, r.article_num) for r in refs], [(card.section_name, 1)])


class CustomerFacts(unittest.TestCase):
    def test_not_enrolled(self):
        self.assertIn("입원의료비보장 특약에 가입하지 않아", customer_facts.not_enrolled("입원하면 하루 얼마 나와요?", DUBU))
        self.assertIn("배상책임보장 특약에 가입하지 않아", customer_facts.not_enrolled("우리 개가 사람을 물었어요", DUBU))
        self.assertIsNone(customer_facts.not_enrolled("통원 하루 한도는?", DUBU))
        self.assertIsNone(customer_facts.not_enrolled("입원 하루 한도는?", BYEOL))

    def test_annual(self):
        a = customer_facts.annual_answer("올해 입원 보험금 얼마나 더 받을 수 있어요?", HAPPY, ON)
        self.assertIn("남은 한도 **25만 5,000원**", a)
        self.assertIsNone(customer_facts.annual_answer("입원 한도 얼마예요?", HAPPY, ON))

    def test_waiting_period(self):
        n = customer_facts.notes("어제 장염으로 병원 갔는데 보장되나요?", BYEOL.model_copy(update={"policies": [
            p.model_copy(update={"contract_date": date(2026, 10, 1)}) for p in BYEOL.policies]}), ON)
        self.assertTrue(any("10월 30일까지" in x for x in n))
        self.assertEqual(customer_facts.notes("병원비 청구 서류가 뭐예요?", HAPPY, ON), [])     # '병원'은 질병이 아니다

    def test_waiting_by_species(self):
        """반려묘는 90일 비뇨기계·전염성복막염, 슬관절 규칙 없음 / 반려견은 1년 슬관절"""
        cat = pet("달이", ("펫퍼민트 반려묘 통원의료비보장 특별약관", "고급형", 30000), species="고양이")
        n = customer_facts.notes("방광염에 걸렸는데 보장돼요?", cat, ON)
        self.assertTrue(any("90일 이내" in x and "비뇨기계" in x for x in n))
        self.assertFalse(any("슬관절" in x for x in customer_facts.notes("무릎 탈구는요?", cat, ON)))
        dog = pet("별이", (DOG + "통원의료비보장 특별약관", "고급형", 30000))
        self.assertTrue(any("슬관절" in x for x in customer_facts.notes("무릎 탈구는요?", dog, ON)))

    def test_age(self):
        self.assertTrue(any("7세" in x for x in customer_facts.notes("해피 몇 살까지 유지돼요?", HAPPY, ON)))


class Exclusions(unittest.TestCase):
    def test_table_and_synonyms(self):
        self.assertEqual(payout.matched_exclusions("고관절 이형성증 진단받았어요", MANGO), ["뒷다리근골격계질환"])
        self.assertEqual(payout.matched_exclusions("무릎이 자꾸 빠져요", MANGO), ["슬개골 탈구"])
        self.assertEqual(payout.matched_exclusions("감기로 입원했어요", MANGO), [])


class Clarify(unittest.TestCase):
    def test_named_section(self):
        self.assertIn("입원", answer.named_section("입원 하루 치료비 40만원", KONG))
        self.assertIsNone(answer.named_section("통원이랑 입원 다 되나요?", KONG))

    def test_needs_grade(self):
        self.assertFalse(answer.needs_grade("회사 주식 사도 될까요?"))
        self.assertTrue(answer.needs_grade("하루 한도가 얼마예요?"))


class FalseAsks(unittest.TestCase):
    def test_no_card_for_missing_setting(self):
        self.assertIsNone(payout.question_turn("입원비가 30만원 나왔어요. 보험금은요?", DUBU, [], on=ON))
        self.assertIsNone(payout.limit_card("입원하면 하루에 얼마까지 나와요?", DUBU))

    def test_no_amount_ask(self):
        self.assertFalse(payout.needs_amount("올해 통원으로 보험금 얼마 받았어요?", BYEOL))
        self.assertFalse(payout.needs_amount("피해자랑 약속한 금액도 보험에서 나와요?", BYEOL))


if __name__ == "__main__":
    unittest.main()
