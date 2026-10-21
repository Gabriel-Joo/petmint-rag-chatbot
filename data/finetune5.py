"""
finetune5.py
rebuild5(7단계, 2026-10-21) 학습 샘플 — 서빙 B 경로로 만든다. 설정 원본: data/review/rebuild5_stage7_config.md

rebuild4(finetune_data)와 다른 점: 발췌를 정답 단위 + 방해 발췌로 '조립'하지 않고, 질문을 서빙과 같은 검색(v2 조각 + 질의 확장 +
원래 청크 표시, 1차 후보 20, top3, 참조 조문, 서버 예산 fit_to_budget)에 넣어 나온 발췌를 그대로 쓴다. 학습 때 본 발췌와 서빙 때
보는 발췌의 모양을 맞추려는 것이다(rebuild4는 짧은 발췌에서 거절 3 → 16).

라벨 3가지(QA 하나에 샘플 하나 — rebuild4의 같은 질문 양성·음성 쌍(distract_pair)은 만들지 않는다):
- natural : 정답이 서빙 발췌에 저절로 들어 있다 → 서빙 발췌 그대로 + 원래 답
- insert  : 정답이 없고, 판정(na_qjudge q2, gemma4:12b)이 발췌 중 하나라도 full·partial → 마지막 발췌를 정답 단위로 바꾼다 + 원래 답
            (답의 근거가 발췌에 있게 — 다른 발췌가 일부만 답하면 원래 답의 나머지를 지어내게 된다)
- no_answer: 정답이 없고, 판정이 발췌 셋 모두 none → 서빙 발췌 그대로 + 거절 문장(prompts.NO_ANSWER_TEXT)
정답 일치: 정답 단위 레코드 본문 앞 40자(공백 제거)가 표시된 발췌 본문이나 참조에 있거나, 같은 조(조번호 있는 것)
(scripts/probe_train_gold.py와 같은 규칙).

  PETMINT_CHUNKS_DIR=data/chunks/v2 PETMINT_GRAPH_DIR=data/graph/v2 PETMINT_SEARCH_VARIANT=v2 PETMINT_SEARCH_EXPAND=1 \
  PETMINT_DISPLAY_PARENT=1 PETMINT_EXPAND_DICT=<v1|v2> python -m data.finetune5 --final-dir data/faq/rebuild5/rw/checked \
    --out-dir data/finetune/rebuild5
"""

import argparse
import json
import random
import re
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from pymilvus import MilvusClient

from app import config
from app.services import policy_data
from app.services.answer import PROMPT_BUDGET, SEARCH_TOP_K, count_tokens, display_parent
from app.services.retrieval import Retriever
from data import na_qjudge, prompts, rag_context
from data.faq_units import is_human_target, make_units, unit_id
from data.finetune_data import MAX_LENGTH, TokenCounter, is_val, write_jsonl
from data.search_scope import SearchScope

SPECIES = ("강아지", "고양이")
SEED = 20261021
JUDGE_VER = "q2"
JUDGE_CACHE = Path("data/finetune/na_qjudge_cache.json")       # finetune_data와 같은 캐시(질문·발췌 키)


def flat(t: str) -> str:
    return re.sub(r"\s+", "", t or "")


def gold_rank(res: list[dict], unit: dict) -> int | None:
    heads = [flat(r["content"])[:40] for r in unit["records"] if len(flat(r["content"])) >= 20]
    keys = {(r["section"], r.get("section_name"), r.get("article_num")) for r in unit["records"] if r.get("article_num") is not None}
    for i, r in enumerate(res, 1):
        shown = flat((r.get("context_prefix") or "") + r["content"])
        refs = flat(" ".join(x.get("content", "") if isinstance(x, dict) else str(x) for x in r.get("reference_contents") or []))
        if any(h in shown or h in refs for h in heads) or (r["section"], r.get("section_name"), r.get("article_num")) in keys:
            return i
    return None


def serving_items(question: str, res: list[dict]) -> list[prompts.ExcerptItem]:
    """서버 _generate와 같은 발췌 — 위치 키, 글자 수 어림 예산(PROMPT_BUDGET)"""
    return prompts.fit_to_budget(question, [replace(prompts.ExcerptItem.from_search_result(x), key=str(i)) for i, x in enumerate(res)],
                                 PROMPT_BUDGET, count_tokens)


def excerpt_text(it: prompts.ExcerptItem) -> str:
    return "\n".join([it.label, it.content] + [f"[참조] {r.label}\n{r.content}" for r in it.references])


def judge_items(question: str, items: list[prompts.ExcerptItem], cache: dict, st: Counter) -> list[str]:
    out = []
    for it in items:
        ex = excerpt_text(it)
        k = na_qjudge.cache_key(question, ex, JUDGE_VER)
        if k not in cache:
            cache[k] = na_qjudge.judge_checked(question, ex, JUDGE_VER)
            st["judge_calls"] += 1
        out.append(cache[k]["verdict"] or "none")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sample", type=int, help="시험용 — 종마다 무작위 N건(라벨 비율 어림)")
    a = ap.parse_args()
    assert config.SEARCH_VARIANT == "v2" and config.DISPLAY_PARENT and config.SEARCH_EXPAND, "B 조건 env(모듈 docstring)"
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks, graphs = policy_data.load()
    builder = rag_context.ContextBuilder(client=MilvusClient(uri=config.MILVUS_URL), chunks=chunks, graphs=graphs)
    v1 = rag_context.ContextBuilder()                       # 정답 단위·참조는 생성 때와 같은 v1 청크로
    retriever = Retriever(config.SEARCH_SERVICE_URL, expand=True, variant=config.SEARCH_VARIANT, pool_k=config.SEARCH_POOL,
                          expand_dict=config.SEARCH_EXPAND_DICT)
    count = TokenCounter()
    cache = json.loads(JUDGE_CACHE.read_text(encoding="utf-8")) if JUDGE_CACHE.exists() else {}
    st, train, val, t0 = Counter(), [], [], time.time()
    for sp in SPECIES:
        units = {unit_id(u): u for u in make_units(v1.chunks[sp])}
        qas = json.loads((Path(a.final_dir) / f"petmint_{sp}_faq_final.json").read_text(encoding="utf-8"))
        if a.sample:
            qas = random.Random(SEED).sample(qas, min(a.sample, len(qas)))
        for qa in qas[: a.limit] if a.limit else qas:
            if is_human_target(qa):
                st["excluded_human_target"] += 1
                continue
            unit = units.get(qa["unit_id"])
            if unit is None:
                st["unit_missing"] += 1
                continue
            q = qa["question"]
            res = display_parent(rag_context.build_full_context(retriever, builder, q, SearchScope.unrestricted(sp), SEARCH_TOP_K),
                                 builder, sp)
            items = serving_items(q, res)
            rank = gold_rank(res, unit)
            verdicts = None
            if rank is not None:
                kind, target = "natural", qa["answer"]
            else:
                verdicts = judge_items(q, items, cache, st)
                if all(v == "none" for v in verdicts):
                    kind, target = "no_answer", prompts.NO_ANSWER_TEXT
                else:
                    gold = prompts.ExcerptItem.from_unit(unit, v1.resolve_references(unit, sp, source_chunks=unit["records"]))
                    items = (items[:-1] if len(items) >= SEARCH_TOP_K else items) + [replace(gold, key="gold")]
                    kind, target = "insert", qa["answer"]
            gold_pos = next((i for i, it in enumerate(items) if it.key == "gold"), None)
            skeleton = prompts.build_training_messages(q, target, [])
            budget = MAX_LENGTH - (count.chat_len(skeleton) - count(skeleton[1]["content"])) - 8
            messages = prompts.build_training_messages(q, target, items, budget=budget, count_tokens=count,
                                                       protected=frozenset() if gold_pos is None else frozenset({gold_pos}))
            n_tokens = count.chat_len(messages)
            if n_tokens > MAX_LENGTH:
                st["too_long"] += 1
                continue
            st[f"kind_{kind}"] += 1
            meta = {"species": sp, "unit_id": qa["unit_id"], "kind": kind, "gold_rank": rank, "gold_pos": gold_pos,
                    "n_items": messages[1]["content"].count("[발췌 "), "verdicts": verdicts, "n_tokens": n_tokens,
                    "flags": qa.get("flags", []), "repair": qa.get("repair"), "question_rw4": qa.get("question_rw4"),
                    "answer_rw4": qa.get("answer_rw4"), "prompt_version": prompts.PROMPT_VERSION}
            (val if is_val(qa["unit_id"]) else train).append({"messages": messages, "meta": meta})
            n = len(train) + len(val)
            if n % 500 == 0:
                JUDGE_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                print(f"{n} {time.time() - t0:.0f}s {dict(st)}", flush=True)
    JUDGE_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    random.Random(SEED).shuffle(train)
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "val.jsonl", val)
    n = len(train) + len(val)
    kinds = Counter(s["meta"]["kind"] for s in train + val)
    stats = {**st, "train": len(train), "val": len(val), "kinds": dict(kinds),
             "kind_pct": {k: round(100 * v / n, 1) for k, v in kinds.items()},
             "gold_rank": dict(Counter(str(s["meta"]["gold_rank"]) for s in train + val)),
             "pet_subject_flag": sum("pet_subject" in str(s["meta"]["flags"]) for s in train + val),
             "expand_dict": config.SEARCH_EXPAND_DICT or "v1", "minutes": round((time.time() - t0) / 60, 1),
             "final_dir": a.final_dir, "seed": SEED, "max_length": MAX_LENGTH, "prompt_budget": PROMPT_BUDGET}
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
