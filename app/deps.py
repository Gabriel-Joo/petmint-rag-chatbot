"""
deps.py
lifespan이 app.state에 올린 저장소를 라우터에 넘기는 의존성.
"""

from fastapi import Request, WebSocket

from data.rag_context import ContextBuilder

from app import config
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


def agent_of(conn: Request | WebSocket) -> str:
    """상담원 신원(13번) — Cloudflare Access 헤더 → sessions.agent_email. 로컬 개발에는 없으므로 기본값.
    지난 채팅 목록 필터와 책임 추적 양쪽에 쓴다"""
    return (conn.headers.get(config.AGENT_HEADER) or "").strip().lower() or config.DEFAULT_AGENT


def agent(request: Request) -> str:
    return agent_of(request)
