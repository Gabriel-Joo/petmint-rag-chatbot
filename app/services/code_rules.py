"""
code_rules.py
업무특화 코드 답 규칙 등록부(2026-10-28, docs/16 4절 A안) — 순서·조건·플래그를 한 곳에. answer._generate가 이 목록을 위에서부터 돌고,
처음 답을 낸 규칙이 답한다(모델을 부르지 않는다). 예전에는 _generate 안에 블록 열세 개로 적혀 있었다 — 순서·인자·ask는 그대로 옮겼다.

- 규칙 하나 = (key, 이름, 켜졌는가, 부르기). 부르기는 Outcome(card, text, ask) 또는 None
- ask=True면 되물은 턴(turns.clarified) — 금액 되묻기·병명 되묻기·카드의 날짜별 금액 칸
- 사내규정 개인화(hr_personal)는 검색 전에 answer._hr_personal이 따로 돈다 — HR_TOPICS에 이름만 적는다
- 트리거 낱말은 lexicon.py, 각 규칙의 범위·측정은 docs/16_code_answers.md
"""

from collections.abc import Callable
from dataclasses import dataclass

from app import config
from app.services import customer_facts, name_check, named_cover, payout


@dataclass(frozen=True)
class Outcome:
    card: object | None
    text: str
    ask: bool


@dataclass(frozen=True)
class Inputs:
    """규칙이 보는 것 — 지금 질문(question), 후속이면 앞 질문까지 이은 글(card), 반려동물, 멀티턴 풀이(resolved), 검색 결과, 고른 특약"""
    mode: str
    question: str
    card: str
    pet: object | None
    resolved: object
    results: list[dict]
    chosen: str | None
    embed: Callable | None


@dataclass(frozen=True)
class Rule:
    key: str
    title: str
    enabled: Callable[[Inputs], bool]
    call: Callable[[Inputs], Outcome | None]
    threaded: bool = False          # 임베딩 HTTP를 부른다 — asyncio.to_thread로


def _card_text(out, ask=True):
    return None if out is None else Outcome(out[0], out[1], ask)


def _text(text, ask=False):
    return None if text is None else Outcome(None, text, ask)


def _card(card, answer, ask=False):
    return None if card is None else Outcome(card, answer(card), ask)


_FACTS = lambda i: config.CUSTOMER_FACTS


def _cover_switch(i: "Inputs") -> bool:
    """금액 되묻기 바로 뒤에 금액 대신 병명 보장을 물었다("감기도 돼요?") — 앞 질문의 '얼마'로 금액 되묻기를 되풀이하지 않는다(NAMED_COVER)"""
    return (config.NAMED_COVER and i.mode == "업무특화" and bool(i.resolved.follow_up) and i.resolved.prior_answer in payout.ASKS
            and named_cover.fires(i.question, None, i.pet) is not None)
_BIZ = lambda flag: (lambda i: i.mode == "업무특화" and getattr(config, flag) and config.CUSTOMER_FACTS)

RULES: list[Rule] = [
    Rule("reply_turn", "되묻기 답 이어받기", lambda i: bool(i.resolved.after_amount_ask),
         lambda i: _card_text(payout.reply_turn(i.question, i.card, i.resolved.reply_stage, i.resolved.prior_calc, i.pet, i.results,
                                                i.chosen))),
    Rule("not_enrolled", "미가입 특약", _FACTS, lambda i: _text(customer_facts.not_enrolled(i.card, i.pet))),
    Rule("annual", "올해 받은·남은", _FACTS, lambda i: _text(customer_facts.annual_answer(i.card, i.pet))),
    Rule("needs_amount", "금액 되묻기", lambda i: not _cover_switch(i),
         lambda i: (Outcome(None, payout.ask_text(i.card, i.pet, i.chosen), True)
                    if payout.needs_amount(i.card, i.pet, i.embed) else None), threaded=True),
    Rule("hypothetical", "가정 등급 한도표", _FACTS,
         lambda i: _card(payout.hypothetical_card(i.card, i.pet), lambda c: payout.limit_answer(c, i.pet, i.card))),
    Rule("legal", "법률비용 카드", lambda i: True, lambda i: _card(payout.legal_card(i.card, i.pet), payout.legal_answer)),
    Rule("question_turn", "치료비 질문 카드", lambda i: True,
         lambda i: _card_text(payout.question_turn(i.card, i.pet, i.results, i.chosen))),
    Rule("limit", "한도표", lambda i: True,
         lambda i: _card(payout.limit_card(i.card, i.pet, i.chosen), lambda c: payout.limit_answer(c, i.pet, i.card))),
    Rule("age", "가입 나이", _BIZ("AGE_CODE"), lambda i: _text(customer_facts.enrollment_age_answer(i.card, i.pet))),
    Rule("exclusion", "부담보", _BIZ("COVERAGE_CODE"), lambda i: _text(customer_facts.exclusion_answer(i.card, i.pet))),
    Rule("proviso", "면책 단서", _BIZ("PROVISO_CODE"), lambda i: _text(customer_facts.proviso_answer(i.question, i.card, i.pet))),
    Rule("named_cover", "병명 보장 대조", _BIZ("NAMED_COVER"),
         lambda i: _text(named_cover.answer(i.question, i.card, i.resolved.prior_answer, i.pet, customer_facts.notes))),
    Rule("injury_followup", "상해 후속", _BIZ("ASK_DISEASE"),
         lambda i: _text(customer_facts.injury_followup(i.question, i.resolved.prior_question, i.resolved.prior_answer, i.pet), ask=True)),
    Rule("disease_ask", "병명 되묻기", lambda i: _BIZ("ASK_DISEASE")(i) and not i.resolved.follow_up,
         lambda i: _text(customer_facts.disease_ask(i.question, i.pet,
                                                    name_check=name_check.has_name if config.ASK_DISEASE_LLM else None), ask=True),
         threaded=True),                              # 모델 판정(ASK_DISEASE_LLM)이면 HTTP — 스레드로
]

# 사내규정 개인화 — 검색 전에 answer._hr_personal(hr_personal.answer)이 돈다. 주제별 조건은 hr_personal.topics_of·replay
HR_TOPICS = ("연차", "연차수당", "퇴직금", "자격수당", "승진", "급여", "통상임금")
