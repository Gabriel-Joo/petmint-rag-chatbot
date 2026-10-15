"""
na_judge.py
no_answer 학습 샘플의 라벨 검사 — 방해 발췌에 답이 실제로 들어 있는지 LLM이 읽고 판정한다(2026-10-14).

배경: search 방식 no_answer 436건 중 215건이 답변 핵심 명사를 50% 이상 담았다. 그러나 포함률(명사 겹침) 0.5 이상 표본 10건을
사람이 읽었을 때 6건이 오탐이었다 — 약관은 같은 어휘가 반복돼 겹침이 쉽게 오른다. 그래서 포함률은 참고 지표로만 남기고,
"이 발췌만 읽고 이 답변을 할 수 있는가"를 직접 판정한다. 답이 들어 있는 발췌에 "확인되지 않음"을 가르치면 라벨 오류다.

- 모델·호출 옵션: 06 심판과 같다(faq_judge.JUDGE_MODEL = gemma4:12b, temperature 0, format json, think 끔, NUM_CTX·NUM_PREDICT).
  프롬프트는 이 판정 전용(NA_JUDGE_SYSTEM) — 06 심판 프롬프트(faq_judge.JUDGE_SYSTEM)는 쓰지도 고치지도 않는다.
- 캐시·재개: 06 셀 4와 같은 구조. 키 = 질문·답변·발췌 글의 해시, SAVE_EVERY건마다 저장, 파싱 실패는 한 번 재시도.
  끊겨도 다시 부르면 캐시에 있는 판정은 건너뛴다. 캐시는 빌드 폴더와 무관하게 하나(data/finetune/na_judge_cache.json)라
  다른 빌드에서 같은 (질문, 답변, 발췌)를 다시 판정하지 않는다.
- 단위: 발췌 하나씩 판정한다(no_answer 샘플은 발췌 1~2개). 발췌 글은 학습 프롬프트에 실제로 들어간 그대로([발췌 N] 라벨·본문·참조).
  샘플 판정 = 발췌 중 yes가 하나라도 있으면 yes, 아니면 unclear가 있으면 unclear, 아니면 no.
- 답변은 06 final에서 (종, unit_id, round, row)로 찾는다 — no_answer 샘플의 목표 답변은 고정 문장이라 원래 답변이 샘플에 없다.

실행:
  python -m data.na_judge run --build-dir=data/finetune/search_base_20261014 [--prompt=v1|v2]      (Ollama gemma4:12b, GPU)
    --prompt: v1 = 첫 프롬프트(기본, 결과 na_judge_results.json), v2 = 내용 포함 기준(결과 na_judge_results_v2.json).
    unclear가 발췌·샘플 중 하나라도 15% 이상이면 종료 코드 3으로 멈춘다(대조로 넘어가지 않도록 `&&`로 잇는다).
  python -m data.na_judge compare --build-dir=... --samples=data/review/na_filtered_samples_drop_0.5_20261014.md \\
         --human-yes=4,8,9,10 --human-no=1,2,3,5,6,7
"""

import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from data import faq_judge, prompts

PROJECT_DIR = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_DIR / "data" / "finetune" / "na_judge_cache.json"
REVIEW_DIR = PROJECT_DIR / "data" / "review"
SAVE_EVERY = 50
VERDICTS = ("yes", "no", "unclear")

NA_JUDGE_SYSTEM = """당신은 반려동물 보험 약관 상담 데이터 검수자입니다. 고객 [질문], 다른 약관 원문을 근거로 작성된 모범 [답변], 검색으로 찾은 [발췌] 하나가 주어집니다.
[발췌]만 읽고 [답변]의 핵심을 말할 수 있는지 판정하세요. [답변]이 맞는지는 판정하지 않습니다.
판정 기준은 "이 발췌만으로 답변의 핵심을 말할 수 있는가"입니다. 답변의 핵심 = 질문에 대한 결론 + 그 결론을 정하는 조건·숫자·기간·대상.
- yes: 발췌에 답변의 핵심이 들어 있어, 이 발췌만 읽은 상담원이 같은 결론과 조건으로 답할 수 있다. 표현이 달라도, 같은 규정이 다른 특약·다른 조에 같은 내용으로 적혀 있어도 yes.
- no: 발췌만으로는 답변의 핵심을 말할 수 없다. 같은 단어·비슷한 주제가 나와도 결론이나 핵심 조건이 없으면 no. 다른 특약·다른 등급이라 한도·비율·기간 같은 핵심 숫자가 답변과 다르면 no.
- unclear: 일부만 들어 있다 — 결론은 있으나 결론을 정하는 핵심 조건·숫자가 빠졌거나, 조건은 있으나 결론을 끌어낼 수 없다.
부분적으로만 들어 있는 경우: 결론과 핵심 조건이 모두 있으면 yes, 둘 중 하나만 있으면 unclear, 둘 다 없으면 no. 답변의 부가 설명(배경, 예시, "확인이 필요합니다" 같은 일반 안내)이 발췌에 없는 것은 판단에 넣지 않습니다.
반드시 JSON 한 개로만 답하세요: {"verdict": "yes" 또는 "no" 또는 "unclear", "reason": "한 문장"}"""

# v2(2026-10-14): v1은 사람 판정 10건 중 5건 일치 — 조문·특약 이름·통원/입원이 다르다는 이유로 no(8·9·10번),
# 정의·일반 원칙만 겹치는데 yes(1번). 기준을 "조문 일치"에서 "내용 포함"으로 다시 쓴다. v1은 지우지 않고 --prompt로 고른다.
NA_JUDGE_SYSTEM_V2 = """당신은 반려동물 보험 약관 상담 데이터 검수자입니다. 고객 [질문], 다른 약관 원문을 근거로 작성된 모범 [답변], 검색으로 찾은 [발췌] 하나가 주어집니다.
[발췌]에 [답변]의 핵심 내용이 들어 있는지 판정하세요. [답변]이 맞는지는 판정하지 않습니다.
판정 기준은 조문 일치가 아니라 내용 포함입니다: "이 발췌 안의 숫자·문장만으로 답변의 핵심 내용을 말할 수 있는가".
답변의 핵심 = 질문이 묻는 것(금액, 비율, 기간, 서류, 절차, 가능 여부, 처리 결과 등)에 대한 결론과, 그 결론을 정하는 숫자·조건.

약관의 특성: 같은 내용이 여러 조문·여러 특약에 거의 같은 문장으로 반복됩니다. 예를 들어 의료비 특약의 보험금 계산 방식과 계산 예시는
통원과 입원, 반려견과 반려묘, 등급(Ⅰ·Ⅱ·Ⅲ) 사이에 같은 문장·같은 숫자로 적혀 있는 경우가 있습니다.
그러므로 조문 번호, 조 제목, 특약 이름, 통원/입원 구분, 반려견/반려묘 구분이 질문·답변과 달라도 그것만으로 no라고 하지 마세요.
발췌의 문장과 숫자를 그대로 적용해 답변과 같은 결론이 나오면 yes입니다.

- yes: 발췌의 숫자·문장만으로 답변의 핵심 내용을 말할 수 있다. 답의 일부만 있어도 그 일부가 답변의 핵심(결론, 또는 결론을 정하는 숫자·조건)이면 yes.
- no: 발췌와 답변이 부수적인 부분만 겹친다 — 같은 단어나 주제, 용어 정의, 배경 설명, 일반 원칙만 있고, 질문이 묻는 것에 대한 결론을
  얻으려면 발췌에 없는 내용을 더해야 한다. 또는 발췌의 숫자(한도·비율·기간 등)를 적용하면 답변과 다른 결론이 나온다.
- unclear: 발췌가 중간에 잘려 판단할 수 없거나, 겹치는 부분이 핵심인지 부수적인지 정말로 가를 수 없을 때만 쓴다.
답변의 부가 설명(예시, "확인이 필요합니다" 같은 일반 안내)이 발췌에 없는 것은 판단에 넣지 않습니다.
반드시 JSON 한 개로만 답하세요: {"verdict": "yes" 또는 "no" 또는 "unclear", "reason": "한 문장"}"""
PROMPTS = {"v1": NA_JUDGE_SYSTEM, "v2": NA_JUDGE_SYSTEM_V2}
UNCLEAR_STOP = 0.15        # 재판정 후 unclear가 이 비율 이상이면(발췌 또는 샘플) 프롬프트가 애매해진 신호 — 대조로 넘어가지 않고 멈춘다


# ---------- 입력 ----------
_EXCERPT = re.compile(r"^\[발췌 (\d+)\] ", re.M)


def split_excerpts(user_content: str) -> tuple[list[str], str]:
    """학습 user 메시지 → ([발췌 글…], 질문). 발췌 글은 '[발췌 N] 라벨'부터 다음 발췌 앞까지(참조 포함)"""
    body, question = user_content.rsplit(f"\n\n{prompts.QUESTION_HEADER}\n", 1)
    body = body.split(prompts.EXCERPT_HEADER + "\n", 1)[1]
    starts = [m.start() for m in _EXCERPT.finditer(body)] + [len(body)]
    return [body[a:b].strip() for a, b in zip(starts, starts[1:])], question.strip()


def excerpt_label(excerpt: str) -> str:
    return _EXCERPT.sub("", excerpt.splitlines()[0]).strip()


def load_items(build_dir: Path) -> list[dict]:
    """no_answer 샘플의 발췌별 판정 단위. 답변은 06 final에서 찾는다(빌드 stats.json의 final_dir)"""
    stats = json.load(open(build_dir / "stats.json", encoding="utf-8"))
    final_dir = Path(stats["final_dir"])
    answers = {}
    for p in final_dir.glob("petmint_*_faq_final.json"):
        for f in json.load(open(p, encoding="utf-8")):
            answers[(f["species"], f["unit_id"], f.get("round"), f.get("row"))] = f
    items = []
    for split in ("train", "val"):
        for line in open(build_dir / f"{split}.jsonl", encoding="utf-8"):
            s = json.loads(line)
            m = s["meta"]
            if m["kind"] != "no_answer":
                continue
            qa = answers[(m["species"], m["unit_id"], m["round"], m["row"])]
            excerpts, question = split_excerpts(s["messages"][1]["content"])
            assert question == qa["question"].strip(), f"질문 불일치: {m['unit_id']}"
            for i, ex in enumerate(excerpts):
                items.append({"sample": f"{split}|{m['species']}|{m['unit_id']}|{m['round']}|{m['row']}",
                              "excerpt_no": i + 1, "n_excerpts": len(excerpts), "species": m["species"],
                              "unit_id": m["unit_id"], "question": question,
                              "answer": prompts.strip_citation(qa["answer"]), "excerpt": ex,
                              "excerpt_label": excerpt_label(ex), "noun_cover_sample": m.get("na_noun_cover")})
    return items


# ---------- 판정 (faq_judge.judge와 같은 호출·옵션) ----------
def build_prompt(it: dict) -> str:
    return f"[질문]\n{it['question']}\n\n[답변]\n{it['answer']}\n\n[발췌]\n{it['excerpt']}"


def judge(prompt: str, system: str = NA_JUDGE_SYSTEM, model: str = faq_judge.JUDGE_MODEL) -> dict:
    body = {"model": model, "system": system, "prompt": prompt, "stream": False, "format": "json", "think": False,
            "options": {"temperature": 0, "num_ctx": faq_judge.NUM_CTX, "num_predict": faq_judge.NUM_PREDICT}}
    r = requests.post(f"{faq_judge.OLLAMA_URL}/api/generate", json=body, timeout=900)
    r.raise_for_status()
    out = r.json()
    used = out.get("prompt_eval_count") or 0
    try:
        j = json.loads(re.search(r"\{.*\}", out.get("response", ""), re.S).group(0))
        v = str(j.get("verdict", "")).strip().lower()
        assert v in VERDICTS
        return {"verdict": v, "reason": j.get("reason"), "prompt_tokens": used, "truncated": used >= faq_judge.PROMPT_BUDGET}
    except Exception:
        return {"verdict": None, "reason": None, "raw": out.get("response", "")[:500],
                "prompt_tokens": used, "truncated": used >= faq_judge.PROMPT_BUDGET}


def cache_key(it: dict, ver: str = "v1") -> str:
    # v1 키는 처음 실행 때 그대로(캐시 재사용) — 다른 프롬프트는 버전을 키에 넣어 섞이지 않게 한다
    base = f"{it['species']}|{it['question']}|{it['answer']}|{it['excerpt']}"
    return hashlib.md5((base if ver == "v1" else f"{ver}|{base}").encode()).hexdigest()


def _renumbered(it: dict):
    """같은 발췌가 학습 프롬프트에서 [발췌 1]이었는지 [발췌 2]였는지만 다른 경우 — 내용이 같으니 판정을 다시 쓰지 않는다"""
    yield it
    m = _EXCERPT.match(it["excerpt"])
    if m:
        for n in ("1", "2"):
            if n != m.group(1):
                yield {**it, "excerpt": f"[발췌 {n}] " + it["excerpt"][m.end():]}


def lookup(cache: dict, it: dict, ver: str) -> dict | None:
    for v in _renumbered(it):
        k = cache_key(v, ver)
        if k in cache:
            return cache[k]
    return None


def judge_item(cache: dict, it: dict, ver: str) -> tuple[dict, bool]:
    """(판정, 새로 불렀나). 캐시(발췌 번호만 다른 것 포함)에 있으면 그대로, 없으면 판정하고 캐시에 넣는다(저장은 호출 측)"""
    hit = lookup(cache, it, ver)
    if hit is not None:
        return hit, False
    p, system = build_prompt(it), PROMPTS[ver]
    res = judge(p, system)
    if res["verdict"] is None:                           # 06과 같이 파싱 실패 한 번 재시도
        res = judge(p, system)
        res["retried"] = True
    cache[cache_key(it, ver)] = res
    return res, True


def require_model():
    tags = {m["name"] for m in requests.get(f"{faq_judge.OLLAMA_URL}/api/tags", timeout=5).json()["models"]}
    assert faq_judge.JUDGE_MODEL in tags, f"{faq_judge.JUDGE_MODEL} 없음 — `docker start ollama` 확인"


def load_cache() -> dict:
    return _load(CACHE_PATH, {})


def save_cache(cache: dict):
    _dump(cache, CACHE_PATH)


def unload_model():
    requests.post(f"{faq_judge.OLLAMA_URL}/api/generate", json={"model": faq_judge.JUDGE_MODEL, "keep_alive": 0}, timeout=60)


def out_paths(build_dir: Path, ver: str) -> tuple[Path, Path]:
    sfx = "" if ver == "v1" else f"_{ver}"
    return build_dir / f"na_judge_results{sfx}.json", build_dir / f"na_judge_summary{sfx}.json"


def _load(p: Path, default):
    return json.load(open(p, encoding="utf-8")) if p.exists() else default


def _dump(obj, p: Path):
    tmp = p.with_suffix(p.suffix + ".tmp")
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tmp.replace(p)


def sample_verdict(vs: list[str | None]) -> str:
    if "yes" in vs:
        return "yes"
    if "unclear" in vs or None in vs:       # 파싱 실패(None)는 unclear로 본다
        return "unclear"
    return "no"


def run(build_dir: Path, ver: str = "v1") -> dict:
    require_model()
    items = load_items(build_dir)
    cache = load_cache()
    todo = sum(lookup(cache, it, ver) is None for it in items)
    print(f"프롬프트 {ver} | no_answer 발췌 {len(items)}개(샘플 {len({it['sample'] for it in items})}건) | 캐시 {len(items) - todo} | 새로 판정 {todo}",
          flush=True)
    t0, n_new, retried = time.time(), 0, 0
    for it in items:
        res, new = judge_item(cache, it, ver)
        if new:
            retried += bool(res.get("retried"))
            n_new += 1
            if n_new % SAVE_EVERY == 0:
                save_cache(cache)
                el = time.time() - t0
                print(f"  {n_new}/{todo} 판정, {el / 60:.1f}분 (건당 {el / n_new:.2f}초, 남은 예상 {(todo - n_new) * el / n_new / 60:.1f}분)",
                      flush=True)
        it.update(res)
    save_cache(cache)
    elapsed = time.time() - t0
    unload_model()

    by_sample = {}
    for it in items:
        by_sample.setdefault(it["sample"], []).append(it["verdict"])
    ex_c = Counter(it["verdict"] for it in items)
    sm_c = Counter(sample_verdict(v) for v in by_sample.values())
    summary = {"build_dir": str(build_dir), "judged_at": datetime.now().isoformat(timespec="seconds"),
               "model": faq_judge.JUDGE_MODEL, "prompt": ver, "excerpts": len(items), "samples": len(by_sample),
               "new_calls": n_new, "retried_parse": retried, "elapsed_sec": round(elapsed, 1),
               "sec_per_call": round(elapsed / n_new, 2) if n_new else None,
               "excerpt_verdicts": dict(ex_c), "sample_verdicts": dict(sm_c),
               "parse_fail": ex_c.get(None, 0), "truncated": sum(bool(it.get("truncated")) for it in items)}
    unc = {"excerpt": ex_c.get("unclear", 0) / len(items), "sample": sm_c.get("unclear", 0) / len(by_sample)}
    summary["unclear_ratio"] = {k: round(v, 4) for k, v in unc.items()}
    summary["unclear_stop"] = max(unc.values()) >= UNCLEAR_STOP
    res_p, sum_p = out_paths(build_dir, ver)
    _dump(items, res_p)
    _dump(summary, sum_p)
    print(render_summary(summary, items))
    print(f"  unclear 비율: 발췌 {unc['excerpt']:.1%} / 샘플 {unc['sample']:.1%} (멈춤 기준 {UNCLEAR_STOP:.0%})")
    print("저장:", res_p, "/", sum_p)
    return summary


def render_summary(s: dict, items: list[dict]) -> str:
    L = [f"\n판정 끝 — 새 호출 {s['new_calls']}회, {s['elapsed_sec'] / 60:.1f}분"
         + (f" (건당 {s['sec_per_call']}초)" if s["sec_per_call"] else "") +
         f", 파싱 실패 재시도 {s['retried_parse']}회, 최종 파싱 실패 {s['parse_fail']}건, 입력 예산 도달 {s['truncated']}건"]
    for name, c, n in (("발췌", s["excerpt_verdicts"], s["excerpts"]), ("샘플", s["sample_verdicts"], s["samples"])):
        L.append(f"  {name} {n}개: " + " / ".join(f"{v} {c.get(v, 0)} ({c.get(v, 0) / n:.1%})" for v in VERDICTS))
    # 참고: 판정별 포함률(샘플 단위, 기존 지표)
    by = {}
    for it in items:
        by.setdefault(it["sample"], it)
    smp = {}
    for it in items:
        smp.setdefault(it["sample"], []).append(it["verdict"])
    for v in VERDICTS:
        cs = sorted(by[k]["noun_cover_sample"] for k, vs in smp.items() if sample_verdict(vs) == v)
        if cs:
            L.append(f"  샘플 판정 {v:7s}: 포함률 평균 {sum(cs) / len(cs):.2f} / 중앙 {cs[len(cs) // 2]:.2f} / 0.5 이상 {sum(c >= 0.5 for c in cs)}건")
    return "\n".join(L)


# ---------- 사람 판정과 대조 ----------
def parse_samples_md(path: Path) -> list[dict]:
    """finetune_data.write_filtered_samples 형식 → [{no, unit_id, cover, question, label}]"""
    out, cur, in_code = [], None, False
    for line in open(path, encoding="utf-8"):
        if cur and line.startswith("```"):
            in_code = not in_code
            continue
        if cur and in_code and "body" not in cur.get("_done", ""):
            cur["body"] = cur.get("body", "") + line
            continue
        if cur and not in_code and "body" in cur:
            cur["_done"] = "body"           # 첫 코드 블록(발췌 본문)만 — 뒤 블록은 참조
        m = re.match(r"^## (\d+)\. (.+) \(포함률 ([\d.]+)\)$", line.strip())
        if m:
            cur = {"no": int(m.group(1)), "unit_id": m.group(2), "cover": float(m.group(3))}
            out.append(cur)
        elif cur and line.startswith("- 질문: "):
            cur["question"] = line[len("- 질문: "):].strip()
        elif cur and line.startswith("- 걸러낸 발췌: "):
            cur["label"] = line[len("- 걸러낸 발췌: "):].strip()
    return out


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def _shown(items: list[dict], s: dict) -> tuple[list[dict], dict]:
    mine = [it for it in items if it["unit_id"] == s["unit_id"] and it["question"] == s["question"]]
    assert mine, f"{s['no']}번을 판정 결과에서 찾지 못함"
    # 같은 조의 두 청크는 라벨이 같다 — 표본 파일의 본문 앞부분으로 사람이 본 발췌를 고른다
    # 한 발췌가 참조로 다른 발췌의 본문을 품을 수 있어, 본문 앞부분이 가장 앞에서 나오는 발췌를 쓴다
    head = _norm(s["body"])[:80]
    shown = sorted((it for it in mine if it["excerpt_label"] == s["label"] and head in _norm(it["excerpt"])),
                   key=lambda it: _norm(it["excerpt"]).index(head))
    assert shown, f"{s['no']}번: 표본에 보인 발췌({s['label']})를 판정 결과에서 찾지 못함"
    return mine, shown[0]


def compare(build_dir: Path, samples_md: Path, human: dict[int, str], ver: str = "v1") -> str:
    items = _load(out_paths(build_dir, ver)[0], None)
    assert items is not None, f"프롬프트 {ver} 판정 결과 없음 — 먼저 run --prompt={ver}"
    prev = _load(out_paths(build_dir, "v1")[0], None) if ver != "v1" else None
    rows, L = [], []
    for s in parse_samples_md(samples_md):
        mine, shown = _shown(items, s)
        r = {**s, "human": human[s["no"]], "llm_shown": shown["verdict"], "reason_shown": shown["reason"],
             "llm_sample": sample_verdict([it["verdict"] for it in mine]),
             "others": [(it["excerpt_label"], it["verdict"], it["reason"]) for it in mine if it is not shown]}
        if prev is not None:
            r["v1_shown"] = _shown(prev, s)[1]["verdict"]
        rows.append(r)
    to_h = {"yes": "답 있음", "no": "답 없음", "unclear": "애매"}
    # unclear는 '답이 있을 수 있음'으로 보고 no_answer에서 걸러낸다(2026-10-14 결정) — 대조에서도 '답 있음' 쪽으로 센다
    agree = lambda r, key: (r[key] != "no") == (r["human"] == "yes")
    has_prev = prev is not None
    L += [f"# no_answer LLM 판정 ↔ 사람 판정 대조 — 프롬프트 {ver} ({samples_md.name})", "",
          "사람은 표본 파일에 보인 발췌 하나(본문 1200자·참조 2개까지 잘림)를 읽었다. 'LLM(그 발췌)'가 같은 발췌의 판정,"
          " 'LLM(샘플)'은 그 샘플의 발췌 전부를 합친 판정(yes 하나라도 → yes)이다. LLM은 잘리지 않은 발췌 글을 받았다.",
          "unclear는 '답 있음'으로 센다(걸러내는 쪽).", "",
          "| # | 사람 | " + ("v1(그 발췌) | " if has_prev else "") + "LLM(그 발췌) | LLM(샘플) | 포함률 | 일치(그 발췌) |",
          "|---|---|" + ("---|" if has_prev else "") + "---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['no']} | {to_h[r['human']]} | " + (f"{r['v1_shown']} | " if has_prev else "") +
                 f"{r['llm_shown']} | {r['llm_sample']} | {r['cover']:.2f} | {'O' if agree(r, 'llm_shown') else 'X'} |")
    n = len(rows)
    a1 = sum(agree(r, "llm_shown") for r in rows)
    a2 = sum(agree(r, "llm_sample") for r in rows)
    unc = sum(r["llm_shown"] == "unclear" for r in rows)
    L += ["", f"- 일치율(그 발췌): **{a1}/{n}** (LLM unclear {unc}건은 '답 있음'으로 셈)",
          f"- 일치율(샘플 전체 판정): {a2}/{n}"]
    if has_prev:
        L.append(f"- v1 일치율(그 발췌, 같은 셈법): {sum(agree(r, 'v1_shown') for r in rows)}/{n}")
    L += [
          f"- 참고 — 포함률 0.5 기준(표본은 전부 0.5 이상이라 모두 '답 있음'으로 본 셈): {sum(r['human'] == 'yes' for r in rows)}/{n}", "",
          "## 판정 근거 (불일치·애매 먼저)", ""]
    for r in sorted(rows, key=lambda r: agree(r, "llm_shown")):
        L += [f"### {r['no']}. 사람 {to_h[r['human']]} / LLM {r['llm_shown']} — {r['unit_id']}", "",
              f"- 질문: {r['question']}", f"- 발췌: {r['label']}", f"- LLM 근거: {r['reason_shown']}"]
        L += [f"- (같은 샘플의 다른 발췌) {lab}: {v} — {why}" for lab, v, why in r["others"]]
        L.append("")
    md = "\n".join(L) + "\n"
    out = REVIEW_DIR / f"na_judge_vs_human_{ver}_{datetime.now():%Y%m%d_%H%M}.md"
    out.write_text(md, encoding="utf-8")
    return md + f"\n저장: {out}\n"


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    opts = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
    cmd = next((a for a in args if not a.startswith("--")), None)
    build_dir = Path(opts["build-dir"])
    ver = opts.get("prompt", "v1")
    assert ver in PROMPTS, f"--prompt는 {'/'.join(PROMPTS)} 중 하나"
    if cmd == "run":
        if run(build_dir, ver)["unclear_stop"]:
            print(f"\n멈춤: unclear 비율이 {UNCLEAR_STOP:.0%} 이상 — 프롬프트가 애매해진 신호. 대조로 넘어가지 않는다.")
            raise SystemExit(3)
    elif cmd == "compare":
        human = {int(x): "yes" for x in opts.get("human-yes", "").split(",") if x} | \
                {int(x): "no" for x in opts.get("human-no", "").split(",") if x}
        print(compare(build_dir, Path(opts["samples"]), human, ver))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
