"""
retrieval.py
search-service HTTP 호출(09 7-3). 앱은 GPU를 쓰지 않는다 — KURE·리랭커·Milvus 조회는 호스트의 search-service가 하고,
앱은 SearchScope를 넘겨 관련 청크 top-k만 받는다. 모드마다 리트리버가 다르다(업무특화=약관, 사내규정=인사규정, 일반=없음).

발췌 조립(섹션 가중, 그래프로 참조 조문 붙이기, 길이 예산)은 Pod가 한다 — GPU가 필요 없고 규칙이 자주 바뀌어
앱만 롤링하면 되게 한다. Retriever는 SearchEngine.search와 같은 모양이라 rag_context.build_full_context(retriever,
app.state.builder, ...)에 엔진 대신 그대로 넘긴다(노트북은 진짜 엔진, 서비스는 이 클라이언트).
build_full_context가 동기이고 ContextBuilder도 Milvus를 동기로 읽으므로 search도 동기다 — 턴 파이프라인에서
asyncio.to_thread로 통째로 돌린다.

search-service가 한 번에 하나씩만 추론하므로(락) 앞 요청이 끝날 때까지 기다릴 수 있다 — 읽기 제한을 넉넉히 둔다.
"""

import httpx

from data.search_scope import SearchScope

SEARCH_TIMEOUT = httpx.Timeout(30, connect=3)


class Retriever:
    def __init__(self, base_url: str, expand: bool = False, variant: str | None = None, pool_k: int | None = None):
        self.base_url = base_url.rstrip("/")
        self.expand, self.variant, self.pool_k = expand, variant, pool_k    # 질의 확장·실험 청크 묶음·1차 후보 깊이 — 기본 끔

    async def health(self) -> bool:
        """search-service GET /health가 ok(모델이 GPU에 있고 Milvus에 닿는다)인가. 닿지 않으면 False"""
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self.base_url}/health")
            return r.status_code == 200 and r.json().get("ok") is True
        except (httpx.HTTPError, ValueError):
            return False

    def search(self, query: str, scope: SearchScope, top_k: int = 5, candidate_k: int = 20) -> list[dict]:
        """SearchEngine.search와 같은 인자·반환. 리랭커 순 청크 top_k개 — {"score", 청크 필드(content·section·section_name·
        type·coverage_type·article_num·article_title·paragraph_num·chunk_index·context_prefix)}.
        조립된 발췌가 아니다(references·reference_contents 없음). 섹션 가중 재정렬은 Pod의 search_with_graph가 하므로
        그쪽이 top_k=candidate_k로 후보를 넉넉히 받아 간다.
        query는 사용자 질문 그대로 보낸다 — scope.retrieval_query는 search-service 안의 SearchEngine.search가 적용한다.
        scope는 scope.describe()로 보내고 search-service가 같은 SearchScope로 되살린다."""
        r = httpx.post(f"{self.base_url}/search", timeout=SEARCH_TIMEOUT,
                       json={"query": query, "scope": scope.describe(), "top_k": top_k, "candidate_k": candidate_k}
                       | ({"expand": True} if self.expand else {}) | ({"variant": self.variant} if self.variant else {})
                       | ({"pool_k": self.pool_k} if self.pool_k else {}))
        r.raise_for_status()
        return r.json()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """search-service POST /embed — KURE 문장 임베딩(정규화). 금액 되묻기 판별(intent.py)이 쓴다"""
        r = httpx.post(f"{self.base_url}/embed", timeout=SEARCH_TIMEOUT, json={"texts": texts})
        r.raise_for_status()
        return r.json()["vectors"]
