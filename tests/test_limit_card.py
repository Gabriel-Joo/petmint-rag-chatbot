"""
test_limit_card.py
payout.limit_card — 치료비 금액 없이 한도를 물을 때의 한도표 카드(kind "limits").
값은 limit_table(약관 각 특약 제1조 ①·②항)과 같아야 한다. 카드 순서(법률비용 → 의료비 → 한도)는 answer._generate가 정한다.
"""

import unittest

from app.schemas import Pet, Policy
from app.services import payout

DOG = "펫퍼민트 반려견 "
CAT = "펫퍼민트 반려묘 "


def pet(species: str, *policies: tuple[str, str | None, int | None]) -> Pet:
    return Pet.model_construct(pet_id="P", name="치즈", species=species, breed=None, age=None,
                               policies=[Policy.model_construct(section_name=n, coverage_type=g, copay=c, excluded_conditions=[])
                                         for n, g, c in policies])


CHEESE = pet("고양이", (CAT + "통원의료비Ⅱ보장 특별약관", "고급형", 30000), (CAT + "입원의료비Ⅱ보장 특별약관", "고급형", 30000),
             ("민사소송법률비용Ⅱ보장 특별약관", None, None))
KONG = pet("강아지", (DOG + "통원의료비보장 특별약관", "고급형", 30000), (DOG + "입원의료비보장 특별약관", "기본형", 30000))
MANGO = pet("강아지", (DOG + "통원의료비Ⅲ보장 특별약관", "기본형", 50000), (DOG + "입원의료비Ⅲ보장 특별약관", "기본형", 50000))


class LimitCard(unittest.TestCase):
    def test_live_question(self):
        """10-20 배포 서버 질문 — Ⅱ 고급형 통원·입원: 1일 30만원, 수술한 날 250만원, 70%, 연간 1,500만원"""
        c = payout.limit_card("제 지급 한도가 얼마인데요?", CHEESE)
        self.assertEqual((c.kind, c.pet_name, len(c.rows), c.highlight), ("limits", "치즈", 2, None))
        for r in c.rows:
            self.assertEqual((r.type, r.coverage_type, r.copay, r.rate_pct, r.non_surgery, r.surgery, r.annual_total, r.mri_1st),
                             ("Ⅱ", "고급형", 30000, 70, 300_000, 2_500_000, 15_000_000, None))

    def test_filter_and_highlight(self):
        c = payout.limit_card("입원하면 수술한 날 한도가 얼마예요?", CHEESE)
        self.assertEqual(([r.section_name for r in c.rows], c.highlight), ([CAT + "입원의료비Ⅱ보장 특별약관"], "surgery"))
        self.assertEqual(payout.limit_card("수술 안 하면 하루 한도는?", CHEESE).highlight, "non_surgery")

    def test_type3_mri(self):
        c = payout.limit_card("MRI 찍으면 얼마까지 나와요?", MANGO)
        r = c.rows[0]
        self.assertEqual((c.highlight, r.type, r.non_surgery, r.mri_1st, r.mri_2nd_plus, r.surgery, r.rate_pct, r.annual_total),
                         ("mri", "Ⅲ", 150_000, 500_000, 150_000, 2_500_000, 70, 10_000_000))

    def test_grade_mismatch(self):
        """질문이 가입과 다른 등급·유형 — 이 고객의 한도가 아니라 카드 없음. 맞는 쪽이 있으면 그것만"""
        self.assertIsNone(payout.limit_card("기본형 수술 한도가 얼마인가요?", CHEESE))
        self.assertIsNone(payout.limit_card("Ⅲ 통원 하루 한도는?", CHEESE))
        c = payout.limit_card("고급형 하루 한도는?", KONG)            # 통원 고급형·입원 기본형 → 통원만
        self.assertEqual([r.section_name for r in c.rows], [DOG + "통원의료비보장 특별약관"])

    def test_chosen_after_clarify(self):
        """되묻기로 고른 특약만(되묻기는 그대로 — 답을 받은 뒤 카드)"""
        c = payout.limit_card("하루 한도가 얼마예요?", KONG, chosen=DOG + "입원의료비보장 특별약관")
        self.assertEqual([(r.coverage_type, r.non_surgery) for r in c.rows], [("기본형", 150_000)])

    def test_not_limit_card(self):
        self.assertIsNone(payout.limit_card("소송 걸리면 변호사비는 한 건에 얼마까지 나와요?", CHEESE))   # 법률 — 법률비용 카드 몫
        self.assertIsNone(payout.limit_card("배상책임 한도는요?", CHEESE))
        self.assertIsNone(payout.limit_card("통원 치료비가 50만원 나왔는데 한도 넘어요?", CHEESE))      # 금액 있음 — 의료비 카드 몫
        self.assertIsNone(payout.limit_card("해지하면 환급금 있나요?", CHEESE))
        self.assertIsNone(payout.limit_card("중도인출 하면 얼마까지 돼요?", CHEESE))                    # 10-21 버그 — 의료비 한도표가 떴다
        self.assertIsNone(payout.limit_card("보험료 최대 얼마까지 올라요?", CHEESE))
        self.assertIsNone(payout.limit_card("제 한도가 얼마예요?", None))                              # 업무특화가 아님


if __name__ == "__main__":
    unittest.main()
