"""
probe_length.py
길이 지름길 직접 시험 — 정답이 프롬프트에 있는데 거절하는 원인이 '정답 발췌가 짧아서'인지를 내용은 그대로 두고 길이만 바꿔 본다.
2026-10-21 감사: 학습 정답 발췌(단위, 중앙값 853자)가 서빙 청크(390자)보다 길어 '가장 긴 블록 길이'만으로 정답 유무를 AUC 0.755로 가른다.
그렇다면 같은 근거를 더 짧게 보여주면 거절이 늘어야 한다(청킹을 바꾸면 발췌가 짧아지므로 6단계 해석에 필요하다).

방법: 서빙 평가(eval_serving)에서 정답이 프롬프트에 있고 모델이 답한 턴의 프롬프트를 가져와, 정답 근거가 든 발췌 블록 본문만
'근거가 든 줄 ± 1줄'로 줄인다(머리말 [발췌 n] 라벨·다른 발췌·참조·질문은 그대로). 원본과 짧은 판을 같은 모델·옵션으로 N회씩.
거절률이 짧은 판에서 오르면 길이 지름길이 거절을 만든다는 직접 증거다.

  python -m scripts.probe_length --result logs/baseline/eval_serving_…_baseline_ft.json --prompt-log logs/baseline/prompts_ft.jsonl
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import httpx

from data import prompts
from scripts.eval_serving import flat, refused

ROOT = Path(__file__).resolve().parent.parent
_BLOCK = re.compile(r"(?m)^\[발췌 \d+\] .*$")


def shorten(user: str, evidence: list[str]) -> tuple[str, int, int] | None:
    """정답 근거가 든 발췌 블록의 본문을 근거 줄 ± 1줄로. (새 user, 원래 블록 길이, 새 블록 길이). 근거 블록을 못 찾으면 None"""
    head, sep, tail = user.partition(prompts.QUESTION_HEADER)
    starts = [m.start() for m in _BLOCK.finditer(head)] + [len(head)]
    for a, b in zip(starts, starts[1:]):
        block = head[a:b]
        body, ref_sep, refs = block.partition("\n[참조]")
        if not any(flat(e) in flat(body) for e in evidence):
            continue
        label, _, text = body.partition("\n")
        unit = _unit_with(text, evidence)
        if unit is None:
            return None
        new_block = f"{label}\n{unit.strip()}\n\n" + (ref_sep + refs if ref_sep else "")
        return head[:a] + new_block + head[b:] + sep + tail, len(block), len(new_block)
    return None


_ITEM = re.compile(r"(?m)^\s*(?=[①-⑳])|\n\s*\n")


def _unit_with(text: str, evidence: list[str]) -> str | None:
    """근거가 든 구조 단위 — 호(①…⑳)나 빈 줄로 나눈 덩어리. 400자를 넘으면 그 안에서 근거가 든 문장(…다.)만.
    6단계 청킹(호 단위 조각)과 같은 모양을 흉내 낸다 — 줄 단위로 자르면 문장이 중간에서 끊겨 '짧음'과 '잘림'이 섞인다"""
    has = lambda u: any(flat(e) in flat(u) for e in evidence)
    units = [u for u in _ITEM.split(text) if u.strip()]
    unit = next((u for u in units if has(u)), None)
    if unit is None:
        return None
    if len(unit) > 400:
        sents = re.split(r"(?<=다\.)\s+", unit)
        for i in range(len(sents)):
            for j in range(i + 1, len(sents) + 1):
                if has(" ".join(sents[i:j])):
                    return " ".join(sents[i:j])
    return unit


def generate(model: str, messages: list[dict], options: dict) -> str:
    r = httpx.post("http://localhost:11434/api/chat", timeout=300,
                   json={"model": model, "messages": messages, "stream": False, "options": options})
    r.raise_for_status()
    return r.json()["message"]["content"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--prompt-log", required=True)
    ap.add_argument("--n", type=int, default=3, help="판마다 생성 횟수")
    ap.add_argument("--model", help="같은 프롬프트를 다른 모델로(예: tri-7b — 학습 영향 없는 대조군). 없으면 기록된 모델")
    ap.add_argument("--tag", default="", help="결과 파일 접미사")
    args = ap.parse_args()
    report = json.loads(Path(args.result).read_text(encoding="utf-8"))
    logged = {json.loads(l)["turn_id"]: json.loads(l) for l in Path(args.prompt_log).read_text(encoding="utf-8").splitlines()}
    cases = json.loads((ROOT / "data" / "eval" / "eval220.json").read_text(encoding="utf-8"))["cases"]
    turns = {t["id"]: t for c in cases for t in (c.get("turns") or [c])}
    picked = [r for r in report["turns"] if r["run"] == 0 and r.get("gold_in_prompt") and not r["refused"]]
    rows, skipped = [], 0
    for r in picked:
        p = logged[r["turn_id"]]
        ev = [g["evidence"] for g in turns[r["id"]]["gold"]]
        user = next(m["content"] for m in p["messages"] if m["role"] == "user")
        s = shorten(user, ev)
        if s is None:
            skipped += 1
            continue
        short_user, n0, n1 = s
        if n1 >= 0.7 * n0:                 # 이미 짧은 블록 — 길이를 바꾸지 못해 시험이 안 된다
            skipped += 1
            continue
        short_msgs = [dict(m, content=short_user) if m["role"] == "user" else m for m in p["messages"]]
        res = {"id": r["id"], "block_chars": n0, "short_chars": n1, "orig": [], "short": []}
        for _ in range(args.n):
            model = args.model or p["model"]
            res["orig"].append(refused(generate(model, p["messages"], p["options"])))
            res["short"].append(refused(generate(model, short_msgs, p["options"])))
        rows.append(res)
        print(f"{r['id']}: 블록 {n0}→{n1}자 | 거절 원본 {sum(res['orig'])}/{args.n} · 짧은 판 {sum(res['short'])}/{args.n}", flush=True)
    o = sum(sum(x["orig"]) for x in rows)
    s = sum(sum(x["short"]) for x in rows)
    n = len(rows) * args.n
    med = lambda v: sorted(v)[len(v) // 2] if v else 0
    print(f"\n문항 {len(rows)}(근거 블록을 못 찾았거나 이미 짧아 뺀 것 {skipped}) × {args.n}회 — 정답 블록 중앙값 "
          f"{med([x['block_chars'] for x in rows])}자 → {med([x['short_chars'] for x in rows])}자")
    print(f"거절: 원본 {o}/{n} · 짧은 판 {s}/{n}")
    flips = Counter((sum(x["orig"]) > 0, sum(x["short"]) > 0) for x in rows)
    print(f"문항별: 원본 답함→짧은 판 거절 {flips[(False, True)]} · 원본 거절→짧은 판 답함 {flips[(True, False)]}")
    out = Path(args.result).with_suffix(f".length_probe{args.tag}.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"결과: {out}")


if __name__ == "__main__":
    main()
