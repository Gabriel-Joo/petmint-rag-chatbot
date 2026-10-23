"""
rollout_table.py
운영 반영 판단 측정(scripts/rollout_measure.sh) 결과 → data/review/rollout_measure.md.
보이는 세트 3회 평균. 거절은 전체 턴 기준과 판정 기준(모델 답 턴) 둘 다, 정답이 프롬프트에 있는데 거절, N축 거절.

  python -m scripts.rollout_table
"""

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
O = ROOT / "logs/rollout"
CONFIGS = [("all", "전부 켬(사전 v1)"), ("dictv2", "전부 켬, 사전 v2"), ("nov3", "청크 v3·부모 표시 끔(옛 청크)"),
           ("noexp", "질의 확장 끔"), ("codeonly", "코드만(플래그 전부 끔)")]
KEYS = [("auto", "자동 통과"), ("refused", "거절(전체 턴)"), ("ref_gold", "정답이 프롬프트에 있는데 거절"),
        ("gold_prompt", "정답이 프롬프트에 든 턴"), ("code", "코드 답 턴"), ("judged", "판정 대상(모델 답) 턴"),
        ("j_정확", "판정 정확"), ("j_틀림", "판정 틀림"), ("j_예외누락", "판정 예외누락"), ("j_거절", "판정 거절"),
        ("N_ref", "N축 거절(/16)"), ("tables", "표가 붙은 턴"), ("table_hl", "그중 행 강조")]


def stats(path: Path) -> tuple[dict, list]:
    rep = json.loads(path.read_text(encoding="utf-8"))
    judge = json.loads(path.with_suffix(".judge.json").read_text(encoding="utf-8"))
    visible = {t["id"] for c in json.loads((ROOT / "data/eval/eval220.json").read_text(encoding="utf-8"))["cases"]
               for t in (c.get("turns") or [c])}
    per = defaultdict(Counter)
    for t in rep["turns"]:
        if t["id"] not in visible:
            continue
        c = per[t["run"]]
        c["auto"] += t["ok"]
        c["refused"] += bool(t["refused"])
        c["ref_gold"] += bool(t["refused"] and t.get("gold_in_prompt"))
        c["gold_prompt"] += bool(t.get("gold_in_prompt"))
        c["code"] += bool(t.get("code_answer"))
        c["tables"] += bool(t.get("n_tables"))
        c["table_hl"] += bool(t.get("table_hl"))
        if t["axis"] == "N":
            c["N_ref"] += bool(t["refused"])
        v = (judge.get(f"{t['run']}:{t['id']}") or {}).get("verdict")
        if v:
            c["judged"] += 1
            c["j_" + v] += 1
    runs = [per[r] for r in sorted(per)]
    return {k: statistics.mean(r[k] for r in runs) for k, _ in KEYS}, [r["auto"] for r in runs]


def main():
    have = []
    for tag, name in CONFIGS:
        f = sorted((O / tag).glob(f"eval_serving_*_{tag}.json"))
        if f and f[-1].with_suffix(".judge.json").exists():
            have.append((tag, name, *stats(f[-1])))
    L = ["# 운영 반영 판단 측정 (rebuild4, 평가 220 보이는 세트 3회 평균)", "",
         "| 지표 | " + " | ".join(f"{n} `{t}`" for t, n, _, _ in have) + " |", "|---|" + "---|" * len(have)]
    for k, label in KEYS:
        L.append(f"| {label} | " + " | ".join(f"{s[k]:.1f}" for _, _, s, _ in have) + " |")
    L.append("| 자동 통과(실행별) | " + " | ".join("·".join(map(str, a)) for _, _, _, a in have) + " |")
    for sr in ("sr_v1", "sr_v2"):
        p = O / sr / "search_regression_pet.json"
        if p.exists():
            s = json.loads(p.read_text(encoding="utf-8")).get("summary", {})
            L += ["", f"검색 회귀 {sr}: `{json.dumps(s.get('all', s), ensure_ascii=False)[:300]}`"]
    out = ROOT / "data/review/rollout_measure.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
