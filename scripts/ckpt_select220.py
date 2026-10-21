"""
ckpt_select220.py
체크포인트 고르기를 평가 220 보이는 세트로(2026-10-22 사용자 결정 8 — 옛 30문항은 좁다). data/ckpt_select.py를 대신한다.

입력: 같은 코드로 잰 서빙 평가 결과(eval_serving JSON)와 그 실행의 서버 프롬프트 로그 — 모델이 답한 턴의 프롬프트(1회차, 보이는 세트만)를
그대로 체크포인트마다 넣는다(HF 4-bit + LoRA, greedy — answer_eval.Generator). 프롬프트는 모델과 무관하다(검색·조립은 코드).
판정: 참고 답이 있는 턴은 eval_judge와 같은 판정(gemma4:12b), 거절해야 하는 턴(expect.refuse)은 거절했는지.
점수 = 정확 − 2×틀림 + 거절해야 하는데 거절한 수. 동점이면 틀림이 적은 쪽, 그다음 뒤 step.
결과: <어댑터>/ckpt_select.json(best_path — GGUF 변환이 이것을 쓴다) + data/review/ckpt_select220_<태그>_<시각>.md

  python -m scripts.ckpt_select220 <어댑터 폴더> --result <eval_serving json> --prompts <prompts jsonl>
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def step_of(p: Path) -> int:
    m = re.search(r"checkpoint-(\d+)", p.name)
    return int(m.group(1)) if m else 10 ** 9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("adapter")
    ap.add_argument("--result", required=True)
    ap.add_argument("--prompts", required=True)
    a = ap.parse_args()
    from data.answer_eval import Generator
    from scripts.eval_judge import PROMPT, ask
    from scripts.eval_serving import refused
    adapter = Path(a.adapter)
    cands = sorted([p for p in adapter.glob("checkpoint-*") if (p / "adapter_config.json").exists()], key=step_of)
    if (adapter / "adapter_config.json").exists():
        cands.append(adapter)
    rep = json.loads(Path(a.result).read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "data" / "eval" / "eval220.json").read_text(encoding="utf-8"))["cases"]
    turns = {t["id"]: t for c in cases for t in (c.get("turns") or [c])}
    by_turn = {r["turn_id"]: r for r in rep["turns"] if r["run"] == 0 and r["id"] in turns}
    prompts = []
    for line in Path(a.prompts).read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        r = by_turn.get(p.get("turn_id"))
        if r is None:
            continue
        t = turns[r["id"]]
        if t["expect"].get("refuse") or t.get("answer"):
            prompts.append({"id": r["id"], "messages": p["messages"], "turn": t})
    print(f"후보 {len(cands)}개 · 프롬프트 {len(prompts)}턴(1회차 모델 답 턴)", flush=True)
    gen = Generator(cands)
    answers = {i: {} for i in range(len(cands))}
    for k, p in enumerate(prompts, 1):
        for i in range(len(cands)):
            answers[i][p["id"]] = gen(p["messages"], i)
        if k % 10 == 0:
            print(f"생성 {k}/{len(prompts)}", flush=True)
    del gen
    import gc
    import torch
    gc.collect()
    torch.cuda.empty_cache()
    scored = {}
    for i, c in enumerate(cands):
        cnt = Counter()
        for p in prompts:
            ans, t = answers[i][p["id"]], p["turn"]
            if t["expect"].get("refuse"):
                cnt["거절해야_거절"] += refused(ans)
                cnt["거절해야"] += 1
                continue
            ev = " / ".join(g["evidence"] for g in t.get("gold", [])) or "(없음 — 약관에 없는 내용)"
            cnt[ask("gemma4:12b", PROMPT.format(question=t["query"], reference=t["answer"], evidence=ev, answer=ans))["verdict"]] += 1
        cnt["점수"] = cnt["정확"] - 2 * cnt["틀림"] + cnt["거절해야_거절"]
        scored[str(c)] = dict(cnt)
        print(c.name, dict(cnt), flush=True)
    best = max(cands, key=lambda c: (scored[str(c)]["점수"], -scored[str(c)].get("틀림", 0), step_of(c)))
    sel = {"best_path": str(best), "best_step": step_of(best), "scored": scored, "n_prompts": len(prompts),
           "result": a.result, "created": datetime.now().isoformat(timespec="seconds")}
    (adapter / "ckpt_select.json").write_text(json.dumps(sel, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# 체크포인트 선택(평가 220 보이는 세트) — {adapter.name}", "",
         f"프롬프트 {len(prompts)}턴(기준 실행 1회차의 모델 답 턴). 점수 = 정확 − 2×틀림 + 거절해야 하는데 거절", "",
         "| 후보 | 정확 | 예외누락 | 틀림 | 거절 | 거절해야→거절 | 점수 |", "|---|---|---|---|---|---|---|"]
    for c in cands:
        s = scored[str(c)]
        L.append(f"| {c.name}{' **선택**' if c == best else ''} | {s.get('정확', 0)} | {s.get('예외누락', 0)} | {s.get('틀림', 0)} | "
                 f"{s.get('거절', 0)} | {s.get('거절해야_거절', 0)}/{s.get('거절해야', 0)} | {s['점수']} |")
    path = ROOT / "data" / "review" / f"ckpt_select220_{adapter.name}_{datetime.now():%Y%m%d_%H%M}.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("선택:", best, "→", path)


if __name__ == "__main__":
    main()
