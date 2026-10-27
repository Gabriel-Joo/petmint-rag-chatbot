"""보통약관 사람 보험 조 낮추기·같은 제목 의료비 특약 조 올리기(rag_context.human_article_adjust) — 검색 서버 없이"""

import unittest

from data.rag_context import human_article_adjust

MED2 = "펫퍼민트 반려견 통원의료비Ⅱ보장 특별약관"


def r(section, art, score, name=None):
    return dict(section=section, section_name=name, article_num=art, adjusted_score=score)


def labels(rs):
    return [(x["section_name"] or x["section"], x["article_num"]) for x in rs]


class HumanArticleAdjust(unittest.TestCase):
    def pool(self):
        return [r("보통약관", 5, 0.9), r("보통약관", 5, 0.8), r("보통약관", 19, 0.5),
                r("특별약관", 2, 0.45, MED2), r("특별약관", 1, 0.4, MED2)]

    def test_off_is_none(self):
        self.assertIsNone(human_article_adjust(False, False))

    def test_demote_halves_human_articles_only(self):
        out = human_article_adjust(True, False)("보험금 안 나오는 경우는?", self.pool(), 3)
        self.assertEqual(labels(out)[:3], [("보통약관", 19), ("보통약관", 5), (MED2, 2)])

    def test_twin_lifts_same_title_rider_article(self):
        out = human_article_adjust(False, True)("보험금 안 나오는 경우는?", self.pool(), 3)
        self.assertEqual(labels(out)[:3], [(MED2, 2), ("보통약관", 5), ("보통약관", 5)])

    def test_twin_skips_when_question_names_rider(self):
        for q in ("통원비 안 나오는 경우는?", "치료비 못 받는 경우는?", "보장 안 되는 질병은?"):
            out = human_article_adjust(False, True)(q, self.pool(), 3)
            self.assertEqual(labels(out)[:1], [("보통약관", 5)], q)

    def test_twin_needs_candidate_in_pool(self):
        pool = [r("보통약관", 5, 0.9), r("보통약관", 19, 0.5), r("보통약관", 2, 0.4), r("특별약관", 4, 0.3, "법률비용")]
        out = human_article_adjust(False, True)("보험금 안 나오는 경우는?", pool, 3)
        self.assertEqual(labels(out), labels(pool))

    def test_procedure_articles_untouched(self):
        pool = [r("보통약관", 20, 0.9), r("보통약관", 29, 0.8), r("특별약관", 2, 0.7, MED2)]
        out = human_article_adjust(True, True)("청약 철회는 며칠까지예요?", pool, 3)
        self.assertEqual(labels(out), labels(pool))


if __name__ == "__main__":
    unittest.main()
