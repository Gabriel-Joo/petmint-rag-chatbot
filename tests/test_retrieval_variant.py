"""
test_retrieval_variant.py
Retriever가 청크 묶음(variant)을 약관 검색에만 붙이는지 — 인사규정에는 v3 컬렉션이 없다(2026-10-23 운영 반영 점검).
"""

import unittest
from unittest import mock

from app.services import retrieval
from data.search_scope import SearchScope


def sent(species: str) -> dict:
    resp = mock.Mock()
    resp.json.return_value = []
    with mock.patch.object(retrieval.httpx, "post", return_value=resp) as post:
        retrieval.Retriever("http://x", expand=True, variant="v3").search("질문", SearchScope.unrestricted(species), 3)
    return post.call_args.kwargs["json"]


class VariantTest(unittest.TestCase):
    def test_variant_on_policy(self):
        self.assertEqual(sent("강아지").get("variant"), "v3")

    def test_no_variant_on_hr(self):
        s = sent("인사규정")
        self.assertNotIn("variant", s)
        self.assertTrue(s["expand"])


if __name__ == "__main__":
    unittest.main()
