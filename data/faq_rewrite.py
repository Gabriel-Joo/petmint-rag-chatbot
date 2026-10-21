"""
faq_rewrite.py
06을 통과한 QA의 질문만 고객 말투로 다시 쓴다(2026-10-14 설계). 답변·근거·unit_id는 그대로 둔다.

배경(실험 C·C-2, 05 질문 프롬프트 개편): V2·V2C는 질문 성질을 바꿨지만(라벨 누출 11.3% → 0~1.5%, 상황형 1.4% → 56~58%)
심판 통과율이 v1 76.1% → 36~38%로 떨어졌다 — 질문과 답변을 한꺼번에 만들면서 incomplete·fabricated가 늘었다.
그래서 05는 v1으로 두고, 재작성을 06 **뒤**에 둔다. 버려질 QA는 재작성하지 않고, 답변은 이미 검증돼 있어
incomplete·fabricated가 생길 자리가 없다. 재작성이 망칠 수 있는 것은 "질문과 답변이 어긋나는 것"뿐이라 재심판으로 그것을 잰다.

흐름 (python -m data.faq_rewrite pilot — 실행은 GPU가 빌 때, 사람이):
1. 표본: checked/petmint_강아지_faq_final.json에서 100건(단위당 1건, seed 42) — 같은 표본을 다시 쓰도록 파일로 남긴다
2. 재작성: tri-7b(05와 같은 모델), temperature 0.2. 결정적 검사에 걸리면 한 번 더, 그래도 걸리면 원래 질문 유지
3. 보존 확인: 답변 해시·unit_id·근거 필드가 재작성 전과 한 글자도 같은지(다르면 assert로 멈춘다)
4. 재심판: 06과 같은 faq_judge(프롬프트 수정 없음, gemma4:12b) — 질문이 바뀐 QA만
5. 리포트: data/review/faq_rewrite_<모드>_<날짜시각>.md — 재심판 통과율, faq_style 질문 성질 전후, 떨어진 QA 전후 전문

출력: data/faq/rewrite/<모드>/ — 기존 checked/·exp_c/는 건드리지 않는다.
"""

import hashlib
import json
import random
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

from data import faq_checks, faq_judge, faq_style

PROJECT_DIR = Path(__file__).resolve().parent.parent
FAQ_DIR = PROJECT_DIR / "data" / "faq"
REVIEW_DIR = PROJECT_DIR / "data" / "review"
OUT_ROOT = FAQ_DIR / "rewrite"

OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "tri-7b:latest"      # 05와 같은 생성 모델(심판 gemma4:12b와 다른 모델)
OLLAMA_EXTRA: dict = {}           # 요청에 더할 필드 — qwen3는 {"think": False}(생각 출력이 num_predict를 먹는다)
TEMPERATURE = 0.2                 # 낮게 — 뜻을 바꾸지 않는 편집이라 다양성이 필요 없다
NUM_CTX = 8192
NUM_PREDICT = 200                 # 질문 하나({"question": "..."})
PROMPT_BUDGET = NUM_CTX - NUM_PREDICT
MAX_ATTEMPTS = 2                  # 결정적 검사에 걸리면 한 번 더. 그래도 걸리면 원래 질문 유지
PILOT_N = 100
SEED = 42
SAVE_EVERY = 100

# 2026-10-21: 예시 문장 "우리 아이가 ~했는데"를 넣었더니 모델이 그 틀을 그대로 따라 써 반려동물이 소송·주소·배당금의 주어가 된
# 질문이 230건 생겼다(학습 데이터에 40건). 예시 문장 대신 무엇을 하라는 지시로 바꿨다 — 나쁜 예든 좋은 예든 문장을 주면 따라 쓴다
REWRITE_SYSTEM = """당신은 반려동물 보험 상담 FAQ의 질문을 고객 말투로 고쳐 쓰는 편집자입니다.
[원문]과 [답변]은 이미 검증되었습니다. [원래 질문]만 아래 규칙대로 고쳐 쓰세요.
- 뜻을 바꾸지 마세요. 고친 질문에 대한 답이 [답변]과 같아야 합니다. 원래 질문이 묻는 대상·조건·범위를 그대로 물으세요.
- 이미 보험에 가입한 고객이 상담 창구에 묻는 말투로, 30자 내외 구어체로 쓰세요.
- 반려동물의 치료·질병·사고를 묻는 질문이면 고객이 자기 반려동물의 상황을 말하며 묻는 형태로 써도 됩니다. 상황은 원래 질문과 답변에 있는 내용으로만 만드세요.
- 계약·보험료·해지·청약·소송·주소·연락처·세금처럼 사람(계약자·피보험자)에 관한 질문은 사람을 주어로 쓰세요. 반려동물을 그 주어로 쓰지 마세요.
- 조문 번호, 약관 이름, 조항 제목은 쓰지 마세요.
- 한 질문에서는 한 가지만 물으세요.
- 약관 용어 대신 고객이 실제로 쓰는 말을 쓰세요(예: 슬관절 탈구 → 슬개골 빠짐, 구강 질환 → 스케일링·입냄새). 단, 바꾼 말이 [답변]·[원문]의 내용과 어긋나면 약관 용어를 그대로 쓰세요.
- 원래 질문에 있는 숫자(금액·기간·나이 등)는 그대로 남기세요. 원문에 없는 상황·나이·금액·질병명을 새로 만들지 마세요.
- 반드시 JSON 한 개로만 답하세요: {"question": "고친 질문"}"""

REWRITE_META = ("question_original", "rewrite", "rewrite_status")

# 06 앞 재작성(순서 B, rebuild3 2026-10-16)의 등급 어구 대체 — 07번 10-7절 4번. 평가에서 "고급형인데 해지하면 환급금 있나요?"처럼
# 등급·유형을 밝힌 공통 조항 질문 23건 중 rebuild2가 15건을 거절했다. 학습에는 그런 양성이 거의 없다.
# 변형을 더하지 않고 대체한다 — 06이 같은 단위 안의 거의 같은 질문을 중복으로 버리고 단위 상한도 걸기 때문(사용자 승인 2026-10-16).
GRADE_SHARE = 0.10          # 전체 QA 대비 등급 어구로 쓰는 비율(대상 = coverage_type 없는 단위의 QA)
GRADE_WORDS = ("고급형", "기본형", "실속형")
TYPE_WORDS = ("Ⅰ유형", "Ⅱ유형", "Ⅲ유형")
# rebuild4(2026-10-18): 등급 + 유형을 함께 밝힌 질문("실속형 Ⅱ유형인데 ~") — rebuild3 학습 7건뿐이고 평가 R058이 이 꼴에서 거절했다.
# 유형 어구로 뽑힌 QA의 절반을 "등급 유형"으로 바꾼다(등급 어구 대상 안에서만, 비율 GRADE_SHARE는 그대로)
COMBO_SHARE = 0.5
# 등급 어구 대상 비율은 일반·주제 회차 QA로만 잰다 — 예외·표 회차(rebuild4)를 더해도 기존 QA의 등급 어구 선택이 그대로이게
RATE_EXCLUDE_KINDS = ("exc", "table")
GRADE_RULE = ("- 고객이 가입한 상품의 등급·유형 '{p}'을(를) 질문 앞부분에서 밝히세요(예: \"{p} 가입했는데 ~\", \"{p}인데 ~\"). "
              "이 조항은 등급·유형과 관계없이 같은 내용이라 [답변]은 그대로 맞습니다. '{p}' 글자를 그대로 쓰세요.")      # 재작성이 더하는 필드 — 보존 확인에서 빼는 것은 이것과 question뿐


# ---------- 프롬프트·호출 ----------
def build_rewrite_prompt(faq: dict, source: str) -> str:
    """source: 생성 단위 원문(rag_context.display_text) — 고객 용어가 원문 범위와 어긋나지 않는지 모델이 보도록 준다"""
    head = f"{faq.get('section_name') or faq.get('section')} {faq.get('article_title') or ''}".strip()
    return (f"[반려동물] {faq['species']}\n\n[원문] {head}\n{source}\n\n"
            f"[원래 질문]\n{faq['question']}\n\n[답변]\n{faq_checks.answer_body(faq['answer'])}")


def call_rewrite(prompt: str, system: str = REWRITE_SYSTEM) -> tuple[str, int]:
    """(응답 원문, 입력 토큰 수)"""
    body = {"model": MODEL_NAME, "system": system, "prompt": prompt, "stream": False, "format": "json",
            "options": {"temperature": TEMPERATURE, "repeat_penalty": 1.1, "num_predict": NUM_PREDICT, "num_ctx": NUM_CTX},
            **OLLAMA_EXTRA}
    r = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=900)
    r.raise_for_status()
    out = r.json()
    return out.get("response", ""), out.get("prompt_eval_count") or 0


def parse_question(raw: str) -> str | None:
    try:
        q = json.loads(re.search(r"\{.*\}", raw, re.S).group(0)).get("question")
    except (AttributeError, json.JSONDecodeError, TypeError):
        return None
    return q.strip() if isinstance(q, str) and q.strip() else None


# ---------- 결정적 검사 — 걸리면 원래 질문 유지 ----------
def _has_chinese(text: str) -> bool:
    """05 has_chinese_sentence와 같은 규칙"""
    return bool(re.search(r"[一-鿿]{4,}", text)) and bool(re.search(r"[的了是在您]", text))


def _bare_numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", (text or "").replace(",", "")))


def _label_tokens(text: str) -> Counter:
    """faq_style.LABEL_LEAK에 걸리는 표현(공백 제거)과 횟수 — '제3조'가 원래 질문에 있었으면 재작성에 남아도 새 누출이 아니다.
    횟수로 센다: 원래 '특별약관이 …'(약관 1회) → '펫퍼민트 기부 특별약관 특별약관이 …'(2회)처럼 상품명을 덧붙인 것은 새 누출이다"""
    return Counter(re.sub(r"\s+", "", m.group(0)) for m in faq_style.LABEL_LEAK.finditer(text or ""))


# 답변 누출(2026-10-16, 사용자 확정): 재작성이 답변의 결론·수치를 질문에 넣으면("연간 총 보상한도는 750만원인가요?") 모델이 발췌를
# 읽지 않고 질문만 보고 답하는 법을 배울 수 있다. 프롬프트 56행이 "상황은 원래 질문과 답변에 있는 내용으로만" 만들라고 해서 생긴다.
# rebuild3_b1p 재작성 6,971건에서: 숫자 규칙 46건(누출 29 · 고객 상황 숫자 17 — 거절해도 원래 질문이 남아 구어체만 잃는다),
# 어구는 4자 조각이면 1,611건(23%)이라 너무 넓어 명사형 어절 4자 이상으로 좁혔다(77건, 표본 15건 중 약 10건이 실제 누출)
_PARTICLE = re.compile(r"(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만|이나|나|인|일|이라|라)$")
_VERB_END = re.compile(r"(다|면|야|지|고|기|요|서|게|며|까지|하는|되는|었|았|였)$")


def _answer_nouns(text: str) -> set[str]:
    """4자 이상 어절에서 조사를 뗀 명사형(동사·어미로 끝나는 것은 뺀다)"""
    out = set()
    for w in re.findall(r"[가-힣A-Za-z()]{4,}", text or ""):
        w = _PARTICLE.sub("", w)
        if len(re.sub(r"[()]", "", w)) >= 4 and not _VERB_END.search(w):
            out.add(w)
    return out


def answer_leak(new_q: str, orig_q: str, body: str) -> list[str]:
    """원래 질문에 없던 숫자·명사형 어구(4자 이상)가 답변에서 왔으면 그 목록"""
    nums = (_bare_numbers(new_q) - _bare_numbers(orig_q)) & _bare_numbers(body)
    o = re.sub(r"\s+", "", orig_q)
    words = {w for w in _answer_nouns(new_q) & _answer_nouns(body) if w not in o}
    return sorted(nums) + sorted(words)


def check_rewrite(new_q: str, faq: dict, source: str, refs: list[dict], paragraphs: list,
                  base_checks: set[str]) -> list[str]:
    """재작성 질문의 문제 목록(빈 목록 = 통과). base_checks: 원래 질문으로 돌린 06 결정적 검사에 이미 걸린 검사 이름"""
    why = []
    orig_q, body = faq["question"], faq_checks.answer_body(faq["answer"])
    if _has_chinese(new_q):
        why.append("중국어 섞임")
    # 라벨 누출·물음표는 원래 질문 대비로 본다(2026-10-14 파일럿: 거부 45건 중 원래 질문이 이미 두 가지를 묻거나 조문 번호를
    # 담은 경우가 많았다 — 재작성이 나빠지게 한 것이 아니다). 원래 없던 라벨·늘어난 물음표만 거부한다
    leaked = _label_tokens(new_q) - _label_tokens(orig_q)      # Counter 차 — 원래보다 많아진 표현만 남는다
    if leaked:
        why.append(f"라벨 누출(조문 번호·약관·특약·별표): {sorted(leaked.elements())}")
    if new_q.count("?") > max(1, orig_q.count("?")):
        why.append(f"물음표 늘어남(두 가지를 물음): {orig_q.count('?')} → {new_q.count('?')}")
    # 답변의 계산·조건이 원래 질문의 숫자를 전제할 수 있다 — 빠지면 질문과 답변이 어긋난다
    lost = faq_checks.numbers(orig_q) - faq_checks.numbers(new_q)
    if lost:
        why.append(f"원래 질문의 숫자 빠짐: {sorted(lost)}")
    pool = orig_q + " " + body + " " + source + " " + " ".join(r.get("content") or "" for r in refs)
    new_nums = _bare_numbers(new_q) - _bare_numbers(pool)
    if new_nums:
        why.append(f"원문·답변에 없는 숫자: {sorted(new_nums)}")
    leak = answer_leak(new_q, orig_q, body)
    if leak:
        why.append(f"답변 누출(원래 질문에 없던 답변의 숫자·어구): {leak}")
    # 06 결정적 검사(종·통원/입원·숫자·조문 등은 질문도 본다)를 바꾼 질문으로 다시 — 원래 없던 drop·flag가 생기면 탈락
    after = faq_checks.run_checks({**faq, "question": new_q}, source, refs, paragraphs)
    new_checks = sorted({c["check"] for c in after if c["action"] in ("drop", "flag")} - base_checks)
    if new_checks:
        why.append(f"06 결정적 검사 새로 걸림: {new_checks}")
    return why


def attempt_problems(q: str | None, used: int, faq: dict, source: str, refs: list[dict], paragraphs: list,
                     base: set[str], grade_phrase: str | None = None) -> list[str]:
    """시도 하나의 문제 목록(빈 목록 = 채택 가능). recheck가 저장된 시도에 같은 규칙을 다시 적용한다"""
    why = [f"입력 {used}토큰 — 잘렸을 수 있음"] if used >= PROMPT_BUDGET else []
    if q is None:
        return why + ["JSON 파싱 실패"]
    if grade_phrase and grade_phrase.replace(" ", "") not in q.replace(" ", ""):
        why.append(f"등급 어구 빠짐: {grade_phrase}")
    return why + check_rewrite(q, faq, source, refs, paragraphs, base)


def settle(faq: dict, attempts: list[dict]) -> tuple[str, str | None]:
    """(상태, 채택한 질문) — 문제 없는 첫 시도를 쓴다"""
    for a in attempts:
        if a["question"] is not None and not a["why"]:
            return ("unchanged" if a["question"] == faq["question"] else "ok"), a["question"]
    return ("parse_fail" if all(a["question"] is None for a in attempts) else "rejected"), None


def rewrite_faq(faq: dict, unit: dict, refs: list[dict], source: str, grade_phrase: str | None = None) -> dict:
    """QA 한 건 → 질문만 바뀐 새 레코드. rewrite.status: ok / unchanged(모델이 그대로 돌려줌) / parse_fail / rejected.
    grade_phrase(06 앞 재작성, 2026-10-16): 공통 조항 QA의 질문에 가입 등급·유형 어구를 넣어 쓴다(GRADE_RULE). 어구가 빠지면 실패"""
    paragraphs = [r["paragraph_num"] for r in unit["records"]]
    base = {c["check"] for c in faq_checks.run_checks(faq, source, refs, paragraphs) if c["action"] in ("drop", "flag")}
    prompt = build_rewrite_prompt(faq, source)
    system = REWRITE_SYSTEM + "\n" + GRADE_RULE.format(p=grade_phrase) if grade_phrase else REWRITE_SYSTEM
    attempts = []
    for _ in range(MAX_ATTEMPTS):
        raw, used = call_rewrite(prompt, system)
        q = parse_question(raw)
        attempts.append({"raw": raw[:500], "prompt_tokens": used, "question": q,
                         "why": attempt_problems(q, used, faq, source, refs, paragraphs, base, grade_phrase)})
        if not attempts[-1]["why"]:
            break
    status, new_q = settle(faq, attempts)
    return {**faq, "question": new_q or faq["question"], "question_original": faq["question"],
            "rewrite": {"status": status, "attempts": attempts, "model": MODEL_NAME, "temperature": TEMPERATURE,
                        "kind": "grade" if grade_phrase else "plain", "grade_phrase": grade_phrase}}


# ---------- 보존 확인 ----------
def answer_hash(f: dict) -> str:
    return hashlib.sha256(f["answer"].encode("utf-8")).hexdigest()


def preservation_problems(before: list[dict], after: list[dict]) -> list[str]:
    """재작성 전후 레코드를 순서대로 대조. 질문·재작성 메타를 뺀 모든 필드(답변·unit_id·references·references_given…)가 같아야 한다"""
    if len(before) != len(after):
        return [f"건수 다름 {len(before)} → {len(after)}"]
    out = []
    for i, (b, a) in enumerate(zip(before, after)):
        if answer_hash(b) != answer_hash(a):
            out.append(f"[{i}] 답변 해시 다름 ({b['unit_id']})")
        if a.get("question_original") != b["question"]:
            out.append(f"[{i}] question_original이 원래 질문과 다름")
        if a["rewrite"]["status"] in ("parse_fail", "rejected") and a["question"] != b["question"]:
            out.append(f"[{i}] 재작성 실패인데 질문이 바뀜")
        rest_b = {k: v for k, v in b.items() if k != "question"}
        rest_a = {k: v for k, v in a.items() if k != "question" and k not in REWRITE_META}
        if rest_b != rest_a:
            diff = sorted(k for k in rest_b.keys() | rest_a.keys() if rest_b.get(k) != rest_a.get(k))
            out.append(f"[{i}] 질문 외 필드 다름: {diff}")
    return out


# ---------- 표본 ----------
def record_key(f: dict) -> str:
    return f"{f['species']}|{f['round']}|{f['row']}"


def pick_pilot(final: list[dict], n: int = PILOT_N, seed: int = SEED) -> list[dict]:
    """단위당 1건 — 같은 단위의 바꿔 말한 질문이 몰리지 않게. 단위 순서·단위 안 선택 모두 seed로 고정"""
    rng = random.Random(seed)
    by_unit = {}
    for f in final:
        by_unit.setdefault(f["unit_id"], []).append(f)
    uids = sorted(by_unit)
    rng.shuffle(uids)
    return [rng.choice(by_unit[u]) for u in uids[:n]]


# ---------- 실행 ----------
def _load_json(p: Path, default):
    return json.load(open(p, encoding="utf-8")) if p.exists() else default


def _dump(obj, p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    tmp.replace(p)


def _unload(model: str):
    requests.post(f"{OLLAMA_URL}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)


def _assert_model(model: str):
    tags = {m["name"] for m in requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()["models"]}
    assert model in tags, f"{model} 없음 — `docker start ollama` 확인"


class UnitIndex:
    """06과 같은 단위·참조 복원(ContextBuilder는 Milvus 조회만 — 임베딩 모델을 올리지 않는다)"""

    def __init__(self, species: list[str]):
        from data import faq_units, rag_context
        self.rag_context = rag_context
        self.builder = rag_context.ContextBuilder()
        self.units = {sp: {faq_units.unit_id(u): u for u in faq_units.make_units(self.builder.chunks[sp])} for sp in species}
        self._refs = {}

    def get(self, sp: str, uid: str):
        u = self.units[sp].get(uid)
        if u is None:
            return None, None, None
        if (sp, uid) not in self._refs:
            self._refs[(sp, uid)] = self.builder.resolve_references(u, sp, source_chunks=u["records"])
        return u, self._refs[(sp, uid)], self.rag_context.display_text(u)


def run_rewrite(inputs: list[dict], idx: UnitIndex, out_path: Path) -> list[dict]:
    """중간 저장·재개: out_path에 이미 있는 레코드(같은 키·같은 원래 질문)는 건너뛴다"""
    _assert_model(MODEL_NAME)
    done = {(record_key(r), r["question_original"]): r for r in _load_json(out_path, [])}
    out, n_new, t0 = [], 0, time.time()
    for f in inputs:
        r = done.get((record_key(f), f["question"]))
        if r is None:
            u, refs, source = idx.get(f["species"], f["unit_id"])
            assert u is not None, f"현재 데이터에 없는 단위: {f['unit_id']} — 06을 다시 돌린 뒤 재작성할 것"
            r = rewrite_faq(f, u, refs, source)
            n_new += 1
            if n_new % SAVE_EVERY == 0:
                _dump(out + [r], out_path)
                print(f"  재작성 {n_new}건, {(time.time() - t0) / 60:.1f}분")
        out.append(r)
    _dump(out, out_path)
    print(f"재작성 새로 {n_new}건 ({(time.time() - t0) / 60:.1f}분) → {out_path}")
    _unload(MODEL_NAME)          # 재심판(gemma4:12b)이 GPU를 쓰도록
    return out


def run_rejudge(records: list[dict], idx: UnitIndex, cache_path: Path) -> list[dict]:
    """질문이 바뀐 QA만 06 심판에 다시 넣는다. 그대로인 QA는 06 판정(통과)과 입력이 같아 다시 판정하지 않는다"""
    _assert_model(faq_judge.JUDGE_MODEL)
    cache = _load_json(cache_path, {})
    n_new, t0 = 0, time.time()
    for r in records:
        if r["rewrite"]["status"] != "ok":
            r["rejudge"] = None
            continue
        body = faq_checks.answer_body(r["answer"])
        k = hashlib.md5(f"{r['species']}|{r['unit_id']}|{r['question']}|{body}".encode()).hexdigest()
        if k not in cache:
            u, refs, source = idx.get(r["species"], r["unit_id"])
            prompt = faq_judge.build_judge_prompt(r, source, refs, body)      # 06 셀 4와 같은 입력
            res = faq_judge.judge(prompt)
            if res["problem"] is None:                                       # 06과 같이 파싱 실패 한 번 재시도
                res = faq_judge.judge(prompt)
            cache[k] = res
            n_new += 1
            if n_new % SAVE_EVERY == 0:
                _dump(cache, cache_path)
        r["rejudge"] = cache[k]
    _dump(cache, cache_path)
    print(f"재심판 새로 {n_new}건 ({(time.time() - t0) / 60:.1f}분)")
    _unload(faq_judge.JUDGE_MODEL)
    return records


# ---------- 리포트 ----------
def _pct(x: float) -> str:
    return f"{x:.1%}"


def verdict(pass_rate: float, situational: float) -> str:
    if pass_rate >= 0.9 and situational >= 0.5:
        return "재심판 90% 이상 + 상황형 50% 이상 → 전량에 적용"
    if pass_rate >= 0.9:
        return "재심판은 90% 이상이나 상황형 50% 미만 → 재작성 프롬프트 보완(상황형 유도)"
    if pass_rate >= 0.7:
        return "재심판 70~90% → 재작성 프롬프트 보완"
    return "재심판 70% 미만 → 재작성이 뜻을 바꾸고 있다. 설계 재검토"


def render(records: list[dict], problems: list[str], mode: str) -> str:
    st = Counter(r["rewrite"]["status"] for r in records)
    judged = [r for r in records if r.get("rejudge") is not None]
    failed = [r for r in judged if r["rejudge"]["problem"]]
    jfail = [r for r in judged if r["rejudge"]["problem"] is None]
    passed = len(judged) - len(failed) - len(jfail)
    pass_rate = passed / len(judged) if judged else 0
    before = faq_style.style_stats([r["question_original"] for r in records])
    after = faq_style.style_stats([r["question"] for r in records])
    ok_only = faq_style.style_stats([r["question"] for r in records if r["rewrite"]["status"] == "ok"])
    tokens = sorted(a["prompt_tokens"] for r in records for a in r["rewrite"]["attempts"]) or [0]

    L = [f"# FAQ 질문 재작성 — {mode}", "", f"생성: {datetime.now():%Y-%m-%d %H:%M} | 모델 {MODEL_NAME} "
         f"temperature {TEMPERATURE} | 입력 토큰 중앙 {tokens[len(tokens) // 2]} / 최대 {tokens[-1]}", "",
         "## 판단", "",
         f"- 재심판 통과율: **{passed}/{len(judged)} = {_pct(pass_rate)}** (질문이 바뀐 QA만. 심판 파싱 실패 {len(jfail)}건은 분모에 넣고 통과로 세지 않음)",
         f"- 상황형(재작성 후 전체): **{_pct(after['situational'])}** / 라벨 누출 {_pct(before['label_leak'])} → {_pct(after['label_leak'])}",
         f"- **{verdict(pass_rate, after['situational'])}**", "",
         "## 보존 확인 (답변 해시·unit_id·근거 필드)", "",
         f"- {'문제 없음 — ' + str(len(records)) + '건 모두 질문 외 필드가 재작성 전과 같다' if not problems else '문제 ' + str(len(problems)) + '건'}"]
    L += [f"  - {p}" for p in problems[:30]]
    L += ["", "## 재작성 결과", "", "| 상태 | 건수 |", "|---|---|"]
    L += [f"| {s} | {st.get(s, 0)} |" for s in ("ok", "unchanged", "rejected", "parse_fail")]
    why = Counter(w.split(":")[0] for r in records if r["rewrite"]["status"] in ("rejected", "parse_fail")
                  for a in r["rewrite"]["attempts"] for w in a["why"])
    if why:
        L += ["", "원래 질문 유지 사유(시도별, 중복 집계): " + ", ".join(f"{k} {v}" for k, v in why.most_common())]
    L += ["", "## 질문 성질 (faq_style)", "",
          "| 집합 | QA | 라벨 누출 | 상황형 | 질문 길이 중앙 | " + " | ".join(faq_style.TOPICS) + " |",
          "|---|---|---|---|---|" + "---|" * len(faq_style.TOPICS)]
    for name, s in [("재작성 전", before), ("재작성 후(전체, 실패는 원래 질문)", after), ("재작성 성공분만", ok_only)]:
        L.append(f"| {name} | {s['n']} | {_pct(s['label_leak'])} | {_pct(s['situational'])} | {s['q_len_median']} | "
                 + " | ".join(_pct(s["topics"][t]) for t in faq_style.TOPICS) + " |")
    L += ["", "## 재심판 탈락 유형", "", "| 유형 | 건수 |", "|---|---|"]
    types = Counter(t for r in failed for t in r["rejudge"]["types"])
    L += [f"| {t} | {types.get(t, 0)} |" for t in faq_style.JUDGE_TYPES]
    L += ["", f"## 재심판 탈락 QA — 전후 전문 ({len(failed)}건, 원인을 직접 읽을 것)", ""]
    for i, r in enumerate(failed, 1):
        L += [f"### {i}. {r['unit_id']}", "", f"- 전: {r['question_original']}", f"- 후: {r['question']}",
              f"- 답변: {faq_checks.answer_body(r['answer'])}",
              f"- 심판: {r['rejudge']['types']} {r['rejudge']['reason']}", ""]
    rej = [r for r in records if r["rewrite"]["status"] in ("rejected", "parse_fail")]
    L += [f"## 원래 질문 유지 — 버린 재작성 ({len(rej)}건)", ""]
    for r in rej:
        tried = " / ".join(f"{a['question']} ← {'; '.join(a['why'])}" for a in r["rewrite"]["attempts"])
        L.append(f"- {r['question_original']}  ⟶  {tried}")
    ok = [r for r in judged if r["rejudge"]["problem"] is False]
    L += ["", f"## 재심판 통과 예시 (앞 30건 / {len(ok)})", "", "| 전 | 후 | 상황형 |", "|---|---|---|"]
    L += [f"| {r['question_original']} | {r['question']} | {'O' if faq_style.is_situational(r['question']) else ''} |"
          for r in ok[:30]]
    L += ["", "## 해석 시 주의", "",
          f"- 표본 {len(records)}건이라 통과율 ±5~10%p 차이는 구분하기 어렵다.",
          "- 재작성 전 질문은 06 심판을 이미 통과했다(temperature 0 재판정 일치 183/183). 탈락은 질문이 바뀐 탓으로 본다.",
          "- 상황형·라벨 누출은 faq_style 정규식 판정이다. 통과 예시 표의 '상황형' 열로 정의를 확인할 것.",
          "- 원래 질문 유지분은 재심판하지 않았다(입력이 06 때와 같다). 상황형 비율에는 원래 질문으로 들어간다."]
    return "\n".join(L) + "\n"


# ---------- 저장된 재작성에 검사만 다시 ----------
def recheck(out_dir: Path, idx: "UnitIndex") -> list[dict]:
    """모델 호출 없이 out_dir/rewritten.json의 시도마다 지금 규칙(check_rewrite)을 다시 적용한다.
    채택이 바뀐 QA 중 새로 ok가 된 것은 아직 재심판을 받지 않았다 — 결과는 rewritten_recheck.json(원래 파일은 그대로)"""
    records = _load_json(out_dir / "rewritten.json", [])
    judged = {(record_key(r), r["question_original"]): r.get("rejudge")
              for r in _load_json(out_dir / "rewritten_judged.json", [])}
    old_why, new_why, moves, out = Counter(), Counter(), Counter(), []
    for r in records:
        faq = {k: v for k, v in r.items() if k not in REWRITE_META} | {"question": r["question_original"]}
        u, refs, source = idx.get(faq["species"], faq["unit_id"])
        paragraphs = [x["paragraph_num"] for x in u["records"]]
        base = {c["check"] for c in faq_checks.run_checks(faq, source, refs, paragraphs) if c["action"] in ("drop", "flag")}
        attempts = []
        for a in r["rewrite"]["attempts"]:
            old_why.update(w.split(":")[0] for w in a["why"])
            why = attempt_problems(a["question"], a["prompt_tokens"], faq, source, refs, paragraphs, base)
            new_why.update(w.split(":")[0] for w in why)
            attempts.append({**a, "why": why, "why_before": a["why"]})
        status, new_q = settle(faq, attempts)
        moves[(r["rewrite"]["status"], status)] += 1
        rejudge = judged.get((record_key(r), r["question_original"])) if new_q == r["question"] else None
        out.append({**faq, "question": new_q or faq["question"], "question_original": faq["question"],
                    "rewrite": {**r["rewrite"], "status": status, "attempts": attempts, "status_before": r["rewrite"]["status"]},
                    "rejudge": rejudge})
    _dump(out, out_dir / "rewritten_recheck.json")
    before, after = Counter(r["rewrite"]["status"] for r in records), Counter(r["rewrite"]["status"] for r in out)
    print(f"\n재검사 {len(out)}건 ({out_dir.name}) — 모델 호출 없음")
    print("상태  전 → 후: " + ", ".join(f"{k} {before.get(k, 0)} → {after.get(k, 0)}"
                                    for k in ("ok", "unchanged", "rejected", "parse_fail")))
    print("전환: " + ", ".join(f"{a}→{b} {n}" for (a, b), n in sorted(moves.items())))
    print("거부 사유(시도별, 중복 집계) 전: " + ", ".join(f"{k} {v}" for k, v in old_why.most_common()))
    print("거부 사유(시도별, 중복 집계) 후: " + ", ".join(f"{k} {v}" for k, v in new_why.most_common()))
    fresh = [r for r in out if r["rewrite"]["status_before"] != "ok" and r["rewrite"]["status"] == "ok"]
    print(f"\n새로 채택된 재작성 {len(fresh)}건 (재심판 전):")
    for r in fresh:
        print(f"  - {r['question_original']}\n    → {r['question']}")
    still = [r for r in out if r["rewrite"]["status"] == "rejected"]
    print(f"\n여전히 거부 {len(still)}건:")
    for r in still:
        print(f"  - {r['question_original']}\n    ← " + " / ".join(f"{a['question']} [{'; '.join(a['why'])}]"
                                                          for a in r["rewrite"]["attempts"]))
    return out


# ---------- 학습용 내보내기 ----------
def export_final(records: list[dict], out_dir: Path, species: list[str]) -> dict:
    """06 final과 같은 모양으로 종별 저장(finetune_data 입력). 재작성이 채택되고(ok) 재심판을 통과한 QA만 새 질문을 쓰고,
    나머지(거부·그대로·재심판 탈락·심판 파싱 실패)는 06을 통과한 원래 질문으로 되돌린다 — 답변은 원래 질문에 대해 검증됐다"""
    stats = Counter()
    for sp in species:
        rows = []
        for r in (x for x in records if x["species"] == sp):
            use_new = r["rewrite"]["status"] == "ok" and (r.get("rejudge") or {}).get("problem") is False
            stats["rewritten" if use_new else ("reverted_rejudge" if r["rewrite"]["status"] == "ok" else f"kept_{r['rewrite']['status']}")] += 1
            rows.append({k: v for k, v in r.items() if k not in ("rewrite", "rejudge", "question")}
                        | {"question": r["question"] if use_new else r["question_original"],
                           "rewrite_status": r["rewrite"]["status"] if use_new or r["rewrite"]["status"] != "ok" else "reverted_rejudge"})
        _dump(rows, out_dir / "final" / f"petmint_{sp}_faq_final.json")
    print("학습용 내보내기:", dict(stats), "→", out_dir / "final")
    return dict(stats)


# ---------- 06 앞 재작성(순서 B) ----------
def _rkey(f: dict) -> str:
    return f"{f['species']}|{f['unit_id']}|{f['question']}"


def grade_rate(records: list[dict]) -> float:
    """대상(coverage_type 없는 단위) 중 등급 어구로 쓸 비율 — 전체의 GRADE_SHARE가 되게"""
    records = [f for f in records if f.get("gen_kind") not in RATE_EXCLUDE_KINDS]
    elig = sum(f.get("coverage_type") in (None, "None") for f in records)
    return min(1.0, GRADE_SHARE * len(records) / elig) if elig else 0.0


def grade_phrase_for(f: dict, rate: float) -> str | None:
    """해시로 고른다(재현). 이름에 유형(Ⅰ·Ⅱ·Ⅲ)이 붙은 특약은 등급 어구만 — 다른 유형을 말하면 단위와 어긋난다"""
    if f.get("coverage_type") not in (None, "None"):
        return None
    h = int(hashlib.md5(("grade|" + _rkey(f)).encode()).hexdigest(), 16)
    if (h % 10000) / 10000 >= rate:
        return None
    sec = f.get("section_name") or ""
    words = GRADE_WORDS if any(t in sec for t in ("Ⅰ", "Ⅱ", "Ⅲ")) else GRADE_WORDS + TYPE_WORDS
    word = words[(h // 10000) % len(words)]
    if word in TYPE_WORDS:
        h2 = int(hashlib.md5(("combo|" + _rkey(f)).encode()).hexdigest(), 16)
        if (h2 % 10000) / 10000 < COMBO_SHARE:
            word = f"{GRADE_WORDS[(h2 // 10000) % len(GRADE_WORDS)]} {word}"
    return word


def progress_key(f: dict, phrase: str | None) -> str:
    """재작성 중간 저장 키. 등급 + 유형 조합(rebuild4)은 같은 QA의 예전 결과(유형 어구만)와 섞이지 않게 어구를 붙인다 —
    그 밖에는 예전 키 그대로라 rebuild3 중간 저장을 이어 쓴다"""
    return _rkey(f) + (f"|{phrase}" if phrase and " " in phrase else "")


def run_pre(records: list[dict], idx: "UnitIndex", progress_path: Path, rate: float) -> list[dict]:
    """05 QA(또는 B-1′의 06 final) 전부 재작성. 재작성이 실패하면 원래 질문 그대로 남는다(06이 그대로 심판). 중간 저장·재개"""
    done = _load_json(progress_path, {})
    out, n_new, t0 = [], 0, time.time()
    for f in records:
        phrase = grade_phrase_for(f, rate)
        k = progress_key(f, phrase)
        if k not in done:
            u, refs, source = idx.get(f["species"], f["unit_id"])
            assert u is not None, f"현재 데이터에 없는 단위: {f['unit_id']}"
            r = rewrite_faq(f, u, refs, source, phrase)
            done[k] = {"question": r["question"], "rewrite": r["rewrite"]}
            n_new += 1
            if n_new % SAVE_EVERY == 0:
                _dump(done, progress_path)
                print(f"  재작성 {n_new}건, {(time.time() - t0) / 60:.1f}분", flush=True)
        d = done[k]
        st = d["rewrite"]["status"]
        out.append({**f, "question": d["question"], "question_original": f["question"], "rewrite": d["rewrite"],
                    "rewrite_status": st if d["rewrite"].get("kind") != "grade" else f"grade_{st}"})
    _dump(done, progress_path)
    if n_new:
        print(f"재작성 새로 {n_new}건 ({(time.time() - t0) / 60:.1f}분)", flush=True)
    return out


def pre_summary(records: list[dict]) -> dict:
    ok = [r for r in records if r["rewrite"]["status"] == "ok"]
    g = [r for r in records if r["rewrite"].get("kind") == "grade"]
    s = faq_style.style_stats([r["question"] for r in records])
    return {"n": len(records), "status": dict(Counter(r["rewrite"]["status"] for r in records)),
            "grade_target": len(g), "grade_ok": sum(r["rewrite"]["status"] == "ok" for r in g),
            "grade_ok_share": round(sum(r["rewrite"]["status"] == "ok" for r in g) / max(len(records), 1), 4),
            "fail_rate": round(1 - (len(ok) + sum(r["rewrite"]["status"] == "unchanged" for r in records)) / max(len(records), 1), 4),
            "label_leak": round(s["label_leak"], 4), "situational": round(s["situational"], 4), "q_len_median": s["q_len_median"]}


def set_model(model: str):
    global MODEL_NAME, OLLAMA_EXTRA
    MODEL_NAME = model
    OLLAMA_EXTRA = {"think": False} if model.startswith("qwen3") else {}


def main_pre(src: Path, out: Path, species: list[str]):
    """순서 B: <src>의 05 라운드 파일 → 재작성한 라운드 파일을 <out>에 같은 이름으로(+ _failures.json·plan.json 복사).
    06은 PETMINT_06_INPUT=<out>(data/faq 기준)으로 이 폴더를 읽는다. 라운드마다 완료 표시(_failures.json)를 마지막에 쓴다"""
    import shutil
    rounds = sorted(p for sp in species for p in src.glob(f"petmint_{sp}_faq_round*.json") if not p.stem.endswith("_failures"))
    assert rounds, f"05 라운드 파일 없음: {src}"
    out.mkdir(parents=True, exist_ok=True)
    allrec = [f for p in rounds for f in _load_json(p, [])]
    rate = grade_rate(allrec)
    print(f"05 QA {len(allrec)}건, 라운드 파일 {len(rounds)}개 | 등급 어구 대상 비율 {rate:.3f} → 예상 {GRADE_SHARE:.0%} | 모델 {MODEL_NAME} {OLLAMA_EXTRA}")
    idx = UnitIndex(species)
    _assert_model(MODEL_NAME)
    for p in rounds:
        dst, fail = out / p.name, out / (p.stem + "_failures.json")
        if dst.exists() and fail.exists():
            continue
        before = _load_json(p, [])
        after = run_pre(before, idx, out / "progress" / f"{p.stem}.json", rate)
        problems = preservation_problems(before, after)
        assert not problems, f"{p.name}: 재작성이 질문 외 필드를 바꿨다:\n" + "\n".join(problems[:20])
        _dump(after, dst)
        shutil.copy2(p.with_name(p.stem + "_failures.json"), fail)
        print(f"{p.name}: {len(after)}건 {dict(Counter(r['rewrite_status'] for r in after))}", flush=True)
    if (src / "plan.json").exists():
        shutil.copy2(src / "plan.json", out / "plan.json")      # 06이 주제 가중치(단위 상한)를 같은 계획으로 적용한다
    _unload(MODEL_NAME)
    recs = [f for p in rounds for f in _load_json(out / p.name, [])]
    summ = pre_summary(recs)
    _dump(summ, out / "rewrite_summary.json")
    print("재작성 요약:", summ)


def main_pre_final(src: Path, out: Path, species: list[str]):
    """B-1′(2026-10-16): 06 final을 순서 B처럼 전부 재작성해 <out>/final/에 쓴다 — 재구축 전에 build 검사를 예측하는 용도.
    06 재심판은 하지 않는다(rebuild3에서는 06이 재작성한 질문을 심판한다 — 그 탈락만큼 이 예측과 다르다)"""
    recs = [f for sp in species for f in _load_json(src / "checked" / f"petmint_{sp}_faq_final.json", [])]
    idx = UnitIndex(species)
    recs = [f for f in recs if f["unit_id"] in idx.units[f["species"]]]
    rate = grade_rate(recs)
    print(f"06 final {len(recs)}건 | 등급 어구 대상 비율 {rate:.3f} | 모델 {MODEL_NAME} {OLLAMA_EXTRA}", flush=True)
    _assert_model(MODEL_NAME)
    after = run_pre(recs, idx, out / "progress.json", rate)
    _unload(MODEL_NAME)
    for sp in species:
        _dump([r for r in after if r["species"] == sp], out / "final" / f"petmint_{sp}_faq_final.json")
    summ = pre_summary(after)
    _dump(summ, out / "rewrite_summary.json")
    print("재작성 요약:", summ)


def main(argv=None):
    """python -m data.faq_rewrite pilot [종]   — final에서 100건(기본 강아지)
       python -m data.faq_rewrite all [종...] — final 전량(판단 기준 통과 후). 끝나면 <out>/final/에 학습용 final을 쓴다
       python -m data.faq_rewrite recheck [폴더명] — 저장된 재작성 시도에 지금 검사 규칙만 다시(모델 호출 없음, 기본 pilot_강아지)
       python -m data.faq_rewrite pre [종...] --src=<05 출력> --out=<06 입력> [--model=qwen3:14b]
           — 순서 B(rebuild3): 05 QA 전부를 06 앞에서 재작성(공통 조항 일부는 등급 어구로). 재심판 없음
       python -m data.faq_rewrite pre-final [종...] --src=<06 출력> --out=<폴더> [--model=…] — B-1′: 06 final을 같은 방식으로(예측용)
       단계만: --rewrite-only / --judge-only (재작성 → 생성 모델 내림 → 재심판 순서는 같다)
       입력·출력: --src=<06 출력 폴더(…/checked의 상위)> --out=<출력 폴더> (기본: data/faq, data/faq/rewrite/<모드>)"""
    args = list(sys.argv[1:] if argv is None else argv)
    opts = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
    flags = {a for a in args if a.startswith("--") and "=" not in a}
    args = [a for a in args if not a.startswith("--")]
    mode = args[0] if args else "pilot"
    assert mode in ("pilot", "all", "recheck", "pre", "pre-final"), "모드는 pilot, all, recheck, pre, pre-final"
    if "model" in opts:
        set_model(opts["model"])
    if mode in ("pre", "pre-final"):
        species = args[1:] or ["강아지", "고양이"]
        (main_pre if mode == "pre" else main_pre_final)(Path(opts["src"]), Path(opts["out"]), species)
        return
    if mode == "recheck":
        out_dir = OUT_ROOT / (args[1] if len(args) > 1 else "pilot_강아지")
        species = sorted({r["species"] for r in _load_json(out_dir / "rewritten.json", [])})
        recheck(out_dir, UnitIndex(species))
        return
    species = args[1:] or (["강아지"] if mode == "pilot" else ["강아지", "고양이"])
    src_dir = Path(opts.get("src", FAQ_DIR))
    out_dir = Path(opts["out"]) if "out" in opts else OUT_ROOT / (mode if mode == "all" else f"pilot_{'_'.join(species)}")
    out_dir.mkdir(parents=True, exist_ok=True)

    idx = UnitIndex(species)
    input_path = out_dir / "input.json"
    if input_path.exists():                       # 같은 표본으로 이어서/다시 — final이 바뀌어도 표본은 고정
        inputs = _load_json(input_path, [])
    else:
        final = [f for sp in species for f in _load_json(src_dir / "checked" / f"petmint_{sp}_faq_final.json", [])]
        assert final, f"06 final 없음: {src_dir / 'checked'}"
        # checked/final(2026-10-13)은 사람 대상 조항 제외(faq_units.is_human_target) 전 결과다 — 지금 단위에 없는 QA는
        # 06을 다시 돌리면 unit_excluded로 버려지므로 뺀다(측정: 강아지 487·고양이 500건, 전부 제외 단위)
        kept = [f for f in final if f["unit_id"] in idx.units[f["species"]]]
        print(f"final {len(final)}건 중 현재 단위에 없는 QA {len(final) - len(kept)}건 제외")
        inputs = pick_pilot(kept) if mode == "pilot" else kept
        _dump(inputs, input_path)
    print(f"{mode}: 입력 {len(inputs)}건 ({species}) → {out_dir}")
    rewrite_path = out_dir / "rewritten.json"
    records = _load_json(rewrite_path, []) if "--judge-only" in flags else run_rewrite(inputs, idx, rewrite_path)
    problems = preservation_problems(inputs, records)
    assert not problems, "재작성이 질문 외 필드를 바꿨다:\n" + "\n".join(problems[:20])
    print(f"보존 확인 통과: {len(records)}건 답변 해시·unit_id·근거 필드 동일")
    if "--rewrite-only" in flags:
        return
    records = run_rejudge(records, idx, out_dir / "rejudge_cache.json")
    _dump(records, out_dir / "rewritten_judged.json")
    md = render(records, problems, out_dir.name)
    out = REVIEW_DIR / f"faq_rewrite_{out_dir.name}_{datetime.now():%Y%m%d_%H%M}.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print("저장:", out)
    if mode == "all":
        export_final(records, out_dir, species)


if __name__ == "__main__":
    main()
