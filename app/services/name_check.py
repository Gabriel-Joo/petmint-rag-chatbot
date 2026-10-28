"""
name_check.py
병명 되묻기 ⑤ "질문에 병명·증상·부위·치료 이름이 있는가"를 베이스 모델로 본다(2026-10-28 docs/16 B안, PETMINT_ASK_DISEASE_LLM).
정규식 ⑤(사건 낱말을 지우고 한글이 남는가)는 처음 보는 말투에 약했다 — gemma가 만든 무병명 질문 43개 중 7개만 되물었다(모델 39개).
모델이 뽑은 말이 사건 낱말·반려동물 이름·부탁하는 말뿐이면 코드가 '이름 없음'으로 본다. 실패·시간 초과면 None(호출하는 쪽이 정규식으로 돌아간다).
프롬프트는 측정한 그대로다 — 바꾸면 다시 잰다(더 넓게 '구체적인 내용'을 물으면 병명 있는 질문도 '없음'이라 했다).
"""

import json
import re

import httpx

from app import config
from app.services.lexicon import EVENT_WORDS, NO_NAME_FILLER, POLITE_ENDINGS, POLITE_FILLER

PROMPT = ("반려동물 보험 상담 질문에서 병명·증상·다친 부위·치료나 검사의 이름을 찾는다. 입원·통원·수술·병원·다쳤다·아프다·치료받았다 같은 말 자체는 이름이 아니다.\n"
          "질문: {q}\n이름이 있으면 그 말을, 없으면 \"없음\"을 JSON으로만 답하라: {{\"이름\": \"...\"}}")
TIMEOUT_SEC = 3.0


def has_name(question: str, pet_name: str) -> bool | None:
    """True: 이름이 있다(되묻지 않는다) / False: 없다 / None: 모델에 닿지 않았다"""
    try:
        r = httpx.post(f"{config.OLLAMA_URL}/api/chat", timeout=TIMEOUT_SEC,
                       json={"model": config.BASE_MODEL, "stream": False, "format": "json",
                             "options": {"temperature": 0, "num_predict": 32},
                             "messages": [{"role": "user", "content": PROMPT.format(q=question)}]})
        r.raise_for_status()
        m = re.search(r"\{[^{}]*\}", r.json()["message"]["content"])
        name = str(json.loads(m.group(0)).get("이름", "")).strip() if m else ""
    except (httpx.HTTPError, ValueError, KeyError, AttributeError):
        return None
    if name in ("", "없음"):
        return False
    rest = POLITE_FILLER.sub(" ", NO_NAME_FILLER.sub(" ", name.replace(pet_name, " ")))
    return bool([w for w in re.findall(r"[가-힣]+", rest) if w not in POLITE_ENDINGS and w not in EVENT_WORDS])
