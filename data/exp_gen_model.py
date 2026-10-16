"""
exp_gen_model.py
실험 G(2026-10-16) — 05 생성 모델 교체(tri-7b → qwen3:14b)와 재작성 위치(06 뒤 → 06 앞)의 효과.
같은 강아지 20단위(섹션 비율대로, seed 42), 일반 회차 1번(temperature 0.5 = 생성 라운드 1), v1 프롬프트 그대로.

  ctrl : tri-7b 생성 → 06                       (지금 05)
  A    : qwen3:14b 생성 → 06                    — ctrl vs A = 생성 모델 교체 효과
  B    : A와 같은 생성 파일 → 재작성 → 06        — A vs B = 재작성을 06 앞으로 옮긴 효과
  A_rw : A → 06 → 재작성 → 재심판(지금 순서)     — 같은 생성에서 갈라지므로 추가 생성 없음. B와 나란히 본다

생성은 ctrl·A 두 번뿐이다. 재작성은 faq_rewrite 그대로(tri-7b, temperature 0.2) — 바꾸는 것은 순서 하나.
06은 노트북 그대로(PETMINT_06_INPUT=exp_g/<설정>, exp_ 접두라 고른 단위만 검사). 심판 gemma4:12b는 두 생성 모델과 다르다.
qwen3는 {"think": False}로 부른다 — 생각 출력이 num_predict(1200)를 먹어 JSON이 잘린다. 답변에 추론이 들어오는지는
생각 모드가 아니라 v1 프롬프트("2~4문장") 그대로의 답변에서 본다.

실행(순서대로):
  python -m data.exp_gen_model select           단위 20개 고르기(모델 없음)
  python -m data.exp_gen_model gen ctrl         tri-7b 생성
  python -m data.exp_gen_model gen A            qwen3:14b 생성
  python -m data.exp_gen_model rewrite-b        A 생성 결과 → 재작성 → exp_g/B
  python -m data.exp_gen_model check ctrl|A|B   노트북 06(nbconvert)
  python -m data.faq_rewrite all 강아지 --src=data/faq/exp_g/A --out=data/faq/exp_g/A_rw
  python -m data.exp_gen_model report           → data/review/exp_g_gen_model_<날짜시각>.md
"""

import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from data import faq_style

PROJECT_DIR = Path(__file__).resolve().parent.parent
EXP_DIR = PROJECT_DIR / "data" / "faq" / "exp_g"
REVIEW_DIR = PROJECT_DIR / "data" / "review"
SPECIES = "강아지"
N_UNITS = 20
SEED = 42
TEMPERATURE = 0.5          # 생성 라운드 1과 같은 값(ROUND_TEMPERATURES 강아지 첫 값)
MODELS = {"ctrl": ("tri-7b:latest", {}), "A": ("qwen3:14b", {"think": False})}
ROUND_FILE = f"petmint_{SPECIES}_faq_round1.json"
# 답변 속 추론 표지 — 조건·이유·결론을 잇는 말. 정규식 근사치라 예시를 함께 본다
REASONING = re.compile(r"따라서|그러므로|때문에|이므로|므로\b|왜냐하면|이 경우|경우에는|다만|단,|만약|라면|이라면|이어서|결과적으로|즉,")


def _dump(obj, p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def _load(p: Path, default=None):
    return json.load(open(p, encoding="utf-8")) if p.exists() else default


# ---------- 단위 ----------
def pick_units(units: list[dict], n: int = N_UNITS, seed: int = SEED) -> list[dict]:
    """섹션 비율대로(최대 나머지 방식) n개, 섹션 안에서는 seed로 무작위 — faq_generate.pick_ref_pilot과 같은 방식"""
    from data.faq_units import unit_id
    by_sec = {}
    for u in units:
        by_sec.setdefault(u["section"], []).append(u)
    total = len(units)
    quota = {s: n * len(v) // total for s, v in by_sec.items()}
    for s in sorted(by_sec, key=lambda s: -(n * len(by_sec[s]) / total - quota[s]))[:n - sum(quota.values())]:
        quota[s] += 1
    rng = random.Random(seed)
    picked = []
    for s in sorted(by_sec):
        picked += rng.sample(sorted(by_sec[s], key=unit_id), quota[s])
    return picked


def select():
    from data import faq_generate, faq_units
    builder, units = faq_generate.load_units()
    picked = pick_units(units[SPECIES])
    sel = [{"species": SPECIES, "unit_id": faq_units.unit_id(u), "section": u["section"],
            "prompt_type": faq_generate.get_prompt_type(u), "content_len": len(u["content"])} for u in picked]
    path = EXP_DIR / "selection.json"
    old = _load(path)
    assert old is None or old == sel, f"{path}가 지금 선택과 다르다 — 다른 폴더를 쓸 것"
    _dump(sel, path)
    print(f"{SPECIES} {len(units[SPECIES])}단위 중 {len(sel)}개: {dict(Counter(s['section'] for s in sel))} | "
          f"{dict(Counter(s['prompt_type'] for s in sel))}")
    return sel


def selected_units():
    from data import faq_generate, faq_units
    builder, units = faq_generate.load_units()
    sel = _load(EXP_DIR / "selection.json")
    assert sel, "먼저 select"
    by = {faq_units.unit_id(u): u for u in units[SPECIES]}
    return builder, [by[s["unit_id"]] for s in sel]


# ---------- 생성 ----------
def gen(cfg: str):
    from data import faq_generate as g
    model, extra = MODELS[cfg]
    out = EXP_DIR / cfg / ROUND_FILE
    if g.round_done(out):
        print(f"{cfg}: 이미 완료 — 건너뜀 ({out})")
        return
    builder, picked = selected_units()
    tags = {m["name"] for m in requests.get(f"{g.OLLAMA_URL}/api/tags", timeout=5).json()["models"]}
    assert model in tags, f"{model} 없음"
    g.MODEL_NAME, g.OLLAMA_EXTRA = model, extra
    g.call_log.clear()
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(f"=== {cfg}: {model} {extra} — {len(picked)}단위, temperature {TEMPERATURE} ===", flush=True)
    g.generate_faq_round(builder, picked, SPECIES, out, TEMPERATURE)
    _dump({"model": model, "extra": extra, "wall_sec": time.time() - t0, "calls": g.call_log}, out.parent / "call_log.json")
    requests.post(f"{g.OLLAMA_URL}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)


# ---------- B: 06 앞 재작성 ----------
def rewrite_b():
    from data import faq_rewrite as rw
    src = EXP_DIR / "A" / ROUND_FILE
    assert src.exists() and (EXP_DIR / "A" / ROUND_FILE.replace(".json", "_failures.json")).exists(), "먼저 gen A"
    out_dir = EXP_DIR / "B"
    out = out_dir / ROUND_FILE
    if out.exists():
        print(f"B: 이미 있음 — 건너뜀 ({out})")
        return
    before = _load(src)
    idx = rw.UnitIndex([SPECIES])
    rw._assert_model(rw.MODEL_NAME)
    after, t0 = [], time.time()
    for f in before:
        u, refs, source = idx.get(f["species"], f["unit_id"])
        after.append(rw.rewrite_faq(f, u, refs, source))
    problems = rw.preservation_problems(before, after)
    assert not problems, "재작성이 질문 외 필드를 바꿨다:\n" + "\n".join(problems[:20])
    rw._unload(rw.MODEL_NAME)
    out_dir.mkdir(parents=True, exist_ok=True)
    _dump(after, out)
    shutil.copy2(src.with_name(src.stem + "_failures.json"), out_dir / src.name.replace(".json", "_failures.json"))
    shutil.copy2(EXP_DIR / "A" / "call_log.json", out_dir / "call_log.json")
    print(f"B: 재작성 {len(after)}건 ({(time.time() - t0) / 60:.1f}분) — {dict(Counter(r['rewrite']['status'] for r in after))}")


# ---------- 06 ----------
def check(cfg: str):
    d = EXP_DIR / cfg
    assert (d / ROUND_FILE).exists(), f"{d}에 생성 결과 없음"
    env = dict(os.environ, PYTHONUNBUFFERED="1", PETMINT_06_INPUT=f"exp_g/{cfg}")
    cmd = [sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute",
           str(PROJECT_DIR / "notebooks" / "06_품질검증.ipynb"), "--output-dir", str(d / "checked"),
           "--output", f"06_executed_{datetime.now():%Y%m%d_%H%M}.ipynb", "--ExecutePreprocessor.timeout=-1"]
    print(f"06: {cfg} — {' '.join(cmd[-6:])}", flush=True)
    subprocess.run(cmd, env=env, check=True)


# ---------- 리포트 ----------
def _pct(a, b) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else "-"


def speed(cfg: str) -> dict | None:
    log = _load(EXP_DIR / cfg / "call_log.json")
    if not log:
        return None
    calls = [c for c in log["calls"] if c.get("eval_duration")]
    tot = [c["total_duration"] / 1e9 for c in calls]
    tps = [c["eval_count"] / (c["eval_duration"] / 1e9) for c in calls]
    return {"model": log["model"], "calls": len(calls), "wall_sec": log["wall_sec"],
            "sec_per_call_median": statistics.median(tot), "sec_per_call_mean": statistics.mean(tot),
            "out_tokens_median": statistics.median(c["eval_count"] for c in calls),
            "tok_per_sec_median": statistics.median(tps), "load_sec_max": max(c["load_duration"] / 1e9 for c in calls)}


def answer_stats(qas: list[dict]) -> dict:
    from data.faq_checks import answer_body
    bodies = [answer_body(q["answer"]) for q in qas]
    sents = [len([s for s in re.split(r"(?<=[.?!다요])\s+", b) if s.strip()]) for b in bodies]
    return {"n": len(bodies), "chars_median": statistics.median(map(len, bodies)) if bodies else 0,
            "sent_median": statistics.median(sents) if sents else 0,
            "reasoning": sum(bool(REASONING.search(b)) for b in bodies)}


def full_estimate() -> dict:
    """전량 생성 호출 수(지금 계획: 가중치·주제 회차) — 생성 모델만 바꿨을 때의 시간 추정용"""
    from data import faq_generate as g
    plan, _ = g.plan_from_data()
    return {"calls": g.plan_calls(plan)}


def report():
    from data import faq_generate as g
    sel = _load(EXP_DIR / "selection.json")
    uids = {s["unit_id"] for s in sel}
    expected_qa = sum(3 if s["prompt_type"] == "조항형" else 2 for s in sel)
    rows = {}
    for cfg in ("ctrl", "A", "B"):
        d = EXP_DIR / cfg
        qas = _load(d / ROUND_FILE, [])
        fails = _load(d / ROUND_FILE.replace(".json", "_failures.json"), [])
        checked = _load(d / "checked" / f"petmint_{SPECIES}_faq_checked_all.json")
        rows[cfg] = {"qas": qas, "fails": fails, "checked": checked,
                     "units_ok": len({q["unit_id"] for q in qas}),
                     "parse_fail": sum(f.get("status") == "parse_fail" for f in fails),
                     "rejected_05": sum(len(f.get("rejected", [])) for f in fails),
                     "judge": faq_style.judge_stats(checked) if checked else None}
    arw = _load(EXP_DIR / "A_rw" / "rewritten_judged.json")
    ref = faq_style.reference_row(uids)
    sp = {c: speed(c) for c in ("ctrl", "A")}
    est = full_estimate()

    L = ["# 실험 G — 05 생성 모델(tri-7b → qwen3:14b)과 재작성 위치", "", f"생성: {datetime.now():%Y-%m-%d %H:%M}", "",
         f"강아지 {len(sel)}단위(섹션 비율, seed {SEED}) — {dict(Counter(s['section'] for s in sel))}, "
         f"일반 회차 1번(temperature {TEMPERATURE}), v1 프롬프트. 기대 QA {expected_qa}건(조항형 3·안내형 2).", "",
         "## 1. 생성 → 06", "",
         "| 설정 | 성공 단위 | 05 남은 QA | 05 탈락 QA | 파싱 실패 | 06 심판 통과 | 06 최종 통과 | 기대 QA 대비 최종 | "
         + " | ".join(faq_style.JUDGE_TYPES) + " |", "|---|---|---|---|---|---|---|---|" + "---|" * len(faq_style.JUDGE_TYPES)]
    names = {"ctrl": "대조 tri-7b → 06", "A": "A qwen3:14b → 06", "B": "B qwen3:14b → 재작성 → 06"}
    for cfg, r in rows.items():
        j = r["judge"]
        if not j:
            L.append(f"| {names[cfg]} | {r['units_ok']}/{len(sel)} | {len(r['qas'])} | {r['rejected_05']} | {r['parse_fail']} | (06 없음) |")
            continue
        passed = sum(f["decision"] != "drop" for f in r["checked"])
        judge_pass = round(j["judge_pass"] * j["judged"])
        L.append(f"| {names[cfg]} | {r['units_ok']}/{len(sel)} | {len(r['qas'])} | {r['rejected_05']} | {r['parse_fail']} | "
                 f"{_pct(judge_pass, j['judged'])} | {_pct(passed, j['n'])} | {_pct(passed, expected_qa)} | "
                 + " | ".join(str(j["judge_types"].get(t, 0)) for t in faq_style.JUDGE_TYPES) + " |")
    if ref:
        j = ref["judge"]
        L.append(f"| 참고: 기존 전량 r1 (같은 단위, tri-7b) | {ref['units']}/{len(sel)} | {j['n']} | - | - | "
                 f"{j['judge_pass']:.0%} ({j['judged']}건) | {j['final_pass']:.0%} | - | "
                 + " | ".join(str(j["judge_types"].get(t, 0)) for t in faq_style.JUDGE_TYPES) + " |")
    if arw:
        ok = [r for r in arw if r["rewrite"]["status"] == "ok"]
        rj_pass = sum((r.get("rejudge") or {}).get("problem") is False for r in ok)
        L += ["", f"**A_rw(지금 순서: A → 06 → 재작성 → 재심판)**: 06 통과 {len(arw)}건 중 질문이 바뀐 것 {len(ok)}건, "
              f"재심판 통과 {_pct(rj_pass, len(ok))}, 재작성 상태 {dict(Counter(r['rewrite']['status'] for r in arw))}. "
              f"최종 = 06 통과 {len(arw)}건(재심판 탈락분은 원래 질문으로 되돌림)."]
    if rows["B"]["qas"]:
        L += ["", f"**B 재작성 상태**(06 앞, A의 05 통과 QA 전부): {dict(Counter(q['rewrite']['status'] for q in rows['B']['qas']))}"]

    L += ["", "## 2. 질문 성질", "", "| 설정 | QA | 라벨 누출 | 상황형 | 질문 길이 중앙 |", "|---|---|---|---|---|"]

    def style_line(name, qs):
        s = faq_style.style_stats(qs)
        return f"| {name} | {s['n']} | {s['label_leak']:.1%} | {s['situational']:.1%} | {s['q_len_median']} |"
    for cfg, r in rows.items():
        if r["checked"]:
            kept = [f["question"] for f in r["checked"] if f["decision"] != "drop"]
            L.append(style_line(names[cfg] + " (06 통과)", kept))
    if arw:
        final_q = [r["question"] if r["rewrite"]["status"] == "ok" and (r.get("rejudge") or {}).get("problem") is False
                   else r["question_original"] for r in arw]
        L.append(style_line("A_rw (06 → 재작성 → 재심판, 최종)", final_q))

    L += ["", "## 3. 답변 — 추론이 들어오는가", "",
          "| 설정 | 답변 수 | 글자 중앙 | 문장 수 중앙 | 추론 표지 있음 |", "|---|---|---|---|---|"]
    for cfg in ("ctrl", "A"):
        a = answer_stats(rows[cfg]["qas"])
        L.append(f"| {names[cfg]} (05 출력) | {a['n']} | {a['chars_median']} | {a['sent_median']} | {_pct(a['reasoning'], a['n'])} |")
    L += ["", f"추론 표지 = `{REASONING.pattern}` (정규식 근사). 같은 단위의 답변을 아래 4절에 나란히 둔다."]

    L += ["", "## 4. 생성 속도와 전량 추정", "",
          "| 모델 | 호출 | 벽시계 | 호출당 초(중앙/평균) | 출력 토큰 중앙 | 출력 토큰/초 |", "|---|---|---|---|---|---|"]
    for cfg, s in sp.items():
        if s:
            L.append(f"| {s['model']} | {s['calls']} | {s['wall_sec'] / 60:.1f}분 | {s['sec_per_call_median']:.1f} / {s['sec_per_call_mean']:.1f} | "
                     f"{s['out_tokens_median']} | {s['tok_per_sec_median']:.1f} |")
    if sp["ctrl"] and sp["A"]:
        ratio = sp["A"]["sec_per_call_mean"] / sp["ctrl"]["sec_per_call_mean"]
        L += ["", f"전량 생성 호출 {est['calls']:,}회(지금 계획: 가중치·주제 회차). 실측 기준 tri-7b {g.SEC_PER_CALL}초/호출"
              f"(2026-10-13 전량) → {est['calls'] * g.SEC_PER_CALL / 3600:.1f}시간.",
              f"이번 20단위에서 qwen3:14b/tri-7b 호출당 시간 비 {ratio:.2f}배 → qwen3:14b 전량 약 "
              f"**{est['calls'] * g.SEC_PER_CALL * ratio / 3600:.1f}시간**(이번 평균 그대로면 {est['calls'] * sp['A']['sec_per_call_mean'] / 3600:.1f}시간)."]

    L += ["", "## 5. 같은 단위 답변 나란히 (단위마다 첫 QA)", ""]
    by = {cfg: {} for cfg in ("ctrl", "A")}
    for cfg in by:
        for q in rows[cfg]["qas"]:
            by[cfg].setdefault(q["unit_id"], q)
    bq = {q["question_original"]: q["question"] for q in rows["B"]["qas"]} if rows["B"]["qas"] else {}
    for s in sel:
        u = s["unit_id"]
        L += [f"### {u.split('|', 1)[1].replace('|', ' · ')}", ""]
        for cfg in ("ctrl", "A"):
            q = by[cfg].get(u)
            if q:
                L += [f"- **{cfg}** Q: {q['question']}", f"  A: {q['answer']}"]
                if cfg == "A" and q["question"] in bq:
                    L.append(f"  B 재작성 Q: {bq[q['question']]}")
            else:
                L.append(f"- **{cfg}** (QA 없음)")
        L.append("")

    L += ["## 해석 시 주의", "",
          f"- 설정당 기대 QA {expected_qa}건이라 통과율 차이가 ±12%p 안쪽이면 구분할 수 없다(n≈60, 95% 구간 반폭).",
          "- 생성 라운드 1번이라 06 중복·단위 상한은 거의 걸리지 않는다 — 심판 통과율이 주 지표.",
          "- B는 06이 버릴 QA까지 재작성한다(재작성 호출이 A_rw보다 많다). 재작성 모델은 tri-7b 그대로."]
    out = REVIEW_DIR / f"exp_g_gen_model_{datetime.now():%Y%m%d_%H%M}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:60]))
    print("저장:", out)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else ""
    if cmd == "select":
        select()
    elif cmd == "gen":
        gen(args[1])
    elif cmd == "rewrite-b":
        rewrite_b()
    elif cmd == "check":
        check(args[1])
    elif cmd == "report":
        report()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
