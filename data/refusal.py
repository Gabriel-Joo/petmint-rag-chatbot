"""
refusal.py
답이 거절인가 — 평가(scripts/eval_serving · verify_modes)와 운영 로그(turns.refused, db/rule_report)가 같은 판정을 쓰게 한 곳에 둔다.

- 문구 기준 자동 판정이다. 학습 목표 NO_ANSWER_TEXT(prompts.py)와 사내규정 시스템 프롬프트("인사부서에 확인")에서 온 것 + 흔한 변형
- 비교 전에 공백·쉼표를 지운다(띄어쓰기가 흔들려도 같게 본다)
- data/*.py라 이미지에 들어간다 — 앱(turn_log)과 db/rule_report가 import한다. scripts/는 이미지에 없다
"""

import re

from data import prompts

REFUSAL_PHRASES = ("확인되지 않", "확인되지않", "명시되어 있지 않", "명시되어있지않", "나와 있지 않", "규정에 없", "약관에 없",
                   "찾을 수 없", "포함되어 있지 않", "언급되어 있지 않", "인사부서에 확인", "인사부서에 문의")


def norm(t: str | None) -> str:
    return re.sub(r"[\s,]", "", t or "")


def refused(answer: str | None) -> bool:
    a = norm(answer)
    return any(norm(p) in a for p in REFUSAL_PHRASES) or norm(prompts.NO_ANSWER_TEXT)[:12] in a
