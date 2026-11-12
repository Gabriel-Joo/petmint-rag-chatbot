"""
refusal.py
답이 거절인가 — 평가(scripts/eval_serving · verify_modes)와 운영 로그(turns.refused, db/rule_report)가 같은 판정을 쓰게 한 곳에 둔다.

- 문구 기준 자동 판정이다. 학습 목표 NO_ANSWER_TEXT(prompts.py)와 사내규정 시스템 프롬프트("인사부서에 확인")에서 온 것 + 흔한 변형
- 비교 전에 공백·쉼표를 지운다(띄어쓰기가 흔들려도 같게 본다)
- data/*.py라 이미지에 들어간다 — 앱(turn_log)과 db/rule_report가 import한다. scripts/는 이미지에 없다

판정 판(2026-11-12 바꿈 — docs/02_pipeline/15_monitoring.md 「거절 판정」):
- refused(현재, C안): 확실히 잘못 찍히던 둘을 뺀다
  ① 코드가 모델 답 뒤에 덧붙인 「참고:」 줄은 보지 않는다 — 나이 참고 줄 "(구체 나이는 약관에 없음)"이 붙은 모델 답이 모두 거절로 찍혔다
  ② "인사부서에 확인/문의" 맺음말은 다른 답이 있으면 거절이 아니다 — 사내규정 프롬프트 탓에 다 답한 뒤에도 붙는다("저는 언제 정년이에요?").
     맺음말뿐인 답("인사부서에 문의해 주세요.")은 그대로 거절
  코드 답(code_rule)은 판정하지 않는다 — 부르는 쪽(answer._turn_log)이 0으로 적는다
  문구가 답 어디에 있든 보는 것은 그대로다(위치로 가르면 서두를 깐 진짜 거절을 놓친다 — 베이스 모델 N축 18 → 1)
- refused_v1: 2026-11-12 이전 판정. 그 전 평가 · 운영 수치를 다시 낼 때만 쓴다(scripts/eval_serving --refusal v1)
"""

import re

from data import prompts

REFUSAL_PHRASES = ("확인되지 않", "확인되지않", "명시되어 있지 않", "명시되어있지않", "나와 있지 않", "규정에 없", "약관에 없",
                   "찾을 수 없", "포함되어 있지 않", "언급되어 있지 않", "인사부서에 확인", "인사부서에 문의")
SIGN_OFF = ("인사부서에 확인", "인사부서에 문의")             # 맺음말 — 이것만으로는 거절이 아니다(C안 ②)
CORE_PHRASES = tuple(p for p in REFUSAL_PHRASES if p not in SIGN_OFF)
CODE_NOTE = re.compile(r"\n+\s*참고\s*:")                    # 코드가 모델 답 뒤에 붙이는 참고 줄(나이 · 대기기간 등) — 그 앞이 모델 답(C안 ①)
CHANGED_ON = "2026-11-12"


def norm(t: str | None) -> str:
    return re.sub(r"[\s,]", "", t or "")


def _no_answer_head() -> str:
    return norm(prompts.NO_ANSWER_TEXT)[:12]


SIGN_OFF_REST = 20                                           # 맺음말 문장을 빼고 남은 글자가 이보다 적으면 맺음말뿐인 답


def refused(answer: str | None) -> bool:
    """모델 답이 거절인가(C안) — 코드 참고 줄 앞까지만 보고, 인사부서 맺음말은 다른 답이 없을 때만 거절로 센다"""
    model = CODE_NOTE.split(answer or "")[0]
    a = norm(model)
    if any(norm(p) in a for p in CORE_PHRASES) or _no_answer_head() in a:
        return True
    if not any(norm(p) in a for p in SIGN_OFF):
        return False
    rest = [s for s in re.split(r"(?<=[.!?。])\s+|\n+", model) if not any(norm(p) in norm(s) for p in SIGN_OFF)]
    return len(norm("".join(rest))) < SIGN_OFF_REST


def refused_v1(answer: str | None) -> bool:
    """2026-11-12 이전 판정 — 과거 수치 재현용. 새 측정에는 쓰지 않는다"""
    a = norm(answer)
    return any(norm(p) in a for p in REFUSAL_PHRASES) or _no_answer_head() in a
