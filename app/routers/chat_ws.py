"""
chat_ws.py
/ws/chat/{session_id} (7-2). 서버 메시지는 전부 turn_id를 가진다(스키마가 강제).

- 없는·종료된·남의 세션 → accept 후 4404로 닫는다. 사용자 정의 종료 코드는 accept 전에는 보낼 수 없다.
  세션은 메시지마다 다시 본다 — 다른 탭에서 상담을 끝내거나 목록에서 제거했을 수 있다.
- question의 pet_id는 세션 고객의 반려동물인지 검증한다(6-2). 업무특화가 아니면 pet_id를 받지 않는다.
- 턴 로그(turns·turn_scope·retrieved)는 done을 보내기 전에 쓴다 — done 뒤 목록 새로고침·피드백이 그 턴을 찾을 수 있게.
- 첫 질문이면(세 모드 모두, 12번 1-1절) 제목 요약을 답변과 나란히 돌리고, done 전에 sessions.title에 한 번 넣는다.
  업무특화 제목은 고객 조회의 과거 상담 목록이 쓴다(09번 2-2절).
- 지금은 answer.run_turn 대신 더미 순서(sources → token → references → done)를 보낸다. 로그는 더미 그대로 남는다.
"""

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app import config
from app.db import now, utc
from app.deps import agent_of
from app.schemas import (CancelMsg, ClarifyAnswerMsg, DoneMsg, ErrorMsg, QuestionMsg, ReferencesMsg, SourcesMsg,
                         TokenMsg, TurnLog, client_message_adapter)
from app.services import titles
from app.services.customers import USER_MESSAGE, CustomerDataError, CustomerStore
from app.services.sessions import SessionStore
from app.services.turn_log import TurnLogStore, pet_snapshot, retrieved_rows, scope_rows

router = APIRouter()
log = logging.getLogger(__name__)


async def _send(ws: WebSocket, msg) -> None:
    await ws.send_text(msg.model_dump_json())


@router.websocket("/ws/chat/{session_id}")
async def chat(ws: WebSocket, session_id: str):
    store: SessionStore = ws.app.state.sessions
    turn_log: TurnLogStore = ws.app.state.turn_log
    customers: CustomerStore = ws.app.state.customers
    agent = agent_of(ws)

    await ws.accept()
    if await asyncio.to_thread(store.get_open, session_id, agent) is None:
        await ws.close(code=config.WS_CLOSE_SESSION_NOT_FOUND)
        return

    try:
        while True:
            raw = await ws.receive_text()
            session = await asyncio.to_thread(store.get_open, session_id, agent)
            if session is None:                    # 연결 중에 종료·제거됐다
                await ws.close(code=config.WS_CLOSE_SESSION_NOT_FOUND)
                return

            try:
                msg = client_message_adapter.validate_json(raw)
            except ValidationError as e:
                await _send(ws, ErrorMsg(turn_id="", code="bad_message", message=str(e)))
                continue

            if isinstance(msg, QuestionMsg):
                turn_id = str(uuid.uuid4())
                pet = None
                if session.mode == "업무특화":
                    try:                                    # 원장을 턴마다 읽는다 — 이 값이 그 턴의 스냅샷
                        pet = (await asyncio.to_thread(customers.pet_of, session.customer_id, msg.pet_id)
                               if msg.pet_id else None)
                    except CustomerDataError as e:          # 원장이 깨졌다 — 연결은 두고 이 턴만 거절, 자세한 건 로그에
                        log.error("고객 원장 오류 (WS session=%s)\n%s", session_id, e)
                        await _send(ws, ErrorMsg(turn_id=turn_id, code="customer_data", message=USER_MESSAGE))
                        continue
                    if pet is None:
                        await _send(ws, ErrorMsg(turn_id=turn_id, code="bad_pet",
                                                 message=f"세션 고객의 반려동물이 아님: {msg.pet_id}"))
                        continue
                elif msg.pet_id is not None:
                    await _send(ws, ErrorMsg(turn_id=turn_id, code="bad_pet",
                                             message=f"{session.mode} 모드는 pet_id를 받지 않는다"))
                    continue

                title_task = None
                if session.title is None:
                    title_task = asyncio.create_task(titles.make_title(msg.text, ws.app.state.llm))

                # 구현 때: scope_for(pet) → answer.run_turn(TurnContext(...))의 메시지를 그대로 흘려보내고,
                # 끝나면 run_turn이 돌려준 TurnLog를 아래처럼 쓴다. 생성 중 새 질문이 오면 앞 턴의 cancel을 set한다
                started = time.monotonic()
                sources, references, answer = [], [], "(더미 답변)"
                await _send(ws, SourcesMsg(turn_id=turn_id, items=sources))
                await _send(ws, TokenMsg(turn_id=turn_id, text=answer))
                await _send(ws, ReferencesMsg(turn_id=turn_id, items=references))
                latency_ms = int((time.monotonic() - started) * 1000)

                turn = TurnLog(turn_id=turn_id, session_id=session_id, question=msg.text, answer=answer,
                               **pet_snapshot(pet), scope=scope_rows(pet),
                               retrieved=retrieved_rows(sources, references),
                               model=config.FINETUNED_MODEL if session.mode == "업무특화" else config.BASE_MODEL,
                               prompt_version=config.PROMPT_VERSION, index_version=config.INDEX_VERSION,
                               latency_ms=latency_ms, created_at=utc(now()))
                try:
                    await asyncio.to_thread(turn_log.record, turn)
                except Exception:                  # 로그 실패로 상담을 끊지 않는다 — 대신 크게 남긴다
                    log.exception("턴 로그 기록 실패: session=%s turn=%s", session_id, turn_id)
                if title_task is not None:
                    await asyncio.to_thread(store.set_title_once, session_id, await title_task)
                await _send(ws, DoneMsg(turn_id=turn_id, latency_ms=latency_ms))

            elif isinstance(msg, CancelMsg):
                pass                                # 구현 때: 진행 중 턴의 cancel 이벤트를 set

            elif isinstance(msg, ClarifyAnswerMsg):
                # 구현 때: answer.resume_clarified로 같은 turn_id의 생성을 잇는다
                await _send(ws, DoneMsg(turn_id=msg.turn_id, latency_ms=0))
    except WebSocketDisconnect:
        pass                                        # 구현 때: 진행 중 턴 취소
