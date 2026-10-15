"""
conn.py
MySQL 접속 정보 — 전부 환경변수(12번 1-2절). 개발은 리포 루트 .env, 배포는 K8s Secret이 같은 이름으로 넣는다.
기본값을 두지 않는다: 빠진 값이 있으면 어느 변수인지 밝히고 바로 실패한다.

  {APP}_DB_HOST / _PORT / _NAME / _USER / _PASSWORD    앱 계정(APP = PETMINT, RUNSHOES)
  MYSQL_HOST / MYSQL_PORT / MYSQL_ROOT_USER / MYSQL_ROOT_PASSWORD    bootstrap.py만 쓴다
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)      # 이미 있는 환경변수(Secret)가 이긴다


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"환경변수 {name}가 없다 — .env.example 참고")
    return v


@dataclass(frozen=True)
class DbSettings:
    host: str
    port: int
    user: str
    password: str
    database: str | None

    def __repr__(self) -> str:                  # 로그·예외에 비밀번호가 찍히지 않게
        return f"DbSettings({self.user}@{self.host}:{self.port}/{self.database})"

    def pymysql_kwargs(self) -> dict:
        return dict(host=self.host, port=self.port, user=self.user, password=self.password,
                    database=self.database, charset="utf8mb4", init_command="SET time_zone = '+00:00'")


def app_settings(app: str) -> DbSettings:
    p = app.upper()
    return DbSettings(env(f"{p}_DB_HOST"), int(env(f"{p}_DB_PORT")), env(f"{p}_DB_USER"),
                      env(f"{p}_DB_PASSWORD"), env(f"{p}_DB_NAME"))


def root_settings() -> DbSettings:
    return DbSettings(env("MYSQL_HOST"), int(env("MYSQL_PORT")), os.environ.get("MYSQL_ROOT_USER") or "root",
                      env("MYSQL_ROOT_PASSWORD"), None)
