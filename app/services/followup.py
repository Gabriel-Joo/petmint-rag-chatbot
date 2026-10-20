"""
followup.py
후속 질문 판별(09번 5절) — 규칙만, LLM 없음. 빠르고 예측 가능해야 해서 판별에는 모델을 쓰지 않는다.

앞 대화를 봐야 뜻이 통하는 질문만 후속으로 본다. 넷 중 하나면 후속:
1. 지시어·접속어로 시작 — 그럼·그건·그거·그 다음·아까·그런데…
2. 생략 꼬리 — "…면요?", "…은요?", "…도요?"(주제를 앞 대화에서 가져온다)
3. 금액만 말한 짧은 문장 — "35만원이요", "치료비는 35만원 나왔어요"(물음표 없음, 공백 뺀 16자 이하)
4. 아주 짧음 — 공백 뺀 8자 이하("언제 들어와요?")

2026-10-21 측정: 혼자서 이해되는 질문 148개(평가 117 + 검증 31) 중 후속으로 잘못 잡힘 0, 후속 14개 중 12개.
놓치는 것(지시어·꼬리 없이 주어만 빠진 "신청은 언제까지 해야 돼요?")은 단독 질문으로 처리한다 — 화면의 ↳ 줄이 없어
상담원이 알아챌 수 있다. 판별이 놓치는 게 거슬리면 그때 LLM 판별을 얹는다(data/review/multiturn_design_20261021.md).
"""

import re

_LEAD = re.compile(r"^\s*(그럼|그러면|그건|그거|그게|그것|그\s*다음|거기|이건|이거|이것|저건|아까|그리고|근데|그래서|그래도|그런데)")
_TAIL = re.compile(r"(?:면|은|는|도|이면|라면)요\s*[?？]?\s*$")
_AMOUNT = re.compile(r"\d[\d,]*\s*(?:만\s*)?원")
AMOUNT_ONLY_MAX = 16      # "금액만 말함"으로 볼 최대 글자 수(공백 뺌)
SHORT_MAX = 8             # 이 글자 수 이하면 후속(공백 뺌). 평가 질문의 최소는 10자


def follow_up_reason(question: str) -> str | None:
    """후속 질문이면 그 이유(로그·화면용 짧은 이름), 아니면 None"""
    flat = re.sub(r"\s", "", question)
    if _LEAD.search(question):
        return "지시어"
    if _TAIL.search(question):
        return "생략 꼬리"
    if "?" not in question and "？" not in question and _AMOUNT.search(question) and len(flat) <= AMOUNT_ONLY_MAX:
        return "금액만"
    if len(flat) <= SHORT_MAX:
        return "짧음"
    return None
