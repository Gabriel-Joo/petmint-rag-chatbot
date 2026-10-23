"""
sibling_sim.py
같은 조 형제 항 데려오기 오프라인 모의(2026-10-24) — 서버와 같은 순서로 프롬프트를 만든 뒤(build_full_context → display_parent →
rule_first → fit_to_budget) 발췌 조의 형제 항을 규칙별로 본문 뒤에 붙여, 정답 문구가 프롬프트에 드는지·토큰·예산 컷을 잰다.
모델은 부르지 않는다. 평가 220 보이는 세트의 단독 질문 모델 턴(측정 폴더 1회차 기준)만 본다.

  규칙  now     지금(붙이지 않음)
        all     발췌 조의 형제 항 전부
        exc     지급사유 조에서 "제1항에도 불구하고"로 시작하는 항(원칙의 예외 — 대기기간 30일·1년 등)
        pool    검색 후보(섹션 가중 순 20개) 4위 이하에 든 형제 항 — 검색이 이미 질문과 가깝다고 본 것만
        pool8   pool을 8위까지로
        exc+pool8
        piece   pool과 같은 후보지만 항 전체가 아니라 그 조각(호 묶음 ≤300자)만 — 면책 조처럼 항이 긴 조
        exc+piece

  python -m scripts.sibling_sim logs/coverage/a3b [--out data/review/sibling_sim.md]
"""

import argparse
import json
import re
import statistics
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from pymilvus import MilvusClient

from app import config
from app.services import policy_data
from app.services.answer import PROMPT_BUDGET, SEARCH_TOP_K, count_tokens, cut_weak_results, display_parent, rule_first
from app.services.customers import scope_for
from app.services.retrieval import Retriever
from data import prompts
from data.rag_context import SECTION_PRIORITY, ContextBuilder, build_full_context
from scripts.eval_serving import flat, pets

ROOT = Path(__file__).resolve().parent.parent
RULES = ("now", "all", "exc", "pool", "pool8", "exc+pool8", "piece", "exc+piece")
EXC_HEAD = "제1항에도불구하고"


def article_key(c: dict) -> tuple:
    return (c.get("section"), c.get("section_name"), c.get("article_num"), c.get("coverage_type"))


def paragraphs(chunks: list[dict]) -> dict[tuple, list[tuple]]:
    """조 → [(항 번호, 부모 글)] — v3 조각은 부모(원래 항 청크) 하나로 모은다"""
    out = defaultdict(dict)
    for c in chunks:
        if c.get("article_num") is None:
            continue
        key = c.get("parent_key") or id(c)
        out[article_key(c)].setdefault(key, (c.get("paragraph_num"), (c.get("parent_content") or c["content"]).strip()))
    return {k: sorted(v.values(), key=lambda x: (x[0] is None, x[0] or 0)) for k, v in out.items()}


def parent_of(r: dict, chunks: list[dict]) -> tuple | None:
    c = next((c for c in chunks if article_key(c) == article_key(r) and c["content"].strip() == r["content"].strip()), None)
    return None if c is None else (c.get("paragraph_num"), (c.get("parent_content") or c["content"]).strip())


def attach(results: list[dict], picks: dict[int, list[str]]) -> list[dict]:
    return [{**r, "content": r["content"] + "".join("\n" + t for t in picks.get(i, []))} for i, r in enumerate(results)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", default=str(ROOT / "data/review/sibling_sim.md"))
    a = ap.parse_args()
    d = ROOT / a.run
    rep = json.loads(next(x for x in sorted(d.glob("eval_serving_*.json")) if not x.name.endswith(".judge.json")).read_text())
    cases = json.loads((ROOT / "data/eval/eval220.json").read_text(encoding="utf-8"))["cases"]
    turns = {t["id"]: t for c in cases for t in (c.get("turns") or [c])}
    pm = pets()
    chunks, graphs = policy_data.load()
    builder = ContextBuilder(client=MilvusClient(uri=config.MILVUS_URL), chunks=chunks, graphs=graphs)
    rt = Retriever(config.SEARCH_SERVICE_URL, expand=config.SEARCH_EXPAND, variant=config.SEARCH_VARIANT,
                   pool_k=config.SEARCH_POOL, expand_dict=config.SEARCH_EXPAND_DICT)
    paras = {sp: paragraphs(chunks[sp]) for sp in ("강아지", "고양이")}

    stat = {k: defaultdict(list) for k in RULES}
    per_id = defaultdict(dict)
    picked = [r for r in rep["turns"] if r["run"] == 0 and r.get("prompt_logged") and not r.get("context")
              and not r.get("clarify") and not r.get("code_answer") and r["id"] in turns]
    for r in picked:
        t = turns[r["id"]]
        pet = pm[t["pet_id"]]
        sp, q, scope = pet.species, t["query"], scope_for(pet)
        res = build_full_context(rt, builder, q, scope, SEARCH_TOP_K)
        res = rule_first(display_parent(cut_weak_results(res, "업무특화"), builder, sp))
        raw = rt.search(q, scope, top_k=20, candidate_k=20)
        for x in raw:
            x["adjusted_score"] = x["score"] * SECTION_PRIORITY.get(x.get("section"), 0.8)
        raw.sort(key=lambda x: x["adjusted_score"], reverse=True)
        pool = [(i + 1, article_key(x), parent_of(x, chunks[sp]), x["content"].strip()) for i, x in enumerate(raw)]
        gold = [flat(g["evidence"]) for g in (t.get("gold") or [])]
        for rule in RULES:
            seen = flat("".join(x["content"] + "".join(y.get("content") or "" for y in x.get("reference_contents") or [])
                                for x in res))
            picks, first_of = defaultdict(list), {}
            for i, x in enumerate(res):
                first_of.setdefault(article_key(x), i)
            for ak, i in first_of.items():
                cand = []
                sib = paras[sp].get(ak, [])
                if rule == "all":
                    cand = [p for p in sib]
                if "exc" in rule and "보험금의 지급사유" in (res[i].get("article_title") or ""):
                    cand += [p for p in sib if flat(p[1]).startswith(EXC_HEAD)]
                if "pool" in rule:
                    lim = 8 if "pool8" in rule else 20
                    cand += [p for rank, k, p, _ in pool if rank > SEARCH_TOP_K and rank <= lim and k == ak and p]
                if "piece" in rule:
                    cand += [(None, piece) for rank, k, _, piece in pool if rank > SEARCH_TOP_K and k == ak]
                for p in cand:
                    if flat(p[1]) not in seen:
                        seen += flat(p[1])
                        picks[i].append(p[1])
            out = attach(res, picks)
            items = [replace(prompts.ExcerptItem.from_search_result(x), key=str(i)) for i, x in enumerate(out)]
            full = count_tokens(prompts.build_user_content(q, items))
            kept = prompts.fit_to_budget(q, items, PROMPT_BUDGET, count_tokens)
            text = flat(prompts.build_user_content(q, kept))
            s = stat[rule]
            s["tokens"].append(count_tokens(prompts.build_user_content(q, kept)))
            s["over"].append(full > PROMPT_BUDGET)
            s["dropped"].append(len(items) - len(kept))
            s["added"].append(sum(len(v) for v in picks.values()))
            if gold:
                hit = any(g in text for g in gold)
                s["gold"].append(hit)
                per_id[r["id"]][rule] = hit

    n = len(picked)
    L = [f"# 같은 조 형제 항 데려오기 모의 — {a.run} 1회차 단독 질문 모델 턴 {n}개", "",
         "| 규칙 | 정답 문구가 프롬프트에 | 붙인 항(턴당) | 예산 넘친 턴 | 예산 컷으로 빠진 발췌 | 토큰 평균 · 최대 |", "|---|---|---|---|---|---|"]
    for rule in RULES:
        s = stat[rule]
        L.append(f"| {rule} | {sum(s['gold'])}/{len(s['gold'])} | {statistics.mean(s['added']):.2f} | {sum(s['over'])} | "
                 f"{sum(s['dropped'])} | {statistics.mean(s['tokens']):.0f} · {max(s['tokens'])} |")
    L += ["", "## 규칙별로 정답 문구가 들고 나는 문항 (now 대비)", "", "| 규칙 | 새로 듦 | 빠짐 |", "|---|---|---|"]
    for rule in RULES[1:]:
        gain = sorted(i for i, v in per_id.items() if v.get(rule) and not v.get("now"))
        loss = sorted(i for i, v in per_id.items() if v.get("now") and not v.get(rule))
        L.append(f"| {rule} | {' '.join(gain) or '-'} | {' '.join(loss) or '-'} |")
    out = Path(a.out)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
