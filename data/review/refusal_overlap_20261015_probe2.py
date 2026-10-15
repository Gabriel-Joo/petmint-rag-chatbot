# 2026-10-15 거절-겹침 측정 2차(평가 경계·학습 구간별 NA 비율·재작성 전후). 실행: PYTHONPATH=. python data/review/refusal_overlap_20261015_probe2.py
# 기록: data/review/refusal_overlap_20261015.md
import json, glob, sys, bisect, statistics as st
from collections import Counter
from data import prompts
from data.finetune_data import question_overlap
from data.faq_style import is_situational
from data.answer_eval import build_inputs
from data.rag_context import ContextBuilder

def qt(v, p): v = sorted(v); return v[min(int(len(v) * p), len(v) - 1)]
def desc(v): return f"n={len(v):4d} 평균={st.mean(v):.3f} p10={qt(v,.1):.3f} p25={qt(v,.25):.3f} 중앙={qt(v,.5):.3f} p75={qt(v,.75):.3f} p90={qt(v,.9):.3f}"
def split(s): return s["messages"][1]["content"].rsplit(f"\n\n{prompts.QUESTION_HEADER}\n", 1)
def pct(sorted_v, x): return bisect.bisect_left(sorted_v, x) / len(sorted_v)

# ---------- 학습셋 ----------
def load(p): return [json.loads(l) for l in open(p, encoding="utf-8")]
NEW, OLD = load("data/finetune/rebuild/train.jsonl"), load("data/finetune/train.jsonl")
rew = {}
for sp in ("강아지", "고양이"):
    for r in json.load(open(f"data/faq/rebuild/rewrite/final/petmint_{sp}_faq_final.json", encoding="utf-8")):
        rew[(r["unit_id"], r["question"])] = r["question_original"]
def train_rows(T, counterfactual=False):
    out = []
    for s in T:
        ex, q = split(s)
        if counterfactual and s["meta"].get("rewrite_status") == "ok":
            q = rew[(s["meta"]["unit_id"], split(s)[1])] if (s["meta"]["unit_id"], split(s)[1]) in rew else None
            if q is None: continue
        out.append({"kind": s["meta"]["kind"], "na": s["meta"]["kind"] == "no_answer", "ov": question_overlap(q, ex),
                    "st": s["meta"].get("rewrite_status"), "sit": is_situational(q)})
    return out
tn, to = train_rows(NEW), train_rows(OLD)
miss = sum(1 for s in NEW if s["meta"].get("rewrite_status") == "ok" and (s["meta"]["unit_id"], split(s)[1]) not in rew)
tc = train_rows(NEW, counterfactual=True)
print(f"[확인] 재작성 ok 표본 중 원 질문 매칭 실패 {miss}건")

print("\n== A. 학습셋 겹침 분포 (같은 지표: 질문 글자 바이그램 중 발췌에 있는 비율)")
for name, T in (("4811건(재작성 없음)", to), ("6806건_rebuild 실제", tn), ("6806건_rebuild 원질문으로 되돌림", tc)):
    print(f" {name}")
    for k in ("gold_only", "distract", "no_answer"):
        v = [r["ov"] for r in T if r["kind"] == k]
        if v: print(f"   {k:10s} {desc(v)}")
    pos = [r for r in T if not r["na"]]
    print(f"   상황형 비율: 양성 {sum(r['sit'] for r in pos)/len(pos):.1%} / no_answer {sum(r['sit'] for r in T if r['na'])/max(1,sum(r['na'] for r in T)):.1%}")

BINS = [0, .1, .2, .3, .4, .5, .6, 1.01]
def binrate(T):
    out = []
    for lo, hi in zip(BINS, BINS[1:]):
        s = [r for r in T if lo <= r["ov"] < hi]
        out.append((sum(r["na"] for r in s), len(s)))
    return out

print("\n== B. 재작성 상태별 겹침 (rebuild, 같은 표본에서 재작성 전/후)")
for k in ("pos", "no_answer"):
    sel = lambda r: r["na"] if k == "no_answer" else not r["na"]
    for stt in ("ok", "rejected", "reverted_rejudge", "unchanged"):
        v = [r["ov"] for r in tn if sel(r) and r["st"] == stt]
        if v: print(f"   {k:9s} {stt:16s} {desc(v)}")
    a = [r["ov"] for r in tn if sel(r) and r["st"] == "ok"]; b = [r["ov"] for r in tc if sel(r) and r["st"] == "ok"]
    print(f"   {k:9s} ok 재작성 전 질문    {desc(b)}  → 후 중앙 {qt(a,.5):.3f}")

# ---------- 평가 ----------
old = json.load(open("data/eval/results/answer_eval_20261014_1011_rag-1_4811건.json"))
new = json.load(open(sorted(glob.glob("data/eval/results/answer_eval_*_rag-1_6806건_rebuild.json"))[-1]))
items = {it["id"]: it for it in build_inputs(ContextBuilder(), 20)}
om = {r["id"]: r for r in old["rows"]}
E = []
for r in new["rows"]:
    ex, q = items[r["id"]]["messages"][1]["content"].rsplit(f"\n\n{prompts.QUESTION_HEADER}\n", 1)
    a, b = om[r["id"]]["ft_flags"]["refused"], r["ft_flags"]["refused"]
    grp = r["kind"] if r["kind"] == "no_answer" else {(1, 1): "둘다거절", (0, 0): "둘다답함", (1, 0): "해소", (0, 1): "새거절"}[(a, b)]
    E.append({"id": r["id"], "grp": grp, "ov": question_overlap(q, ex), "ref": b, "q": q, "sit": is_situational(q)})
print("\n== C. 평가 그룹별 겹침")
for g in ("둘다거절", "새거절", "해소", "둘다답함", "no_answer"):
    v = [e["ov"] for e in E if e["grp"] == g]
    print(f"   {g:8s} {desc(v)}")
G = [e for e in E if e["grp"] != "no_answer"]
print("\n== D. 경계: 겹침 임계값 t 아래면 거절이라고 볼 때 (신 어댑터 gold 97건)")
best = None
for t in [x / 100 for x in range(5, 50, 1)]:
    tp = sum(e["ref"] and e["ov"] < t for e in G); fp = sum(not e["ref"] and e["ov"] < t for e in G)
    acc = (tp + sum(not e["ref"] and e["ov"] >= t for e in G)) / len(G)
    if best is None or acc > best[0]: best = (acc, t)
    if t in (0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4): print(f"   t={t:.2f}: 아래 {tp+fp}건 중 거절 {tp} ({tp/max(1,tp+fp):.0%}) | 위 {len(G)-tp-fp}건 중 거절 {sum(e['ref'] for e in G)-tp}")
print(f"   정확도 최대 임계값 t={best[1]:.2f} (정확도 {best[0]:.0%}, 기준선 = 전부 답함 {1-sum(e['ref'] for e in G)/len(G):.0%})")
n_ = sum(1 for e in G for f in G if e["ref"] and not f["ref"]); w = sum((e["ov"] < f["ov"]) + 0.5 * (e["ov"] == f["ov"]) for e in G for f in G if e["ref"] and not f["ref"])
print(f"   AUC(겹침이 낮을수록 거절) = {w/n_:.3f}")

print("\n== E. 같은 겹침 구간에서: 학습셋 no_answer 비율 vs 평가 gold 거절률")
rn, ro, rc = binrate(tn), binrate(to), binrate(tc)
print("   구간      | 4811 학습 NA비율 | rebuild 학습 NA비율 | rebuild(원질문) NA비율 | 평가 gold 거절(신)")
for i, (lo, hi) in enumerate(zip(BINS, BINS[1:])):
    s = [e for e in G if lo <= e["ov"] < hi]
    f = lambda x: f"{x[0]:4d}/{x[1]:5d} {x[0]/x[1]:5.1%}" if x[1] else "     -     "
    print(f"   {lo:.1f}~{min(hi,1):.1f}   | {f(ro[i])} | {f(rn[i])} | {f(rc[i])} | {sum(e['ref'] for e in s)}/{len(s)}")

print("\n== F. 평가 거절 문항이 학습 분포의 어디에 있나 (rebuild 기준 백분위)")
P = sorted(r["ov"] for r in tn if not r["na"]); N = sorted(r["ov"] for r in tn if r["na"])
for g in ("둘다거절", "둘다답함"):
    v = [e["ov"] for e in E if e["grp"] == g]
    print(f"   {g}: 중앙 {qt(v,.5):.3f} → 학습 양성의 하위 {pct(P, qt(v,.5)):.1%}, 학습 no_answer의 하위 {pct(N, qt(v,.5)):.1%}")
print(f"   평가 gold 상황형(faq_style 기준): {sum(e['sit'] for e in G)}/{len(G)}, 그중 거절 {sum(e['sit'] and e['ref'] for e in G)} | 비상황형 거절 {sum(not e['sit'] and e['ref'] for e in G)}/{sum(not e['sit'] for e in G)}")
print("\n   둘다거절 32건 (겹침 오름차순)")
for e in sorted([e for e in E if e["grp"] == "둘다거절"], key=lambda e: e["ov"]):
    print(f"     {e['id']} {e['ov']:.2f} {e['q']}")
print("\n   둘다답함 중 겹침 0.20 미만")
for e in sorted([e for e in E if e["grp"] == "둘다답함" and e["ov"] < .2], key=lambda e: e["ov"]):
    print(f"     {e['id']} {e['ov']:.2f} {e['q']}")
