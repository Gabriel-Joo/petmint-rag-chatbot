"""
faq_rag.py
C 작업(2026-10-22) — 학습 QA의 답을 서빙과 같은 검색 발췌로 다시 만든다. 설정 원본: data/review/rebuild5_stage7_config.md,
흐름도: https://claude.ai/artifact/7MFBbn5B216urdzjs52QwW

05·06과의 관계: 05의 질문과 재작성(말투·등급 어구), 06의 결정적 검사·질문 품질 판정은 그대로 쓴다. 05의 답과 06의 답 심판만 대신한다.
- 06 심판은 원문 단위 전체와 비교해 incomplete로 4,769건을 버렸다(답이 2~4문장이라 단위를 다 담을 수 없었다). 그 질문도 되살려 쓴다
- 학습 발췌 = 서빙 발췌: data.finetune5의 serving 경로(v3 조각 → v1 부모 표시, 질의 확장, 1차 후보 20, 상위 3, 참조, 예산)

한 QA의 흐름
1. 질문 확정 — 약관 말이 있으면 동의어 사전 힌트로 다시 쓴다(data.rewrite5.rewrite_question, 06 검사·반려동물 주어 검사 포함)
2. 서빙 B 검색 → 발췌(서버와 같은 user 메시지)
3. 답 생성(qwen3:14b, think 끔) — 발췌만 보고, "결론 + 단서". 발췌에 답이 없으면 prompts.NO_ANSWER_TEXT 그대로
4. 판정 ① 발췌 기준(gemma4:12b, EXCERPT_JUDGE) — 근거 없음·값·뒤집힘·조항 섞임·단서 누락·잘못된 거절
   판정 ② 원문 단위 기준(06 faq_judge 그대로) — 뒤집힘·값·용어만 센다(incomplete·fabricated는 단위 밖 발췌를 쓴 답에 오탐이라 보지 않는다)
5. 코드 검사 — 답의 숫자가 발췌·질문에 있는지, 계산형이면 verify_all(별표3이 틀리면 코드 값으로)
라벨: answer(문제 없음) / no_answer(거절 + 판정 ①이 잘못된 거절이 아니라고 봄) / drop(사유)

GPU 모델을 번갈아 올리지 않게 단계별로 돈다: 1·2·3(qwen3 + search-service) 전부 → 4(gemma4) 전부.

  PETMINT_CHUNKS_DIR=data/chunks/v3 PETMINT_GRAPH_DIR=data/graph/v3 PETMINT_SEARCH_VARIANT=v3 PETMINT_SEARCH_EXPAND=1 \
  PETMINT_DISPLAY_PARENT=1 python -m data.faq_rag pilot [--n 100 --revived 30]
"""

import argparse
import json
import random
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from data import faq_checks, faq_judge, faq_rewrite as RW, faq_verify as V, prompts, synonyms
from data import rewrite5

SRC = Path("data/faq/rebuild4/rw/checked")
OUT = Path("data/faq/rag")
SPECIES = ("강아지", "고양이")
GEN_MODEL = "qwen3:14b"
SEED = 20261022
OLLAMA = "http://localhost:11434"

# 2026-10-22 파일럿 1차: "단서가 있으면 '다만'으로 덧붙여라"는 규칙에 새 답 93%가 '다만'을 쓰고 drop 64 중 62가 그 문장에서 틀렸다
# (단서를 지어내거나 넓힘). 사용자 결정: 강제하지 않는다 — 발췌에 단서가 적혀 있으면 옮기고, 없으면 쓰지 않는다
GEN_RULE = ("\n[학습 데이터 작성 규칙] 첫 문장은 질문에 대한 결론(된다·안 된다·금액·기간)입니다. 발췌에 이 질문의 결론을 제한하는 "
            "단서·예외가 문장으로 적혀 있으면 그 내용을 그대로 옮겨 덧붙이고, 적혀 있지 않으면 덧붙이지 마세요. 발췌에 없는 조건·예외를 "
            "만들거나 넓히지 마세요. 발췌로 질문에 답할 수 없으면 다른 말 없이 다음 문장만 쓰세요: " + prompts.NO_ANSWER_TEXT)

EXCERPT_JUDGE = """당신은 반려동물 보험 상담 답변의 검수자입니다. [약관 발췌]만 근거로, [질문]에 대한 [답변]에 상담에 쓰면 안 되는 문제가 있는지 판정하세요.
발췌 밖의 지식은 쓰지 않습니다. 발췌가 여러 개이면 질문과 관련된 발췌를 기준으로 봅니다.
문제 유형:
- unsupported: 발췌에 없는 규정·숫자·조건·상황을 답에 씀(비슷한 다른 조항을 질문의 답처럼 쓴 것 포함)
- wrong_value: 금액·기간·비율·계산이 발췌와 다름
- reversal: 발췌의 결론을 뒤집음(지급↔미지급, 포함↔제외, 가능↔불가)
- clause_mix: 질문과 관계없는 다른 조항·예외를 질문에 잘못 적용함
- missing_condition: 발췌에 질문의 결론을 바꾸는 단서·예외가 있는데 답에서 빠짐
- wrong_refusal: 발췌에 질문의 답이 있는데 '확인되지 않는다'고 답함
표현 차이나 사소한 생략은 문제가 아닙니다. 발췌에 답이 없어 '확인되지 않는다'고 한 답은 문제가 아닙니다.
반드시 JSON 한 개로만 답하세요: {"problem": true 또는 false, "types": ["유형", ...], "reason": "한 문장"}"""
UNIT_TYPES = {"reversal", "wrong_value", "wrong_term"}


# ---------- 입력 ----------
def revived(sp: str) -> list[dict]:
    """06에서 심판 incomplete 하나만으로 버려진 QA(결정적 검사는 통과) — 질문은 문제가 없었다"""
    out = []
    for f in json.loads((SRC / f"petmint_{sp}_faq_checked_all.json").read_text(encoding="utf-8")):
        drops = [c for c in f["checks"] if c.get("action") == "drop"]
        if f.get("decision") != "drop" or {c["check"] for c in drops} != {"judge"}:
            continue
        if set(re.findall(r"'(\w+)'", drops[0]["detail"].split("]")[0])) == {"incomplete"}:
            out.append({k: v for k, v in f.items() if k not in ("checks", "decision")} | {"origin": "revived_incomplete"})
    return out


def pool() -> list[dict]:
    final = {sp: json.loads((SRC / f"petmint_{sp}_faq_final.json").read_text(encoding="utf-8")) for sp in SPECIES}
    rewrite5.repair_calc(final)                       # 별표3 계산 오류 → 코드 값(final 2건 고침, 버려진 3건 되살림)
    out = [f | {"origin": f.get("origin") or ("repaired" if f.get("repair") else "final")} for sp in SPECIES for f in final[sp]]
    return out + [f for sp in SPECIES for f in revived(sp)]


# ---------- 검색 범위 ----------
def scope_for_qa(f: dict):
    """등급이 있는 단위(의료비 특약 한도 조항)의 QA는 그 특약·등급에 가입한 고객처럼 범위를 좁힌다 — 서빙은 고객 가입 등급 하나로
    좁힌다. 파일럿 2차: 등급 없는 질문에 발췌 셋이 등급별 한도를 줘 모델이 한 등급 숫자를 일반 답처럼 썼다(drop 48 중 23이 등급 단위).
    나머지는 고객 없는 일반 질문(unrestricted)"""
    from data.search_scope import MEDICAL_SECTIONS, SearchScope, Subscription
    sp = f["species"]
    if f.get("coverage_type") and f.get("section_name") in MEDICAL_SECTIONS[sp]:
        return SearchScope(sp, (Subscription(f["section_name"], f["coverage_type"]),), frozenset())
    return SearchScope.unrestricted(sp)


def fix_format(a: str) -> str:
    """답을 쓰고 끝에 거절 문장을 붙인 형식 오류(파일럿 2차 잘못된 거절 2/2) — 답이 있으면 거절 문장을 뗀다"""
    if prompts.NO_ANSWER_TEXT in a and len(a.replace(prompts.NO_ANSWER_TEXT, "").strip()) > 20:
        return a.replace(prompts.NO_ANSWER_TEXT, "").strip()
    return a


# ---------- 생성 ----------
def chat(model: str, messages: list[dict], num_predict: int = 400, fmt: str | None = None) -> str:
    body = {"model": model, "messages": messages, "stream": False, "think": False,
            "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": num_predict}} | ({"format": fmt} if fmt else {})
    r = requests.post(f"{OLLAMA}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def generate_answer(messages: list[dict]) -> str:
    msgs = [{"role": "system", "content": messages[0]["content"] + GEN_RULE}] + messages[1:]
    return re.sub(r"\s*근거\s*:.*$", "", chat(GEN_MODEL, msgs), flags=re.S).strip()


def is_refusal(a: str) -> bool:
    return prompts.NO_ANSWER_TEXT[:15] in a or bool(re.search(r"확인되지 않", a)) and len(a) < 90


# ---------- 판정·검사 ----------
def judge_excerpt(user_content: str, answer: str) -> dict:
    prompt = f"{user_content}\n\n[답변]\n{answer}"
    body = {"model": faq_judge.JUDGE_MODEL, "system": EXCERPT_JUDGE, "prompt": prompt, "stream": False, "format": "json",
            "think": False, "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 400}}
    r = requests.post(f"{OLLAMA}/api/generate", json=body, timeout=900)
    r.raise_for_status()
    try:
        j = json.loads(re.search(r"\{.*\}", r.json().get("response", ""), re.S).group(0))
        return {"problem": bool(j.get("problem")), "types": j.get("types") or [], "reason": j.get("reason")}
    except Exception:
        return {"problem": None, "types": [], "reason": None}


def number_problems(answer: str, user_content: str) -> list[str]:
    miss = faq_checks.numbers(answer) - faq_checks.numbers(user_content)
    return sorted(miss)


def decide(r: dict) -> tuple[str, list[str]]:
    """판정 정책(2026-10-22 사용자 확정, drop 20건 판독 — 오탐 25%):
    unsupported·reversal·wrong_value(① 또는 ②)·잘못된 거절·발췌에 없는 숫자·계산 오류 → drop
    ①의 clause_mix·missing_condition만 걸림(② 문제 없음) → answer_warn(오탐 2/5·3/6 — 경고만, final만 학습에 넣는다)"""
    why = []
    j1, j2 = r.get("judge_excerpt") or {}, r.get("judge_unit") or {}
    if r["refusal"]:
        if j1.get("problem") is None:
            why.append("판정① 파싱 실패")
        elif "wrong_refusal" in j1.get("types", []):
            why.append("잘못된 거절")
        return ("no_answer", []) if not why else ("drop", why)
    t1 = set(j1.get("types") or []) if j1.get("problem") else set()
    t2 = set(j2.get("types") or []) & UNIT_TYPES if j2.get("problem") else set()
    if j1.get("problem") is None:
        why.append("판정① 파싱 실패")
    if t1 & {"unsupported", "reversal", "wrong_value", "wrong_refusal"}:
        why.append("판정① " + ",".join(sorted(t1)))
    if t2:
        why.append("판정② " + ",".join(sorted(t2)))
    if r.get("number_miss"):
        why.append(f"발췌에 없는 숫자 {r['number_miss']}")
    if r.get("calc") and not r["calc"][0]:
        why.append("계산 " + "; ".join(r["calc"][1])[:80])
    if why:
        return "drop", why
    if t1 & {"clause_mix", "missing_condition"}:
        return "answer_warn", ["경고 " + ",".join(sorted(t1))]
    return "answer", []


# ---------- 파일럿 ----------
class Ctx:
    """검색·단위 복원 도구(서빙 B 경로). 스레드 여럿이 같이 쓴다 — 단위 복원(idx)만 잠근다"""
    def __init__(self):
        import threading
        from pymilvus import MilvusClient
        from app import config
        from app.services import policy_data
        from app.services.retrieval import Retriever
        from data import rag_context
        assert config.SEARCH_VARIANT and config.DISPLAY_PARENT and config.SEARCH_EXPAND, "B 조건 env(모듈 docstring)"
        chunks, graphs = policy_data.load()
        self.rag_context = rag_context
        self.builder = rag_context.ContextBuilder(client=MilvusClient(uri=config.MILVUS_URL), chunks=chunks, graphs=graphs)
        self.retriever = Retriever(config.SEARCH_SERVICE_URL, expand=True, variant=config.SEARCH_VARIANT, pool_k=config.SEARCH_POOL,
                                   expand_dict=config.SEARCH_EXPAND_DICT)
        self.idx = RW.UnitIndex(list(SPECIES))
        self.lock = threading.Lock()
        RW.set_model(GEN_MODEL)

    def unit(self, sp: str, uid: str):
        with self.lock:
            return self.idx.get(sp, uid)


def gen_one(f: dict, ctx: Ctx, t: dict | None = None) -> dict:
    """1·2·3 — 질문 확정 → 서빙 B 검색 → 답 생성(qwen3)"""
    from app.services.answer import SEARCH_TOP_K, display_parent
    from data import finetune5 as F5
    t = t if t is not None else {"rewrite": 0.0, "search": 0.0, "gen": 0.0}
    unit, refs, source = ctx.unit(f["species"], f["unit_id"])
    r = {"key": RW.record_key(f), "origin": f["origin"], "species": f["species"], "unit_id": f["unit_id"],
         "section_name": f.get("section_name"), "article_num": f.get("article_num"), "coverage_type": f.get("coverage_type"),
         "question_05": f["question"], "answer_05": f["answer"], "flags": f.get("flags", []), "repair": f.get("repair")}
    q = f["question"]
    t0 = time.time()
    if synonyms.rewrite_hints(q) and unit is not None:
        rq = rewrite5.rewrite_question(f, unit, refs, source)
        r["rewrite"] = {"status": rq["status"], "hints": rq["hints"], "why": [a["why"] for a in rq["attempts"]]}
        q = rq["question"] or q
    t["rewrite"] += time.time() - t0
    t0 = time.time()
    res = display_parent(ctx.rag_context.build_full_context(ctx.retriever, ctx.builder, q, scope_for_qa(f), SEARCH_TOP_K),
                         ctx.builder, f["species"])
    items = F5.serving_items(q, res)
    messages = prompts.build_messages(q, items)
    t["search"] += time.time() - t0
    t0 = time.time()
    ans = fix_format(generate_answer(messages))
    t["gen"] += time.time() - t0
    r.update(question=q, excerpts=[it.label for it in items], n_items=len(items),
             gold_rank=F5.gold_rank(res, unit) if unit else None, user_content=messages[1]["content"], answer=ans,
             refusal=is_refusal(ans))
    return r


def judge_one(r: dict, ctx: Ctx) -> dict:
    """4·5 — 판정 ①(발췌) ②(원문 단위, 06 그대로) · 숫자 · 계산 → 라벨"""
    _, refs, source = ctx.unit(r["species"], r["unit_id"])
    r["judge_excerpt"] = judge_excerpt(r["user_content"], r["answer"])
    if not r["refusal"]:
        qa = {"species": r["species"], "section_name": r["section_name"], "article_title": None, "question": r["question"],
              "answer": r["answer"], "section": None}
        r["judge_unit"] = faq_judge.judge(faq_judge.build_judge_prompt(qa, source or "", refs or [], r["answer"]))
        r["number_miss"] = number_problems(r["answer"], r["user_content"] + " " + r["question"])
        cv = V.verify_all({"question": r["question"], "answer": r["answer"]}, r["coverage_type"], r["section_name"])
        r["calc"] = list(cv) if cv is not None else None
    r["label"], r["why"] = decide(r)
    return r


def pilot(n: int, n_revived: int):
    rng = random.Random(SEED)
    allq = pool()
    fin = [f for f in allq if f["origin"] != "revived_incomplete"]
    rev = [f for f in allq if f["origin"] == "revived_incomplete"]
    sample = rng.sample(fin, n - n_revived) + rng.sample(rev, n_revived)
    rng.shuffle(sample)
    print(f"풀: final {len(fin)} · 되살림 {len(rev)} → 표본 {len(sample)}", flush=True)
    ctx = Ctx()
    OUT.mkdir(parents=True, exist_ok=True)
    t = {"rewrite": 0.0, "search": 0.0, "gen": 0.0, "judge": 0.0}
    recs = []
    for k, f in enumerate(sample, 1):
        recs.append(gen_one(f, ctx, t))
        print(f"[{k}/{len(sample)}] gold={recs[-1]['gold_rank']} 거절={recs[-1]['refusal']} {recs[-1]['question'][:40]}", flush=True)
    for r in recs:
        t0 = time.time()
        judge_one(r, ctx)
        t["judge"] += time.time() - t0
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    (OUT / f"pilot_{ts}.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    report(recs, t, ts)


# ---------- 전량 ----------
FULL_GEN = OUT / "full_gen.jsonl"
FULL_JUDGED = OUT / "full_judged.jsonl"


def _done_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(l)["key"] + "|" + json.loads(l)["question_05"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def _run_parallel(fn, items: list, out: Path, workers: int, label: str):
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    lock, t0, n = threading.Lock(), time.time(), 0
    with ThreadPoolExecutor(workers) as ex, open(out, "a", encoding="utf-8") as fh:
        futs = [ex.submit(fn, x) for x in items]
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception as e:                       # 한 건 실패로 전체를 멈추지 않는다 — 실패는 다시 돌리면 이어서 한다
                print(f"{label} 실패: {e!r}", flush=True)
                continue
            with lock:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush()
                n += 1
                if n % 100 == 0:
                    el = time.time() - t0
                    print(f"{label} {n}/{len(items)} {el / 60:.0f}분 · 남은 {el / n * (len(items) - n) / 60:.0f}분", flush=True)


def full(workers: int):
    """final 전량(되살린 incomplete는 뺀다 — 2026-10-22 사용자 결정). 재개 가능: 끝난 건은 건너뛴다.
    1단계 qwen3 생성 전부 → 2단계 gemma4 판정 전부(모델을 번갈아 올리지 않게)"""
    OUT.mkdir(parents=True, exist_ok=True)
    qs = [f for f in pool() if f["origin"] != "revived_incomplete"]
    ctx = Ctx()
    done = _done_keys(FULL_GEN)
    todo = [f for f in qs if RW.record_key(f) + "|" + f["question"] not in done]
    print(f"생성: 전체 {len(qs)} · 남은 {len(todo)} · 동시 {workers}", flush=True)
    _run_parallel(lambda f: gen_one(f, ctx), todo, FULL_GEN, workers, "생성")
    unload(GEN_MODEL)
    gen = [json.loads(l) for l in FULL_GEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    jd = _done_keys(FULL_JUDGED)
    todo = [r for r in gen if r["key"] + "|" + r["question_05"] not in jd]
    print(f"판정: 전체 {len(gen)} · 남은 {len(todo)}", flush=True)
    _run_parallel(lambda r: judge_one(r, ctx), todo, FULL_JUDGED, workers, "판정")
    unload(faq_judge.JUDGE_MODEL)
    recs = [json.loads(l) for l in FULL_JUDGED.read_text(encoding="utf-8").splitlines() if l.strip()]
    c = Counter(r["label"] for r in recs)
    print("라벨:", dict(c), flush=True)


def unload(model: str):
    try:
        requests.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)
    except requests.RequestException:
        pass


# ---------- 학습 샘플 ----------
NO_ANSWER_CAP = 0.10       # 거절 샘플 비율 상한(사용자 결정 2: 상한을 둔다 — 파일럿 거절 2~3%라 걸리지 않을 것)


def build(out_dir: Path):
    """C 판정 결과 → train/val.jsonl(07 형식). 프롬프트는 서빙과 같은 system + C가 본 user 메시지 그대로, 목표는 C의 답.
    answer · answer_warn(final만 — 되살린 것은 이미 뺐다) · no_answer(상한 NO_ANSWER_CAP). 정답 끼워넣기 없음(사용자 결정 3)"""
    from data.finetune_data import MAX_LENGTH, TokenCounter, is_val, write_jsonl
    recs = [json.loads(l) for l in FULL_JUDGED.read_text(encoding="utf-8").splitlines() if l.strip()]
    keep = [r for r in recs if r["label"] in ("answer", "answer_warn")]
    na = [r for r in recs if r["label"] == "no_answer"]
    cap = int(NO_ANSWER_CAP * (len(keep) + len(na)))
    if len(na) > cap:
        na = random.Random(SEED).sample(na, cap)
    count = TokenCounter()
    st, train, val = Counter(), [], []
    for r in keep + na:
        target = prompts.NO_ANSWER_TEXT if r["label"] == "no_answer" else prompts.strip_citation(r["answer"])
        messages = [{"role": "system", "content": prompts.SYSTEM_PROMPT}, {"role": "user", "content": r["user_content"]},
                    {"role": "assistant", "content": target}]
        n_tok = count.chat_len(messages)
        if n_tok > MAX_LENGTH:
            st["too_long"] += 1
            continue
        meta = {"species": r["species"], "unit_id": r["unit_id"], "kind": r["label"], "n_items": r.get("n_items"),
                "gold_pos": (r["gold_rank"] - 1) if r.get("gold_rank") else None, "gold_rank": r.get("gold_rank"),
                "why": r.get("why"), "flags": r.get("flags"), "origin": r["origin"], "question_05": r["question_05"],
                "n_tokens": n_tok, "prompt_version": prompts.PROMPT_VERSION}
        (val if is_val(r["unit_id"]) else train).append({"messages": messages, "meta": meta})
    random.Random(SEED).shuffle(train)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "val.jsonl", val)
    allr = train + val
    stats = {**st, "train": len(train), "val": len(val), "labels_all": dict(Counter(r["label"] for r in recs)),
             "kinds": dict(Counter(s["meta"]["kind"] for s in allr)),
             "no_answer_pct": round(100 * sum(s["meta"]["kind"] == "no_answer" for s in allr) / max(1, len(allr)), 1),
             "gold_in_excerpts_pct": round(100 * sum(bool(s["meta"]["gold_rank"]) for s in allr) / max(1, len(allr)), 1),
             "train_units": len({s["meta"]["unit_id"] for s in train}), "val_units": len({s["meta"]["unit_id"] for s in val}),
             "unit_overlap": len({s["meta"]["unit_id"] for s in train} & {s["meta"]["unit_id"] for s in val}),
             "max_length": MAX_LENGTH, "prompt_version": prompts.PROMPT_VERSION, "source": str(FULL_JUDGED),
             "no_answer_cap": NO_ANSWER_CAP}
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


def report(recs: list[dict], t: dict, ts: str):
    n = len(recs)
    by = Counter((r["origin"], r["label"]) for r in recs)
    L = [f"# C 파일럿 — 답을 서빙 발췌로 다시 만들기 ({ts})", "",
         f"표본 {n}건: final {sum(r['origin'] != 'revived_incomplete' for r in recs)} · 되살린 incomplete "
         f"{sum(r['origin'] == 'revived_incomplete' for r in recs)}. 생성 {GEN_MODEL}, 판정 {faq_judge.JUDGE_MODEL}.", "",
         "## 요약", "", "| 출처 | answer | answer_warn | no_answer | drop |", "|---|---|---|---|---|"]
    for o in ("final", "repaired", "revived_incomplete"):
        if any(r["origin"] == o for r in recs):
            L.append(f"| {o} | {by[(o, 'answer')]} | {by[(o, 'answer_warn')]} | {by[(o, 'no_answer')]} | {by[(o, 'drop')]} |")
    gold = Counter("있음" if r["gold_rank"] else "없음" for r in recs)
    L += ["", f"- 정답 단위가 서빙 발췌에 있음 {gold['있음']} / 없음 {gold['없음']}",
          f"- 정답이 없는데 답함(answer) {sum(1 for r in recs if not r['gold_rank'] and r['label'] == 'answer')}, "
          f"정답이 있는데 거절 {sum(1 for r in recs if r['gold_rank'] and r['refusal'])}",
          "- drop 사유: " + ", ".join(f"{k} {v}" for k, v in Counter(w.split()[0] + ' ' + (w.split()[1] if len(w.split()) > 1 else '')
                                                                    for r in recs for w in r["why"]).most_common()),
          f"- 시간(초, {n}건 합): " + ", ".join(f"{k} {v:.0f}" for k, v in t.items())
          + f" → 건당 {sum(t.values()) / n:.1f}초", "", "## 전체 (판정·사람 검수용)", ""]
    for i, r in enumerate(recs, 1):
        L += [f"### {i}. [{r['label']}] {r['origin']} · {r['species']} · {r['unit_id']}", "",
              f"- 질문: {r['question']}" + (f"  \n  (05: {r['question_05']})" if r["question"] != r["question_05"] else ""),
              f"- 발췌: {' / '.join(r['excerpts'])} · 정답 단위 순위 {r['gold_rank']}",
              f"- 05 답: {faq_checks.answer_body(r['answer_05'])}", f"- **새 답**: {r['answer']}",
              f"- 판정①: {r['judge_excerpt'].get('problem')} {r['judge_excerpt'].get('types')} — {r['judge_excerpt'].get('reason')}"]
        if r.get("judge_unit"):
            L.append(f"- 판정②: {r['judge_unit'].get('problem')} {r['judge_unit'].get('types')} — {r['judge_unit'].get('reason')}")
        if r["why"]:
            L.append(f"- drop 사유: {'; '.join(r['why'])}")
        L.append("")
    path = Path("data/review") / f"faq_rag_pilot_{ts}.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("리포트:", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pilot", "count", "full", "build"])
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out-dir", default="data/finetune/rebuild5")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--revived", type=int, default=30)
    a = ap.parse_args()
    if a.cmd == "count":
        p = pool()
        print(Counter(f["origin"] for f in p), "힌트 대상", sum(bool(synonyms.rewrite_hints(f["question"])) for f in p))
        return
    if a.cmd == "full":
        full(a.workers)
    elif a.cmd == "build":
        build(Path(a.out_dir))
    else:
        pilot(a.n, a.revived)


if __name__ == "__main__":
    main()
