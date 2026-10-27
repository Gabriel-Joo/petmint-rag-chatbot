"""
me.py
/api/me — 로그인한 상담원 본인(2026-10-28). 사내규정 화면 위의 본인 정보 블록(업무특화 고객 블록과 같은 자리·모양).
인사 원장(insurance_core, 읽기만)에 없는 상담원(access 모드의 dev@local·헤더 없음)은 404 — 블록을 띄우지 않는다.
급여·평균임금·수당 금액·평가는 싣지 않는다 — 옆에서 볼 수 있다. 물을 때만 답에 나온다(hr_personal).
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app import deps
from app.schemas import EmployeeProfile
from app.services import hr_personal, payout

router = APIRouter(prefix="/api/me", tags=["me"])


def employees(request: Request) -> hr_personal.EmployeeStore:
    return request.app.state.employees


@router.get("/profile", response_model=EmployeeProfile)
def profile(agent: str = Depends(deps.agent), store: hr_personal.EmployeeStore = Depends(employees)):
    f = store.load(agent)
    if f is None or (f.retired_on is not None and f.retired_on <= payout.today()):
        raise HTTPException(404, "인사 원장에 없는 상담원")
    return EmployeeProfile(**hr_personal.profile(f, payout.today()))
