"""
ckpt_select.py
학습 뒤 체크포인트 고르기(2026-10-16) — data/rebuild.py의 select 단계.

배경: rebuild2(450 step)의 체크포인트 9개를 97문항으로 재 보니 gold 거절이 19(350) ~ 25(250)로 흔들렸고 최종(450)은 23이었다.
val loss는 끝까지 내려갔다(0.524 → 0.433) — loss로는 거절 과학습이 보이지 않는다. 그래서 체크포인트마다 축소판 문항으로 재서 고른다.

선택 세트(data/eval/ckpt_select_set.json, 고정): answerable gold 22 + no_answer 8 = 30문항.
- answerable만 쓴다(partial·flawed는 거절도 변호 가능해 점수가 흔들린다). 등급·유형 어구 질문 비율을 97문항과 같게 층화, seed 42.
- 이 25문항으로 고른 체크포인트를 97문항 전체로 판정하면 그 25문항만큼 낙관적이다 —
  판정 보고에는 97문항 전체와 함께 선택 세트를 뺀 나머지(gold 75 · no_answer 12)를 따로 적는다(report_holdout).
- 25문항(18+7)도 재 봤다(replay, 2026-10-16): rebuild 후보 3개가 전부 동점이었다. 30문항이 사용자 범위(20~30)의 위 끝이다.
  replay 결과 — rebuild2: 축소판 400(점수 4) · 97문항 전체 350(19, 400도 19) / rebuild: 축소판 최종(동점) · 전체 400.
  축소판은 상위 묶음(전체 점수 차 1 이내)까지는 고르지만 그 안의 순서는 못 가린다 — 그 차이는 문항 수로 보면 잡음이다.

점수(낮을수록 좋다) = answerable 거절 + no_answer를 거절하지 않은 수. 동점이면 answerable 거절이 적은 쪽, 그다음 뒤 step.
고른 결과는 <어댑터>/ckpt_select.json에 쓴다. 최종 어댑터 파일은 바꾸지 않는다 — GGUF 변환 등에서 이 파일의 best를 쓴다.

실행:
  python -m data.ckpt_select make-set                       선택 세트 만들기(모델 없음, 이미 있으면 같은지 확인)
  python -m data.ckpt_select run <어댑터 폴더>               체크포인트 전부 + 최종을 축소판으로 재고 고른다(GPU)
  python -m data.ckpt_select replay <answer_eval 결과 json…>  이미 잰 97문항 결과로 '축소판이었다면 무엇을 골랐나'(모델 없음)
"""

import filecmp
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SET_PATH = PROJECT_DIR / "data" / "eval" / "ckpt_select_set.json"
REVIEW_DIR = PROJECT_DIR / "data" / "review"
N_GOLD, N_NA, SEED = 22, 8, 42


def _flags(v):
    import ast
    return ast.literal_eval(v) if isinstance(v, str) else v


def make_set() -> list[str]:
    from data import answer_eval as ae
    from data import search_regression as R
    from data.search_scope import mentioned_grade, mentioned_type
    labels = json.loads(ae.LABELS_PATH.read_text(encoding="utf-8"))
    gold = [c for c in R.load_cases() if c["gold"] and ae.gold_label(c["id"], labels) == "answerable"]
    phrase = [c["id"] for c in gold if mentioned_grade(c["query"]) or mentioned_type(c["query"])]
    plain = [c["id"] for c in gold if c["id"] not in phrase]
    rng = random.Random(SEED)
    n_phrase = round(N_GOLD * len(phrase) / len(gold))
    ids = sorted(rng.sample(sorted(phrase), n_phrase)) + sorted(rng.sample(sorted(plain), N_GOLD - n_phrase))
    na = [f"NA{97 + i:03d}" for i in range(20)]        # answer_eval no_answer 20문항 id(NA097~NA116, val.jsonl 앞 20건)
    ids += sorted(rng.sample(na, N_NA))
    if SET_PATH.exists():
        old = json.loads(SET_PATH.read_text(encoding="utf-8"))
        assert old == ids, f"{SET_PATH}가 지금 규칙으로 만든 것과 다르다 — 선택 세트는 고정이어야 한다"
    else:
        SET_PATH.write_text(json.dumps(ids, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"선택 세트 {len(ids)}문항: answerable {N_GOLD}(등급 어구 {n_phrase}/{len(phrase)}) + no_answer {N_NA} → {SET_PATH}")
    return ids


def score(rows: list[dict], ids: set[str] | None = None) -> dict:
    """rows: answer_eval 결과 rows. ids가 있으면 그 문항만"""
    from data import answer_eval as ae
    labels = json.loads(ae.LABELS_PATH.read_text(encoding="utf-8"))
    rows = [r for r in rows if ids is None or r["id"] in ids]
    ans = [r for r in rows if r["kind"] == "gold" and ae.gold_label(r["id"], labels) == "answerable"]
    na = [r for r in rows if r["kind"] != "gold"]
    a_ref = sum(_flags(r["ft_flags"])["refused"] for r in ans)
    na_miss = sum(not _flags(r["ft_flags"])["refused"] for r in na)
    return {"answerable_refused": a_ref, "answerable_n": len(ans), "na_missed": na_miss, "na_n": len(na),
            "errors": a_ref + na_miss}


def step_of(adapter: str) -> int:
    m = re.search(r"checkpoint-(\d+)", adapter)
    return int(m.group(1)) if m else 10 ** 9          # 최종 어댑터 = 맨 뒤


def pick(scored: dict[str, dict]) -> str:
    return min(scored, key=lambda a: (scored[a]["errors"], scored[a]["answerable_refused"], -step_of(a)))


def candidates(adapter_dir: Path) -> list[Path]:
    cks = sorted((p for p in adapter_dir.glob("checkpoint-*") if (p / "adapter_model.safetensors").exists()),
                 key=lambda p: step_of(p.name))
    # 마지막 체크포인트가 최종 어댑터와 같은 파일이면(학습이 저장 간격에서 끝남 — rebuild2의 450) 최종만 잰다
    if cks and filecmp.cmp(cks[-1] / "adapter_model.safetensors", adapter_dir / "adapter_model.safetensors", shallow=False):
        cks = cks[:-1]
    return cks + [adapter_dir]


def render(adapter_dir: Path, scored: dict[str, dict], best: str, title: str) -> str:
    L = [f"# 체크포인트 고르기 — {adapter_dir.name}", "", f"{title} · {datetime.now():%Y-%m-%d %H:%M}", "",
         "점수 = answerable 거절 + no_answer 놓침(낮을수록 좋다). 동점이면 answerable 거절이 적은 쪽, 그다음 뒤 step.", "",
         "| 후보 | answerable 거절 | no_answer 놓침 | 점수 |", "|---|---|---|---|"]
    for a, s in scored.items():
        mark = " **← 선택**" if a == best else ""
        L.append(f"| {a}{mark} | {s['answerable_refused']}/{s['answerable_n']} | {s['na_missed']}/{s['na_n']} | {s['errors']} |")
    return "\n".join(L) + "\n"


def run(adapter_dir: Path):
    from data import answer_eval as ae
    ids = make_set()
    cands = candidates(adapter_dir)
    assert len(cands) > 1, f"{adapter_dir}에 체크포인트가 없다 — 07 save_total_limit 확인"
    paths = ae.main(["--subset", str(SET_PATH), "--adapter", *map(str, cands)])
    scored = {}
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        scored[ae.adapter_tag(d["adapter"])] = score(d["rows"])
    scored = dict(sorted(scored.items(), key=lambda kv: step_of(kv[0])))
    best = pick(scored)
    best_path = next(c for c in cands if ae.adapter_tag(c) == best)
    out = {"adapter": str(adapter_dir), "best": best, "best_path": str(best_path), "set": str(SET_PATH),
           "scored": scored, "created": datetime.now().isoformat(timespec="seconds")}
    (adapter_dir / "ckpt_select.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = REVIEW_DIR / f"ckpt_select_{adapter_dir.name}_{datetime.now():%Y%m%d_%H%M}.md"
    title = f"축소판 {N_GOLD + N_NA}문항"
    md.write_text(render(adapter_dir, scored, best, title), encoding="utf-8")
    print(render(adapter_dir, scored, best, title))
    print(f"선택: {best} → {adapter_dir / 'ckpt_select.json'} | {md}")
    return out


def replay(paths: list[str]):
    """이미 잰 97문항 결과들: 축소판 점수와 97문항 전체 점수, 선택 세트를 뺀 나머지 점수를 나란히"""
    from data import answer_eval as ae
    ids = set(make_set())
    rows_by = {}
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        rows_by[ae.adapter_tag(d["adapter"])] = d["rows"]
    rest = {r["id"] for rows in rows_by.values() for r in rows} - ids
    sub = {a: score(r, ids) for a, r in rows_by.items()}
    print("| 후보 | 축소판 점수(answerable 거절+NA 놓침) | 나머지 점수 | 97문항 전체 점수 |\n|---|---|---|---|")
    for a in sorted(rows_by, key=step_of):
        s, h, f = sub[a], score(rows_by[a], rest), score(rows_by[a])
        print(f"| {a} | {s['errors']} ({s['answerable_refused']}+{s['na_missed']}) | {h['errors']} ({h['answerable_refused']}+{h['na_missed']}) "
              f"| {f['errors']} ({f['answerable_refused']}+{f['na_missed']}) |")
    print(f"축소판이 고른 것: {pick(sub)} | 나머지로 고른 것: {pick({a: score(r, rest) for a, r in rows_by.items()})} "
          f"| 전체로 고른 것: {pick({a: score(r) for a, r in rows_by.items()})}")


def report_holdout(rows: list[dict]) -> dict:
    """판정 보고용 — 선택 세트를 뺀 나머지 문항 점수"""
    ids = set(json.loads(SET_PATH.read_text(encoding="utf-8")))
    return score(rows, {r["id"] for r in rows} - ids)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else ""
    if cmd == "make-set":
        make_set()
    elif cmd == "run":
        run(Path(args[1]))
    elif cmd == "replay":
        replay(args[1:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
