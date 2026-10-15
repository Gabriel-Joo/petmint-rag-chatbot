"""
answer.py
한 턴의 파이프라인(09 8절): scope → (재작성) → 검색 → 되묻기 판정 → 계산 카드 → 생성 → used_references.
결과는 WS 서버 메시지(sources → token… → references → done, 또는 clarify)로 흘려보낸다.

고정된 결정(구현 때 바꾸지 말 것):
- 고객 정보·대화 이력은 프롬프트에 넣지 않는다(5절). prompts.build_messages(customer=, history=)는 NotImplementedError —
  등급은 SearchScope가, 자기부담금·부담보는 계산 카드·배너(코드)가, 멀티턴은 재작성 + 앞 턴 발췌 이월이 맡는다.
- 재작성기는 베이스 모델(5절). 재작성된 질문은 화면에 보여준다.
- 되묻기: 상위 결과의 section_name이 서로 다른 (유형, 등급) 조합일 때만. 가정 질문은 안 한다(4절).
- 금액 계산은 limit_table이 하고 모델은 손대지 않는다.

이번 범위는 인터페이스만.
"""

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator

from data.search_scope import SearchScope

from app.schemas import Pet, ServerMessage, Session, SessionTurn


@dataclass
class TurnContext:
    turn_id: str
    session: Session
    pet: Pet | None                       # 업무특화만
    scope: SearchScope | None             # 일반 모드는 None(검색 없음)
    question: str
    agent: str
    cancel: asyncio.Event = field(default_factory=asyncio.Event)


async def rewrite_question(history: list[SessionTurn], question: str) -> str:
    """후속 질문 → 독립 질문(베이스 모델). 이력이 없으면 그대로"""
    raise NotImplementedError("5절 질문 재작성")


def run_turn(ctx: TurnContext) -> AsyncIterator[ServerMessage]:
    """한 턴을 실행하며 서버 메시지를 순서대로 낸다. 끝나면 TurnLog(turn_log.pet_snapshot·scope_rows·retrieved_rows로
    조립)를 만들어 chat_ws가 done 전에 TurnLogStore.record로 쓰게 한다"""
    raise NotImplementedError("09 8절 answer 파이프라인")


def resume_clarified(ctx: TurnContext, choice: str) -> AsyncIterator[ServerMessage]:
    """clarify_answer를 받은 뒤 고른 쪽으로 생성을 잇는다"""
    raise NotImplementedError("4절 되묻기 응답")
