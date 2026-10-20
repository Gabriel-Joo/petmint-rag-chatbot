"""
context.py
멀티턴(09번 5절) — 후속 질문(followup.follow_up_reason)을 앞 대화로 푼다. 모드마다 다르다:

- 일반: 최근 3턴(질문·답변)을 대화 이력으로 그대로 넘긴다. 베이스 모델이고 검색이 없다
- 사내규정: 베이스 모델이 앞 기준 질문 + 후속 → 독립 질문으로 재작성한다. 답변도 베이스 모델이라 모델 교체가 없다
  (올라가 있으면 0.1~0.4초). 재작성이 실패하면 업무특화처럼 이어 붙인다
- 업무특화: LLM을 쓰지 않는다 — 베이스로 재작성하면 파인튜닝 모델과 GPU를 번갈아 써 후속 턴마다 약 5초 늦어진다.
  앞 기준 질문 + 후속을 이어 붙여 검색하고, 답변 모델에도 기준 질문 + 후속을 넘긴다(금액만 말한 후속은 후속만 — generation_question)

기준 질문(anchor): 단독 질문은 질문 자체, 후속은 앞 턴의 기준 질문. 후속에 통원/입원·등급·유형이 새로 나오면 기준 질문 속
같은 종류 낱말을 갈아 끼운다 — "고급형 통원 하루 한도는?" → "그럼 입원은요?" → "수술하면요?"에서 셋째 턴 검색어가
"고급형 입원 하루 한도는? 수술하면요?"가 된다(원래 질문과만 붙이면 '입원'이 사라졌다). 연쇄는 늘 기준 질문에 붙인다.

2026-10-21 측정(data/review/multiturn_design_20261021.md): 이어 붙인 검색이 이상적 재작성과 같은 조항을 가져왔다.
답변 모델에 넘길 질문은 10회씩 다섯 사례로 정했다(generation_question).
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field

from app import config
from app.schemas import ContextKind, ContextMsg, Mode, Pet
from app.services import payout
from app.services.followup import follow_up_reason
from app.services.llm import OllamaClient
from app.services.turn_log import PriorTurn

log = logging.getLogger(__name__)

HISTORY_TURNS = 3            # 일반 — 넘길 이력 턴 수
REWRITE_TIMEOUT_SEC = 10
# 갈아 끼울 낱말 종류 — 한 종류에서 후속이 하나만 말하면 기준 질문의 다른 값을 그것으로 바꾼다
SLOTS = (("통원", "입원"), ("고급형", "기본형", "실속형"), ("Ⅰ", "Ⅱ", "Ⅲ"))

_REWRITE_PROMPT = (
    "마지막 질문이 앞 대화를 봐야 뜻이 통하면, 앞 대화에 나온 낱말로 빠진 부분만 채워 혼자서 이해되는 질문으로 고쳐 써라. "
    "마지막 질문이 이미 혼자서 이해되면 한 글자도 바꾸지 말고 그대로 써라. 답하지 말고 질문 한 줄만 써라.\n\n"
    "예1\n앞 질문: 연차는 며칠 나와요?\n마지막 질문: 그럼 반차는요?\n고쳐 쓴 질문: 반차는 며칠 나와요?\n\n"
    "예2\n앞 질문: 경조휴가는 며칠이에요?\n마지막 질문: 신청은 언제까지 해요?\n고쳐 쓴 질문: 경조휴가 신청은 언제까지 해요?\n\n"
    "앞 질문: {anchor}\n마지막 질문: {question}\n고쳐 쓴 질문:")


@dataclass
class Resolved:
    """한 턴을 앞 대화로 푼 결과. follow_up이 None이면 단독 질문 — 나머지는 질문 그대로"""
    question: str                                  # 상담원이 쓴 질문
    follow_up: str | None = None
    kind: ContextKind | None = None
    anchor: str | None = None                      # 기준 질문 — turns.rewritten_question. 단독이면 None(질문 자체가 기준)
    search_query: str | None = None                # 검색에 쓸 문장(사내규정·업무특화)
    history: list[dict] = field(default_factory=list)   # 일반 — chat 메시지 이력
    chosen: str | None = None                      # 업무특화 — 앞 턴에서 이어 쓰는 특약(되묻기 생략)
    after_amount_ask: bool = False                 # 업무특화 — 앞 턴이 금액 되묻기였고 이번에 금액을 말했다(모델 대신 카드로 답)

    @property
    def retrieval_query(self) -> str:
        return self.search_query or self.question

    @property
    def generation_question(self) -> str:
        """답변 모델에 넘길 질문.
        rewrite(사내규정): 재작성된 질문 / concat(업무특화): 기준 질문 + 후속, 단 금액만 말한 후속은 후속만 / 그 밖: 그대로.
        2026-10-21 업무특화 모델 10회씩 다섯 사례: "그럼 입원은요?"는 후속만이면 0/10(전부 거절), 기준+후속이면 10/10.
        "치료비는 35만원 나왔어요"는 반대로 기준+후속이면 10/10 거절, 후속만이면 답한다(금액은 계산 카드가 맞다)"""
        if self.kind == "rewrite" and self.anchor:
            return self.anchor
        if self.kind == "concat" and self.anchor and self.follow_up != "금액만":
            return f"{self.anchor} {self.question}"
        return self.question

    @property
    def card_text(self) -> str:
        """계산 카드가 읽을 문장 — 업무특화 후속은 기준 질문까지(금액·통원/입원이 앞 질문에 있을 수 있다)"""
        return self.search_query if self.kind == "concat" and self.search_query else self.question

    def message(self, turn_id: str) -> ContextMsg | None:
        if self.kind is None:
            return None
        return ContextMsg(turn_id=turn_id, kind=self.kind, reason=self.follow_up or "",
                          text=None if self.kind == "history" else self.anchor,
                          turns=len(self.history) // 2 if self.kind == "history" else None)


def override(anchor: str, question: str) -> str:
    """후속에 새로 나온 통원/입원·등급·유형으로 기준 질문 속 같은 종류 낱말을 갈아 끼운다"""
    for values in SLOTS:
        said = [v for v in values if v in question]
        if len(said) != 1:
            continue
        for old in values:
            if old != said[0]:
                anchor = anchor.replace(old, said[0])
    return anchor


def carry_chosen(prior: PriorTurn | None, question: str, pet: Pet | None) -> str | None:
    """앞 턴에서 고른 특약을 이어 쓴다. 후속이 '통원'/'입원'을 새로 말하면 그쪽 가입 특약으로 바꾼다"""
    if prior is None or prior.chosen_section is None or pet is None:
        return None
    for word in ("통원", "입원"):
        if word in question and word not in prior.chosen_section:
            other = [p.section_name for p in pet.policies if word in p.section_name and p.coverage_type]
            return other[0] if len(other) == 1 else None
    return prior.chosen_section


async def resolve(mode: Mode, question: str, prior: list[PriorTurn], pet: Pet | None,
                  llm: OllamaClient | None) -> Resolved:
    """prior: 같은 세션의 정상 완료 턴(오래된 순). 후속이 아니거나 앞 턴이 없으면 질문 그대로"""
    r = Resolved(question=question)
    if not prior:
        return r
    last = prior[-1]
    # 금액 되묻기("치료비가 얼마인가요?") 바로 뒤에 금액을 말했으면 후속 규칙에 안 걸려도 후속이다
    # ("35만원 정도 나왔고 수술은 안 했어요"처럼 길거나 물음표가 있어도)
    answered_ask = mode == "업무특화" and last.answer == payout.ASK_AMOUNT_TEXT and bool(payout.amounts_in(question))
    reason = follow_up_reason(question) or ("되묻기 답" if answered_ask else None)
    if reason is None:
        return r
    if mode == "일반":
        r.follow_up, r.kind = reason, "history"
        for t in prior[-HISTORY_TURNS:]:
            r.history += [{"role": "user", "content": t.question}, {"role": "assistant", "content": t.answer}]
        return r
    if mode == "업무특화":
        if pet is None or last.pet_id != pet.pet_id:      # 반려동물을 바꿨다 — 앞 턴은 다른 반려동물 이야기
            return r
        r.follow_up, r.kind = reason, "concat"
        r.anchor = override(last.anchor, question)
        r.search_query = f"{r.anchor} {question}"
        r.chosen = carry_chosen(last, question, pet)
        r.after_amount_ask = answered_ask
        return r
    # 사내규정 — 베이스 모델 재작성, 실패하면 이어 붙이기
    r.follow_up = reason
    rewritten = await rewrite(last.anchor, question, llm)
    if rewritten:
        r.kind, r.anchor, r.search_query = "rewrite", rewritten, rewritten
    else:
        r.kind, r.anchor = "concat", last.anchor
        r.search_query = f"{last.anchor} {question}"
    return r


async def rewrite(anchor: str, question: str, llm: OllamaClient | None) -> str | None:
    """베이스 모델 재작성 — 한 줄, 실패·빈 답·지나치게 긴 답이면 None"""
    if llm is None:
        return None
    try:
        raw = await asyncio.wait_for(
            llm.complete(config.BASE_MODEL, [{"role": "user", "content": _REWRITE_PROMPT.format(anchor=anchor, question=question)}],
                         options={"temperature": 0, "num_predict": 64}),
            timeout=REWRITE_TIMEOUT_SEC)
    except Exception:
        log.warning("질문 재작성 실패 — 이어 붙이기로 대신한다", exc_info=True)
        return None
    line = next((l for l in raw.strip().splitlines() if l.strip()), "")
    line = re.sub(r"^(고쳐\s*쓴\s*질문|질문)\s*[:：]\s*", "", line.strip()).strip(" \"'“”")
    if not line or len(line) > 4 * max(len(anchor), len(question)):
        return None
    return line
