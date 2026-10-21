"""
eval_check_prompts.py
측정 도구 자체 검사 — 서버가 남긴 프롬프트(PETMINT_PROMPT_LOG)를 같은 라이브러리 함수로 오프라인에서 다시 만들어 글자까지 같은지 본다.
같으면 (1) 프롬프트 기록이 모델이 본 것을 그대로 담고 있고 (2) 오프라인 실험(청킹 변형 등)이 서버와 같은 발췌를 만든다는 뜻이다.
후속 질문(앞 턴과 이어 붙임)·되묻기로 고른 턴은 앞 대화가 필요해 빼고, 단독 질문 턴만 본다.

  python -m scripts.eval_check_prompts --result data/eval/results/eval_serving_….json --prompt-log logs/eval/prompts_ft.jsonl [--n 30]
"""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from pymilvus import MilvusClient

from app import config
from app.schemas import Pet
from app.services import policy_data
from app.services.answer import PROMPT_BUDGET, SEARCH_TOP_K, count_tokens, cut_weak_results, display_parent
from app.services.customers import scope_for
from app.services.retrieval import Retriever
from data import prompts
from data.rag_context import ContextBuilder, build_full_context

ROOT = Path(__file__).resolve().parent.parent


def rebuild(question: str, pet: Pet, retriever: Retriever, builder: ContextBuilder) -> list[dict]:
    """서버 answer.run_turn → _generate와 같은 순서(단독 질문, 업무특화)"""
    results = build_full_context(retriever, builder, question, scope_for(pet), SEARCH_TOP_K)
    results = cut_weak_results(results, "업무특화")
    if config.DISPLAY_PARENT:
        results = display_parent(results, builder, pet.species)
    items = prompts.fit_to_budget(question, [replace(prompts.ExcerptItem.from_search_result(x), key=str(i))
                                            for i, x in enumerate(results)], PROMPT_BUDGET, count_tokens)
    return prompts.build_messages(question, items, system=prompts.SYSTEM_PROMPT, excerpt_header=prompts.EXCERPT_HEADER)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--prompt-log", required=True)
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()
    report = json.loads(Path(args.result).read_text(encoding="utf-8"))
    logged = {}
    for line in Path(args.prompt_log).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        logged[row["turn_id"]] = row
    cases = json.loads((ROOT / "data" / "eval" / "eval220.json").read_text(encoding="utf-8"))["cases"]
    turns = {t["id"]: t for c in cases for t in (c.get("turns") or [c])}
    cs = json.loads((ROOT / "app" / "fixtures" / "customers.json").read_text(encoding="utf-8"))
    pets = {p["pet_id"]: Pet.model_validate(p) for c in cs for p in c["pets"]}
    chunks, graphs = policy_data.load()
    builder = ContextBuilder(client=MilvusClient(uri=config.MILVUS_URL), chunks=chunks, graphs=graphs)
    retriever = Retriever(config.SEARCH_SERVICE_URL, expand=config.SEARCH_EXPAND, variant=config.SEARCH_VARIANT, pool_k=config.SEARCH_POOL,
                      expand_dict=config.SEARCH_EXPAND_DICT)
    picked = [r for r in report["turns"] if r["turn_id"] in logged and not r["context"] and not r.get("clarify")][: args.n]
    same, diff = 0, []
    for r in picked:
        t = turns[r["id"]]
        want = logged[r["turn_id"]]["messages"]
        got = rebuild(t["query"], pets[t["pet_id"]], retriever, builder)
        if got == want:
            same += 1
        else:
            diff.append(r["id"])
    print(f"단독 질문 턴 {len(picked)}개 중 서버 프롬프트와 글자까지 같음 {same}, 다름 {len(diff)} {diff}")
    raise SystemExit(1 if diff else 0)


if __name__ == "__main__":
    main()
