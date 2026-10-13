"""
faq_judge.py
06번(FAQ 품질 검증)의 LLM 심판 — 코드로 못 잡는 독해 오류·규정 지어내기·질문 품질을 판정한다. 판정이 "문제"면 버린다.

모델: gemma4:12b (Ollama, Apache 2.0). 생성 모델(Tri-7B)과 다른 모델이어야 같은 곳에서 틀리지 않는다. 외부 API는 쓰지 않는다.
2026-10-12~13 측정(검수 정답지, 참조를 함께 준 조건):
- 후보(개발용 1·2차 88건): Gemma 4 12B 재현 77% / OK 오탐 15% — Qwen3-14B(thinking 끔 42%/12%, 켬 50%/6%),
  Kanana 1.5 8B(53%/29%, 용어·주체 오류 0/3), A.X 4.0 Light(28%/23%)보다 낫다. EXAONE은 비상업 라이선스라 제외.
- 프롬프트: 질문 품질·핵심 조건 누락 기준을 늘린 변형 3개는 재현을 올린 만큼 정상 QA를 더 버려 남는 데이터 오류율이 같았다(15%) → 원형 유지.
- 안정성: temperature 0 두 번 183/183 일치, temperature 0.3에서도 96.7% 같은 판정.
- 최종 시험(3차 99건, 한 번만): 재현 88%(폐기 판정 9/9), OK 오탐 20%, 버림 37%, 남는 데이터 오류율 25% → 5%.
- 참조 없이 판정하면 원문 밖 내용을 '지어냈다'고 보는 오탐이 늘었다(15% → 33%) — 반드시 생성 때와 같은 참조를 준다.
"""
import json
import re
import requests

OLLAMA_URL = "http://localhost:11434"
JUDGE_MODEL = "gemma4:12b"
NUM_CTX = 8192
NUM_PREDICT = 600
PROMPT_BUDGET = NUM_CTX - NUM_PREDICT     # 넘으면 Ollama가 경고 없이 앞부분을 자른다(3차 시험 최대 입력 3404토큰)

JUDGE_SYSTEM = """당신은 반려동물 보험 약관 FAQ 검수자입니다. 주어진 [약관 원문]과 [관련 조항]만 근거로, FAQ 질문·답변에 고객 상담에 쓰면 안 되는 문제가 있는지 판정하세요.
문제 유형:
- reversal: 원문의 조건·결론을 뒤집음(지급↔미지급, 포함↔제외, 가능↔불가)
- clause_mix: 단서·예외·다른 항의 규정을 잘못 섞어 적용함
- fabricated: 원문·관련 조항에 없는 규정·절차·숫자·상황을 지어내 답에 씀
- incomplete: 답의 결론을 바꾸는 핵심 조건을 빠뜨렸거나 "명시되지 않음"으로 회피함
- wrong_term: 용어·주체를 잘못 씀(보험수익자/피보험자/계약자, 임직원/보험설계사 등)
- wrong_value: 금액·기간·비율·계산이 원문과 다름
- question_quality: 실제 보험 상담에서 나오기 어려운 질문(법률 일반상식, 원문 문장을 되묻는 질문, 앞 질문을 전제한 질문, 부자연스러운 가정)
표현 차이나 사소한 생략은 문제가 아닙니다. 원문과 비교해 확인한 뒤 판정하세요.
반드시 JSON 한 개로만 답하세요: {"problem": true 또는 false, "types": ["유형", ...], "reason": "한 문장"}"""


def build_judge_prompt(faq: dict, source: str, refs: list[dict], answer_body: str) -> str:
    """source: 생성 단위 원문(rag_context.display_text), refs: 생성 때 준 참조(get_references_for_unit + merged_refs)"""
    ref_text = "".join(f"\n[{r['citation_label']}]\n{r['content']}\n" for r in refs if r.get("content")) or "(없음)"
    head = f"{faq.get('section_name') or faq.get('section')} {faq.get('article_title') or ''}".strip()
    return (f"[약관 원문] {head}\n{source}\n\n[관련 조항]{ref_text}\n\n"
            f"[FAQ 질문]\n{faq['question']}\n\n[FAQ 답변]\n{answer_body}")


def judge(prompt: str, model: str = JUDGE_MODEL) -> dict:
    """반환 {"problem": bool|None, "types": [...], "reason": str|None, "prompt_tokens": int, "truncated": bool}.
    problem None = 파싱 실패(측정에서는 0건) — 호출 쪽에서 재시도하거나 사람 검수로 보낸다."""
    body = {"model": model, "system": JUDGE_SYSTEM, "prompt": prompt, "stream": False, "format": "json", "think": False,
            "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT}}
    r = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=900)
    r.raise_for_status()
    out = r.json()
    used = out.get("prompt_eval_count") or 0
    try:
        j = json.loads(re.search(r"\{.*\}", out.get("response", ""), re.S).group(0))
        return {"problem": bool(j.get("problem")), "types": j.get("types") or [], "reason": j.get("reason"),
                "prompt_tokens": used, "truncated": used >= PROMPT_BUDGET}
    except Exception:
        return {"problem": None, "types": [], "reason": None, "raw": out.get("response", "")[:500],
                "prompt_tokens": used, "truncated": used >= PROMPT_BUDGET}
