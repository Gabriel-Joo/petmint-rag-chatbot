from fastapi import APIRouter, Depends, Query

from app import deps
from app.schemas import RecentConsultation
from app.services.sessions import SessionStore

router = APIRouter(prefix="/api/consultations", tags=["consultations"])


@router.get("/recent", response_model=list[RecentConsultation])
def recent(limit: int = Query(50, ge=1, le=200), store: SessionStore = Depends(deps.sessions)):
    """고객 조회 '최근 상담' 탭 — 고객별 마지막 업무특화 상담 시각(종료 시각, 진행 중이면 시작 시각) 내림차순.
    상담원으로 거르지 않는다(09번 2-2절·7-1절): "아까 그 고객"을 다시 찾는 고객 단위 목록이고,
    다른 상담원이 받은 고객도 다시 전화할 수 있다"""
    return [RecentConsultation(customer_id=cid, last_consulted_at=at) for cid, at in store.recent_customers(limit)]
