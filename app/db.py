"""
db.py
MySQL 연결 풀(SQLAlchemy Core + PyMySQL). 쿼리는 text()로 직접 쓴다 — ORM을 들이지 않는다.

- 동기 엔진이다. REST 핸들러는 def라 스레드풀에서 돌고, WS(async)는 asyncio.to_thread로 부른다.
- 시각은 UTC로 저장·조회한다(접속마다 time_zone='+00:00'). 읽은 naive datetime은 utc()로 tz를 붙인다.
"""

from datetime import datetime, timezone

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL

from db.conn import DbSettings


def make_engine(s: DbSettings) -> Engine:
    url = URL.create("mysql+pymysql", username=s.user, password=s.password, host=s.host, port=s.port,
                     database=s.database, query={"charset": "utf8mb4"})
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600,
                         connect_args={"init_command": "SET time_zone = '+00:00'"})


def now() -> datetime:
    """DB에 넣는 시각 — UTC naive(DATETIME 칼럼은 tz를 담지 않는다)"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None else None
