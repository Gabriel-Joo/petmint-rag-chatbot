"""
test_rule_first.py
1안(2026-10-23) — 지급사유 조항의 예외 항이 발췌 본문이면 같은 조 제1항(원칙) 참조를 본문 앞으로 옮긴다.
"""

import unittest

from app.services.answer import rule_first

SEC = "펫퍼민트 반려묘 입원의료비Ⅲ보장 특별약관"
RULE = {"article_num": 1, "paragraph_num": 1, "section_name": SEC, "citation_label": "제1조(보험금의 지급사유) 제1항",
        "content": "회사는 … 질병 또는 상해가 발생하여 … 보상합니다."}
OTHER = {"article_num": 15, "paragraph_num": 6, "section_name": "반려동물 비용손해 관련 특별약관 일반조항", "citation_label": "제15조 제6항",
         "content": "재가입 …"}


def hit(**kw):
    return {"section": "특별약관", "section_name": SEC, "article_num": 1, "article_title": "보험금의 지급사유",
            "content": "제1항에도 불구하고 … 30일 이내에 발생한 질병은 보상하지 않습니다.", "reference_contents": [RULE, OTHER]} | kw


class RuleFirstTest(unittest.TestCase):
    def test_moves_rule_into_body(self):
        r = rule_first([hit()])[0]
        self.assertTrue(r["content"].startswith("회사는"))
        self.assertIn("30일 이내", r["content"])
        self.assertEqual(r["reference_contents"], [OTHER])         # 원칙만 빠지고 다른 참조는 그대로

    def test_other_articles_untouched(self):
        h = hit(article_title="보험금을 지급하지 않는 사유", article_num=2)
        self.assertEqual(rule_first([h]), [h])

    def test_without_rule_reference(self):
        h = hit(reference_contents=[OTHER])
        self.assertEqual(rule_first([h]), [h])


if __name__ == "__main__":
    unittest.main()
