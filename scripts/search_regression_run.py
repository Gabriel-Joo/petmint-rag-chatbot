"""
search_regression_run.py
검색 회귀(data/search_regression.py)를 search-service(HTTP)로 돌린다 — 서버와 같은 경로. 질의 확장·청크 묶음은 플래그로.
--compare로 이전 결과와 문항별 순위를 대조한다(기본 설정이 바뀌지 않았는지 확인할 때).

  python -m scripts.search_regression_run --out logs/x [--expand] [--variant v2] [--compare 이전_pet.json]
"""

import argparse
import json
from pathlib import Path

from app import config
from app.services.retrieval import Retriever
from data import rag_context
from data import search_regression as R


def ranks(rep: dict) -> dict:
    return {c["id"]: (c.get("rank"), [t if isinstance(t, str) else (t.get("section_name"), t.get("article_num")) for t in c.get("top", [])]) for c in rep["cases"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--expand", action="store_true")
    ap.add_argument("--variant")
    ap.add_argument("--pool", type=int, help="1차 후보 깊이(pool_k)")
    ap.add_argument("--dict", help="질의 확장 사전 판(v1·v2) — --expand와 같이")
    ap.add_argument("--human-demote", action="store_true", help="보통약관 사람 보험 조 낮추기(PETMINT_HUMAN_DEMOTE)")
    ap.add_argument("--twin", action="store_true", help="같은 제목 의료비 특약 조 올리기(PETMINT_TWIN_ARTICLE)")
    ap.add_argument("--compare", help="이전 약관 결과 JSON — 문항별 gold 순위가 같은지")
    args = ap.parse_args()
    eng = Retriever(config.SEARCH_SERVICE_URL, expand=args.expand, variant=args.variant, pool_k=args.pool, expand_dict=args.dict)
    builder = rag_context.ContextBuilder()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, path in [("pet", R.CASES_PATH), ("hr", R.HR_CASES_PATH)]:
        if name == "hr" and args.variant:
            continue                                 # 인사규정은 청크 묶음 실험 대상이 아니다
        rep = R.run(R.new_search_fn(eng, builder, rag_context.human_article_adjust(args.human_demote, args.twin)),
                    R.load_cases(path))
        print("==", name)
        R.print_summary(rep)
        (out / f"search_regression_{name}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        if name == "pet" and args.compare:
            a, b = ranks(json.loads(Path(args.compare).read_text(encoding="utf-8"))), ranks(rep)
            diff = {k: (a.get(k), b.get(k)) for k in a if a.get(k) != b.get(k)}
            print(f"이전과 gold 순위가 다른 문항 {len(diff)}: {diff}")


if __name__ == "__main__":
    main()
