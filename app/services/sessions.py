"""
sessions.py
세션 저장소 — MySQL sessions(12번). 재시작해도 남는다.

- 모드마다 수명이 다르다(10번 2절). 업무특화는 상담 종료로 ended_at을 찍고, 끝난 상담은 읽기 전용이다.
  일반·사내규정은 닫히지 않는다(ended_at NULL = 이어 쓸 수 있다). 무활동 정리는 없다.
- 지난 채팅 "목록에서 제거"는 deleted_at만 찍는다. turns 이하 로그는 지우지 않는다(12번 1-4절).
- 읽기와 쓰기가 다르다(09번 7-1절). 바꾸는 작업(update·end·hide·WS용 get_open)과 내 목록(list)은 agent_email로 거른다 —
  남의 세션은 없는 세션과 같다. 읽기(get_readable)는 고객이 있는 세션(업무특화)에 한해 남의 것도 연다 — 다른 상담원이 받은
  고객도 다시 전화하기 때문이다(09번 2-2절). 일반·사내규정은 남의 개인 작업 공간이라 열리지 않는다.
  고객 단위 목록(recent_customers·customer_sessions)은 상담원으로 거르지 않는다.
- pet_id는 세션에 두지 않는다 — 메시지(턴)에만 담는다.
- 동기 메서드다. REST는 스레드풀에서, WS는 asyncio.to_thread로 부른다.
"""

import uuid
from datetime import datetime

from sqlalchemy import Engine, text

from app.db import now, utc
from app.schemas import Mode, Session, SessionSummary, SessionTurn

_COLS = "session_id, mode, customer_id, agent_email, title, pinned, started_at, ended_at, deleted_at"


def _session(row) -> Session:
    m = row._mapping
    return Session(session_id=m["session_id"], mode=m["mode"], customer_id=m["customer_id"],
                   agent_email=m["agent_email"], title=m["title"], pinned=bool(m["pinned"]),
                   started_at=utc(m["started_at"]), ended_at=utc(m["ended_at"]), deleted_at=utc(m["deleted_at"]))


class SessionStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, mode: Mode, customer_id: str | None, agent_email: str) -> Session:
        s = Session(session_id=str(uuid.uuid4()), mode=mode, customer_id=customer_id, agent_email=agent_email,
                    started_at=utc(now()))
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO sessions (session_id, mode, customer_id, agent_email, started_at)"
                           " VALUES (:sid, :mode, :cid, :agent, :at)"),
                      dict(sid=s.session_id, mode=mode, cid=customer_id, agent=agent_email,
                           at=s.started_at.replace(tzinfo=None)))
        return s

    def get(self, session_id: str, agent_email: str) -> Session | None:
        """그 상담원의 세션이면 Session(종료된 것 포함), 아니면 None. 목록에서 제거한 세션도 None"""
        with self.engine.connect() as c:
            row = c.execute(text(f"SELECT {_COLS} FROM sessions"
                                 " WHERE session_id = :sid AND agent_email = :agent AND deleted_at IS NULL"),
                            dict(sid=session_id, agent=agent_email)).first()
        return _session(row) if row else None

    def get_readable(self, session_id: str, agent_email: str) -> Session | None:
        """GET /api/sessions/{id} — 내 세션이거나, 고객이 있는 세션(업무특화)이면 남의 것도. 목록에서 제거한 세션은 None"""
        with self.engine.connect() as c:
            row = c.execute(text(f"SELECT {_COLS} FROM sessions WHERE session_id = :sid AND deleted_at IS NULL"
                                 " AND (agent_email = :agent OR customer_id IS NOT NULL)"),
                            dict(sid=session_id, agent=agent_email)).first()
        return _session(row) if row else None

    def get_open(self, session_id: str, agent_email: str) -> Session | None:
        """질문을 받을 수 있는 세션 — 종료된 업무특화 상담은 None(읽기 전용)"""
        s = self.get(session_id, agent_email)
        return s if s is not None and s.ended_at is None else None

    def list(self, agent_email: str, mode: Mode, limit: int) -> list[SessionSummary]:
        """지난 채팅 — 자기 것만, 그 모드만, 제목이 생긴(질문이 있는) 것만. 고정 먼저 → 마지막 활동 내림차순"""
        return self._summaries("s.mode = :mode ORDER BY s.pinned DESC, last_active_at DESC LIMIT :limit",
                               dict(agent=agent_email, mode=mode, limit=limit))

    def summary(self, session_id: str, agent_email: str) -> SessionSummary | None:
        """목록 한 줄(PATCH 응답). 제목이 없으면(질문 전) None"""
        rows = self._summaries("s.session_id = :sid", dict(agent=agent_email, sid=session_id))
        return rows[0] if rows else None

    def _summaries(self, where: str, params: dict) -> list[SessionSummary]:
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT s.session_id, s.mode, s.title, s.pinned, s.started_at,"
                "       COALESCE((SELECT MAX(t.created_at) FROM turns t WHERE t.session_id = s.session_id),"
                "                s.started_at) AS last_active_at"
                " FROM sessions s"
                " WHERE s.agent_email = :agent AND s.deleted_at IS NULL AND s.title IS NOT NULL AND " + where),
                params).all()
        return [SessionSummary(session_id=r.session_id, mode=r.mode, title=r.title, pinned=bool(r.pinned),
                               started_at=utc(r.started_at), last_active_at=utc(r.last_active_at)) for r in rows]

    def update(self, session_id: str, agent_email: str, *, title: str | None = None,
               pinned: bool | None = None) -> bool:
        sets, params = [], dict(sid=session_id, agent=agent_email)
        if title is not None:
            sets.append("title = :title")
            params["title"] = title
        if pinned is not None:
            sets.append("pinned = :pinned")
            params["pinned"] = pinned
        if not sets:
            return self.get(session_id, agent_email) is not None
        return self._update(f"SET {', '.join(sets)}", params)

    def _update(self, set_clause: str, params: dict) -> bool:
        """그 상담원의 (제거되지 않은) 세션이 있었으면 True. SQLAlchemy의 MySQL 방언은 CLIENT_FOUND_ROWS를 켜므로
        rowcount는 바뀐 행이 아니라 걸린 행 수다 — 같은 값으로 다시 써도 True"""
        with self.engine.begin() as c:
            r = c.execute(text(f"UPDATE sessions {set_clause}"
                               " WHERE session_id = :sid AND agent_email = :agent AND deleted_at IS NULL"), params)
        return r.rowcount == 1

    def set_title_once(self, session_id: str, title: str) -> bool:
        """제목은 세션당 한 번 — 이미 있으면 그대로 둔다(경합해도 먼저 쓴 쪽이 남는다)"""
        with self.engine.begin() as c:
            r = c.execute(text("UPDATE sessions SET title = :title WHERE session_id = :sid AND title IS NULL"),
                          dict(sid=session_id, title=title))
        return r.rowcount == 1

    def end(self, session_id: str, agent_email: str) -> bool:
        """업무특화 상담 종료 — ended_at을 찍는다. 이미 끝났으면 처음 시각을 둔다(멱등)"""
        return self._update("SET ended_at = COALESCE(ended_at, :at)",
                            dict(sid=session_id, agent=agent_email, at=now()))

    def hide(self, session_id: str, agent_email: str) -> bool:
        """지난 채팅 목록에서 제거 — deleted_at만 찍는다. 로그는 남는다"""
        return self._update("SET deleted_at = :at", dict(sid=session_id, agent=agent_email, at=now()))

    def history(self, session_id: str) -> list[SessionTurn]:
        """대화 문맥(5절) — 정상 완료된 앞 턴, 오래된 순. source_keys는 답변이 쓴 근거의 graph_key"""
        with self.engine.connect() as c:
            turns = c.execute(text("SELECT turn_id, pet_id, question, rewritten_question, answer FROM turns"
                                   " WHERE session_id = :sid AND status = 'ok' ORDER BY created_at, turn_id"),
                              dict(sid=session_id)).all()
            keys = c.execute(text("SELECT r.turn_id, r.graph_key FROM retrieved r JOIN turns t USING (turn_id)"
                                  " WHERE t.session_id = :sid AND r.used AND r.graph_key IS NOT NULL"
                                  " ORDER BY r.turn_id, r.via_graph, r.`rank`, r.id"),
                             dict(sid=session_id)).all()
        by_turn: dict[str, list[str]] = {}
        for k in keys:
            by_turn.setdefault(k.turn_id, []).append(k.graph_key)
        return [SessionTurn(turn_id=t.turn_id, pet_id=t.pet_id, question=t.question,
                            rewritten_question=t.rewritten_question, answer=t.answer,
                            source_keys=by_turn.get(t.turn_id, [])) for t in turns]

    def customer_sessions(self, customer_id: str, limit: int) -> list[Session]:
        """그 고객의 과거 상담(09번 2-2절) — started_at 역순. 담당 상담원과 무관하게 전부. 질문이 없던 상담(제목 없음)은
        열어 읽을 것이 없으므로 뺀다"""
        with self.engine.connect() as c:
            rows = c.execute(text(f"SELECT {_COLS} FROM sessions WHERE customer_id = :cid AND deleted_at IS NULL"
                                  " AND title IS NOT NULL ORDER BY started_at DESC LIMIT :limit"),
                             dict(cid=customer_id, limit=limit)).all()
        return [_session(r) for r in rows]

    def recent_customers(self, limit: int) -> list[tuple[str, datetime]]:
        """고객별 마지막 상담 시각(업무특화). 종료했으면 종료 시각, 아니면 시작 시각.
        상담원으로 거르지 않는다 — 09번 2-2절: "아까 그 고객"을 다시 찾는 고객 단위 목록이고, 다른 상담원이 받은 고객도
        다시 전화할 수 있다. 상담원 필터는 지난 대화 목록(일반·사내규정, 개인 작업 공간)에만 건다"""
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT customer_id, MAX(COALESCE(ended_at, started_at)) AS last_at FROM sessions"
                " WHERE mode = '업무특화' AND deleted_at IS NULL AND customer_id IS NOT NULL"
                " GROUP BY customer_id ORDER BY last_at DESC LIMIT :limit"), dict(limit=limit)).all()
        return [(r.customer_id, utc(r.last_at)) for r in rows]
