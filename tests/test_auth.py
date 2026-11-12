"""
test_auth.py
앱 자체 인증(2026-10-28, 13번 2-1절).

- RouteTest·WsTest: 라우터·의존성·Origin 검사 — AuthStore를 목으로 바꾼다(DB 없음, 늘 돈다)
- StoreTest: AuthStore의 SQL — 로컬 MySQL(petmint·insurance_core)에서 가상 직원 E2025112(조현석)의 계정을 만들었다 지운다.
  PETMINT_DB_TESTS=1일 때만 돈다
"""

import os
import unittest
from unittest import mock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import config, deps
from app.routers import auth, chat_ws, sessions
from app.services.auth import AuthError, Me

ME = Me("E2018032", "장민혁", "jang.minhyuk@petmint.example", "고객상담팀", "대리", "상담원", False)


def make_app(store, mode="app"):
    import app.main as main_mod
    a = FastAPI()
    a.middleware("http")(main_mod.check_origin)
    a.include_router(auth.router)
    a.include_router(sessions.router, dependencies=[Depends(deps.require_login)])
    a.include_router(chat_ws.router)
    a.state.auth = store
    a.state.sessions = mock.Mock()
    a.state.sessions.list.return_value = []
    a.state.sessions.get_open.return_value = None
    a.state.turn_log = a.state.customers = a.state.retriever = a.state.builder = a.state.llm = mock.Mock()
    return a


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.mode = mock.patch.object(config, "AUTH", "app")
        self.mode.start()
        self.store = mock.Mock()
        self.store.resolve.return_value = None
        self.c = TestClient(make_app(self.store))

    def tearDown(self):
        self.mode.stop()

    def test_protected_route_needs_login(self):
        r = self.c.get("/api/sessions?mode=일반")
        self.assertEqual(r.status_code, 401)

    def test_logged_in_route_uses_employee_email(self):
        self.store.resolve.return_value = ME
        self.c.cookies.set(config.AUTH_COOKIE, "tok")
        self.assertEqual(self.c.get("/api/sessions?mode=일반").status_code, 200)
        self.c.app.state.sessions.list.assert_called_once_with(ME.email, "일반", mock.ANY)

    def test_must_change_password_blocks_other_routes(self):
        self.store.resolve.return_value = Me(ME.employee_id, ME.name, ME.email, ME.team, ME.grade, ME.role, True)
        self.c.cookies.set(config.AUTH_COOKIE, "tok")
        self.assertEqual(self.c.get("/api/sessions?mode=일반").status_code, 403)
        self.assertEqual(self.c.get("/api/auth/me").json()["must_change_password"], True)

    def test_login_sets_httponly_cookie(self):
        self.store.login.return_value = ("tok123", ME)
        r = self.c.post("/api/auth/login", json={"employee_id": "E2018032", "password": "x" * 12})
        self.assertEqual(r.status_code, 200, r.text)
        cookie = r.headers["set-cookie"]
        for part in ("petmint_session=tok123", "HttpOnly", "SameSite=lax", "Path=/"):
            self.assertIn(part.lower(), cookie.lower())
        self.assertEqual(r.json()["name"], "장민혁")

    def test_login_failure_message(self):
        self.store.login.side_effect = AuthError(401, "사번 또는 비밀번호가 올바르지 않습니다.")
        r = self.c.post("/api/auth/login", json={"employee_id": "nope", "password": "x"})
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "사번 또는 비밀번호가 올바르지 않습니다."))

    def test_cross_site_post_rejected(self):
        self.store.login.return_value = ("tok", ME)
        r = self.c.post("/api/auth/login", json={"employee_id": "E2018032", "password": "x"},
                        headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        self.store.login.assert_not_called()

    def test_same_host_origin_allowed(self):
        self.store.login.return_value = ("tok", ME)
        r = self.c.post("/api/auth/login", json={"employee_id": "E2018032", "password": "x"},
                        headers={"origin": "http://testserver"})
        self.assertEqual(r.status_code, 200)

    def test_logout_clears_cookie(self):
        self.c.cookies.set(config.AUTH_COOKIE, "tok")
        r = self.c.post("/api/auth/logout")
        self.assertEqual(r.status_code, 204)
        self.store.logout.assert_called_once_with("tok")
        self.assertIn("max-age=0", r.headers["set-cookie"].lower())


class AccessModeTest(unittest.TestCase):
    """기본(access) 모드는 지금 동작 그대로 — 쿠키 없이 헤더(없으면 기본값)가 상담원"""

    def test_access_mode_unchanged(self):
        with mock.patch.object(config, "AUTH", "access"):
            store = mock.Mock()
            store.employee_by_email.return_value = None
            c = TestClient(make_app(store))
            self.assertEqual(c.get("/api/sessions?mode=일반").status_code, 200)
            c.app.state.sessions.list.assert_called_once_with(config.DEFAULT_AGENT, "일반", mock.ANY)
            self.assertEqual(c.post("/api/auth/login", json={"employee_id": "a", "password": "b"}).status_code, 404)
            me = c.get("/api/auth/me").json()
            self.assertEqual((me["auth_mode"], me["email"]), ("access", config.DEFAULT_AGENT))
            store.resolve.assert_not_called()


class WsTest(unittest.TestCase):
    def ws_close_code(self, store, headers=None, cookie=None):
        with mock.patch.object(config, "AUTH", "app"):
            c = TestClient(make_app(store))
            if cookie:
                c.cookies.set(config.AUTH_COOKIE, cookie)
            with c.websocket_connect("/ws/chat/s1", headers=headers or {}) as ws:
                with self.assertRaises(WebSocketDisconnect) as e:
                    ws.receive_text()
            return e.exception.code

    def test_ws_without_login(self):
        store = mock.Mock()
        store.resolve.return_value = None
        self.assertEqual(self.ws_close_code(store), config.WS_CLOSE_UNAUTHORIZED)

    def test_ws_cross_site(self):
        store = mock.Mock()
        store.resolve.return_value = ME
        self.assertEqual(self.ws_close_code(store, {"origin": "https://evil.example"}, "tok"), config.WS_CLOSE_FORBIDDEN_ORIGIN)

    def test_ws_logged_in_reaches_session_check(self):
        store = mock.Mock()
        store.resolve.return_value = ME
        self.assertEqual(self.ws_close_code(store, cookie="tok"), config.WS_CLOSE_SESSION_NOT_FOUND)



class DemoRouteTest(unittest.TestCase):
    """체험 로그인 라우터(2026-11-12, 13번 2-4절) — 꺼지면 404, 켜면 카드 · 쿠키, IP는 CF-Connecting-IP"""

    def setUp(self):
        self.patches = [mock.patch.object(config, "AUTH", "app"), mock.patch.object(config, "DEMO_LOGIN", True)]
        for p in self.patches:
            p.start()
        from app.services.auth import Employee
        self.store = mock.Mock()
        self.store.resolve.return_value = None
        self.store.demo_pool.return_value = [(Employee("E2001003", "권태호", "kwon@petmint.example", "고객상담팀", "부장", False), "관리자")]
        self.demo_me = Me("E2001003", "권태호", "kwon@petmint.example", "고객상담팀", "부장", "관리자", False, True)
        self.store.demo_login.return_value = ("tok", self.demo_me)
        app_ = make_app(self.store)
        app_.state.employees = mock.Mock()
        app_.state.employees.load.return_value = None
        self.c = TestClient(app_)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_off_is_404(self):
        with mock.patch.object(config, "DEMO_LOGIN", False):
            self.assertEqual(self.c.get("/api/auth/demo-accounts").status_code, 404)
            self.assertEqual(self.c.post("/api/auth/demo", json={"employee_id": "E2001003"}).status_code, 404)
        self.store.demo_login.assert_not_called()

    def test_access_mode_is_404(self):
        with mock.patch.object(config, "AUTH", "access"):
            self.assertEqual(self.c.get("/api/auth/demo-accounts").status_code, 404)

    def test_cards(self):
        r = self.c.get("/api/auth/demo-accounts")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]["role"], "관리자")
        self.assertNotIn("password", r.text.lower())

    def test_demo_login_sets_cookie_and_flag(self):
        r = self.c.post("/api/auth/demo", json={"employee_id": "E2001003"}, headers={"CF-Connecting-IP": "203.0.113.7"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["is_demo"])
        self.assertIn("httponly", r.headers["set-cookie"].lower())
        self.assertEqual(self.store.demo_login.call_args.args[:2], ("E2001003", "203.0.113.7"))

    def test_demo_login_errors_pass_through(self):
        self.store.demo_login.side_effect = AuthError(400, "체험할 수 없는 계정입니다.")
        self.assertEqual(self.c.post("/api/auth/demo", json={"employee_id": "E9999999"}).status_code, 400)

    def test_demo_post_cross_site_rejected(self):
        r = self.c.post("/api/auth/demo", json={"employee_id": "E2001003"}, headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)


class RateLimitTest(unittest.TestCase):
    def test_sliding_window(self):
        from app.services.rate_limit import SlidingWindow
        t = [0.0]
        w = SlidingWindow(10, 60, clock=lambda: t[0])
        self.assertTrue(all(w.allow("a") for _ in range(10)))
        self.assertFalse(w.allow("a"))
        self.assertTrue(w.allow("b"))                     # 방문자마다 따로
        t[0] = 60.5
        self.assertTrue(w.allow("a"))                     # 창이 지나면 다시


class DemoCardTest(unittest.TestCase):
    def test_card_text(self):
        from datetime import date

        from app.services import demo
        from app.services.auth import Employee
        from app.services.hr_personal import Facts
        f = Facts("E1", "류채원", "고객상담팀", "사원", date(2026, 9, 1), "정규직", date(2026, 9, 1), date(2001, 1, 1), None)
        c = demo.card(Employee("E1", "류채원", "r@x", "고객상담팀", "사원", False), "상담원", f, date(2026, 11, 12))
        self.assertEqual(c.summary, "류채원 사원 · 근속 2개월 · 연차 2일 남음")
        self.assertIn("수습 중(11-30까지)", c.tags)
        self.assertIn("1년 미만(퇴직금 없음)", c.tags)

    def test_card_without_ledger(self):
        from datetime import date

        from app.services import demo
        from app.services.auth import Employee
        c = demo.card(Employee("E1", "가", "a@x", None, "사원", False), "상담원", None, date(2026, 11, 12))
        self.assertEqual((c.summary, c.tags), ("가 사원", []))

@unittest.skipUnless(os.environ.get("PETMINT_DB_TESTS") == "1", "로컬 MySQL 필요(PETMINT_DB_TESTS=1)")
class StoreTest(unittest.TestCase):
    EID = "E2025112"

    @classmethod
    def setUpClass(cls):
        from sqlalchemy import text

        from app.db import make_engine
        from app.services.auth import AuthStore, hash_password
        from db.conn import app_settings
        cls.text = staticmethod(text)
        cls.engine = make_engine(app_settings("petmint"))
        cls.store = AuthStore(cls.engine, make_engine(app_settings("petmint_core")))
        cls.hash = staticmethod(hash_password)

    def setUp(self):
        from app.db import now
        with self.engine.begin() as c:
            c.execute(self.text("DELETE FROM accounts WHERE employee_id = :e"), dict(e=self.EID))
            c.execute(self.text("INSERT INTO accounts (employee_id, role, password_hash, must_change_password, created_at)"
                                " VALUES (:e, '상담원', :h, TRUE, :t)"), dict(e=self.EID, h=self.hash("first-pass-123"), t=now()))

    def tearDown(self):
        with self.engine.begin() as c:
            c.execute(self.text("DELETE FROM accounts WHERE employee_id = :e"), dict(e=self.EID))

    def test_login_resolve_logout(self):
        token, me = self.store.login(self.EID, "first-pass-123", "127.0.0.1", "test")
        self.assertEqual((me.name, me.email, me.must_change_password), ("조현석", "cho.hyunseok@petmint.example", True))
        self.assertEqual(self.store.resolve(token).employee_id, self.EID)
        self.store.logout(token)
        self.assertIsNone(self.store.resolve(token))

    def test_wrong_password_and_unknown_id_same_message(self):
        with self.assertRaises(AuthError) as a:
            self.store.login(self.EID, "wrong-password", None, None)
        with self.assertRaises(AuthError) as b:
            self.store.login("E9999999", "wrong-password", None, None)
        self.assertEqual((a.exception.status, a.exception.message), (b.exception.status, b.exception.message))

    def test_lock_after_five_failures(self):
        for _ in range(4):
            with self.assertRaises(AuthError):
                self.store.login(self.EID, "wrong-password", None, None)
        with self.assertRaises(AuthError) as e:
            self.store.login(self.EID, "wrong-password", None, None)
        self.assertEqual(e.exception.status, 429)
        with self.assertRaises(AuthError) as e:                  # 맞는 비밀번호도 잠금 중에는 막힌다
            self.store.login(self.EID, "first-pass-123", None, None)
        self.assertEqual(e.exception.status, 429)

    def test_idle_expiry(self):
        token, _ = self.store.login(self.EID, "first-pass-123", None, None)
        with self.engine.begin() as c:
            c.execute(self.text("UPDATE auth_sessions SET last_seen_at = last_seen_at - INTERVAL 3 HOUR WHERE employee_id = :e"),
                      dict(e=self.EID))
        self.assertIsNone(self.store.resolve(token))

    def test_change_password_drops_other_sessions(self):
        t1, me = self.store.login(self.EID, "first-pass-123", None, None)
        t2, _ = self.store.login(self.EID, "first-pass-123", None, None)
        with self.assertRaises(AuthError):
            self.store.change_password(me, t1, "first-pass-123", "short")
        self.store.change_password(me, t1, "first-pass-123", "second-pass-456")
        self.assertFalse(self.store.resolve(t1).must_change_password)
        self.assertIsNone(self.store.resolve(t2))
        _, me2 = self.store.login(self.EID, "second-pass-456", None, None)
        self.assertFalse(me2.must_change_password)

    def test_disabled_account(self):
        token, _ = self.store.login(self.EID, "first-pass-123", None, None)
        with self.engine.begin() as c:
            c.execute(self.text("UPDATE accounts SET disabled_at = NOW() WHERE employee_id = :e"), dict(e=self.EID))
        self.assertIsNone(self.store.resolve(token))
        with self.assertRaises(AuthError) as e:
            self.store.login(self.EID, "first-pass-123", None, None)
        self.assertEqual(e.exception.status, 403)

    def test_retired_employee_cannot_login(self):
        with self.engine.begin() as c:
            c.execute(self.text("DELETE FROM accounts WHERE employee_id = 'E2015044'"))
            c.execute(self.text("INSERT INTO accounts (employee_id, password_hash, must_change_password, created_at)"
                                " VALUES ('E2015044', :h, FALSE, NOW())"), dict(h=self.hash("first-pass-123")))
        try:
            with self.assertRaises(AuthError) as e:
                self.store.login("E2015044", "first-pass-123", None, None)
            self.assertEqual(e.exception.status, 403)
        finally:
            with self.engine.begin() as c:
                c.execute(self.text("UPDATE accounts SET must_change_password = TRUE WHERE employee_id = 'E2015044'"))


    # ----- 체험 로그인(2026-11-12, 13번 2-4절)

    def _demo_sessions(self):
        with self.engine.begin() as c:
            return c.execute(self.text("SELECT COUNT(*) FROM auth_sessions WHERE employee_id = :e AND demo"), dict(e=self.EID)).scalar()

    def test_demo_login_is_marked_and_skips_password_change(self):
        token, me = self.store.demo_login(self.EID, None, "test")
        self.assertTrue(me.demo)
        self.assertFalse(me.must_change_password)               # 계정은 첫 로그인 변경 대기지만 체험은 묻지 않는다
        r = self.store.resolve(token)
        self.assertTrue(r.demo)
        self.assertFalse(r.must_change_password)
        with self.assertRaises(AuthError) as e:
            self.store.change_password(r, token, "first-pass-123", "second-pass-456")
        self.assertEqual(e.exception.status, 403)
        _, normal = self.store.login(self.EID, "first-pass-123", None, None)   # 같은 직원의 비밀번호 로그인은 체험이 아니다
        self.assertFalse(normal.demo)

    def test_demo_login_ignores_and_keeps_lock(self):
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.store.login(self.EID, "wrong-password", None, None)
        token, _ = self.store.demo_login(self.EID, None, None)  # 누가 잠가도 체험은 막히지 않는다
        self.assertIsNotNone(self.store.resolve(token))
        with self.assertRaises(AuthError) as e:                  # 잠금은 그대로 남는다
            self.store.login(self.EID, "first-pass-123", None, None)
        self.assertEqual(e.exception.status, 429)

    def test_demo_pool_excludes_retired_and_disabled(self):
        ids = [e.employee_id for e, _ in self.store.demo_pool()]
        self.assertIn(self.EID, ids)
        self.assertNotIn("E2015044", ids)                        # 퇴직
        with self.assertRaises(AuthError) as e:
            self.store.demo_login("E2015044", None, None)
        self.assertEqual(e.exception.status, 400)
        with self.engine.begin() as c:
            c.execute(self.text("UPDATE accounts SET disabled_at = NOW() WHERE employee_id = :e"), dict(e=self.EID))
        self.assertNotIn(self.EID, [e.employee_id for e, _ in self.store.demo_pool()])

    def test_demo_login_creates_passwordless_account(self):
        with self.engine.begin() as c:
            c.execute(self.text("DELETE FROM accounts WHERE employee_id = :e"), dict(e=self.EID))
        token, me = self.store.demo_login(self.EID, None, None)
        self.assertEqual(me.role, "상담원")
        with self.assertRaises(AuthError) as e:                  # 비밀번호 없는 계정 — 사번 · 비밀번호로는 못 들어온다
            self.store.login(self.EID, "", None, None)
        self.assertEqual(e.exception.status, 401)

    def test_demo_ip_limit(self):
        with mock.patch.object(config, "DEMO_LOGIN_PER_IP", 3):
            for _ in range(3):
                self.store.demo_login(self.EID, "203.0.113.9", None)
            with self.assertRaises(AuthError) as e:
                self.store.demo_login(self.EID, "203.0.113.9", None)
            self.assertEqual(e.exception.status, 429)
            self.store.demo_login(self.EID, "203.0.113.10", None)   # 다른 IP는 된다
        self.assertEqual(self._demo_sessions(), 4)

if __name__ == "__main__":
    unittest.main()
