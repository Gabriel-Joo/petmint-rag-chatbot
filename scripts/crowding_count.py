"""
crowding_count.py
발췌 자리 다툼 세기(2026-10-23 레오 "감기 입원 보장?" 1안 뒤에도 거절) — 측정 폴더의 프롬프트 기록·결과·판정으로 두 유형을 센다.

  유형 A  원칙(의료비 특약 제1조 ①)이 발췌 본문에 있는데 모델이 거절·틀림 — 같은 프롬프트의 다른 발췌가 면책 조항인지,
          정답 조항이 아닌지, 원칙 발췌가 몇 번째인지로 나눈다
  유형 B  부담보 특약(반려동물 특정 질병 보장제한부 인수 특별약관) 발췌가 자리를 차지했는데 질문이 그 반려동물의 부담보 병명과
          무관한 턴(payout.matched_exclusions가 비었다). 부담보 특약은 가입한 반려동물(초코·레오·망고)만 검색 범위에 든다

  python -m scripts.crowding_count logs/coverage/a3b [--out data/review/crowding_count.md]
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from app.services import payout
from app.services.customers import EXCLUSION_SECTION
from scripts.eval_serving import COVERAGE_RULE, flat, gold_hit, pets

ROOT = Path(__file__).resolve().parent.parent
EXEMPT = ("지급하지 않는", "보상하지 않는", "면책")     # 조 제목에 이 말이 있으면 면책 조항


def blocks(messages: list[dict]) -> list[str]:
    """발췌 블록 본문([참조] 앞까지, 공백 없앤 글) — 순서대로"""
    user = next(m["content"] for m in messages if m["role"] == "user")
    part = user.split("[질문]")[0]
    return [flat(re.split(r"\n\[참조\]", b)[0]) for b in re.split(r"(?=\[발췌 \d+\])", part)[1:]]


def load(d: Path):
    f = [x for x in sorted(d.glob("eval_serving_*.json")) if not x.name.endswith(".judge.json")][-1]
    rep = json.loads(f.read_text(encoding="utf-8"))
    judge = json.loads(f.with_suffix(".judge.json").read_text(encoding="utf-8"))
    prompts = {}
    for p in d.glob("prompts_*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            prompts[r["turn_id"]] = r
    return rep, judge, prompts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--out", default=str(ROOT / "data/review/crowding_count.md"))
    a = ap.parse_args()
    rep, judge, prompts = load(ROOT / a.run)
    cases = json.loads((ROOT / "data/eval/eval220.json").read_text(encoding="utf-8"))["cases"]
    turns = {t["id"]: t for c in cases for t in (c.get("turns") or [c])}
    prev = {}                                       # 멀티턴 — 앞 턴 질문(부담보 병명 대조용)
    for c in cases:
        ts = c.get("turns") or []
        for x, y in zip(ts, ts[1:]):
            prev[y["id"]] = x["query"]
    pm = pets()
    rule = flat(COVERAGE_RULE)
    n_runs = len({t["run"] for t in rep["turns"]})

    A = defaultdict(list)                           # id → [턴 정보…]
    B = defaultdict(list)
    for t in rep["turns"]:
        case = turns.get(t["id"])
        p = prompts.get(t.get("turn_id"))
        if case is None or p is None or t.get("code_answer"):
            continue
        v = (judge.get(f"{t['run']}:{t['id']}") or {}).get("verdict")
        kept = [p["results"][int(k)] for k in p["kept"]]
        bl = blocks(p["messages"])
        gold = case.get("gold") or []
        titles = []
        for i, r in enumerate(kept):
            titles.append(dict(pos=i + 1, sec=r.get("section_name") or "보통약관", art=r.get("article_num"),
                               gold=any(gold_hit(r, g) for g in gold),
                               exempt=False, rider=r.get("section_name") == EXCLUSION_SECTION))
        # 조 제목은 프롬프트의 발췌 머리줄에서 읽는다(결과 기록에는 제목이 없다)
        user = next(m["content"] for m in p["messages"] if m["role"] == "user")
        for i, head in enumerate(re.findall(r"\[발췌 \d+\] ([^\n]*)", user)[:len(titles)]):
            titles[i]["head"] = head
            titles[i]["exempt"] = any(w in head for w in EXEMPT)
        row = dict(run=t["run"], refused=bool(t["refused"]), verdict=v, ok=t["ok"], ex=titles,
                   expect_refuse=case["expect"]["refuse"])
        pos = next((i + 1 for i, b in enumerate(bl) if rule in b), None)
        if pos is not None and not case["expect"]["refuse"]:
            A[t["id"]].append(row | dict(rule_pos=pos))
        if any(x["rider"] for x in titles):
            pet = pm[case["pet_id"]]
            text = f"{prev.get(t['id'], '')} {case['query']}"
            B[t["id"]].append(row | dict(matched=payout.matched_exclusions(text, pet), pet=pet.name))

    L = [f"# 발췌 자리 다툼 세기 — {a.run} ({n_runs}회)", ""]
    # ---- 유형 A
    allA = [r for rs in A.values() for r in rs]
    bad = [r for r in allA if r["refused"] or r["verdict"] in ("틀림", "거절")]
    L += ["## 유형 A — 원칙(제1조 ①)이 발췌 본문에 있는 모델 턴 (거절 기대 턴 제외)", "",
          f"- 문항 {len(A)} · 턴 {len(allA)}(회당 {len(allA) / n_runs:.1f}) · 그중 거절 {sum(r['refused'] for r in allA)}"
          f" · 판정 거절/틀림 {len(bad)}", ""]
    L += ["| 원칙 발췌 위치 | 턴 | 거절 | 판정 거절 | 판정 틀림 | 판정 정확 |", "|---|---|---|---|---|---|"]
    for pos in (1, 2, 3):
        rs = [r for r in allA if r["rule_pos"] == pos]
        L.append(f"| {pos}번째 | {len(rs)} | {sum(r['refused'] for r in rs)} | {sum(r['verdict'] == '거절' for r in rs)} | "
                 f"{sum(r['verdict'] == '틀림' for r in rs)} | {sum(r['verdict'] == '정확' for r in rs)} |")
    L += ["", "| 다른 발췌 구성 | 턴 | 거절 | 거절률 |", "|---|---|---|---|"]
    def kind(r):
        others = [x for x in r["ex"] if x["pos"] != r["rule_pos"]]
        k = []
        if any(x["exempt"] for x in others):
            k.append("면책 조항")
        if any(x["rider"] for x in others):
            k.append("부담보 특약")
        if any(not x["gold"] and not x["exempt"] and not x["rider"] for x in others):
            k.append("정답 아닌 기타")
        return " + ".join(k) or "(모두 정답 조항)"
    for k, n in Counter(kind(r) for r in allA).most_common():
        rs = [r for r in allA if kind(r) == k]
        ref = sum(r["refused"] for r in rs)
        L.append(f"| {k} | {n} | {ref} | {ref / n:.0%} |")
    L += ["", "### 거절이 한 번이라도 난 문항", "", "| 문항 | 거절/턴 | 원칙 위치 | 판정 | 발췌 |", "|---|---|---|---|---|"]
    for i, rs in sorted(A.items()):
        ref = sum(r["refused"] for r in rs)
        if not ref:
            continue
        ex = " / ".join(f"{x['pos']}:{x.get('head', x['sec'])[:28]}{'(면책)' if x['exempt'] else ''}{'(정답)' if x['gold'] else ''}"
                        for x in rs[0]["ex"])
        L.append(f"| {i} | {ref}/{len(rs)} | {'·'.join(str(r['rule_pos']) for r in rs)} | "
                 f"{'·'.join(r['verdict'] or '-' for r in rs)} | {ex} |")
    # ---- 유형 B
    allB = [r for rs in B.values() for r in rs]
    unrel = [r for r in allB if not r["matched"]]
    L += ["", "## 유형 B — 부담보 특약 발췌가 프롬프트에 든 모델 턴", "",
          f"- 문항 {len(B)} · 턴 {len(allB)}(회당 {len(allB) / n_runs:.1f})",
          f"- 그중 질문이 부담보 병명과 무관(배너 대조 빈 것): 턴 {len(unrel)}(회당 {len(unrel) / n_runs:.1f}),"
          f" 거절 {sum(r['refused'] for r in unrel)}, 부담보 발췌가 정답 조항인 턴 {sum(any(x['rider'] and x['gold'] for x in r['ex']) for r in unrel)}",
          f"- 질문이 부담보 병명에 걸림: 턴 {len(allB) - len(unrel)}", "",
          "| 문항 | 반려동물 | 병명 대조 | 거절/턴 | 판정 | 부담보 발췌 위치 | 기대 거절 |", "|---|---|---|---|---|---|---|"]
    for i, rs in sorted(B.items()):
        r0 = rs[0]
        pos = "·".join(str(x["pos"]) + ("(정답)" if x["gold"] else "") for x in r0["ex"] if x["rider"])
        L.append(f"| {i} | {r0['pet']} | {', '.join(r0['matched']) or '무관'} | {sum(r['refused'] for r in rs)}/{len(rs)} | "
                 f"{'·'.join(r['verdict'] or '-' for r in rs)} | {pos} | {'예' if r0['expect_refuse'] else ''} |")
    out = Path(a.out)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
