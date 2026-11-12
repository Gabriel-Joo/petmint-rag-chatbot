"""
test_admin.py
관리자 화면(2026-11-12, 13번 2-5절).

- RouteTest: 권한(관리자만, 상담원 · access · 체험 상담원 404, 로그인 없음 401), 기간(기본 오늘, 31일 넘으면 422), 열람 기록 호출 —
  AdminStore를 목으로 바꾼다(DB 없음, 늘 돈다)
- SourceTest: 급여 · 평가 · 휴가 테이블을 쿼리에 넣지 않는다, 쓰는 SQL은 admin_views INSERT 하나
- StoreTest: AdminStore의 SQL — 로컬 MySQL. 일반 모드 제외, 원장 밖(dev@local) 제외, 열람 기록. PETMINT_DB_TESTS=1일 때만 돈다
"""

import os
import re
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.routers import admin
from app.schemas import AdminSessionList
from app.services import payout
from app.services.admin import utc_range
from app.services.auth import Me

ADMIN = Me("E2001003", "권태호", "kwon.taeho@petmint.example", "고객상담팀", "부장", "관리자", False)
AGENT = Me("E2018032", "장민혁", "jang.minhyuk@petmint.example", "고객상담팀", "대리", "상담원", False)
DEMO_ADMIN = Me("E2001003", "권태호", "kwon.taeho@petmint.example", "고객상담팀", "부장", "관리자", False, demo=True)


def make_app():
    a = FastAPI()
    a.include_router(admin.router)
    a.state.auth = mock.Mock()
    a.state.auth.resolve.return_value = None
    a.state.admin = mock.Mock()
    a.state.admin.agents.return_value = []
    a.state.admin.employees.return_value = []
    a.state.admin.agent_email.return_value = ADMIN.email
    a.state.admin.sessions.return_value = AdminSessionList(total=0, items=[])
    a.state.admin.session.return_value = None
    return a


class RouteTest(unittest.TestCase):
    PATHS = ["/api/admin/agents", "/api/admin/employees", "/api/admin/agents/E2001003/sessions", "/api/admin/sessions/x"]

    def setUp(self):
        self.mode = mock.patch.object(config, "AUTH", "app")
        self.mode.start()
        self.c = TestClient(make_app())
        self.c.cookies.set(config.AUTH_COOKIE, "tok")

    def tearDown(self):
        self.mode.stop()

    def login(self, me):
        self.c.app.state.auth.resolve.return_value = me

    def test_no_login_401(self):
        for p in self.PATHS:
            self.assertEqual(self.c.get(p).status_code, 401, p)

    def test_agent_gets_404_not_403(self):
        self.login(AGENT)
        for p in self.PATHS:
            self.assertEqual(self.c.get(p).status_code, 404, p)
        self.c.app.state.admin.agents.assert_not_called()

    def test_access_mode_404(self):
        with mock.patch.object(config, "AUTH", "access"):
            for p in self.PATHS:
                self.assertEqual(self.c.get(p).status_code, 404, p)

    def test_admin_and_demo_admin_allowed(self):
        for me in (ADMIN, DEMO_ADMIN):
            self.login(me)
            self.assertEqual(self.c.get("/api/admin/agents").status_code, 200)
            self.assertEqual(self.c.get("/api/admin/employees").status_code, 200)

    def test_period_default_today_and_limit(self):
        self.login(ADMIN)
        self.c.get("/api/admin/agents")
        today = payout.today()
        self.c.app.state.admin.agents.assert_called_with(today, today)
        self.assertEqual(self.c.get("/api/admin/agents?from=2026-10-01&to=2026-10-31").status_code, 200)
        self.assertEqual(self.c.get("/api/admin/agents?from=2026-10-01&to=2026-11-01").status_code, 422)
        self.assertEqual(self.c.get("/api/admin/agents?from=2026-10-05&to=2026-10-01").status_code, 422)

    def test_views_are_logged(self):
        self.login(DEMO_ADMIN)
        st = self.c.app.state.admin
        self.c.get("/api/admin/agents/E2001003/sessions?from=2026-11-01&to=2026-11-02")
        st.log_view.assert_called_with("E2001003", True, "sessions", ADMIN.email, mock.ANY,
                                       d_from=date(2026, 11, 1), d_to=date(2026, 11, 2))
        st.log_view.reset_mock()
        self.assertEqual(self.c.get("/api/admin/sessions/nope").status_code, 404)   # 없는 세션 · 일반 모드
        st.log_view.assert_not_called()

    def test_unknown_employee_404(self):
        self.login(ADMIN)
        self.c.app.state.admin.agent_email.return_value = None
        self.assertEqual(self.c.get("/api/admin/agents/dev@local/sessions").status_code, 404)

    def test_utc_range_is_kst_day(self):
        a, b = utc_range(date(2026, 11, 12), date(2026, 11, 12))
        self.assertEqual((a.isoformat(), b.isoformat()), ("2026-11-11T15:00:00", "2026-11-12T15:00:00"))


class SourceTest(unittest.TestCase):
    def test_no_salary_evaluation_leave_and_read_only(self):
        src = (Path(__file__).parents[1] / "app" / "services" / "admin.py").read_text()
        src = re.sub(r'"""[\s\S]*?"""', "", src)                       # 문서 문자열은 SQL이 아니다
        sql = " ".join(re.findall(r'"([^"]*)"', src))
        for table in ("employee_payroll", "employee_evaluations", "employee_leaves"):
            self.assertNotIn(table, sql)
        writes = re.findall(r"\b(INSERT|UPDATE|DELETE|REPLACE|ALTER|DROP)\b", sql)
        self.assertEqual(writes, ["INSERT"])
        self.assertIn("INSERT INTO admin_views", sql)


@unittest.skipUnless(os.environ.get("PETMINT_DB_TESTS") == "1", "로컬 MySQL 필요(PETMINT_DB_TESTS=1)")
class StoreTest(unittest.TestCase):
    """가상 직원 E2022071(신하늘 — 앱 계정 있음)로 사내규정 · 일반 세션을 하나씩 만들었다 지운다"""
    EMAIL = "shin.haneul@petmint.example"

    @classmethod
    def setUpClass(cls):
        from sqlalchemy import text

        from app.db import make_engine
        from app.services.admin import AdminStore
        from app.services.turn_log import TurnLogStore
        from db.conn import app_settings
        cls.text = staticmethod(text)
        cls.engine = make_engine(app_settings("petmint"))
        cls.store = AdminStore(cls.engine, make_engine(app_settings("petmint_core")), TurnLogStore(cls.engine))

    def setUp(self):
        import uuid

        from app.db import now
        self.ids = {m: str(uuid.uuid4()) for m in ("사내규정", "일반")}
        self.turns = {m: str(uuid.uuid4()) for m in self.ids}
        t = now()
        with self.engine.begin() as c:
            for m, sid in self.ids.items():
                c.execute(self.text("INSERT INTO sessions (session_id, mode, agent_email, title, started_at)"
                                    " VALUES (:s, :m, :a, '시험', :t)"), dict(s=sid, m=m, a=self.EMAIL, t=t))
                c.execute(self.text("INSERT INTO turns (turn_id, session_id, question, answer, model, prompt_version, index_version,"
                                    " latency_ms, refused, created_at) VALUES (:id, :s, '질문', '답', 'm', 'p', 'i', 1, 1, :t)"),
                          dict(id=self.turns[m], s=sid, t=t))
            c.execute(self.text("INSERT INTO feedback (turn_id, rating, created_at) VALUES (:id, 'down', :t)"),
                      dict(id=self.turns["사내규정"], t=t))

    def tearDown(self):
        with self.engine.begin() as c:
            for tid in self.turns.values():
                c.execute(self.text("DELETE FROM feedback WHERE turn_id = :t"), dict(t=tid))
            for sid in self.ids.values():
                c.execute(self.text("DELETE FROM turns WHERE session_id = :s"), dict(s=sid))
                c.execute(self.text("DELETE FROM sessions WHERE session_id = :s"), dict(s=sid))
            c.execute(self.text("DELETE FROM admin_views WHERE viewer_employee_id = 'TEST'"))

    def test_general_mode_hidden(self):
        today = payout.today()
        self.assertIsNone(self.store.session(self.ids["일반"]))
        d = self.store.session(self.ids["사내규정"])
        self.assertEqual((d.agent_name, d.turns[0].refused, d.turns[0].rating), ("신하늘", True, "down"))
        lst = self.store.sessions(self.EMAIL, today - timedelta(days=1), today)
        got = {it.session_id for it in lst.items}
        self.assertIn(self.ids["사내규정"], got)
        self.assertNotIn(self.ids["일반"], got)
        row = next(it for it in lst.items if it.session_id == self.ids["사내규정"])
        self.assertEqual((row.turns, row.refused), (1, 1))

    def test_agents_are_ledger_only(self):
        today = payout.today()
        agents = self.store.agents(today - timedelta(days=30), today)
        self.assertNotIn("dev@local", {a.employee_id for a in agents})
        names = {a.name for a in agents}
        self.assertFalse({"조현석", "문태양", "류채원", "황재민"} & names)   # 앱 계정 없는 직원은 상담원 목록에 없다
        shin = next(a for a in agents if a.name == "신하늘")
        self.assertGreaterEqual(shin.sessions, 1)

    def test_employees_have_no_pay_fields(self):
        rows = self.store.employees(payout.today())
        self.assertTrue(rows)
        self.assertFalse({"base_pay", "total_pay", "ordinary_wage", "grade_s", "evaluations", "leaves"} & set(rows[0].model_dump()))
        kwon = next(r for r in rows if r.employee_id == "E2001003")
        self.assertEqual(kwon.role, "관리자")
        self.assertGreaterEqual(kwon.tenure_years, 25)            # 2001-03-02 입사

    def test_log_view(self):
        self.store.log_view("TEST", True, "session", self.EMAIL, "127.0.0.1", session_id=self.ids["사내규정"])
        with self.engine.connect() as c:
            r = c.execute(self.text("SELECT demo, kind, target_agent_email, session_id FROM admin_views WHERE viewer_employee_id = 'TEST'")).one()
        self.assertEqual(tuple(r), (1, "session", self.EMAIL, self.ids["사내규정"]))


if __name__ == "__main__":
    unittest.main()
