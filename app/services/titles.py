"""
titles.py
지난 채팅 제목(10번 2-1절) — 첫 질문을 짧게 요약한다. 세션당 한 번(sessions.set_title_once가 보장).

모델(베이스)이 실패하거나 늦으면 첫 질문 첫 줄을 잘라 쓴다 — 제목이 없으면 목록에 안 나오므로 비워 두지 않는다.
config.TITLE_USE_LLM이 꺼져 있으면 모델을 부르지 않는다(GPU를 쓰면 안 될 때).
업무특화는 늘 첫 질문 첫 줄이다 — 답변은 파인튜닝 모델이고 GPU에는 베이스와 둘 중 하나만 올라가서(각 8.7GB + search-service),
제목을 베이스로 지으면 상담마다 첫 답변이 모델 교체로 약 5초 늦어졌다(2026-10-21: 첫 토큰 0.9 → 5.5초).
"""

import asyncio
import logging
import re

from app import config
from app.schemas import Mode
from app.services.llm import OllamaClient

log = logging.getLogger(__name__)

_PROMPT = ("다음은 보험 상담원이 사내 도우미에게 한 질문이다. 대화 목록에 띄울 제목을 {n}자 이내 한국어 명사구로 만들어라.\n"
           "제목만 한 줄로 쓰고 따옴표·마침표·설명은 붙이지 마라.\n\n질문: {q}")


def fallback_title(question: str) -> str:
    """첫 줄의 공백을 접어 TITLE_MAX_CHARS로 자른다"""
    line = re.sub(r"\s+", " ", question.strip().split("\n")[0])
    n = config.TITLE_MAX_CHARS
    return line if len(line) <= n else line[: n - 1].rstrip() + "…"


def _clean(raw: str) -> str:
    line = next((l for l in raw.strip().splitlines() if l.strip()), "")
    line = re.sub(r"^제목\s*[:：]\s*", "", line.strip())
    return line.strip(" \"'“”‘’「」.").strip()


def uses_llm(mode: Mode) -> bool:
    """이 모드의 제목을 모델로 짓는가 — 일반·사내규정만(베이스 모델이 답변 모델과 같다)"""
    return config.TITLE_USE_LLM and mode != "업무특화"


async def make_title(question: str, llm: OllamaClient | None, mode: Mode) -> str:
    if not uses_llm(mode) or llm is None:
        return fallback_title(question)
    try:
        raw = await asyncio.wait_for(
            llm.complete(config.BASE_MODEL,
                         [{"role": "user", "content": _PROMPT.format(n=config.TITLE_MAX_CHARS // 2, q=question)}],
                         options={"temperature": 0, "num_predict": 48}),
            timeout=config.TITLE_TIMEOUT_SEC)
    except Exception:                                   # 모델 장애·지연은 제목을 막을 이유가 아니다
        log.warning("제목 요약 실패 — 첫 줄로 대신한다", exc_info=True)
        return fallback_title(question)
    title = _clean(raw)
    return fallback_title(title) if title else fallback_title(question)
