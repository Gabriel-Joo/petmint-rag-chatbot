"""
eval_serving.py
평가 세트(data/eval/eval220.json)를 실제 서버로 잰다 — 서빙 경로 그대로(고객 범위·후속 질문·되묻기·코드 답·카드).
예전 answer_eval --search는 서빙과 다른 경로(참조 조문 없음, 고객 범위 없음)였다(2026-10-21 발견). 이 도구는 서버를 거치므로
서빙과 다를 수 없다. 모델이 실제로 본 프롬프트는 서버의 PETMINT_PROMPT_LOG에서 turn_id로 붙인다.

  # 서버를 프롬프트 기록과 함께 띄운다(업무특화 모델은 PETMINT_MODEL_RAG — 베이스로 재려면 tri-7b)
  PETMINT_PROMPT_LOG=logs/eval/prompts_ft.jsonl uvicorn app.main:app --port 8000
  python -m scripts.eval_serving --tag rebuild4 --runs 3 --prompt-log logs/eval/prompts_ft.jsonl

판정(자동): 낱말 묶음(must·must_not), 거절, 카드 종류·값(범위는 허용 오차), 부담보 배너(화면과 같은 대조 규칙), 멀티턴 처리 종류,
정답이 검색 결과(sources)·프롬프트에 들어갔는가. 내용 판정(정확·예외누락·틀림)은 scripts/eval_judge.py가 따로 한다.
숨긴 세트(eval220_hidden.json)는 --open-hidden으로만 연다 — 해시를 manifest와 대조한다.
"""

import argparse
import asyncio
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.schemas import Pet
from app.services import payout
from data import prompts
from scripts.verify_cases import REFUSAL_PHRASES
from scripts.verify_modes import AGENT_HEADER, calc_field

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "data" / "eval"
TERMINAL = {"done", "error", "clarify"}


def norm(t: str | None) -> str:
    return re.sub(r"[\s,]", "", t or "")


def flat(t: str | None) -> str:
    return re.sub(r"\s+", "", t or "")


def load_cases(open_hidden: bool) -> list[dict]:
    cases = json.loads((EVAL / "eval220.json").read_text(encoding="utf-8"))["cases"]
    if open_hidden:
        text = (EVAL / "eval220_hidden.json").read_text(encoding="utf-8")
        manifest = json.loads((EVAL / "eval220_manifest.json").read_text(encoding="utf-8"))
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != manifest["hidden_sha256"]:
            raise SystemExit("숨긴 세트 해시가 manifest와 다르다 — 만든 뒤 바뀌었다")
        cases += json.loads(text)["cases"]
    return cases


def pets() -> dict[str, Pet]:
    cs = json.loads((ROOT / "app" / "fixtures" / "customers.json").read_text(encoding="utf-8"))
    return {p["pet_id"]: Pet.model_validate(p) for c in cs for p in c["pets"]}


async def exchange(ws, payload: dict, first_timeout: float, idle_timeout: float) -> dict:
    """메시지 하나를 보내고 끝(done·error·clarify)까지 받는다"""
    t0 = time.monotonic()
    await ws.send(json.dumps(payload, ensure_ascii=False))
    rec = dict(turn_id=None, answer="", context=None, sources=[], references=[], calc=None, clarify=None, error=None, exclusions=None,
               tables=[], order="", server_latency_ms=None, server_first_token_ms=None)
    code = {"context": "X", "sources": "S", "calc": "C", "token": "T", "references": "R", "done": "D", "clarify": "Q", "error": "E",
            "exclusions": "B", "tables": "L"}
    first = True
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), first_timeout if first else idle_timeout)
        except asyncio.TimeoutError:
            rec["error"] = {"code": "client_timeout"}
            break
        except ConnectionClosed as e:
            rec["error"] = {"code": "ws_closed", "message": str(e)}
            break
        first = False
        m = json.loads(raw)
        kind = m.get("type")
        rec["turn_id"] = rec["turn_id"] or m.get("turn_id")
        if kind != "token" or not rec["order"].endswith("T"):     # 토큰은 한 글자로 묶는다
            rec["order"] += code.get(kind, "?")
        if kind == "token":
            rec["answer"] += m.get("text", "")
        elif kind == "context":
            rec["context"] = {k: m.get(k) for k in ("kind", "reason", "text")}
        elif kind == "sources":
            rec["sources"] = [{k: s.get(k) for k in ("section", "section_name", "article_num", "coverage_type", "score", "content")}
                              for s in m.get("items", [])]
        elif kind == "references":
            rec["references"] = [{k: r.get(k) for k in ("citation_label", "section", "section_name", "article_num")}
                                 for r in m.get("items", [])]
        elif kind == "calc":
            rec["calc"] = m.get("result")
        elif kind == "clarify":
            rec["clarify"] = m.get("options")
        elif kind == "exclusions":
            rec["exclusions"] = m.get("items")
        elif kind == "tables":
            rec["tables"] = m.get("items") or []
        elif kind == "error":
            rec["error"] = {"code": m.get("code"), "message": m.get("message")}
        elif kind == "done":
            rec["server_latency_ms"], rec["server_first_token_ms"] = m.get("latency_ms"), m.get("first_token_ms")
        if kind in TERMINAL:
            break
    rec["client_ms"] = int((time.monotonic() - t0) * 1000)
    return rec


async def run_script(http: httpx.AsyncClient, base_ws: str, headers: dict, case: dict, args) -> list[dict]:
    """한 문항(멀티턴이면 각본 전체)을 새 세션 하나에서"""
    turns = case.get("turns") or [case]
    r = await http.post("/api/sessions", json={"mode": "업무특화", "customer_id": turns[0]["customer_id"]})
    r.raise_for_status()
    sid = r.json()["session_id"]
    out = []
    async with connect(f"{base_ws}/ws/chat/{sid}", additional_headers=headers, max_size=None) as ws:
        for t in turns:
            rec = await exchange(ws, {"type": "question", "text": t["query"], "pet_id": t["pet_id"]}, args.first_timeout, args.timeout)
            if t.get("clarify") and rec["clarify"]:
                choice = next((o for o in rec["clarify"] if t["clarify_choice"] in o), rec["clarify"][0])
                second = await exchange(ws, {"type": "clarify_answer", "turn_id": rec["turn_id"], "choice": choice},
                                        args.first_timeout, args.timeout)
                rec = dict(second, clarify=rec["clarify"], clarify_choice=choice, order=rec["order"] + "|" + second["order"])
            out.append(dict(rec, id=t["id"], session_id=sid))
    detail = (await http.get(f"/api/sessions/{sid}")).json()
    stored = {x["turn_id"]: x for x in detail.get("turns", [])}
    for rec in out:
        s = stored.get(rec["turn_id"])
        rec["stored"] = bool(s) and s.get("answer") == rec["answer"]
        # 화면이 받은 출처와 DB에 남은 출처가 같은가(검색 결과 순서까지)
        key = lambda x: (x.get("section"), x.get("section_name"), x.get("article_num"), round(x.get("score") or 0, 4))
        rec["stored_sources_same"] = bool(s) and [key(x) for x in s.get("sources", [])] == [key(x) for x in rec["sources"]]
    return out


# ----- 판정 -----
def refused(answer: str) -> bool:
    a = norm(answer)
    return any(norm(p) in a for p in REFUSAL_PHRASES) or norm(prompts.NO_ANSWER_TEXT)[:12] in a


def screen_match(text: str, pet: Pet) -> list[str]:
    """서버가 부담보를 보내지 않을 때 화면이 하는 대조(ExclusionBanner.matchExclusions) — 공백 무시 전체 일치 또는 3글자 이상 낱말"""
    flat_text = re.sub(r"\s+", "", text)
    conds = [c for p in pet.policies for c in p.excluded_conditions]
    return [c for c in dict.fromkeys(conds)
            if re.sub(r"\s+", "", c) in flat_text or any(len(w) >= 3 and w in flat_text for w in c.split())]


def gold_hit(item: dict, g: dict) -> bool:
    if item.get("section") != g.get("section") or item.get("section_name") != g.get("section_name"):
        return False
    return g.get("article_num") is None or item.get("article_num") == g.get("article_num")


def excerpt_part(messages: list[dict]) -> str:
    user = next((m["content"] for m in messages if m["role"] == "user"), "")
    return user.split(prompts.QUESTION_HEADER)[0]


def judge_turn(t: dict, rec: dict, pet: Pet, prompt: dict | None) -> dict:
    exp = t["expect"]
    ans = rec["answer"]
    checks = {}
    if exp["must"]:
        checks["must"] = all(any(norm(w) in norm(ans) for w in grp) for grp in exp["must"])
    if exp["must_not"]:
        checks["must_not"] = not any(norm(w) in norm(ans) for w in exp["must_not"])
    if exp["refuse"]:
        checks["refuse"] = refused(ans)
    calc = rec["calc"]
    if exp["calc"] is not None:
        kind = (calc or {}).get("kind", "medical") if calc else "none"
        checks["calc"] = kind == exp["calc"]
        for path, want in exp["calc_values"].items():
            got = calc_field(calc or {}, path)
            tol = exp.get("calc_tol", {}).get(path, 0)
            ok = got == want if not (isinstance(want, int) and not isinstance(want, bool) and isinstance(got, int)) \
                else abs(got - want) <= tol
            checks[f"calc.{path}"] = ok
    if exp.get("banner") is not None:
        text = f"{rec['context']['text']} {t['query']}" if rec.get("context") and rec["context"].get("text") else t["query"]
        # 화면 배너 = 서버가 보낸 부담보(4d 이후). 서버가 보내지 않았으면(걸린 것 없음·예전 서버) 같은 대조 함수로
        got = set(rec["exclusions"]) if rec.get("exclusions") is not None else set(screen_match(text, pet))
        checks["banner"] = set(exp["banner"]) <= got
    if exp.get("context") is not None:
        got = (rec.get("context") or {}).get("kind") or "none"
        checks["context"] = got == exp["context"]
    if rec.get("error"):
        checks["no_error"] = False
    if not (rec.get("clarify") and not ans):           # 등급 되묻기에서 멈춘 턴은 답이 없어 취소로 저장된다 — 대조할 것이 없다
        checks["stored"] = rec.get("stored", False)
        checks["stored_sources"] = rec.get("stored_sources_same", False)
    gold = t.get("gold") or []
    info = dict(refused=refused(ans), code_answer=prompt is None and not rec.get("error") and bool(ans),
                n_tables=len(rec.get("tables") or []), table_hl=sum(t.get("highlight") is not None for t in rec.get("tables") or []),
                clarify_only=bool(rec.get("clarify")) and not ans, guard_flag="※ 답변의" in ans,
                n_references=len(rec.get("references") or []))
    if gold:
        info["gold_in_sources"] = any(gold_hit(s, g) for s in rec["sources"] for g in gold)
        if prompt is not None:
            ex = flat(excerpt_part(prompt["messages"]))
            info["gold_in_prompt"] = any(flat(g["evidence"]) in ex for g in gold)
    return dict(id=t["id"], ok=all(checks.values()), checks=checks, **info)


async def main_async(args) -> dict:
    cases = load_cases(args.open_hidden)
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only) or c["id"].split("-")[0] in set(args.only)]
    pet_map = pets()
    headers = {AGENT_HEADER: args.agent} if args.agent else {}
    base_ws = args.base.replace("http", "ws", 1)
    runs = []
    async with httpx.AsyncClient(base_url=args.base, headers=headers, timeout=60) as http:
        for k in range(args.runs):
            recs = []
            for c in cases:
                recs += await run_script(http, base_ws, headers, c, args)
            runs.append(recs)
            print(f"  실행 {k + 1}/{args.runs}: 턴 {len(recs)}", flush=True)
    prompts_by_turn = {}
    if args.prompt_log and Path(args.prompt_log).exists():
        for line in Path(args.prompt_log).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            prompts_by_turn[row["turn_id"]] = row
    turns = {t["id"]: t for c in cases for t in (c.get("turns") or [c])}
    judged = []
    for k, recs in enumerate(runs):
        for rec in recs:
            t = turns[rec["id"]]
            p = prompts_by_turn.get(rec["turn_id"])
            j = judge_turn(t, rec, pet_map[t["pet_id"]], p)
            judged.append(dict(j, run=k, axis=rec["id"][0], tags=t.get("tags", []), answer=rec["answer"], calc=rec["calc"],
                               context=rec["context"], sources=[{k2: s[k2] for k2 in ("section", "section_name", "article_num", "score")}
                                                                for s in rec["sources"]],
                               order=rec["order"], turn_id=rec["turn_id"], session_id=rec["session_id"],
                               prompt_logged=p is not None, latency_ms=rec["server_latency_ms"], error=rec["error"],
                               clarify=rec.get("clarify"), n_excerpts=len(p["kept"]) if p else None))
    return dict(tag=args.tag, base=args.base, runs=args.runs, open_hidden=args.open_hidden, created=datetime.now().isoformat(),
                n_cases=len(cases), turns=judged)


def summarize(report: dict) -> str:
    rows = report["turns"]
    lines = [f"# 서빙 경로 평가 — {report['tag']} ({report['created'][:16]}, 실행 {report['runs']}회, 숨긴 세트 "
             f"{'포함' if report['open_hidden'] else '제외'})", ""]
    by_run_axis = defaultdict(lambda: Counter())
    for r in rows:
        c = by_run_axis[(r["run"], r["axis"])]
        c["n"] += 1
        c["ok"] += r["ok"]
        c["refused"] += r["refused"]
        if "gold_in_sources" in r:
            c["gold_n"] += 1
            c["gold_src"] += r["gold_in_sources"]
        if "gold_in_prompt" in r:
            c["gp_n"] += 1
            c["gold_prompt"] += r["gold_in_prompt"]
    axes = sorted({a for _, a in by_run_axis})
    lines.append("| 축 | 턴 | 자동 판정 통과(실행별) | 거절(실행별) | 정답이 검색 결과에(실행별) | 정답이 프롬프트에(실행별) |")
    lines.append("|---|---|---|---|---|---|")
    for a in axes + ["전체"]:
        cs = [by_run_axis[(k, a)] for k in range(report["runs"])] if a != "전체" else \
            [sum((by_run_axis[(k, x)] for x in axes), Counter()) for k in range(report["runs"])]
        fmt = lambda key, den: " / ".join(f"{c[key]}/{c[den]}" for c in cs)
        lines.append(f"| {a} | {cs[0]['n']} | {fmt('ok', 'n')} | {fmt('refused', 'n')} | {fmt('gold_src', 'gold_n')} | "
                     f"{fmt('gold_prompt', 'gp_n')} |")
    # 조건부 거절표(실행 0) — 정답이 프롬프트에 있나 × 거절
    r0 = [r for r in rows if r["run"] == 0 and "gold_in_prompt" in r]
    t = Counter((r["gold_in_prompt"], r["refused"]) for r in r0)
    lines += ["", "조건부 거절(실행 1, 모델이 답한 턴 중 정답이 있는 문항)", "",
              "| | 거절 | 답함 |", "|---|---|---|",
              f"| 정답이 프롬프트에 있음 | {t[(True, True)]} | {t[(True, False)]} |",
              f"| 정답이 프롬프트에 없음 | {t[(False, True)]} | {t[(False, False)]} |"]
    # 판정 항목별 실패 수(실행 0)
    fails = Counter(k for r in rows if r["run"] == 0 for k, v in r["checks"].items() if not v)
    lines += ["", "판정 항목별 실패(실행 1): " + ", ".join(f"{k} {v}" for k, v in fails.most_common())]
    # 실행 사이 흔들림 — 같은 턴이 실행마다 판정이 달랐나
    by_id = defaultdict(list)
    for r in rows:
        by_id[r["id"]].append(r["ok"])
    flip = sorted(i for i, v in by_id.items() if len(set(v)) > 1)
    lines += [f"실행마다 판정이 갈린 턴 {len(flip)}: {', '.join(flip[:40])}{' …' if len(flip) > 40 else ''}"]
    missing_prompt = sum(1 for r in rows if not r["prompt_logged"] and not r["code_answer"] and not r["error"]
                         and not r["clarify_only"])
    # 결정적인 부분(검색 결과·카드)은 실행마다 같아야 한다 — 다르면 측정이 흔들린다
    det = defaultdict(set)
    for r in rows:
        det[r["id"]].add(json.dumps([r["sources"], r["calc"]], ensure_ascii=False, sort_keys=True))
    unstable = sorted(i for i, v in det.items() if len(v) > 1)
    lines += [f"실행마다 검색 결과·카드가 달라진 턴(0이어야 함): {len(unstable)} {', '.join(unstable[:20])}"]
    r0 = [r for r in rows if r["run"] == 0]
    few = [r["id"] for r in rows if r["run"] == 0 and r.get("n_excerpts") is not None and r["n_excerpts"] < 3]
    lines += [f"발췌가 3개보다 적은 모델 턴(실행 1 — B 조건의 부모 겹침 등): {len(few)} {', '.join(few[:20])}"]
    lines += [f"숫자 가드레일 표시(실행 1): {sum(r.get('guard_flag', False) for r in r0)} — "
              f"{', '.join(r['id'] for r in r0 if r.get('guard_flag'))}",
              f"근거 조항이 붙은 코드 답(실행 1): {sum(1 for r in r0 if r['code_answer'] and r.get('n_references'))}"
              f"/{sum(1 for r in r0 if r['code_answer'])}"]
    lines += [f"모델이 답했는데 프롬프트 기록이 없는 턴: {missing_prompt}", f"기록 저장 불일치(stored=False): "
              f"{sum(1 for r in rows if not r['checks'].get('stored', True))}",
              f"등급 되묻기에서 멈춘 턴(실행 1): {', '.join(r['id'] for r in rows if r['run'] == 0 and r['clarify_only'])}"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="평가 세트를 실제 서버(서빙 경로)로 잰다")
    ap.add_argument("--tag", required=True, help="결과 이름(예: rebuild4, base)")
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--prompt-log", help="서버의 PETMINT_PROMPT_LOG 파일")
    ap.add_argument("--agent", help="상담원 헤더 값(로컬)")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--open-hidden", action="store_true", help="숨긴 세트까지 — rebuild5 평가 때만")
    ap.add_argument("--first-timeout", type=float, default=600)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--out", default=str(ROOT / "data" / "eval" / "results"))
    args = ap.parse_args()
    report = asyncio.run(main_async(args))
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out = Path(args.out) / f"eval_serving_{stamp}_{args.tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = summarize(report)
    out.with_suffix(".md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\n결과: {out}")


if __name__ == "__main__":
    main()
