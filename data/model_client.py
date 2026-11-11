"""
data/model_client.py
model-service(공용 임베딩 · 리랭커 서비스, ~/AI_programming/model-service, 192.168.122.1:8200) HTTP 클라이언트.

SearchEngine(models_url=...)일 때 SentenceTransformer · CrossEncoder 자리에 들어간다. 그래서 SearchEngine.search와
search_service가 쓰는 모양만 흉내 낸다 — encode(texts, normalize_embeddings=...) → float32 ndarray,
predict(pairs) → float32 ndarray. 그 밖의 속성(tokenizer · device 등)은 없다(2026-11-11 저장소 전수 확인 — 쓰는 곳 없음).
모델 상태(장치 · 판)는 model-service만 안다 → health()로 그 응답을 그대로 받는다.

값은 JSON을 거쳐도 그대로다 — 서비스가 float32를 파이썬 float로 내고(값 그대로), JSON 표기는 왕복 손실이 없고,
여기서 float32로 되돌린다. 로컬에 올렸을 때와 비트까지 같다.
"""

import httpx
import numpy as np

# 연결은 짧게(서비스가 내려가 있으면 바로 503으로), 추론은 넉넉히(리랭커 후보 100개 · 1024토큰)
TIMEOUT = httpx.Timeout(30, connect=2)


class ModelServiceError(RuntimeError):
    """model-service에 닿지 않거나 오류를 냈다 — search_service가 503으로 바꾼다"""


def _post(url: str, body: dict) -> dict:
    try:
        r = httpx.post(url, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ModelServiceError(f"{url}: {e!r}") from e


class RemoteEmbedder:
    def __init__(self, base_url: str):
        self.url = base_url.rstrip("/") + "/embed"

    def encode(self, texts: list[str], normalize_embeddings: bool = False) -> np.ndarray:
        # SentenceTransformer.encode와 같은 기본값(normalize_embeddings=False) — 부르는 쪽은 모두 True를 넘긴다
        out = _post(self.url, {"texts": list(texts), "normalize": normalize_embeddings})
        return np.asarray(out["vectors"], dtype=np.float32)


class RemoteReranker:
    def __init__(self, base_url: str):
        self.url = base_url.rstrip("/") + "/rerank"

    def predict(self, pairs: list[tuple[str, str]]) -> np.ndarray:
        # model-service는 질의 하나 + 문서[]를 받는다. SearchEngine.search는 모든 쌍에 같은 질의를 쓴다
        queries = {q for q, _ in pairs}
        if len(queries) != 1:
            raise ValueError(f"질의가 하나여야 한다 — {len(queries)}개")
        out = _post(self.url, {"query": pairs[0][0], "documents": [d for _, d in pairs]})
        return np.asarray(out["scores"], dtype=np.float32)


def health(base_url: str) -> dict:
    """model-service GET /health 응답 그대로({ok, models: {embedding: {name, device, dtype, ...}, reranker: {...}}}).
    닿지 않으면 ModelServiceError. 503(cpu로 떠 있음)이어도 본문을 돌려준다 — ok가 false다"""
    try:
        r = httpx.get(base_url.rstrip("/") + "/health", timeout=httpx.Timeout(5, connect=2))
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ModelServiceError(f"{base_url}/health: {e!r}") from e
