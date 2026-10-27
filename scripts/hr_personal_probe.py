"""
hr_personal_probe.py
사내규정 개인화 탐침(data/eval/hr_personal.json)과 HR 검증 세트(verify_cases HR1~20)를 8000 서버에 묻는다 — 사내규정 모드, 질문마다 새 세션.
직원은 Access 헤더 이메일로 정한다(access 모드). 서버는 PETMINT_TODAY=2026-10-28·PETMINT_PROMPT_LOG로 띄운다(scripts/hr_personal_chain.sh).
판정: 기대값(쉼표·공백 무시)이 답에 다 있으면 정답. 음성·HR 세트는 판정하지 않고 답과 프롬프트를 남긴다(설정 간 대조용).

  python -m scripts.hr_personal_probe <out.json> [--runs 3]
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

from scripts.verify_cases import MODES

ROOT = Path(__file__).resolve().parent.parent
HEADER = "Cf-Access-Authenticated-User-Email"


def flat(t: str) -> str:
    return re.sub(r"[\s,]", "", t or "")


async def ask_seq(queries: list[str], email: str | None) -> list[dict]:
    """한 세션에서 차례로 묻는다 — 턴마다 답·근거(references)·근거 패널(sources 조 번호)"""
    headers = {HEADER: email} if email else {}
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", headers=headers) as h:
        sid = (await h.post("/api/sessions", json={"mode": "사내규정"})).json()["session_id"]
    out = []
    async with connect(f"ws://127.0.0.1:8000/ws/chat/{sid}", additional_headers=headers) as ws:
        for query in queries:
            await ws.send(json.dumps({"type": "question", "text": query}))
            ans, refs, srcs, tid = "", [], [], None
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 180))
                tid = m.get("turn_id", tid)
                if m["type"] == "token":
                    ans += m["text"]
                if m["type"] == "references":
                    refs = [x.get("article_num") for x in m["items"]]
                if m["type"] == "sources":
                    srcs = [x.get("article_num") for x in m["items"]]
                if m["type"] in ("done", "error", "clarify"):
                    break
            out.append(dict(turn_id=tid, answer=ans, refs=refs, sources=srcs))
    return out


async def ask(query: str, email: str | None) -> dict:
    return (await ask_seq([query], email))[0]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    data = json.loads((ROOT / "data/eval/hr_personal.json").read_text(encoding="utf-8"))
    hr = MODES["hr"]
    items = [("case", c["id"], c["email"], c["query"], c["expect"]) for c in data["cases"]]
    items += [("neg", c["id"], c["email"], c["query"], None) for c in data["negatives"]]
    items += [("hr", c.id, None, c.question, None) for c in hr.cases if not c.session]   # 멀티턴(HR19·20)은 뺀다
    seqs = data.get("sequences", [])
    rows = []
    for run in range(a.runs):
        for c in seqs:
            turns = await ask_seq(c["turns"], c["email"])
            for i, (q, r) in enumerate(zip(c["turns"], turns)):
                last = i == len(turns) - 1
                ok = (all(flat(x) in flat(r["answer"]) for x in c["expect"]) if c["expect"] else None) if last else None
                rows.append(dict(run=run, kind=("seq" if c["expect"] else "seqneg") + ("" if last else "0"), id=f"{c['id']}-{i + 1}",
                                 email=c["email"], query=q, ok=ok, **r))
        for kind, cid, email, q, expect in items:
            r = await ask(q, email)
            ok = all(flat(x) in flat(r["answer"]) for x in expect) if expect else None
            rows.append(dict(run=run, kind=kind, id=cid, email=email, query=q, ok=ok, **r))
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    cases = [r for r in rows if r["kind"] == "case"]
    seq = [r for r in rows if r["kind"] == "seq"]
    print(f"개인화 탐침 정답 {sum(r['ok'] for r in cases)}/{len(cases)} · 후속 정답 {sum(r['ok'] for r in seq)}/{len(seq)}")


if __name__ == "__main__":
    asyncio.run(main())
