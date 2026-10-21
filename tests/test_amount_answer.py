"""
test_amount_answer.py
금액 되묻기 뒤 턴 — 모델 대신 카드 값으로 답(payout.reply_turn → amount_answer). 답의 숫자가 카드와 같고, 부담보와 보장 여부
단서가 붙고, 되묻기 직후의 금액은 치료비 낱말이 없어도 치료비로 본다(context.resolve → after_amount_ask).
여러 날: 일수 2~5일이면 날짜별 금액 칸(days_ask) → 날짜별 금액이면 정확한 값, '잘 모르겠어요'면 범위. 6일 이상은 바로 범위.
청구 이력이 있으면 연간 남은 한도까지, Ⅲ MRI는 올해 몇 번째인지 이력으로.
"""

import asyncio
import json
import re
import unittest
from datetime import date

from app.schemas import Claim, DaysAskCalc, MedicalCalc, Pet, Policy
from app.services import context, payout
from app.services.turn_log import PriorTurn
from data.limit_table import calculate_payout

DOG, CAT = "펫퍼민트 반려견 ", "펫퍼민트 반려묘 "


ON = date(2026, 10, 21)
JOINED = date(2026, 7, 15)


def pet(name, species, *pols, excl=(), claims=()):
    return Pet.model_construct(pet_id="P", name=name, species=species, breed=None, age=None, policies=[
        Policy.model_construct(section_name=n, coverage_type=g, copay=c, excluded_conditions=list(excl), contract_date=JOINED)
        for n, g, c in pols], claims=list(claims))


def claim(section, paid, days=1, mri=False, when=date(2026, 9, 1)):
    return Claim.model_construct(claim_id="X", section_name=section, claim_date=when, treatment_date=when,
                                 treatment_type="입원" if "입원" in section else "통원", days=days, treatment_cost=paid * 2,
                                 paid=paid, surgery=False, mri=mri)


BYEOL = pet("별이", "강아지", (DOG + "통원의료비보장 특별약관", "고급형", 30000), (DOG + "입원의료비보장 특별약관", "고급형", 30000))
KONG = pet("콩이", "강아지", (DOG + "통원의료비보장 특별약관", "고급형", 30000), (DOG + "입원의료비보장 특별약관", "기본형", 30000))
CHEESE = pet("치즈", "고양이", (CAT + "통원의료비Ⅱ보장 특별약관", "고급형", 30000), (CAT + "입원의료비Ⅱ보장 특별약관", "고급형", 30000),
             excl=("슬개골 탈구",))
KKAMI = pet("까미", "고양이", (CAT + "통원의료비Ⅱ보장 특별약관", "실속형", 50000), (CAT + "입원의료비Ⅱ보장 특별약관", "실속형", 50000))
# 청구 이력 — 해피: 입원 기본형Ⅰ(연간 500만) 474.5만원 받음 / 초코: 입원 고급형Ⅱ(연간 1,500만) 350만원 / 뭉치: Ⅲ MRI 한 번
HAPPY = pet("해피", "강아지", (DOG + "통원의료비보장 특별약관", "기본형", 30000), (DOG + "입원의료비보장 특별약관", "기본형", 30000),
            claims=[claim(DOG + "입원의료비보장 특별약관", 4_745_000, days=11)])
CHOCO = pet("초코", "강아지", (DOG + "입원의료비Ⅱ보장 특별약관", "고급형", 30000),
            claims=[claim(DOG + "입원의료비Ⅱ보장 특별약관", 3_200_000, 5), claim(DOG + "입원의료비Ⅱ보장 특별약관", 300_000)])
MUNGCHI = pet("뭉치", "강아지", (DOG + "통원의료비Ⅲ보장 특별약관", "고급형", 30000),
              claims=[claim(DOG + "통원의료비Ⅲ보장 특별약관", 749_000, mri=True)])
LAST_YEAR = pet("작년", "강아지", (DOG + "입원의료비보장 특별약관", "기본형", 30000),
                claims=[claim(DOG + "입원의료비보장 특별약관", 4_900_000, when=date(2026, 7, 14))])   # 가입일 전날 — 지난 보험연도


def turn_after_ask(p, q1, q2):
    """금액 되묻기 → 답한 턴. (Resolved, 카드, 답)"""
    prior = [PriorTurn(question=q1, anchor=q1, answer=payout.ask_text(q1, p, None), pet_id=p.pet_id, chosen_section=None)]
    r = asyncio.run(context.resolve("업무특화", q2, prior, p, None))
    out = payout.reply_turn(q2, r.card_text, r.reply_stage, r.prior_calc, p, [], None, on=ON) if r.after_amount_ask else None
    return (r, *out) if out else (r, None, None)


def chain(p, q1, *replies):
    """되묻기부터 여러 턴 — 앞 턴의 답·카드를 다음 턴의 PriorTurn으로. 마지막 (카드, 답)"""
    anchor, answer, calc = q1, payout.ask_text(q1, p, None), None
    for q in replies:
        prior = [PriorTurn(question=q, anchor=anchor, answer=answer, pet_id=p.pet_id, chosen_section=None,
                           payout=calc.model_dump(mode="json") if calc else None)]
        r = asyncio.run(context.resolve("업무특화", q, prior, p, None))
        assert r.after_amount_ask, q
        calc, answer = payout.reply_turn(q, r.card_text, r.reply_stage, r.prior_calc, p, [], None, on=ON)
    return calc, answer


def bold(answer):
    return re.search(r"\*\*(.+?)\*\*", answer).group(1)


def no_days(setting="입원"):
    return (f"{'입원 일수' if setting == '입원' else '통원 횟수'}를 말씀하지 않아 하루 치료비로 계산했습니다. "
            f"여러 {'날' if setting == '입원' else '번'}이면 금액이 달라지니 '3{'일' if setting == '입원' else '번'} 총 70만원'처럼 알려 주세요.")


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
                              "1일 지급 한도(30만원) 안이라 예상 보험금은 **22만 4,000원**입니다.\n"
                              + no_days() + "\n" + payout.COVERAGE_NOTE)            # 일수를 안 들었다 — 하루로 계산했다고 밝힌다
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
        r = asyncio.run(context.resolve("업무특화", "3일이요", prior, BYEOL, None))
        self.assertFalse(r.after_amount_ask)
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


class AskText(unittest.TestCase):
    def test_by_setting(self):
        """되묻기 문장은 입원/통원에 따라 — 총액과 일수(횟수)를 함께 받는다"""
        self.assertEqual(payout.ask_text("입원했는데 얼마 나와요?", BYEOL, None), payout.ASK_TEXTS["입원"])
        self.assertEqual(payout.ask_text("통원했는데 얼마 나와요?", BYEOL, None), payout.ASK_TEXTS["통원"])
        self.assertEqual(payout.ask_text("보험금 얼마 나와요?", BYEOL, None), payout.ASK_TEXTS[None])
        self.assertEqual(payout.ask_text("보험금 얼마 나와요?", MUNGCHI, None), payout.ASK_TEXTS["통원"])   # 통원만 가입
        self.assertIn("입원 일수", payout.ASK_TEXTS["입원"])

    def test_old_ask_text_still_recognized(self):
        """10-21 이전 되묻기 문장 뒤의 금액도 이어 받는다"""
        prior = [PriorTurn(question="입원했는데 얼마?", anchor="입원했는데 얼마?", answer=payout.ASK_AMOUNT_TEXT, pet_id="P",
                           chosen_section=None)]
        self.assertTrue(asyncio.run(context.resolve("업무특화", "35만원이요", prior, BYEOL, None)).after_amount_ask)


class MultiDay(unittest.TestCase):
    Q = "입원하면 보험금 얼마 나와요?"

    def test_days_ask_then_list(self):
        """3일 총 70만원 → 날짜별 칸 → 30만·30만·10만 → 정확히 42.7만원(하루치로 보던 30만원이 아니다)"""
        card, ans = chain(BYEOL, self.Q, "3일 입원했고 총 70만원이요")
        self.assertIsInstance(card, DaysAskCalc)
        self.assertEqual((card.days, card.total, len(card.prefill)), (3, 700_000, 3))
        self.assertIn("진료비 세부내역서에 일자별로 나와 있습니다", ans)
        card, ans = chain(BYEOL, self.Q, "3일 입원했고 총 70만원이요", "300,000원, 300,000원, 100,000원")
        self.assertTrue(card.exact)
        self.assertEqual(([r.payout for r in card.day_rows], card.payout), ([189_000, 189_000, 49_000], 427_000))
        self.assertEqual(bold(ans), "42만 7,000원")

    def test_free_list_without_won(self):
        card, _ = chain(BYEOL, self.Q, "사흘 입원, 70만원", "첫날 30만 둘째 날 30만 셋째 날 10만")
        self.assertEqual(card.payout, 427_000)

    def test_unknown_gives_range(self):
        """'잘 모르겠어요' — 범위와 고르게 나뉜 추정, 정확한 값이 안 나온다고 말한다"""
        card, ans = chain(BYEOL, self.Q, "3일 입원, 총 70만원", "잘 모르겠어요")
        self.assertFalse(card.exact)
        self.assertEqual((card.range_min, card.range_max, card.even, card.payout), (300_000, 441_000, 427_000, 427_000))
        self.assertIn("**30만원 ~ 44만 1,000원**", ans)
        self.assertIn("고르게 나뉘었다면 **42만 7,000원**", ans)
        self.assertIn(payout.EXACT_NEEDS, ans)
        self.assertIn("정확한 금액은 계산할 수 없습니다", ans)

    def test_six_days_or_more_range_with_hint(self):
        card, ans = chain(BYEOL, self.Q, "일주일 입원했고 총 200만원이요")
        self.assertIsInstance(card, MedicalCalc)
        self.assertFalse(card.exact)
        self.assertIn(payout.LIST_HINT, ans)
        card, _ = chain(BYEOL, self.Q, "일주일 입원했고 총 200만원이요", "30만, 30만, 30만, 30만, 30만, 30만, 20만")
        self.assertTrue(card.exact)
        self.assertEqual(card.payout, 6 * 189_000 + 119_000)

    def test_surgery_day(self):
        """수술한 날 금액 — 2일이면 남은 하루가 정해져 정확, 3일이면 그 칸을 미리 채운 날짜별 칸"""
        card, ans = chain(BYEOL, self.Q, "2일 입원 총 70만원, 수술한 날 40만원")
        self.assertEqual([(r.surgery, r.payout) for r in card.day_rows], [(True, 259_000), (False, 189_000)])
        card, _ = chain(BYEOL, self.Q, "3일 입원 총 70만원, 수술한 날 40만원")
        self.assertEqual([(d.cost, d.surgery) for d in card.prefill], [(400_000, True), (None, False), (None, False)])
        card, ans = chain(BYEOL, self.Q, "3일 입원 총 70만원, 수술한 날 40만원", "20만원, 10만원")   # 빈 두 칸만 보냈다
        self.assertEqual(card.payout, 259_000 + 119_000 + 49_000)

    def test_outpatient_visits(self):
        """통원 3번 총 45만원 — 범위 25.2만~28만원(하루치 29.4만원은 많게 안내했다), 3번 = 서로 다른 3일"""
        card, ans = chain(BYEOL, "통원하면 얼마 받아요?", "3번 통원 총 45만원 나왔어요", "잘 모르겠어요")
        self.assertEqual((card.range_min, card.range_max), (252_000, 280_000))
        self.assertIn("통원 3번은 서로 다른 3일로 보고 계산했습니다", ans)

    def test_days_later(self):
        """일수 없이 금액만 → 하루로 계산하고 밝힘 → '3일이요'로 이어 받아 날짜별 칸"""
        card, ans = chain(BYEOL, self.Q, "치료비는 70만원이에요")
        self.assertFalse(card.days_known)
        self.assertIn(no_days(), ans)
        card, _ = chain(BYEOL, self.Q, "치료비는 70만원이에요", "3일이요")
        self.assertIsInstance(card, DaysAskCalc)
        self.assertEqual(card.total, 700_000)

    def test_days_only_asks_total(self):
        card, ans = chain(BYEOL, self.Q, "3일이요")
        self.assertIsNone(card)
        self.assertEqual(ans, payout.NEED_COST_TEXT)

    def test_silsok_copay_50k(self):
        """실속형 50% · 자기부담금 5만원 — 15만·8만 → 5만 + 1.5만"""
        card, ans = chain(KKAMI, "통원하면 얼마 받아요?", "통원 2번, 15만원, 8만원")
        self.assertEqual(([r.payout for r in card.day_rows], card.payout), ([50_000, 15_000], 65_000))
        self.assertIn("자기부담금 5만원을 빼고 50%를", ans)

    def test_exclusion_with_days(self):
        card, ans = chain(CHEESE, "슬개골 탈구로 입원했는데 보험금 얼마나 나와요?", "2일 입원 30만, 20만")
        self.assertIn("다만 치즈는 슬개골 탈구가 부담보 대상이라", ans)
        self.assertTrue(ans.endswith(payout.COVERAGE_NOTE))


class History(unittest.TestCase):
    Q = "입원하면 보험금 얼마 나와요?"

    def test_card_shows_usage(self):
        """청구 이력 — 올해 350만원 받음, 남은 한도 1,150만원"""
        card, ans = chain(CHOCO, self.Q, "1일 입원 50만원")
        self.assertEqual((card.annual_used, card.annual_remaining, str(card.year_start)), (3_500_000, 11_500_000, "2026-07-15"))
        self.assertIn("올해 이미 받은 보험금 350만원을 빼면 남은 연간 한도는 1,150만원입니다.", ans)

    def test_no_history(self):
        card, ans = chain(BYEOL, self.Q, "1일 입원 50만원")
        self.assertEqual((card.annual_used, card.annual_remaining), (0, 7_500_000))
        self.assertNotIn("올해 이미", ans)

    def test_annual_cap(self):
        """해피는 남은 연간 한도 25.5만원 — 날짜별 합계 35.7만원이 거기서 잘린다"""
        card, ans = chain(HAPPY, self.Q, "2박 3일 입원했고 날짜별로 20만원, 20만원, 20만원")
        self.assertEqual((card.payout, card.capped), (255_000, True))
        self.assertIn("35만 7,000원이지만, 올해 남은 연간 한도가 25만 5,000원이라 예상 보험금은 **25만 5,000원**", ans)
        card, _ = chain(HAPPY, self.Q, "3일 입원, 총 70만원", "잘 모르겠어요")
        self.assertLessEqual(card.range_max, 255_000)

    def test_last_policy_year_not_counted(self):
        """가입일(계약해당일) 전 치료는 지난 보험연도"""
        card, _ = chain(LAST_YEAR, self.Q, "1일 입원 50만원")
        self.assertEqual(card.annual_used, 0)
        self.assertEqual(payout.policy_year_start(JOINED, date(2027, 7, 14)), JOINED)
        self.assertEqual(payout.policy_year_start(JOINED, date(2027, 7, 15)), date(2027, 7, 15))

    def test_mri_nth(self):
        """Ⅲ MRI — 뭉치는 올해 MRI를 한 번 받아 이번은 두 번째: 한도 30만원(첫 번째면 100만원)"""
        q = "MRI 찍었는데 통원 보험금 얼마 나와요?"
        card, ans = chain(MUNGCHI, q, "1번, 120만원 나왔어요")
        self.assertEqual((card.mri_before, card.limit, card.payout), (1, 300_000, 300_000))
        self.assertIn("이번은 2번째라 그날 한도는 30만원입니다", ans)
        fresh = pet("새봄", "강아지", (DOG + "통원의료비Ⅲ보장 특별약관", "고급형", 30000))
        card, _ = chain(fresh, q, "1번, 120만원 나왔어요")
        self.assertEqual((card.limit, card.payout), (1_000_000, 819_000))


class TurnLogPayout(unittest.TestCase):
    def test_card_is_json_serializable(self):
        """턴 로그는 카드를 JSON으로 저장한다 — year_start(date)를 그대로 넣어 기록이 실패하고 턴이 사라졌다(10-21 검증 R15 등)"""
        from app.schemas import Session
        from app.services import answer
        card, _ = chain(CHOCO, "입원하면 보험금 얼마 나와요?", "1일 입원 50만원")
        session = Session.model_construct(session_id="S", mode="업무특화", customer_id="C", agent_email="a")
        ctx = answer.TurnContext(turn_id="T", session=session, pet=None, scope=None, question="q", agent="a", calc=card)
        log = answer._turn_log(ctx, "ok", [], [], [])
        self.assertEqual(json.loads(json.dumps(log.payout))["year_start"], "2026-07-15")
        self.assertEqual(payout.reply_stage("", log.payout), None)       # 일수까지 알아 정확 — 이어 받지 않는다


class Standalone(unittest.TestCase):
    """단독 금액 질문의 카드도 하루 단위 — 답 문장은 모델 그대로(카드만)"""

    def test_outpatient_not_overstated(self):
        card = payout.estimate("통원 3번 다녀서 치료비가 총 45만원 나왔는데 얼마 받아요?", BYEOL, [], None, on=ON)
        self.assertFalse(card.exact)
        self.assertEqual((card.range_min, card.range_max, card.payout), (252_000, 280_000, 252_000))
        self.assertEqual(card.flow, "question")

    def test_single_day_unchanged(self):
        """일수 없는 단독 질문 — 예전과 같은 하루치(카드에 가정만 적는다)"""
        card = payout.estimate("통원 치료비가 50만원 나왔는데 보험금 얼마 받을 수 있어요?", BYEOL, [], None, on=ON)
        self.assertEqual((card.claimed, card.limit, card.payout, card.days_known), (500_000, 300_000, 300_000, False))

    def test_day_list_in_question(self):
        card = payout.estimate("입원 첫날 30만원 둘째 날 30만원 치료비 나왔는데 얼마예요?", BYEOL, [], None, on=ON)
        self.assertEqual((card.exact, card.payout), (True, 378_000))


if __name__ == "__main__":
    unittest.main()
