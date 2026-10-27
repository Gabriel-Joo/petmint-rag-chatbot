"""
main.py
09 UI FastAPI 앱. 리포 루트에서 띄운다: uvicorn app.main:app

lifespan: 약관 청크·그래프 로드(없으면 기동 실패) → 고객 원장(insurance_core) 검증 → ContextBuilder(Milvus)
→ MySQL(petmint) 연결·스키마 확인.
어느 하나라도 안 되면 기동하지 않는다.
web/dist가 있으면 / 에서 React 빌드물을 같이 서빙한다 — 컨테이너 하나로 배포한다.
search-service에 닿는지는 기동 때 보지 않는다(Retriever.health는 있다). search-service는 청크 top-k만 돌려주고 발췌 조립은 여기서 만든 ContextBuilder가 한다.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymilvus import MilvusClient
from sqlalchemy import text

from data.rag_context import ContextBuilder

from app import config, deps
from app.db import make_engine
from app.routers import articles, auth, chat_ws, consultations, customers, feedback, me, sessions
from app.services import policy_data
from app.services.auth import AuthStore
from app.services.hr_personal import EmployeeStore
from app.services.customers import USER_MESSAGE, CustomerDataError, CustomerStore
from app.services.llm import OllamaClient
from app.services.retrieval import Retriever
from app.services.sessions import SessionStore
from app.services.turn_log import TurnLogStore

MIGRATIONS = config.ROOT / "db" / "migrations" / "petmint"


@asynccontextmanager
async def lifespan(app: FastAPI):
    chunks, graphs = policy_data.load()                               # PolicyDataError → 기동 실패
    core = make_engine(config.CORE_DB)                                # 고객 원장(기간계) — SELECT만
    app.state.customers = CustomerStore.load(core, chunks)            # 접속 실패·CustomerDataError → 기동 실패
    # 조항 원문·참조 조문. 청크·그래프는 위에서 읽은 것을 넘긴다(rag_context 기본 경로를 쓰지 않는다)
    app.state.builder = ContextBuilder(client=MilvusClient(uri=config.MILVUS_URL), chunks=chunks, graphs=graphs)
    engine = make_engine(config.DB)
    with engine.connect() as c:                                       # 접속 실패·스키마가 코드보다 뒤처짐 → 기동 실패
        applied = {r[0] for r in c.execute(text("SELECT version FROM schema_migrations"))}
    missing = sorted(p.name for p in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql") if p.name not in applied)
    if missing:
        raise RuntimeError(f"{config.DB!r}에 적용되지 않은 마이그레이션: {missing} — python -m db.migrate")
    app.state.sessions = SessionStore(engine)
    app.state.auth = AuthStore(engine, core)
    app.state.employees = EmployeeStore(core)                         # 사내규정 개인화(PETMINT_HR_PERSONAL) — 인사 원장, SELECT만                          # 로그인(PETMINT_AUTH=app). access 모드도 /api/auth/me가 쓴다
    app.state.turn_log = TurnLogStore(engine)
    app.state.llm = OllamaClient(config.OLLAMA_URL)
    # 검색(GPU)은 호스트 search-service. 기동 때 닿는지 보지 않는다 — 아직 배포 전이고, 없으면 턴이 search_unavailable로 끝난다
    app.state.retriever = Retriever(config.SEARCH_SERVICE_URL, expand=config.SEARCH_EXPAND, variant=config.SEARCH_VARIANT, pool_k=config.SEARCH_POOL,
                      expand_dict=config.SEARCH_EXPAND_DICT)
    try:
        yield
    finally:
        engine.dispose()
        core.dispose()


app = FastAPI(title="펫퍼민트 상담", lifespan=lifespan)
log = logging.getLogger("app.customers")


@app.exception_handler(CustomerDataError)
async def customer_data_error(request: Request, e: CustomerDataError):
    """원장이 깨졌다 → 500. 상담원에게는 문의 안내만, 어긋난 고객·값은 서버 로그에"""
    log.error("고객 원장 오류 (%s %s)\n%s", request.method, request.url.path, e)
    return JSONResponse(status_code=500, content={"detail": USER_MESSAGE})


@app.middleware("http")
async def check_origin(request: Request, call_next):
    """쿠키 인증(PETMINT_AUTH=app)의 CSRF 방지 — 상태를 바꾸는 /api 요청은 Origin이 허용 목록이거나 같은 Host여야 한다"""
    if (config.AUTH == "app" and request.url.path.startswith("/api/")
            and request.method not in ("GET", "HEAD", "OPTIONS") and not deps.origin_ok(request)):
        return JSONResponse(status_code=403, content={"detail": "허용되지 않은 출처의 요청입니다."})
    return await call_next(request)


app.include_router(auth.router)
# 보호 라우터 — access 모드에서 require_login은 아무것도 하지 않는다. WS는 핸들러가 직접 확인한다(4401)
for r in (customers.router, consultations.router, sessions.router, articles.router, feedback.router, me.router):
    app.include_router(r, dependencies=[Depends(deps.require_login)])
app.include_router(chat_ws.router)

# React 빌드물 — /api·/ws 라우트 뒤에 붙여 그쪽이 먼저 잡히게 한다. 빌드물이 없으면(개발 중 vite로 띄울 때) 붙이지 않는다
if (config.WEB_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=config.WEB_DIST, html=True), name="web")
