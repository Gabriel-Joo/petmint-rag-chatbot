"""
test_daycalc.py
하루 단위 계산(daycalc) — 날마다 자기부담금·그날 한도, 범위(최소·최대)는 전수 탐색과 같고, 고르게 나뉜 추정은 범위 안,
연간 남은 한도까지. 기대값은 약관 표(limit_table)로 손으로 계산한 값이다.
"""

import unittest

from app.services.daycalc import Annual, DayIn, DayLimits, bounds, day_payout, even_value, exact

GOLD_1 = DayLimits.of("고급형", "Ⅰ", 30_000)       # 1일 30만 · 수술한 날 200만 · 70% · 연간 750만
SILSOK_2 = DayLimits.of("실속형", "Ⅱ", 50_000)     # 1일 10만 · 수술한 날 200만 · 50% · 연간 700만
GOLD_3 = DayLimits.of("고급형", "Ⅲ", 30_000)       # MRI 첫 번째 100만 · 두 번째부터 30만


def brute(total: int, limits: list[int], copay: int, pct: int, unit: int = 10_000) -> tuple[int, int]:
    """1만원 단위로 모든 나눔(날마다 1만원 이상)을 센다 — bounds()와 대조용"""
    n, T = len(limits), total // unit
    lo, hi = None, None

    def rec(i, left, acc):
        nonlocal lo, hi
        if i == n - 1:
            v = acc + day_payout(left * unit, copay, pct, limits[i])
            lo, hi = (v if lo is None else min(lo, v)), (v if hi is None else max(hi, v))
            return
        for x in range(1, left - (n - 1 - i) + 1):
            rec(i + 1, left - x, acc + day_payout(x * unit, copay, pct, limits[i]))
    rec(0, T, 0)
    return lo, hi


def span(total, n, lim=GOLD_1):
    limits = [lim.non_surgery] * n
    return (*bounds(total, limits, lim.copay, lim.pct), even_value(total, limits, lim.copay, lim.pct))


class Range(unittest.TestCase):
    def test_inpatient_n_days(self):
        """입원 N일(1·3·5·10·30) 총액만 알 때 — (최소, 최대, 고르게)"""
        self.assertEqual(span(700_000, 1), (300_000, 300_000, 300_000))
        self.assertEqual(span(700_000, 3), (300_000, 441_000, 427_000))
        self.assertEqual(span(1_200_000, 5), (300_000, 763_000, 735_000))
        self.assertEqual(span(2_000_000, 10), (300_000, 1_260_000, 1_190_000))
        self.assertEqual(span(12_000_000, 30), (300_000, 7_812_000, 7_770_000))   # 연간 한도 750만 적용 전

    def test_small_outpatient_visits(self):
        """통원 소액 여러 번 — 하루치(자기부담금 한 번)로 계산하면 많게 안내했다(45만원 → 29.4만원)"""
        lo, hi, even = span(450_000, 3)
        self.assertEqual((lo, hi, even), (252_000, 280_000, 252_000))
        self.assertGreater(day_payout(450_000, 30_000, 70, 300_000), hi)          # 예전 하루치 294,000원은 범위 밖
        self.assertEqual(span(150_000, 3), (42_000, 70_000, 42_000))

    def test_matches_brute_force(self):
        for total, limits in [(700_000, [300_000] * 3), (1_200_000, [300_000] * 5), (450_000, [300_000] * 3),
                              (150_000, [300_000] * 3), (700_000, [2_000_000, 300_000, 300_000]),
                              (300_000, [150_000] * 4), (900_000, [1_000_000, 300_000, 300_000])]:
            self.assertEqual(bounds(total, limits, 30_000, 70), brute(total, limits, 30_000, 70), (total, limits))

    def test_order_property(self):
        """성질 — 최소 ≤ 고르게 ≤ 최대, 날짜별로 정확히 계산한 값은 범위 안(날마다 원 미만을 버려 (일수 - 1)원까지 아래)"""
        for total in range(20_000, 3_000_001, 70_000):
            for n in (2, 3, 4, 6):
                if total // 2 // (n - 1) < 10_000:             # 범위는 날마다 1만원 이상을 전제로 한다(DAY_FLOOR)
                    continue
                for lim in (GOLD_1, SILSOK_2):
                    lo, hi, even = span(total, n, lim)
                    self.assertLessEqual(lo, even, (total, n))
                    self.assertLessEqual(even, hi, (total, n))
                    first = total // 2
                    rest = [(total - first) // (n - 1)] * (n - 1)
                    rest[0] += total - first - sum(rest)
                    v = sum(r.payout for r in exact([DayIn(first), *map(DayIn, rest)], lim))
                    self.assertTrue(lo - (n - 1) <= v <= hi, (total, n, v))


class Exact(unittest.TestCase):
    def test_day_list(self):
        rows = exact([DayIn(300_000), DayIn(300_000), DayIn(100_000)], GOLD_1)
        self.assertEqual([r.payout for r in rows], [189_000, 189_000, 49_000])

    def test_surgery_day(self):
        """수술한 날은 그날만 수술 한도(200만원) — 나머지 날은 30만원"""
        rows = exact([DayIn(3_000_000, surgery=True), DayIn(800_000)], GOLD_1)
        self.assertEqual([(r.limit, r.payout) for r in rows], [(2_000_000, 2_000_000), (300_000, 300_000)])
        self.assertEqual(rows[0].label, "수술한 날")

    def test_silsok_rate_and_copay_50k(self):
        """실속형 50% · 자기부담금 5만원 — 13만원이면 (13 - 5) × 50% = 4만원"""
        self.assertEqual(exact([DayIn(130_000)], SILSOK_2)[0].payout, 40_000)
        self.assertEqual(exact([DayIn(40_000)], SILSOK_2)[0].payout, 0)        # 자기부담금 이하
        self.assertEqual(exact([DayIn(130_000)], DayLimits.of("실속형", "Ⅱ", 30_000))[0].payout, 50_000)

    def test_mri_nth_from_history(self):
        """Ⅲ MRI — 올해 첫 번째면 100만원, 이미 한 번 받았으면 30만원. 수술한 날의 MRI는 수술 한도이고 횟수에 안 센다"""
        self.assertEqual(exact([DayIn(1_200_000, mri=True)], GOLD_3, mri_before=0)[0].payout, 819_000)
        self.assertEqual(exact([DayIn(1_200_000, mri=True)], GOLD_3, mri_before=1)[0].payout, 300_000)
        rows = exact([DayIn(1_200_000, mri=True), DayIn(1_200_000, mri=True)], GOLD_3)
        self.assertEqual([r.limit for r in rows], [1_000_000, 300_000])
        rows = exact([DayIn(4_000_000, surgery=True, mri=True), DayIn(1_200_000, mri=True)], GOLD_3)
        self.assertEqual([r.limit for r in rows], [2_500_000, 1_000_000])


class AnnualCap(unittest.TestCase):
    def test_remaining(self):
        a = Annual(total=15_000_000, used=3_500_000, year_start="2026-07-15")
        self.assertEqual(a.remaining, 11_500_000)
        self.assertEqual(a.cap(300_000), 300_000)

    def test_overflow(self):
        """입원 30일 1,200만원(고르게) — 777만원이 연간 750만원에 걸린다. 이미 474.5만원 받았으면 25.5만원까지"""
        even = span(12_000_000, 30)[2]
        self.assertEqual(Annual(total=7_500_000, used=0, year_start=None).cap(even), 7_500_000)
        self.assertEqual(Annual(total=5_000_000, used=4_745_000, year_start=None).cap(357_000), 255_000)
        self.assertEqual(Annual(total=5_000_000, used=5_200_000, year_start=None).remaining, 0)


if __name__ == "__main__":
    unittest.main()
