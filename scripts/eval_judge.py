"""
eval_judge.py
서빙 평가 결과(scripts/eval_serving.py)의 모델 답을 내용으로 판정한다 — 정확 / 예외누락 / 틀림 / 거절 / 무관.
판정 모델은 gemma4:12b(생성 모델 tri-7b와 다르다). 참고 답(문항의 answer)과 정답 근거 문장을 주고, 답이 그것과 맞는지만 보게 한다.
코드가 쓴 답(금액 계산·되묻기)은 자동 판정(eval_serving)으로 충분해 판정하지 않는다.

판정 모델도 틀린다 — 처음 쓸 때 사람(Claude) 판정과 표본으로 맞춰 본다(--sample로 표본을 뽑아 사람이 판정해 --human으로 넣으면 일치율).

  python -m scripts.eval_judge --result data/eval/results/eval_serving_….json [--model gemma4:12b]
"""

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
VERDICTS = ("정확", "예외누락", "틀림", "거절", "무관")

PROMPT = """너는 보험 상담 답변을 채점한다. [참고 답]과 [약관 근거]가 정답이다. [상담 답변]이 그 정답과 맞는지만 본다.
판정은 다섯 가지 중 하나다.
- 정확: 결론이 참고 답과 같고, 참고 답에 있는 핵심 조건·금액을 빠뜨리지 않았다(표현이 달라도 된다. 군더더기가 있어도 결론이 맞으면 정확)
- 예외누락: 결론은 맞지만 참고 답에 있는 단서·예외·조건 중 하나 이상을 빠뜨렸다(참고 답에 없는 내용을 더 말한 것은 감점하지 않는다 —
  그 더한 내용이 약관과 어긋날 때만 틀림)
- 틀림: 결론·금액·기간이 참고 답과 다르거나, 약관 근거와 반대로 말했다
- 거절: 확인할 수 없다·약관에서 확인되지 않는다는 식으로 답하지 않았다
- 무관: 질문과 상관없는 내용을 답했다
JSON 한 줄로만 답한다: {{"verdict": "정확|예외누락|틀림|거절|무관", "reason": "한 문장"}}

[질문] {question}
[참고 답] {reference}
[약관 근거] {evidence}
[상담 답변] {answer}"""


def ask(model: str, prompt: str) -> dict:
    r = httpx.post("http://localhost:11434/api/chat", timeout=300, json={
        "model": model, "stream": False, "format": "json", "think": False,
        "options": {"temperature": 0, "num_predict": 200},
        "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    text = r.json()["message"]["content"]
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        out = json.loads(m.group(0)) if m else {}
    v = out.get("verdict")
    return {"verdict": v if v in VERDICTS else "파싱실패", "reason": out.get("reason", text[:200])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--model", default="gemma4:12b")
    ap.add_argument("--sample", type=int, help="사람 판정용 표본 N개를 뽑아 <result>.judge_sample.json으로")
    ap.add_argument("--human", help="사람 판정 파일 {turn key: verdict} — 판정 모델과 일치율")
    args = ap.parse_args()
    path = Path(args.result)
    report = json.loads(path.read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "data" / "eval" / "eval220.json").read_text(encoding="utf-8"))["cases"]
    if report.get("open_hidden"):
        cases += json.loads((ROOT / "data" / "eval" / "eval220_hidden.json").read_text(encoding="utf-8"))["cases"]
    turns = {t["id"]: t for c in cases for t in (c.get("turns") or [c])}
    out_path = path.with_suffix(".judge.json")
    if out_path.exists() and json.loads(out_path.read_text(encoding="utf-8")).get("_prompt") != hashlib.sha256(PROMPT.encode()).hexdigest()[:12]:
        out_path.unlink()                    # 판정 기준이 바뀌었다 — 다시 판정
    done = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {"_prompt": hashlib.sha256(PROMPT.encode()).hexdigest()[:12]}
    # 거절해야 하는 문항(약관에 없음)은 자동 판정(거절 여부)이 맡는다 — 내용 판정에서 거절이 '정답'이라 다섯 갈래와 섞인다
    todo = [r for r in report["turns"] if r["prompt_logged"] and r["answer"] and turns[r["id"]].get("answer")
            and not turns[r["id"]]["expect"].get("refuse")]
    skipped = sum(1 for r in report["turns"] if r["prompt_logged"] and r["answer"] and not turns[r["id"]].get("answer"))
    for i, r in enumerate(todo):
        key = f"{r['run']}:{r['id']}"
        if key in done:
            continue
        t = turns[r["id"]]
        ev = " / ".join(g["evidence"] for g in t.get("gold", [])) or "(없음 — 약관에 없는 내용)"
        done[key] = ask(args.model, PROMPT.format(question=t["query"], reference=t["answer"], evidence=ev, answer=r["answer"]))
        if i % 20 == 0:
            out_path.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    out_path.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    runs = sorted({r["run"] for r in todo})
    print(f"판정 {len(todo)}턴(참고 답 없는 모델 턴 {skipped}개 제외) — {args.model}")
    for k in runs:
        c = Counter(done[f"{k}:{r['id']}"]["verdict"] for r in todo if r["run"] == k)
        print(f"  실행 {k + 1}: " + " · ".join(f"{v} {c[v]}" for v in (*VERDICTS, "파싱실패") if c[v]))
    if args.sample:
        random.seed(0)
        pick = random.sample([r for r in todo if r["run"] == 0], min(args.sample, sum(1 for r in todo if r["run"] == 0)))
        sample = [dict(key=f"0:{r['id']}", question=turns[r["id"]]["query"], reference=turns[r["id"]]["answer"],
                       evidence=[g["evidence"] for g in turns[r["id"]].get("gold", [])], answer=r["answer"],
                       judge=done[f"0:{r['id']}"]) for r in pick]
        sp = path.with_suffix(".judge_sample.json")
        sp.write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"표본 {len(sample)}개 → {sp}")
    if args.human:
        human = json.loads(Path(args.human).read_text(encoding="utf-8"))
        agree = sum(1 for k, v in human.items() if done.get(k, {}).get("verdict") == v)
        print(f"사람 판정과 일치 {agree}/{len(human)}")
        for k, v in human.items():
            if done.get(k, {}).get("verdict") != v:
                print(f"  {k}: 사람 {v} · 판정 모델 {done.get(k, {}).get('verdict')} — {done.get(k, {}).get('reason')}")


if __name__ == "__main__":
    main()
