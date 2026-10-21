"""
probe_train_gold.py
rebuild5 학습 데이터(7단계) 라벨 비율을 정하기 전 측정 — 학습 QA(rebuild4 final 7,480건)의 질문을 서빙 B 경로
(v2 조각 검색 + 질의 확장 + 원래 청크 표시, 1차 후보 20, top3)로 검색했을 때 정답 단위가 발췌에 '저절로' 들어오는 비율.

정답 일치는 두 단계로 센다(v1 단위 레코드 ↔ v2 부모 글이라 키가 다르다):
- article: 같은 section·section_name·article_num(·coverage_type)
- text: 정답 레코드 본문 앞 40자(공백 제거)가 표시된 글(본문 또는 참조 조문)에 들어 있다
결과는 JSON(QA별)과 요약을 남긴다. 검색은 search-service(HTTP), 생성 모델은 쓰지 않는다.

  PETMINT_CHUNKS_DIR=data/chunks/v2 PETMINT_GRAPH_DIR=data/graph/v2 PETMINT_SEARCH_VARIANT=v2 PETMINT_SEARCH_EXPAND=1 \
    python -m scripts.probe_train_gold --out logs/stage7/train_gold.json [--limit N]
"""

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

from pymilvus import MilvusClient

from app import config
from app.services import policy_data
from app.services.answer import SEARCH_TOP_K, display_parent
from app.services.retrieval import Retriever
from data import rag_context
from data.faq_units import is_human_target, make_units, unit_id
from data.search_scope import SearchScope

FINAL = Path("data/faq/rebuild4/rw/checked")
V1 = Path("data/chunks")


def flat(t: str) -> str:
    return re.sub(r"\s+", "", t or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    assert config.SEARCH_VARIANT == "v2" and config.DISPLAY_PARENT, "B 조건 env를 주고 돌린다(모듈 docstring)"
    chunks, graphs = policy_data.load()
    builder = rag_context.ContextBuilder(client=MilvusClient(uri=config.MILVUS_URL), chunks=chunks, graphs=graphs)
    retriever = Retriever(config.SEARCH_SERVICE_URL, expand=config.SEARCH_EXPAND, variant=config.SEARCH_VARIANT, pool_k=config.SEARCH_POOL,
                      expand_dict=config.SEARCH_EXPAND_DICT)
    rows, t0 = [], time.time()
    for species in ("강아지", "고양이"):
        v1 = json.load(open(V1 / f"petmint_{species}.json")) if (V1 / f"petmint_{species}.json").exists() else None
        units = {unit_id(u): u for u in make_units(v1 if v1 is not None else chunks[species])}
        qas = json.load(open(FINAL / f"petmint_{species}_faq_final.json"))
        for qa in qas[: a.limit] if a.limit else qas:
            if is_human_target(qa) or qa["unit_id"] not in units:
                continue
            unit = units[qa["unit_id"]]
            res = rag_context.build_full_context(retriever, builder, qa["question"], SearchScope.unrestricted(species), SEARCH_TOP_K)
            res = display_parent(res, builder, species)
            heads = [flat(r["content"])[:40] for r in unit["records"] if len(flat(r["content"])) >= 20]
            shown = [flat((r.get("context_prefix") or "") + r["content"]) for r in res]
            refs = [flat(x.get("content", "") if isinstance(x, dict) else str(x)) for r in res for x in (r.get("reference_contents") or [])]
            keys = {(r["section"], r.get("section_name"), r.get("article_num")) for r in unit["records"]}
            rank_a = next((i for i, r in enumerate(res, 1) if (r["section"], r.get("section_name"), r.get("article_num")) in keys
                           and (r.get("article_num") is not None or any(h in shown[i - 1] for h in heads))), None)
            rank_t = next((i for i, s in enumerate(shown, 1) if any(h in s for h in heads)), None)
            rows.append({"species": species, "unit_id": qa["unit_id"], "question": qa["question"], "n": len(res),
                         "rank_article": rank_a, "rank_text": rank_t, "in_refs": any(h in x for h in heads for x in refs),
                         "flags": qa.get("flags", [])})
            if len(rows) % 500 == 0:
                print(f"{len(rows)} {time.time() - t0:.0f}s", flush=True)
    n = len(rows)
    c = Counter()
    for r in rows:
        c["article"] += r["rank_article"] is not None
        c["text"] += r["rank_text"] is not None
        c["text_or_ref"] += r["rank_text"] is not None or r["in_refs"]
        c["any"] += r["rank_article"] is not None or r["rank_text"] is not None or r["in_refs"]
        c[f"n_excerpts_{r['n']}"] += 1
    summary = {"n": n, **{k: v for k, v in c.items()}, **{f"{k}_pct": round(100 * v / n, 1) for k, v in c.items()},
               "minutes": round((time.time() - t0) / 60, 1)}
    json.dump({"summary": summary, "rows": rows}, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
