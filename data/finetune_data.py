"""
finetune_data.py
07 파인튜닝 학습 샘플 생성 — 06 최종 FAQ를 RAG 추론과 같은 형식(data/prompts.py)의 chat 샘플로 바꾼다.

C안(2026-10-13 확정): 실제 RAG 상황처럼 발췌를 주고, 검색이 빗나갔을 때 지어내지 않는 법도 가르친다.
- distract 70%: 정답 발췌 + 방해 발췌 1~2개(순서 섞음) → 원래 답변
- gold_only 20%: 정답 발췌만 → 원래 답변
- no_answer 10%: 방해 발췌만(최대 2개) → prompts.NO_ANSWER_TEXT (코드가 정한 고정 문장, LLM 생성 아님)
정답 발췌 = 05가 그 QA를 만들 때 본 단위 원문 + 참조(unit_id로 복원, prompts.ExcerptItem.from_unit).
방해 발췌 = 그 질문으로 실제 검색한 결과(SearchScope.unrestricted — 고객 없는 일반 질문) 중 정답 단위가 아닌 것.
val은 unit_id 단위로 나눈다 — 같은 단위를 다른 표현으로 물은 QA가 train·val에 갈라지면 val loss가 과대평가된다.
목표 답변은 "근거: …"를 뗀다(prompts.strip_citation) — 근거 표기는 서비스에서 코드가 단다.

방해 발췌 거르기는 샘플 종류마다 엄격도가 다르다(2026-10-13 첫 생성 측정):
- no_answer(엄격): 방해 발췌에 답이 섞이면 "있는 답을 없다고 하라"를 가르친다 → 본문+참조 전부에서 답변과 8자 이상 겹치면 제외,
  정답 단위와 40자 이상 겹치면 제외(통원↔입원 반복 문장), 정답과 같은 조(조번호 없는 별표·안내는 같은 문서)도 제외.
- distract(완화): 정답 발췌가 함께 있으므로 방해에 답 비슷한 내용이 있어도 틀린 답을 가르치지 않는다 → 방해 청크 본문만 보고
  답변과 20자, 정답 단위와 40자 이상 겹치면 제외. 8자 기준을 그대로 쓰면 '정하지 않은 사항은', '계약자나 피보험자는' 같은
  상투구에 걸려 방해 후보가 사라졌다(1개 이상 남은 QA 60% → distract 41%에 그침, 목표 70%).
- 종류 배정은 자격을 먼저 세고 한다: 방해 후보가 없고 엄격 후보만 있는 QA를 no_answer에 먼저 쓴다(그래야 distract 몫이 남는다).

실행: python -m data.finetune_data [--search-only] (검색은 GPU 필요, 결과는 cache에 저장해 재실행 시 재사용)
"""

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

from data import prompts
from data.faq_units import make_units, unit_id
from data.rag_context import _flat_cite, graph_key
from data.search_scope import SearchScope

BASE_DIR = Path(__file__).parent
FINAL_FILES = {sp: BASE_DIR / "faq" / "checked" / f"petmint_{sp}_faq_final.json" for sp in ("강아지", "고양이")}
OUT_DIR = BASE_DIR / "finetune"
SEARCH_CACHE = OUT_DIR / "search_cache.json"
BASE_MODEL_DIR = BASE_DIR.parent / "models" / "base" / "Tri-7B"

SEED = 20261013
TARGET = {"distract": 0.70, "gold_only": 0.20, "no_answer": 0.10}
VAL_RATIO = 0.10
MAX_LENGTH = 3072          # 07 학습 시퀀스 상한(토큰). 넘는 샘플은 발췌를 줄이고(fit_to_budget), 그래도 넘으면 버린다
SEARCH_TOP_K = 6           # 방해 후보로 검색해 두는 수(정답·겹침 제외 전)
STRICT_ANSWER_OVERLAP = 8  # no_answer: 답변과 이 길이 이상 겹치면 제외(rag_context.used_references와 같은 기준)
LOOSE_ANSWER_OVERLAP = 20  # distract: 상투구가 아니라 내용이 겹치는 길이
UNIT_OVERLAP = 40          # 정답 단위 원문과 이 길이 이상 겹치면(통원↔입원 반복 문장 등) 제외 — 두 종류 공통
# no_answer 추가 관문: 답변의 핵심 명사(상투어 제외)가 방해 발췌에 이 비율 이상 나오면 답이 들어 있을 수 있다고 본다.
# 2026-10-13 측정: 글자 겹침만 거른 답 없음 533건의 핵심 명사 포함률 평균 0.40(정답 포함 샘플은 0.89), 0.6 이상 104건 —
# '진단계약 정의'(용어 정의 조문마다 있음), '고의 상해'(면책 조항마다 있음)처럼 다른 문서에서도 답할 수 있는 질문이었다.
NOUN_COVER_MAX = 0.5
GENERIC_NOUNS = {"보험", "보험금", "계약", "회사", "경우", "지급", "보상", "약관", "특별약관", "계약자", "피보험자", "반려동물",
                 "해당", "사항", "규정", "내용", "포함", "적용", "기간", "이상", "이내"}


def _h(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest(), 16)


def _qa_key(qa: dict) -> tuple:
    return (qa["unit_id"], qa.get("round"), qa.get("row"), qa["question"])


def is_val(uid: str) -> bool:
    return _h(SEED, "val", uid) % 1000 < VAL_RATIO * 1000


def load_final(species: str) -> list[dict]:
    return json.loads(FINAL_FILES[species].read_text(encoding="utf-8"))


# ---------------- 방해 발췌 검색 ----------------
def run_searches(engine, builder, qas_by_species: dict, cache_path: Path = SEARCH_CACHE) -> dict:
    """질문마다 SearchScope.unrestricted로 build_full_context 결과를 저장. 이미 있는 질문은 건너뛴다"""
    from data.rag_context import build_full_context
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = [(sp, qa["question"]) for sp, qas in qas_by_species.items() for qa in qas
            if f"{sp}|{qa['question']}" not in cache]
    todo = list(dict.fromkeys(todo))
    keep = ("section", "section_name", "type", "article_num", "article_title", "coverage_type", "content",
            "paragraph_num", "chunk_index", "context_prefix", "score", "adjusted_score", "reference_contents")
    for n, (sp, q) in enumerate(todo, 1):
        results = build_full_context(engine, builder, q, SearchScope.unrestricted(sp), top_k=SEARCH_TOP_K)
        cache[f"{sp}|{q}"] = [{k: r.get(k) for k in keep} for r in results]
        if n % 200 == 0 or n == len(todo):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"  검색 {n}/{len(todo)}", flush=True)
    return cache


def _shingles(text: str, n: int) -> set[str]:
    f = _flat_cite(text)
    return {f[i:i + n] for i in range(len(f) - n + 1)}


def _shares(a: set[str], text: str, n: int) -> bool:
    """두 글이 (공백·괄호 무시) n자 이상 연속으로 겹치는가 — n자 조각이 하나라도 같으면 정확히 그렇다"""
    return not a.isdisjoint(_shingles(text, n))


_kiwi = None


def answer_nouns(text: str) -> set[str]:
    """답변의 핵심 명사(2자 이상, 상투어 제외) — kiwipiepy"""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return {t.form for t in _kiwi.tokenize(text) if t.tag in ("NNG", "NNP") and len(t.form) >= 2} - GENERIC_NOUNS


def noun_cover(nouns: set[str], text: str) -> float:
    return sum(1 for n in nouns if n in text) / len(nouns) if nouns else 0.0


def pick_distractors(results: list[dict], unit: dict, answer_body: str, strict: bool) -> list[dict]:
    """정답 단위가 아닌 검색 결과 중 방해로 쓸 수 있는 것(검색 순위 순). strict는 no_answer용(모듈 docstring)."""
    own = {graph_key(r) for r in unit["records"]}
    a_len = STRICT_ANSWER_OVERLAP if strict else LOOSE_ANSWER_OVERLAP
    ans_sh, unit_sh = _shingles(answer_body, a_len), _shingles(unit["content"], UNIT_OVERLAP)
    nouns = answer_nouns(answer_body) if strict else set()
    out = []
    for r in results:
        if graph_key(r) in own:
            continue
        # 답 없음: 같은 조(조번호 없는 별표·안내·별첨은 같은 문서 전체)의 다른 청크도 뺀다 — 답이 이어져 있을 수 있다
        if strict and (r.get("section"), r.get("section_name"), r.get("article_num")) == \
                (unit["section"], unit.get("section_name"), unit.get("article_num")):
            continue
        texts = [r["content"]] + ([ref.get("content") or "" for ref in r.get("reference_contents") or []] if strict else [])
        if any(_shares(ans_sh, t, a_len) or _shares(unit_sh, t, UNIT_OVERLAP) for t in texts):
            continue
        if strict and noun_cover(nouns, " ".join(texts)) >= NOUN_COVER_MAX:
            continue
        out.append(r)
    return out


def assign_kinds(entries: list[dict]) -> None:
    """entries[i]["kind"]를 정한다. 목표 비율에 맞추되 자격(방해·엄격 후보 유무)을 지킨다. 해시 순서라 재현된다."""
    n = len(entries)
    want_na, want_d = round(n * TARGET["no_answer"]), round(n * TARGET["distract"])
    order = sorted(range(n), key=lambda i: _h(SEED, "kind", *_qa_key(entries[i]["qa"])))
    for e in entries:
        e["kind"] = "gold_only"
    # no_answer: 방해 후보가 없는 QA(어차피 distract가 안 되는 것)부터
    na_pool = sorted((i for i in order if entries[i]["strict"]), key=lambda i: bool(entries[i]["loose"]))
    for i in na_pool[:want_na]:
        entries[i]["kind"] = "no_answer"
    d = [i for i in order if entries[i]["kind"] == "gold_only" and entries[i]["loose"]]
    for i in d[:want_d]:
        entries[i]["kind"] = "distract"


# ---------------- 샘플 조립 ----------------
class TokenCounter:
    def __init__(self, model_dir: Path = BASE_MODEL_DIR):
        from transformers import AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(model_dir)

    def __call__(self, text: str) -> int:
        return len(self.tok(text, add_special_tokens=False)["input_ids"])

    def chat_len(self, messages: list[dict]) -> int:
        # 텍스트로 렌더링한 뒤 토큰화 — transformers 5의 apply_chat_template(tokenize=True)는 dict를 돌려준다
        return self(self.tok.apply_chat_template(messages, tokenize=False))

    def prompt_len(self, messages: list[dict]) -> int:
        """assistant 답변 앞까지(학습 시 loss를 걸지 않는 부분)"""
        return self(self.tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True))


def build_sample(e: dict, count: TokenCounter) -> tuple[dict | None, str]:
    """(샘플 또는 None, 사유). e = {"qa", "species", "gold", "kind", "loose", "strict"}"""
    qa, kind, gold = e["qa"], e["kind"], e["gold"]
    rng = random.Random(_h(SEED, "rng", *_qa_key(qa)))
    if kind == "no_answer":
        picked = e["strict"][:2]
        nouns = answer_nouns(prompts.strip_citation(qa["answer"]))
        joined = lambda rs: " ".join(r["content"] + " ".join(x.get("content") or "" for x in r.get("reference_contents") or []) for r in rs)
        if len(picked) == 2 and noun_cover(nouns, joined(picked)) >= NOUN_COVER_MAX:
            picked = picked[:1]   # 둘을 합치면 답의 핵심어가 다 모이는 경우 — 하나만 쓴다
        items, target = [prompts.ExcerptItem.from_search_result(r) for r in picked], prompts.NO_ANSWER_TEXT
    elif kind == "distract":
        n = min(len(e["loose"]), rng.choice((1, 2)))
        items = [gold] + [prompts.ExcerptItem.from_search_result(r) for r in e["loose"][:n]]
        rng.shuffle(items)
        target = qa["answer"]
    else:
        items, target = [gold], qa["answer"]
    gold_pos = next((i for i, it in enumerate(items) if it is gold), None)
    protected = frozenset() if gold_pos is None else frozenset({gold_pos})
    # 예산: 전체 MAX_LENGTH에서 템플릿·시스템 프롬프트·답변을 뺀 나머지가 user 메시지 상한
    skeleton = prompts.build_training_messages(qa["question"], target, [])
    fixed = count.chat_len(skeleton) - count(skeleton[1]["content"])
    budget = MAX_LENGTH - fixed - 8
    messages = prompts.build_training_messages(qa["question"], target, items, budget=budget,
                                               count_tokens=count, protected=protected)
    n_tokens = count.chat_len(messages)
    if n_tokens > MAX_LENGTH:
        return None, "too_long"
    user = messages[1]["content"]
    n_items = user.count("[발췌 ")
    meta = {"species": e["species"], "unit_id": qa["unit_id"], "kind": kind, "gold_pos": gold_pos, "n_items": n_items,
            "trimmed": n_items < len(items) or user.count("[참조] ") < sum(len(it.references) for it in items),
            "distractor_keys": [it.key for it in items if it is not gold],
            "round": qa.get("round"), "row": qa.get("row"), "flags": qa.get("flags", []),
            "n_tokens": n_tokens, "n_prompt_tokens": count.prompt_len(messages),
            "prompt_version": prompts.PROMPT_VERSION}
    return {"messages": messages, "meta": meta}, "ok"


def build_all(builder, cache: dict, count: TokenCounter) -> tuple[list, list, dict]:
    stats, entries = Counter(), []
    for species in FINAL_FILES:
        units = {unit_id(u): u for u in make_units(builder.chunks[species])}
        golds = {}
        for qa in load_final(species):
            unit = units.get(qa["unit_id"])
            if unit is None:
                stats["unit_missing"] += 1
                continue
            results = cache.get(f"{species}|{qa['question']}")
            if results is None:
                stats["search_missing"] += 1
                continue
            if qa["unit_id"] not in golds:
                refs = builder.resolve_references(unit, species, source_chunks=unit["records"])
                golds[qa["unit_id"]] = prompts.ExcerptItem.from_unit(unit, refs)
            body = prompts.strip_citation(qa["answer"])
            entries.append({"qa": qa, "species": species, "gold": golds[qa["unit_id"]],
                             "loose": pick_distractors(results, unit, body, strict=False),
                             "strict": pick_distractors(results, unit, body, strict=True)})
    stats["eligible_distract"] = sum(1 for e in entries if e["loose"])
    stats["eligible_no_answer"] = sum(1 for e in entries if e["strict"])
    assign_kinds(entries)
    train, val = [], []
    for e in entries:
        sample, why = build_sample(e, count)
        stats[why] += 1
        if sample is None:
            continue
        stats[f"kind_{sample['meta']['kind']}"] += 1
        stats["trimmed"] += sample["meta"]["trimmed"]
        (val if is_val(e["qa"]["unit_id"]) else train).append(sample)
    return train, val, dict(stats)


def write_jsonl(path: Path, samples: list[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--search-only", action="store_true")
    args = ap.parse_args(argv)
    from data import rag_context
    qas = {sp: load_final(sp) for sp in FINAL_FILES}
    print("최종 QA:", {sp: len(v) for sp, v in qas.items()})
    cache = json.loads(SEARCH_CACHE.read_text(encoding="utf-8")) if SEARCH_CACHE.exists() else {}
    missing = any(f"{sp}|{qa['question']}" not in cache for sp, v in qas.items() for qa in v)
    if missing or args.search_only:
        from data import search_engine   # 검색이 남았을 때만 모델을 올린다(GPU)
        engine = search_engine.SearchEngine()
        builder = rag_context.ContextBuilder(client=engine.client, chunks=engine.chunks)
        cache = run_searches(engine, builder, qas)
        if args.search_only:
            return
    else:
        builder = rag_context.ContextBuilder()
    count = TokenCounter()
    train, val, stats = build_all(builder, cache, count)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT_DIR / "train.jsonl", train)
    write_jsonl(OUT_DIR / "val.jsonl", val)
    stats.update({"train": len(train), "val": len(val),
                  "val_units": len({s["meta"]["unit_id"] for s in val}),
                  "train_units": len({s["meta"]["unit_id"] for s in train}),
                  "unit_overlap": len({s["meta"]["unit_id"] for s in val} & {s["meta"]["unit_id"] for s in train}),
                  "max_length": MAX_LENGTH, "prompt_version": prompts.PROMPT_VERSION, "seed": SEED})
    (OUT_DIR / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
