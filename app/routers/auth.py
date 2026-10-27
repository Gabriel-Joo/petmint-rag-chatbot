"""
auth.py
/api/auth — 앱 자체 로그인(2026-10-28, 13번 2-1절). PETMINT_AUTH=app일 때만 로그인·로그아웃·비밀번호 변경이 동작한다.
/api/auth/me는 두 모드 모두 답한다 — 프런트는 auth_mode를 보고 로그인 화면을 띄울지 정한다.
이 라우터는 require_login을 걸지 않는다(로그인 전에 불러야 한다). 상태를 바꾸는 요청은 main의 Origin 검사를 거친다.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app import config, deps
from app.schemas import LoginIn, MeOut, PasswordIn
from app.services.auth import ABSOLUTE, AuthError, AuthStore, Me

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _out(me: Me) -> MeOut:
    return MeOut(auth_mode="app", email=me.email, employee_id=me.employee_id, name=me.name, team=me.team, grade=me.grade,
                 role=me.role, must_change_password=me.must_change_password)


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
        token, found = store.login(body.employee_id.strip(), body.password,
                                   request.client.host if request.client else None, request.headers.get("user-agent"))
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
