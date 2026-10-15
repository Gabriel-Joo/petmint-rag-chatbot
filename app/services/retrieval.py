"""
retrieval.py
search-service HTTP 호출(09 7-3). 앱은 GPU를 쓰지 않는다 — KURE·리랭커·Milvus 조회는 호스트의 search-service가 하고,
앱은 SearchScope를 넘겨 결과만 받는다. 모드마다 리트리버가 다르다(업무특화=약관, 사내규정=인사규정, 일반=없음).

이번 범위는 인터페이스만. 구현은 search_service/main.py와 함께 한다.
"""

from data.search_scope import SearchScope

from app.schemas import SourceItem


class Retriever:
    def __init__(self, base_url: str):
        self.base_url = base_url

    async def health(self) -> bool:
        raise NotImplementedError("search-service 헬스체크 — lifespan에서 부른다")

    async def search(self, query: str, scope: SearchScope, top_k: int = 3) -> list[SourceItem]:
        """scope.describe()를 보내고 rag_context 조립까지 끝난 발췌를 받는다.
        query는 scope.retrieval_query()를 거친 문장이어야 한다(등급 표현 제거는 scope가 정한다)."""
        raise NotImplementedError("search-service 호출")
