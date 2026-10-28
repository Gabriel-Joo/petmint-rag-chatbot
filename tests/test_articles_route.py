"""
test_articles_route.py
조항 원문 API가 사내규정 코퍼스도 받는지 — 사내규정 답의 근거 조항을 열면 422가 났다(2026-10-23 운영 로그, Species가 강아지·고양이만).
"""

import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import deps
from app.routers import articles


def client(content: str | None) -> tuple[TestClient, mock.Mock]:
    builder = mock.Mock()
    builder.fetch_article_content.return_value = content
    builder.fetch_article_rows.return_value = [{"content": content or "", "paragraph_num": None, "coverage_type": None}]
    builder.chunks = {"강아지": [{"content": content or ""}]}
    app = FastAPI()
    app.include_router(articles.router)
    app.dependency_overrides[deps.builder] = lambda: builder
    return TestClient(app), builder


class ArticleRouteTest(unittest.TestCase):
    def test_hr_article(self):
        c, b = client("월 3회 이상 무단지각한 직원은 징계할 수 있다.")
        r = c.get("/api/articles/인사규정/본칙/제6장 교육 및 평가/33")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["species"], "인사규정")
        b.fetch_article_content.assert_called_once_with("인사규정", "본칙", "제6장 교육 및 평가", 33, None, None)

    def test_pet_article(self):
        c, _ = client("본문")
        r = c.get("/api/articles/강아지/보통약관/_/8")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["content"], "본문")                       # 원문은 그대로
        self.assertEqual(r.json()["sections"][0]["blocks"][0]["text"], "본문")  # 표시용 블록은 더해진다

    def test_hr_article_has_no_display_blocks(self):
        c, _ = client("월 3회 이상 무단지각한 직원은 징계할 수 있다.")
        self.assertIsNone(c.get("/api/articles/인사규정/본칙/제6장 교육 및 평가/33").json()["sections"])

    def test_unknown_corpus(self):
        c, _ = client("본문")
        self.assertEqual(c.get("/api/articles/토끼/보통약관/_/8").status_code, 422)


if __name__ == "__main__":
    unittest.main()
