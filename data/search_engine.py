"""
search_engine.py
펫퍼민트 약관 RAG 검색 엔진 — Hybrid Search(BM25+Dense) + Reranker + 메타데이터 필터
02번(테스트)과 04번(실제 RAG 서비스)이 공통으로 import해서 쓰는 "진실의 원천" 모듈.
"""

import re
from pathlib import Path
import json

import torch
from pymilvus import MilvusClient
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi

from data.search_scope import SearchScope

BASE_DIR = Path(__file__).parent  # data/ 폴더 기준
CHUNKS_DIR = BASE_DIR / "chunks"

MILVUS_URI = "http://localhost:19530"
EMBEDDING_MODEL_NAME = "nlpai-lab/KURE-v1"
RERANKER_MODEL_NAME = "BAAI/bge-reranker-v2-m3"
# 512토큰이면 1000자 청크(≈580토큰)의 뒷부분을 못 보고 채점 → 1024. fp16으로 지연·메모리를 512 fp32 이하로 유지
# (2026-10-12 측정: 꼬리질의 MRR 0.677→0.702/0.596→0.647, 대조군·실제질문 불변, 평균 443→200ms, p95 555→362ms)
RERANKER_MAX_LENGTH = 1024

# 키는 '종 또는 코퍼스'다(SearchScope.species와 같은 값). 인사규정은 09 사내규정 모드용(data/hr_preprocess.py)
COLLECTION_NAMES = {
    "강아지": "petmint_dog",
    "고양이": "petmint_cat",
    "인사규정": "hr_regulation",
}

CHUNK_FILES = {
    "강아지": CHUNKS_DIR / "petmint_강아지.json",
    "고양이": CHUNKS_DIR / "petmint_고양이.json",
    "인사규정": CHUNKS_DIR / "hr_인사규정.json",
}


def build_embedding_text(c: dict) -> str:
    """임베딩(02번 색인)·BM25·리랭커 공용 텍스트 — 메타데이터를 맥락으로 앞에 붙여 검색 정확도를 높인다.
    02번이 이 함수를 import해 색인하므로 질의 시점과 색인 시점의 텍스트가 항상 같다.
    context_prefix(분할된 뒷조각의 '다음 각 호' 도입 문장/제목 경로, 01번)는 헤더 다음 줄에 둔다 —
    content에는 넣지 않아 fetch 결합 시 중복되지 않는다. dense 결과(Milvus)와 BM25 결과(JSON)가 같은 헤더를
    갖도록 Milvus에도 context_prefix 필드가 있어야 한다."""
    parts = []
    if c.get("section_name"):
        parts.append(c["section_name"])
    if c.get("type"):
        parts.append(f"유형{c['type']}")
    if c.get("coverage_type"):
        parts.append(c["coverage_type"])
    if c.get("article_title"):
        parts.append(c["article_title"])
    header = " / ".join(parts)
    lines = []
    if header:
        lines.append(f"[{header}]")
    if c.get("context_prefix"):
        lines.append(f"[{c['context_prefix']}]")
    lines.append(c["content"])
    return "\n".join(lines)


def build_rerank_text(c: dict) -> str:
    """리랭커 입력 = 라벨 한 줄 + build_embedding_text. build_embedding_text 헤더에는 section·조번호가 없다(보통약관은
    section_name도 None) — 리랭커만 라벨을 더 본다(색인·BM25 텍스트는 그대로라 재색인 불필요).
    2026-10-18 검색 실험(data/search_experiments.py "라벨+중복제거", 회귀 세트 97문항): 조항 중복 제거와 함께
    hit@5 88 → 90, MRR 0.762 → 0.798, 잃은 문항 없음. 라벨만으로는 87(R001·R074를 잃음)이라 중복 제거와 짝이다."""
    parts = [c.get("section"), c.get("section_name")]
    if c.get("article_num") is not None:
        parts.append(f"제{c['article_num']}조" + (f"({c['article_title']})" if c.get("article_title") else ""))
    if c.get("coverage_type"):
        parts.append(c["coverage_type"])
    return "[" + " | ".join(p for p in parts if p) + "]\n" + build_embedding_text(c)


class SearchEngine:
    """한 번만 초기화해서(모델 로드), 여러 번 검색에 재사용하는 엔진 객체"""

    def __init__(self):
        print("임베딩 모델 로드 중...")
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        print("리랭커 로드 중...")
        self.reranker = CrossEncoder(RERANKER_MODEL_NAME, max_length=RERANKER_MAX_LENGTH,
                                     model_kwargs={"torch_dtype": torch.float16})
        self.client = MilvusClient(uri=MILVUS_URI)

        self.chunks = {}
        self.bm25_index = {}
        for species, path in CHUNK_FILES.items():
            if not path.exists():          # 전처리 전인 코퍼스는 건너뛴다
                continue
            chunks = self._load_chunks(species)
            self.chunks[species] = chunks
            self.bm25_index[species] = self._build_bm25(chunks)
        print("검색 엔진 초기화 완료")

    def _load_chunks(self, species: str) -> list[dict]:
        with open(CHUNK_FILES[species], "r", encoding="utf-8") as f:
            return json.load(f)

    def _simple_tokenize(self, text: str) -> list[str]:
        text = re.sub(r"[^\w\s가-힣]", " ", text)
        return text.split()

    def _build_embedding_text(self, c: dict) -> str:
        return build_embedding_text(c)

    def _build_bm25(self, chunks: list[dict]):
        corpus_texts = [self._build_embedding_text(c) for c in chunks]
        tokenized = [self._simple_tokenize(t) for t in corpus_texts]
        return BM25Okapi(tokenized)

    @staticmethod
    def _dedup_key(c: dict):
        """후보 중복 제거용 고유 식별자. content 앞부분이 같아도(한도표 등)
        등급·유형·조·항·분할조각까지 달라 서로 덮어쓰지 않는다. None 혼재해도 안전(튜플).
        안내류는 조·항·등급이 전부 None이라 메타만으로는 축퇴하므로 content로 구분한다
        (Milvus와 청크 JSON의 content가 동일하다는 전제 — dense/BM25 병합이 이 키로 이뤄짐).
        item_num/sub_label 등은 Milvus 스키마에 없어 dense 쪽 키와 어긋나므로 쓰지 않는다."""
        return (c.get("section"), c.get("section_name"), c.get("type"), c.get("article_num"),
                c.get("paragraph_num"), c.get("coverage_type"), c.get("chunk_index"), c.get("content"))

    def search(self, query: str, scope: SearchScope, top_k: int = 5,
               candidate_k: int = 20, min_content_len: int = 15) -> list[dict]:
        """Hybrid Search(BM25+Dense) → 메타데이터 필터 → Reranker 최종 정렬.
        필터는 scope가 정한다(가입 정보 / 질문 속 등급·유형 — SearchScope.from_query). 질문 문자열에서 직접 뽑지 않는다.
        검색 문장은 scope.retrieval_query — 필터가 맡은 등급·유형 단어를 뺀다(남겨 두면 그 등급 한도표 행을 끌어온다)."""
        query = scope.retrieval_query(query)
        species = scope.species
        collection_name = COLLECTION_NAMES[species]
        chunks = self.chunks[species]
        bm25 = self.bm25_index[species]
        filter_expr = scope.milvus_expr()

        # --- Dense 검색 ---
        query_vec = self.embedding_model.encode([query], normalize_embeddings=True)[0].tolist()
        dense_results = self.client.search(
            collection_name=collection_name,
            data=[query_vec],
            limit=candidate_k,
            filter=filter_expr,
            output_fields=["content", "section", "section_name", "type", "coverage_type", "article_num", "article_title",
                           "paragraph_num", "chunk_index", "context_prefix"],
        )[0]

        # --- BM25 검색 ---
        tokenized_query = self._simple_tokenize(query)
        bm25_scores = bm25.get_scores(tokenized_query)
        # 범위 밖 청크를 먼저 거르고 상위 candidate_k — 예전엔 상위 k를 자른 뒤 걸러 범위 안 후보가 k보다 적게 남았다
        bm25_ranked_idx = sorted((i for i in range(len(bm25_scores)) if scope.allows(chunks[i])),
                                 key=lambda i: bm25_scores[i], reverse=True)[:candidate_k]

        # --- 후보 합치기 (최소 길이 필터. 메타데이터 필터는 dense=Milvus 식, BM25=scope.allows로 이미 적용) ---
        candidates = {}
        for hit in dense_results:
            c = hit["entity"]
            if len(c["content"].strip()) < min_content_len:
                continue
            candidates[self._dedup_key(c)] = c
        for idx in bm25_ranked_idx:
            c = chunks[idx]
            if len(c["content"].strip()) < min_content_len:
                continue
            candidates[self._dedup_key(c)] = c

        candidate_list = list(candidates.values())
        if not candidate_list:
            return []

        # --- Reranker ---
        pairs = [(query, build_rerank_text(c)) for c in candidate_list]
        rerank_scores = self.reranker.predict(pairs)
        ranked = sorted(zip(candidate_list, rerank_scores), key=lambda x: x[1], reverse=True)[:top_k]

        return [{"score": float(score), **c} for c, score in ranked]