"""
test_dayparse.py
자유 입력 해석기(dayparse·payout.read_costs) — 일수·횟수 표현, 날짜별 금액, 수술한 날 금액, 총액, 일수 없는 문장.
"""

import unittest

from app.services import dayparse
from app.services.payout import read_costs


def days(text):
    return dayparse.day_count(text)[0]


def values(text):
    return [a.value for a in dayparse.amounts(text)]


class DayCount(unittest.TestCase):
    def test_expressions(self):
        cases = {"3일 입원했어요": 3, "사흘 입원": 3, "열흘 동안": 10, "일주일 입원했고": 7, "2주 입원": 14,
                 "2박 3일 입원했어요": 3, "통원 3번 했어요": 3, "세 번 다녔어요": 3, "2회 통원": 2, "하루 입원": 1}
        for text, want in cases.items():
            self.assertEqual(days(text), want, text)

    def test_not_days(self):
        """1일당·1일차·두 번째·날짜는 일수가 아니다"""
        for text in ("1일당 한도가 얼마예요?", "1일차에 30만원", "두 번째 MRI예요", "치료비는 35만원 나왔어요"):
            self.assertIsNone(days(text), text)
        self.assertEqual(days("10월 3일에 입원해서 3일 있었어요"), 3)

    def test_same_day(self):
        """같은 날 두 번 통원은 하루"""
        self.assertEqual(dayparse.day_count("같은 날 두 번 통원했어요"), (1, "번", True))


class Amounts(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(values("12만 5,000원"), [125_000])
        self.assertEqual(values("300,000원"), [300_000])
        self.assertEqual(values("30만, 30만, 10만"), [300_000, 300_000, 100_000])       # 원 없이도
        self.assertEqual(values("첫날 30만 둘째 날 30만 셋째 날 10만"), [300_000, 300_000, 100_000])
        self.assertEqual(values("자기부담금 3만원 빼고 치료비 50만원"), [500_000])        # 자기부담금은 치료비가 아니다
        self.assertEqual(values("3일 입원"), [])

    def test_marks(self):
        a = dayparse.amounts("수술한 날 40만원, 총 70만원")
        self.assertEqual([(x.value, x.surgery, x.total) for x in a], [(400_000, True, False), (700_000, False, True)])
        a = dayparse.amounts("300,000원(수술), 300,000원, 100,000원")
        self.assertEqual([x.surgery for x in a], [True, False, False])
        a = dayparse.amounts("MRI 찍은 날 110만원, 다른 날 20만원")
        self.assertEqual([x.mri for x in a], [True, False])

    def test_unknown(self):
        self.assertTrue(dayparse.read("잘 모르겠어요").unknown)
        self.assertTrue(dayparse.is_reply("잘 모르겠어요"))
        self.assertTrue(dayparse.is_reply("30만, 30만, 10만"))
        self.assertFalse(dayparse.is_reply("해외에서 다친 것도 나오나요?"))


class Costs(unittest.TestCase):
    def test_total_and_days(self):
        c = read_costs("3일 입원했고 총 70만원이요")
        self.assertEqual((c.total, c.n, c.per_day), (700_000, 3, None))

    def test_day_list(self):
        c = read_costs("첫날 30만 둘째 날 30만 셋째 날 10만")
        self.assertEqual([d.cost for d in c.per_day], [300_000, 300_000, 100_000])

    def test_surgery_day_amount(self):
        """총액과 수술한 날 금액 — 수술한 날은 금액을 아는 날(fixed)"""
        c = read_costs("3일 입원 총 70만원, 수술한 날 40만원")
        self.assertEqual((c.total, c.n, [(d.cost, d.surgery) for d in c.fixed]), (700_000, 3, [(400_000, True)]))
        c = read_costs("3일 입원 70만원, 수술한 날 40만원")                  # '총' 없이도 — 일수와 개수가 다르다
        self.assertEqual((c.total, [d.cost for d in c.fixed]), (700_000, [400_000]))

    def test_no_days(self):
        c = read_costs("치료비는 50만원이에요")
        self.assertEqual((c.total, c.n), (500_000, None))


if __name__ == "__main__":
    unittest.main()
