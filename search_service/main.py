"""
search_service/main.py
search-service — data/search_engine.py를 감싸는 얇은 HTTP 래퍼(09번 7-3절). 호스트(GPU)에서 띄우고 Pod의 앱이 부른다.
검색 로직은 여기 두지 않는다 — 노트북 01~08은 SearchEngine을 직접 import하고, 서비스만 HTTP로 같은 코드를 부른다(3-3절).

  POST /search  {query, scope, top_k, candidate_k} → SearchEngine.search의 list[dict] 그대로
                scope는 SearchScope.describe() 결과 — from_describe로 되살린다
  GET  /health  모델이 올라왔는지(장치), Milvus에 닿는지, 코퍼스별 컬렉션이 있는지

기동할 때 KURE·리랭커를 올려 상주시킨다(요청마다 올리면 느리다). 16GB 하나를 Ollama와 나눠 쓰므로
추론은 락으로 한 번에 하나씩만 한다 — worker도 1개(모델이 프로세스 안에 있다).

실행(리포 루트, llm_env): python -m search_service.main
  PETMINT_SEARCH_HOST(기본 192.168.122.1 — VM 사설망의 호스트 쪽 주소, 14번 1-4절) / PETMINT_SEARCH_PORT(기본 8100)
"""

import os
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pymilvus.exceptions import MilvusException

from data.search_engine import COLLECTION_NAMES, SearchEngine
from data.search_scope import SearchScope

HOST = os.environ.get("PETMINT_SEARCH_HOST", "192.168.122.1")
PORT = int(os.environ.get("PETMINT_SEARCH_PORT", "8100"))

_gpu_lock = threading.Lock()   # 임베딩·리랭커 추론을 한 번에 하나씩. 핸들러가 동기라 스레드풀에서 돈다 → threading.Lock


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = SearchEngine()   # 모델 로드·청크·BM25 — 끝나야 포트를 연다
    yield


app = FastAPI(title="petmint search-service", lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str
    scope: dict                                # SearchScope.describe()
    top_k: int = Field(5, ge=1)                # 기본값은 SearchEngine.search와 같다
    candidate_k: int = Field(20, ge=1)


@app.post("/search")
def search(req: SearchRequest) -> list[dict]:
    engine: SearchEngine = app.state.engine
    try:
        scope = SearchScope.from_describe(req.scope)
    except (KeyError, TypeError, ValueError) as e:   # 키 누락·모양 오류·모르는 종/특약/등급(__post_init__)
        raise HTTPException(422, f"scope를 되살릴 수 없다: {e!r}")
    if scope.species not in engine.chunks:
        raise HTTPException(422, f"올라오지 않은 코퍼스: {scope.species}")
    try:
        with _gpu_lock:
            return engine.search(req.query, scope, top_k=req.top_k, candidate_k=req.candidate_k)
    except MilvusException as e:                     # Milvus가 내려갔거나 컬렉션이 없다(색인 전 코퍼스)
        raise HTTPException(503, f"Milvus: {e}")


@app.get("/health")
def health():
    engine: SearchEngine = app.state.engine
    models = {"embedding": str(engine.embedding_model.device), "reranker": str(engine.reranker.device)}
    try:
        collections = set(engine.client.list_collections())
        milvus = True
    except MilvusException:
        collections, milvus = set(), False
    corpora = {species: COLLECTION_NAMES[species] in collections for species in engine.chunks}
    # 장치가 cpu면 GPU에 못 올라간 것(지연이 크게 는다) — 실패로 본다. 색인 전 코퍼스(인사규정)는 corpora에만 드러낸다
    ok = milvus and all(d.startswith("cuda") for d in models.values())
    return JSONResponse({"ok": ok, "models": models, "milvus": milvus, "corpora": corpora},
                        status_code=200 if ok else 503)


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, workers=1)
