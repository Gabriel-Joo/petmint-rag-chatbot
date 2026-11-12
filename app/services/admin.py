"""
admin.py
관리자 화면(2026-11-12, 13번 2-5절) — 상담원별 상담 조회와 직원 목록. **읽기만** 한다.

- Grafana(전체 추세)와 역할이 다르다 — 여기는 개별 상담을 연다. 숫자 · 그래프는 다시 그리지 않는다(상담원 목록의 건수만).
- 일반 모드는 SQL에서 뺀다(개인적인 질문이라 관리자도 보지 않는다). 세션 id를 직접 넣어도 None → 404.
- 상담원은 인사 원장(insurance_core.employees) 직원만 — 원장 밖 이메일(평가 스크립트 dev@local)은 목록에 없다.
- 인사 원장은 기간계 소유라 SELECT만. 급여 · 평가 · 휴가 테이블은 쿼리에도 넣지 않는다. 근속 계산에 휴직(employee_absences)만 읽는다.
- 열람 기록(admin_views)만 쓴다 — 누가 언제 어느 상담원의 목록 · 대화를 열었나.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Engine, bindparam, text

from app.db import now, utc
from app.schemas import AdminAgent, AdminEmployee, AdminSession, AdminSessionDetail, AdminSessionList, AdminTurn
from app.services import hr_personal, payout
from app.services.turn_log import TurnLogStore

KST = timezone(timedelta(hours=9))
MAX_DAYS = 31                 # 기간 최대 — 평가 기록이 하루 수천 건 쌓인 날이 있다
LIST_LIMIT = 200              # 상담 목록은 한 번에 이만큼(최신부터). 더 보려면 offset — 「더 보기」


def utc_range(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    """KST 날짜 [from, to] → UTC naive [시작, 끝) — DB 시각은 UTC다(app/db.py)"""
    a = datetime.combine(d_from, time(), KST).astimezone(timezone.utc).replace(tzinfo=None)
    b = datetime.combine(d_to + timedelta(days=1), time(), KST).astimezone(timezone.utc).replace(tzinfo=None)
    return a, b


@dataclass(frozen=True)
class _Emp:
    employee_id: str
    name: str
    email: str
    grade: str
    retired: bool


class AdminStore:
    def __init__(self, engine: Engine, core: Engine, turn_log: TurnLogStore):
        self.engine, self.core, self.turn_log = engine, core, turn_log

    # ----- 기간계(읽기만)

    def _employees(self) -> list[_Emp]:
        today = payout.today()
        with self.core.connect() as c:
            rows = c.execute(text("SELECT employee_id, name, email, grade, retired_on FROM employees ORDER BY employee_id")).all()
        return [_Emp(r[0], r[1], r[2].lower(), r[3], r[4] is not None and r[4] <= today) for r in rows]

    def _roles(self) -> dict[str, tuple[str, bool]]:
        with self.engine.connect() as c:
            return {r[0]: (r[1], r[2] is not None) for r in c.execute(text("SELECT employee_id, role, disabled_at FROM accounts"))}

    def _customer_names(self, ids: set[str]) -> dict[str, str]:
        if not ids:
            return {}
        with self.core.connect() as c:
            q = text("SELECT customer_id, name FROM customers WHERE customer_id IN :ids").bindparams(bindparam("ids", expanding=True))
            return {r[0]: r[1] for r in c.execute(q, dict(ids=sorted(ids)))}

    # ----- 상담 조회

    def agents(self, d_from: date, d_to: date) -> list[AdminAgent]:
        a, b = utc_range(d_from, d_to)
        with self.engine.connect() as c:
            counts = {r[0]: (int(r[1]), int(r[2])) for r in c.execute(text(
                "SELECT s.agent_email, COUNT(*), COUNT(DISTINCT s.customer_id) FROM sessions s"
                " WHERE s.mode <> '일반' AND s.started_at >= :a AND s.started_at < :b"
                " AND EXISTS (SELECT 1 FROM turns t WHERE t.session_id = s.session_id)"
                " GROUP BY s.agent_email"), dict(a=a, b=b))}
        roles = self._roles()
        out = [AdminAgent(employee_id=e.employee_id, name=e.name, grade=e.grade, role=roles.get(e.employee_id, (None,))[0],
                          retired=e.retired, sessions=counts.get(e.email, (0, 0))[0], customers=counts.get(e.email, (0, 0))[1])
               for e in self._employees()]
        # 상담이 있는 사람 먼저(많은 순), 나머지는 사번 순. 퇴직자는 그 기간에 상담이 없으면 맨 뒤
        return sorted(out, key=lambda x: (-x.sessions, x.retired, x.employee_id))

    def agent_email(self, employee_id: str) -> str | None:
        return next((e.email for e in self._employees() if e.employee_id == employee_id), None)

    def sessions(self, email: str, d_from: date, d_to: date, offset: int = 0) -> AdminSessionList:
        a, b = utc_range(d_from, d_to)
        p = dict(m=email, a=a, b=b, lim=LIST_LIMIT, off=offset)
        where = ("s.agent_email = :m AND s.mode <> '일반' AND s.started_at >= :a AND s.started_at < :b")
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT s.session_id, s.mode, s.customer_id, s.title, s.started_at, s.ended_at, s.deleted_at,"
                " COUNT(*) AS n, COALESCE(SUM(t.refused = 1), 0) AS refused,"
                " GROUP_CONCAT(DISTINCT t.pet_name ORDER BY t.pet_name SEPARATOR '\\n') AS pets"
                f" FROM sessions s JOIN turns t ON t.session_id = s.session_id WHERE {where}"
                " GROUP BY s.session_id ORDER BY s.started_at DESC, s.session_id LIMIT :lim OFFSET :off"), p).all()
            total = c.execute(text(
                f"SELECT COUNT(*) FROM sessions s WHERE {where}"
                " AND EXISTS (SELECT 1 FROM turns t WHERE t.session_id = s.session_id)"), p).scalar_one()
        names = self._customer_names({r.customer_id for r in rows if r.customer_id})
        return AdminSessionList(total=int(total), offset=offset, items=[AdminSession(
            session_id=r.session_id, mode=r.mode, title=r.title, customer_name=names.get(r.customer_id) if r.customer_id else None,
            pet_names=[x for x in (r.pets or "").split("\n") if x], turns=int(r.n), refused=int(r.refused),
            started_at=utc(r.started_at), ended_at=utc(r.ended_at), hidden=r.deleted_at is not None) for r in rows])

    def session(self, session_id: str) -> AdminSessionDetail | None:
        """대화 하나 — 일반 모드면 None(404)"""
        with self.engine.connect() as c:
            s = c.execute(text("SELECT session_id, mode, customer_id, agent_email, title, started_at, ended_at, deleted_at"
                               " FROM sessions WHERE session_id = :sid AND mode <> '일반'"), dict(sid=session_id)).first()
            if s is None:
                return None
            marks = {r[0]: (None if r[1] is None else bool(r[1]), r[2], r[3]) for r in c.execute(text(
                "SELECT t.turn_id, t.refused, f.rating, f.comment FROM turns t LEFT JOIN feedback f USING (turn_id)"
                " WHERE t.session_id = :sid"), dict(sid=session_id))}
        agent = next((e for e in self._employees() if e.email == s.agent_email), None)
        names = self._customer_names({s.customer_id} if s.customer_id else set())
        turns = [AdminTurn(**t.model_dump(), refused=marks.get(t.turn_id, (None,))[0],
                           rating=marks.get(t.turn_id, (None, None))[1], rating_comment=marks.get(t.turn_id, (None, None, None))[2])
                 for t in self.turn_log.turns_of(session_id)]
        return AdminSessionDetail(session_id=s.session_id, mode=s.mode, title=s.title, agent_name=agent.name if agent else None,
                                  agent_email=s.agent_email, customer_name=names.get(s.customer_id) if s.customer_id else None,
                                  started_at=utc(s.started_at), ended_at=utc(s.ended_at), hidden=s.deleted_at is not None, turns=turns)

    # ----- 직원 목록

    def employees(self, today: date) -> list[AdminEmployee]:
        """인사 원장 그대로. 급여(employee_payroll) · 평가(employee_evaluations) · 휴가(employee_leaves)는 읽지 않는다"""
        with self.core.connect() as c:
            rows = c.execute(text("SELECT employee_id, name, team, grade, grade_since, employment_type, hire_date, birth_date,"
                                  " retired_on, career_hire FROM employees ORDER BY employee_id")).all()
            absences: dict[str, list] = {}
            for r in c.execute(text("SELECT employee_id, kind, start_date, end_date FROM employee_absences ORDER BY start_date")):
                absences.setdefault(r[0], []).append((r[1], r[2], r[3]))
        roles = self._roles()
        out = []
        for r in rows:
            f = hr_personal.Facts(*r)
            f.absences = absences.get(f.employee_id, [])
            until = min(today, f.retired_on) if f.retired_on else today
            years, months, _ = hr_personal.tenure_ym(f, until)
            role, disabled = roles.get(f.employee_id, (None, False))
            out.append(AdminEmployee(employee_id=f.employee_id, name=f.name, grade=f.grade, employment_type=f.employment_type,
                                     hire_date=f.hire_date, tenure_years=years, tenure_months=months, retired_on=f.retired_on,
                                     role=role, disabled=disabled))
        return out

    # ----- 열람 기록

    def log_view(self, viewer: str, demo: bool, kind: str, target_email: str, ip: str | None,
                 session_id: str | None = None, d_from: date | None = None, d_to: date | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(text("INSERT INTO admin_views (viewer_employee_id, demo, kind, target_agent_email, session_id,"
                           " date_from, date_to, ip, viewed_at) VALUES (:v, :d, :k, :t, :s, :f, :to, :ip, :at)"),
                      dict(v=viewer, d=demo, k=kind, t=target_email, s=session_id, f=d_from, to=d_to, ip=ip, at=now()))
