"""
test_amount_answer.py
금액 되묻기 직후 턴 — 모델 대신 카드 값으로 답(payout.amount_answer). 답의 숫자가 카드와 같고, 부담보와 보장 여부 단서가 붙고,
되묻기 직후의 금액은 치료비 낱말이 없어도 치료비로 본다(context.resolve → after_amount_ask, estimate(cost=)).
"""

import asyncio
import re
import unittest

from app.schemas import Pet, Policy
from app.services import context, payout
from app.services.turn_log import PriorTurn
from data.limit_table import calculate_payout

DOG, CAT = "펫퍼민트 반려견 ", "펫퍼민트 반려묘 "


def pet(name, species, *pols, excl=()):
    return Pet.model_construct(pet_id="P", name=name, species=species, breed=None, age=None, policies=[
        Policy.model_construct(section_name=n, coverage_type=g, copay=c, excluded_conditions=list(excl)) for n, g, c in pols])


BYEOL = pet("별이", "강아지", (DOG + "통원의료비보장 특별약관", "고급형", 30000), (DOG + "입원의료비보장 특별약관", "고급형", 30000))
KONG = pet("콩이", "강아지", (DOG + "통원의료비보장 특별약관", "고급형", 30000), (DOG + "입원의료비보장 특별약관", "기본형", 30000))
CHEESE = pet("치즈", "고양이", (CAT + "통원의료비Ⅱ보장 특별약관", "고급형", 30000), (CAT + "입원의료비Ⅱ보장 특별약관", "고급형", 30000),
             excl=("슬개골 탈구",))
KKAMI = pet("까미", "고양이", (CAT + "통원의료비Ⅱ보장 특별약관", "실속형", 50000), (CAT + "입원의료비Ⅱ보장 특별약관", "실속형", 50000))


def turn_after_ask(p, q1, q2):
    prior = [PriorTurn(question=q1, anchor=q1, answer=payout.ASK_AMOUNT_TEXT, pet_id=p.pet_id, chosen_section=None)]
    r = asyncio.run(context.resolve("업무특화", q2, prior, p, None))
    amounts = payout.amounts_in(q2)
    card = payout.estimate(r.card_text, p, [], None, cost=amounts[0] if amounts else None)
    return r, card, payout.amount_answer(card, p, r.card_text) if card else None


def bold(answer):
    return re.search(r"\*\*(.+?)\*\*", answer).group(1)


class AmountAnswer(unittest.TestCase):
    def test_five_cases_match_card(self):
        """10-21 다섯 사례 — 답의 예상 보험금이 카드와 같다"""
        cases = [(BYEOL, "강아지가 감기로 입원했는데 보험금 얼마나 나올 수 있나요?", "치료비는 35만원 나왔어요", 224_000, "22만 4,000원"),
                 (BYEOL, "강아지가 감기로 입원했는데 보험금 얼마나 나올 수 있나요?", "치료비는 하루에 입원비 포함 10만원 나왔어요", 49_000, "4,9000원"),
                 (BYEOL, "골절로 입원했는데 보상받을 수 있는 금액은?", "치료비는 80만원이에요", 300_000, "30만원"),
                 (BYEOL, "피부병으로 통원 치료 받았는데 얼마 받을 수 있어요?", "15만원 들었어요", 84_000, "8만 4,000원"),
                 (KONG, "입원했는데 보험금 얼마나 나와요?", "40만원이요", 150_000, "15만원")]
        for p, q1, q2, want, _ in cases:
            r, card, ans = turn_after_ask(p, q1, q2)
            self.assertTrue(r.after_amount_ask, q2)
            self.assertIsNotNone(card, q2)                                   # 콩이 "40만원이요"도 — 치료비 낱말 없이
            self.assertEqual(card.payout, want, q2)
            self.assertEqual(bold(ans), payout._won(card.payout), q2)
            self.assertTrue(ans.endswith(payout.COVERAGE_NOTE))

    def test_text(self):
        _, _, ans = turn_after_ask(BYEOL, "강아지가 감기로 입원했는데 보험금 얼마나 나올 수 있나요?", "치료비는 35만원 나왔어요")
        self.assertEqual(ans, "입원 치료비 35만원에서 자기부담금 3만원을 뺀 32만원의 70%는 22만 4,000원입니다. "
                              "1일 지급 한도(30만원) 안이라 예상 보험금은 **22만 4,000원**입니다.\n" + payout.COVERAGE_NOTE)
        _, _, ans = turn_after_ask(BYEOL, "골절로 입원했는데 보상받을 수 있는 금액은?", "치료비는 80만원이에요")
        self.assertIn("77만원의 70%는 53만 9,000원입니다. 1일 지급 한도가 30만원이라 예상 보험금은 **30만원**입니다.", ans)

    def test_rate_from_table(self):
        """실속형은 50% — 70% 고정이 아니다"""
        _, card, ans = turn_after_ask(KKAMI, "통원 치료 받았는데 얼마 나와요?", "13만원이요")
        self.assertEqual((card.rate_pct, card.payout), (50, 40_000))
        self.assertIn("8만원의 50%는 4만원", ans)

    def test_exclusion(self):
        _, _, ans = turn_after_ask(CHEESE, "슬개골 탈구로 입원했는데 보험금 얼마나 나와요?", "치료비는 50만원이에요")
        self.assertIn("다만 치즈는 슬개골 탈구가 부담보 대상이라 해당 치료는 보험금이 지급되지 않습니다.", ans)
        self.assertTrue(ans.endswith(payout.COVERAGE_NOTE))
        _, _, ans = turn_after_ask(CHEESE, "감기로 입원했는데 보험금 얼마나 나와요?", "치료비는 50만원이에요")
        self.assertNotIn("부담보", ans)
        self.assertTrue(ans.endswith(payout.COVERAGE_NOTE))           # 부담보에 안 걸려도 늘
        self.assertEqual(payout.matched_exclusions("슬개골 수술 받았어요", CHEESE), ["슬개골 탈구"])   # 3글자 이상 낱말

    def test_long_amount_reply_is_follow_up(self):
        """후속 규칙(금액만 16자 이하)에 안 걸리는 긴 답도 되묻기 직후면 후속"""
        r, card, _ = turn_after_ask(BYEOL, "입원했는데 보험금 얼마나 나와요?", "영수증 보니까 35만원 정도 나왔고 수술은 안 했어요")
        self.assertEqual((r.follow_up, r.after_amount_ask, card.payout), ("되묻기 답", True, 224_000))

    def test_not_after_ask(self):
        """앞 턴이 되묻기가 아니면 지금처럼(모델이 답한다)"""
        prior = [PriorTurn(question="고급형 통원 하루 한도는?", anchor="고급형 통원 하루 한도는?", answer="30만원입니다", pet_id="P",
                           chosen_section=None)]
        r = asyncio.run(context.resolve("업무특화", "그럼 입원은요?", prior, BYEOL, None))
        self.assertFalse(r.after_amount_ask)
        r = asyncio.run(context.resolve("업무특화", "50만원 나왔는데 얼마 받아요?", prior, BYEOL, None))
        self.assertFalse(r.after_amount_ask)

    def test_below_copay(self):
        _, card, ans = turn_after_ask(BYEOL, "통원 치료 받았는데 얼마 나와요?", "2만원이요")
        self.assertEqual(card.payout, 0)
        self.assertIn("자기부담금 3만원 이하라 예상 보험금은 **0원**", ans)

    def test_integer_payout(self):
        """보상비율을 정수로 — 실수 곱셈은 41,000원에서 7,699원이 나왔다"""
        self.assertEqual(calculate_payout(41_000, 30_000, 0.7, 10**9), 7_700)
        self.assertEqual(calculate_payout(400_000, 30_000, 0.7, 10**9), 259_000)


if __name__ == "__main__":
    unittest.main()
