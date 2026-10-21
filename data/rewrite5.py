"""
rewrite5.py
rebuild5(7단계, 2026-10-21) 학습 QA 손질 — rebuild4 final(data/faq/rebuild4/rw/checked) 7,480건에서 출발한다. 생성·06은 다시 돌리지 않는다.
설정 원본: data/review/rebuild5_stage7_config.md

1. 계산 수리: 【별표3】 변호사비용 계산이 틀린 QA(faq_verify.verify_all 실패 — final 2건, 06에서 버려진 28건)의 답을 코드 값으로 바꾼다.
   버려졌던 것은 같은 (종, 소송목적의 값) 질문을 하나씩만 되살린다(06 중복 규칙 대신)
2. 질문 일상어: 질문에 약관 말(data/synonyms.py policy)이 있으면 "고객은 흔히 say라고 말한다"를 낱말로만 주고 다시 쓴다.
   faq_rewrite와 같은 결정적 검사(06 검사 재실행 — pet_subject 포함)에 더해, 약관 말이 그대로 남으면 실패. 두 번 실패면 원래 질문.
   새 QA를 만들지 않는다(같은 QA의 질문만 바꾼다 — 일상어를 따로 학습하지 않는다)
3. 답 형식 "결론 + 단서": 원문에 단서(다만·단,·제외)가 있는데 답에 없는 QA만, 질문에 해당하는 단서를 '다만'으로 덧붙이게 한다.
   해당 단서가 없으면 모델이 원래 답을 그대로 돌려준다. 숫자 검사(새 숫자 금지·원래 숫자 유지) 뒤 06 심판(gemma4:12b)을 다시 통과해야 채택
4. 바뀐 질문·답은 06 심판으로 재판정 — 문제면 원래로 되돌린다

출력: data/faq/rebuild5/rw/checked/petmint_<종>_faq_final.json (finetune_data --final-dir 입력, 06 final과 같은 모양) +
      data/review/rewrite5_<시각>.md. 중간 저장(재개): data/faq/rebuild5/rw/progress.json

  python -m data.rewrite5 [--limit N]     # qwen3:14b(재작성, think 끔) + gemma4:12b(심판), Ollama
"""

import argparse
import json
import random
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from data import faq_checks, faq_judge, faq_rewrite as RW, faq_verify as V, synonyms

SRC = Path("data/faq/rebuild4/rw/checked")
OUT = Path("data/faq/rebuild5/rw")
SPECIES = ("강아지", "고양이")
MODEL = "qwen3:14b"
SEED = 20261021

_HAS_COND_SRC = re.compile(r"다만|단,|제외")
_HAS_COND_ANS = re.compile(r"다만|단,|제외|경우에는|한하여|한합니다")

ANSWER_SYSTEM = """당신은 반려동물 보험 상담 FAQ의 답변을 다듬는 편집자입니다. [원문]과 [답변]은 이미 검증되었습니다.
[답변]을 "결론 + 단서" 모양으로 고쳐 쓰세요.
- 첫 문장은 질문에 대한 결론입니다. [답변]의 결론(된다·안 된다·금액·기간)을 바꾸지 마세요.
- [원문]에 이 질문의 결론을 제한하거나 바꾸는 조건·예외가 있고 [답변]에 빠져 있으면, '다만'으로 시작하는 문장 하나로 덧붙이세요.
- 질문과 관계없는 조건은 넣지 마세요. 덧붙일 조건이 없으면 [답변]을 한 글자도 바꾸지 말고 그대로 돌려주세요.
- [원문]에 없는 내용·숫자를 새로 만들지 마세요. 전체 2~4문장으로 쓰세요. 조문 번호와 '근거:' 표기는 쓰지 마세요.
- 반드시 JSON 한 개로만 답하세요: {"answer": "고친 답변"}"""

HINT_RULE = ("- 이 질문의 약관 말 {pairs}. 고객이 실제로 쓰는 그 말로 바꿔 쓰세요. 바꾼 말이 [답변]·[원문]과 어긋나면 그 낱말만 "
             "약관 말로 두세요.")


# ---------- 1. 계산 수리 ----------
def lawyer_answer(value: int) -> str:
    """【별표3】 변호사비용 — 코드 계산(limit_table)으로 쓴 답"""
    from app.services.payout import _won, bracket_text
    exp, (base, low, rate) = V.lawyer_fee(value)
    if rate == 0:
        calc = f"정액 {_won(int(base))}"
    else:
        calc = f"{_won(int(base))} + ({_won(value)} − {_won(int(low))}) × {rate * 100:g}% = {_won(int(exp))}"
    return (f"소송목적의 값이 {_won(value)}이면 【별표3】의 {bracket_text(value).split(' · ')[0]} 구간이 적용되어 "
            f"변호사비용은 {calc}입니다. 근거: 【별표3】 소송목적의 값에 따른 변호사비용")


def claim_value(q: str) -> int | None:
    vals = V.money_values(re.sub(r"\(.*?\)", "", q))
    return int(vals[0]) if len(vals) == 1 else None


def repair_calc(final: dict[str, list[dict]]) -> Counter:
    """final 안의 계산 오류는 답을 고치고, 06에서 계산 오류로 버려진 QA는 (종, 값)마다 하나 되살린다(final에 같은 값이 없을 때)"""
    st = Counter()
    for sp in SPECIES:
        have = set()
        for f in final[sp]:
            r = V.verify_all(f, f.get("coverage_type"), f.get("section_name"))
            v = claim_value(f["question"]) if "별표3" in (f.get("section_name") or "") else None
            if r is not None and not r[0] and v:
                f["answer_original"], f["answer"] = f["answer"], lawyer_answer(v)
                f["repair"] = "calc_code"
                st["fixed_in_final"] += 1
            if v:
                have.add(v)
        dropped = json.loads((SRC / f"petmint_{sp}_faq_checked_all.json").read_text(encoding="utf-8"))
        for f in dropped:
            if f.get("decision") != "drop" or "별표3" not in (f.get("section_name") or ""):
                continue
            r = V.verify_all(f, f.get("coverage_type"), f.get("section_name"))
            other = [c for c in f["checks"] if c.get("action") == "drop" and c.get("check") not in ("calc", "judge")]
            v = claim_value(f["question"])
            if r is None or r[0] or other or not v or v in have:
                continue
            have.add(v)
            rec = {k: x for k, x in f.items() if k not in ("checks", "decision")}
            rec["answer_original"], rec["answer"], rec["repair"] = f["answer"], lawyer_answer(v), "calc_code_restored"
            final[sp].append(rec)
            st["restored"] += 1
    return st


# ---------- 2·3. 재작성 ----------
def _call(system: str, prompt: str) -> str:
    raw, _ = RW.call_rewrite(prompt, system)
    return raw


def rewrite_question(f: dict, unit, refs, source) -> dict:
    hints = synonyms.rewrite_hints(f["question"])
    pairs = "; ".join(f"'{p}'은(는) 고객이 흔히 {', '.join(repr(s) for s in say)}(이)라고 말합니다" for p, say in hints)
    paragraphs = [r["paragraph_num"] for r in unit["records"]]
    base = {c["check"] for c in faq_checks.run_checks(f, source, refs, paragraphs) if c["action"] in ("drop", "flag")}
    system = RW.REWRITE_SYSTEM + "\n" + HINT_RULE.format(pairs=pairs)
    prompt = RW.build_rewrite_prompt(f, source)
    attempts = []
    for _ in range(RW.MAX_ATTEMPTS):
        q = RW.parse_question(_call(system, prompt))
        why = RW.attempt_problems(q, 0, f, source, refs, paragraphs, base)
        if q is not None and all(p in q for p, _ in hints):
            why.append("약관 말이 그대로 남음: " + ", ".join(p for p, _ in hints if p in q))
        attempts.append({"question": q, "why": why})
        if not why:
            return {"status": "ok", "question": q, "hints": hints, "attempts": attempts}
    return {"status": "rejected", "question": None, "hints": hints, "attempts": attempts}


def answer_gap(f: dict, source: str) -> bool:
    return bool(_HAS_COND_SRC.search(source)) and not _HAS_COND_ANS.search(faq_checks.answer_body(f["answer"]))


def parse_answer(raw: str) -> str | None:
    try:
        a = json.loads(re.search(r"\{.*\}", raw, re.S).group(0)).get("answer")
    except (AttributeError, json.JSONDecodeError, TypeError):
        return None
    return a.strip() if isinstance(a, str) and a.strip() else None


def answer_problems(new: str, old: str, question: str, source: str, refs: list[dict]) -> list[str]:
    why = []
    pool = old + " " + question + " " + source + " " + " ".join(r.get("content") or "" for r in refs)
    extra = RW._bare_numbers(new) - RW._bare_numbers(pool)
    if extra:
        why.append(f"새 숫자 {sorted(extra)}")
    lost = RW._bare_numbers(old) - RW._bare_numbers(new)
    if lost:
        why.append(f"원래 숫자 빠짐 {sorted(lost)}")
    if RW._has_chinese(new):
        why.append("중국어 섞임")
    if re.search(r"근거\s*:|제\s*\d+\s*조", new) and not re.search(r"제\s*\d+\s*조", old):
        why.append("조문 표기")
    n_sent = len([s for s in re.split(r"(?<=[.!?다요])\s+", new) if s.strip()])
    if n_sent > 4 or len(new) > max(320, 2 * len(old)):
        why.append(f"너무 김({n_sent}문장, {len(new)}자)")
    if new != old and not new.startswith(old.split(". ")[0][:12]):
        why.append("첫 문장(결론)이 바뀜")
    return why


def rewrite_answer(f: dict, source: str, refs: list[dict]) -> dict:
    old = faq_checks.answer_body(f["answer"])
    prompt = (f"[원문] {f.get('section_name') or f.get('section')} {f.get('article_title') or ''}\n{source}\n\n"
              f"[질문]\n{f['question']}\n\n[답변]\n{old}")
    attempts = []
    for _ in range(RW.MAX_ATTEMPTS):
        a = parse_answer(_call(ANSWER_SYSTEM, prompt))
        why = ["JSON 파싱 실패"] if a is None else answer_problems(a, old, f["question"], source, refs)
        attempts.append({"answer": a, "why": why})
        if not why:
            return {"status": "unchanged" if a == old else "ok", "answer": a, "attempts": attempts}
    return {"status": "rejected", "answer": None, "attempts": attempts}


def citation(answer: str) -> str:
    m = re.search(r"\s*근거\s*:.*$", answer, re.DOTALL)
    return m.group(0) if m else ""


def process(f: dict, idx, do_q: bool, do_a: bool) -> dict:
    u, refs, source = idx.get(f["species"], f["unit_id"])
    rec = {"key": RW.record_key(f), "question_original": f["question"]}
    cur = dict(f)
    if do_q:
        rq = rewrite_question(f, u, refs, source)
        rec["q"] = rq
        if rq["status"] == "ok":
            cur["question"] = rq["question"]
    if do_a:
        ra = rewrite_answer(cur, source, refs)
        rec["a"] = ra
        if ra["status"] == "ok":
            cur["answer"] = ra["answer"] + citation(f["answer"])
    if cur["question"] != f["question"] or cur["answer"] != f["answer"]:
        j = faq_judge.judge(faq_judge.build_judge_prompt(cur, source, refs, faq_checks.answer_body(cur["answer"])))
        rec["rejudge"] = j
        if j.get("problem") is not False:              # 문제·파싱 실패 → 원래로(질문만 바꾼 경우는 원래 질문, 둘 다면 둘 다)
            cur = dict(f)
    rec["question"], rec["answer"] = cur["question"], cur["answer"]
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="시험용 — 대상 QA 앞 N건만 재작성")
    args = ap.parse_args()
    RW.set_model(MODEL)
    RW._assert_model(MODEL)
    final = {sp: json.loads((SRC / f"petmint_{sp}_faq_final.json").read_text(encoding="utf-8")) for sp in SPECIES}
    st = Counter(repair_calc(final))
    idx = RW.UnitIndex(list(SPECIES))
    progress_path = OUT / "progress.json"
    done = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {}
    todo = []
    for sp in SPECIES:
        for f in final[sp]:
            if f.get("repair"):
                continue
            u, refs, source = idx.get(sp, f["unit_id"])
            if u is None:
                continue
            do_q, do_a = bool(synonyms.rewrite_hints(f["question"])), answer_gap(f, source)
            if do_q or do_a:
                todo.append((f, do_q, do_a))
    st["target_question"] = sum(1 for _, q, _ in todo if q)
    st["target_answer"] = sum(1 for _, _, a in todo if a)
    if args.limit:
        random.Random(SEED).shuffle(todo)
        todo = todo[: args.limit]
    print(f"대상 {len(todo)}건(질문 {st['target_question']} · 답 {st['target_answer']}), 이미 {len(done)}건", flush=True)
    t0, n = time.time(), 0
    for f, do_q, do_a in todo:
        k = f"{RW.record_key(f)}|{f['question']}"
        if k not in done:
            done[k] = process(f, idx, do_q, do_a)
            n += 1
            if n % 50 == 0:
                RW._dump(done, progress_path)
                print(f"{n}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
        r = done[k]
        q_ok, a_ok = r["question"] != f["question"], r["answer"] != f["answer"]
        st["q_changed"] += q_ok
        st["a_changed"] += a_ok
        st["q_status_" + r.get("q", {}).get("status", "-")] += do_q
        st["a_status_" + r.get("a", {}).get("status", "-")] += do_a
        st["reverted_rejudge"] += bool(r.get("rejudge")) and r["rejudge"].get("problem") is not False
        f.update({"question_rw4": f["question"], "question": r["question"], "answer_rw4": f["answer"], "answer": r["answer"]}
                 if (q_ok or a_ok) else {})
    RW._dump(done, progress_path)
    for sp in SPECIES:
        RW._dump(final[sp], OUT / "checked" / f"petmint_{sp}_faq_final.json")
    st["minutes"] = round((time.time() - t0) / 60, 1)
    st["total_final"] = sum(len(v) for v in final.values())
    st["pet_subject_flag"] = sum(bool(faq_checks.check_pet_subject(f["question"])) for v in final.values() for f in v)
    report(st, done, todo)
    print(json.dumps(dict(st), ensure_ascii=False))


def report(st: Counter, done: dict, todo: list):
    path = Path("data/review") / f"rewrite5_{datetime.now():%Y%m%d_%H%M}.md"
    L = ["# rebuild5 학습 QA 손질(rewrite5)", "", "```", json.dumps(dict(st), ensure_ascii=False, indent=1), "```", "",
         "## 바뀐 예(무작위 30)", ""]
    changed = [r for r in done.values() if r["question"] != r["question_original"] or r.get("a", {}).get("status") == "ok"]
    for r in random.Random(SEED).sample(changed, min(30, len(changed))):
        L += [f"- 질문: {r['question_original']}", f"  - → {r['question']}"]
        if r.get("a", {}).get("status") == "ok":
            L += [f"  - 답: {r['answer'][:300]}"]
        if r.get("rejudge"):
            L += [f"  - 재심판: {r['rejudge'].get('problem')} {r['rejudge'].get('types')}"]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("리포트:", path)


if __name__ == "__main__":
    main()
