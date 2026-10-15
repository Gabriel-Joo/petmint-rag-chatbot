"""
hr_index.py
인사규정 청크(data/chunks/hr_인사규정.json, hr_preprocess.py 산출)를 Milvus `hr_regulation` 컬렉션에 적재한다 — 02의 사내규정판.
임베딩 모델(KURE-v1)을 올리므로 GPU를 쓴다. 청크 49개라 수 초.

스키마는 02와 같은 골격이다. species는 빼고(컬렉션 자체가 코퍼스), chapter_num·effective_date를 더한다.
type·coverage_type은 늘 null이지만 남긴다 — search_engine의 dense output_fields와 rag_context가 이 필드를 꺼내므로,
없으면 검색 코드를 코퍼스마다 갈라야 한다.

실행: python -m data.hr_index [--search-check]   (--search-check: 적재 후 회귀 세트 search_regression_hr.json 실행)
"""

import argparse
import json
import sys

from pymilvus import DataType, MilvusClient

from data.search_engine import (COLLECTION_NAMES, CHUNK_FILES, EMBEDDING_MODEL_NAME, MILVUS_URI,
                                build_embedding_text)

CORPUS = "인사규정"


def create_collection(client: MilvusClient, name: str):
    if client.has_collection(name):
        client.drop_collection(name)
    schema = client.create_schema(auto_id=True, enable_dynamic_field=True)
    schema.add_field("id", DataType.INT64, is_primary=True)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=1024)
    schema.add_field("content", DataType.VARCHAR, max_length=12000)
    schema.add_field("section", DataType.VARCHAR, max_length=64)                       # 본칙/부칙/별표
    schema.add_field("section_name", DataType.VARCHAR, max_length=256, nullable=True)   # 제N장 이름 / 부칙 / 별표N 이름
    schema.add_field("chapter_num", DataType.INT64, nullable=True)
    schema.add_field("article_num", DataType.INT64, nullable=True)                     # 별표는 null
    schema.add_field("article_title", DataType.VARCHAR, max_length=256, nullable=True)
    schema.add_field("paragraph_num", DataType.INT64, nullable=True)                   # 조 단위 청크라 null
    schema.add_field("type", DataType.VARCHAR, max_length=5, nullable=True)            # 호환용(늘 null)
    schema.add_field("coverage_type", DataType.VARCHAR, max_length=10, nullable=True)  # 호환용(늘 null)
    schema.add_field("chunk_index", DataType.INT64)
    schema.add_field("chunk_total", DataType.INT64)
    schema.add_field("printed_page_start", DataType.INT64)
    schema.add_field("printed_page_end", DataType.INT64)
    schema.add_field("citations_raw", DataType.VARCHAR, max_length=4000, nullable=True)
    schema.add_field("context_prefix", DataType.VARCHAR, max_length=1024, nullable=True)
    schema.add_field("effective_date", DataType.VARCHAR, max_length=10, nullable=True)
    idx = client.prepare_index_params()
    idx.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(collection_name=name, schema=schema, index_params=idx)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--search-check", action="store_true")
    args = ap.parse_args(argv)
    from sentence_transformers import SentenceTransformer
    chunks = json.loads(CHUNK_FILES[CORPUS].read_text(encoding="utf-8"))
    client = MilvusClient(uri=MILVUS_URI)
    name = COLLECTION_NAMES[CORPUS]
    create_collection(client, name)
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    vecs = model.encode([build_embedding_text(c) for c in chunks], normalize_embeddings=True)
    rows = [{"vector": v.tolist(), "content": c["content"], "section": c["section"], "section_name": c["section_name"],
             "chapter_num": c["chapter_num"], "article_num": c["article_num"], "article_title": c["article_title"],
             "paragraph_num": None, "type": None, "coverage_type": None,
             "chunk_index": c["chunk_index"], "chunk_total": c["chunk_total"],
             "printed_page_start": c["printed_page_range"][0], "printed_page_end": c["printed_page_range"][1],
             "citations_raw": ", ".join(x["raw"] for x in c["citations"]) or None,
             "context_prefix": c["context_prefix"], "effective_date": c["effective_date"]} for c, v in zip(chunks, vecs)]
    client.insert(collection_name=name, data=rows)
    n = len(client.query(collection_name=name, filter="chunk_index >= 0", output_fields=["chunk_index"], limit=1000))
    print(f"{name}: {n}행 적재(청크 {len(chunks)}개)")
    assert n == len(chunks)
    if args.search_check:
        from data import rag_context, search_engine, search_regression as R
        engine = search_engine.SearchEngine()
        builder = rag_context.ContextBuilder(client=engine.client, chunks=engine.chunks)
        from data.search_scope import SearchScope
        print("scope 일치:", R.check_scope_consistency(engine, [SearchScope.unrestricted(CORPUS)]) or "0건 불일치")
        rep = R.run(R.new_search_fn(engine, builder), R.load_cases(R.HR_CASES_PATH))
        R.print_summary(rep)
        print("ref_gold:", {k: (v["ref_ok"], v["ref_n"]) for k, v in rep["summary"].items() if v["ref_n"]})
        print("저장:", R.save(rep, "hr"))


if __name__ == "__main__":
    sys.exit(main())
