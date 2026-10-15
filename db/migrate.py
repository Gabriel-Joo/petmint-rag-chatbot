"""
migrate.py
db/migrations/{app}/NNNN_*.sql을 번호 순으로 한 번씩 적용한다. 적용 기록은 그 데이터베이스의 schema_migrations.
앱 계정으로 돈다(자기 데이터베이스에 DDL 권한이 있다). 배포 때는 초기화 Job이 같은 명령을 부른다.

  python -m db.migrate                       # petmint (petmint_app 계정)
  python -m db.migrate --app insurance_core  # 기간계 흉내 (insurance_seed 계정 — petmint_app은 SELECT만 있다)
  python -m db.migrate --status              # 적용 여부만

MySQL DDL은 트랜잭션으로 묶이지 않는다 — 파일 중간에서 실패하면 앞 문장은 이미 반영돼 있으니 손으로 정리하고 다시 돌린다.
"""

import argparse
import re
from pathlib import Path

import pymysql

from db.conn import app_settings

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
# 마이그레이션 폴더 → DDL 권한이 있는 계정의 환경변수 접두어(db/conn.py)
ACCOUNTS = {"petmint": "petmint", "insurance_core": "insurance_seed"}


def _statements(sql: str) -> list[str]:
    """'-- ' 주석을 지우고 ';'로 나눈다. 마이그레이션 SQL의 문자열 안에 '--'·';'를 쓰지 않는다는 전제"""
    body = "\n".join(re.sub(r"--\s.*$", "", line) for line in sql.splitlines())
    return [s.strip() for s in body.split(";") if s.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="petmint", choices=sorted(ACCOUNTS))
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    files = sorted(p for p in (MIGRATIONS / args.app).glob("*.sql") if re.match(r"\d{4}_", p.name))
    conn = pymysql.connect(**app_settings(ACCOUNTS[args.app]).pymysql_kwargs(), autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                        " version VARCHAR(255) NOT NULL PRIMARY KEY,"
                        " applied_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3))")
            cur.execute("SELECT version FROM schema_migrations")
            done = {r[0] for r in cur.fetchall()}
            for f in files:
                if f.name in done:
                    print(f"  적용됨  {f.name}")
                    continue
                if args.status:
                    print(f"  대기    {f.name}")
                    continue
                for stmt in _statements(f.read_text(encoding="utf-8")):
                    cur.execute(stmt)
                cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (f.name,))
                print(f"  적용    {f.name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
