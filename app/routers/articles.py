"""
조항 원문(7-1). Milvus id가 아니라 구조 경로로 받는다 — id는 재색인하면 바뀐다.
경로 값이 null인 조문(보통약관의 section_name, 별표 등의 article_num)은 NULL_SEGMENT로 보낸다.
section_name에 '/'가 든 것이 있어('【별표4】 민사소송 인지액 /【별표5】 송달료') path 변환기로 받는다.
본문은 ContextBuilder.fetch_article_content를 그대로 부른다(Milvus 행을 원문 순서로 잇는다) — 평가와 같은 코드.
"""

from fastapi import APIRouter, Depends, HTTPException

from data.rag_context import ContextBuilder

from app import deps
from app.schemas import ArticleOut, Grade, Species

router = APIRouter(prefix="/api/articles", tags=["articles"])

NULL_SEGMENT = "_"


def _nullable(segment: str) -> str | None:
    return None if segment == NULL_SEGMENT else segment


@router.get("/{species}/{section}/{section_name:path}/{article_num}", response_model=ArticleOut)
def get_article(species: Species, section: str, section_name: str, article_num: str,
                coverage_type: Grade | None = None, paragraph_num: int | None = None,
                builder: ContextBuilder = Depends(deps.builder)):
    num = _nullable(article_num)
    if num is not None and not num.isdigit():
        raise HTTPException(422, f"article_num은 숫자 또는 {NULL_SEGMENT!r}: {article_num}")
    name, n = _nullable(section_name), int(num) if num is not None else None
    content = builder.fetch_article_content(species, section, name, n, coverage_type, paragraph_num)
    if content is None:
        raise HTTPException(404, f"조항 없음: {species}/{section}/{section_name}/{article_num}")
    return ArticleOut(species=species, section=section, section_name=name, article_num=n,
                      coverage_type=coverage_type, paragraph_num=paragraph_num, content=content)
