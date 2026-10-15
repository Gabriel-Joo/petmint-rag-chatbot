"""
bootstrap.py
데이터베이스·계정 만들기(12번 1-3절) — root로 한 번 돌린다. 여러 번 돌려도 같은 결과(비밀번호는 환경변수 값으로 다시 맞춘다).

  petmint  ← petmint_app   (자기 데이터베이스만)
  runshoes ← runshoes_app  (자리만 — 스키마 없음)

  MYSQL_ROOT_PASSWORD=... python -m db.bootstrap
"""

import pymysql

from db.conn import env, root_settings

APPS = ("PETMINT", "RUNSHOES")


def main() -> None:
    conn = pymysql.connect(**root_settings().pymysql_kwargs())
    try:
        with conn.cursor() as cur:
            for app in APPS:
                name, user, password = env(f"{app}_DB_NAME"), env(f"{app}_DB_USER"), env(f"{app}_DB_PASSWORD")
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` "
                            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
                # 앱은 도커 브리지(개발)·Pod 네트워크(배포)에서 붙으므로 호스트를 '%'로 둔다
                cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (user, password))
                cur.execute("ALTER USER %s@'%%' IDENTIFIED BY %s", (user, password))
                cur.execute(f"GRANT ALL PRIVILEGES ON `{name}`.* TO %s@'%%'", (user,))
                print(f"{name} ← {user}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
