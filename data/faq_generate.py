"""
faq_generate.py
05 FAQ 전량 생성 — 전체 재구축(2026-10-14)용. 노트북 05의 v1 생성 경로를 그대로 옮기고 두 가지를 더한다.
노트북 05는 실험 기록(실험 C 셀 포함)으로 그대로 둔다. 프롬프트·생성 설정이 노트북과 같은지는 assert_same_as_notebook이
노트북 셀 원문을 ast로 읽어 매 실행마다 확인한다(어긋나면 멈춘다).

더하는 것
1. 주제 가중치(data/topic_weights.py): 단위별 생성 횟수 = 기본 횟수 × 가중치(반올림, 최소 1).
   기본 횟수는 기존 전량과 같다 — 원문 600자 이상 단위 10회, 짧은 단위는 강아지 7회·고양이 8회
   (노트북 셀 9 LONG_UNIT_ONLY_FROM_ROUND: 추가 생성 라운드는 긴 단위만).
   생성 라운드 r은 생성 횟수가 r 이상인 단위만 돈다. temperature는 기존 10라운드 값을 순환(0.7 초과는 측정한 적 없어 쓰지 않는다).
2. 주제 지정 회차: ×3 묶음 중 원문이 그 주제를 다루는 단위(faq_style.eligible_topics)에, 주제마다 TOPIC_ROUNDS 수만큼.
   실험 C v2C-T r2 방식(끝에 [주제] 줄, 주제 질문 2개)이되 ① 질문 프롬프트는 v1이다 — v2 계열의 구어체·상황형 지시는 넣지 않는다.
   구어체는 06 뒤 재작성 단계(data/faq_rewrite.py)가 맡는다. ② 한 호출에 주제 하나 — v2C-T는 원문이 다루는 주제를 한 줄에 다 넣어
   질문 2개가 흔한 주제로 쏠릴 수 있었다. 주제마다 회차 수를 따로 정해야 드문 주제(가입 나이·기왕증)를 늘릴 수 있다.
   측정(2026-10-14): 원문에 가입 나이가 있는 단위는 종마다 4개(×3 묶음 2개: 일반조항 제2·15조), 기왕증 9개(×3 8개)뿐이다.
   실험 C의 가입 나이 9.5%는 28단위 표본에 그 단위가 들어 있어서 나온 값이라 전량 비율로 옮겨지지 않는다 — 생성 전 예상 분포는
   python -m data.topic_weights 로 본다. 주제 회차 파일은 round101부터(일반 라운드 수가 가중치에 따라 달라도 번호가 겹치지 않게).

출력: <out_dir>/petmint_{종}_faq_round{N}.json (+ _failures.json = 완료 표시, 노트북 round_done과 같은 규칙) + plan.json
      plan.json이 이미 있는데 지금 계획과 다르면 멈춘다 — 다른 가중치로 만든 라운드가 섞이지 않게.

3. 참조 회차(2026-10-14, REF_ROUNDS = 0으로 꺼 둠 — 파일럿 기각): 다른 조 참조가 있는 조항형 단위(rag_context.cross_article_refs)에
   QA 1개짜리 호출을 REF_ROUNDS번 더한다.
   참조를 [함께 적용되는 다른 조항]으로 따로 보여 주고 두 조항이 모두 있어야 답할 수 있는 고객 질문을 만든다(SYSTEM_PROMPT_REF).
   일반·주제 회차는 v1 그대로. 파일은 round201부터, QA의 gen_kind "ref". 채택 전 파일럿: pilot-ref → 06 → python -m data.ref_usage.

실행: python -m data.faq_generate plan               — 계획·예상 시간만(Ollama 불필요)
      python -m data.faq_generate run --out=DIR      — 생성(tri-7b, GPU). 끝난 라운드는 건너뛴다
          --model=qwen3:14b  생성 모델 바꾸기(rebuild3, think 끔)   --smoke=20,10  소규모 시험(종마다 앞 N단위, 라운드 1 + 주제 회차 1씩)
      python -m data.faq_generate show-ref           — 참조 회차 프롬프트 예시(섹션마다 1개, 모델 호출 없음)
      python -m data.faq_generate pilot-ref [--out=data/faq/exp_r]  — 파일럿 생성(tri-7b, 참조 회차 60호출 ≈ 3분)
"""

import ast
import json
import random
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import requests

from data import faq_style, faq_units, faq_verify, rag_context, topic_weights
from data.faq_units import build_citation_suffix, main_label, unit_id

PROJECT_DIR = Path(__file__).resolve().parent.parent
NOTEBOOK_05 = PROJECT_DIR / "notebooks" / "05_FAQ_생성.ipynb"

# ---------- 노트북 05와 같아야 하는 값(assert_same_as_notebook이 확인) ----------
OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "tri-7b:latest"
NUM_CTX = 8192
NUM_PREDICT = 1200
PROMPT_BUDGET = NUM_CTX - NUM_PREDICT

ARTICLE_PROMPT_TEMPLATE = """출처: {section_name}
조항: {label}
{content}

관련 조항 (보충 설명용):
{references_text}
"""

GUIDE_PROMPT_TEMPLATE = """분류: {section} {section_name}
{content}
"""

SYSTEM_PROMPT_ARTICLE = """당신은 반려동물 보험 상담 FAQ를 만드는 전문가입니다.
- 주어진 약관 조항에 적힌 사실만 근거로 질문과 답변을 만드세요. 원문에 없는 숫자, 금액, 날짜, 비율은 절대로 만들어내지 마세요.
- 원문에 구체적인 수치가 없으면 "회사가 정한 기준에 따릅니다"처럼 돌려 표현하세요.
- 보험금 계산 질문은 원문에 있는 계산 예시(치료비·자기부담금·결과 금액)를 그대로 사용하세요. 원문에 없는 새 금액으로 직접 계산하지 마세요.
- 서로 다른 관점에서 3개의 질문-답변 쌍을 만드세요.
- 답변은 2~4문장으로 자연스럽게 설명하세요. "근거" 표기는 쓰지 마세요.
- 반드시 아래 JSON 배열 형식으로만 출력하세요.
[{"question": "...", "answer": "..."}, {"question": "...", "answer": "..."}, {"question": "...", "answer": "..."}]
"""

SYSTEM_PROMPT_GUIDE = """당신은 반려동물 보험 상담 FAQ를 만드는 전문가입니다.
- 주어진 안내 자료에 적힌 사실만 근거로 개념 설명형 질문과 답변을 만드세요. 지어내지 마세요.
- 서로 다른 관점에서 2개의 질문-답변 쌍을 만드세요.
- 답변은 2~4문장으로 자연스럽게 설명하세요. "근거" 표기는 쓰지 마세요.
- 반드시 아래 JSON 배열 형식으로만 출력하세요.
[{"question": "...", "answer": "..."}, {"question": "...", "answer": "..."}]
"""

PERSPECTIVE_ARTICLE = "- 서로 다른 관점에서 3개의 질문-답변 쌍을 만드세요."
JSON_3 = SYSTEM_PROMPT_ARTICLE[SYSTEM_PROMPT_ARTICLE.index("- 반드시 아래 JSON"):]
JSON_2 = SYSTEM_PROMPT_GUIDE[SYSTEM_PROMPT_GUIDE.index("- 반드시 아래 JSON"):]

ROUND_TEMPERATURES = {
    "강아지": [0.5, 0.45, 0.55, 0.65, 0.5, 0.6, 0.4, 0.7, 0.65, 0.7],
    "고양이": [0.5, 0.45, 0.55, 0.65, 0.6, 0.4, 0.35, 0.7, 0.65, 0.7],
}
LONG_UNIT_ONLY_FROM_ROUND = {"강아지": 8, "고양이": 9}
LONG_UNIT_MIN_CHARS = 600
SHARED_WITH_NOTEBOOK = ("MODEL_NAME", "NUM_CTX", "NUM_PREDICT", "ARTICLE_PROMPT_TEMPLATE", "GUIDE_PROMPT_TEMPLATE",
                        "SYSTEM_PROMPT_ARTICLE", "SYSTEM_PROMPT_GUIDE", "PERSPECTIVE_ARTICLE", "ROUND_TEMPERATURES",
                        "LONG_UNIT_ONLY_FROM_ROUND", "LONG_UNIT_MIN_CHARS")

# ---------- 이 모듈에서 더한 것 ----------
# 주제 회차 — v1 조항형 시스템 프롬프트에서 "서로 다른 관점에서 3개" 한 줄과 JSON 형식(3개 → 2개)만 바꾼다.
# 실험 C의 SYSTEM_PROMPT_TOPIC(V2 계열)에서 질문 지시(구어체·상황형·가입 전 고객 예외)를 뺀 것이다.
TOPIC_LINE = "- 아래 [주제]에 대해 고객이 실제로 묻는 질문 2개를 만드세요. 원문이 답하는 범위 안에서만 만드세요."
SYSTEM_PROMPT_TOPIC_V1 = SYSTEM_PROMPT_ARTICLE.replace(PERSPECTIVE_ARTICLE, TOPIC_LINE).replace(JSON_3, JSON_2)
assert SYSTEM_PROMPT_TOPIC_V1.count(TOPIC_LINE) == 1 and JSON_2 in SYSTEM_PROMPT_TOPIC_V1 and JSON_3 not in SYSTEM_PROMPT_TOPIC_V1
assert [l for l in SYSTEM_PROMPT_TOPIC_V1.splitlines() if l != TOPIC_LINE and l not in JSON_2.splitlines()] == \
    [l for l in SYSTEM_PROMPT_ARTICLE.splitlines() if l != PERSPECTIVE_ARTICLE and l not in JSON_3.splitlines()], \
    "주제 회차 프롬프트가 v1과 질문 줄·JSON 줄 외에 달라졌다"

# 참조 회차 — 다른 조 참조(rag_context.cross_article_refs)가 있는 조항형 단위에 QA 1개짜리 호출을 따로 더한다(일반 회차는 v1 그대로).
# 측정(2026-10-14, 기존 전량): 다른 조 참조 단위 QA 4514건 중 참조 내용을 쓴 것은 17%, 06 탈락률은 참조를 쓰든 안 쓰든
# 같았다(59.7% vs 57.9%) — 걸러져서가 아니라 안 써서 적다. v1은 참조를 본문 끝 '보충 설명용'으로만 붙이고 쓰라는 말이 없다.
# 먼저 시험한 v1r(일반 회차 3개 중 1개를 참조형으로, 파일럿 강아지 60단위, data/review/ref_usage_20261014_2031.md)은 기각:
# 참조 내용 사용 16.9% → 22.1%(기준 33%)뿐이고 늘어난 몫은 대부분 조번호 언급(13% → 25%), 지시가 길어져 답 없이 질문만 낸
# 단위가 9개(v1 1개), 질문에 프롬프트 표현("[함께 적용되는 다른 조항]에 따르면")이 14/149건 새어 나왔다.
# → 일반 회차는 건드리지 않고(형식이 깨질 위험 없음), 참조형 질문 하나만 만드는 짧은 호출을 주제 회차처럼 따로 둔다.
REF_SECTION = "[함께 적용되는 다른 조항]"
REF_PROMPT_TEMPLATE = """출처: {section_name}
조항: {label}
{content}

""" + REF_SECTION + """
{cross_text}

관련 조항 (보충 설명용):
{references_text}
"""
FACT_ARTICLE = "- 주어진 약관 조항에 적힌 사실만 근거로 질문과 답변을 만드세요."
FACT_REF = f"- 주어진 약관 조항과 {REF_SECTION}에 적힌 사실만 근거로 질문과 답변을 만드세요."
REF_LINES = (f"- 위 조항과 {REF_SECTION}을 함께 봐야 답할 수 있는 질문-답변 1개를 만드세요. "
             f"답변에는 다른 조항의 조건·기간·숫자를 원문 그대로 옮기세요.\n"
             f"- 질문에는 \"다른 조항\", \"{REF_SECTION}\" 같은 말이나 조문 번호(제○조)를 쓰지 마세요.\n"
             f"- 질문은 고객이 실제로 묻는 말로 쓰되, 위 조항만으로는 답할 수 없고 두 조항이 모두 있어야 답할 수 있게 만드세요.\n"
             f"- 다른 조항은 본문이 그 조항을 가리키는 경우에만 적용하세요. 다른 조항의 예외·단서를 본문의 다른 경우에 섞지 마세요.")
JSON_1 = JSON_3.split("\n")[0] + '\n[{"question": "...", "answer": "..."}]\n'
assert SYSTEM_PROMPT_ARTICLE.count(FACT_ARTICLE) == 1 and SYSTEM_PROMPT_ARTICLE.count(PERSPECTIVE_ARTICLE) == 1
SYSTEM_PROMPT_REF = SYSTEM_PROMPT_ARTICLE.replace(FACT_ARTICLE, FACT_REF).replace(PERSPECTIVE_ARTICLE, REF_LINES) \
    .replace(JSON_3, JSON_1)
assert [l for l in SYSTEM_PROMPT_ARTICLE.splitlines()
        if l != PERSPECTIVE_ARTICLE and not l.startswith(FACT_ARTICLE) and l not in JSON_3.splitlines()] == \
    [l for l in SYSTEM_PROMPT_REF.splitlines()
     if l not in REF_LINES.splitlines() and not l.startswith(FACT_REF) and l not in JSON_1.splitlines()], \
    "참조 회차 프롬프트가 v1과 근거 줄·관점 줄·JSON 줄 외에 달라졌다"
assert SYSTEM_PROMPT_ARTICLE.split(FACT_ARTICLE, 1)[1].split("\n", 1)[0] == \
    SYSTEM_PROMPT_REF.split(FACT_REF, 1)[1].split("\n", 1)[0], "근거 줄 뒷부분(숫자 지어내기 금지)이 달라졌다"
# 참조 회차 수(단위마다 같은 수). temperature는 TOPIC_TEMPERATURES 순환.
# 0 = 끔(2026-10-14 파일럿 기각, data/review/ref_usage_20261014_2053.md — 강아지 60단위 참조 회차 1회 vs v1 일반 회차 1회):
# 참조 회차 QA 124건(1개를 지시했는데 호출당 약 2건) — 참조 내용 사용 22.6%(기준 50%), 질문 노출 25.8%(5%), 형식 실패 6.7%(5%),
# 심판 탈락 76.0%(v1 57.6%) — fabricated 13.2%(4.1%)·clause_mix 21.5%(8.7%)·reversal 19.0%(12.8%).
# 06 통과 + 참조 내용 사용은 호출당 0.10건(60호출에 6건). 전량 재구축은 v1만으로 한다 — 코드는 다시 시험할 때를 위해 남긴다.
REF_ROUNDS = 0
REF_ROUND_START = 201      # 주제 회차(101~)와 번호가 겹치지 않게
PILOT_REF_UNITS = 60       # pilot-ref: 강아지 다른 조 단위(96개) 중 섹션 비율대로. 30단위는 ±10%p 흔들려 판단이 안 된다
PILOT_REF_TEMPERATURE = 0.5

# 주제 → 회차 수. 회차마다 temperature는 TOPIC_TEMPERATURES를 순환(실험 C v2C-T r2는 0.5 한 번).
# 드문 주제일수록 많이 — 대상 단위가 적어(가입 나이 2단위) 호출 수는 크지 않다. 값은 예상 분포를 보고 정한 초기값이다.
TOPIC_ROUNDS = {"가입 나이": 10, "기왕증": 6, "자기부담금": 2, "면책·보장개시": 2, "보장 제외": 2}
TOPIC_TEMPERATURES = [0.5, 0.6, 0.45, 0.55, 0.65, 0.4, 0.7]
TOPIC_ROUND_START = 101
SEED = 42                               # 노트북 셀 9와 같은 단위 순서(random.seed(42) 뒤 강아지 → 고양이 순으로 섞음)
SAVE_EVERY = 50
SEC_PER_CALL = 3.1     # 예상 시간용 — 2026-10-13 고양이 생성 라운드 9·10: 178단위 9.2~9.3분(재시도 포함) = 단위당 3.1초


# ---------- 노트북과 같은지 ----------
def notebook_values(names=SHARED_WITH_NOTEBOOK) -> dict:
    """노트북 05 코드 셀에서 `이름 = 리터럴` 대입을 ast로 읽는다(셀을 실행하지 않는다)"""
    nb = json.load(open(NOTEBOOK_05, encoding="utf-8"))
    found = {}
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        try:
            tree = ast.parse("".join(cell["source"]))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and node.targets[0].id in names:
                try:
                    found[node.targets[0].id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return found


def assert_same_as_notebook():
    """프롬프트·생성 설정이 노트북 05와 같은지. 생성 모델만은 --model로 바꿀 수 있다(rebuild3 2026-10-16: qwen3:14b) —
    노트북에는 tri-7b가 적혀 있으므로 MODEL_NAME은 바꿨을 때만 비교에서 뺀다(나머지 프롬프트·온도·길이는 그대로 비교)"""
    nb = notebook_values()
    here = globals()
    names = [n for n in SHARED_WITH_NOTEBOOK if not (n == "MODEL_NAME" and MODEL_OVERRIDDEN)]
    missing = [n for n in names if n not in nb]
    diff = [n for n in names if n in nb and nb[n] != here[n]]
    assert not missing and not diff, f"노트북 05와 다름 — 없음 {missing}, 값 다름 {diff}"


MODEL_OVERRIDDEN = False
SEC_PER_CALL_BY_MODEL = {"tri-7b:latest": 3.1,   # 2026-10-13·15 전량 실측
                         "qwen3:14b": 5.4}       # 실험 G(2026-10-16) 호출당 시간 비 1.75 × 3.1 — 추정


def set_model(model: str):
    """생성 모델 바꾸기. qwen3는 think 끔 — 생각 출력이 num_predict를 먹어 JSON이 잘린다"""
    global MODEL_NAME, OLLAMA_EXTRA, MODEL_OVERRIDDEN, SEC_PER_CALL
    MODEL_OVERRIDDEN = model != MODEL_NAME or MODEL_OVERRIDDEN
    MODEL_NAME = model
    OLLAMA_EXTRA = {"think": False} if model.startswith("qwen3") else {}
    SEC_PER_CALL = SEC_PER_CALL_BY_MODEL.get(model, SEC_PER_CALL)


def smoke_plan(plan: dict, n_by_sp: dict[str, int]) -> dict:
    """소규모 시험: 종마다 생성 순서 앞 n단위만, 일반 라운드 1 + 주제마다 첫 주제 회차 1(그 단위가 대상이면)"""
    out = {**plan, "smoke": n_by_sp, "rounds": {}}
    for sp, rounds in plan["rounds"].items():
        keep = set(rounds[0]["unit_ids"][:n_by_sp.get(sp, 0)])
        new, seen_topics = [], set()
        for rd in rounds:
            ids = [u for u in rd["unit_ids"] if u in keep]
            if not ids:
                continue
            if rd["kind"] == "normal" and rd["round"] == 1:
                new.append({**rd, "unit_ids": ids})
            elif rd["kind"] == "topic" and rd["topic"] not in seen_topics:
                seen_topics.add(rd["topic"])
                new.append({**rd, "unit_ids": ids})
        out["rounds"][sp] = new
    return out


# ---------- 프롬프트·호출 (노트북 셀 3·5·6·7과 같은 동작, v1 경로만) ----------
def get_prompt_type(unit: dict) -> str:
    return "조항형" if unit.get("article_num") is not None else "안내형"


def has_cross_refs(unit: dict, references: list[dict]) -> bool:
    """참조 회차 대상인가 — 조항형 + 다른 조 참조 있음"""
    return get_prompt_type(unit) == "조항형" and bool(rag_context.cross_article_refs(unit, references)[0])


def _refs_text(refs: list[dict], unit: dict | None = None) -> str:
    """unit을 주면 다른 문서의 조항 앞에 문서 이름을 붙인다(표시만 — citation_label·06 심판 입력은 그대로)"""
    def head(ref):
        if unit is None or ref.get("section_name") == unit.get("section_name"):
            return ref["citation_label"]
        return f"「{ref.get('section_name') or '보통약관'}」 {ref['citation_label']}"
    return "".join(f"\n{head(ref)}\n{ref['content']}\n" for ref in refs if ref.get("content")) or "(없음)"


def build_single_prompt(unit: dict, references: list[dict], topics: list[str] | None = None, ref_prompt: bool = False) -> str:
    content = rag_context.display_text(unit)
    if get_prompt_type(unit) == "조항형" and ref_prompt:
        cross, other = rag_context.cross_article_refs(unit, references)
        prompt = REF_PROMPT_TEMPLATE.format(section_name=unit.get("section_name") or unit["section"],
                                            label=main_label(unit), content=content,
                                            cross_text=_refs_text(cross, unit), references_text=_refs_text(other))
    elif get_prompt_type(unit) == "조항형":
        references_text = "".join(f"\n{ref['citation_label']}\n{ref['content']}\n"
                                  for ref in references if ref.get("content")) or "(없음)"
        prompt = ARTICLE_PROMPT_TEMPLATE.format(section_name=unit.get("section_name") or unit["section"],
                                                label=main_label(unit), content=content, references_text=references_text)
    else:
        prompt = GUIDE_PROMPT_TEMPLATE.format(section=unit["section"], section_name=unit.get("section_name") or "",
                                              content=content)
    if topics:
        prompt += f"\n[주제] {', '.join(topics)}\n"
    return prompt


truncation_log = []
# 실험용(data/exp_gen_model.py): 요청에 더할 필드(qwen3는 {"think": False} — 생각 출력이 num_predict를 먹는다)와 호출별 토큰·시간.
# 전량 생성(run)은 OLLAMA_EXTRA를 비워 둔다 — 요청 본문이 노트북 05와 같다
OLLAMA_EXTRA: dict = {}
call_log: list[dict] = []


def call_ollama(prompt: str, unit: dict, temperature: float, system: str | None = None) -> str:
    system_prompt = system or (SYSTEM_PROMPT_ARTICLE if get_prompt_type(unit) == "조항형" else SYSTEM_PROMPT_GUIDE)
    response = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": MODEL_NAME, "system": system_prompt, "prompt": prompt, "stream": False,
        "options": {"temperature": temperature, "repeat_penalty": 1.1, "num_predict": NUM_PREDICT, "num_ctx": NUM_CTX},
        **OLLAMA_EXTRA,
    })
    response.raise_for_status()
    body = response.json()
    call_log.append({"unit_id": unit_id(unit), "model": MODEL_NAME,
                     **{k: body.get(k) for k in ("prompt_eval_count", "eval_count", "eval_duration", "total_duration", "load_duration")}})
    used = body.get("prompt_eval_count") or 0
    if used >= PROMPT_BUDGET:
        truncation_log.append((unit_id(unit), used))
        print(f"  !! 입력 {used}토큰 ≥ 예산 {PROMPT_BUDGET} — 앞부분이 잘렸을 수 있음: {unit_id(unit)}")
    return body["response"]


def has_chinese_sentence(text: str) -> bool:
    return bool(re.search(r'[一-鿿]{4,}', text)) and bool(re.search(r'[的了是在您]', text))


def finalize_answer(raw_answer: str, unit: dict, refs: list[dict]) -> tuple[str, list[dict]]:
    body = re.sub(r'\s*근거\s*:.*$', '', raw_answer, flags=re.DOTALL).strip()
    used = rag_context.used_references(body, refs + unit.get("merged_refs", []), unit["content"],
                                       unit_article=unit.get("article_num"))
    return f"{body} {build_citation_suffix(unit, used)}", used


def fix_missing_commas(raw: str) -> str:
    return re.sub(r'"\s*\n(\s*)"', '",\n\\1"', raw)


def extract_json(raw: str):
    raw = raw.strip()
    raw = re.sub(r"^```(json)?", "", raw)
    raw = re.sub(r"```$", "", raw)
    raw = fix_missing_commas(raw.strip())
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return None


def call_ollama_with_retry(prompt: str, unit: dict, temperature: float, max_retries: int = 2, system: str | None = None):
    raws = []
    for _ in range(max_retries):
        raw = call_ollama(prompt, unit, temperature=temperature, system=system)
        raws.append(raw)
        parsed = extract_json(raw)
        if parsed:
            return parsed, raws
    return None, raws


def generate_for_unit(builder, unit: dict, species: str, temperature: float, kind: str = "normal",
                      topic: str | None = None) -> dict:
    """노트북 generate_for_unit의 v1 경로. kind "topic" = 주제 회차(v1 + [주제] 한 줄, 주제 하나),
    "ref" = 참조 회차(다른 조 참조를 따로 보여 주고 두 조항을 엮는 QA 1개)"""
    refs = builder.resolve_references(unit, species, source_chunks=unit["records"])
    topics = [topic] if kind == "topic" else []
    assert kind != "topic" or topic in faq_style.eligible_topics(unit["content"]), \
        f"주제 회차인데 원문이 '{topic}'을 다루지 않음: {unit_id(unit)}"
    ref_prompt = kind == "ref"
    assert not ref_prompt or has_cross_refs(unit, refs), f"참조 회차인데 다른 조 참조가 없음: {unit_id(unit)}"
    system = {"topic": SYSTEM_PROMPT_TOPIC_V1, "ref": SYSTEM_PROMPT_REF}.get(kind)
    parsed, raws = call_ollama_with_retry(build_single_prompt(unit, refs, topics or None, ref_prompt), unit,
                                          temperature=temperature, system=system)
    result = {"status": "parse_fail", "faqs": [], "rejected": [], "raw_outputs": raws, "unit_id": unit_id(unit)}
    if not parsed:
        return result
    for qa in parsed:
        if not isinstance(qa, dict) or "question" not in qa or "answer" not in qa:
            result["rejected"].append({"qa": qa, "why": ["형식(question/answer 없음)"]})
            continue
        if has_chinese_sentence(qa["answer"]) or has_chinese_sentence(qa["question"]):
            result["rejected"].append({"qa": qa, "why": ["중국어 문장 섞임"]})
            continue
        check = faq_verify.verify(qa, unit.get("coverage_type"), unit.get("section_name")) \
            or faq_verify.verify_byeopyo(qa, unit.get("section_name"))
        if check is not None and not check[0]:
            result["rejected"].append({"qa": qa, "why": check[1]})
            continue
        answer, used = finalize_answer(qa["answer"], unit, refs)
        result["faqs"].append({
            "species": species, "section": unit["section"], "section_name": unit.get("section_name"),
            "article_num": unit.get("article_num"), "article_title": unit.get("article_title"),
            "coverage_type": unit.get("coverage_type"),
            "question": qa["question"], "answer": answer,
            "references": [r["citation_label"] for r in used],
            "references_given": [r["citation_label"] for r in refs],
            "calc_verified": check is not None,
            "unit_id": unit_id(unit),
            "prompt_version": "v1", "gen_kind": kind, "topics": topics,
            "topic_weight": topic_weights.unit_weight(unit),
        })
    result["status"] = "ok" if result["faqs"] else "all_rejected"
    return result


def round_done(save_path: Path) -> bool:
    """노트북과 같은 완료 표시 — _failures.json은 라운드 끝에만 쓴다"""
    return save_path.exists() and save_path.with_name(save_path.stem + "_failures.json").exists()


def generate_faq_round(builder, units: list[dict], species: str, save_path: Path, temperature: float, kind: str = "normal",
                       topic: str | None = None):
    results, failures = [], []
    start_time = time.time()
    for i, unit in enumerate(units):
        try:
            res = generate_for_unit(builder, unit, species, temperature, kind, topic)
            if res["rejected"] or res["status"] != "ok":
                failures.append({"index": i, **{k: res[k] for k in ("unit_id", "status", "rejected", "raw_outputs")}})
            if res["status"] != "ok":
                print(f"[{i}] {res['status']}, 건너뜀")
                continue
            results.extend(res["faqs"])
        except Exception as e:
            print(f"[{i}] 에러: {e}")
            failures.append({"index": i, "unit_id": unit_id(unit), "status": "error", "error": str(e)})
            continue
        if (i + 1) % SAVE_EVERY == 0:
            json.dump(results, open(save_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"{i+1}/{len(units)} 처리, 누적 {len(results)}개, 경과 {(time.time()-start_time)/60:.1f}분", flush=True)
    json.dump(results, open(save_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(failures, open(save_path.with_name(save_path.stem + "_failures.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    elapsed = time.time() - start_time
    errors = sum(f.get("status") == "error" for f in failures)
    print(f"완료: 총 {len(results)}개, 실패·탈락 기록 {len(failures)}건(에러 {errors}) "
          f"(총 {elapsed/60:.1f}분, 단위당 {elapsed/max(len(units),1):.1f}초)", flush=True)
    # 에러(연결 끊김 등)가 절반을 넘으면 라운드를 실패로 본다 — 완료 표시를 지워 다음 실행에서 다시 만든다
    if units and errors > len(units) / 2:
        save_path.with_name(save_path.stem + "_failures.json").unlink()
        raise RuntimeError(f"{save_path.name}: 에러 {errors}/{len(units)} — Ollama 상태 확인(`docker ps -a`, `docker start ollama`)")
    return results


# ---------- 계획 ----------
def _round_half_up(x: float) -> int:
    return int(x + 0.5)


def base_gens(species: str, unit: dict) -> int:
    """기존 전량의 생성 횟수 — 긴 단위 10회, 짧은 단위는 '긴 단위만' 라운드 전까지"""
    n = len(ROUND_TEMPERATURES[species])
    return n if len(unit["content"]) >= LONG_UNIT_MIN_CHARS else LONG_UNIT_ONLY_FROM_ROUND[species] - 1


def shuffled_units(units: dict[str, list[dict]]) -> dict[str, list[dict]]:
    rng = random.Random(SEED)
    out = {}
    for sp in ("강아지", "고양이"):
        lst = list(units[sp])
        rng.shuffle(lst)
        out[sp] = lst
    return out


def ref_target_ids(builder, units: dict[str, list[dict]]) -> dict[str, set[str]]:
    """종 → 참조 회차 대상 unit_id(다른 조 참조가 있는 조항형 단위). 참조는 05 생성 때와 같게 붙인다"""
    return {sp: {unit_id(u) for u in lst if has_cross_refs(u, builder.resolve_references(u, sp, source_chunks=u["records"]))}
            for sp, lst in units.items()}


def build_plan(units: dict[str, list[dict]], use_weights: bool = True, topic_rounds: dict[str, int] | None = None,
               ref_targets: dict[str, set[str]] | None = None) -> dict:
    """units: 종 → make_units 결과(제외 조항이 이미 빠진 목록). ref_targets: ref_target_ids 결과(None이면 참조 회차 없음).
    반환 plan(JSON으로 저장 가능)"""
    topic_rounds = dict(TOPIC_ROUNDS if topic_rounds is None else topic_rounds) if use_weights else {}
    order = shuffled_units(units)
    plan = {"use_weights": use_weights, "topic_rounds": topic_rounds, "model": MODEL_NAME,
            "prompt_version": "v1", "ref_rounds": REF_ROUNDS if ref_targets is not None else 0, "base_gens": {}, "gens": {}, "topic_gens": {}, "rounds": {}}
    for sp, lst in order.items():
        base = {unit_id(u): base_gens(sp, u) for u in lst}
        w = {unit_id(u): (topic_weights.unit_weight(u) if use_weights else 1.0) for u in lst}
        gens = {uid: max(1, _round_half_up(base[uid] * w[uid])) for uid in base}
        temps = ROUND_TEMPERATURES[sp]
        rounds = [{"round": r, "kind": "normal", "temperature": temps[(r - 1) % len(temps)],
                   "unit_ids": [unit_id(u) for u in lst if gens[unit_id(u)] >= r]}
                  for r in range(1, max(gens.values()) + 1)]
        topic_gens, r = {}, TOPIC_ROUND_START
        for topic, n in topic_rounds.items():
            assert topic in faq_style.TOPICS, topic
            targets = [unit_id(u) for u in lst if w[unit_id(u)] >= topic_weights.TOPIC_ROUND_MIN_WEIGHT
                       and topic in faq_style.eligible_topics(u["content"])]
            for k in range(n):
                rounds.append({"round": r, "kind": "topic", "topic": topic,
                               "temperature": TOPIC_TEMPERATURES[k % len(TOPIC_TEMPERATURES)], "unit_ids": targets})
                r += 1
            for uid in targets:
                topic_gens.setdefault(uid, {})[topic] = n
        ref_ids = [unit_id(u) for u in lst if unit_id(u) in ref_targets[sp]] if ref_targets is not None else []
        for k in range(plan["ref_rounds"]):
            rounds.append({"round": REF_ROUND_START + k, "kind": "ref",
                           "temperature": TOPIC_TEMPERATURES[k % len(TOPIC_TEMPERATURES)], "unit_ids": ref_ids})
        plan["base_gens"][sp], plan["gens"][sp], plan["topic_gens"][sp] = base, gens, topic_gens
        plan["rounds"][sp] = rounds
    return plan


def plan_calls(plan: dict) -> int:
    return sum(len(r["unit_ids"]) for rs in plan["rounds"].values() for r in rs)


def render_plan(plan: dict) -> str:
    L = [f"## 05 생성 계획 — 가중치 {'적용' if plan['use_weights'] else '미적용'}, 주제 회차 {plan['topic_rounds'] or '없음'} "
         f"({plan['model']}, 질문 프롬프트 {plan['prompt_version']})"]
    for sp, rounds in plan["rounds"].items():
        normal = [r for r in rounds if r["kind"] == "normal"]
        topic = [r for r in rounds if r["kind"] == "topic"]
        ref = [r for r in rounds if r["kind"] == "ref"]
        ref_desc = f"{len(ref)}회×{len(ref[0]['unit_ids'])}단위" if ref else "없음"
        n_units = len(plan["gens"][sp])
        calls = sum(len(r["unit_ids"]) for r in rounds)
        base_calls = sum(plan["base_gens"][sp].values())
        per_topic = {}
        for r in topic:
            per_topic.setdefault(r["topic"], [0, len(r["unit_ids"])])[0] += 1
        L.append(f"- {sp}: 단위 {n_units}개 | 일반 라운드 {len(normal)}개 "
                 f"(단위 수 {', '.join(str(len(r['unit_ids'])) for r in normal)}) | "
                 f"주제 회차 {', '.join(f'{t} {n}회×{u}단위' for t, (n, u) in per_topic.items()) or '없음'} | "
                 f"참조 회차 {ref_desc} | "
                 f"호출 {calls}회 (기존 방식 {base_calls}회) | 예상 {calls * SEC_PER_CALL / 3600:.1f}시간")
    total = plan_calls(plan)
    L.append(f"- 합계 호출 {total}회 → 예상 {total * SEC_PER_CALL / 3600:.1f}시간 (단위당 {SEC_PER_CALL}초, 2026-10-13 실측)")
    return "\n".join(L)


def load_units(builder=None) -> tuple[object, dict[str, list[dict]]]:
    builder = builder or rag_context.ContextBuilder()
    return builder, {sp: faq_units.make_units(builder.chunks[sp]) for sp in ("강아지", "고양이")}


def plan_from_data(use_weights: bool = True) -> tuple[dict, dict[str, dict[str, dict]]]:
    """(plan, 종 → unit_id → 단위) — topic_weights.estimate 입력"""
    builder, units = load_units()
    refs = ref_target_ids(builder, units) if use_weights and REF_ROUNDS else None    # --no-weights = 기존 방식(주제·참조 회차 없음)
    return build_plan(units, use_weights, ref_targets=refs), {sp: {unit_id(u): u for u in lst} for sp, lst in units.items()}


# ---------- 실행 ----------
def _assert_model():
    tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()
    assert any(m["name"] == MODEL_NAME for m in tags["models"]), f"{MODEL_NAME} 없음 — `docker start ollama` 확인"


def generate_all(out_dir: Path, use_weights: bool = True, smoke: dict[str, int] | None = None):
    assert out_dir.resolve() != (PROJECT_DIR / "data" / "faq").resolve(), \
        "data/faq에는 기존 전량 라운드 파일이 있다 — round_done이 그것을 완료로 보고 건너뛴다. 새 폴더를 쓸 것"
    assert_same_as_notebook()
    builder, units = load_units()
    plan = build_plan(units, use_weights, ref_targets=ref_target_ids(builder, units) if use_weights and REF_ROUNDS else None)
    if smoke:
        plan = smoke_plan(plan, smoke)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "plan.json"
    if plan_path.exists():
        old = json.load(open(plan_path, encoding="utf-8"))
        assert old == plan, (f"{plan_path}가 지금 계획과 다르다(가중치·단위·회차 변경?) — 다른 계획으로 만든 라운드가 섞인다. "
                             f"새로 만들려면 다른 출력 폴더를 쓸 것")
    else:
        json.dump(plan, open(plan_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(render_plan(plan), flush=True)
    _assert_model()
    by_uid = {sp: {unit_id(u): u for u in lst} for sp, lst in units.items()}
    for sp, rounds in plan["rounds"].items():
        for rd in rounds:
            save_path = out_dir / f"petmint_{sp}_faq_round{rd['round']}.json"
            if round_done(save_path):
                print(f"=== {sp} 생성 라운드 {rd['round']}: 이미 완료 — 건너뜀", flush=True)
                continue
            if save_path.exists():
                print(f"=== {sp} 생성 라운드 {rd['round']}: 중간 저장본만 있음 — 처음부터 다시 생성")
            print(f"\n=== {sp} 생성 라운드 {rd['round']} ({rd['kind']}{' ' + rd['topic'] if rd.get('topic') else ''}, "
                  f"temperature={rd['temperature']}) — "
                  f"{len(rd['unit_ids'])}단위, 예상 {len(rd['unit_ids']) * SEC_PER_CALL / 60:.0f}분 ===", flush=True)
            generate_faq_round(builder, [by_uid[sp][u] for u in rd["unit_ids"]], sp, save_path, rd["temperature"],
                               rd["kind"], rd.get("topic"))
    if truncation_log:
        print("!! 예산에 닿은 호출:", truncation_log)
    requests.post(f"{OLLAMA_URL}/api/generate", json={"model": MODEL_NAME, "keep_alive": 0}, timeout=60)   # 06 심판이 GPU를 쓰도록


def pick_ref_pilot(builder, units: dict[str, list[dict]], species: str = "강아지", n: int = PILOT_REF_UNITS) -> list[dict]:
    """다른 조 참조가 있는 조항형 단위 n개 — 섹션 비율대로(최대 나머지 방식), 섹션 안에서는 SEED로 무작위"""
    by_sec = {}
    for u in units[species]:
        refs = builder.resolve_references(u, species, source_chunks=u["records"])
        if has_cross_refs(u, refs):
            by_sec.setdefault(u["section"], []).append(u)
    total = sum(len(v) for v in by_sec.values())
    assert total >= n, f"{species} 다른 조 참조 단위 {total}개 < {n}"
    quota = {s: n * len(v) // total for s, v in by_sec.items()}
    for s in sorted(by_sec, key=lambda s: -(n * len(by_sec[s]) / total - quota[s]))[:n - sum(quota.values())]:
        quota[s] += 1
    rng = random.Random(SEED)
    picked = []
    for s in sorted(by_sec):
        picked += rng.sample(sorted(by_sec[s], key=unit_id), quota[s])
    return picked


def pilot_ref(out_dir: Path, species: str = "강아지"):
    """참조 회차 파일럿 — 같은 60단위에 일반 회차 1(v1, 대조군)과 참조 회차 1(round201, temperature 0.5).
    out_dir/v1 = 일반 회차만(앞선 v1r 파일럿의 대조군을 그대로 쓴다, 없으면 만든다),
    out_dir/v1ref = v1 라운드 1 복사 + 참조 회차 — 06을 둘이 함께 받아야 참조 QA가 중복·단위 상한에서 살아남는지 보인다.
    v1 심판 캐시(키 = 종|라운드|행|프롬프트 해시)를 v1ref/checked로 복사해 같은 QA는 다시 심판하지 않는다(판정도 같게).
    06은 PETMINT_06_INPUT=<exp_…>/v1ref. 앞선 v1r 결과(out_dir/v1r)는 기록으로 남긴다"""
    assert out_dir.resolve().is_relative_to((PROJECT_DIR / "data" / "faq").resolve()) and out_dir.name.startswith("exp_"), \
        "data/faq/exp_… 아래에 둘 것 — 06이 exp_ 접두로 실험(고른 단위만) 모드를 켠다"
    assert_same_as_notebook()
    builder, units = load_units()
    picked = pick_ref_pilot(builder, units, species)
    out_dir.mkdir(parents=True, exist_ok=True)
    sel = [{"species": species, "unit_id": unit_id(u), "section": u["section"], "content_len": len(u["content"]),
            "cross_refs": [r["citation_label"] for r in rag_context.cross_article_refs(
                u, builder.resolve_references(u, species, source_chunks=u["records"]))[0]]} for u in picked]
    sel_path = out_dir / "selection.json"
    if sel_path.exists():
        assert json.load(open(sel_path, encoding="utf-8")) == sel, f"{sel_path}가 지금 선택과 다르다 — 다른 폴더를 쓸 것"
    else:
        json.dump(sel, open(sel_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{species} 다른 조 참조 단위 {len(picked)}개: {dict(sorted(Counter(u['section'] for u in picked).items()))}")
    _assert_model()
    v1_path = out_dir / "v1" / f"petmint_{species}_faq_round1.json"
    if not round_done(v1_path):
        v1_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n=== v1 일반 회차 ({len(picked)}단위, temperature={PILOT_REF_TEMPERATURE}) ===", flush=True)
        generate_faq_round(builder, picked, species, v1_path, PILOT_REF_TEMPERATURE)
    mix = out_dir / "v1ref"
    (mix / "checked").mkdir(parents=True, exist_ok=True)
    for src in (v1_path, v1_path.with_name(v1_path.stem + "_failures.json"), out_dir / "v1" / "checked" / "judge_cache.json"):
        dst = mix / "checked" / src.name if src.parent.name == "checked" else mix / src.name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
    ref_path = mix / f"petmint_{species}_faq_round{REF_ROUND_START}.json"
    if round_done(ref_path):
        print("=== 참조 회차: 이미 완료 — 건너뜀")
    else:
        print(f"\n=== 참조 회차 ({len(picked)}단위, temperature={PILOT_REF_TEMPERATURE}, "
              f"예상 {len(picked) * SEC_PER_CALL / 60:.0f}분) ===", flush=True)
        generate_faq_round(builder, picked, species, ref_path, PILOT_REF_TEMPERATURE, kind="ref")
    requests.post(f"{OLLAMA_URL}/api/generate", json={"model": MODEL_NAME, "keep_alive": 0}, timeout=60)   # 06 심판이 GPU를 쓰도록


def show_ref(n: int = 3, species: str = "강아지"):
    """pilot-ref 단위 중 섹션마다 하나씩 참조 회차 프롬프트(시스템 + 사용자)를 찍는다 — 모델 호출 없음"""
    builder, units = load_units()
    seen = set()
    for u in pick_ref_pilot(builder, units, species):
        if u["section"] in seen or len(seen) >= n:
            continue
        seen.add(u["section"])
        refs = builder.resolve_references(u, species, source_chunks=u["records"])
        print(f"\n{'=' * 30} {unit_id(u)} {'=' * 30}\n{build_single_prompt(u, refs, ref_prompt=True)}")
    print(f"\n{'=' * 30} 시스템 프롬프트(참조 회차) {'=' * 30}\n{SYSTEM_PROMPT_REF}")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    opts = dict(a[2:].split("=", 1) for a in args if a.startswith("--") and "=" in a)
    flags = {a for a in args if a.startswith("--") and "=" not in a}
    cmd = next((a for a in args if not a.startswith("--")), "plan")
    use_weights = "--no-weights" not in flags
    if cmd == "plan":
        assert_same_as_notebook()
        plan, _ = plan_from_data(use_weights)
        print(render_plan(plan))
    elif cmd == "run":
        assert "out" in opts, "--out=<출력 폴더> 필요 (기존 data/faq 라운드 파일과 섞이지 않게)"
        if "model" in opts:
            set_model(opts["model"])
        smoke = dict(zip(("강아지", "고양이"), map(int, opts["smoke"].split(",")))) if "smoke" in opts else None
        generate_all(Path(opts["out"]), use_weights, smoke)
    elif cmd == "pilot-ref":
        pilot_ref(Path(opts.get("out", PROJECT_DIR / "data" / "faq" / "exp_r")))
    elif cmd == "show-ref":
        show_ref()
    else:
        raise SystemExit(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    main()
