"""
seed_consultations.py
관리자 화면 시드 상담(2026-11-12, docs/13 2-5절) — db/fixtures/seed_consultations.json의 질문을 **챗봇에 실제로 물어** 상담을 만든다.
답 · 발췌(retrieved) · 근거 조항(references) · 계산 카드는 운영 경로 그대로 남는다. 시각만 나중에 SQL로 흩는다.

  python scripts/seed_consultations.py run https://petmint.ronanlab.dev  out.json   # 1) 묻기 — 체험 로그인으로 직원마다 들어간다
  python scripts/seed_consultations.py retime out.json > retime.sql                  # 2) 시각 흩기 SQL(평일 09~18시 KST, 2주)
  # 3) 운영: zcat 없이 retime.sql을 mysql에 넣는다(docs/12 1-5절의 $K)

- 체험 로그인(POST /api/auth/demo)을 쓰므로 PETMINT_DEMO_LOGIN=1이고 그 직원의 앱 계정이 있어야 한다(0012).
- 업무특화는 질문마다 pet_id를 붙이고, 끝나면 상담 종료(DELETE). 되묻기(clarify)가 오면 첫 선택지로 답한다.
- 상담원 평가(fb)는 실제 피드백 API로 남긴다. 체험 세션은 끝에 로그아웃한다.
"""

import asyncio
import json
import random
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

FIXTURE = Path(__file__).resolve().parents[1] / "db" / "fixtures" / "seed_consultations.json"
KST = timezone(timedelta(hours=9))


async def ask(ws, text: str, pet: str | None) -> dict:
    """질문 하나 → 서버 메시지를 done/error까지 모은다. 되묻기면 첫 선택지로 답한다"""
    await ws.send(json.dumps({"type": "question", "text": text, "pet_id": pet}))
    out = {"q": text, "turn_id": None, "sources": 0, "references": 0, "calc": False, "answer": "", "clarified": None}
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
        out["turn_id"] = m.get("turn_id") or out["turn_id"]
        t = m["type"]
        if t == "token":
            out["answer"] += m["text"]
        elif t == "sources":
            out["sources"] = len(m["items"])
        elif t == "references":
            out["references"] = len(m["items"])
        elif t == "calc":
            out["calc"] = True
        elif t == "clarify":
            out["clarified"] = m["options"][0]
            await ws.send(json.dumps({"type": "clarify_answer", "turn_id": m["turn_id"], "choice": m["options"][0]}))
        elif t == "done":
            out["latency_ms"] = m["latency_ms"]
            return out
        elif t == "error":
            out["error"] = f'{m["code"]}: {m["message"]}'
            return out


async def run(base: str, out_path: str, limit: int | None = None) -> None:
    seed = json.loads(FIXTURE.read_text())["sessions"][:limit]
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    hdr = {"Origin": base}
    results = []
    by_emp: dict[str, list[dict]] = {}
    for s in seed:
        by_emp.setdefault(s["emp"], []).append(s)
    for emp, sessions in by_emp.items():
        c = httpx.Client(base_url=base, timeout=60, headers=hdr)
        r = c.post("/api/auth/demo", json={"employee_id": emp})
        r.raise_for_status()
        email = r.json()["email"]
        cookie = f'petmint_session={c.cookies.get("petmint_session")}'
        for s in sessions:
            body = {"mode": s["mode"]} | ({"customer_id": s["customer"]} if s["mode"] == "업무특화" else {})
            sess = c.post("/api/sessions", json=body)
            sess.raise_for_status()
            sid = sess.json()["session_id"]
            turns = []
            async with connect(f"{ws_base}/ws/chat/{sid}", additional_headers={"Cookie": cookie, "Origin": base}, max_size=None) as ws:
                for t in s["turns"]:
                    res = await ask(ws, t["q"], s.get("pet"))
                    if t.get("fb") and res["turn_id"] and "error" not in res:
                        fb = c.post(f'/api/turns/{res["turn_id"]}/feedback', json={"rating": t["fb"], "comment": t.get("comment")})
                        res["feedback"] = fb.status_code
                    turns.append(res)
                    print(f'{emp} {s["mode"]} {res.get("latency_ms", "-")}ms src={res["sources"]} ref={res["references"]} '
                          f'{"calc " if res["calc"] else ""}{res.get("error", "")} | {t["q"][:30]}', flush=True)
            if s["mode"] == "업무특화":
                c.delete(f"/api/sessions/{sid}")
            results.append({"session_id": sid, "emp": emp, "email": email, "mode": s["mode"], "turns": turns})
            Path(out_path).write_text(json.dumps(results, ensure_ascii=False, indent=1))
        c.post("/api/auth/logout")
    print(f"세션 {len(results)} · 턴 {sum(len(r['turns']) for r in results)} · 오류 "
          f"{sum('error' in t for r in results for t in r['turns'])}")


def retime(out_path: str, today: date) -> str:
    """세션마다 평일 09:00~17:30 KST 시각을 준다(직원마다 겹치지 않게, 최근 2주). 오늘에도 몇 건. 턴은 1~3분 간격.
    결정적이다(같은 입력이면 같은 시각). DB는 UTC naive라 9시간을 뺀다"""
    rows = json.loads(Path(out_path).read_text())
    rnd = random.Random(20261112)
    days = [today - timedelta(days=i) for i in range(0, 17) if (today - timedelta(days=i)).weekday() < 5]
    now_kst = datetime.now(KST).replace(tzinfo=None)
    used: set[tuple[str, date]] = set()
    sql = ["-- seed_consultations retime — 생성된 상담의 시각만 흩는다(내용은 그대로)", "START TRANSACTION;"]
    utc = lambda d: (d - timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    for i, r in enumerate(rows):
        while True:
            day = days[0] if i % 7 == 0 else rnd.choice(days[1:])     # 일곱에 하나는 오늘(관리자 화면 기본이 오늘이다)
            if (r["emp"], day) not in used or len(used) > 200:
                break
        used.add((r["emp"], day))
        start = datetime.combine(day, time(9, 0)) + timedelta(minutes=rnd.randrange(0, 8 * 60 + 30))
        if day == today and start > now_kst - timedelta(minutes=30):   # 오늘이면 지금보다 앞
            start = now_kst - timedelta(minutes=rnd.randrange(30, 240))
        t = start + timedelta(seconds=rnd.randrange(20, 60))
        sql.append(f"-- {r['email']} {r['mode']}")
        for turn in r["turns"]:
            if not turn.get("turn_id"):
                continue
            sql.append(f"UPDATE turns SET created_at = '{utc(t)}' WHERE turn_id = '{turn['turn_id']}';")
            sql.append(f"UPDATE feedback SET created_at = '{utc(t + timedelta(seconds=40))}' WHERE turn_id = '{turn['turn_id']}';")
            t += timedelta(seconds=rnd.randrange(60, 180))
        end = f"'{utc(t)}'" if r["mode"] == "업무특화" else "NULL"
        sql.append(f"UPDATE sessions SET started_at = '{utc(start)}', ended_at = {end} WHERE session_id = '{r['session_id']}';")
    sql.append("COMMIT;")
    return "\n".join(sql) + "\n"


if __name__ == "__main__":
    if sys.argv[1] == "run":
        asyncio.run(run(sys.argv[2].rstrip("/"), sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else None))   # 넷째 인자: 앞 N개만(시험)
    elif sys.argv[1] == "retime":
        print(retime(sys.argv[2], date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else datetime.now(KST).date()), end="")
