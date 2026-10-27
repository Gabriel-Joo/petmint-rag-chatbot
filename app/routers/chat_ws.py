"""
chat_ws.py
/ws/chat/{session_id} (7-2). 서버 메시지는 전부 turn_id를 가진다(스키마가 강제).

- 없는·종료된·남의 세션 → accept 후 4404로 닫는다. 사용자 정의 종료 코드는 accept 전에는 보낼 수 없다.
  세션은 메시지마다 다시 본다 — 다른 탭에서 상담을 끝내거나 목록에서 제거했을 수 있다.
- question의 pet_id는 세션 고객의 반려동물인지 검증한다(6-2). 업무특화가 아니면 pet_id를 받지 않는다.
- 턴 로그(turns·turn_scope·retrieved)는 done을 보내기 전에 쓴다 — done 뒤 목록 새로고침·피드백이 그 턴을 찾을 수 있게.
- 첫 질문이면(세 모드 모두, 12번 1-1절) 제목 요약을 답변과 나란히 돌리고, done 전에 sessions.title에 한 번 넣는다.
  업무특화 제목은 고객 조회의 과거 상담 목록이 쓴다(09번 2-2절).
- 한 턴은 answer.run_turn이 낸 메시지를 그대로 보낸다(sources → calc → token… → references, 되묻기면 clarify에서 멈춤,
  실패면 error). 턴 로그를 쓰고 제목을 넣은 뒤 done — error로 끝난 턴은 done을 보내지 않는다.
- 되묻기에서 멈춘 턴은 연결마다 들고 있다가 clarify_answer로 잇는다. 응답 전에 새 질문이 오거나 연결이 끊기면 cancelled로 남긴다.
- 턴은 수신 루프 안에서 차례로 돈다 — 생성 중에는 cancel을 받지 못한다(아직 cancel 미구현).
"""

import asyncio
import logging
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app import config
from app.deps import header_agent, origin_ok, session_me
from app.schemas import CancelMsg, ClarifyAnswerMsg, DoneMsg, ErrorMsg, QuestionMsg, ServerMessage, client_message_adapter
from app.services import answer, context, dayparse, hr_personal, payout, titles
from app.services.answer import TurnContext, TurnDeps
from app.services.customers import USER_MESSAGE, CustomerDataError, CustomerStore
from app.services.followup import follow_up_reason
from app.services.sessions import SessionStore
from app.services.turn_log import TurnLogStore

router = APIRouter()
log = logging.getLogger(__name__)


async def _send(ws: WebSocket, msg) -> None:
    await ws.send_text(msg.model_dump_json())


async def _record(turn_log: TurnLogStore, ctx: TurnContext) -> None:
    try:
        await asyncio.to_thread(turn_log.record, ctx.log)
    except Exception:                      # 로그 실패로 상담을 끊지 않는다 — 대신 크게 남긴다
        log.exception("턴 로그 기록 실패: session=%s turn=%s", ctx.session.session_id, ctx.turn_id)


async def _drive(ws: WebSocket, turn_log: TurnLogStore, ctx: TurnContext, messages: AsyncIterator[ServerMessage]) -> None:
    """턴의 메시지를 보내고, 끝났으면(되묻기 대기가 아니면) 턴 로그를 쓴다. 보내다 연결이 끊기면 cancelled로 남긴다"""
    try:
        async for m in messages:
            await _send(ws, m)
    finally:
        if ctx.clarify is None:
            answer.abandon(ctx)            # 이미 끝났으면(ctx.log 있음) 그대로 둔다
            await _record(turn_log, ctx)


@router.websocket("/ws/chat/{session_id}")
async def chat(ws: WebSocket, session_id: str):
    store: SessionStore = ws.app.state.sessions
    turn_log: TurnLogStore = ws.app.state.turn_log
    customers: CustomerStore = ws.app.state.customers
    deps = TurnDeps(retriever=ws.app.state.retriever, builder=ws.app.state.builder, llm=ws.app.state.llm,
                    employees=getattr(ws.app.state, "employees", None))
    me = None
    if config.AUTH == "app":                       # 쿠키 로그인(13번 2-1절) — 거절은 accept 뒤 코드로 닫는다(4404와 같은 방식)
        me = None if not origin_ok(ws) else await asyncio.to_thread(session_me, ws)
    agent = header_agent(ws) if config.AUTH != "app" else (me.email if me and not me.must_change_password else None)
    pending: dict[str, TurnContext] = {}           # 되묻기 응답을 기다리는 턴

    async def drop_pending() -> None:
        for ctx in pending.values():
            answer.abandon(ctx)
            await _record(turn_log, ctx)
        pending.clear()

    async def finish(ctx: TurnContext, title_task: asyncio.Task | None) -> None:
        """제목을 넣고(첫 질문) done — 되묻기 대기면 done 없이 기다린다, 실패한 턴은 error로 이미 끝났다"""
        if title_task is not None:
            await asyncio.to_thread(store.set_title_once, session_id, await title_task)
        if ctx.clarify is not None:
            pending[ctx.turn_id] = ctx
        elif ctx.log is not None and ctx.log.status != "error":
            await _send(ws, DoneMsg(turn_id=ctx.turn_id, latency_ms=ctx.log.latency_ms,
                                    first_token_ms=ctx.log.first_token_ms))

    await ws.accept()
    if config.AUTH == "app" and agent is None:
        await ws.close(code=config.WS_CLOSE_FORBIDDEN_ORIGIN if not origin_ok(ws) else config.WS_CLOSE_UNAUTHORIZED)
        return
    if await asyncio.to_thread(store.get_open, session_id, agent) is None:
        await ws.close(code=config.WS_CLOSE_SESSION_NOT_FOUND)
        return

    try:
        while True:
            raw = await ws.receive_text()
            if config.AUTH == "app" and await asyncio.to_thread(session_me, ws) is None:   # 연결 중 로그아웃·만료·퇴직
                await ws.close(code=config.WS_CLOSE_UNAUTHORIZED)
                return
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

                await drop_pending()                        # 되묻기에 답하지 않고 새로 물었다

                title_task = None
                if session.title is None:
                    title_task = asyncio.create_task(titles.make_title(msg.text, ws.app.state.llm, session.mode))

                # 멀티턴 — 후속 질문이면 앞 턴(정상 완료만)으로 푼다. 판별은 규칙이라 후속이 아니면 DB도 모델도 안 부른다
                resolved = None
                # 업무특화에서 금액·일수·'모르겠어요'를 말하면 앞 턴이 코드의 되묻기였는지 봐야 한다(context.resolve) —
                # 후속 규칙에 안 걸려도("30만, 30만, 10만"처럼 원 없이 쓴 날짜별 금액도)
                # 사내규정 개인화(PETMINT_HR_PERSONAL): 본인 지칭 없이 연차·퇴직금 등을 물으면 바로 앞 질문이 개인화였는지 본다
                # ("연차 미사용분은 얼마 받나요?" — 후속 규칙에 안 걸리는 온전한 문장). 후속이 아니면 resolve는 질문 그대로다
                hr_chain = session.mode == "사내규정" and config.HR_PERSONAL and hr_personal.may_inherit(msg.text, payout.today())
                if follow_up_reason(msg.text) or (session.mode == "업무특화" and dayparse.is_reply(msg.text)) or hr_chain:
                    prior = await asyncio.to_thread(turn_log.recent_turns, session_id,
                                                    max(context.HISTORY_TURNS, hr_personal.PRIOR_TURNS if hr_chain else 0))
                    resolved = await context.resolve(session.mode, msg.text, prior, pet, ws.app.state.llm)
                ctx = TurnContext(turn_id=turn_id, session=session, pet=pet, scope=answer.scope_of(session.mode, pet),
                                  question=msg.text, agent=agent, resolved=resolved)
                await _drive(ws, turn_log, ctx, answer.run_turn(ctx, deps))
                await finish(ctx, title_task)

            elif isinstance(msg, CancelMsg):
                pass                                # 구현 때: 진행 중 턴의 cancel 이벤트를 set(턴을 수신 루프 밖 태스크로)

            elif isinstance(msg, ClarifyAnswerMsg):
                ctx = pending.pop(msg.turn_id, None)
                if ctx is None:
                    await _send(ws, ErrorMsg(turn_id=msg.turn_id, code="bad_turn",
                                             message=f"되묻기를 기다리는 턴이 아님: {msg.turn_id}"))
                    continue
                await _drive(ws, turn_log, ctx, answer.resume_clarified(ctx, msg.choice, deps))
                await finish(ctx, None)
    except WebSocketDisconnect:
        pass
    finally:
        await drop_pending()
