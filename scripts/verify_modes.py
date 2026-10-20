"""
verify_modes.py
모드 검증 — 질문 묶음(verify_cases.py)을 실제 서버에 WebSocket으로 던지고 응답을 모아 판정한다(docs/모드검증.md).
서버는 그대로 쓴다(검색은 search-service, 생성은 Ollama) — 이 스크립트는 GPU를 쓰지 않는다.

  python -m scripts.verify_modes --mode=hr
  python -m scripts.verify_modes --mode=general --base=http://localhost:8000
  python -m scripts.verify_modes --mode=rag --customer=C005 --pet=P005
  python -m scripts.verify_modes --check-doc          # 질문 문장이 docs/모드검증.md에 있는지만 대조(서버 불필요)

세션: 질문마다 새 세션. Case.session이 같은 질문끼리는 한 세션·한 연결에서 차례로 묻는다(멀티턴 자리).
결과: <out>/verify_<mode>_<YYYYMMDD_HHMM>.json + 화면 요약. 자동 판정은 ✓/✗, 사람이 볼 것은 '사람' 표시.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from scripts.verify_cases import MODES, REFUSAL_PHRASES, Case, ModeSpec

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "모드검증.md"
AGENT_HEADER = "Cf-Access-Authenticated-User-Email"          # app/config.AGENT_HEADER — 로컬에서 상담원 값을 줄 때

# 메시지 순서 규약 — 타입을 한 글자로 줄인 열에 맞춘다(S sources, C calc, T token, R references, D done, Q clarify, E error)
ORDER_RULES = {
    "plain": (re.compile(r"^ST+RD$"), "sources → token… → references → done"),             # 일반·사내규정(calc 없음)
    "rag": (re.compile(r"^S(?:C?T+RD|Q)$"), "sources → (calc) → token… → references → done, 또는 sources → clarify"),
}
CODE = {"sources": "S", "calc": "C", "token": "T", "references": "R", "done": "D", "clarify": "Q", "error": "E"}
TERMINAL = {"done", "error", "clarify"}
AMOUNT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:만\s*)?(?:천\s*)?원|\d+\s*만\s*원")


def norm(t: str) -> str:
    return re.sub(r"[\s,]", "", t or "")


def source_label(s: dict) -> str:
    num = f"제{s['article_num']}조" if s.get("article_num") is not None else ""
    title = f"({s['article_title']})" if s.get("article_title") else ""
    return f"{num}{title}" or s.get("section_name") or s.get("section") or ""


# ----- 판정 -----

def judge(spec: ModeSpec, case: Case, r: dict) -> list[dict]:
    """자동 판정(✓/✗/!)과 사람 판정 항목. result: True 통과 / False 실패 / None 사람 또는 확인 필요"""
    out = []
    def auto(name, ok, detail=""):
        out.append({"name": name, "kind": "auto", "result": ok, "detail": detail})

    seq = "".join(CODE.get(m["type"], "?") for m in r["messages"])
    pat, desc = ORDER_RULES[spec.order]
    auto("메시지 순서", bool(pat.match(seq)), f"규약 {desc} | 받은 것 {re.sub('T+', 'T…', seq) or '(없음)'}")
    if r.get("error"):
        auto("오류 없음", False, f"{r['error'].get('code')}: {r['error'].get('message')}")
    ans = norm(r["answer"])
    for group in case.must_include:
        hit = [g for g in group if norm(g) in ans]
        auto(f"정답 숫자 {'/'.join(group)}", bool(hit), f"답변에 {hit[0]}" if hit else "답변에 없음")
    for bad in case.must_not_include:
        if norm(bad) in ans:
            auto(f"들어가면 안 되는 값 {bad}", False, "답변에 있음")
    if case.must_not_include and not any(norm(b) in ans for b in case.must_not_include):
        auto("들어가면 안 되는 값 없음", True, ", ".join(case.must_not_include))
    sus = [s for s in case.suspect_include if norm(s) in ans]
    if sus:
        out.append({"name": "확인 필요(다른 값 섞임?)", "kind": "auto", "result": None, "detail": ", ".join(sus)})
    if case.expect_refusal:
        hit = [p for p in REFUSAL_PHRASES if norm(p) in ans]
        auto("거절 문구", bool(hit), f"'{hit[0]}'" if hit else "거절 문구 없음 — 답을 지어냈는지 본다")
    nums = {s.get("article_num") for s in r["sources"]}
    for n in case.expect_articles:
        auto(f"출처에 제{n}조", n in nums, f"출처 조번호 {sorted(x for x in nums if x is not None)}")
    if case.sources_empty:
        auto("출처 패널 비어 있음", not r["sources"], f"{len(r['sources'])}건")
    if case.corpus_only:
        other = sorted({s.get("species") for s in r["sources"]} - {case.corpus_only})
        auto(f"출처 코퍼스가 {case.corpus_only}뿐", not other, f"다른 코퍼스 {other}" if other else "")
    if case.expect_calc:
        calc = r.get("calc") or {}
        kind = (calc.get("kind") or "medical") if calc else None
        auto(f"계산 카드 {case.expect_calc}", kind == case.expect_calc, f"받은 카드 {kind}")
        for k, v in case.calc_values:
            auto(f"카드 {k}={v}", bool(calc) and calc.get(k) == v, f"카드 값 {calc.get(k) if calc else '(카드 없음)'}")
    if spec.order == "plain":
        tokens = [m for m in r["messages"] if m["type"] == "token"]
        gaps = [b["t_ms"] - a["t_ms"] for a, b in zip(tokens, tokens[1:])]
        auto("스트리밍(토큰 2개 이상, 끝까지 done)", len(tokens) >= 2 and seq.endswith("D"),
             f"토큰 {len(tokens)}개, 최대 간격 {max(gaps) if gaps else 0}ms")
    for h in case.human:
        out.append({"name": h, "kind": "human", "result": None, "detail": ""})
    return out


# ----- 실행 -----

async def create_session(http: httpx.AsyncClient, spec: ModeSpec, customer: str | None) -> str:
    body = {"mode": spec.mode} | ({"customer_id": customer} if spec.needs_customer else {})
    r = await http.post("/api/sessions", json=body)
    r.raise_for_status()
    return r.json()["session_id"]


async def ask(ws, case: Case, pet: str | None, first_timeout: float, idle_timeout: float) -> dict:
    """질문 하나를 보내고 끝(done·error·clarify)까지 받는다. 시각은 보낸 때부터 ms"""
    msg = {"type": "question", "text": case.question} | ({"pet_id": case.pet_id or pet} if (case.pet_id or pet) else {})
    t0 = time.monotonic()
    await ws.send(json.dumps(msg, ensure_ascii=False))
    messages, answer = [], ""
    rec = {"messages": messages, "answer": "", "sources": [], "references": [], "calc": None, "clarify": None,
           "error": None, "turn_id": None, "client_first_token_ms": None, "client_total_ms": None,
           "server_latency_ms": None, "server_first_token_ms": None}
    while True:
        timeout = first_timeout if not messages else idle_timeout   # 첫 응답은 모델 로딩·검색까지 기다린다
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout)
        except asyncio.TimeoutError:
            rec["error"] = {"code": "client_timeout", "message": f"{timeout:.0f}초 동안 메시지 없음"}
            break
        except ConnectionClosed as e:
            rec["error"] = {"code": "ws_closed", "message": f"close {e.rcvd.code if e.rcvd else '?'}"}
            break
        m = json.loads(raw)
        t = int((time.monotonic() - t0) * 1000)
        messages.append({"t_ms": t, **m})
        rec["turn_id"] = rec["turn_id"] or m.get("turn_id")
        kind = m.get("type")
        if kind == "token":
            answer += m.get("text", "")
            if rec["client_first_token_ms"] is None:
                rec["client_first_token_ms"] = t
        elif kind == "sources":
            rec["sources"] = [{k: s.get(k) for k in ("species", "section", "section_name", "article_num", "article_title",
                                                     "coverage_type", "score", "graph_key")} | {"label": source_label(s)}
                              for s in m.get("items", [])]
        elif kind == "references":
            rec["references"] = m.get("items", [])
        elif kind == "calc":
            rec["calc"] = m.get("result")
        elif kind == "clarify":
            rec["clarify"] = m.get("options")
        elif kind == "error":
            rec["error"] = {"code": m.get("code"), "message": m.get("message")}
        elif kind == "done":
            rec["server_latency_ms"], rec["server_first_token_ms"] = m.get("latency_ms"), m.get("first_token_ms")
        if kind in TERMINAL:
            break
    rec["answer"] = answer
    rec["client_total_ms"] = int((time.monotonic() - t0) * 1000)
    return rec


def groups_of(cases: list[Case]) -> list[list[Case]]:
    """세션 묶음 — 같은 session 값은 한 묶음(처음 나온 자리), None은 질문마다 따로. 묶음 안 순서는 정의 순서"""
    out, by_key = [], {}
    for c in cases:
        if c.session is None:
            out.append([c])
        elif c.session in by_key:
            by_key[c.session].append(c)
        else:
            by_key[c.session] = [c]
            out.append(by_key[c.session])
    return out


async def run(spec: ModeSpec, args) -> dict:
    headers = dict(h.split(":", 1) for h in args.header)
    headers = {k.strip(): v.strip() for k, v in headers.items()}
    if args.agent:
        headers[AGENT_HEADER] = args.agent
    base = args.base.rstrip("/")
    ws_base = re.sub(r"^http", "ws", base)
    cases = [c for c in spec.cases if not args.only or c.id in args.only]
    results = []
    async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30) as http:
        for group in groups_of(cases):
            sid = await create_session(http, spec, args.customer)
            async with connect(f"{ws_base}/ws/chat/{sid}", additional_headers=headers, open_timeout=30,
                               max_size=None, ping_interval=None) as ws:
                for case in group:
                    print(f"  {case.id} {case.question}", flush=True)
                    rec = await ask(ws, case, args.pet, args.first_timeout, args.timeout)
                    results.append({"id": case.id, "question": case.question, "expect": case.expect, "session_id": sid,
                                    **rec})
            # 새로고침 뒤 복원 — 세션 상세(GET /api/sessions/{id})에 이 묶음의 턴이 같은 답변으로 남았나
            detail = (await http.get(f"/api/sessions/{sid}")).json()
            stored = {t["turn_id"]: t for t in detail.get("turns", [])}
            for r in results:
                if r["session_id"] == sid:
                    t = stored.get(r["turn_id"])
                    r["restored"] = {"found": t is not None, "same_answer": bool(t) and t["answer"] == r["answer"],
                                     "sources": len(t["sources"]) if t else None}
    for r in results:
        case = next(c for c in spec.cases if c.id == r["id"])
        r["checks"] = judge(spec, case, r)
        if r.get("clarify") is None and r.get("turn_id"):
            ok = r.get("restored", {}).get("found") and r["restored"]["same_answer"]
            r["checks"].append({"name": "새로고침 뒤 복원(세션 상세에 같은 답변)", "kind": "auto", "result": bool(ok),
                                "detail": json.dumps(r.get("restored"), ensure_ascii=False)})
        r["amounts_in_answer"] = sorted(set(m.group(0).strip() for m in AMOUNT.finditer(r["answer"])))
    return {"mode": spec.key, "server_mode": spec.mode, "model": spec.model, "corpus": spec.corpus, "base": base,
            "started_at": datetime.now().isoformat(timespec="seconds"), "cases": results}


def summary(report: dict) -> str:
    mark = {True: "✓", False: "✗", None: "!"}
    lines = [f"# 모드 검증 — {report['server_mode']} ({report['model']}, 코퍼스 {report['corpus']}) · {report['base']}"]
    for r in report["cases"]:
        autos = [c for c in r["checks"] if c["kind"] == "auto"]
        fails = sum(c["result"] is False for c in autos)
        lines.append(f"\n## {r['id']} {'실패 ' + str(fails) if fails else '자동 통과'} — {r['question']}")
        lines.append(f"정답·보는 것: {r['expect']}")
        lines.append(f"시간: 첫 토큰 {r['client_first_token_ms']}ms · 전체 {r['client_total_ms']}ms"
                     f" (서버 first_token {r['server_first_token_ms']} · latency {r['server_latency_ms']})")
        if r.get("error"):
            lines.append(f"오류: {r['error']['code']} — {r['error']['message']}")
        lines.append("출처: " + (" / ".join(f"{s['label']} [{s.get('section_name') or s.get('section')}]" for s in r["sources"])
                                 or "(없음)"))
        lines.append("쓴 근거(references): " + (" / ".join(x.get("citation_label", "") for x in r["references"]) or "(없음)"))
        if r.get("calc"):
            lines.append(f"계산 카드: {json.dumps(r['calc'], ensure_ascii=False)}")
        if r.get("clarify"):
            lines.append(f"되묻기: {r['clarify']}")
        if r["amounts_in_answer"]:
            lines.append(f"답변 속 금액: {', '.join(r['amounts_in_answer'])}")
        for c in r["checks"]:
            tag = "사람" if c["kind"] == "human" else mark[c["result"]]
            lines.append(f"  [{tag}] {c['name']}" + (f" — {c['detail']}" if c["detail"] else ""))
        lines.append("답변:\n" + "\n".join("  " + l for l in (r["answer"] or "(빈 답변)").splitlines()))
    total = [c for r in report["cases"] for c in r["checks"] if c["kind"] == "auto"]
    lines.append(f"\n자동 판정: 통과 {sum(c['result'] is True for c in total)} · 실패 {sum(c['result'] is False for c in total)}"
                 f" · 확인 필요 {sum(c['result'] is None for c in total)} | 사람 판정 "
                 f"{sum(c['kind'] == 'human' for r in report['cases'] for c in r['checks'])}건")
    return "\n".join(lines)


def check_doc() -> int:
    """질문 문장이 docs/모드검증.md에 그대로 있는지(문서를 파싱하지 않고 문장 포함만 본다). 업무특화는 질문이 없어 건너뜀"""
    text = DOC.read_text(encoding="utf-8")
    missing = [(m.key, c.id, c.question) for m in MODES.values() for c in m.cases if c.question not in text]
    for key, cid, q in missing:
        print(f"문서에 없음: {key} {cid} {q}")
    print(f"질문 {sum(len(m.cases) for m in MODES.values())}개 중 문서에 없는 것 {len(missing)}개")
    return 1 if missing else 0


def main():
    p = argparse.ArgumentParser(description="모드 검증(docs/모드검증.md)")
    p.add_argument("--mode", choices=sorted(MODES), help="hr=사내규정, general=일반, rag=업무특화")
    p.add_argument("--base", default="http://localhost:8000", help="서버 주소 — 배포는 https://petmint.ronanlab.dev")
    p.add_argument("--header", action="append", default=[], metavar="'Name: value'",
                   help="요청·WS 헤더(반복 가능). 배포는 Cloudflare Access — 서비스 토큰(CF-Access-Client-Id/Secret) 또는 'Cookie: CF_Authorization=…'")
    p.add_argument("--agent", help=f"상담원 값({AGENT_HEADER}). 로컬에서만 의미가 있다 — 배포는 Access가 넣는다")
    p.add_argument("--customer", help="업무특화 세션의 customer_id")
    p.add_argument("--pet", help="업무특화 질문의 pet_id(질문에 pet_id가 없을 때)")
    p.add_argument("--only", nargs="*", help="이 질문 id만(예: HR3 HR5)")
    p.add_argument("--first-timeout", type=float, default=600, help="질문마다 첫 메시지까지 기다릴 초(모델 로딩)")
    p.add_argument("--timeout", type=float, default=180, help="그 뒤 메시지 사이 최대 초")
    p.add_argument("--out", default=str(ROOT / "data" / "review"), help="결과 JSON 폴더")
    p.add_argument("--check-doc", action="store_true", help="질문이 docs/모드검증.md와 같은지만 본다")
    args = p.parse_args()
    if args.check_doc:
        sys.exit(check_doc())
    if not args.mode:
        p.error("--mode가 필요하다")
    spec = MODES[args.mode]
    if not spec.cases:
        print(f"{spec.mode}: 질문이 없다 — scripts/verify_cases.py의 {spec.key.upper()} cases를 채운다")
        return
    if spec.needs_customer and not args.customer:
        p.error(f"{spec.mode} 모드는 --customer가 필요하다")
    print(f"{spec.mode} 검증 시작 — {args.base}, 질문 {len(spec.cases)}개")
    report = asyncio.run(run(spec, args))
    out = Path(args.out) / f"verify_{spec.key}_{datetime.now():%Y%m%d_%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(summary(report))
    print(f"\n결과: {out}")


if __name__ == "__main__":
    main()
