"""
auth.py
앱 자체 인증(2026-10-28, 13번 2-1절) — 사번·비밀번호 로그인, 서버 저장 세션, 잠금, 비밀번호 변경.

- 직원 신원(이름·이메일·팀·직급·퇴직)은 기간계 insurance_core.employees를 읽는다(SELECT 계정). 앱이 쓰는 값(역할·해시·잠금·세션)은
  petmint.accounts·auth_sessions에 있다. 다른 데이터베이스라 조인하지 않고 두 번 읽는다.
- 쿠키에는 32바이트 난수 토큰, DB에는 그 SHA-256만 둔다. JWT를 쓰지 않는다 — 퇴직·비밀번호 변경·로그아웃 때 즉시 끊어야 한다.
- 실패 문구는 하나다(사번이 없는지 비밀번호가 틀렸는지 알려 주지 않는다). 없는 사번도 같은 시간이 걸리게 가짜 해시를 검증한다.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import Engine, text

from app.db import now

IDLE = timedelta(hours=2)            # 마지막 요청 후 이만큼 지나면 만료
ABSOLUTE = timedelta(hours=12)       # 로그인 후 이만큼 지나면 만료(상담 근무 한 교대)
TOUCH_EVERY = timedelta(minutes=1)   # last_seen_at을 매 요청 쓰지 않는다
MAX_FAILED = 5
LOCK = timedelta(minutes=15)
MIN_PASSWORD = 10

FAIL_MESSAGE = "사번 또는 비밀번호가 올바르지 않습니다."
LOCK_MESSAGE = "로그인 실패가 반복되어 잠시 잠겼습니다. 15분 뒤에 다시 시도하세요."

_hasher = PasswordHasher()
_DUMMY = _hasher.hash("dummy-password-for-timing")


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@dataclass(frozen=True)
class Employee:
    employee_id: str
    name: str
    email: str
    team: str | None
    grade: str
    retired: bool


@dataclass(frozen=True)
class Me:
    employee_id: str
    name: str
    email: str
    team: str | None
    grade: str
    role: str
    must_change_password: bool


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def check_password_rule(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(422, f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthStore:
    def __init__(self, engine: Engine, core: Engine):
        self.engine, self.core = engine, core

    # ----- 기간계(읽기만)

    def employee(self, employee_id: str) -> Employee | None:
        with self.core.connect() as c:
            r = c.execute(text("SELECT employee_id, name, email, team, grade, retired_on FROM employees WHERE employee_id = :e"),
                          dict(e=employee_id)).first()
        return None if r is None else Employee(r[0], r[1], r[2].lower(), r[3], r[4], r[5] is not None and r[5] <= now().date())

    def employee_by_email(self, email: str) -> Employee | None:
        with self.core.connect() as c:
            r = c.execute(text("SELECT employee_id FROM employees WHERE email = :m"), dict(m=email.lower())).first()
        return None if r is None else self.employee(r[0])

    # ----- 로그인

    def login(self, employee_id: str, password: str, ip: str | None, user_agent: str | None) -> tuple[str, Me]:
        """성공하면 (쿠키 토큰, Me). 실패는 AuthError — 401(사번·비밀번호), 429(잠김), 403(중지·퇴직).
        실패 횟수는 커밋한 뒤 던진다 — 트랜잭션 블록 안에서 던지면 롤백된다"""
        t = now()
        fail, token = None, None
        with self.engine.begin() as c:
            a = c.execute(text("SELECT role, password_hash, must_change_password, failed_count, locked_until, disabled_at"
                               " FROM accounts WHERE employee_id = :e FOR UPDATE"), dict(e=employee_id)).first()
            emp = self.employee(employee_id) if a is not None else None
            if a is None or emp is None or a[1] is None:
                _verify(_DUMMY, password)                       # 없는 사번도 같은 시간
                raise AuthError(401, FAIL_MESSAGE)
            role, pw_hash, must_change, failed, locked_until, disabled_at = a
            if locked_until is not None and locked_until > t:
                raise AuthError(429, LOCK_MESSAGE)
            if not _verify(pw_hash, password):
                failed += 1
                lock = t + LOCK if failed >= MAX_FAILED else None
                c.execute(text("UPDATE accounts SET failed_count = :f, locked_until = :l WHERE employee_id = :e"),
                          dict(f=0 if lock else failed, l=lock, e=employee_id))
                fail = AuthError(429 if lock else 401, LOCK_MESSAGE if lock else FAIL_MESSAGE)
            elif disabled_at is not None or emp.retired:        # 비밀번호가 맞아야 알려 준다
                fail = AuthError(403, "접근이 중지된 계정입니다. 관리자에게 문의하세요.")
            else:
                if _hasher.check_needs_rehash(pw_hash):
                    c.execute(text("UPDATE accounts SET password_hash = :h WHERE employee_id = :e"),
                              dict(h=hash_password(password), e=employee_id))
                token = secrets.token_urlsafe(32)
                c.execute(text("UPDATE accounts SET failed_count = 0, locked_until = NULL, last_login_at = :t"
                               " WHERE employee_id = :e"), dict(t=t, e=employee_id))
                c.execute(text("INSERT INTO auth_sessions (token_hash, employee_id, created_at, last_seen_at, expires_at, ip,"
                               " user_agent) VALUES (:h, :e, :t, :t, :x, :ip, :ua)"),
                          dict(h=_token_hash(token), e=employee_id, t=t, x=t + ABSOLUTE, ip=ip,
                               ua=(user_agent or "")[:255] or None))
        if fail is not None:
            raise fail
        return token, Me(emp.employee_id, emp.name, emp.email, emp.team, emp.grade, role, bool(must_change))

    def resolve(self, token: str | None) -> Me | None:
        """쿠키 토큰 → 지금 직원. 없음·만료·중지·퇴직이면 None(만료된 행은 지운다)"""
        if not token:
            return None
        t, h = now(), _token_hash(token)
        with self.engine.begin() as c:
            r = c.execute(text("SELECT s.employee_id, s.last_seen_at, s.expires_at, a.role, a.must_change_password, a.disabled_at"
                               " FROM auth_sessions s JOIN accounts a USING (employee_id) WHERE s.token_hash = :h"),
                          dict(h=h)).first()
            if r is None:
                return None
            employee_id, seen, expires, role, must_change, disabled_at = r
            if expires <= t or seen + IDLE <= t or disabled_at is not None:
                c.execute(text("DELETE FROM auth_sessions WHERE token_hash = :h"), dict(h=h))
                return None
            if t - seen >= TOUCH_EVERY:
                c.execute(text("UPDATE auth_sessions SET last_seen_at = :t WHERE token_hash = :h"), dict(t=t, h=h))
        emp = self.employee(employee_id)
        if emp is None or emp.retired:
            self.logout(token)
            return None
        return Me(emp.employee_id, emp.name, emp.email, emp.team, emp.grade, role, bool(must_change))

    def logout(self, token: str | None) -> None:
        if token:
            with self.engine.begin() as c:
                c.execute(text("DELETE FROM auth_sessions WHERE token_hash = :h"), dict(h=_token_hash(token)))

    def change_password(self, me: Me, token: str, current: str, new: str) -> None:
        """현재 비밀번호를 확인하고 바꾼다. 이 세션만 남기고 그 직원의 다른 세션을 모두 끊는다"""
        check_password_rule(new)
        if new == current:
            raise AuthError(422, "새 비밀번호가 지금 비밀번호와 같습니다.")
        with self.engine.begin() as c:
            pw_hash = c.execute(text("SELECT password_hash FROM accounts WHERE employee_id = :e FOR UPDATE"),
                                dict(e=me.employee_id)).scalar()
            if pw_hash is None or not _verify(pw_hash, current):
                raise AuthError(401, "지금 비밀번호가 올바르지 않습니다.")
            c.execute(text("UPDATE accounts SET password_hash = :h, must_change_password = FALSE, password_changed_at = :t"
                           " WHERE employee_id = :e"), dict(h=hash_password(new), t=now(), e=me.employee_id))
            c.execute(text("DELETE FROM auth_sessions WHERE employee_id = :e AND token_hash <> :h"),
                      dict(e=me.employee_id, h=_token_hash(token)))


def _verify(pw_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(pw_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
