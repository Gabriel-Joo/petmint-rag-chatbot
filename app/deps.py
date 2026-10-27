"""
deps.py
lifespan이 app.state에 올린 저장소를 라우터에 넘기는 의존성.
"""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket

from data.rag_context import ContextBuilder

from app import config
from app.services.auth import AuthStore, Me
from app.services.customers import CustomerStore
from app.services.sessions import SessionStore
from app.services.turn_log import TurnLogStore


def customers(request: Request) -> CustomerStore:
    return request.app.state.customers


def builder(request: Request) -> ContextBuilder:
    return request.app.state.builder


def sessions(request: Request) -> SessionStore:
    return request.app.state.sessions


def turn_log(request: Request) -> TurnLogStore:
    return request.app.state.turn_log


def auth(request: Request) -> AuthStore:
    return request.app.state.auth


def header_agent(conn: Request | WebSocket) -> str:
    """PETMINT_AUTH=access — Cloudflare Access 헤더 → sessions.agent_email. 로컬 개발에는 없으므로 기본값"""
    return (conn.headers.get(config.AGENT_HEADER) or "").strip().lower() or config.DEFAULT_AGENT


def origin_ok(conn: Request | WebSocket) -> bool:
    """쿠키 인증의 CSRF·WS 위조 방지 — Origin이 없으면(브라우저 밖) 통과, 있으면 허용 목록이거나 요청 Host와 같아야 한다"""
    origin = conn.headers.get("origin")
    return not origin or origin in config.ALLOWED_ORIGINS or urlsplit(origin).netloc == conn.headers.get("host")


def session_me(conn: Request | WebSocket) -> Me | None:
    """PETMINT_AUTH=app — 로그인 쿠키 → 직원. 없거나 만료면 None"""
    return conn.app.state.auth.resolve(conn.cookies.get(config.AUTH_COOKIE))


def require_login(request: Request) -> None:
    """보호 라우터 공통 의존성. access 모드는 아무것도 하지 않는다(지금 동작 그대로).
    app 모드: 로그인 안 됨 401, 첫 로그인 비밀번호 변경 전 403"""
    if config.AUTH != "app":
        return
    me = getattr(request.state, "me", None) or session_me(request)
    if me is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    if me.must_change_password:
        raise HTTPException(403, "비밀번호를 먼저 바꿔야 합니다.")
    request.state.me = me


def agent(request: Request) -> str:
    """상담원 신원(13번) → sessions.agent_email. 지난 채팅 목록 필터와 책임 추적 양쪽에 쓴다"""
    if config.AUTH != "app":
        return header_agent(request)
    require_login(request)
    return request.state.me.email
