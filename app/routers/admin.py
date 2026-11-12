"""
admin.py
/api/admin — 관리자 화면(2026-11-12, 13번 2-5절). 모두 GET, 읽기만.

- 관리자(accounts.role = 관리자)만. 상담원 · access 모드는 404 — 403은 이 화면이 있다는 것을 알려 준다.
- 체험 관리자(체험 로그인 세션)도 들어온다. 체험 대화도 그대로 보인다(사용자 결정 — 체험 계정은 이미 "함께 쓰는 계정"이라고 안내한다).
- 상담 목록 · 대화를 열면 admin_views에 남긴다(누가 · 언제 · 누구의 무엇을).
- 직원 추가 · 계정 중지 · 비밀번호 초기화는 여기서 하지 않는다 — python -m db.employees(인사 원장은 기간계 소유).
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import config, deps
from app.schemas import AdminAgent, AdminEmployee, AdminSessionDetail, AdminSessionList
from app.services import payout
from app.services.admin import MAX_DAYS, AdminStore
from app.services.auth import Me


def require_admin(request: Request) -> Me:
    if config.AUTH != "app":
        raise HTTPException(404, "Not Found")
    deps.require_login(request)
    me: Me = request.state.me
    if me.role != "관리자":
        raise HTTPException(404, "Not Found")
    return me


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def store(request: Request) -> AdminStore:
    return request.app.state.admin


def period(d_from: date | None = Query(None, alias="from"), d_to: date | None = Query(None, alias="to")) -> tuple[date, date]:
    """기간(KST 날짜). 기본 오늘. 끝이 시작보다 앞이거나 31일을 넘으면 422"""
    today = payout.today()
    a, b = d_from or d_to or today, d_to or d_from or today
    if b < a:
        raise HTTPException(422, "끝 날짜가 시작 날짜보다 앞입니다.")
    if (b - a).days + 1 > MAX_DAYS:
        raise HTTPException(422, f"기간은 {MAX_DAYS}일까지 고를 수 있습니다.")
    return a, b


@router.get("/agents", response_model=list[AdminAgent])
def agents(p: tuple[date, date] = Depends(period), s: AdminStore = Depends(store)):
    return s.agents(*p)


@router.get("/agents/{employee_id}/sessions", response_model=AdminSessionList)
def agent_sessions(employee_id: str, request: Request, p: tuple[date, date] = Depends(period), offset: int = Query(0, ge=0),
                   s: AdminStore = Depends(store), me: Me = Depends(require_admin)):
    email = s.agent_email(employee_id)
    if email is None:
        raise HTTPException(404, "인사 원장에 없는 직원")
    out = s.sessions(email, *p, offset=offset)
    s.log_view(me.employee_id, me.demo, "sessions", email, deps.client_ip(request), d_from=p[0], d_to=p[1])
    return out


@router.get("/sessions/{session_id}", response_model=AdminSessionDetail)
def session(session_id: str, request: Request, s: AdminStore = Depends(store), me: Me = Depends(require_admin)):
    d = s.session(session_id)
    if d is None:                                  # 없는 세션 · 일반 모드
        raise HTTPException(404, "상담 없음")
    s.log_view(me.employee_id, me.demo, "session", d.agent_email, deps.client_ip(request), session_id=session_id)
    return d


@router.get("/employees", response_model=list[AdminEmployee])
def employees(s: AdminStore = Depends(store)):
    return s.employees(payout.today())
