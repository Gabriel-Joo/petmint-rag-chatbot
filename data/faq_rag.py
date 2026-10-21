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

GEN_RULE = ("\n[학습 데이터 작성 규칙] 첫 문장은 질문에 대한 결론(된다·안 된다·금액·기간)입니다. 발췌에 그 결론을 제한하거나 바꾸는 "
            "조건·예외가 있으면 '다만'으로 시작하는 문장으로 덧붙이세요. 질문과 관계없는 조건은 넣지 마세요. 발췌로 질문에 답할 수 "
            f"없으면 다른 말 없이 다음 문장만 쓰세요: {prompts.NO_ANSWER_TEXT}")

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
    why = []
    if r["refusal"]:
        j = r.get("judge_excerpt") or {}
        if j.get("problem") is None:
            why.append("판정① 파싱 실패")
        elif "wrong_refusal" in j.get("types", []):
            why.append("잘못된 거절")
        return ("no_answer", []) if not why else ("drop", why)
    j1, j2 = r.get("judge_excerpt") or {}, r.get("judge_unit") or {}
    if j1.get("problem") is None:
        why.append("판정① 파싱 실패")
    elif j1["problem"]:
        why.append("판정① " + ",".join(j1.get("types") or ["?"]))
    if set(j2.get("types") or []) & UNIT_TYPES and j2.get("problem"):
        why.append("판정② " + ",".join(sorted(set(j2["types"]) & UNIT_TYPES)))
    if r.get("number_miss"):
        why.append(f"발췌에 없는 숫자 {r['number_miss']}")
    if r.get("calc") and not r["calc"][0]:
        why.append("계산 " + "; ".join(r["calc"][1])[:80])
    return ("answer", []) if not why else ("drop", why)


# ---------- 파일럿 ----------
def pilot(n: int, n_revived: int):
    from app import config
    from data import finetune5 as F5
    assert config.SEARCH_VARIANT and config.DISPLAY_PARENT and config.SEARCH_EXPAND, "B 조건 env(모듈 docstring)"
    rng = random.Random(SEED)
    allq = pool()
    fin = [f for f in allq if f["origin"] != "revived_incomplete"]
    rev = [f for f in allq if f["origin"] == "revived_incomplete"]
    sample = rng.sample(fin, n - n_revived) + rng.sample(rev, n_revived)
    rng.shuffle(sample)
    print(f"풀: final {len(fin)} · 되살림 {len(rev)} → 표본 {len(sample)}", flush=True)

    from pymilvus import MilvusClient
    from app.services import policy_data
    from app.services.answer import SEARCH_TOP_K, display_parent
    from app.services.retrieval import Retriever
    from data import rag_context
    from data.search_scope import SearchScope
    chunks, graphs = policy_data.load()
    builder = rag_context.ContextBuilder(client=MilvusClient(uri=config.MILVUS_URL), chunks=chunks, graphs=graphs)
    retriever = Retriever(config.SEARCH_SERVICE_URL, expand=True, variant=config.SEARCH_VARIANT, pool_k=config.SEARCH_POOL,
                          expand_dict=config.SEARCH_EXPAND_DICT)
    idx = RW.UnitIndex(list(SPECIES))
    RW.set_model(GEN_MODEL)
    OUT.mkdir(parents=True, exist_ok=True)
    recs, t = [], {"rewrite": 0.0, "search": 0.0, "gen": 0.0, "judge": 0.0}

    # 1·2·3 — qwen3 + search-service
    for k, f in enumerate(sample, 1):
        unit, refs, source = idx.get(f["species"], f["unit_id"])
        r = {"key": RW.record_key(f), "origin": f["origin"], "species": f["species"], "unit_id": f["unit_id"],
             "section_name": f.get("section_name"), "article_num": f.get("article_num"), "coverage_type": f.get("coverage_type"),
             "question_05": f["question"],
             "answer_05": f["answer"], "flags": f.get("flags", [])}
        q = f["question"]
        t0 = time.time()
        if synonyms.rewrite_hints(q) and unit is not None:
            rq = rewrite5.rewrite_question(f, unit, refs, source)
            r["rewrite"] = {"status": rq["status"], "hints": rq["hints"], "why": [a["why"] for a in rq["attempts"]]}
            q = rq["question"] or q
        t["rewrite"] += time.time() - t0
        t0 = time.time()
        res = display_parent(rag_context.build_full_context(retriever, builder, q, SearchScope.unrestricted(f["species"]),
                                                            SEARCH_TOP_K), builder, f["species"])
        items = F5.serving_items(q, res)
        messages = prompts.build_messages(q, items)
        t["search"] += time.time() - t0
        t0 = time.time()
        ans = generate_answer(messages)
        t["gen"] += time.time() - t0
        r.update(question=q, excerpts=[it.label for it in items], gold_rank=F5.gold_rank(res, unit) if unit else None,
                 user_content=messages[1]["content"], answer=ans, refusal=is_refusal(ans), unit_source=source,
                 unit_refs=refs)
        recs.append(r)
        print(f"[{k}/{len(sample)}] gold={r['gold_rank']} 거절={r['refusal']} {q[:40]}", flush=True)

    # 4·5 — gemma4 판정, 코드 검사
    for r in recs:
        t0 = time.time()
        r["judge_excerpt"] = judge_excerpt(r["user_content"], r["answer"])
        if not r["refusal"]:
            qa = {"species": r["species"], "section_name": r["section_name"], "article_title": None, "question": r["question"],
                  "answer": r["answer"], "section": None}
            r["judge_unit"] = faq_judge.judge(faq_judge.build_judge_prompt(qa, r["unit_source"] or "", r["unit_refs"] or [], r["answer"]))
            r["number_miss"] = number_problems(r["answer"], r["user_content"] + " " + r["question"])
            cv = V.verify_all({"question": r["question"], "answer": r["answer"]}, r["coverage_type"], r["section_name"])
            r["calc"] = list(cv) if cv is not None else None
        t["judge"] += time.time() - t0
        r["label"], r["why"] = decide(r)
    for r in recs:
        r.pop("unit_source", None)
        r.pop("unit_refs", None)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    (OUT / f"pilot_{ts}.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    report(recs, t, ts)


def report(recs: list[dict], t: dict, ts: str):
    n = len(recs)
    by = Counter((r["origin"], r["label"]) for r in recs)
    L = [f"# C 파일럿 — 답을 서빙 발췌로 다시 만들기 ({ts})", "",
         f"표본 {n}건: final {sum(r['origin'] != 'revived_incomplete' for r in recs)} · 되살린 incomplete "
         f"{sum(r['origin'] == 'revived_incomplete' for r in recs)}. 생성 {GEN_MODEL}, 판정 {faq_judge.JUDGE_MODEL}.", "",
         "## 요약", "", "| 출처 | answer | no_answer | drop |", "|---|---|---|---|"]
    for o in ("final", "repaired", "revived_incomplete"):
        if any(r["origin"] == o for r in recs):
            L.append(f"| {o} | {by[(o, 'answer')]} | {by[(o, 'no_answer')]} | {by[(o, 'drop')]} |")
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
    ap.add_argument("cmd", choices=["pilot", "count"])
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--revived", type=int, default=30)
    a = ap.parse_args()
    if a.cmd == "count":
        p = pool()
        print(Counter(f["origin"] for f in p), "힌트 대상", sum(bool(synonyms.rewrite_hints(f["question"])) for f in p))
        return
    pilot(a.n, a.revived)


if __name__ == "__main__":
    main()
