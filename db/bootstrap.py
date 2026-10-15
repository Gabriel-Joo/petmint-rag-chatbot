"""
bootstrap.py
데이터베이스·계정 만들기(12번 1-3절) — root로 한 번 돌린다. 여러 번 돌려도 같은 결과(비밀번호는 환경변수 값으로 다시 맞춘다).

  petmint        ← petmint_app     (자기 데이터베이스 전체)
  runshoes       ← runshoes_app    (자리만 — 스키마 없음)
  insurance_core ← insurance_seed  (기간계 흉내. 적재·수정용 전체 권한)
  insurance_core ← petmint_app     SELECT만 — 챗봇은 고객 원장을 읽기만 한다

  MYSQL_ROOT_PASSWORD=... python -m db.bootstrap
"""

import os

import pymysql

from db.conn import env, root_settings

# 각자 자기 데이터베이스에 전체 권한. BOOTSTRAP_APPS로 고른다 — 클러스터의 petmint 초기화 Job은 runshoes 비밀번호를 갖지 않는다
# (Secret은 네임스페이스별, 12번 1-3절). runshoes는 자기 네임스페이스의 Job이 같은 명령으로 만든다
APPS = tuple(a.strip().upper() for a in os.environ.get("BOOTSTRAP_APPS", "PETMINT,RUNSHOES,INSURANCE_SEED").split(",")
             if a.strip())


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
            if "PETMINT" not in APPS:
                return conn.commit()
            # 챗봇이 고객 원장을 읽는 계정 — SELECT만. 쓰기 권한은 주지 않는다(남아 있으면 걷는다)
            core, reader = env("PETMINT_CORE_DB_NAME"), env("PETMINT_CORE_DB_USER")
            cur.execute("SELECT 1 FROM mysql.db WHERE Db = %s AND User = %s", (core, reader))
            if cur.fetchone():
                cur.execute(f"REVOKE ALL PRIVILEGES ON `{core}`.* FROM %s@'%%'", (reader,))
            cur.execute(f"GRANT SELECT ON `{core}`.* TO %s@'%%'", (reader,))
            print(f"{core} ← {reader} (SELECT)")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
