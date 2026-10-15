"""
na_qjudge.py
no_answer 라벨의 질문 기준 판정 — "이 발췌만 읽고 질문에 (일부라도) 맞게 답할 수 있는가"(2026-10-15).

na_judge(v2)와 다른 점:
- 원래 답변을 판정기에게 보여주지 않는다. na_judge는 [답변]의 핵심이 발췌에 있는지를 물어, 답변 전체가 있어야 yes로 보는
  쪽으로 엄격해졌다(표본: "해지할 수 있다는 내용은 있으나 … 지급한다는 내용은 없다" → no). no_answer 라벨이 묻는 것은
  "이 질문에 이 발췌로 답할 수 있는가"이므로 기준을 질문으로 둔다.
- 3단계: full(답할 수 있다) / partial(묻는 것의 일부·결론·핵심 조건 하나는 답할 수 있다) / none.
- full·partial이면 답이 되는 발췌 문구를 그대로 인용하게 하고, 인용이 발췌에 실제로 있는지 기계적으로 대조한다(quote_ok).
- 캐시는 na_judge와 따로 둔다(data/finetune/na_qjudge_cache.json). 같은 캐시를 쓰면 독립된 검사가 아니다.
- 모델·호출 옵션은 06 심판과 같다(faq_judge.JUDGE_MODEL, temperature 0, format json, think 끔). 모델이 같으므로
  완전히 독립된 판정은 아니다 — 프롬프트·입력(답변 없음)·캐시가 다르다.

실행:
  python -m data.na_qjudge sample --build-dir=data/finetune/rebuild [--n=200 --seed=20261015]
    → 표본의 발췌별 판정 + na_judge와 어긋난 샘플만 md로 (data/review/na_qjudge_<빌드>_<n>_<시각>.md/.json)
"""

import hashlib
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import requests

from data import faq_judge
from data.na_judge import _dump, _load, require_model, unload_model

PROJECT_DIR = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_DIR / "data" / "finetune" / "na_qjudge_cache.json"
REVIEW_DIR = PROJECT_DIR / "data" / "review"
SAVE_EVERY = 25
VERDICTS = ("full", "partial", "none")
KO = {"full": "있음", "partial": "일부", "none": "없음", None: "파싱 실패"}

QJUDGE_SYSTEM = """당신은 반려동물 보험 약관 상담 데이터 검수자입니다. 고객 [질문]과 약관 [발췌] 하나가 주어집니다.
[발췌]만 읽은 상담원이 [질문]에 맞는 답을 할 수 있는지 판정하세요. 발췌 밖의 지식은 쓰지 않습니다.

- full: 질문이 묻는 것에 대한 결론을 발췌의 문장·숫자만으로 말할 수 있다.
- partial: 질문이 묻는 것의 일부는 발췌로 답할 수 있다 — 여러 가지를 묻는 질문 중 하나, 결론은 있으나 조건이 빠진 경우,
  결론을 정하는 조건·숫자·기간 하나만 있는 경우.
- none: 발췌로는 질문이 묻는 것에 답할 수 없다. 같은 단어나 같은 주제, 용어 정의, 배경 설명만 있고 질문이 묻는 것에 대한
  내용이 없으면 none.

주의:
- 같은 규정이 여러 특약·조문에 같은 문장으로 적혀 있다. 문장이 같은 규정이면 특약 이름·조 번호가 질문과 달라도 답할 수 있는 것으로 본다.
- 다만 한도·비율·기간처럼 특약·등급·통원/입원·반려견/반려묘마다 다른 숫자는, 질문이 지정한 대상의 숫자가 아니면 답이 아니다.
- 계산을 해야만 나오는 답이라도 발췌에 계산 방식과 필요한 숫자가 모두 있으면 답할 수 있는 것으로 본다.

full 또는 partial이면 답이 되는 발췌 문구를 발췌에서 그대로 옮겨 적으세요(고치거나 요약하지 말 것).
반드시 JSON 한 개로만 답하세요: {"verdict": "full" 또는 "partial" 또는 "none", "quote": "발췌에서 그대로 옮긴 문구(none이면 빈 문자열)", "reason": "한 문장"}"""


# q2(2026-10-15): q1은 rebuild 표본 200건에서 73건을 잡았으나 10건을 읽어 보니 4건이 과했다 — 비슷한 조항(선천적·유전적 질병)을
# 질문(기왕증)의 답으로 보거나, 해지 '조건'을 해지 '후 조치'의 답으로 봤다. 인용 문구가 발췌에 없는 판정도 96건 중 10건.
# 고친 것: (1) "비슷한 조항"과 "질문에 답이 됨"을 가르는 예시를 넣는다 (2) 인용이 발췌에 그대로 없으면 판정을 인정하지 않는다
# (한 번 다시 묻고, 그래도 없으면 none + quote_fail — 근거 없는 주장은 판정이 아니다). 기준(질문, 답변 미제공)은 q1과 같다.
QJUDGE_SYSTEM_V2 = """당신은 반려동물 보험 약관 상담 데이터 검수자입니다. 고객 [질문]과 약관 [발췌] 하나가 주어집니다.
[발췌]만 읽은 상담원이 [질문]이 묻는 바로 그것에 맞는 답을 할 수 있는지 판정하세요. 발췌 밖의 지식은 쓰지 않습니다.

- full: 질문이 묻는 것에 대한 결론을 발췌의 문장·숫자만으로 말할 수 있다.
- partial: 질문이 묻는 것의 일부는 발췌로 답할 수 있다 — 여러 가지를 묻는 질문 중 하나, 결론은 있으나 조건이 빠진 경우,
  결론을 정하는 조건·숫자·기간 하나만 있는 경우.
- none: 발췌로는 질문이 묻는 것에 답할 수 없다.

가장 중요한 구분 — "비슷한 조항이 있다"는 "질문에 답이 된다"가 아니다:
- 질문 "가입 전부터 앓던 병도 보상되나요?" / 발췌 "반려동물의 선천적, 유전적 질병에 의한 손해(보험계약 이전부터 인지할 수 있는 증상 포함)"
  → none. 선천적·유전적 질병 조항이지, 가입 전에 이미 발병한 질병(기왕증) 조항이 아니다. 발췌에 "보험계약일 이전에 이미 발병한 질병"이 있어야 답이 된다.
- 질문 "알릴 의무 위반으로 계약이 해지되면 회사는 무엇을 해 주나요?" / 발췌 "회사는 그 사실을 안 날부터 1개월 이내에 계약을 해지할 수 있다"
  → none. 질문은 해지 '후'의 처리(환급금 등)를 묻는데, 발췌는 해지할 수 있는 '조건'만 말한다.
- 질문 "보장 제한은 언제부터 적용되나요?" / 발췌 "부담보 기간은 1개월부터 5년 또는 계약의 보험기간"
  → none. 질문은 시작 시점을, 발췌는 기간의 길이를 말한다.
- 질문 "투견으로 쓰다가 다친 병원비도 받을 수 있나요?" / 발췌 "투견 등 흥행 목적으로 사육하는 개는 가입 대상이 아닙니다"
  → full. 표현은 달라도 질문에 대한 결론(받을 수 없다)이 발췌에서 바로 나온다.
- 질문 "변호사 비용 한도가 얼마인가요?" / 발췌 "별표3의 한도 내에서 실제 부담한 보수 중 자기부담금 10만원 초과분" (별표3 표는 없음)
  → partial. 한도를 정하는 방식과 자기부담금은 있으나 한도 금액은 없다.
같은 단어나 같은 주제, 용어 정의, 배경 설명만 있으면 none이다.

그 밖의 주의:
- 같은 규정이 여러 특약·조문에 같은 문장으로 적혀 있다. 문장이 같은 규정이면 특약 이름·조 번호가 질문과 달라도 답할 수 있는 것으로 본다.
- 한도·비율·기간처럼 특약·등급·통원/입원·반려견/반려묘마다 다른 숫자는, 질문이 지정한 대상의 숫자가 아니면 답이 아니다.

full 또는 partial이면 질문에 답이 되는 발췌 문구를 발췌에서 한 군데, 글자 그대로 옮겨 적으세요(고치거나 줄이거나 이어 붙이지 말 것).
그대로 옮길 문구가 없다면 답이 되지 않는 것이므로 none입니다.
반드시 JSON 한 개로만 답하세요: {"verdict": "full" 또는 "partial" 또는 "none", "quote": "발췌에서 그대로 옮긴 문구(none이면 빈 문자열)", "reason": "한 문장"}"""
PROMPTS = {"q1": QJUDGE_SYSTEM, "q2": QJUDGE_SYSTEM_V2}
CONFIRM_MODEL = "qwen3:14b"     # 확인 검사 — 라벨링(JUDGE_MODEL)과 다른 모델. Apache 2.0, 로컬


def _flat(t: str) -> str:
    return re.sub(r"\s+", "", t or "")


def build_prompt(question: str, excerpt: str) -> str:
    return f"[질문]\n{question}\n\n[발췌]\n{excerpt}"


def cache_key(question: str, excerpt: str, ver: str = "q1", model: str = faq_judge.JUDGE_MODEL) -> str:
    # q1 키는 첫 실행 그대로(캐시 재사용). 다른 버전·모델은 키에 넣어 섞이지 않게 한다
    tag = ver if model == faq_judge.JUDGE_MODEL else f"{ver}@{model}"
    return hashlib.md5(f"{tag}|{question}|{excerpt}".encode()).hexdigest()


def quote_ok(res: dict, excerpt: str) -> bool | None:
    if res["verdict"] in (None, "none"):
        return None
    return bool(res["quote"]) and _flat(res["quote"]) in _flat(excerpt)


def judge_checked(question: str, excerpt: str, ver: str = "q2", model: str = faq_judge.JUDGE_MODEL) -> dict:
    """q2부터: 파싱 실패·인용 불일치는 한 번 다시 묻는다. 그래도 인용이 발췌에 없으면 판정을 인정하지 않는다(none + quote_fail)"""
    res = judge(question, excerpt, ver, model)
    if res["verdict"] is None or quote_ok(res, excerpt) is False:
        res = {**judge(question, excerpt, ver, model), "retried": True}
    if quote_ok(res, excerpt) is False:
        res = {**res, "verdict": "none", "quote_fail": True, "claimed": res["verdict"]}
    return res


def judge(question: str, excerpt: str, ver: str = "q1", model: str = faq_judge.JUDGE_MODEL) -> dict:
    body = {"model": model, "system": PROMPTS[ver], "prompt": build_prompt(question, excerpt), "stream": False,
            "format": "json", "think": False,
            "options": {"temperature": 0, "num_ctx": faq_judge.NUM_CTX, "num_predict": faq_judge.NUM_PREDICT}}
    r = requests.post(f"{faq_judge.OLLAMA_URL}/api/generate", json=body, timeout=900)
    r.raise_for_status()
    out = r.json()
    used = out.get("prompt_eval_count") or 0
    res = {"verdict": None, "quote": "", "reason": None, "prompt_tokens": used, "truncated": used >= faq_judge.PROMPT_BUDGET}
    try:
        j = json.loads(re.search(r"\{.*\}", out.get("response", ""), re.S).group(0))
        v = str(j.get("verdict", "")).strip().lower()
        assert v in VERDICTS
        res.update(verdict=v, quote=str(j.get("quote") or ""), reason=j.get("reason"))
    except Exception:
        res["raw"] = out.get("response", "")[:500]
    return res


def sample_verdict(vs: list) -> str | None:
    """샘플 = 발췌 중 가장 강한 판정. 파싱 실패가 있으면 None(사람이 본다)"""
    if None in vs:
        return None
    return "full" if "full" in vs else "partial" if "partial" in vs else "none"


def load_samples(build_dir: Path, ver: str = "v2") -> dict[str, list[dict]]:
    """na_judge 결과(발췌 단위)를 샘플별로 묶는다 — 질문·발췌·na_judge 판정만 쓰고 답변은 쓰지 않는다"""
    by = defaultdict(list)
    for it in _load(build_dir / f"na_judge_results_{ver}.json", []):
        by[it["sample"]].append(it)
    return {k: sorted(v, key=lambda x: x["excerpt_no"]) for k, v in by.items()}


def run_sample(build_dir: Path, n: int, seed: int, ver: str = "q1") -> Path:
    require_model()
    samples = load_samples(build_dir)
    pick = random.Random(seed).sample(sorted(samples), n)     # na_label_review_200_20261015.md와 같은 표본
    cache = _load(CACHE_PATH, {})
    rows, new, t0 = [], 0, time.time()
    for i, key in enumerate(pick, 1):
        exs = []
        for it in samples[key]:
            k = cache_key(it["question"], it["excerpt"], ver)
            if k not in cache:
                if ver == "q1":
                    res = judge(it["question"], it["excerpt"])
                    if res["verdict"] is None:
                        res = {**judge(it["question"], it["excerpt"]), "retried": True}
                else:
                    res = judge_checked(it["question"], it["excerpt"], ver)
                cache[k] = res
                new += 1
                if new % SAVE_EVERY == 0:
                    _dump(cache, CACHE_PATH)
            res = cache[k]
            exs.append({"excerpt_no": it["excerpt_no"], "label": it["excerpt_label"], "excerpt": it["excerpt"],
                        "na_judge": it["verdict"], "na_reason": it["reason"], **res, "quote_ok": quote_ok(res, it["excerpt"])})
        rows.append({"no": i, "sample": key, "unit_id": samples[key][0]["unit_id"], "question": samples[key][0]["question"],
                     "na_judge": "yes" if any(e["na_judge"] == "yes" for e in exs) else "no",
                     "qjudge": sample_verdict([e["verdict"] for e in exs]), "excerpts": exs})
        if i % 20 == 0:
            print(f"  {i}/{n} (새 판정 {new}, {time.time() - t0:.0f}초)", flush=True)
    _dump(cache, CACHE_PATH)
    unload_model()
    return write_report(build_dir, rows, n, seed, ver)


def write_report(build_dir: Path, rows: list[dict], n: int, seed: int, ver: str = "q1") -> Path:
    cnt = Counter(r["qjudge"] for r in rows)
    # na_judge는 이 빌드의 no_answer를 전부 no로 통과시켰다 — 어긋남 = 질문 기준 판정이 none이 아닌 것(파싱 실패 포함)
    off = [r for r in rows if r["qjudge"] != "none"]
    bad_quote = [r for r in off if any(e["verdict"] in ("full", "partial") and not e["quote_ok"] for e in r["excerpts"])]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = REVIEW_DIR / f"na_qjudge_{ver}_{build_dir.name}_{n}_{stamp}"
    _dump({"build_dir": str(build_dir), "n": n, "seed": seed, "prompt": ver, "model": faq_judge.JUDGE_MODEL, "counts": dict(cnt),
           "rows": rows}, base.with_suffix(".json"))
    L = [f"# no_answer 질문 기준 판정 — na_judge와 어긋난 샘플 ({build_dir.name}, 표본 {n}건)", "",
         f"- 표본: no_answer 전체에서 `random.Random({seed}).sample` {n}건. 판정기 {faq_judge.JUDGE_MODEL}, 프롬프트 `{ver}`(원래 답변 없음).",
         "- na_judge(v2)는 이 표본을 전부 no(답 없음)로 판정했다. 아래는 질문 기준 판정이 **없음이 아닌** 샘플 — 어긋난 것만 싣는다.",
         f"- 질문 기준 판정: 있음 {cnt.get('full', 0)} · 일부 {cnt.get('partial', 0)} · 없음 {cnt.get('none', 0)}"
         + (f" · 파싱 실패 {cnt[None]}" if cnt.get(None) else "") + f" → **어긋남 {len(off)}/{n} ({len(off) / n:.1%})**",
         f"- 인용 대조: 있음·일부 판정의 인용 문구가 발췌에 그대로 없는 샘플 {len(bad_quote)}건(⚠ 표시) — 판정기가 문구를 지어냈을 수 있다.",
         "- 사람 판정란: `라벨 맞음`(답 없음 — na_judge가 맞다) / `일부` / `있음`", ""]
    for r in off:
        warn = " ⚠ 인용 불일치" if r in bad_quote else ""
        L += ["---", f"## {r['no']}. 질문 기준 {KO[r['qjudge']]}{warn} — {r['unit_id']}", "", f"**[질문]** {r['question']}", ""]
        for e in r["excerpts"]:
            ex = re.sub(r"\n{3,}", "\n\n", e["excerpt"])
            L += [f"**[발췌 {e['excerpt_no']}/{len(r['excerpts'])}]** {e['label']} — 질문 기준 **{KO[e['verdict']]}**", "```", ex, "```"]
            if e["verdict"] in ("full", "partial"):
                L.append(f"- 인용{'' if e['quote_ok'] else ' (⚠ 발췌에 없음)'}: `{e['quote']}`")
            L += [f"- 질문 기준 근거: {e['reason']}", f"- na_judge: {e['na_judge']} — {e['na_reason']}", ""]
        L += ["**사람 판정:** ______", ""]
    md = base.with_suffix(".md")
    md.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps({"counts": {KO[k]: v for k, v in cnt.items()}, "off": len(off), "bad_quote": len(bad_quote)}, ensure_ascii=False))
    print("저장:", md, base.with_suffix(".json"))
    return md


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    opts = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
    cmd = next((a for a in args if not a.startswith("--")), None)
    if cmd == "sample":
        run_sample(Path(opts["build-dir"]), int(opts.get("n", 200)), int(opts.get("seed", 20261015)), opts.get("prompt", "q1"))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
