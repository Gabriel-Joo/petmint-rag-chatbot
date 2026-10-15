"""
조항 원문(7-1). Milvus id가 아니라 구조 경로로 받는다 — id는 재색인하면 바뀐다.
경로 값이 null인 조문(보통약관의 section_name, 별표 등의 article_num)은 NULL_SEGMENT로 보낸다.
section_name에 '/'가 든 것이 있어('【별표4】 민사소송 인지액 /【별표5】 송달료') path 변환기로 받는다.
"""

from fastapi import APIRouter, HTTPException

from app.schemas import ArticleOut, Grade, Species

router = APIRouter(prefix="/api/articles", tags=["articles"])

NULL_SEGMENT = "_"


def _nullable(segment: str) -> str | None:
    return None if segment == NULL_SEGMENT else segment


@router.get("/{species}/{section}/{section_name:path}/{article_num}", response_model=ArticleOut)
def get_article(species: Species, section: str, section_name: str, article_num: str,
                coverage_type: Grade | None = None, paragraph_num: int | None = None):
    """구현 때 ContextBuilder.fetch_article_content(species, section, section_name, article_num,
    coverage_type, paragraph_num)를 그대로 부른다. 지금은 더미"""
    num = _nullable(article_num)
    if num is not None and not num.isdigit():
        raise HTTPException(422, f"article_num은 숫자 또는 {NULL_SEGMENT!r}: {article_num}")
    return ArticleOut(species=species, section=section, section_name=_nullable(section_name),
                      article_num=int(num) if num is not None else None, coverage_type=coverage_type,
                      paragraph_num=paragraph_num, content="(더미) 조항 원문")
