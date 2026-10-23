"""
coverage_table.py
보장 여부 질문 개선 측정(2026-10-23 — 원칙이 참조에만 · 부담보·대기기간 혼동 · 제2조 정리) 결과 표.
평가 220 보이는 세트 3회 평균. 원칙(제1조 ①)이 참조에만 있는 턴은 프롬프트 기록에서 다시 계산한다(기준 측정은 이 항목이 생기기 전).

  python -m scripts.coverage_table 기준=logs/rollout/all 1안=logs/coverage/a1 ... [--out data/review/coverage_measure.md]
"""

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from scripts.eval_serving import COVERAGE_RULE, body_and_refs, flat

ROOT = Path(__file__).resolve().parent.parent
# 대상 — 문제 1(원칙이 참조에만, 운영 설정 기준) 12문항 ∪ 문제 2(질문이 그 반려동물 부담보에 걸림) 8문항, 겹침 4
P1 = {"C19", "C21", "C22", "C24", "C26", "C29", "M15-2", "M19-2", "P21", "S01", "S10", "S17"}
P2 = {"C19", "C20", "C21", "C22", "C27", "M15-2", "P32", "P49"}
P4 = {"C51", "C52", "P09", "S42"}          # 제2조(용어의 정의) 깨진 중복 글자 — 가입 나이·대상
GROUPS = [("문제1", P1), ("문제2", P2), ("제2조", P4)]
VERDICTS = ("정확", "예외누락", "결론없음", "틀림", "거절")


def load(d: Path) -> tuple[dict, dict, dict]:
    f = sorted(d.glob("eval_serving_*.json"))
    f = [x for x in f if not x.name.endswith(".judge.json")][-1]
    rep = json.loads(f.read_text(encoding="utf-8"))
    judge = json.loads(f.with_suffix(".judge.json").read_text(encoding="utf-8"))
    prompts = {}
    for p in d.glob("prompts_*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            prompts[r["turn_id"]] = r
    return rep, judge, prompts


def stats(d: Path) -> dict:
    rep, judge, prompts = load(d)
    visible = {t["id"] for c in json.loads((ROOT / "data/eval/eval220.json").read_text(encoding="utf-8"))["cases"]
               for t in (c.get("turns") or [c])}
    rule = flat(COVERAGE_RULE)
    per = defaultdict(Counter)
    for t in rep["turns"]:
        if t["id"] not in visible:
            continue
        c = per[t["run"]]
        v = (judge.get(f"{t['run']}:{t['id']}") or {}).get("verdict")
        c["auto"] += t["ok"]
        c["refused"] += bool(t["refused"])
        c["code"] += bool(t.get("code_answer"))
        c["ref_gold"] += bool(t["refused"] and t.get("gold_in_prompt"))
        if t["axis"] == "N":
            c["N_ref"] += bool(t["refused"])
        if v:
            c["judged"] += 1
            c["j_" + v] += 1
        p = prompts.get(t.get("turn_id"))
        if p and not t.get("code_answer"):
            body, refs = body_and_refs(p["messages"])
            if rule in refs and rule not in body:
                c["rule_ref"] += 1
                c["rule_ref_refused"] += bool(t["refused"])
        for name, ids in GROUPS:
            if t["id"] in ids:
                c[f"{name}_n"] += 1
                c[f"{name}_auto"] += t["ok"]
                c[f"{name}_code"] += bool(t.get("code_answer"))
                c[f"{name}_{v or '코드답'}"] += 1
    runs = [per[r] for r in sorted(per)]
    keys = set().union(*runs)
    return {k: statistics.mean(r[k] for r in runs) for k in keys} | {"_auto_runs": [r["auto"] for r in runs]}


ROWS = [("auto", "자동 통과"), ("refused", "거절(전체 턴)"), ("ref_gold", "정답이 프롬프트에 있는데 거절"), ("code", "코드 답 턴"),
        ("judged", "판정 대상(모델 답) 턴"), ("j_정확", "판정 정확"), ("j_틀림", "판정 틀림"), ("j_예외누락", "판정 예외누락"), ("j_결론없음", "판정 결론없음"),
        ("j_거절", "판정 거절"), ("N_ref", "N축 거절(/16)"), ("rule_ref", "원칙이 참조에만 있는 모델 턴"),
        ("rule_ref_refused", "그중 거절")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="이름=폴더")
    ap.add_argument("--out", default=str(ROOT / "data/review/coverage_measure.md"))
    a = ap.parse_args()
    cols = [(x.split("=", 1)[0], stats(ROOT / x.split("=", 1)[1])) for x in a.runs]
    g = lambda s, k: s.get(k, 0.0)
    L = ["# 보장 여부 질문 개선 측정 (rebuild4, 평가 220 보이는 세트 3회 평균)", "",
         "| 지표 | " + " | ".join(n for n, _ in cols) + " |", "|---|" + "---|" * len(cols)]
    for k, label in ROWS:
        L.append(f"| {label} | " + " | ".join(f"{g(s, k):.1f}" for _, s in cols) + " |")
    L.append("| 자동 통과(실행별) | " + " | ".join("·".join(map(str, s["_auto_runs"])) for _, s in cols) + " |")
    for name, ids in GROUPS:
        L += ["", f"## {name} 대상 {len(ids)}문항 ({', '.join(sorted(ids))}) — 회당", "",
              "| | " + " | ".join(n for n, _ in cols) + " |", "|---|" + "---|" * len(cols)]
        for k in ("auto", "code") + VERDICTS + ("코드답",):
            L.append(f"| {k} | " + " | ".join(f"{g(s, f'{name}_{k}'):.1f}" for _, s in cols) + " |")
    out = Path(a.out)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
