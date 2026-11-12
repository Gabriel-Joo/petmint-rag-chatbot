"""
refusal_rescore.py
저장된 eval_serving 결과를 거절 판정 두 판(v1 · 현재)으로 다시 센다 — 2026-11-12 판정을 바꿀 때 과거 수치가 얼마나 흔들리는지 잰 도구.
답 글은 결과 파일에 있으므로 서버 없이 돈다. 같은 이름의 .judge.json(gemma 판정)이 있으면 "거절" 판정과 맞는 비율도 낸다.

  python -m scripts.refusal_rescore logs/stage7b/r5/eval_serving_20261023_0800_r5bfinal.json [...]

모델 답만 센다(code_answer · error 턴은 뺀다). N = 거절해야 하는 문항(expect.refuse)의 통과 수.
"""

import json
import sys
from collections import Counter
from pathlib import Path

from data import refusal


def rescore(path: Path) -> Counter:
    d = json.loads(path.read_text())
    if not isinstance(d, dict):                       # 옛 형식(턴 목록만) — 셀 수 없다
        return Counter({"건너뜀(옛 형식)": 1})
    jp = path.with_name(path.name.removesuffix(".json") + ".judge.json")
    judge = json.loads(jp.read_text()) if jp.exists() else {}
    judge = judge if isinstance(judge, dict) else {}
    c = Counter()
    for r in d.get("turns", []):
        if r.get("code_answer") or r.get("error") or not r.get("answer"):
            continue
        old, new = refusal.refused_v1(r["answer"]), refusal.refused(r["answer"])
        c["턴"] += 1
        c["거절 v1"] += old
        c["거절 현재"] += new
        c["바뀜"] += old != new
        v = judge.get(f'{r.get("run", 0)}:{r["id"]}')
        if isinstance(v, dict) and v.get("verdict"):
            c["gemma 판정"] += 1
            c["gemma 일치 v1"] += old == (v["verdict"] == "거절")
            c["gemma 일치 현재"] += new == (v["verdict"] == "거절")
        if "refuse" in (r.get("checks") or {}):
            c["N 문항"] += 1
            c["N 통과 v1"] += old
            c["N 통과 현재"] += new
    return c


if __name__ == "__main__":
    total = Counter()
    for p in sys.argv[1:]:
        c = rescore(Path(p))
        total += c
        print(Path(p).name, dict(c))
    if len(sys.argv) > 2:
        print("합계", dict(total))
