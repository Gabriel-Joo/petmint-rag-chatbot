"""
auth.py
/api/auth — 앱 자체 로그인(2026-10-28, 13번 2-1절). PETMINT_AUTH=app일 때만 로그인·로그아웃·비밀번호 변경이 동작한다.
/api/auth/me는 두 모드 모두 답한다 — 프런트는 auth_mode를 보고 로그인 화면을 띄울지 정한다.
이 라우터는 require_login을 걸지 않는다(로그인 전에 불러야 한다). 상태를 바꾸는 요청은 main의 Origin 검사를 거친다.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app import config, deps
from app.schemas import DemoAccountOut, DemoLoginIn, LoginIn, MeOut, PasswordIn
from app.services import demo, payout
from app.services.auth import ABSOLUTE, AuthError, AuthStore, Me

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _out(me: Me) -> MeOut:
    return MeOut(auth_mode="app", email=me.email, employee_id=me.employee_id, name=me.name, team=me.team, grade=me.grade,
                 role=me.role, must_change_password=me.must_change_password, is_demo=me.demo)


def _app_only() -> None:
    if config.AUTH != "app":
        raise HTTPException(404, "앱 로그인이 꺼져 있다(PETMINT_AUTH=access)")


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(config.AUTH_COOKIE, token, max_age=int(ABSOLUTE.total_seconds()), path="/", httponly=True,
                        secure=config.COOKIE_SECURE, samesite="lax")


@router.get("/me", response_model=MeOut)
def me(request: Request, store: AuthStore = Depends(deps.auth)):
    if config.AUTH != "app":
        email = deps.header_agent(request)
        e = store.employee_by_email(email)
        return MeOut(auth_mode="access", email=email, employee_id=e and e.employee_id, name=e and e.name,
                     team=e and e.team, grade=e and e.grade)
    found = deps.session_me(request)
    if found is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return _out(found)


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, store: AuthStore = Depends(deps.auth)):
    _app_only()
    store.logout(request.cookies.get(config.AUTH_COOKIE))        # 이전 세션이 있으면 버린다(세션 고정 방지)
    try:
        token, found = store.login(body.employee_id.strip(), body.password, deps.client_ip(request),
                                   request.headers.get("user-agent"))
    except AuthError as e:
        raise HTTPException(e.status, e.message)
    _set_cookie(response, token)
    return _out(found)


def _demo_on() -> None:
    if config.AUTH != "app" or not config.DEMO_LOGIN:
        raise HTTPException(404, "체험 로그인이 꺼져 있다(PETMINT_DEMO_LOGIN)")


@router.get("/demo-accounts", response_model=list[DemoAccountOut])
def demo_accounts(request: Request, store: AuthStore = Depends(deps.auth)):
    """체험 카드 — 퇴직 · 중지 아닌 가상 직원 전부. 꺼져 있으면 404(화면이 체험 영역을 그리지 않는다)"""
    _demo_on()
    employees = request.app.state.employees
    today = payout.today()
    return [demo.card(emp, role, employees.load(emp.email), today) for emp, role in store.demo_pool()]


@router.post("/demo", response_model=MeOut)
def demo_login(body: DemoLoginIn, request: Request, response: Response, store: AuthStore = Depends(deps.auth)):
    """체험 로그인 — 비밀번호 없이 그 직원으로. 풀 밖 400, 같은 IP 15분 PETMINT_DEMO_LOGIN_PER_IP번 넘으면 429"""
    _demo_on()
    store.logout(request.cookies.get(config.AUTH_COOKIE))        # 이전 세션이 있으면 버린다(세션 고정 방지)
    try:
        token, found = store.demo_login(body.employee_id.strip(), deps.client_ip(request), request.headers.get("user-agent"))
    except AuthError as e:
        raise HTTPException(e.status, e.message)
    _set_cookie(response, token)
    return _out(found)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, store: AuthStore = Depends(deps.auth)):
    _app_only()
    store.logout(request.cookies.get(config.AUTH_COOKIE))
    response.delete_cookie(config.AUTH_COOKIE, path="/", httponly=True, secure=config.COOKIE_SECURE, samesite="lax")


@router.post("/password", status_code=204)
def change_password(body: PasswordIn, request: Request, store: AuthStore = Depends(deps.auth)):
    _app_only()
    token = request.cookies.get(config.AUTH_COOKIE)
    found = store.resolve(token)
    if found is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    try:
        store.change_password(found, token, body.current, body.new)
    except AuthError as e:
        raise HTTPException(e.status, e.message)
