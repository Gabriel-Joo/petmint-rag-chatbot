from fastapi import APIRouter, Depends, HTTPException

from app import deps
from app.schemas import FeedbackIn, FeedbackOut
from app.services.turn_log import TurnLogStore

router = APIRouter(prefix="/api/turns", tags=["feedback"])


@router.post("/{turn_id}/feedback", response_model=FeedbackOut)
def post_feedback(turn_id: str, body: FeedbackIn, log: TurnLogStore = Depends(deps.turn_log),
                  agent: str = Depends(deps.agent)):
    """feedback 테이블에 turn_id를 키로 남긴다(다시 누르면 덮어쓴다). 원본 턴 로그는 고치지 않는다(6-3).
    턴 로그는 done 전에 쓰므로 done을 받은 턴이면 있다. 남의 턴은 없는 턴과 같다"""
    if not log.save_feedback(turn_id, agent, body):
        raise HTTPException(404, f"턴 없음: {turn_id}")
    return FeedbackOut(turn_id=turn_id, accepted=True)
