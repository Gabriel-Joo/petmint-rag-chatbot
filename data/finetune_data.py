"""
finetune_data.py
07 파인튜닝 학습 샘플 생성 — 06 최종 FAQ를 RAG 추론과 같은 형식(data/prompts.py)의 chat 샘플로 바꾼다.

C안(2026-10-13 확정): 실제 RAG 상황처럼 발췌를 주고, 검색이 빗나갔을 때 지어내지 않는 법도 가르친다.
- distract 70%: 정답 발췌 + 방해 발췌 1~2개(순서 섞음) → 원래 답변
- gold_only 20%: 정답 발췌만 → 원래 답변
- no_answer 10%: 방해 발췌만(최대 2개) → prompts.NO_ANSWER_TEXT (코드가 정한 고정 문장, LLM 생성 아님)
정답 발췌 = 05가 그 QA를 만들 때 본 단위 원문 + 참조(unit_id로 복원, prompts.ExcerptItem.from_unit).
방해 발췌 = 그 질문으로 실제 검색한 결과(SearchScope.unrestricted — 고객 없는 일반 질문) 중 정답 단위가 아닌 것.
val은 unit_id 단위로 나눈다 — 같은 단위를 다른 표현으로 물은 QA가 train·val에 갈라지면 val loss가 과대평가된다.
목표 답변은 "근거: …"를 뗀다(prompts.strip_citation) — 근거 표기는 서비스에서 코드가 단다.
사람 대상 조항(faq_units.is_human_target — 보통약관 기본계약 전용 조문·장해분류표 등)의 QA는 뺀다(2026-10-13 확정).

방해 발췌 거르기는 샘플 종류마다 엄격도가 다르다(2026-10-13 첫 생성 측정):
- no_answer(엄격): 방해 발췌에 답이 섞이면 "있는 답을 없다고 하라"를 가르친다 → 본문+참조 전부에서 답변과 8자 이상 겹치면 제외,
  정답 단위와 40자 이상 겹치면 제외(통원↔입원 반복 문장), 정답과 같은 조(조번호 없는 별표·안내는 같은 문서)도 제외.
- distract(완화): 정답 발췌가 함께 있으므로 방해에 답 비슷한 내용이 있어도 틀린 답을 가르치지 않는다 → 방해 청크 본문만 보고
  답변과 20자, 정답 단위와 40자 이상 겹치면 제외. 8자 기준을 그대로 쓰면 '정하지 않은 사항은', '계약자나 피보험자는' 같은
  상투구에 걸려 방해 후보가 사라졌다(1개 이상 남은 QA 60% → distract 41%에 그침, 목표 70%).
- 종류 배정은 자격을 먼저 세고 한다: 방해 후보가 없고 엄격 후보만 있는 QA를 no_answer에 먼저 쓴다(그래야 distract 몫이 남는다).

no_answer 방해 발췌 고르는 방식(--distractor, 2026-10-14):
- legacy: 위 엄격 거르기(pick_distractors strict) — 비교용으로 남긴다.
- search: 검색 순위 그대로 쓰고 정답 단위(같은 unit_id)와 "답이 글자로 들어 있는 것"만 뺀다(pick_search_distractors).
  측정(첫 학습 데이터 5,343건): 질문-발췌 바이그램 겹침이 양성 0.58~0.59 vs no_answer 0.34 — 겹침만 보고 거절을 배울 수 있었다.
  검색 캐시로 시뮬레이션(QA 4,356건, 첫 2개 발췌 본문만): 엄격 0.31 / 정답 단위만 제외 0.44 / 정답 단위 + 답변 20자·정답 40자 제외 0.39
  (정답 단위 본문 0.49). 정답 단위만 빼면 발췌의 61%가 답변 핵심 명사를 60% 이상 담았다 — 통원↔입원 같은 문장, 같은 조의 옆 청크처럼
  실제로 답이 들어 있는 경우라 "있는 답을 없다고 하라"를 가르친다. 그래서 같은 조 제외와 글자 겹침 관문(답변 20자·정답 단위 40자,
  distract와 같은 기준)은 둔다. 같은 조 제외가 겹침을 낮추는 폭은 0.005뿐이었다(시뮬레이션 0.386 → 0.381).
- search + 답 포함 거르기(--na-cover-max, 2026-10-14): 위 거르기로도 no_answer 436건 중 215건이 답변 핵심 명사를 50% 이상 담았고,
  표본 6건 중 1건은 실제로 답이 들어 있었다 — 라벨 오류다. 발췌(본문+참조)의 핵심 명사 포함률이 기준값 이상이면 no_answer로 쓰지 않는다.
  기준값은 포함률 분포(빌드 출력 '구간별')를 보고 사람이 정한다. 0이면 끈다(기존 search와 같은 결과).
  거른 만큼을 어떻게 할지(--na-fill)도 사람이 고른다 — 기준값을 주면 반드시 지정해야 한다:
    drop   : 기준값 0일 때와 같은 배정을 두고, 기준 이상인 no_answer 샘플만 버린다(no_answer가 그만큼 적어진다. 그 QA는 학습에서 빠진다)
    refill : 후보 단계에서 거른다 — 같은 QA의 다음 순위 검색 결과, 그것도 없으면 다른 QA가 no_answer 몫(10%)을 채운다
  걸러낸 발췌 표본은 <out-dir>/na_filtered_samples.md에 남긴다.
- search + LLM 판정 거르기(--na-judge v1|v2, 2026-10-14): 포함률(명사 겹침)은 표본 10건 중 6건이 오탐 — 깨끗한 분리점이 없었다.
  data/na_judge.py가 "이 발췌만 읽고 답변의 핵심을 말할 수 있는가"를 발췌 하나씩 판정한다(gemma4:12b, 캐시 공유). 판정이 no가 아닌
  발췌(yes·unclear·파싱 실패)는 no_answer로 쓰지 않는다 — unclear는 답이 있을 수 있다고 보고 거른다(2026-10-14 결정).
  --na-cover-max와 같이 쓸 수 없다(둘 중 하나를 고른다). --na-fill은 필수:
    drop   : 배정은 그대로, 앞 2개 발췌 중 하나라도 no가 아니면 그 no_answer 샘플을 버린다
    refill : 배정 후 no_answer QA마다 검색 순위대로 판정해 no인 발췌 2개를 채운다(같은 QA의 다음 순위). 하나도 없으면 그 QA는
             gold_only로 돌리고, 배정 순서상 다음 gold_only QA(no_answer 자격 있음)가 그 몫을 채운다
  배정이 끝난 no_answer QA만 판정하므로 판정 호출은 no_answer 몫(10%) 근처에서 끝난다. Ollama(gemma4:12b)가 떠 있어야 한다.
  빌드 끝에 na_judge.run으로 실제 train/val의 no_answer 발췌를 다시 판정해(대부분 캐시) <out-dir>/na_judge_summary_<ver>.json을 남긴다
  — rebuild.py 빌드 검사의 라벨 정합성 기준이 이것을 읽는다.

실행: python -m data.finetune_data [--search-only] [--distractor legacy|search] [--final-dir DIR] [--out-dir DIR]
     (검색은 GPU 필요, 결과는 cache에 저장해 재실행 시 재사용)
"""

import argparse
import hashlib
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

from data import prompts
from data.faq_units import is_human_target, make_units, unit_id
from data.rag_context import _flat_cite, graph_key
from data.search_scope import SearchScope

BASE_DIR = Path(__file__).parent
FINAL_FILES = {sp: BASE_DIR / "faq" / "checked" / f"petmint_{sp}_faq_final.json" for sp in ("강아지", "고양이")}
OUT_DIR = BASE_DIR / "finetune"
SEARCH_CACHE = OUT_DIR / "search_cache.json"     # 질문 문자열 키 — 출력 폴더가 달라도 같은 캐시를 쓴다
DISTRACTOR_MODES = ("legacy", "search")
NA_NOUN_COVER_MAX = 0.0    # search no_answer 답 포함 거르기 기준(핵심 명사 포함률). 0 = 끔. 값은 분포를 보고 사람이 정한다
NA_FILL_MODES = ("drop", "refill")
NA_JUDGE_VERSIONS = ("v1", "v2", "q2")   # v1·v2 = data/na_judge.PROMPTS(답변 기준), q2 = data/na_qjudge(질문 기준, 2026-10-15)
CONFIRM_MAX_BAD = 0.15     # q2 확인 검사(다른 모델)가 답이 있다고 본 no_answer 비율 상한 — 넘으면 두 판정기가 크게 어긋난 것이라 빌드를 멈춘다
COVER_BIN = 0.1            # 포함률 분포 출력 구간 폭
FILTERED_SAMPLE_N = 10     # na_filtered_samples.md에 남길 표본 수
BASE_MODEL_DIR = BASE_DIR.parent / "models" / "base" / "Tri-7B"

SEED = 20261013
TARGET = {"distract": 0.70, "gold_only": 0.20, "no_answer": 0.10}
VAL_RATIO = 0.10
MAX_LENGTH = 3072          # 07 학습 시퀀스 상한(토큰). 넘는 샘플은 발췌를 줄이고(fit_to_budget), 그래도 넘으면 버린다
SEARCH_TOP_K = 6           # 방해 후보로 검색해 두는 수(정답·겹침 제외 전)
STRICT_ANSWER_OVERLAP = 8  # no_answer: 답변과 이 길이 이상 겹치면 제외(rag_context.used_references와 같은 기준)
LOOSE_ANSWER_OVERLAP = 20  # distract: 상투구가 아니라 내용이 겹치는 길이
UNIT_OVERLAP = 40          # 정답 단위 원문과 이 길이 이상 겹치면(통원↔입원 반복 문장 등) 제외 — 두 종류 공통
# no_answer 추가 관문: 답변의 핵심 명사(상투어 제외)가 방해 발췌에 이 비율 이상 나오면 답이 들어 있을 수 있다고 본다.
# 2026-10-13 측정: 글자 겹침만 거른 답 없음 533건의 핵심 명사 포함률 평균 0.40(정답 포함 샘플은 0.89), 0.6 이상 104건 —
# '진단계약 정의'(용어 정의 조문마다 있음), '고의 상해'(면책 조항마다 있음)처럼 다른 문서에서도 답할 수 있는 질문이었다.
NOUN_COVER_MAX = 0.5
GENERIC_NOUNS = {"보험", "보험금", "계약", "회사", "경우", "지급", "보상", "약관", "특별약관", "계약자", "피보험자", "반려동물",
                 "해당", "사항", "규정", "내용", "포함", "적용", "기간", "이상", "이내"}


def _h(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest(), 16)


def _qa_key(qa: dict) -> tuple:
    return (qa["unit_id"], qa.get("round"), qa.get("row"), qa["question"])


def is_val(uid: str) -> bool:
    return _h(SEED, "val", uid) % 1000 < VAL_RATIO * 1000


def final_files(final_dir: Path | None = None) -> dict[str, Path]:
    """final_dir: 06 final(petmint_{종}_faq_final.json)이 있는 폴더. None이면 기존 checked/"""
    return FINAL_FILES if final_dir is None else {sp: Path(final_dir) / p.name for sp, p in FINAL_FILES.items()}


def load_final(species: str, final_dir: Path | None = None) -> list[dict]:
    return json.loads(final_files(final_dir)[species].read_text(encoding="utf-8"))


# ---------------- 방해 발췌 검색 ----------------
def run_searches(engine, builder, qas_by_species: dict, cache_path: Path = SEARCH_CACHE) -> dict:
    """질문마다 SearchScope.unrestricted로 build_full_context 결과를 저장. 이미 있는 질문은 건너뛴다"""
    from data.rag_context import build_full_context
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = [(sp, qa["question"]) for sp, qas in qas_by_species.items() for qa in qas
            if f"{sp}|{qa['question']}" not in cache]
    todo = list(dict.fromkeys(todo))
    keep = ("section", "section_name", "type", "article_num", "article_title", "coverage_type", "content",
            "paragraph_num", "chunk_index", "context_prefix", "score", "adjusted_score", "reference_contents")
    for n, (sp, q) in enumerate(todo, 1):
        results = build_full_context(engine, builder, q, SearchScope.unrestricted(sp), top_k=SEARCH_TOP_K)
        cache[f"{sp}|{q}"] = [{k: r.get(k) for k in keep} for r in results]
        if n % 200 == 0 or n == len(todo):
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"  검색 {n}/{len(todo)}", flush=True)
    return cache


def _shingles(text: str, n: int) -> set[str]:
    f = _flat_cite(text)
    return {f[i:i + n] for i in range(len(f) - n + 1)}


def _shares(a: set[str], text: str, n: int) -> bool:
    """두 글이 (공백·괄호 무시) n자 이상 연속으로 겹치는가 — n자 조각이 하나라도 같으면 정확히 그렇다"""
    return not a.isdisjoint(_shingles(text, n))


_kiwi = None


def answer_nouns(text: str) -> set[str]:
    """답변의 핵심 명사(2자 이상, 상투어 제외) — kiwipiepy"""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return {t.form for t in _kiwi.tokenize(text) if t.tag in ("NNG", "NNP") and len(t.form) >= 2} - GENERIC_NOUNS


def noun_cover(nouns: set[str], text: str) -> float:
    return sum(1 for n in nouns if n in text) / len(nouns) if nouns else 0.0


def pick_distractors(results: list[dict], unit: dict, answer_body: str, strict: bool) -> list[dict]:
    """정답 단위가 아닌 검색 결과 중 방해로 쓸 수 있는 것(검색 순위 순). strict는 no_answer용(모듈 docstring)."""
    own = {graph_key(r) for r in unit["records"]}
    a_len = STRICT_ANSWER_OVERLAP if strict else LOOSE_ANSWER_OVERLAP
    ans_sh, unit_sh = _shingles(answer_body, a_len), _shingles(unit["content"], UNIT_OVERLAP)
    nouns = answer_nouns(answer_body) if strict else set()
    out = []
    for r in results:
        if graph_key(r) in own:
            continue
        # 답 없음: 같은 조(조번호 없는 별표·안내·별첨은 같은 문서 전체)의 다른 청크도 뺀다 — 답이 이어져 있을 수 있다
        if strict and (r.get("section"), r.get("section_name"), r.get("article_num")) == \
                (unit["section"], unit.get("section_name"), unit.get("article_num")):
            continue
        texts = [r["content"]] + ([ref.get("content") or "" for ref in r.get("reference_contents") or []] if strict else [])
        if any(_shares(ans_sh, t, a_len) or _shares(unit_sh, t, UNIT_OVERLAP) for t in texts):
            continue
        if strict and noun_cover(nouns, " ".join(texts)) >= NOUN_COVER_MAX:
            continue
        out.append(r)
    return out


def na_text(rs: list[dict]) -> str:
    """no_answer 발췌 글(본문 + 참조) — 포함률을 거를 때와 잴 때 같은 글을 쓴다"""
    return " ".join(r["content"] + " ".join(x.get("content") or "" for x in r.get("reference_contents") or []) for r in rs)


def proximity(r: dict, unit: dict) -> int:
    """정답 단위와의 거리 — 0 같은 조(다른 청크) / 1 같은 문서 인접 조(±2) / 2 같은 문서 / 3 다른 문서"""
    if (r.get("section"), r.get("section_name")) != (unit["section"], unit.get("section_name")):
        return 3
    a, b = r.get("article_num"), unit.get("article_num")
    if a == b:
        return 0
    return 1 if a is not None and b is not None and abs(a - b) <= 2 else 2


def pick_search_distractors(results: list[dict], unit: dict, answer_body: str, cover_max: float = 0.0,
                            nouns: set[str] | None = None, filtered: list | None = None, hard: bool = False) -> list[dict]:
    """no_answer용(search 방식). 검색 순위 순으로, 정답 조문과 답이 글자로 들어 있는 결과만 뺀다 —
    ① 정답 단위의 레코드(같은 unit_id) ② 같은 조의 다른 청크(조번호 없는 별표·안내는 같은 문서) — 1500자를 넘는 조는 여러 단위로
    나뉘어 같은 표·계산식이 옆 청크에 있다(표본 검수: 통원Ⅲ 제1조 고급형 계산 질문에 같은 조 다음 청크가 답을 담고 있었다)
    ③ 본문·참조 어디든 답변과 20자 또는 정답 단위 원문과 40자 이상 겹치는 것.
    ④ cover_max > 0이면 답변 핵심 명사(nouns) 포함률이 cover_max 이상인 것(--na-fill refill). 걸러진 것 중 ①~③을 통과한 순서로
       앞 2개(기준값 0이었다면 쓰였을 발췌)는 filtered에 (결과, 포함률)로 남긴다.
    hard(2026-10-15, --distractor-hard): 검색이 실제로 함께 가져오는 가까운 오답을 앞에 쓴다 — ②(같은 조 제외)를 풀고
    proximity 순(같은 조 다른 청크 → 같은 문서 인접 조 → 같은 문서 → 다른 문서, 같은 거리면 검색 순위)으로 고른다.
    지금까지 no_answer 방해 발췌의 72%가 다른 문서였다 — 어휘만 세도 정답과 구분됐다. 같은 조의 옆 청크는 답을 담기 쉬우므로
    ①·③은 그대로 두고, 답이 섞였는지는 질문 기준 판정(--na-judge q2)과 다른 모델의 확인 검사가 거른다."""
    own = {graph_key(r) for r in unit["records"]}
    own_article = (unit["section"], unit.get("section_name"), unit.get("article_num"))
    ans_sh, unit_sh = _shingles(answer_body, LOOSE_ANSWER_OVERLAP), _shingles(unit["content"], UNIT_OVERLAP)
    out, passed = [], 0
    if hard:
        results = sorted(results, key=lambda r: proximity(r, unit))      # 안정 정렬 — 같은 거리 안에서는 검색 순위 유지
    for r in results:
        if graph_key(r) in own or (not hard and (r.get("section"), r.get("section_name"), r.get("article_num")) == own_article):
            continue
        texts = [r["content"]] + [ref.get("content") or "" for ref in r.get("reference_contents") or []]
        if any(_shares(ans_sh, t, LOOSE_ANSWER_OVERLAP) or _shares(unit_sh, t, UNIT_OVERLAP) for t in texts):
            continue
        passed += 1
        if cover_max > 0:
            c = noun_cover(nouns, na_text([r]))
            if c >= cover_max:
                if filtered is not None and passed <= 2:
                    filtered.append((r, c))
                continue
        out.append(r)
    return out


def cover_hist(covers: list[float], width: float = COVER_BIN) -> list[tuple[str, int]]:
    """포함률 구간별 건수 — [0,10%), [10,20%) … [90,100%] (마지막 구간은 100% 포함)"""
    n_bins = round(1 / width)
    counts = [0] * n_bins
    for c in covers:
        counts[min(int(c / width + 1e-9), n_bins - 1)] += 1
    return [(f"{i * width:.0%}~{(i + 1) * width:.0%}", counts[i]) for i in range(n_bins)]


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def question_overlap(question: str, excerpt: str) -> float:
    """질문 글자 바이그램(공백·기호 제외) 중 발췌에도 있는 비율 — 양성·no_answer가 이 값만으로 갈리면 안 된다"""
    q = _bigrams(question)
    return len(q & _bigrams(excerpt)) / len(q) if q else 0.0


def overlap_bins(samples: list[dict], width: float = 0.1) -> dict:
    """2-4 build 검사용(2026-10-15) — 겹침 구간별 양성·no_answer 수, 겹침 0.2 미만 양성 비율, 30자 미만 질문 비율, 쌍 비율.
    평균 차이(overlap_gap)는 꼬리를 숨긴다: rebuild는 평균 차이 0.174로 통과했지만 겹침 0.1~0.2 구간의 no_answer가 44%였다"""
    bins, pos_low, short, n_pos = {}, 0, Counter(), 0
    na_pairs, pair_ids = [], set()
    for s in samples:
        excerpt, question = s["messages"][1]["content"].rsplit(f"\n\n{prompts.QUESTION_HEADER}\n", 1)
        ov, na = question_overlap(question, excerpt), s["meta"]["kind"] == "no_answer"
        b = f"{min(int(ov / width + 1e-9), int(1 / width) - 1) * width:.1f}"
        d = bins.setdefault(b, {"pos": 0, "na": 0})
        d["na" if na else "pos"] += 1
        short["na" if na else "pos"] += len(question.strip()) < 30
        if na:
            na_pairs.append(s["meta"].get("pair_id"))
        else:
            n_pos += 1
            pos_low += ov < 0.2
            if s["meta"]["kind"] == "distract_pair":
                pair_ids.add(s["meta"].get("pair_id"))
    n_na = len(na_pairs)
    return {"bins": dict(sorted(bins.items())), "na_ratio": round(n_na / len(samples), 4) if samples else 0.0,
            "low_pos_ratio": round(pos_low / n_pos, 4) if n_pos else 0.0, "low_pos": pos_low,
            "short_pos_ratio": round(short["pos"] / n_pos, 4) if n_pos else 0.0,
            "short_na_ratio": round(short["na"] / n_na, 4) if n_na else 0.0,
            "pair_ratio": round(sum(1 for p in na_pairs if p and p in pair_ids) / n_na, 4) if n_na else 0.0}


def overlap_report(samples: list[dict]) -> dict:
    """종류별 질문-발췌 바이그램 겹침 분포(발췌 = 프롬프트에 실제로 들어간 [약관 발췌] 전체, 라벨 포함)"""
    by = {}
    for s in samples:
        excerpt, question = s["messages"][1]["content"].rsplit(f"\n\n{prompts.QUESTION_HEADER}\n", 1)
        by.setdefault(s["meta"]["kind"], []).append(question_overlap(question, excerpt))
    out = {}
    for k, v in sorted(by.items()):
        v = sorted(v)
        out[k] = {"n": len(v), "mean": round(sum(v) / len(v), 3), "p10": round(v[len(v) // 10], 3),
                  "median": round(v[len(v) // 2], 3), "p90": round(v[len(v) * 9 // 10], 3)}
    return out


def assign_kinds(entries: list[dict]) -> None:
    """entries[i]["kind"]를 정한다. 목표 비율에 맞추되 자격(방해·엄격 후보 유무)을 지킨다. 해시 순서라 재현된다."""
    n = len(entries)
    want_na, want_d = round(n * TARGET["no_answer"]), round(n * TARGET["distract"])
    order = sorted(range(n), key=lambda i: _h(SEED, "kind", *_qa_key(entries[i]["qa"])))
    for e in entries:
        e["kind"] = "gold_only"
    # no_answer: 방해 후보가 없는 QA(어차피 distract가 안 되는 것)부터
    na_pool = sorted((i for i in order if entries[i]["strict"]), key=lambda i: bool(entries[i]["loose"]))
    for i in na_pool[:want_na]:
        entries[i]["kind"] = "no_answer"
    d = [i for i in order if entries[i]["kind"] == "gold_only" and entries[i]["loose"]]
    for i in d[:want_d]:
        entries[i]["kind"] = "distract"


# ---------------- 샘플 조립 ----------------
class TokenCounter:
    def __init__(self, model_dir: Path = BASE_MODEL_DIR):
        from transformers import AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(model_dir)

    def __call__(self, text: str) -> int:
        return len(self.tok(text, add_special_tokens=False)["input_ids"])

    def chat_len(self, messages: list[dict]) -> int:
        # 텍스트로 렌더링한 뒤 토큰화 — transformers 5의 apply_chat_template(tokenize=True)는 dict를 돌려준다
        return self(self.tok.apply_chat_template(messages, tokenize=False))

    def prompt_len(self, messages: list[dict]) -> int:
        """assistant 답변 앞까지(학습 시 loss를 걸지 않는 부분)"""
        return self(self.tok.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True))


def build_sample(e: dict, count: TokenCounter) -> tuple[dict | None, str]:
    """(샘플 또는 None, 사유). e = {"qa", "species", "gold", "kind", "loose", "strict"}"""
    qa, kind, gold = e["qa"], e["kind"], e["gold"]
    rng = random.Random(_h(SEED, "rng", *_qa_key(qa)))
    nouns, joined = answer_nouns(prompts.strip_citation(qa["answer"])), na_text
    if kind in ("no_answer", "distract_pair"):
        picked = na_picked(e, nouns)
    if kind == "no_answer":
        items, target = [prompts.ExcerptItem.from_search_result(r) for r in picked], prompts.NO_ANSWER_TEXT
    elif kind == "distract_pair":
        # 2-1(2026-10-15): no_answer와 같은 질문·같은 방해 발췌 + 정답 발췌 → 원래 답변. 둘의 차이는 정답 발췌 하나뿐이라
        # 질문 형태(겹침·길이·등급 어구)로는 라벨을 맞힐 수 없다
        items = [gold] + [prompts.ExcerptItem.from_search_result(r) for r in picked]
        random.Random(_h(SEED, "pair", *_qa_key(qa))).shuffle(items)
        target = qa["answer"]
    elif kind == "distract":
        n = min(len(e["loose"]), rng.choice((1, 2)))
        items = [gold] + [prompts.ExcerptItem.from_search_result(r) for r in e["loose"][:n]]
        rng.shuffle(items)
        target = qa["answer"]
    else:
        items, target = [gold], qa["answer"]
    gold_pos = next((i for i, it in enumerate(items) if it is gold), None)
    # no_answer 발췌가 답변 핵심 명사를 얼마나 담았나 — 높으면 답이 들어 있을 수 있다(drop이면 build_all이 이 값으로 거른다)
    na_cover = round(noun_cover(nouns, joined(picked)), 3) if kind == "no_answer" else None
    if kind == "no_answer" and e.get("na_fill") == "drop" and noun_cover(nouns, joined(picked)) >= e["na_cover_max"]:
        e["na_dropped"] = (picked, na_cover)
        return None, "na_dropped_cover"
    protected = frozenset() if gold_pos is None else frozenset({gold_pos})
    # 예산: 전체 MAX_LENGTH에서 템플릿·시스템 프롬프트·답변을 뺀 나머지가 user 메시지 상한
    skeleton = prompts.build_training_messages(qa["question"], target, [])
    fixed = count.chat_len(skeleton) - count(skeleton[1]["content"])
    budget = MAX_LENGTH - fixed - 8
    messages = prompts.build_training_messages(qa["question"], target, items, budget=budget,
                                               count_tokens=count, protected=protected)
    n_tokens = count.chat_len(messages)
    if n_tokens > MAX_LENGTH:
        return None, "too_long"
    user = messages[1]["content"]
    n_items = user.count("[발췌 ")
    meta = {"species": e["species"], "unit_id": qa["unit_id"], "kind": kind, "gold_pos": gold_pos, "n_items": n_items,
            "trimmed": n_items < len(items) or user.count("[참조] ") < sum(len(it.references) for it in items),
            "distractor_keys": [it.key for it in items if it is not gold],
            "round": qa.get("round"), "row": qa.get("row"), "flags": qa.get("flags", []),
            "rewrite_status": qa.get("rewrite_status"),
            "n_tokens": n_tokens, "n_prompt_tokens": count.prompt_len(messages), "distractor_mode": e["na_mode"], "na_noun_cover": na_cover,
            "prompt_version": prompts.PROMPT_VERSION}
    if e.get("pair_na") and kind in ("no_answer", "distract_pair"):
        meta["pair_id"] = hashlib.md5("|".join(map(str, _qa_key(qa))).encode()).hexdigest()[:12]
    return {"messages": messages, "meta": meta}, "ok"


def na_picked(e: dict, nouns: set[str]) -> list[dict]:
    """no_answer(와 그 쌍)의 방해 발췌 — 판정·거르기를 통과한 후보 중 앞 2개(포함률 규칙에 걸리면 1개)"""
    picked = e["strict"][:2]
    if e["na_mode"] == "legacy" and len(picked) == 2 and noun_cover(nouns, na_text(picked)) >= NOUN_COVER_MAX:
        picked = picked[:1]   # 둘을 합치면 답의 핵심어가 다 모이는 경우 — 하나만 쓴다
    # search + refill: 하나씩은 기준 미만이어도 둘을 합치면 넘을 수 있다 — 하나만 쓴다(샘플 포함률이 기준 미만으로 보장된다)
    if e.get("na_fill") == "refill" and len(picked) == 2 and noun_cover(nouns, na_text(picked)) >= e["na_cover_max"]:
        picked = picked[:1]
    return picked


def judge_no_answer(entries: list[dict], ver: str, na_fill: str, stats: Counter) -> list[dict]:
    """--na-judge: assign_kinds 뒤 no_answer QA의 방해 발췌를 LLM 판정으로 거른다(모듈 docstring). 걸러낸 발췌 목록을 돌려준다"""
    from data import na_judge, na_qjudge
    na_judge.require_model()
    q = ver == "q2"
    cache = na_qjudge._load(na_qjudge.CACHE_PATH, {}) if q else na_judge.load_cache()
    save = (lambda c: na_qjudge._dump(c, na_qjudge.CACHE_PATH)) if q else na_judge.save_cache
    filtered, n_new, t0 = [], 0, time.time()

    def judge_q(it: dict) -> tuple[dict, bool]:
        """q2: 질문 기준(답변을 보여주지 않는다). full·partial → yes, none → no, 파싱 실패 → unclear(걸러낸다)"""
        k = na_qjudge.cache_key(it["question"], it["excerpt"], "q2")
        new = k not in cache
        if new:
            cache[k] = na_qjudge.judge_checked(it["question"], it["excerpt"], "q2")
        res = cache[k]
        v = {"none": "no", "partial": "yes", "full": "yes"}.get(res["verdict"], "unclear")
        return {**res, "verdict": v, "q_verdict": res["verdict"]}, new

    def verdict(e: dict, r: dict) -> dict:
        nonlocal n_new
        it = {"species": e["species"], "question": e["qa"]["question"].strip(),
              "answer": prompts.strip_citation(e["qa"]["answer"]),
              "excerpt": prompts.format_item(1, prompts.ExcerptItem.from_search_result(r))}
        res, new = judge_q(it) if q else na_judge.judge_item(cache, it, ver)
        if new:
            n_new += 1
            if n_new % na_judge.SAVE_EVERY == 0:
                save(cache)
                print(f"  no_answer 판정 새 호출 {n_new}회, {(time.time() - t0) / 60:.1f}분", flush=True)
        return res

    def clean(e: dict, candidates: list[dict]) -> list[dict]:
        keep = []
        for r in candidates:
            res = verdict(e, r)
            stats[f"na_judge_{res['verdict']}"] += 1
            if res["verdict"] == "no":
                keep.append(r)
                if len(keep) == 2:
                    break
            else:                                    # yes·unclear·파싱 실패(None) — 답이 있을 수 있다
                filtered.append({"qa": e["qa"], "species": e["species"], "result": r, "verdict": res["verdict"],
                                 "reason": res.get("reason"),
                                 "cover": noun_cover(answer_nouns(prompts.strip_citation(e["qa"]["answer"])), na_text([r]))})
        return keep

    order = sorted(range(len(entries)), key=lambda i: _h(SEED, "kind", *_qa_key(entries[i]["qa"])))   # assign_kinds와 같은 순서
    na = [i for i in order if entries[i]["kind"] == "no_answer"]
    if na_fill == "drop":
        for i in na:
            e = entries[i]
            first = e["strict"][:2]
            if len(clean(e, first)) < len(first):
                e["na_judge_drop"] = True
    else:
        lost = 0
        for i in na:
            e = entries[i]
            e["strict"] = clean(e, e["strict"])
            if not e["strict"]:
                e["kind"] = "gold_only"
                lost += 1
        stats["na_judge_no_clean"] = lost
        # 빈 몫은 no_answer 자격 있는 다른 QA가 채운다 — gold_only 먼저, 없으면 distract에서(포함률 refill이 배정 전에 거르는 것과
        # 같은 결과: 그쪽도 no_answer가 distract보다 먼저 배정된다). 2026-10-14 첫 빌드: 남은 자격 QA가 전부 distract라 gold_only만
        # 보면 28건을 못 채웠다. 순서는 assign_kinds의 na_pool(방해 후보 없는 QA 먼저, 해시 순)
        tried = set(na)
        pool = sorted((i for i in order if entries[i]["kind"] in ("gold_only", "distract") and entries[i]["strict"]
                       and i not in tried), key=lambda i: (entries[i]["kind"] == "distract", bool(entries[i]["loose"])))
        for i in pool:
            if lost == 0:
                break
            e = entries[i]
            e["strict"] = clean(e, e["strict"])
            if e["strict"]:
                stats[f"na_judge_refilled_from_{e['kind']}"] += 1
                e["kind"] = "no_answer"
                lost -= 1
                stats["na_judge_refilled_qa"] += 1
        stats["na_judge_short"] = lost
    save(cache)
    na_judge.unload_model()
    stats["na_judge_new_calls"] = n_new
    stats["na_judge_minutes"] = round((time.time() - t0) / 60, 1)
    print(f"no_answer LLM 판정({ver}, {na_fill}): 새 호출 {n_new}회, {(time.time() - t0) / 60:.1f}분 | "
          f"판정 yes {stats['na_judge_yes']} / unclear {stats['na_judge_unclear']} / no {stats['na_judge_no']}"
          f" / 실패 {stats['na_judge_None']}", flush=True)
    return filtered


def build_all(builder, cache: dict, count: TokenCounter, distractor: str = "legacy",
              final_dir: Path | None = None, na_cover_max: float = NA_NOUN_COVER_MAX,
              na_fill: str | None = None, na_judge: str | None = None, hard: bool = False,
              pair_na: bool = False) -> tuple[list, list, dict]:
    """반환 (train, val, stats). stats["na_filtered"]에 걸러낸 no_answer 발췌(표본 파일용, stats.json에는 쓰지 않음)"""
    assert distractor in DISTRACTOR_MODES, distractor
    if na_judge is not None:
        assert distractor == "search" and na_judge in NA_JUDGE_VERSIONS, "--na-judge는 search 방식에만, v1|v2"
        assert na_cover_max == 0, "--na-judge와 --na-cover-max는 같이 쓰지 않는다 — 둘 중 하나를 고른다"
        assert na_fill in NA_FILL_MODES, f"--na-judge를 주면 --na-fill {NA_FILL_MODES} 중 하나를 골라야 한다"
    elif na_cover_max > 0:
        assert distractor == "search", "--na-cover-max는 search 방식에만 쓴다(legacy는 자체 핵심 명사 관문이 있다)"
        assert na_fill in NA_FILL_MODES, f"--na-cover-max를 주면 --na-fill {NA_FILL_MODES} 중 하나를 골라야 한다(모듈 docstring)"
    else:
        na_fill = None
    stats, entries, filtered = Counter(), [], []
    for species in FINAL_FILES:
        units = {unit_id(u): u for u in make_units(builder.chunks[species])}
        golds = {}
        for qa in load_final(species, final_dir):
            if is_human_target(qa):            # 사람 대상 조항(faq_units.EXCLUDE_ARTICLES·EXCLUDE_SECTION_NAMES) — 학습에서 뺀다
                stats["excluded_human_target"] += 1
                continue
            unit = units.get(qa["unit_id"])
            if unit is None:
                stats["unit_missing"] += 1
                continue
            results = cache.get(f"{species}|{qa['question']}")
            if results is None:
                stats["search_missing"] += 1
                continue
            if qa["unit_id"] not in golds:
                refs = builder.resolve_references(unit, species, source_chunks=unit["records"])
                golds[qa["unit_id"]] = prompts.ExcerptItem.from_unit(unit, refs)
            body = prompts.strip_citation(qa["answer"])
            # 검색이 결과를 못 준 질문(빈 결과)은 방해 후보가 없어 gold_only로만 간다(assign_kinds 자격)
            stats["search_empty"] += not results
            stats["search_hit_gold"] += any(graph_key(r) in {graph_key(x) for x in unit["records"]} for r in results)
            if distractor == "legacy":
                strict = pick_distractors(results, unit, body, strict=True)
            elif na_fill == "refill" and na_judge is None:
                cut = []
                strict = pick_search_distractors(results, unit, body, na_cover_max, answer_nouns(body), cut, hard=hard)
                filtered += [{"qa": qa, "species": species, "result": r, "cover": c} for r, c in cut]
            else:
                strict = pick_search_distractors(results, unit, body, hard=hard)
            entries.append({"qa": qa, "species": species, "gold": golds[qa["unit_id"]], "na_mode": distractor,
                             "na_cover_max": na_cover_max, "na_fill": None if na_judge else na_fill, "pair_na": pair_na,
                             "loose": pick_distractors(results, unit, body, strict=False), "strict": strict})
    stats["eligible_distract"] = sum(1 for e in entries if e["loose"])
    stats["eligible_no_answer"] = sum(1 for e in entries if e["strict"])
    assign_kinds(entries)
    if na_judge is not None:
        filtered += judge_no_answer(entries, na_judge, na_fill, stats)
    train, val = [], []
    for e in entries:
        if e.get("na_judge_drop"):
            stats["na_dropped_judge"] += 1
            continue
        sample, why = build_sample(e, count)
        stats[why] += 1
        if why == "na_dropped_cover":
            filtered += [{"qa": e["qa"], "species": e["species"], "result": r, "cover": e["na_dropped"][1]}
                         for r in e["na_dropped"][0]]
        if sample is None:
            continue
        out = [sample]
        if pair_na and e["kind"] == "no_answer":
            pair, why2 = build_sample({**e, "kind": "distract_pair"}, count)
            stats[f"pair_{why2}"] += 1
            if pair is None:            # 정답 발췌를 더하면 길이를 넘는 경우 — no_answer는 남기고 건수만 센다
                del sample["meta"]["pair_id"]
            else:
                out.append(pair)
        for smp in out:
            stats[f"kind_{smp['meta']['kind']}"] += 1
            stats["trimmed"] += smp["meta"]["trimmed"]
            (val if is_val(e["qa"]["unit_id"]) else train).append(smp)
    stats["overlap"] = overlap_report(train + val)
    stats["overlap_bins"] = overlap_bins(train + val)
    covers = sorted(s["meta"]["na_noun_cover"] for s in train + val if s["meta"]["kind"] == "no_answer")
    if covers:
        stats["no_answer_noun_cover"] = {"mean": round(sum(covers) / len(covers), 3), "median": covers[len(covers) // 2],
                                         f"ge_{NOUN_COVER_MAX}": sum(c >= NOUN_COVER_MAX for c in covers),
                                         "hist": cover_hist(covers)}
    stats = dict(stats)       # Counter.update는 더하기라 문자열 값을 넣을 수 없다
    stats.update(distractor_mode=distractor, na_cover_max=na_cover_max, na_fill=na_fill, na_judge=na_judge,
                 na_filtered_excerpts=len(filtered), na_filtered_qas=len({_qa_key(f["qa"]) for f in filtered}),
                 na_filtered=filtered)
    return train, val, stats


def write_filtered_samples(path: Path, filtered: list[dict], stats: dict, n: int = FILTERED_SAMPLE_N):
    """걸러낸 no_answer 발췌 표본(QA당 하나, seed 고정)을 사람이 읽을 수 있게 — 정말 답이 들어 있었는지 확인용"""
    by_qa = {}
    for f in filtered:
        by_qa.setdefault(_qa_key(f["qa"]), f)
    pick = sorted(by_qa.values(), key=lambda f: _h(SEED, "filtered", *_qa_key(f["qa"])))[:n]
    L = [f"# no_answer에서 걸러낸 발췌 — 표본 {len(pick)}건 / 걸러진 QA {len(by_qa)}건 (발췌 {len(filtered)}개)", "",
         (f"기준: LLM 판정({stats['na_judge']}) yes·unclear" if stats.get("na_judge") else
          f"기준: 답변 핵심 명사 포함률 ≥ {stats['na_cover_max']}")
         + f" | 채움 방식: {stats['na_fill']} | 방해 발췌: {stats['distractor_mode']}",
         "각 항목에서 '발췌에 답이 들어 있는가'를 읽고 판단한다. 들어 있으면 거른 것이 맞다(라벨 오류를 막음).", ""]
    for i, f in enumerate(pick, 1):
        qa, r = f["qa"], f["result"]
        body = prompts.strip_citation(qa["answer"])
        nouns = answer_nouns(body)
        text = na_text([r])
        L += [f"## {i}. {qa['unit_id']} (포함률 {f['cover']:.2f})", "",
              f"- 질문: {qa['question']}", f"- 답변: {body}",
              f"- 핵심 명사 — 발췌에 있음: {sorted(x for x in nouns if x in text)} / 없음: {sorted(x for x in nouns if x not in text)}",
              f"- 걸러낸 발췌: {prompts.item_label(r)}"]
        if "verdict" in f:
            L.append(f"- LLM 판정: {f['verdict']} — {f.get('reason')}")
        L += ["", "```", r["content"].strip()[:1200], "```"]
        for ref in (r.get("reference_contents") or [])[:2]:
            L += [f"참조 {ref.get('citation_label')}:", "```", (ref.get("content") or "").strip()[:500], "```"]
        L.append("")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def write_jsonl(path: Path, samples: list[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def print_overlap(stats: dict):
    print("\n질문-발췌 바이그램 겹침 (종류별, 발췌 = 프롬프트의 [약관 발췌] 전체)")
    print("  기준(첫 학습 데이터, legacy): distract 0.592 / gold_only 0.581 / no_answer 0.342")
    for k, v in stats["overlap"].items():
        print(f"  {k:10s} n={v['n']:5d}  평균 {v['mean']:.3f}  p10 {v['p10']:.3f}  중앙 {v['median']:.3f}  p90 {v['p90']:.3f}")
    if "no_answer_noun_cover" in stats:
        c = stats["no_answer_noun_cover"]
        n = sum(k for _, k in c["hist"])
        print(f"\nno_answer 발췌의 답변 핵심 명사 포함률 ({n}건, 기준값 {stats['na_cover_max']}, 채움 {stats['na_fill']}): "
              f"평균 {c['mean']} / 중앙 {c['median']} / {NOUN_COVER_MAX} 이상 {c[f'ge_{NOUN_COVER_MAX}']}건 — 높을수록 답이 들어 있을 위험")
        cum = 0
        for label, k in c["hist"]:
            cum += k
            print(f"  {label:>9s}  {k:4d}건  {'#' * round(k / max(n, 1) * 50):50s} 누적 {cum / max(n, 1):.0%}")
    if stats.get("na_judge"):
        print(f"  LLM 판정으로 걸러낸 발췌 {stats['na_filtered_excerpts']}개(QA {stats['na_filtered_qas']}건)"
              + (f", 버린 no_answer 샘플 {stats.get('na_dropped_judge', 0)}건" if stats["na_fill"] == "drop" else
                 f", 깨끗한 발췌가 없어 gold_only로 돌린 QA {stats.get('na_judge_no_clean', 0)}건 → 다른 QA로 채움 "
                 f"{stats.get('na_judge_refilled_qa', 0)}건(gold_only에서 {stats.get('na_judge_refilled_from_gold_only', 0)}, "
                 f"distract에서 {stats.get('na_judge_refilled_from_distract', 0)}) (못 채움 {stats.get('na_judge_short', 0)})"))
    if stats.get("na_cover_max"):
        print(f"  걸러낸 발췌 {stats['na_filtered_excerpts']}개(QA {stats['na_filtered_qas']}건)"
              + (f", 버린 no_answer 샘플 {stats.get('na_dropped_cover', 0)}건" if stats["na_fill"] == "drop" else ""))


def confirm_no_answer(train: list[dict], val: list[dict], out_dir: Path, stats: dict,
                      max_bad: float = CONFIRM_MAX_BAD) -> tuple[list, list, bool]:
    """q2 확인 검사(2026-10-15) — 라벨링과 **다른 모델**(na_qjudge.CONFIRM_MODEL)·별도 캐시로 실제 train/val의 no_answer 발췌를
    질문 기준으로 다시 판정한다. 같은 판정기·같은 캐시로 다시 보던 검사(v1·v2)는 자기가 거른 것을 자기가 검사해 "0건"이 구조상 당연했다.
    - 답이 있다고 본(full·partial·파싱 실패) no_answer 비율이 CONFIRM_MAX_BAD를 넘으면 두 판정기가 크게 어긋난 것 — 빌드를 멈춘다(False).
    - 넘지 않으면 그 샘플(과 그 쌍)을 학습에서 뺀다 — 둘 중 하나라도 답이 있다고 본 발췌는 no_answer로 쓰지 않는다(보수적).
    - 요약은 <out-dir>/na_judge_summary_q2.json(빼기 전 수치) — rebuild.py 빌드 검사가 읽는다."""
    from data import na_judge, na_qjudge
    model = na_qjudge.CONFIRM_MODEL
    cache = na_qjudge._load(na_qjudge.CACHE_PATH, {})
    flagged, ev, n_new, t0 = set(), Counter(), 0, time.time()
    na = [s for s in train + val if s["meta"]["kind"] == "no_answer"]
    for i, s in enumerate(na, 1):
        excerpts, question = na_judge.split_excerpts(s["messages"][1]["content"])
        for ex in excerpts:
            k = na_qjudge.cache_key(question, ex, "q2", model)
            if k not in cache:
                cache[k] = na_qjudge.judge_checked(question, ex, "q2", model)
                n_new += 1
                if n_new % na_qjudge.SAVE_EVERY == 0:
                    na_qjudge._dump(cache, na_qjudge.CACHE_PATH)
            v = cache[k]["verdict"]
            ev[str(v)] += 1
            if v != "none":
                flagged.add(id(s))
        if i % 100 == 0:
            print(f"  확인 검사({model}) {i}/{len(na)} — 답 있다고 본 샘플 {len(flagged)}, {(time.time() - t0) / 60:.1f}분", flush=True)
    na_qjudge._dump(cache, na_qjudge.CACHE_PATH)
    requests_unload(model)
    bad = len(flagged)
    ratio = bad / len(na) if na else 0.0
    summary = {"build_dir": str(out_dir), "judged_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model, "prompt": "q2",
               "independent_of": "na_qjudge q2 @ gemma4:12b (라벨링)", "samples": len(na), "excerpts": sum(ev.values()),
               "excerpt_verdicts": dict(ev), "sample_verdicts": {"no": len(na) - bad, "yes": bad}, "new_calls": n_new,
               "max_bad": max_bad, "dropped": 0}
    ok = ratio <= max_bad
    if ok and bad:
        drop_pairs = {s["meta"].get("pair_id") for s in na if id(s) in flagged} - {None}
        keep = lambda s: id(s) not in flagged and not (s["meta"]["kind"] == "distract_pair" and s["meta"].get("pair_id") in drop_pairs)
        train, val = [s for s in train if keep(s)], [s for s in val if keep(s)]
        summary["dropped"] = bad
        summary["dropped_pairs"] = len(drop_pairs)
    (out_dir / "na_judge_summary_q2.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    stats["na_confirm"] = {k: summary[k] for k in ("model", "samples", "excerpt_verdicts", "sample_verdicts", "dropped", "new_calls")}
    print(f"확인 검사({model}): no_answer {len(na)}건 중 답이 있다고 본 것 {bad}건({ratio:.1%}) — "
          + ("뺐다" if ok else f"상한 {max_bad:.0%} 초과, 빌드를 멈춘다"), flush=True)
    return train, val, ok


def requests_unload(model: str):
    import requests
    from data import faq_judge
    requests.post(f"{faq_judge.OLLAMA_URL}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--search-only", action="store_true")
    ap.add_argument("--distractor", choices=DISTRACTOR_MODES, default="legacy",
                    help="no_answer 방해 발췌 고르는 방식(모듈 docstring). legacy = 첫 학습 데이터와 같은 방식")
    ap.add_argument("--final-dir", type=Path, default=None, help="06 final 폴더(기본: data/faq/checked)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR, help="train/val/stats 출력 폴더(기본: data/finetune)")
    ap.add_argument("--na-cover-max", type=float, default=NA_NOUN_COVER_MAX,
                    help="search no_answer 발췌의 답변 핵심 명사 포함률 상한(이상이면 no_answer로 안 씀). 0 = 끔")
    ap.add_argument("--na-fill", choices=NA_FILL_MODES, default=None,
                    help="걸러낸 만큼: drop(적게 둔다) / refill(다음 순위·다른 QA로 채운다). --na-cover-max를 주면 필수")
    ap.add_argument("--na-judge", choices=NA_JUDGE_VERSIONS, default=None,
                    help="search no_answer 발췌를 LLM 판정(data/na_judge.py 프롬프트 버전)으로 거른다. --na-cover-max와 택일, --na-fill 필수")
    ap.add_argument("--distractor-hard", action="store_true",
                    help="no_answer 방해 발췌를 가까운 오답(같은 조 → 인접 조 → 같은 문서 → 다른 문서) 순으로 고른다(2026-10-15)")
    ap.add_argument("--confirm-max-bad", type=float, default=CONFIRM_MAX_BAD,
                    help="q2 확인 검사가 답이 있다고 본 no_answer 비율 상한 — 넘으면 멈춘다. 1이면 멈추지 않고 그 샘플만 뺀다")
    ap.add_argument("--pair-na", action="store_true", help="no_answer마다 같은 질문·같은 방해 발췌 + 정답 발췌 양성(distract_pair)을 더한다")
    args = ap.parse_args(argv)
    if (args.na_cover_max > 0 or args.na_judge) and args.na_fill is None:
        ap.error("--na-cover-max나 --na-judge를 주면 --na-fill drop|refill 을 골라야 한다")
    if args.na_cover_max > 0 and args.na_judge:
        ap.error("--na-cover-max와 --na-judge는 같이 쓰지 않는다 — 둘 중 하나를 고른다")
    from data import rag_context
    qas = {sp: load_final(sp, args.final_dir) for sp in FINAL_FILES}
    print("최종 QA:", {sp: len(v) for sp, v in qas.items()}, "| 방해 발췌:", args.distractor)
    cache = json.loads(SEARCH_CACHE.read_text(encoding="utf-8")) if SEARCH_CACHE.exists() else {}
    missing = any(f"{sp}|{qa['question']}" not in cache for sp, v in qas.items() for qa in v)
    if missing or args.search_only:
        from data import search_engine   # 검색이 남았을 때만 모델을 올린다(GPU)
        engine = search_engine.SearchEngine()
        builder = rag_context.ContextBuilder(client=engine.client, chunks=engine.chunks)
        cache = run_searches(engine, builder, qas)
        if args.search_only:
            return
        if args.na_judge:      # 검색 모델(GPU)을 내리고 나서 판정 모델(Ollama)을 올린다 — 한 프로세스에서 둘이 겹치지 않게
            import gc
            import torch
            del engine
            gc.collect()
            torch.cuda.empty_cache()
    else:
        builder = rag_context.ContextBuilder()
    count = TokenCounter()
    train, val, stats = build_all(builder, cache, count, distractor=args.distractor, final_dir=args.final_dir,
                                  na_cover_max=args.na_cover_max, na_fill=args.na_fill, na_judge=args.na_judge,
                                  hard=args.distractor_hard, pair_na=args.pair_na)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    filtered = stats.pop("na_filtered")
    if args.na_cover_max > 0 or args.na_judge:
        write_filtered_samples(out_dir / "na_filtered_samples.md", filtered, stats)
        print("걸러낸 표본:", out_dir / "na_filtered_samples.md")
    confirmed = True
    if args.na_judge == "q2":
        train, val, confirmed = confirm_no_answer(train, val, out_dir, stats, args.confirm_max_bad)
        kinds = Counter(s["meta"]["kind"] for s in train + val)
        stats.update({f"kind_{k}": v for k, v in kinds.items()})
        stats["overlap"] = overlap_report(train + val)
        stats["overlap_bins"] = overlap_bins(train + val)
    stats.update(distractor_hard=args.distractor_hard, pair_na=args.pair_na)
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "val.jsonl", val)
    stats.update({"train": len(train), "val": len(val),
                  "val_units": len({s["meta"]["unit_id"] for s in val}),
                  "train_units": len({s["meta"]["unit_id"] for s in train}),
                  "unit_overlap": len({s["meta"]["unit_id"] for s in val} & {s["meta"]["unit_id"] for s in train}),
                  "max_length": MAX_LENGTH, "prompt_version": prompts.PROMPT_VERSION, "seed": SEED,
                  "final_dir": str(args.final_dir or FINAL_FILES["강아지"].parent)})
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.na_judge in ("v1", "v2"):
        # 검증: 실제로 써진 train/val의 no_answer 발췌를 프롬프트에 들어간 글 그대로 다시 판정(대부분 캐시) — 판정 yes가 남았는가
        from data import na_judge
        s = na_judge.run(out_dir, args.na_judge)
        stats["na_judge_check"] = {k: s[k] for k in ("excerpts", "samples", "excerpt_verdicts", "sample_verdicts", "new_calls")}
    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "overlap"}, ensure_ascii=False, indent=1))
    print_overlap(stats)
    if not confirmed:
        return 4


if __name__ == "__main__":
    sys.exit(main())
