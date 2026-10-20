"""
test_legal_fees.py
limit_table의 【별표3】 변호사비용 · 【별표4】 인지액 · 【별표5】 송달료, payout.legal_estimate 검증.
약관 원문(data/chunks/petmint_{종}.json)의 별표 표를 읽어 코드의 표와 대조한다 — 원문에 계산 예시가 없어서
구간별 기준액·비율·송달료를 원문 값과 맞춘다. 의료비 calculate_payout의 원문 예시도 같이 묶어 둔다(회귀).

실행: python -m unittest tests.test_legal_fees -v   (GPU·Milvus 안 씀)
"""

import json
import re
import unittest
from pathlib import Path

from data.limit_table import (LAWYER_FEE_BRACKETS, SERVICE_FEE, STAMP_FEE_BRACKETS, calculate_payout, lawyer_fee_limit,
                              legal_cost_payout, service_fee, stamp_fee)

CHUNKS = Path(__file__).resolve().parent.parent / "data" / "chunks"
SPECIES = ("강아지", "고양이")


def _won(text: str) -> int:
    """'2,000만원' '1억5천만원' '555,000원' → 원"""
    t = text.replace(",", "").replace(" ", "")
    total, unit_val = 0, {"억": 10 ** 8, "천만": 10 ** 7, "천": 10 ** 3, "만": 10 ** 4}
    for num, unit in re.findall(r"(\d+)(억|천만|천|만)?", t.replace("원", "")):
        total += int(num) * unit_val.get(unit, 1)
    return total


def _annex(species: str, name: str) -> str:
    chunks = json.loads((CHUNKS / f"petmint_{species}.json").read_text(encoding="utf-8"))
    return next(c["content"] for c in chunks if c["section"] == "별표" and c.get("section_name") == name)


def _table_rows(text: str) -> list[list[str]]:
    """청크 끝의 [표] 마크다운 행들(머리줄·구분줄 제외)"""
    rows = []
    for line in text.split("[표]", 1)[1].splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


class LawyerFeeTable(unittest.TestCase):
    NAME = "【별표3】 소송목적의 값에 따른 변호사비용"

    def test_brackets_match_source(self):
        """원문 표의 행마다 [기준액 + (소송목적의 값 - 하한) x 비율] — 기준액·하한·비율이 코드 표와 같다"""
        for sp in SPECIES:
            rows = [r for r in _table_rows(_annex(sp, self.NAME)) if r[0] != "소송목적의 값"]
            self.assertEqual(len(rows), len(LAWYER_FEE_BRACKETS), sp)
            first = rows[0]
            self.assertEqual((first[0], _won(first[1])), ("300만원까지 부분", 300_000), sp)
            for (cell, ratio), (low, _high, base, permille) in zip(rows[1:], LAWYER_FEE_BRACKETS[1:]):
                m = re.search(r"\[([\d,억천만]+원)\s*\+\s*\(소송목적의 값 - ([\d,억천만]+원)\)", cell.replace("<br>", ""))
                self.assertIsNotNone(m, f"{sp} {cell}")
                self.assertEqual(_won(m.group(1)), base, f"{sp} {cell}")
                self.assertEqual(_won(m.group(2)), low, f"{sp} {cell}")
                self.assertEqual(round(float(ratio.rstrip("%")) * 10), permille, f"{sp} {cell}")

    def test_brackets_continuous(self):
        """구간 상한에서 계산한 값 = 다음 구간 기준액(원문 표가 누진 합계로 짜여 있다)"""
        for (_l, high, _b, _r), (_l2, _h2, base2, _r2) in zip(LAWYER_FEE_BRACKETS, LAWYER_FEE_BRACKETS[1:]):
            self.assertEqual(lawyer_fee_limit(high), base2, high)

    def test_examples(self):
        self.assertEqual(lawyer_fee_limit(30_000_000), 2_800_000)      # R043: 200만 + 1,000만 × 8% (어댑터는 30만원)
        self.assertEqual(lawyer_fee_limit(1_000_000), 300_000)         # 300만원까지 정액
        self.assertEqual(lawyer_fee_limit(3_000_000), 300_000)
        self.assertEqual(lawyer_fee_limit(10_000_000), 1_000_000)      # 30만 + 700만 × 10%
        self.assertEqual(lawyer_fee_limit(600_000_000), 13_900_000)    # 1,340만 + 1억 × 0.5%
        with self.assertRaises(ValueError):
            lawyer_fee_limit(-1)


class StampFeeTable(unittest.TestCase):
    NAME = "【별표4】 민사소송 인지액 /【별표5】 송달료"

    def test_brackets_match_source(self):
        for sp in SPECIES:
            rows = [r for r in _table_rows(_annex(sp, self.NAME)) if r[0] not in ("소송목적의 값", "사건")][:4]
            for (cell_range, cell_fee), (low, _high, base, bp) in zip(rows, STAMP_FEE_BRACKETS):
                fee = cell_fee.replace(",", "")
                m_rate = re.search(r"X\s*([\d.]+)%", fee)
                m_base = re.match(r"(\d+)원\s*\+", fee)
                self.assertEqual(round(float(m_rate.group(1)) * 100), bp, f"{sp} {cell_fee}")
                self.assertEqual(int(m_base.group(1)) if m_base else 0, base, f"{sp} {cell_fee}")
                lows = re.findall(r"(\d+(?:천만|억)원)이상", cell_range.replace(" ", ""))
                self.assertEqual(_won(lows[0]) if lows else 0, low, f"{sp} {cell_range}")

    def test_examples(self):
        self.assertEqual(stamp_fee(5_000_000), 25_000)                  # 500만 × 0.5%
        self.assertEqual(stamp_fee(25_000_000), 117_500)                # 5,000 + 2,500만 × 0.45% (부동소수면 117,499)
        self.assertEqual(stamp_fee(30_000_000), 140_000)
        self.assertEqual(stamp_fee(100_000_000), 455_000)               # 1억 이상 구간: 55,000 + 1억 × 0.4%
        self.assertEqual(stamp_fee(1_000_000_000), 4_055_000)           # 10억 이상 구간


class ServiceFeeTable(unittest.TestCase):
    def test_matches_source(self):
        """원문 표: |1심<br>민사소액 / 민사단독 / 민사합의|110,000원 / 165,000원 /<br>165,000원| · |항소심 / 상고심|132,000원 / 88,000원|"""
        for sp in SPECIES:
            rows = {r[0].replace("<br>", " "): r[1].replace("<br>", "") for r in _table_rows(_annex(sp, StampFeeTable.NAME))
                    if "심" in r[0]}
            first = next(v for k, v in rows.items() if k.startswith("1심"))
            kinds = re.findall(r"민사(소액|단독|합의)", next(k for k in rows if k.startswith("1심")))
            fees = [int(x.replace(",", "")) for x in re.findall(r"([\d,]+)원", first)]
            self.assertEqual({("1심", "민사" + k): f for k, f in zip(kinds, fees)},
                             {k: v for k, v in SERVICE_FEE.items() if k[0] == "1심"}, sp)
            upper = [int(x.replace(",", "")) for x in re.findall(r"([\d,]+)원", rows["항소심 / 상고심"])]
            self.assertEqual(upper, [SERVICE_FEE[("항소심", None)], SERVICE_FEE[("상고심", None)]], sp)

    def test_lookup(self):
        self.assertEqual(service_fee("1심", "민사단독"), 165_000)       # R044: 단독·합의는 165,000원(어댑터는 셋 다 110,000원)
        self.assertEqual(service_fee("항소심"), 132_000)
        with self.assertRaises(ValueError):
            service_fee("1심")                                         # 1심은 사건 종류가 있어야 한다


class LegalCostPayout(unittest.TestCase):
    def test_lawyer_capped_by_annex3(self):
        """민사소송법률비용Ⅱ 제3조 ②항: 실제 보수 300만 - 자기부담금 10만 = 290만, 별표3 한도 280만 → 280만"""
        r = legal_cost_payout(30_000_000, 3_000_000, 140_000, 165_000, "1심", "민사단독")
        self.assertEqual((r["lawyer"], r["stamp"], r["service"], r["total"]), (2_800_000, 140_000, 165_000, 3_105_000))

    def test_copay_and_actual(self):
        r = legal_cost_payout(30_000_000, 1_000_000, 100_000, 50_000, "항소심")
        self.assertEqual((r["lawyer"], r["stamp"], r["service"]), (900_000, 100_000, 50_000))   # 실제 부담액이 한도보다 작으면 실제액

    def test_lawyer_limit_20m(self):
        r = legal_cost_payout(2_000_000_000, 50_000_000, 0, 0, "상고심")
        self.assertEqual(r["lawyer"], 20_000_000)                       # 별표3은 2,090만이지만 1소송당 2,000만 한도가 먼저
        self.assertEqual(lawyer_fee_limit(2_000_000_000), 20_900_000)
        self.assertEqual(legal_cost_payout(500_000_000, 50_000_000, 0, 0, "상고심")["lawyer"], 13_400_000)


class MedicalPayoutRegression(unittest.TestCase):
    def test_source_examples(self):
        """limit_table.calculate_payout 독스트링의 원문 예시(약관 요약서 21쪽)"""
        cases = [((230_000, 30_000, 0.7, 150_000), 140_000), ((4_000_000, 30_000, 0.7, 2_000_000), 2_000_000),
                 ((130_000, 30_000, 0.5, 100_000), 50_000), ((1_030_000, 30_000, 0.7, 1_000_000), 700_000)]
        for args, want in cases:
            self.assertEqual(calculate_payout(*args), want, args)


class AnnexAnswerVerification(unittest.TestCase):
    """faq_verify.verify_byeopyo — 05 생성·06 결정적 검사(calc, drop)가 QA 답변의 별표3·4·5 금액을 limit_table 계산값과 대조"""
    S3 = "【별표3】 소송목적의 값에 따른 변호사비용"
    S45 = "【별표4】 민사소송 인지액 /【별표5】 송달료"

    def v(self, sec, q, a):
        from data.faq_verify import verify_byeopyo
        return verify_byeopyo({"question": q, "answer": a}, sec)

    def test_lawyer(self):
        q = "소송 금액이 3천만원이면 변호사 보수는 얼마까지 인정돼요?"
        self.assertFalse(self.v(self.S3, q, "3천만원까지는 30만원이 소송비용에 산입됩니다.")[0])            # R043 어댑터 답
        self.assertTrue(self.v(self.S3, q, "200만원 + (3,000만원 - 2,000만원) × 8% = 280만원입니다.")[0])
        bad = self.v(self.S3, "소송목적의 값이 2억5천만원일 때 변호사비용은 어떻게 계산되나요?",
                     "2억원까지 부분은 1%를 적용하고, 그 초과분에는 0.5%를 적용합니다. [1,040만원 + (소송목적의 값 - 2억원) x 1%]")
        self.assertFalse(bad[0])
        self.assertIn("윗구간 비율", " ".join(bad[1]))                                                     # 소규모 시험에서 나온 오답

    def test_stamp(self):
        q = "소송목적의 값이 5천만원이면 인지액은 얼마인가요?"
        self.assertTrue(self.v(self.S45, q, "5,000원 + 5,000만원 × 0.45% = 230,000원입니다.")[0])
        self.assertFalse(self.v(self.S45, q, "5,000원 + 5,000만원 × 0.45% = 235,000원입니다.")[0])

    def test_service(self):
        q = "1심 소송 송달료는 얼마로 잡혀 있어요?"
        self.assertFalse(self.v(self.S45, q, "1심 민사소액, 민사단독, 민사합의 사건의 경우 송달료는 110,000원입니다.")[0])  # R044
        ok = self.v(self.S45, q, "1심 송달료는 민사소액 110,000원, 민사단독·민사합의 165,000원입니다.")
        self.assertTrue(ok is None or ok[0])
        self.assertFalse(self.v(self.S45, q, "1심 송달료는 120,000원입니다.")[0])                         # 표에 없는 금액

    def test_tables_from_limit_table(self):
        from data import faq_verify
        self.assertEqual(faq_verify.lawyer_fee(30_000_000)[0], lawyer_fee_limit(30_000_000))
        self.assertEqual(faq_verify.stamp_fee(25_000_000)[0], stamp_fee(25_000_000))


class LegalEstimateParsing(unittest.TestCase):
    def setUp(self):
        from app.services.payout import legal_estimate
        self.f = legal_estimate

    def test_r043(self):
        e = self.f("소송 금액이 3천만원이면 변호사 보수는 얼마까지 인정돼요?")
        self.assertEqual((e.claim_value, e.lawyer_limit, e.stamp, e.service), (30_000_000, 2_800_000, 140_000, None))

    def test_instance_and_kind(self):
        e = self.f("1심 민사단독인데 청구 금액 2,500만원이면 송달료 얼마예요?")
        self.assertEqual((e.instance, e.case_kind, e.service, e.stamp), ("1심", "민사단독", 165_000, 117_500))
        e = self.f("소가 1억 5천만원 항소심이면 송달료랑 인지액은?")
        self.assertEqual((e.claim_value, e.instance, e.service, e.lawyer_limit), (150_000_000, "항소심", 132_000, 9_400_000))

    def test_not_claim_value(self):
        self.assertIsNone(self.f("변호사비 300만원 냈는데 다 나와요?"))    # 소송 금액이 아니라 보수 금액
        self.assertIsNone(self.f("1심 송달료가 얼마예요?"))                 # 소송 금액도 사건 종류도 없음
        self.assertIsNone(self.f("치료비 33만원 나왔는데 얼마 받아요?"))

    def test_service_only(self):
        """소송 금액 없이 심급(1심은 사건 종류까지)만 — 송달료만 낸다(verify R7)"""
        e = self.f("민사단독 사건으로 1심 소송을 하면 송달료는 얼마예요?")
        self.assertEqual((e.claim_value, e.lawyer_limit, e.stamp, e.instance, e.case_kind, e.service),
                         (None, None, None, "1심", "민사단독", 165_000))
        self.assertEqual(self.f("상고심 가면 송달료는?").service, 88_000)
        # 알려진 한계: 금액이 '소송' 낱말 앞에 오면 소송 금액으로 잡지 않는다(보수 금액 오인을 막는 규칙) — 송달료만
        self.assertIsNone(self.f("1억 5천만원 소송 항소심이면 송달료랑 인지액은?").claim_value)


class LegalCard(unittest.TestCase):
    """payout.legal_card — 특약 가입자에게만, 적용 구간 표시"""
    def setUp(self):
        from app.schemas import Pet, Policy
        from app.services import payout
        self.payout = payout
        def pet(*sections):
            return Pet.model_construct(pet_id="P", name="달이", species="고양이", breed=None, age=None,
                                       policies=[Policy.model_construct(section_name=s, coverage_type=None, copay=None,
                                                                        excluded_conditions=[]) for s in sections])
        self.legal = pet("펫퍼민트 반려묘 통원의료비보장 특별약관", "민사소송법률비용Ⅱ보장 특별약관")
        self.plain = pet("펫퍼민트 반려묘 통원의료비보장 특별약관")

    def test_r6(self):
        c = self.payout.legal_card("소송 금액이 3천만원이면 변호사 보수는 얼마까지 보장돼요?", self.legal)
        self.assertEqual((c.kind, c.claim_value, c.lawyer_limit, c.lawyer_max, c.stamp, c.lawyer_copay, c.lawyer_cap,
                          c.stamp_service_cap), ("legal", 30_000_000, 2_800_000, 2_800_000, 140_000, 100_000, 20_000_000, 10_000_000))
        self.assertEqual(c.bracket, "2,000만원 초과 5,000만원까지 · 200만원 + 초과분 × 8%")

    def test_r7_service_only(self):
        c = self.payout.legal_card("민사단독 사건으로 1심 소송을 하면 송달료는 얼마예요?", self.legal)
        self.assertEqual((c.claim_value, c.bracket, c.lawyer_limit, c.stamp, c.service), (None, None, None, None, 165_000))

    def test_not_subscribed(self):
        self.assertIsNone(self.payout.legal_card("소송 금액이 3천만원이면?", self.plain))
        self.assertIsNone(self.payout.legal_card("소송 금액이 3천만원이면?", None))

    def test_brackets(self):
        b = self.payout.bracket_text
        self.assertEqual(b(2_000_000), "300만원까지 · 정액 30만원")
        self.assertEqual(b(150_000_000), "1억원 초과 1억 5,000만원까지 · 740만원 + 초과분 × 4%")
        self.assertEqual(b(600_000_000), "5억원 초과 · 1,340만원 + 초과분 × 0.5%")


if __name__ == "__main__":
    unittest.main()
