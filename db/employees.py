"""
employees.py
앱 로그인 계정 관리(2026-10-28, 13번 2-1절) — 관리 화면이 아직 없어서 명령으로 한다. 직원 자체는 기간계(insurance_core.employees)에
있어야 한다. 이 명령은 앱 쪽 계정(petmint.accounts)만 만든다.
비밀번호는 명령줄에 쓰지 않는다 — 화면에 안 보이게 두 번 묻는다(getpass). 파이프로 넣을 때만 --password-stdin.

  python -m db.employees list
  python -m db.employees add E2001003 [--role 관리자]     # 임시 비밀번호를 묻는다 → 첫 로그인 때 바꾸게 한다
  python -m db.employees reset E2018032                   # 임시 비밀번호 재발급 · 잠금 해제 · 로그인 세션 모두 끊기
  python -m db.employees disable E2018032 | enable E2018032
"""

import argparse
import getpass
import sys

from sqlalchemy import text

from app.db import make_engine, now
from app.services.auth import AuthError, check_password_rule, hash_password
from db.conn import app_settings


def ask_password(from_stdin: bool) -> str:
    if from_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    else:
        pw = getpass.getpass("임시 비밀번호: ")
        if getpass.getpass("한 번 더: ") != pw:
            raise SystemExit("두 번 입력한 비밀번호가 다르다")
    try:
        check_password_rule(pw)
    except AuthError as e:
        raise SystemExit(e.message)
    return pw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["list", "add", "reset", "disable", "enable"])
    ap.add_argument("employee_id", nargs="?")
    ap.add_argument("--role", choices=["상담원", "관리자"], default="상담원")
    ap.add_argument("--password-stdin", action="store_true")
    a = ap.parse_args()
    app, core = make_engine(app_settings("petmint")), make_engine(app_settings("petmint_core"))
    with core.connect() as c:
        staff = {r[0]: r for r in c.execute(text("SELECT employee_id, name, team, grade, retired_on FROM employees"))}
    if a.command == "list":
        with app.connect() as c:
            acc = {r[0]: r for r in c.execute(text("SELECT employee_id, role, password_hash IS NOT NULL, must_change_password,"
                                                   " locked_until, disabled_at, last_login_at FROM accounts"))}
        for eid, (_, name, team, grade, retired) in sorted(staff.items()):
            r = acc.get(eid)
            state = ("계정 없음" if r is None else
                     f"{r[1]} · {'비번 있음' if r[2] else '비번 없음'}{' · 변경 필요' if r[3] else ''}"
                     f"{' · 잠김' if r[4] and r[4] > now() else ''}{' · 중지' if r[5] else ''}"
                     f" · 최근 로그인 {r[6] or '-'}")
            print(f"{eid}  {name}  {team or '-'}  {grade}{'  (퇴직 ' + str(retired) + ')' if retired else ''}  |  {state}")
        return
    if not a.employee_id:
        raise SystemExit("사번을 적는다")
    if a.employee_id not in staff:
        raise SystemExit(f"기간계에 없는 사번: {a.employee_id}")
    t = now()
    with app.begin() as c:
        exists = c.execute(text("SELECT 1 FROM accounts WHERE employee_id = :e"), dict(e=a.employee_id)).first()
        if a.command == "add":
            if exists:
                raise SystemExit("이미 계정이 있다 — reset을 쓴다")
            c.execute(text("INSERT INTO accounts (employee_id, role, password_hash, must_change_password, created_at)"
                           " VALUES (:e, :r, :h, TRUE, :t)"),
                      dict(e=a.employee_id, r=a.role, h=hash_password(ask_password(a.password_stdin)), t=t))
        elif not exists:
            raise SystemExit("계정이 없다 — add를 먼저")
        elif a.command == "reset":
            c.execute(text("UPDATE accounts SET password_hash = :h, must_change_password = TRUE, failed_count = 0,"
                           " locked_until = NULL WHERE employee_id = :e"),
                      dict(h=hash_password(ask_password(a.password_stdin)), e=a.employee_id))
            c.execute(text("DELETE FROM auth_sessions WHERE employee_id = :e"), dict(e=a.employee_id))
        elif a.command == "disable":
            c.execute(text("UPDATE accounts SET disabled_at = :t WHERE employee_id = :e"), dict(t=t, e=a.employee_id))
            c.execute(text("DELETE FROM auth_sessions WHERE employee_id = :e"), dict(e=a.employee_id))
        elif a.command == "enable":
            c.execute(text("UPDATE accounts SET disabled_at = NULL WHERE employee_id = :e"), dict(e=a.employee_id))
    print(f"{a.command} {a.employee_id} {staff[a.employee_id][1]} — 완료")


if __name__ == "__main__":
    main()
