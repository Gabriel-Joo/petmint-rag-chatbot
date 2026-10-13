"""
answer_eval.py
파인튜닝 답변 평가 — 회귀 세트(data/eval/search_regression.json)의 gold 있는 문항을 정답 발췌와 함께 넣어
베이스 모델과 파인튜닝 모델의 답을 나란히 만든다. 05 FAQ 재생성 여부를 정하기 위한 측정(2026-10-13).

왜 이 문항들인가: 학습 질문(05 FAQ)은 고객 1인칭·상황형이 1%뿐이고 주제가 조문 길이에 비례해 쏠려 있다.
회귀 세트 질문은 상담원 말투의 구어체(원문 문구를 피해서 씀)라, "학습 분포 밖의 고객식 질문"에서 모델이 버티는지 본다.
검색 품질과 섞이지 않게 발췌는 검색 결과가 아니라 gold 청크(evidence가 든 청크 + 그 참조)를 준다.

- 같은 프로세스에서 PeftModel.disable_adapter()로 베이스 답을 만든다(모델을 두 번 올리지 않음).
- 답 없음 거절 확인: val의 no_answer 샘플(방해 발췌만)도 일부 넣어, 확인되지 않는다고 말하는지 본다.
- 자동 표시는 참고용이다(근거 문구 반영·거절·발췌에 없는 조문 번호·근거 표기 누출). 최종 판단은 사람이 md를 읽고 한다.

실행: python -m data.answer_eval [--adapter DIR] [--no-answer 20] [--dry-run]
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from data import prompts
from data import search_regression as R

BASE_DIR = Path(__file__).parent
PROJECT = BASE_DIR.parent
BASE_MODEL_DIR = PROJECT / "models" / "base" / "Tri-7B"
DEFAULT_ADAPTER = PROJECT / "models" / "lora_adapter" / f"{prompts.PROMPT_VERSION}_4811건"
RESULTS_DIR = BASE_DIR / "eval" / "results"
REVIEW_DIR = BASE_DIR / "review"
MAX_NEW_TOKENS = 300


def _flat(t: str) -> str:
    return re.sub(r"[\s「」『』()\[\],.·ㆍ'\"“”]", "", t or "")


def gold_item(case: dict, builder) -> tuple[prompts.ExcerptItem, str]:
    """evidence가 든 gold 청크 1개 + 그 참조(가입 등급 힌트 포함) → (발췌, evidence)"""
    sp, scope = case["species"], R.scope_of(case)
    for g in case["gold"]:
        rows = [c for c in builder.chunks[sp] if R.matches(c, g)]
        hit = [c for c in rows if g.get("evidence") and _flat(g["evidence"]) in _flat(c["content"])]
        for c in hit or rows:
            refs = builder.resolve_references(c, sp, [c], coverage_hint=scope.grade_for(c.get("section_name")))
            return prompts.ExcerptItem.from_search_result({**c, "reference_contents": refs}), g.get("evidence") or ""
    raise ValueError(f"{case['id']}: gold 청크 없음")


def auto_flags(answer: str, excerpt_text: str, evidence: str) -> dict:
    """참고용 자동 표시"""
    refused = prompts.NO_ANSWER_TEXT[:12] in answer or "확인되지 않" in answer
    ev = _flat(evidence)
    ev_hit = bool(ev) and (ev in _flat(answer) or (len(ev) >= 6 and ev[:6] in _flat(answer)))
    cited = set(re.findall(r"제\s*(\d+)\s*조", answer))
    in_excerpt = set(re.findall(r"제\s*(\d+)\s*조", excerpt_text))
    return {"refused": refused, "evidence_hit": ev_hit, "foreign_article": sorted(cited - in_excerpt),
            "citation_leak": bool(re.search(r"근거\s*:", answer)), "chars": len(answer)}


class Generator:
    def __init__(self, adapter_dir: Path):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(BASE_MODEL_DIR)
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                                 bnb_4bit_use_double_quant=True)    # 07 학습과 같은 양자화
        base = AutoModelForCausalLM.from_pretrained(BASE_MODEL_DIR, quantization_config=bnb, device_map="auto", dtype=torch.bfloat16)
        self.model = PeftModel.from_pretrained(base, str(adapter_dir))
        self.model.eval()

    def __call__(self, messages: list[dict], use_adapter: bool) -> str:
        prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tok(prompt, return_tensors="pt", add_special_tokens=False).to(self.model.device)
        with self.torch.no_grad():
            if use_adapter:
                out = self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, pad_token_id=self.tok.pad_token_id)
            else:
                with self.model.disable_adapter():
                    out = self.model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, pad_token_id=self.tok.pad_token_id)
        return self.tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def build_inputs(builder, n_no_answer: int) -> list[dict]:
    items = []
    for case in R.load_cases():
        if not case["gold"]:
            continue
        item, ev = gold_item(case, builder)
        items.append({"id": case["id"], "kind": "gold", "category": case["category"], "species": case["species"],
                      "question": case["query"], "evidence": ev, "label": item.label,
                      "messages": prompts.build_messages(case["query"], [item])})
    val = [json.loads(l) for l in open(BASE_DIR / "finetune" / "val.jsonl", encoding="utf-8")]
    for r in [r for r in val if r["meta"]["kind"] == "no_answer"][:n_no_answer]:
        q = r["messages"][1]["content"].split(prompts.QUESTION_HEADER + "\n")[-1]
        items.append({"id": f"NA{len(items):03d}", "kind": "no_answer", "category": "답없음(val)", "species": r["meta"]["species"],
                      "question": q, "evidence": "", "label": " / ".join(l.split("] ", 1)[1] for l in r["messages"][1]["content"].splitlines()
                                                                         if l.startswith("[발췌 ")),
                      "messages": r["messages"][:2]})
    return items


def summarize(rows: list[dict]) -> dict:
    out = {}
    for kind in ("gold", "no_answer"):
        sub = [r for r in rows if r["kind"] == kind]
        if not sub:
            continue
        for who in ("base", "ft"):
            f = [r[f"{who}_flags"] for r in sub]
            out[f"{kind}|{who}"] = {"n": len(sub), "refused": sum(x["refused"] for x in f),
                                    "evidence_hit": sum(x["evidence_hit"] for x in f) if kind == "gold" else None,
                                    "foreign_article": sum(bool(x["foreign_article"]) for x in f),
                                    "citation_leak": sum(x["citation_leak"] for x in f),
                                    "chars_mean": round(sum(x["chars"] for x in f) / len(f))}
    return out


def write_md(rows: list[dict], summary: dict, path: Path, adapter: str):
    md = ["# 파인튜닝 답변 평가 — 회귀 세트 gold 문항(정답 발췌 제공) + 답 없음 샘플", "",
          f"- 어댑터: `{adapter}` · 프롬프트 `{prompts.PROMPT_VERSION}` · greedy, 최대 {MAX_NEW_TOKENS}토큰",
          "- 자동 표시는 참고용: 거절(정답 발췌가 있는데 확인 안 된다고 함), 근거 반영(evidence 문구가 답에 있음), 외부 조문(발췌에 없는 조 번호), 근거 표기 누출.",
          "- 판정란: `FT 나음` / `같음` / `베이스 나음` / `둘 다 틀림`", "",
          "| 구분 | 모델 | 문항 | 거절 | 근거 반영 | 외부 조문 | 근거 표기 | 평균 길이 |", "|---|---|---|---|---|---|---|---|"]
    for k, s in summary.items():
        kind, who = k.split("|")
        md.append(f"| {kind} | {who} | {s['n']} | {s['refused']} | {s['evidence_hit'] if s['evidence_hit'] is not None else '-'} | "
                  f"{s['foreign_article']} | {s['citation_leak']} | {s['chars_mean']}자 |")
    for r in rows:
        flag = lambda f: " ".join(x for x, on in [("거절", f["refused"]), ("근거반영", f["evidence_hit"]),
                                                   (f"외부조문{f['foreign_article']}", f["foreign_article"]), ("근거누출", f["citation_leak"])] if on) or "-"
        md += ["", "---", f"### {r['id']} [{r['category']}] {r['species']}", f"**질문** {r['question']}", "",
               f"**발췌** {r['label']}" + (f" · evidence: `{r['evidence']}`" if r["evidence"] else ""), "",
               f"**베이스** ({flag(r['base_flags'])}) {r['base']}", "", f"**파인튜닝** ({flag(r['ft_flags'])}) {r['ft']}", "",
               "**판정:** ____________"]
    path.write_text("\n".join(md) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=str(DEFAULT_ADAPTER))
    ap.add_argument("--no-answer", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="모델 없이 입력 조립·토큰 길이만 확인(GPU 안 씀)")
    args = ap.parse_args(argv)
    from data.rag_context import ContextBuilder
    builder = ContextBuilder()
    items = build_inputs(builder, args.no_answer)
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(BASE_MODEL_DIR)
    lens = [len(tok(tok.apply_chat_template(it["messages"], tokenize=False, add_generation_prompt=True), add_special_tokens=False)["input_ids"])
            for it in items]
    print(f"입력 {len(items)}개(gold {sum(i['kind'] == 'gold' for i in items)}, 답없음 {sum(i['kind'] == 'no_answer' for i in items)}) "
          f"| 프롬프트 토큰 최대 {max(lens)} 평균 {sum(lens) // len(lens)}")
    if args.dry_run:
        gen = lambda messages, use_adapter: "(dry-run)"
    else:
        if not Path(args.adapter).exists():
            sys.exit(f"어댑터 없음: {args.adapter}")
        gen = Generator(Path(args.adapter))
    rows = []
    for n, it in enumerate(items, 1):
        excerpt = it["messages"][1]["content"].split(prompts.QUESTION_HEADER)[0]
        base, ft = gen(it["messages"], False), gen(it["messages"], True)
        rows.append({**{k: v for k, v in it.items() if k != "messages"}, "base": base, "ft": ft,
                     "base_flags": auto_flags(base, excerpt, it["evidence"]), "ft_flags": auto_flags(ft, excerpt, it["evidence"])})
        if n % 10 == 0:
            print(f"  {n}/{len(items)}", flush=True)
    summary = summarize(rows)
    tag = "dryrun" if args.dry_run else Path(args.adapter).name
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    jpath = RESULTS_DIR / f"answer_eval_{stamp}_{tag}.json"
    jpath.write_text(json.dumps({"adapter": args.adapter, "summary": summary, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    mpath = (RESULTS_DIR if args.dry_run else REVIEW_DIR) / f"answer_eval_{stamp}_{tag}.md"
    write_md(rows, summary, mpath, args.adapter)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("저장:", jpath, mpath)


if __name__ == "__main__":
    main()
