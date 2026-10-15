"""
main.py
09 UI FastAPI 앱. 리포 루트에서 띄운다: uvicorn app.main:app

lifespan: 고객 로드·검증(어긋나면 기동 실패) → MySQL 연결·스키마 확인(안 되면 기동 실패).
search-service 헬스체크·ContextBuilder는 검색을 붙일 때 넣는다.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app import config
from app.db import make_engine
from app.routers import articles, chat_ws, consultations, customers, feedback, sessions
from app.services.customers import CustomerStore
from app.services.llm import OllamaClient
from app.services.sessions import SessionStore
from app.services.turn_log import TurnLogStore

MIGRATIONS = config.ROOT / "db" / "migrations" / "petmint"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.customers = CustomerStore.load(config.CUSTOMERS_PATH)   # CustomerDataError → 기동 실패
    engine = make_engine(config.DB)
    with engine.connect() as c:                                       # 접속 실패·스키마가 코드보다 뒤처짐 → 기동 실패
        applied = {r[0] for r in c.execute(text("SELECT version FROM schema_migrations"))}
    missing = sorted(p.name for p in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql") if p.name not in applied)
    if missing:
        raise RuntimeError(f"{config.DB!r}에 적용되지 않은 마이그레이션: {missing} — python -m db.migrate")
    app.state.sessions = SessionStore(engine)
    app.state.turn_log = TurnLogStore(engine)
    app.state.llm = OllamaClient(config.OLLAMA_URL)
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="펫퍼민트 상담", lifespan=lifespan)
for r in (customers.router, consultations.router, sessions.router, articles.router, feedback.router, chat_ws.router):
    app.include_router(r)
