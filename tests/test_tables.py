"""
test_tables.py
답 아래 표 붙이기(2026-10-22, app/services/tables.py) — 표 읽기, 행 강조, 크기 줄이기.
"""

import unittest

from app.services import tables
from tests.test_stage4 import BYEOL

BYEOLPYO3 = """【별표3】
[표]
|소송목적의 값|소송비용에 산입되는 비율 또는 산입액|
|---|---|
|300만원까지 부분|30만원|
|300만원을 초과하여 2,000만원까지 부분 [30만원 + (소송목적의 값 - 300만원) x 10%]|10%|
|2,000만원을 초과하여 5,000만원까지 부분 [200만원 + (소송목적의 값 - 2,000만원) x 8%]|8%|
|5,000만원을 초과하여 1억원까지 부분 [440만원 + (소송목적의 값 - 5,000만원) x 6%]|6%|
|5억원을 초과하는 부분 [1,340만원+ (소송목적의 값 - 5억원) x 0.5%]|0.5%|
"""
TERMS = """[표]
|용어|정의|
|---|---|
|계약자|회사와 계약을 체결하고 보험료를 납입할 의무를 지는 사람|
|보험 수익자|보험금을 청구하여 받을 수 있는 사람|
|피보험자|보험사고의 대상이 되는 사람|
"""


class Tables(unittest.TestCase):
    def test_parse(self):
        t = tables.parse_tables(BYEOLPYO3)
        self.assertEqual(len(t), 1)
        self.assertEqual(t[0]["header"][0], "소송목적의 값")
        self.assertEqual(len(t[0]["rows"]), 5)

    def test_range_highlight(self):
        t = tables.parse_tables(BYEOLPYO3)[0]
        self.assertEqual(tables.highlight(t, "소송 금액이 3천만원이면 변호사비는요?", None), 2)
        self.assertEqual(tables.highlight(t, "6억원 소송이면요?", None), 4)
        self.assertEqual(tables.highlight(t, "200만원짜리 소송이면요?", None), 0)

    def test_term_highlight(self):
        t = tables.parse_tables(TERMS)[0]
        self.assertEqual(tables.highlight(t, "피보험자가 누구예요?", BYEOL), 2)
        self.assertIsNone(tables.highlight(t, "해지하면 어떻게 돼요?", BYEOL))     # 맞는 행이 없으면 강조하지 않는다

    def test_trim(self):
        big = {"header": ["a", "b"], "rows": [[str(i), "x"] for i in range(30)]}
        rows, idx, collapsed = tables.trim(big, 10)
        self.assertEqual((idx, collapsed), ([9, 10, 11], True))
        rows, idx, collapsed = tables.trim(big, None)
        self.assertEqual((len(rows), collapsed), (tables.MAX_ROWS, True))

    def test_answer_tables(self):
        items = tables.answer_tables([("【별표3】", BYEOLPYO3)], "1억짜리 소송이면 변호사비가 얼마예요?", None)
        self.assertEqual((len(items), items[0].highlight, items[0].collapsed), (1, 3, False))


if __name__ == "__main__":
    unittest.main()
