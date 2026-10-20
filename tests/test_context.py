"""
test_context.py
context.resolve — 멀티턴. 모드별 처리(일반 이력 3턴 / 사내규정 재작성 / 업무특화 이어 붙이기), 기준 질문 낱말 갈아 끼우기,
되묻기로 고른 특약 이어 쓰기, 반려동물을 바꾸면 끊기.
"""

import asyncio
import unittest

from app.schemas import Pet, Policy
from app.services import context
from app.services.turn_log import PriorTurn

DOG = "펫퍼민트 반려견 "
KONG = Pet.model_construct(pet_id="P005", name="콩이", species="강아지", breed=None, age=None, policies=[
    Policy.model_construct(section_name=DOG + "통원의료비보장 특별약관", coverage_type="고급형", copay=30000, excluded_conditions=[]),
    Policy.model_construct(section_name=DOG + "입원의료비보장 특별약관", coverage_type="기본형", copay=30000, excluded_conditions=[])])


def turn(q, anchor=None, pet="P005", chosen=None, a="답"):
    return PriorTurn(question=q, anchor=anchor or q, answer=a, pet_id=pet, chosen_section=chosen)


def run(coro):
    return asyncio.run(coro)


class FakeLLM:
    def __init__(self, out=None, fail=False):
        self.out, self.fail, self.calls = out, fail, 0

    async def complete(self, model, messages, **kw):
        self.calls += 1
        if self.fail:
            raise RuntimeError("down")
        return self.out


class Resolve(unittest.TestCase):
    def test_standalone_untouched(self):
        r = run(context.resolve("업무특화", "해외에서 다친 것도 나오나요?", [turn("고급형 통원 하루 한도는?")], KONG, None))
        self.assertEqual((r.kind, r.retrieval_query, r.generation_question), (None, "해외에서 다친 것도 나오나요?", "해외에서 다친 것도 나오나요?"))

    def test_no_prior(self):
        self.assertIsNone(run(context.resolve("업무특화", "그럼 입원은요?", [], KONG, None)).kind)

    def test_concat_and_override_chain(self):
        """고급형 통원 → 그럼 입원은요? → 수술하면요? — 셋째 턴에도 '입원'이 남는다"""
        r2 = run(context.resolve("업무특화", "그럼 입원은요?", [turn("고급형 통원 하루 한도는?")], KONG, None))
        self.assertEqual((r2.kind, r2.anchor, r2.search_query, r2.generation_question),
                         ("concat", "고급형 입원 하루 한도는?", "고급형 입원 하루 한도는? 그럼 입원은요?", "고급형 입원 하루 한도는? 그럼 입원은요?"))
        r3 = run(context.resolve("업무특화", "수술하면요?", [turn("고급형 통원 하루 한도는?"), turn("그럼 입원은요?", r2.anchor)], KONG, None))
        self.assertEqual((r3.anchor, r3.search_query, r3.card_text),
                         ("고급형 입원 하루 한도는?", "고급형 입원 하루 한도는? 수술하면요?", "고급형 입원 하루 한도는? 수술하면요?"))

    def test_override_grade_and_type(self):
        self.assertEqual(context.override("고급형 통원Ⅱ 한도는?", "기본형 Ⅲ이면요?"), "기본형 통원Ⅲ 한도는?")
        self.assertEqual(context.override("통원 한도는?", "통원이랑 입원 둘 다요?"), "통원 한도는?")   # 둘 다 말하면 안 바꾼다

    def test_pet_changed(self):
        r = run(context.resolve("업무특화", "그럼 입원은요?", [turn("고급형 통원 하루 한도는?", pet="P001")], KONG, None))
        self.assertIsNone(r.kind)

    def test_carry_chosen(self):
        prior = [turn("하루 한도가 얼마예요?", chosen=DOG + "입원의료비보장 특별약관")]
        self.assertEqual(run(context.resolve("업무특화", "수술하면요?", prior, KONG, None)).chosen, DOG + "입원의료비보장 특별약관")
        self.assertEqual(run(context.resolve("업무특화", "통원은요?", prior, KONG, None)).chosen, DOG + "통원의료비보장 특별약관")

    def test_amount_follow_up_card_text(self):
        r = run(context.resolve("업무특화", "치료비는 35만원 나왔어요", [turn("감기로 입원했는데 보험금 얼마나 나올 수 있나요?")], KONG, None))
        self.assertEqual((r.follow_up, r.card_text), ("금액만", "감기로 입원했는데 보험금 얼마나 나올 수 있나요? 치료비는 35만원 나왔어요"))
        self.assertEqual(r.generation_question, "치료비는 35만원 나왔어요")   # 금액만 — 후속만(기준+후속이면 거절했다)

    def test_general_history_3_turns(self):
        prior = [turn(f"질문{i}", a=f"답{i}", pet=None) for i in range(5)]
        r = run(context.resolve("일반", "그럼 언제 튜플을 써?", prior, None, None))
        self.assertEqual((r.kind, len(r.history), r.history[0]["content"], r.message("t").turns), ("history", 6, "질문2", 3))

    def test_hr_rewrite(self):
        llm = FakeLLM("고쳐 쓴 질문: 재택근무 신청은 언제까지 해야 돼요?")
        r = run(context.resolve("사내규정", "그 다음엔요?", [turn("재택근무는 주에 며칠까지 할 수 있나요?", pet=None)], None, llm))
        self.assertEqual((r.kind, r.anchor, r.retrieval_query, r.generation_question),
                         ("rewrite", "재택근무 신청은 언제까지 해야 돼요?", "재택근무 신청은 언제까지 해야 돼요?", "재택근무 신청은 언제까지 해야 돼요?"))

    def test_hr_rewrite_fails_concat(self):
        r = run(context.resolve("사내규정", "그 다음엔요?", [turn("병가는 며칠까지 쓸 수 있어요?", pet=None)], None, FakeLLM(fail=True)))
        self.assertEqual((r.kind, r.search_query, r.generation_question),
                         ("concat", "병가는 며칠까지 쓸 수 있어요? 그 다음엔요?", "병가는 며칠까지 쓸 수 있어요? 그 다음엔요?"))


if __name__ == "__main__":
    unittest.main()
