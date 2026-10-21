"""
rebuild5_verdict.py
rebuild5 채택 판정(2026-10-22 사용자 확정 기준 — data/review/rebuild5_stage7_config.md "rebuild5 채택 기준").
같은 날 같은 코드로 잰 rebuild4·rebuild5 서빙 평가(숨긴 세트 포함, 3회)와 판정 결과를 받아 기준 1~7을 계산한다.
보이는 세트(eval220.json)로 1~6, 숨긴 세트로 7. 3회 평균.

  python -m scripts.rebuild5_verdict --r4 <rebuild4 eval json> --r5 <rebuild5 eval json> [--out md]
"""

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AXES = ("S", "P", "C", "M", "L")


def stats(path: str) -> dict:
    rep = json.loads(Path(path).read_text(encoding="utf-8"))
    judge = json.loads(Path(path).with_suffix(".judge.json").read_text(encoding="utf-8"))
    visible = {t["id"] for c in json.loads((ROOT / "data/eval/eval220.json").read_text(encoding="utf-8"))["cases"]
               for t in (c.get("turns") or [c])}
    per = defaultdict(Counter)
    for t in rep["turns"]:
        part = "vis" if t["id"] in visible else "hid"
        c = per[(part, t["run"])]
        c["n"] += 1
        c["auto"] += t["ok"]
        c["ref_gold"] += t["refused"] and bool(t.get("gold_in_prompt"))
        if t["axis"] == "N":
            c["N_n"] += 1
            c["N_ref"] += t["refused"]
        v = (judge.get(f"{t['run']}:{t['id']}") or {}).get("verdict")
        if v:
            c["judged"] += 1
            c["j_" + v] += 1
            if v == "정확":
                c["acc_" + t["axis"]] += 1
    out = {}
    for part in ("vis", "hid"):
        runs = [per[(part, r)] for r in sorted({r for p, r in per if p == part})]
        if runs:
            keys = set().union(*runs)
            out[part] = {k: statistics.mean(r[k] for r in runs) for k in keys}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--r4", required=True)
    ap.add_argument("--r5", required=True)
    ap.add_argument("--out", default=str(ROOT / "data/review/rebuild5_verdict.md"))
    a = ap.parse_args()
    s4, s5 = stats(a.r4), stats(a.r5)
    v4, v5 = s4["vis"], s5["vis"]
    g = lambda d, k: d.get(k, 0.0)
    rows = []

    def crit(no, name, b4, b5, ok, rule):
        rows.append((no, name, b4, b5, ok, rule))
        return ok
    c1 = crit(1, "정답이 프롬프트에 있는데 거절", g(v4, "ref_gold"), g(v5, "ref_gold"), g(v4, "ref_gold") - g(v5, "ref_gold") >= 5, "5건 이상 감소")
    c2 = crit(2, "판정 정확", g(v4, "j_정확"), g(v5, "j_정확"), g(v5, "j_정확") - g(v4, "j_정확") >= 5, "+5 이상")
    c3 = crit(3, "판정 틀림", g(v4, "j_틀림"), g(v5, "j_틀림"), g(v5, "j_틀림") - g(v4, "j_틀림") <= 2, "+2 이하")
    c4 = crit(4, "판정 예외누락", g(v4, "j_예외누락"), g(v5, "j_예외누락"), g(v5, "j_예외누락") - g(v4, "j_예외누락") <= 3, "+3 이하")
    c5 = crit(5, "N축 거절", g(v4, "N_ref"), g(v5, "N_ref"), g(v5, "N_ref") >= g(v5, "N_n") - 1, f"{g(v5, 'N_n') - 1:.0f}/{g(v5, 'N_n'):.0f} 이상")
    drops = {ax: g(v5, "acc_" + ax) - g(v4, "acc_" + ax) for ax in AXES}
    c6 = crit(6, "축별 정확(최저 변화)", min(drops.values()), min(drops.values()), all(d >= -3 for d in drops.values()),
              "어느 축도 −3 넘게 떨어지지 않음 · " + " ".join(f"{k}{d:+.1f}" for k, d in drops.items()))
    h5 = s5.get("hid", {})
    vis_rate = g(v5, "j_정확") / max(1, g(v5, "judged"))
    hid_rate = g(h5, "j_정확") / max(1, g(h5, "judged")) if h5 else None
    c7 = hid_rate is not None and hid_rate >= vis_rate - 0.10
    rows.append((7, "숨긴 세트 정확 비율(경보)", vis_rate, hid_rate, c7, "보이는 세트보다 10%p 넘게 낮지 않음"))
    if all((c1, c2, c3, c4, c5, c6)):
        verdict = "채택"
    elif (c3 and c5) and (c4 and c6) and not (c1 and c2):
        verdict = "보류(1 또는 2 미달 — 다른 체크포인트·C 비율 조정 후 한 번 더)"
    elif not (c3 and c5):
        verdict = "불채택(3 또는 5 위반)"
    else:
        verdict = "불채택"
    L = ["# rebuild5 채택 판정", "", f"- rebuild4: `{a.r4}`", f"- rebuild5: `{a.r5}`",
         "- 보이는 세트 3회 평균(1~6), 숨긴 세트(7). 기준: data/review/rebuild5_stage7_config.md", "",
         f"## 판정: **{verdict}**", "", "| # | 기준 | rebuild4 | rebuild5 | 통과 | 선 |", "|---|---|---|---|---|---|"]
    for no, name, b4, b5, ok, rule in rows:
        fmt = (lambda x: "-" if x is None else (f"{x:.1%}" if no == 7 else f"{x:.1f}"))
        L.append(f"| {no} | {name} | {fmt(b4)} | {fmt(b5)} | {'✅' if ok else '❌'} | {rule} |")
    L += ["", "## 참고(보이는 세트 3회 평균)", "", "| 지표 | rebuild4 | rebuild5 |", "|---|---|---|"]
    for k in ("auto", "judged", "j_정확", "j_예외누락", "j_틀림", "j_거절", "ref_gold", "N_ref"):
        L.append(f"| {k} | {g(v4, k):.1f} | {g(v5, k):.1f} |")
    if h5:
        h4 = s4.get("hid", {})
        L += ["", "## 숨긴 세트 3회 평균", "", "| 지표 | rebuild4 | rebuild5 |", "|---|---|---|"]
        for k in ("auto", "judged", "j_정확", "j_예외누락", "j_틀림", "j_거절", "ref_gold", "N_ref"):
            L.append(f"| {k} | {g(h4, k):.1f} | {g(h5, k):.1f} |")
    Path(a.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
