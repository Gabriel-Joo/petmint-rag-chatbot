"""근거 패널 약관 원문 표시(article_display) — 표시만 바꾸고 원문은 그대로"""

import unittest

from app.services.article_display import Vocab, article_sections, blocks_of, snippet

V = Vocab({"강아지": [{"content": "국내 동물병원에서 치료를 받은\n반려동물에게 질병이 발생하여\n동물병원 진료비"}]})


def texts(blocks):
    return [b.get("text") or b.get("title") for b in blocks]


class Unwrap(unittest.TestCase):
    def test_mid_word_and_space_breaks(self):
        b = blocks_of("국내 동물\n병원에서 치료를 받은 반려동물에게\n질병이 발생하여", V)
        self.assertEqual(texts(b), ["국내 동물병원에서 치료를 받은 반려동물에게 질병이 발생하여"])

    def test_items_start_new_paragraph(self):
        b = blocks_of("다음과 같습니다.\n ① 청구서\n ② 사고증명서(동물\n병원 영수증)", V)
        self.assertEqual(texts(b), ["다음과 같습니다.", "① 청구서", "② 사고증명서(동물병원 영수증)"])
        self.assertTrue(b[1]["item"])

    def test_gi_is_not_a_list_marker_mid_sentence(self):
        b = blocks_of(" ④ 피보험자의 임신, 출산, 산후\n기. 그러나 보험금을 지급합니다.", V)
        self.assertEqual(len(b), 1)

    def test_page_break_blank_lines_inside_sentence(self):
        b = blocks_of("아래에 열거된 행위로 인하여 제3조\n\n\n\n(보험금의 지급사유)의 상해 관련", V)
        self.assertEqual(len(b), 1)

    def test_private_glyph_removed(self):
        self.assertNotIn("\uf000", texts(blocks_of("\uf000회사는 보상합니다.", V))[0])


class Structure(unittest.TestCase):
    def test_box(self):
        b = blocks_of("보상합니다.\n\n【심신상실】\n 정신병 등으로 인하\n 여 능력이 없는 상태\n\n ② 다음 항목", V)
        self.assertEqual([x["kind"] for x in b], ["p", "box", "p"])
        self.assertEqual(b[1]["title"], "심신상실")
        self.assertFalse(b[1]["example"])

    def test_example_box(self):
        b = blocks_of("【보험금 지급금액(자기부담금 3만원인 경우)[예시]】\n ①통원 중 수술을 하지 않은 경우", V)
        self.assertTrue(b[0]["example"])

    def test_space_aligned_table(self):
        b = blocks_of("      항목                     자기부담금        지급 한도\n      통원 중 수술을 하지 않은 날    1일당 3만원    1일당 30만원", V)
        self.assertEqual(b[0]["kind"], "table")
        self.assertEqual(b[0]["rows"][1], ["통원 중 수술을 하지 않은 날", "1일당 3만원", "1일당 30만원"])

    def test_grades_and_paragraph_labels(self):
        rows = [{"content": "한도 1,500만원", "paragraph_num": 1, "coverage_type": "고급형"},
                {"content": "30일 이내", "paragraph_num": 3, "coverage_type": "고급형"},
                {"content": "한도 700만원", "paragraph_num": 1, "coverage_type": "실속형"},
                {"content": "한도 1,000만원", "paragraph_num": 1, "coverage_type": "기본형"}]
        s = article_sections(rows, "실속형", V)
        self.assertEqual([(x["grade"], x["mine"]) for x in s], [("실속형", True), ("고급형", False), ("기본형", False)])
        self.assertEqual(texts(s[1]["blocks"]), ["제1항", "한도 1,500만원", "제3항", "30일 이내"])
        self.assertEqual(texts(s[0]["blocks"]), ["한도 700만원"])           # 항 하나면 머리 없음

    def test_split_rows_of_same_paragraph_joined_first(self):
        rows = [{"content": " ② 사고증명서(촬영일자 필수),", "paragraph_num": 1, "coverage_type": None},
                {"content": "   기타 지불 증빙서류 등)", "paragraph_num": 1, "coverage_type": None}]
        self.assertEqual(texts(article_sections(rows, None, V)[0]["blocks"]), ["② 사고증명서(촬영일자 필수), 기타 지불 증빙서류 등)"])

    def test_snippet(self):
        self.assertEqual(snippet("국내 동물\n병원에서\n\n【정의】\n 수의사", V), "국내 동물병원에서 정의 수의사")


if __name__ == "__main__":
    unittest.main()
