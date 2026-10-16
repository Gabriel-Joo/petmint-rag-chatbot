"""
build_review.py
빌드 뒤 사람 표본 검수(2026-10-16, rebuild3) — data/rebuild.py의 review 단계(build와 train 사이).

no_answer 확인 검사를 다른 모델(qwen3:14b)로 하던 것을 사람 표본으로 바꾼다. qwen 확인 검사는 12건 중 8건을 과하게 잡았고
(data/review/na_confirm_qwen_check12_20261015.md), 같은 판정기·같은 캐시로 다시 재는 것은 구조상 0건이 나온다 — 검사가 아니다.

표본(고정 seed, train+val에서): no_answer 30 · 등급 어구 양성 20 · 재작성 양성 20.
- no_answer: "답없음"(라벨이 맞다) / "답있음"(발췌에 질문의 답이 있다 — 라벨 오류)
- 양성: "맞음"(질문·발췌·답변이 맞는다) / "틀림"(재작성이 뜻을 바꿨거나 답변과 어긋난다)
통과 기준(사용자 확정 2026-10-16): no_answer 중 "답있음" ≤ NA_MAX_BAD(3건 = 10%). 양성 "틀림"은 건수만 보고한다.

흐름: 첫 실행은 검수지(data/review/build_review_<이름>_<날짜시각>.md)와 판정 파일(<logs>/review_verdicts.json, 판정 칸이 빈 상태)을
만들고 종료 코드 3으로 멈춘다(= review 단계 실패, 파이프라인이 train으로 넘어가지 않는다). 사람이 판정 칸을 채운 뒤 다시 실행하면
판정을 세어 <logs>/review_result.json을 쓰고, 통과면 0 · 미달이면 4로 끝난다.

실행: python -m data.build_review run --ft=<학습 데이터 폴더> --logs=<로그 폴더> --name=<재구축 이름>
"""

import json
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
REVIEW_DIR = PROJECT_DIR / "data" / "review"
SEED = 20261016
N = {"no_answer": 30, "grade": 20, "rewrite": 20}
NA_MAX_BAD = 3
ALLOWED = {"no_answer": ("답없음", "답있음"), "grade": ("맞음", "틀림"), "rewrite": ("맞음", "틀림")}
WAIT, FAIL = 3, 4


def _load_samples(ft: Path) -> list[dict]:
    return [json.loads(l) for n in ("train.jsonl", "val.jsonl") for l in open(ft / n, encoding="utf-8")]


def group_of(s: dict) -> str | None:
    m = s["meta"]
    if m["kind"] == "no_answer":
        return "no_answer"
    st = m.get("rewrite_status") or ""
    if st == "grade_ok":
        return "grade"
    if st == "ok":
        return "rewrite"
    return None


def pick(samples: list[dict]) -> list[tuple[str, dict]]:
    rng = random.Random(SEED)
    out = []
    for g, n in N.items():
        pool = [s for s in samples if group_of(s) == g]
        out += [(g, s) for s in rng.sample(pool, min(n, len(pool)))]
    return out


def render(picked: list[tuple[str, dict]], name: str, verdict_path: Path) -> str:
    L = [f"# 빌드 표본 검수 — {name}", "", f"생성: {datetime.now():%Y-%m-%d %H:%M}", "",
         f"판정은 `{verdict_path}`의 verdict 칸에 적는다.",
         "- no_answer: `답없음`(라벨이 맞다) / `답있음`(발췌에 질문의 답이 있다)",
         "- 등급 어구·재작성 양성: `맞음` / `틀림`(뜻이 바뀌었거나 답변과 어긋난다)",
         f"- 통과 기준: no_answer 중 `답있음` ≤ {NA_MAX_BAD}건. 양성 `틀림`은 건수만 보고", ""]
    for i, (g, s) in enumerate(picked, 1):
        m, msgs = s["meta"], s["messages"]
        L += [f"## {i:02d}. [{g}] {m['species']} · {m['unit_id']}", ""]
        orig = m.get("question_original")
        if orig:
            L.append(f"- 원래 질문: {orig}")
        L += ["", "```", msgs[1]["content"], "```", "", f"**학습 답변**: {msgs[2]['content']}", ""]
    return "\n".join(L) + "\n"


def run(ft: Path, logs: Path, name: str) -> int:
    vpath = logs / "review_verdicts.json"
    if not vpath.exists():
        picked = pick(_load_samples(ft))
        items = [{"no": i, "group": g, "unit_id": s["meta"]["unit_id"], "question": s["messages"][1]["content"].rsplit("\n", 1)[-1],
                  "verdict": ""} for i, (g, s) in enumerate(picked, 1)]
        logs.mkdir(parents=True, exist_ok=True)
        vpath.write_text(json.dumps({"ft": str(ft), "allowed": ALLOWED, "na_max_bad": NA_MAX_BAD, "items": items},
                                    ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        sheet = REVIEW_DIR / f"build_review_{name}_{datetime.now():%Y%m%d_%H%M}.md"
        sheet.write_text(render(picked, name, vpath), encoding="utf-8")
        print(f"검수 대기 — {dict(Counter(g for g, _ in picked))}건. 검수지 {sheet} 를 보고 {vpath} 의 verdict를 채운 뒤 다시 실행")
        return WAIT
    v = json.loads(vpath.read_text(encoding="utf-8"))
    bad_val = [it["no"] for it in v["items"] if it["verdict"] and it["verdict"] not in ALLOWED[it["group"]]]
    empty = [it["no"] for it in v["items"] if not it["verdict"]]
    if bad_val:
        print(f"허용되지 않은 판정 값: {bad_val} — {ALLOWED}")
        return WAIT
    if empty:
        print(f"검수 대기 — 판정이 빈 항목 {len(empty)}건: {empty[:20]}")
        return WAIT
    c = Counter((it["group"], it["verdict"]) for it in v["items"])
    na_bad = c[("no_answer", "답있음")]
    res = {"approved": na_bad <= NA_MAX_BAD, "na_answer_present": na_bad, "na_n": sum(it["group"] == "no_answer" for it in v["items"]),
           "grade_wrong": c[("grade", "틀림")], "grade_n": sum(it["group"] == "grade" for it in v["items"]),
           "rewrite_wrong": c[("rewrite", "틀림")], "rewrite_n": sum(it["group"] == "rewrite" for it in v["items"]),
           "na_max_bad": NA_MAX_BAD, "checked": datetime.now().isoformat(timespec="seconds")}
    (logs / "review_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"검수 결과: no_answer 답있음 {na_bad}/{res['na_n']} (기준 ≤ {NA_MAX_BAD}) → {'통과' if res['approved'] else '미달'} | "
          f"등급 어구 틀림 {res['grade_wrong']}/{res['grade_n']} · 재작성 틀림 {res['rewrite_wrong']}/{res['rewrite_n']}")
    return 0 if res["approved"] else FAIL


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    opts = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
    if not args or args[0] != "run":
        sys.exit(__doc__)
    sys.exit(run(Path(opts["ft"]), Path(opts["logs"]), opts["name"]))


if __name__ == "__main__":
    main()
