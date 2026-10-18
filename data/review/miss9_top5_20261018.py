"""검색 회귀 놓친 9문항(R010·R014·R017·R018·R022·R024·R035·R060·R094) 상위 5 청크 복원 — gold 재검수용(docs/저녁실행.md 5-1) — GPU(fp16, SearchEngine 그대로). search_with_graph와 같은 단계(engine.search top20 → 섹션 가중 → 상위 5), 참조 붙이기만 뺐다."""
import json, sys, torch
torch.set_num_threads(6)
from data import search_regression as R
from data.search_engine import SearchEngine
from data.rag_context import SECTION_PRIORITY
MISS = ["R010", "R014", "R017", "R018", "R022", "R024", "R035", "R060", "R094"]
cases = {c["id"]: c for c in R.load_cases()}
old = {c["id"]: c for c in json.load(open("data/eval/results/search_regression_20261013_A_current.json"))["cases"]}
eng = SearchEngine()
print("device", eng.reranker.model.device, eng.reranker.model.dtype, file=sys.stderr)
out = {}
for qid in MISS:
    case = cases[qid]; scope = R.scope_of(case)
    raw = eng.search(case["query"], scope, top_k=20, candidate_k=20)
    for r in raw:
        r["adjusted_score"] = r["score"] * SECTION_PRIORITY.get(r.get("section"), 0.8)
    raw.sort(key=lambda r: r["adjusted_score"], reverse=True)
    top = raw[:5]
    labels = [R._brief(r) for r in top]
    rank = next((i for i, r in enumerate(top, 1) if any(R.matches(r, g) for g in case["gold"])), None)
    out[qid] = {"labels": labels, "same_as_A_current": labels == old[qid]["top"], "rank": rank,
                "top": [{k: r.get(k) for k in ("section", "section_name", "article_num", "article_title", "coverage_type",
                                               "paragraph_num", "chunk_index", "score", "adjusted_score", "content")} for r in top]}
    print(qid, "같음" if labels == old[qid]["top"] else "다름", rank, file=sys.stderr, flush=True)
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1, default=float)
