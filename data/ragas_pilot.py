"""
ragas_pilot.py
08 Ragas 파일럿 — 로컬 심판(gemma4:12b, Ollama)이 한국어 답변·약관 발췌로 faithfulness를 제대로 매기는지 10문항으로 본다(docs/08_ragas_eval.md 6절).
안 되면 08 설계(평가자 모델)가 바뀐다 — 본 평가보다 먼저 돌린다.

두 단계, 두 환경:
  1) prepare — llm_env(리포 모듈·Milvus 필요, GPU 안 씀). 문항 10개의 발췌를 answer_eval.gold_item으로 다시 만들고(평가 때와 같은 발췌),
     답변 세 가지를 붙여 data/eval/ragas_pilot_set.json으로 쓴다
       grounded_ft   rebuild2 평가의 FT 답(근거 문구 반영, 짧다)
       grounded_base 같은 문항의 베이스 답(근거 반영, 길고 문장이 많다 — 문장 분해를 보기 좋다)
       fabricated    발췌와 어긋나게 손으로 쓴 답(명백히 지어낸 것 — 점수가 낮아야 한다)
     python -m data.ragas_pilot prepare
  2) score — ~/ragas_env(ragas 0.4.3, data/eval/requirements-ragas.txt). 이 단계는 리포 모듈을 import하지 않는다
     ~/ragas_env/bin/python -m data.ragas_pilot score [--repeats 3] [--ollama http://localhost:11434] [--model gemma4:12b]
     → data/review/ragas_pilot_<시각>.json + 화면 요약

보는 것(score 출력):
  - 문장 분해: 답변마다 심판이 나눈 문장 목록(사람이 한국어로 제대로 나눴는지 본다)
  - 구분: grounded 두 종류의 평균·최솟값 vs fabricated 평균·최댓값 — 겹치지 않아야 쓸 수 있다
  - 속도: 호출(분해·검증)마다 초, 프롬프트 토큰 수(num_ctx를 넘으면 Ollama가 앞을 잘라 판정이 망가진다 — 표시)
  - 흔들림: 같은 입력을 --repeats번 — 점수의 최소·최대, 분해 문장 수가 바뀌는가
Ragas Faithfulness의 두 단계(_create_statements, _create_verdicts)를 직접 불러 중간 결과를 남긴다 — 점수 계산은 Ragas와 같다.
"""

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SET_PATH = ROOT / "data" / "eval" / "ragas_pilot_set.json"
OUT_DIR = ROOT / "data" / "review"
SOURCE_EVAL = ROOT / "data" / "eval" / "results" / "answer_eval_20261016_0440_rag-1_7192건_rebuild2.json"
NUM_CTX = 8192                    # data/faq_judge.py와 같다 — Ollama 기본 문맥보다 길게(발췌가 길다)

# 문항 — answerable이고 FT·베이스 답이 둘 다 근거 문구를 담은 것 중 범주가 겹치지 않게(2026-10-18 고름)
# fabricated: 발췌와 어긋나는 사실을 일부러 넣은 답. 숫자·범위·예외를 뒤집었다
PILOT = {
    "R005": "네, 해지된 계약은 해지일로부터 10년 이내라면 언제든 별도 심사 없이 부활시킬 수 있고, 밀린 보험료는 내지 않아도 됩니다.",
    "R010": "강아지는 나이 제한 없이 가입할 수 있습니다. 다만 15살이 넘으면 보험료가 두 배가 됩니다.",
    "R018": "개 물림 사고는 어떤 경우든 전액 보상되며, 보험이 보상하지 않는 경우는 없습니다.",
    "R020": "중성화 수술은 수술비 보장 대상이며 1회당 최대 50만원까지 지급됩니다.",
    "R027": "실속형 Ⅱ 통원은 하루 한도가 50만원이고 자기부담금은 없습니다.",
    "R030": "법률비용 보장은 1심 소송만 해당하고 항소심과 상고심은 보장하지 않습니다.",
    "R037": "대리 청구인은 지정할 수 없고, 반드시 계약자 본인이 동물병원에 직접 방문해 청구해야 합니다.",
    "R042": "'영구적'은 6개월 이상 치료가 필요한 상태를 말하며, 회복 가능성과는 관계없습니다.",
    "R052": "자녀가 남에게 피해를 주면 나이와 관계없이 아이 본인이 전액 배상해야 하고 부모는 책임이 없습니다.",
    "R059": "실속형은 청약 철회가 불가능하며, 가입 후 1년이 지나야 해지할 수 있습니다.",
}
VARIANTS = ("grounded_ft", "grounded_base", "fabricated")


def context_text(block: dict) -> str:
    """발췌 블록 하나 → Ragas retrieved_contexts 한 줄(프롬프트에 보인 라벨·본문·참조 그대로)"""
    lines = [block["label"], block["content"]]
    for r in block["references"]:
        lines += [f"[참조] {r['label']}", r["content"]]
    return "\n".join(lines)


# ----- 1) prepare (llm_env) -----

def prepare() -> None:
    from pymilvus import MilvusClient
    from data import prompts, search_regression as R
    from data.answer_eval import contexts_of, gold_item
    from data.rag_context import ContextBuilder
    builder = ContextBuilder(client=MilvusClient(uri="http://localhost:19530"))
    cases = {c["id"]: c for c in R.load_cases()}
    ev = {r["id"]: r for r in json.loads(SOURCE_EVAL.read_text(encoding="utf-8"))["rows"]}
    items = []
    for qid, fabricated in PILOT.items():
        case, row = cases[qid], ev[qid]
        item, evidence, _ = gold_item(case, builder)
        blocks = contexts_of(prompts.build_messages(row["question"], [item]))   # 평가 때 모델이 본 블록 그대로
        assert isinstance(blocks, list) and blocks, f"{qid}: 발췌를 블록으로 되돌리지 못함"
        items.append({"id": qid, "category": row["category"], "question": row["question"], "evidence": evidence,
                      "contexts": [context_text(b) for b in blocks],
                      "answers": {"grounded_ft": row["ft"], "grounded_base": row["base"], "fabricated": fabricated}})
    SET_PATH.write_text(json.dumps({"source": str(SOURCE_EVAL.relative_to(ROOT)), "created": datetime.now().isoformat(timespec="seconds"),
                                    "items": items}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"파일럿 세트 {len(items)}문항 × 답변 {len(VARIANTS)}종 → {SET_PATH}")


# ----- 2) score (~/ragas_env) -----

class CallTimer:
    """LangChain 콜백 — LLM 호출마다 걸린 시간과 Ollama가 돌려준 토큰 수(prompt_eval_count·eval_count)"""
    def __init__(self):
        from langchain_core.callbacks import BaseCallbackHandler

        timer = self

        class _H(BaseCallbackHandler):
            def on_chat_model_start(self, serialized, messages, **kw):
                timer._t0 = time.monotonic()

            def on_llm_start(self, serialized, prompts, **kw):
                timer._t0 = time.monotonic()

            def on_llm_end(self, response, **kw):
                meta = {}
                try:
                    meta = response.generations[0][0].message.response_metadata or {}
                except (AttributeError, IndexError):
                    pass
                timer.calls.append({"sec": round(time.monotonic() - timer._t0, 2),
                                    "prompt_tokens": meta.get("prompt_eval_count"), "output_tokens": meta.get("eval_count")})
        self.calls: list[dict] = []
        self._t0 = 0.0
        self.handler = _H()

    def take(self) -> list[dict]:
        out, self.calls = self.calls, []
        return out


async def score_one(metric, row: dict, timer: CallTimer) -> dict:
    rec = {"statements": None, "verdicts": None, "score": None, "error": None}
    t0 = time.monotonic()
    try:
        st = await metric._create_statements(row, [timer.handler])
        rec["statements"] = list(st.statements)
        rec["calls_split"] = timer.take()
        if rec["statements"]:
            vd = await metric._create_verdicts(row, rec["statements"], [timer.handler])
            rec["verdicts"] = [{"statement": v.statement, "verdict": int(v.verdict), "reason": v.reason} for v in vd.statements]
            rec["score"] = metric._compute_score(vd)
        rec["calls_verify"] = timer.take()
    except Exception as e:                       # JSON 파싱 실패·연결 실패 — 기록하고 다음으로
        rec["error"] = f"{type(e).__name__}: {e}"[:500]
        rec["calls_failed"] = timer.take()
    rec["sec"] = round(time.monotonic() - t0, 2)
    return rec


async def score_all(args) -> dict:
    from langchain_ollama import ChatOllama
    from ragas.llms.base import LangchainLLMWrapper
    from ragas.metrics import Faithfulness
    llm = ChatOllama(model=args.model, base_url=args.ollama, temperature=0, num_ctx=NUM_CTX)
    metric = Faithfulness(llm=LangchainLLMWrapper(llm))
    timer = CallTimer()
    data = json.loads(SET_PATH.read_text(encoding="utf-8"))
    results = []
    for it in data["items"]:
        for variant in VARIANTS:
            row = {"user_input": it["question"], "response": it["answers"][variant], "retrieved_contexts": it["contexts"]}
            runs = []
            for k in range(args.repeats):
                runs.append(await score_one(metric, row, timer))
                print(f"  {it['id']} {variant} #{k + 1}: {runs[-1]['score']} ({runs[-1]['sec']}초)"
                      + (f" 오류 {runs[-1]['error'][:80]}" if runs[-1]["error"] else ""), flush=True)
            results.append({"id": it["id"], "variant": variant, "question": it["question"], "answer": it["answers"][variant],
                            "context_chars": sum(len(c) for c in it["contexts"]), "runs": runs})
    return {"model": args.model, "ollama": args.ollama, "num_ctx": NUM_CTX, "repeats": args.repeats,
            "started_at": datetime.now().isoformat(timespec="seconds"), "results": results}


def summary(report: dict) -> str:
    lines = [f"# Ragas 파일럿 — faithfulness, 심판 {report['model']} (num_ctx {report['num_ctx']}, 반복 {report['repeats']})"]
    by_var = {v: [] for v in VARIANTS}
    calls, over_ctx, errors, unstable = [], 0, 0, []
    for r in report["results"]:
        scores = [x["score"] for x in r["runs"] if x["score"] is not None]
        by_var[r["variant"]] += scores
        errors += sum(x["error"] is not None for x in r["runs"])
        for x in r["runs"]:
            for c in x.get("calls_split", []) + x.get("calls_verify", []):
                calls.append(c["sec"])
                over_ctx += bool(c["prompt_tokens"]) and c["prompt_tokens"] >= report["num_ctx"]
        n_st = {len(x["statements"]) for x in r["runs"] if x["statements"] is not None}
        if scores and (max(scores) - min(scores) > 1e-9 or len(n_st) > 1):
            unstable.append(f"{r['id']} {r['variant']} 점수 {min(scores):.2f}~{max(scores):.2f}, 분해 문장 수 {sorted(n_st)}")
        lines.append(f"\n## {r['id']} {r['variant']} — 점수 {[round(s, 2) for s in scores]}")
        lines.append(f"질문: {r['question']}")
        lines.append(f"답변: {r['answer'][:300]}")
        first = next((x for x in r["runs"] if x["statements"] is not None), None)
        if first:
            lines.append("분해(1회차):")
            for v in first["verdicts"] or [{"statement": s, "verdict": "-", "reason": ""} for s in first["statements"]]:
                lines.append(f"  [{v['verdict']}] {v['statement']}")
    lines.append("\n## 요약")
    for v in VARIANTS:
        s = by_var[v]
        if s:
            lines.append(f"{v}: 평균 {statistics.mean(s):.3f} · 최소 {min(s):.2f} · 최대 {max(s):.2f} (n={len(s)})")
    g = by_var["grounded_ft"] + by_var["grounded_base"]
    f = by_var["fabricated"]
    if g and f:
        lines.append(f"구분: 근거 있는 답 최솟값 {min(g):.2f} vs 지어낸 답 최댓값 {max(f):.2f} → "
                     + ("겹치지 않음" if min(g) > max(f) else "겹침 — 문항별로 본다"))
    if calls:
        lines.append(f"호출 {len(calls)}회: 평균 {statistics.mean(calls):.1f}초 · 최대 {max(calls):.1f}초 | num_ctx 넘은 호출 {over_ctx}")
    lines.append(f"오류(파싱·연결) {errors}회 | 흔들림 {len(unstable)}건")
    lines += [f"  {u}" for u in unstable]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="08 Ragas 파일럿(gemma4:12b 한국어 faithfulness)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare", help="파일럿 세트 만들기(llm_env, Milvus)")
    sc = sub.add_parser("score", help="Ragas faithfulness 매기기(~/ragas_env, Ollama)")
    sc.add_argument("--model", default="gemma4:12b")
    sc.add_argument("--ollama", default="http://localhost:11434")
    sc.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare()
        return
    if not SET_PATH.exists():
        sys.exit(f"{SET_PATH} 없음 — 먼저 llm_env에서 python -m data.ragas_pilot prepare")
    import asyncio
    report = asyncio.run(score_all(args))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"ragas_pilot_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(summary(report))
    print(f"\n결과: {out}")


if __name__ == "__main__":
    main()
