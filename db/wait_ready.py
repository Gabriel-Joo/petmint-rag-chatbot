"""
wait_ready.py
앱보다 초기화 Job이 먼저 끝났는지 기다린다 — 앱 Pod의 initContainer가 부른다(앱과 같은 이미지·같은 계정).
준비됨 = petmint와 insurance_core의 마이그레이션 파일이 전부 적용됐고, 고객 원장이 비어 있지 않다.
앱 자신도 기동 때 같은 것을 보고 실패하지만, 그러면 Job이 도는 동안 CrashLoopBackOff가 쌓인다. 여기서 조용히 기다린다.

  python -m db.wait_ready [--timeout 600]
"""

import argparse
import sys
import time

import pymysql

from db.conn import app_settings
from db.migrate import MIGRATIONS


def missing() -> list[str]:
    """아직 안 된 것들(빈 목록이면 준비됨). 접속이 안 되는 것도 '안 됨'으로 센다"""
    out = []
    for app, prefix in (("petmint", "petmint"), ("insurance_core", "petmint_core")):
        want = sorted(p.name for p in (MIGRATIONS / app).glob("[0-9][0-9][0-9][0-9]_*.sql"))
        try:
            conn = pymysql.connect(**app_settings(prefix).pymysql_kwargs(), connect_timeout=5)
        except pymysql.MySQLError as e:
            return [f"{app}: 접속 안 됨({e.args[0]})"]
        try:
            with conn.cursor() as cur:
                try:
                    cur.execute("SELECT version FROM schema_migrations")
                    done = {r[0] for r in cur.fetchall()}
                except pymysql.MySQLError:
                    done = set()
                out += [f"{app}: {v}" for v in want if v not in done]
                if app == "insurance_core" and not out:
                    cur.execute("SELECT COUNT(*) FROM customers")
                    if cur.fetchone()[0] == 0:
                        out.append("insurance_core: 고객 원장 비어 있음(시드 전)")
        finally:
            conn.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--interval", type=int, default=5)
    args = ap.parse_args()
    deadline = time.monotonic() + args.timeout
    while True:
        left = missing()
        if not left:
            print("DB 준비됨")
            return
        if time.monotonic() > deadline:
            sys.exit(f"DB 준비 시간 초과({args.timeout}s): {left}")
        print("기다리는 중:", ", ".join(left), flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
