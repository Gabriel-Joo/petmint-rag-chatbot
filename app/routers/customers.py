from fastapi import APIRouter, Depends, HTTPException, Query

from app import deps
from app.schemas import Customer, CustomerSessionSummary
from app.services.customers import CustomerStore
from app.services.sessions import SessionStore

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("", response_model=list[Customer])
def list_customers(store: CustomerStore = Depends(deps.customers)):
    return store.all()


@router.get("/{customer_id}", response_model=Customer)
def get_customer(customer_id: str, store: CustomerStore = Depends(deps.customers)):
    c = store.get(customer_id)
    if c is None:
        raise HTTPException(404, f"고객 없음: {customer_id}")
    return c


@router.get("/{customer_id}/sessions", response_model=list[CustomerSessionSummary])
def customer_sessions(customer_id: str, limit: int = Query(50, ge=1, le=200),
                      store: CustomerStore = Depends(deps.customers), sessions: SessionStore = Depends(deps.sessions)):
    """그 고객의 과거 상담(09번 2-2절) — started_at 역순, 담당 상담원과 무관하게. 열기는 GET /api/sessions/{id}(읽기 전용)"""
    if store.get(customer_id) is None:
        raise HTTPException(404, f"고객 없음: {customer_id}")
    return [CustomerSessionSummary(session_id=s.session_id, mode=s.mode, title=s.title, agent_email=s.agent_email,
                                   started_at=s.started_at, ended_at=s.ended_at)
            for s in sessions.customer_sessions(customer_id, limit)]
