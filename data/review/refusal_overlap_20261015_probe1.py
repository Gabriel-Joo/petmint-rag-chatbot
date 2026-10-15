# 2026-10-15 거절-겹침 측정 1차(길이·겹침·조 커버리지). 실행: PYTHONPATH=. python data/review/refusal_overlap_20261015_probe1.py <feat.json 출력 경로>
# 기록: data/review/refusal_overlap_20261015.md
import json, glob, re, statistics as st
from collections import Counter, defaultdict
from data import prompts
from data import search_regression as R
from data.answer_eval import gold_item, build_inputs
from data.finetune_data import question_overlap
from data.rag_context import ContextBuilder
from data.search_scope import mentioned_grade, mentioned_type

def q(v, p): v = sorted(v); return v[min(int(len(v) * p), len(v) - 1)]
def desc(v): return f"n={len(v)} mean={st.mean(v):.2f} p10={q(v,.1):.2f} med={q(v,.5):.2f} p90={q(v,.9):.2f}" if v else "n=0"

old = json.load(open("data/eval/results/answer_eval_20261014_1011_rag-1_4811건.json"))
new = json.load(open(sorted(glob.glob("data/eval/results/answer_eval_*_rag-1_6806건_rebuild.json"))[-1]))
REF = "제공된 약관 발췌에서는 확인되지 않는"
print("== 1. 전제 확인: 길이")
for name, d in (("구", old), ("신", new)):
    g = [r for r in d["rows"] if r["kind"] == "gold"]
    ref = [len(r["ft"]) for r in g if r["ft_flags"]["refused"]]
    ans = [len(r["ft"]) for r in g if not r["ft_flags"]["refused"]]
    print(name, "거절", desc(ref), "| 답", desc(ans), "| 전체 평균", round(st.mean(ref + ans)), "| 거절문 고정문장", sum(REF in r["ft"] for r in g if r["ft_flags"]["refused"]))

print("\n== 2. 학습 데이터(rebuild/train.jsonl)")
train = [json.loads(l) for l in open("data/finetune/rebuild/train.jsonl", encoding="utf-8")]
print("시스템 프롬프트 길이 지시:", re.findall(r"답변은[^.]*\.", train[0]["messages"][0]["content"]))
by = defaultdict(list); refusal_kind = Counter(); tr_ov = defaultdict(list); qlen = defaultdict(list)
for s in train:
    k = s["meta"]["kind"]; a = s["messages"][2]["content"]; by[k].append(len(a))
    if REF in a: refusal_kind[k] += 1
    ex, qq = s["messages"][1]["content"].rsplit(f"\n\n{prompts.QUESTION_HEADER}\n", 1)
    tr_ov[k].append(question_overlap(qq, ex)); qlen[k].append(len(qq))
for k, v in by.items(): print(f"  답 길이 {k:10s}", desc(v), "| 거절문 포함", refusal_kind[k])
print("  거절 비율:", f"{sum(refusal_kind.values())}/{len(train)} = {sum(refusal_kind.values())/len(train):.1%}")
gold_ans = by["gold_only"] + by["distract"]
print("  양성 답 중 >150자:", sum(x > 150 for x in gold_ans), "/", len(gold_ans), " >250자:", sum(x > 250 for x in gold_ans))
for k, v in tr_ov.items(): print(f"  질문-발췌 겹침 {k:10s}", desc(v))
for k, v in qlen.items(): print(f"  질문 길이 {k:10s}", desc(v))

print("\n== 3. 평가 문항(같은 지표)")
builder = ContextBuilder()
items = {it["id"]: it for it in build_inputs(builder, 20)}
cases = {c["id"]: c for c in R.load_cases()}
train_units = Counter("|".join(s["meta"]["unit_id"].split("|")[:3]) for s in train if s["meta"]["kind"] != "no_answer")
feat = []
for r in new["rows"]:
    it = items[r["id"]]
    ex, qq = it["messages"][1]["content"].rsplit(f"\n\n{prompts.QUESTION_HEADER}\n", 1)
    f = {"id": r["id"], "kind": r["kind"], "ov": question_overlap(qq, ex), "qlen": len(qq), "exlen": len(ex),
         "base_len": len(r["base"]), "ref_new": r["ft_flags"]["refused"], "base_ref": r["base_flags"]["refused"],
         "graded": bool(mentioned_grade(qq) or mentioned_type(qq)), "cat": r["category"]}
    if r["kind"] == "gold":
        _, _, c = gold_item(cases[r["id"]], builder)
        key = "|".join(str(x) for x in (c.get("section_type") or c.get("section"), c.get("section_name"), c.get("article_num")))
        f["chunk_keys"] = {k: c.get(k) for k in ("section_type", "section", "section_name", "article_num", "article_title", "type")}
        f["unit"] = key; f["unit_n"] = train_units.get(key)
    feat.append(f)
print(" chunk 필드 예:", feat[0]["chunk_keys"], "| train unit 예:", list(train_units)[:3])
G = [f for f in feat if f["kind"] == "gold"]
for lab, sel in (("gold 거절", [f for f in G if f["ref_new"]]), ("gold 답함", [f for f in G if not f["ref_new"]]),
                 ("no_answer", [f for f in feat if f["kind"] == "no_answer"])):
    print(f" {lab:9s} 겹침", desc([f["ov"] for f in sel]))
    print(f" {lab:9s} 질문길이", desc([f["qlen"] for f in sel]), "| 발췌길이", desc([f["exlen"] for f in sel]))
    print(f" {lab:9s} 베이스답길이", desc([f["base_len"] for f in sel]))
print(" 겹침 구간별 gold 거절률:")
for lo, hi in ((0, .3), (.3, .4), (.4, .5), (.5, .6), (.6, 1.01)):
    s = [f for f in G if lo <= f["ov"] < hi]
    print(f"   {lo:.1f}~{min(hi,1):.1f}: {sum(f['ref_new'] for f in s)}/{len(s)}")
print(" 등급어구 gold:", sum(f["ref_new"] for f in G if f["graded"]), "/", sum(f["graded"] for f in G),
      "| 비등급:", sum(f["ref_new"] for f in G if not f["graded"]), "/", sum(not f["graded"] for f in G))
print(" 베이스도 거절한 gold:", sum(f["base_ref"] for f in G), "중 FT 거절", sum(f["base_ref"] and f["ref_new"] for f in G))
print(" 카테고리별 거절:", {c: f"{sum(f['ref_new'] for f in G if f['cat']==c)}/{sum(f['cat']==c for f in G)}" for c in sorted({f['cat'] for f in G})})
json.dump(feat, open(__import__("sys").argv[1], "w"), ensure_ascii=False, indent=1, default=str)
