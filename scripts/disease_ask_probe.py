"""
disease_ask_probe.py
병명 없이 보장을 묻는 질문 탐침(data/eval/disease_ask_probe.json, 2026-10-28)을 8000 서버에 묻는다 — 업무특화, 질문(묶음)마다 새 세션.
되묻기 판정: 답에 "어떤 질병이나 상해로"가 있으면 되물었다. 거절 판정은 평가와 같은 refused(). 후속은 둘째 턴을 기대값으로 본다.

  python -m scripts.disease_ask_probe <out.json> [--runs 3]
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

from scripts.eval_serving import refused

ROOT = Path(__file__).resolve().parent.parent
ASKED = "어떤 질병이나 상해로"


def flat(t: str) -> str:
    return re.sub(r"\s", "", t or "")


async def ask_seq(customer_id: str, pet_id: str, queries: list[str]) -> list[dict]:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as h:
        sid = (await h.post("/api/sessions", json={"mode": "업무특화", "customer_id": customer_id})).json()["session_id"]
    out = []
    async with connect(f"ws://127.0.0.1:8000/ws/chat/{sid}") as ws:
        for q in queries:
            await ws.send(json.dumps({"type": "question", "text": q, "pet_id": pet_id}))
            ans, tid = "", None
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 180))
                tid = m.get("turn_id", tid)
                if m["type"] == "token":
                    ans += m["text"]
                if m["type"] == "clarify":                  # 등급 되묻기 — 첫 선택지로 답한다
                    await ws.send(json.dumps({"type": "clarify_answer", "turn_id": m["turn_id"], "choice": m["options"][0]}))
                    continue
                if m["type"] in ("done", "error"):
                    break
            out.append(dict(turn_id=tid, answer=ans, refused=refused(ans), asked=ASKED in ans))
    return out


def check(answer: str, refused_: bool, e: dict) -> bool:
    a = flat(answer)
    return (("refuse" not in e or refused_ == e["refuse"]) and (not e.get("any") or any(flat(x) in a for x in e["any"]))
            and not any(flat(x) in a for x in e.get("none", [])))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--file", default="data/eval/disease_ask_probe.json")
    a = ap.parse_args()
    d = json.loads((ROOT / a.file).read_text(encoding="utf-8"))
    rows = []
    for run in range(a.runs):
        for kind in ("ask", "negatives"):
            for c in d[kind]:
                r = (await ask_seq(c["customer_id"], c["pet_id"], [c["query"]]))[0]
                rows.append(dict(run=run, kind=kind, id=c["id"], query=c["query"], **r))
        for c in d["sequences"]:
            rs = await ask_seq(c["customer_id"], c["pet_id"], c["turns"])
            for i, (q, r) in enumerate(zip(c["turns"], rs)):
                last = i == len(rs) - 1
                rows.append(dict(run=run, kind="seq" if last else "seq0", id=f"{c['id']}-{i + 1}", query=q,
                                 ok=check(r["answer"], r["refused"], c["expect"]) if last else None, **r))
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    k = lambda kind: [r for r in rows if r["kind"] == kind]
    print(f"되물어야 {sum(r['asked'] for r in k('ask'))}/{len(k('ask'))} (거절 {sum(r['refused'] for r in k('ask'))}) · "
          f"되묻지 말아야 {sum(not r['asked'] for r in k('negatives'))}/{len(k('negatives'))} · "
          f"후속 정답 {sum(r['ok'] for r in k('seq'))}/{len(k('seq'))} (후속 거절 {sum(r['refused'] for r in k('seq'))})")


if __name__ == "__main__":
    asyncio.run(main())
