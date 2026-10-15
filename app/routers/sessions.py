from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app import deps
from app.schemas import SessionCreate, SessionDetail, SessionOut, SessionPatch, SessionSummary
from app.services.customers import CustomerStore
from app.services.sessions import SessionStore
from app.services.turn_log import TurnLogStore

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
def list_sessions(mode: Literal["일반", "사내규정"], limit: int = Query(50, ge=1, le=200),
                  store: SessionStore = Depends(deps.sessions), agent: str = Depends(deps.agent)):
    """지난 채팅(10번 2-1절) — 이 상담원의 것만, 그 모드만. 업무특화는 목록이 없다(고객 조회 '최근 상담'이 맡는다)"""
    return store.list(agent, mode, limit)


@router.post("", response_model=SessionOut, status_code=201)
def start_session(body: SessionCreate, store: SessionStore = Depends(deps.sessions),
                  customers: CustomerStore = Depends(deps.customers), agent: str = Depends(deps.agent)):
    """업무특화만 고객을 거친다(1-2). 일반·사내규정은 "새 대화"마다 새 세션"""
    if body.mode == "업무특화":
        if body.customer_id is None:
            raise HTTPException(422, "업무특화 모드는 customer_id가 필요하다")
        if customers.get(body.customer_id) is None:
            raise HTTPException(404, f"고객 없음: {body.customer_id}")
    elif body.customer_id is not None:
        raise HTTPException(422, f"{body.mode} 모드는 고객을 받지 않는다")
    s = store.create(body.mode, body.customer_id, agent)
    return SessionOut(session_id=s.session_id, mode=s.mode, customer_id=s.customer_id, started_at=s.started_at)


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, store: SessionStore = Depends(deps.sessions),
                log: TurnLogStore = Depends(deps.turn_log), agent: str = Depends(deps.agent)):
    """세션 상세 — turns·retrieved에서 복원. 내 세션, 또는 고객이 있는 세션(업무특화)이면 남의 것도 연다(09번 7-1절).
    남의 일반·사내규정 세션과 제거한 세션은 404. 바꾸는 작업(PATCH·DELETE·WS·피드백)은 여전히 내 것만"""
    s = store.get_readable(session_id, agent)
    if s is None:
        raise HTTPException(404, f"세션 없음: {session_id}")
    return SessionDetail(session_id=s.session_id, mode=s.mode, customer_id=s.customer_id, started_at=s.started_at,
                         agent_email=s.agent_email, title=s.title, pinned=s.pinned, ended_at=s.ended_at, turns=log.turns_of(session_id))


@router.patch("/{session_id}", response_model=SessionSummary)
def update_session(session_id: str, body: SessionPatch, store: SessionStore = Depends(deps.sessions),
                   agent: str = Depends(deps.agent)):
    """지난 채팅 고정·이름 변경 — 보낸 필드만. 일반·사내규정 전용(고정은 상담원 개인 설정, 12번 1-1절) — 업무특화는 404"""
    title = body.title.strip() if body.title is not None else None
    if title is not None and not title:
        raise HTTPException(422, "제목이 비어 있다")
    s = store.get(session_id, agent)
    if s is None or s.mode == "업무특화":
        raise HTTPException(404, f"지난 채팅 없음: {session_id}")
    if s.title is None:                            # 질문 전 세션은 목록 대상이 아니다 — 제목은 첫 질문이 정한다
        raise HTTPException(409, "질문이 없는 세션은 목록에 없다")
    store.update(session_id, agent, title=title, pinned=body.pinned)
    return store.summary(session_id, agent)


@router.delete("/{session_id}", status_code=204)
def end_or_hide_session(session_id: str, store: SessionStore = Depends(deps.sessions),
                        agent: str = Depends(deps.agent)):
    """업무특화: 상담 종료(ended_at, 이후 읽기 전용) / 일반·사내규정: 목록에서 제거(deleted_at).
    어느 쪽이든 로그는 지우지 않는다(12번 1-4절). 진행 중 생성의 취소는 WS 쪽이 한다"""
    s = store.get(session_id, agent)
    if s is None:
        raise HTTPException(404, f"세션 없음: {session_id}")
    (store.end if s.mode == "업무특화" else store.hide)(session_id, agent)
    return Response(status_code=204)
