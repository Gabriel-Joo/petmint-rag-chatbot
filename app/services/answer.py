"""
answer.py
한 턴의 파이프라인(09 8절): scope → 검색·조립 → 되묻기 판정 → 계산 카드 → 생성 → used_references.
결과는 WS 서버 메시지로 흘려보낸다 — sources → (calc) → token… → references, 되묻기면 sources → clarify에서 멈춘다,
실패면 error. done은 chat_ws가 턴 로그(ctx.log)를 쓴 뒤 보낸다.

고정된 결정(구현 때 바꾸지 말 것):
- 고객 정보·대화 이력은 프롬프트에 넣지 않는다(5절). prompts.build_messages(customer=, history=)는 NotImplementedError —
  등급은 SearchScope가, 자기부담금·부담보는 계산 카드·배너(코드)가, 멀티턴은 context.py가 맡는다(모드별 — 일반만 이력 전달).
- 재작성기는 베이스 모델(5절). 재작성된 질문은 화면에 보여준다.
- 되묻기: 상위 결과의 section_name이 서로 다른 (유형, 등급) 조합일 때만. 가정 질문은 안 한다(4절).
- 금액 계산은 limit_table이 하고 모델은 손대지 않는다.

검색·조립은 노트북·평가와 같은 코드다(3-3절) — rag_context.build_full_context에 SearchEngine 대신 Retriever(HTTP)를 넘긴다.
build_full_context·used_references가 동기(HTTP·Milvus·SequenceMatcher)라 asyncio.to_thread로 돌린다 — 그냥 부르면
이벤트 루프가 막혀 다른 세션의 수신이 멈춘다.

멀티턴은 context.resolve(chat_ws가 부른다)가 푼 결과(ctx.resolved)를 쓴다 — 검색어·답변 질문·카드 문장·이어 쓰는 특약.
아직 없는 것: 가정 질문 판정(is_hypothetical), 부담보 배너.
"""

import asyncio
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field, replace
from typing import AsyncIterator

import httpx

from data import prompts
from data.rag_context import (ContextBuilder, build_full_context, graph_key, human_article_adjust,
                              infer_type_from_section_name, used_references)
from data.search_scope import MEDICAL_SECTIONS, SearchScope

from app import config
from app.db import now, utc
from app.schemas import (CalcMsg, CalcResult, ClarifyMsg, ErrorMsg, ExclusionsMsg, Mode, Pet, ReferenceItem, ReferencesMsg, ServerMessage,
                         TablesMsg,
                         Session, SourceItem, SourcesMsg, TokenMsg, TurnLog)
from app.services import article_display, customer_facts, guardrail, hr_personal, payout, tables
from app.services.context import Resolved
from app.services.customers import scope_for
from app.services.llm import OllamaClient, OllamaError
from app.services.retrieval import Retriever
from app.services.turn_log import pet_snapshot, retrieved_rows, scope_rows

log = logging.getLogger(__name__)

HR_CORPUS = "인사규정"
SEARCH_TOP_K = 3              # 08 검색 조건 평가(answer_eval SEARCH_TOP_K)와 같은 값
PROMPT_BUDGET = 2400          # user 메시지 토큰 상한 — answer_eval SEARCH_BUDGET과 같다(학습 MAX_LENGTH 3072 기준)
# 앱에는 토크나이저가 없다 — 글자 수로 어림한다. Tri-7B 실측(2026-10-18, CPU): 청크 1,730개 글자/토큰 최소 1.57·p1 1.73,
# 학습 user 메시지 300개 최소 1.83. 1.5로 나누면 실제 토큰보다 늘 크게 세어 예산을 넘지 않는다(대신 조금 더 자른다)
CHARS_PER_TOKEN = 1.5
LLM_OPTIONS = {"num_predict": 300}   # answer_eval MAX_NEW_TOKENS. 온도·num_ctx는 Modelfile 값(tri-7b: 0.3, 8192)을 따른다
# 베이스 모델 모드(사내규정·일반)는 더 길게 — 300은 업무특화 학습 모델 평가와 맞춘 값이라 업무특화만 300으로 둔다.
# 사내규정은 규정에 없는 질문에 "왜 없는지"를 설명하다 300에서 잘려 거절 문구 전에 끊겼고(2026-10-21 HR5),
# 일반은 마크다운으로 그리자 300에서 끊긴 표·코드가 더 눈에 띄었다(2026-10-21)
LLM_OPTIONS_BASE = {"num_predict": 512}
# 사내규정만: 리랭커 점수가 1위의 이 배수 미만인 발췌는 뺀다 — 늘 3개를 채우느라 들어온 0.01대 발췌(배우자 출산에 제44조 해고 제한)를
# 모델이 답에 섞었다(HR2 7→10/10). 절대 하한은 못 쓴다 — 답 있는 HR4(0.008·0.003)와 답 없는 HR5(0.004)가 같은 높이다.
# 업무특화는 학습 때 발췌 3개 형식이라 적용하지 않는다
HR_REL_CUT = 0.1


RULE_ARTICLES = ("보험금의 지급사유", "보상하는 손해")


def rule_first(results: list[dict]) -> list[dict]:
    """1안(2026-10-23) — "○○ 걸렸는데 보장돼요?"에 지급사유 조항의 예외 항(30일 대기기간 등)만 본문으로 오고 원칙(제1항
    "…보상합니다")은 [참조]로만 붙으면 모델이 거절했다(평가 220 원칙이 참조에만 있는 턴 24/36 거절). 같은 조 제1항 참조를
    본문 앞으로 옮긴다 — 같은 글이 자리만 바뀌어 토큰은 늘지 않고(참조 머리줄만 빠진다) 예외 발췌는 그대로 남는다"""
    out = []
    for r in results:
        refs = r.get("reference_contents") or []
        title = r.get("article_title") or ""
        rule = next((x for x in refs if any(t in title for t in RULE_ARTICLES) and x.get("article_num") == r.get("article_num")
                     and x.get("paragraph_num") == 1 and x.get("section_name") in (None, r.get("section_name"))), None)
        if rule is None or not (rule.get("content") or "").strip():
            out.append(r)
            continue
        out.append({**r, "content": rule["content"].strip() + "\n" + r["content"],
                    "reference_contents": [x for x in refs if x is not rule]})
    return out


def display_parent(results: list[dict], builder, species: str) -> list[dict]:
    """6단계 B 조건 — 청크 v2의 조각으로 찾은 결과를 부모(원래 청크) 글로 바꿔 보여준다. 같은 부모가 겹치면 처음 것만 남긴다
    (다음 순위로 채우지 않는다 — 형제 청크를 지우고 채운 10-19 실험이 거절을 늘렸다. 발췌 수가 줄어든 턴은 평가가 따로 센다).
    조각이 아닌 청크(부모 = 자기)는 그대로"""
    out, seen = [], set()
    for r in results:
        src = next((c for c in builder.chunks.get(species, []) if c.get("section") == r.get("section")
                    and c.get("section_name") == r.get("section_name") and c.get("article_num") == r.get("article_num")
                    and c.get("coverage_type") == r.get("coverage_type") and c["content"].strip() == r["content"].strip()), None)
        if src is None or "parent_index" not in src:
            out.append(r)
            continue
        if src["parent_index"] in seen:
            continue
        seen.add(src["parent_index"])
        out.append({**r, "content": src["parent_content"], "context_prefix": src.get("parent_context_prefix")}
                   if src.get("piece") else r)
    return out


def cut_weak_results(results: list[dict], mode: Mode) -> list[dict]:
    """사내규정 모드면 1위 점수의 HR_REL_CUT배 미만 결과를 뺀다. 다른 모드는 그대로"""
    if mode != "사내규정" or not results:
        return results
    top = results[0]["score"]
    return [r for r in results if r["score"] >= HR_REL_CUT * top]


def count_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass
class TurnDeps:
    """턴이 쓰는 앱 상태(lifespan이 만든 것)"""
    retriever: Retriever
    builder: ContextBuilder
    llm: OllamaClient
    employees: "hr_personal.EmployeeStore | None" = None      # 사내규정 개인화(PETMINT_HR_PERSONAL) — 인사 원장


@dataclass
class TurnContext:
    turn_id: str
    session: Session
    pet: Pet | None                       # 업무특화만
    scope: SearchScope | None             # 일반 모드는 None(검색 없음)
    question: str
    agent: str
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    # ----- 턴을 돌며 채운다 -----
    started: float = field(default_factory=time.monotonic)
    results: list[dict] = field(default_factory=list)          # build_full_context 결과(reference_contents 포함)
    sources: list[SourceItem] = field(default_factory=list)
    clarify: dict[str, str] | None = None                     # 되묻기 선택지 → section_name. 응답을 기다리는 중이면 있다
    clarified: bool = False
    calc: CalcResult | None = None
    tables: list = field(default_factory=list)                 # 답 아래 표(TablesMsg) — 평가·로그용
    resolved: Resolved | None = None                          # 멀티턴(context.resolve) — None이면 질문 그대로
    chosen: str | None = None                                 # 되묻기로 고르거나 앞 턴에서 이어 쓴 특약
    answer: str = ""
    first_token_ms: int | None = None
    log: TurnLog | None = None                                # 끝나면(ok·error·cancelled) 채운다 — chat_ws가 done 전에 쓴다


def scope_of(mode: Mode, pet: Pet | None) -> SearchScope | None:
    """모드별 검색 범위 — 일반: 검색 없음 / 업무특화: 가입 정보 / 사내규정: 인사규정 전체(필터 없음)"""
    if mode == "업무특화":
        return scope_for(pet)
    if mode == "사내규정":
        return SearchScope.unrestricted(HR_CORPUS)
    return None


def model_of(mode: Mode) -> str:
    return config.FINETUNED_MODEL if mode == "업무특화" else config.BASE_MODEL


def _r(ctx: TurnContext) -> Resolved:
    return ctx.resolved or Resolved(question=ctx.question)


def _keep_chosen(results: list[dict], scope: SearchScope, chosen: str) -> list[dict]:
    """고른 의료비 특약과 의료비가 아닌 결과(공통 조항)만"""
    medical = MEDICAL_SECTIONS[scope.species]
    return [r for r in results if r.get("section_name") == chosen or r.get("section_name") not in medical]


async def run_turn(ctx: TurnContext, deps: TurnDeps) -> AsyncIterator[ServerMessage]:
    """한 턴을 실행하며 서버 메시지를 순서대로 낸다. 끝나면 ctx.log(TurnLog)를 채운다 — 되묻기로 멈추면 비워 두고
    ctx.clarify에 선택지를 남긴다(resume_clarified 또는 abandon이 마무리한다)"""
    try:
        context = _r(ctx).message(ctx.turn_id)
        if context is not None:                 # 후속 질문 — 앞 대화로 어떻게 풀었는지(화면의 ↳ 줄)
            yield context
        if ctx.session.mode == "사내규정" and config.HR_PERSONAL and deps.employees is not None:
            done = False
            async for m in _hr_personal(ctx, deps):
                done = True
                yield m
            if done:
                return
        if ctx.scope is not None:
            try:
                adjust = (human_article_adjust(config.HUMAN_DEMOTE, config.TWIN_ARTICLE)
                          if ctx.session.mode == "업무특화" else None)
                ctx.results = await asyncio.to_thread(build_full_context, deps.retriever, deps.builder,
                                                      _r(ctx).retrieval_query, ctx.scope, SEARCH_TOP_K, adjust)
            except httpx.HTTPError as e:        # search-service가 없거나 실패 — Milvus(조립) 오류는 아래 internal
                yield _fail(ctx, e, "search_unavailable")
                return
            ctx.results = cut_weak_results(ctx.results, ctx.session.mode)   # 출처 패널도 모델이 본 발췌만
            if config.DISPLAY_PARENT:
                ctx.results = display_parent(ctx.results, deps.builder, ctx.scope.species)
            if config.RULE_FIRST:
                ctx.results = rule_first(ctx.results)
            ctx.sources = [_source_item(r, ctx.scope.species, deps.builder.chunks) for r in ctx.results]
        yield SourcesMsg(turn_id=ctx.turn_id, items=ctx.sources)
        excl = payout.matched_exclusions(_r(ctx).card_text, ctx.pet) if config.CUSTOMER_FACTS else []   # 부담보 배너(4d)
        if excl:
            yield ExclusionsMsg(turn_id=ctx.turn_id, items=excl)

        carried = _r(ctx).chosen
        if carried is not None and ctx.scope is not None:    # 앞 턴에서 고른 특약을 이어 쓴다 — 다시 묻지 않는다
            ctx.chosen = carried
            async for m in _generate(ctx, deps, _keep_chosen(ctx.results, ctx.scope, carried), carried):
                yield m
            return
        options = clarify_options(ctx.results, ctx.scope)
        if options:
            # 되묻기가 걸리는 경우만 줄인다(4e) — 질문이 통원/입원을 말했으면 그 가입 특약으로, 등급과 상관없는 질문이면 묻지 않는다.
            # 되묻기가 안 걸리던 반려동물의 발췌는 그대로다
            named = named_section(_r(ctx).card_text, ctx.pet)
            if named is not None:
                ctx.chosen = named
                async for m in _generate(ctx, deps, _keep_chosen(ctx.results, ctx.scope, named), named):
                    yield m
                return
            if not needs_grade(_r(ctx).card_text):
                options = None
        if options:
            ctx.clarify, ctx.clarified = options, True       # 답 없이 버려져도 되묻기는 발동했다(turns.clarified)
            yield ClarifyMsg(turn_id=ctx.turn_id, options=list(options))
            return
        async for m in _generate(ctx, deps, ctx.results):
            yield m
    except Exception as e:
        yield _fail(ctx, e)


async def resume_clarified(ctx: TurnContext, choice: str, deps: TurnDeps) -> AsyncIterator[ServerMessage]:
    """clarify_answer를 받은 뒤 고른 쪽으로 생성을 잇는다 — 고른 의료비 특약과 의료비가 아닌 결과(공통 조항)만 발췌로 쓴다"""
    chosen = (ctx.clarify or {}).get(choice)
    if chosen is None:
        yield ErrorMsg(turn_id=ctx.turn_id, code="bad_choice", message=f"선택지에 없는 답: {choice}")
        return
    ctx.clarify, ctx.started, ctx.chosen = None, time.monotonic(), chosen
    kept = _keep_chosen(ctx.results, ctx.scope, chosen)
    try:
        async for m in _generate(ctx, deps, kept, chosen):
            yield m
    except Exception as e:
        yield _fail(ctx, e)


def abandon(ctx: TurnContext) -> None:
    """끝나지 않은 턴(되묻기 응답 전에 새 질문·연결 끊김, 생성 중 끊김)을 cancelled로 남긴다"""
    if ctx.log is None:
        ctx.log = _turn_log(ctx, "cancelled", [], [], [])


# 등급 되묻기는 등급에 따라 숫자가 달라지는 질문에만(4e, 2026-10-21) — 기준선에서 통원/입원 등급이 다른 반려동물(콩이·레오)에게
# "주식 사도 될까요?"·"약욕 비용 청구돼요?"까지 되물어 답이 멈췄다(실행마다 9턴). 면책·절차 질문은 등급과 상관없이 같다
_GRADE_MATTERS = re.compile(r"한도|얼마|금액|보험금|최대|하루|1일|보상비율|몇\s*퍼센트|자기\s*부담")


def needs_grade(question: str) -> bool:
    return bool(_GRADE_MATTERS.search(question))


def named_section(question: str, pet: Pet | None) -> str | None:
    """질문이 '통원'이나 '입원' 하나만 말하고 그쪽 의료비 특약에 가입했으면 그 특약. 둘 다 말했거나 가입하지 않았으면 None"""
    if pet is None:
        return None
    said = [w for w in ("통원", "입원") if w in question]
    if len(said) != 1:
        return None
    hits = [p.section_name for p in pet.policies
            if p.coverage_type and said[0] in p.section_name and p.section_name in MEDICAL_SECTIONS[pet.species]]
    return hits[0] if len(hits) == 1 else None


def clarify_options(results: list[dict], scope: SearchScope | None) -> dict[str, str] | None:
    """상위 결과의 의료비 특약들이 서로 다른 (유형, 등급) 조합이면 선택지(표시 문구 → section_name). 아니면 None.
    같은 유형·등급이면 통원/입원 한도가 같아 묻지 않는다(4절). 범위에 등급이 없으면(인사규정·일반) 늘 None"""
    if scope is None or scope.medical is None:
        return None
    medical = MEDICAL_SECTIONS[scope.species]
    combos: dict[tuple, str] = {}
    for r in results:
        name = r.get("section_name")
        if name in medical:
            combos.setdefault((infer_type_from_section_name(name), scope.grade_for(name) or r.get("coverage_type")), name)
    if len(combos) < 2:
        return None
    return {f"{name} {grade}" if grade else name: name for (_, grade), name in combos.items()}


async def _generate(ctx: TurnContext, deps: TurnDeps, results: list[dict],
                    chosen: str | None = None) -> AsyncIterator[ServerMessage]:
    mode = ctx.session.mode
    r = _r(ctx)
    if r.after_amount_ask:
        # 코드가 되물은 턴(금액·날짜별 금액·일수) 바로 뒤 — 모델을 부르지 않고 카드와 같은 계산 결과로 답한다(payout.reply_turn):
        # 업무특화 모델은 이 계산을 못 했다(틀린 숫자·거절 — data/review/amount_turn_20261021.md). 날짜별 금액이 필요하면
        # 입력칸 카드(days_ask)로 한 번 더 묻는다
        out = payout.reply_turn(ctx.question, r.card_text, r.reply_stage, r.prior_calc, ctx.pet, results, chosen)
        if out is not None:
            for m in _code_answer(ctx, *out):
                yield m
            return
    # 고객 고유 사실(4d) — 가입하지 않은 특약, 올해 받은·남은 보험금은 코드가 답한다(모델은 고객 정보를 받지 않는다)
    fact = (customer_facts.not_enrolled(r.card_text, ctx.pet) or customer_facts.annual_answer(r.card_text, ctx.pet)
            if config.CUSTOMER_FACTS else None)
    if fact is not None:
        for m in _code_answer(ctx, None, fact, ask=False):
            yield m
        return
    if await asyncio.to_thread(payout.needs_amount, r.card_text, ctx.pet, deps.retriever.embed):
        # 금액 되묻기 — 모델을 부르지 않고 묻고 끝낸다(정상 완료 턴). 입원/통원에 따라 총액과 일수(횟수)를 함께 묻는다.
        # 다음 턴 "3일 입원 총 70만원"은 멀티턴으로 이 질문과 이어 붙고 코드가 계산한다(reply_turn).
        # 등급 되묻기가 있으면 그 뒤에 온다(이 함수는 되묻기 응답 뒤에 불린다)
        ctx.clarified = True
        ctx.answer = payout.ask_text(r.card_text, ctx.pet, chosen)
        ctx.first_token_ms = int((time.monotonic() - ctx.started) * 1000)
        yield TokenMsg(turn_id=ctx.turn_id, text=ctx.answer)
        yield ReferencesMsg(turn_id=ctx.turn_id, items=[])
        ctx.log = _turn_log(ctx, "ok", [], [], [])
        return
    # 카드 순서: 가정 등급·유형 → 법률비용 → 의료비(치료비 금액 있음) → 한도표(금액 없이 한도만). 소송 낱말이 있으면 한도표는
    # 나오지 않는다. 카드가 뜨면 답도 카드 값으로 코드가 만든다(2026-10-21 — 모델은 3천만원 소송의 변호사비를 30만원이라 했다).
    # 업무특화 후속은 기준 질문까지 읽는다 — "그럼 입원은요?"의 금액·한도 낱말은 앞 질문에 있다
    q = r.card_text
    card = payout.hypothetical_card(q, ctx.pet) if config.CUSTOMER_FACTS else None
    if card is not None:
        for m in _code_answer(ctx, card, payout.limit_answer(card, ctx.pet, q), ask=False):
            yield m
        return
    card = payout.legal_card(q, ctx.pet)
    if card is not None:
        for m in _code_answer(ctx, card, payout.legal_answer(card), ask=False):
            yield m
        return
    # 의료비 카드가 뜨면 답도 카드 값으로 — 처음부터 금액을 다 말한 질문도 되묻기 뒤 턴과 같다(모델은 거절했다, R2·R26·R29)
    out = payout.question_turn(q, ctx.pet, results, chosen)
    if out is not None:
        for m in _code_answer(ctx, *out):
            yield m
        return
    card = payout.limit_card(q, ctx.pet, chosen)
    if card is not None:
        for m in _code_answer(ctx, card, payout.limit_answer(card, ctx.pet, q), ask=False):
            yield m
        return

    # 3안(2026-10-23) — 보장 여부 질문에서 코드가 확실히 아는 부정 사실(부담보·대기기간 안)은 모델 대신 코드가 답한다.
    # 카드(금액·한도)가 먼저다 — 카드 답에는 이미 부담보·대기기간 줄이 붙는다
    if mode == "업무특화" and config.AGE_CODE and config.CUSTOMER_FACTS:
        text = customer_facts.enrollment_age_answer(q, ctx.pet)       # 신규 가입 나이(2026-10-24) — 조건 셋, 범위 좁게
        if text is not None:
            for m in _code_answer(ctx, None, text, ask=False):
                yield m
            return
    if mode == "업무특화" and config.COVERAGE_CODE and config.CUSTOMER_FACTS:
        text = customer_facts.exclusion_answer(q, ctx.pet)        # 대기기간 결론(waiting_answer)은 측정에서 해가 커 쓰지 않는다
        if text is not None:
            for m in _code_answer(ctx, None, text, ask=False):
                yield m
            return

    if mode == "업무특화" and config.PROVISO_CODE and config.CUSTOMER_FACTS:
        text = customer_facts.proviso_answer(ctx.question, q, ctx.pet)  # 면책 단서 셋(2026-10-24) — 병명·치료 말은 지금 질문에서만
        if text is not None:
            for m in _code_answer(ctx, None, text, ask=False):
                yield m
            return

    if mode == "업무특화" and config.ASK_DISEASE and config.CUSTOMER_FACTS:
        # 병명 되묻기 뒤 상해로 답한 턴(2026-10-28) — 상해 보상 원칙(대기기간 없음) + 금액 되묻기. 앞 답이 되묻기일 때만
        text = customer_facts.injury_followup(ctx.question, r.prior_question, r.prior_answer, ctx.pet)
        if text is not None:
            for m in _code_answer(ctx, None, text):
                yield m
            return
    if mode == "업무특화" and config.ASK_DISEASE and config.CUSTOMER_FACTS and not r.follow_up:
        text = customer_facts.disease_ask(ctx.question, ctx.pet)     # 병명 없이 보장을 묻는다(2026-10-28) — 원칙 + 병명 되묻기
        if text is not None:
            for m in _code_answer(ctx, None, text):                  # ask=True — 되물은 턴(turns.clarified)
                yield m
            return

    items: list[prompts.ExcerptItem] = []
    if ctx.scope is None:                      # 일반 — 검색 없이 질문만(후속이면 최근 3턴 이력을 앞에)
        messages = r.history + [{"role": "user", "content": ctx.question}]
    else:
        # key는 결과 위치 — graph_key는 조번호 없는 청크(안내·별표·별첨)끼리 겹친다. 프롬프트에는 안 나간다.
        # 답변 모델에 넘기는 질문: 사내규정은 재작성된 질문, 업무특화는 기준 질문 + 후속(금액만 말한 후속은 후속만) — context.Resolved
        gq = r.generation_question
        items = prompts.fit_to_budget(gq, [replace(prompts.ExcerptItem.from_search_result(x), key=str(i))
                                           for i, x in enumerate(results)],
                                      PROMPT_BUDGET, count_tokens)
        hr = mode == "사내규정"
        messages = prompts.build_messages(gq, items,
                                          system=prompts.SYSTEM_PROMPT_HR if hr else prompts.SYSTEM_PROMPT,
                                          excerpt_header=prompts.HR_EXCERPT_HEADER if hr else prompts.EXCERPT_HEADER)

    options = LLM_OPTIONS if mode == "업무특화" else LLM_OPTIONS_BASE
    if config.PROMPT_LOG:
        _log_prompt(ctx, messages, options, results, items)
    async for piece in deps.llm.stream(model_of(mode), messages, cancel=ctx.cancel, options=options):
        if ctx.first_token_ms is None:
            ctx.first_token_ms = int((time.monotonic() - ctx.started) * 1000)
        ctx.answer += piece
        yield TokenMsg(turn_id=ctx.turn_id, text=piece)
    if ctx.cancel.is_set():
        ctx.log = _turn_log(ctx, "cancelled", [], [], [])
        return
    if mode == "업무특화" and config.NUMBER_GUARD:
        # 숫자 가드레일 — 모델이 본 글·카드에 없는 금액이면 한 줄 덧붙인다(guardrail.py)
        unknown = guardrail.unknown_amounts(ctx.answer, [m["content"] for m in messages], ctx.calc)
        if unknown:
            extra = "\n\n" + guardrail.note(unknown)
            ctx.answer += extra
            yield TokenMsg(turn_id=ctx.turn_id, text=extra)
            log.info("숫자 가드레일: turn=%s 금액 %s", ctx.turn_id, unknown)
    if mode == "업무특화" and config.CUSTOMER_FACTS:
        facts = customer_facts.notes(r.card_text, ctx.pet)                 # 가입일 대기기간·나이(4d)
        if facts:
            extra = "\n\n" + "\n".join(facts)
            ctx.answer += extra
            yield TokenMsg(turn_id=ctx.turn_id, text=extra)

    corpus = ctx.scope.species if ctx.scope else None
    references, graph_refs, used_graph = await asyncio.to_thread(_used, ctx.answer, results, items, corpus)
    if config.ANSWER_TABLES and items:
        # 답이 쓴 발췌의 표 — 숫자는 발췌 원문 그대로, 질문에 맞는 행 강조(tables.py). 카드 턴은 위에서 이미 끝났다
        chosen = pick_excerpts(ctx.answer, [(it.label, _block_text(it)) for it in items])
        tbls = tables.answer_tables([(items[i].label, items[i].content) for i in sorted(chosen)], r.card_text, ctx.pet)
        if tbls:
            ctx.tables = tbls
            yield TablesMsg(turn_id=ctx.turn_id, items=tbls)
    yield ReferencesMsg(turn_id=ctx.turn_id, items=references)
    ctx.log = _turn_log(ctx, "ok", references, graph_refs, used_graph)


def _log_prompt(ctx: TurnContext, messages: list[dict], options: dict, results: list[dict],
                items: list[prompts.ExcerptItem]) -> None:
    """평가가 모델이 실제로 본 것을 대조하게 — 프롬프트 전문, 검색 결과 순서, 예산 맞추기 뒤 남은 발췌(key = 결과 위치)"""
    row = dict(turn_id=ctx.turn_id, session_id=ctx.session.session_id, model=model_of(ctx.session.mode), options=options,
               messages=messages, kept=[it.key for it in items],
               results=[{k: r.get(k) for k in ("section", "section_name", "article_num", "paragraph_num", "coverage_type", "score")}
                        for r in results])
    try:
        with open(config.PROMPT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        log.exception("프롬프트 기록 실패: %s", config.PROMPT_LOG)


async def _hr_personal(ctx: TurnContext, deps: TurnDeps) -> AsyncIterator[ServerMessage]:
    """사내규정 개인화(2026-10-28) — 본인 연차·연차수당·퇴직금·자격수당·승진이면 인사 원장으로 코드가 답한다. 걸리지 않으면 아무것도 내지 않는다.
    검색보다 먼저 정한다: 근거 조항(sources)은 검색 결과가 아니라 코드가 실제로 쓴 조항이다 — 검색 결과를 내보내면 연차 답에
    제43조(정년)·제33조(승진)가 붙었다(운영). 지금 질문에 본인 지칭이 없어도 앞 턴들이 개인화 사슬이면 이어받는다(hr_personal.replay)"""
    r = _r(ctx)
    facts = await asyncio.to_thread(deps.employees.load, ctx.session.agent_email)
    out = hr_personal.answer(ctx.question, facts, payout.today(), r.prior_questions)
    if out is None:
        return
    text, articles = out
    chunks = deps.builder.chunks.get(HR_CORPUS, [])
    ctx.sources = hr_personal.sources(articles, chunks)
    yield SourcesMsg(turn_id=ctx.turn_id, items=ctx.sources)
    refs = hr_personal.references(articles, chunks)
    ctx.answer = text
    ctx.first_token_ms = int((time.monotonic() - ctx.started) * 1000)
    yield TokenMsg(turn_id=ctx.turn_id, text=text)
    yield ReferencesMsg(turn_id=ctx.turn_id, items=refs)
    ctx.log = _turn_log(ctx, "ok", refs, [], [])


def _code_answer(ctx: TurnContext, card: CalcResult | None, text: str, ask: bool = True) -> list[ServerMessage]:
    """코드가 답하는 턴 — 카드(있으면)와 같은 계산 결과로 만든 답을 한 번에 보낸다. 모델·근거 판정 없음.
    카드 없이 답만이면 되묻기다(총액 없이 일수만 — NEED_COST_TEXT). ask=False면 고객 사실 답(미가입·연간 잔여)이다.
    계산 카드가 있는 답에는 고객 사실(대기기간·나이)을 덧붙인다 — 되묻기 문장은 다음 턴이 글자로 알아보므로 건드리지 않는다"""
    out: list[ServerMessage] = []
    if card is not None:
        ctx.calc = card
        out.append(CalcMsg(turn_id=ctx.turn_id, result=card))
        facts = customer_facts.notes(_r(ctx).card_text, ctx.pet) if config.CUSTOMER_FACTS else []
        if facts:
            text = text + "\n" + "\n".join(facts)
    elif ask:
        ctx.clarified = True
    ctx.answer = text
    ctx.first_token_ms = int((time.monotonic() - ctx.started) * 1000)
    refs = payout.code_references(card, ctx.pet, _r(ctx).card_text)    # 계산의 근거 조항(4c) — 되묻기만 한 턴은 없다
    out += [TokenMsg(turn_id=ctx.turn_id, text=text), ReferencesMsg(turn_id=ctx.turn_id, items=refs)]
    ctx.log = _turn_log(ctx, "ok", refs, [], [])
    return out


def _used(answer: str, results: list[dict], items: list[prompts.ExcerptItem],
          corpus: str | None) -> tuple[list[ReferenceItem], list[dict], list[dict]]:
    """답변이 실제로 쓴 근거(08 Ragas가 쓴다). 프롬프트에 들어간 발췌만 본다(fit_to_budget이 뺀 것은 모델이 못 봤다).
    1) 어느 발췌를 썼나: pick_excerpts — 발췌 블록(본문+참조) 중 답변과 가장 길게 겹친 것(+ 조문 언급으로 걸린 것)
    2) 고른 발췌 안에서: 검색 결과 자체(본문과 8자 이상 일치 또는 조문 언급), 참조 조문·법령 박스(used_references,
       검색 결과 본문에서 온 구간은 빼고 본다). 고르지 않은 발췌의 참조는 보지 않는다
    반환: (ReferenceItem 목록, 프롬프트에 들어간 그래프 참조 전부, 그중 쓴 것) — 뒤 둘은 retrieved 그래프 행"""
    if corpus is None:
        return [], [], []
    by_key = {it.key: it for it in items}           # 위치("0", "1", …) → 프롬프트에 남은 발췌(_generate가 key를 매긴다)
    shown = [(i, r, by_key[str(i)]) for i, r in enumerate(results) if str(i) in by_key]
    chosen = pick_excerpts(answer, [(it.label, _block_text(it)) for _, _, it in shown])
    refs: list[ReferenceItem] = []
    graph_refs, used_graph = [], []
    for n, (i, r, item) in enumerate(shown):
        label = item.label
        in_prompt = {(ref.label, ref.content) for ref in item.references}
        kept = [_with_section(g, r.get("references", [])) for g in r.get("reference_contents", [])
                if (g["citation_label"], (g.get("content") or "").strip()) in in_prompt]
        graph_refs += kept
        if n not in chosen:
            continue
        if used_references(answer, [{"citation_label": label, "content": r["content"]}], ""):
            refs.append(ReferenceItem(citation_label=label, species=corpus, section=r["section"],
                                      section_name=r.get("section_name"), article_num=r.get("article_num"),
                                      paragraph_num=r.get("paragraph_num")))
        used = used_references(answer, kept, r["content"], unit_article=r.get("article_num"))
        used_graph += used
        refs += [ReferenceItem(citation_label=g["citation_label"], species=corpus, section=g["section"],
                               section_name=g.get("section_name"), article_num=g.get("article_num"),
                               paragraph_num=g.get("paragraph_num")) for g in used]
    return refs, graph_refs, used_graph


def pick_excerpts(answer: str, blocks: list[tuple[str, str]]) -> set[int]:
    """답변이 쓴 발췌의 위치. blocks = [(발췌 라벨, 발췌 블록 글)] — 블록은 프롬프트에 보인 본문 + 참조 본문.
    used_references(longest_only=True): 조문 언급으로 걸린 것 + 8자 이상 겹친 것 중 가장 길게 겹친 하나(같은 길이면 모두).
    같은 문장이 두 발췌에 다 있으면(통원/입원 제1조처럼) 둘 다 남는다 — 글자로는 가를 수 없다"""
    cands = [{"citation_label": label, "content": text, "_i": i} for i, (label, text) in enumerate(blocks)]
    return {c["_i"] for c in used_references(answer, cands, "", longest_only=True)}


def _block_text(item: prompts.ExcerptItem) -> str:
    return "\n".join([item.content, *(ref.content for ref in item.references)])


def _with_section(g: dict, edges: list) -> dict:
    """참조 항목에 section을 붙인다 — resolve_references 결과에는 없고, 그 결과의 그래프 엣지
    [ref_num, ref_title, ref_section, ref_section_name, 항, 호]에 있다. 법령 박스(약관 밖 법령)는 None"""
    law_box = g["citation_label"] == g.get("article_title") and not g["citation_label"].startswith("제") \
        and g.get("article_num") is not None
    section = None
    if not law_box:
        section = next((e[2] for e in edges if e[0] == g.get("article_num") and e[3] == g.get("section_name")
                        and e[4] == g.get("paragraph_num")), None) \
            or next((e[2] for e in edges if e[0] == g.get("article_num") and e[3] == g.get("section_name")), None)
    return {**g, "section": section}


def _source_item(r: dict, corpus: str, chunks: dict | None = None) -> SourceItem:
    snippet = (article_display.snippet(r["content"], article_display.vocab(chunks))
               if chunks is not None and corpus in article_display.PET else None)   # 표시만(2026-10-28) — content는 그대로
    return SourceItem(graph_key=graph_key(r), species=corpus, section=r["section"], section_name=r.get("section_name"),
                      article_num=r.get("article_num"), article_title=r.get("article_title"),
                      coverage_type=r.get("coverage_type"), score=float(r["score"]), content=r["content"], snippet=snippet)


_FAIL_MESSAGE = {
    "search_unavailable": "검색 서비스에 닿지 않습니다. 잠시 뒤 다시 물어 주세요.",
    "llm_unavailable": "답변 모델에 닿지 않습니다. 잠시 뒤 다시 물어 주세요.",
    "internal": "답변을 만들지 못했습니다. 관리자에게 문의하세요.",
}


def _fail(ctx: TurnContext, e: Exception, code: str | None = None) -> ErrorMsg:
    """실패를 error 메시지로 — 상담원에게는 안내 문구만, 원인은 서버 로그에. 턴 로그는 status=error(받은 만큼의 답변)"""
    code = code or ("llm_unavailable" if isinstance(e, (httpx.HTTPError, OllamaError)) else "internal")
    message = _FAIL_MESSAGE[code]
    log.exception("턴 실패(%s): session=%s turn=%s", code, ctx.session.session_id, ctx.turn_id, exc_info=e)
    ctx.log = _turn_log(ctx, "error", [], [], [])
    return ErrorMsg(turn_id=ctx.turn_id, code=code, message=message)


def _turn_log(ctx: TurnContext, status: str, references: list[ReferenceItem], graph_refs: list[dict],
              used_graph: list[dict]) -> TurnLog:
    corpus = ctx.scope.species if ctx.scope else None
    r = _r(ctx)
    return TurnLog(turn_id=ctx.turn_id, session_id=ctx.session.session_id, question=ctx.question, answer=ctx.answer,
                   rewritten_question=r.anchor, follow_up=r.follow_up, context_kind=r.kind,
                   context_turns=len(r.history) // 2 if r.kind == "history" else None, chosen_section=ctx.chosen,
                   payout=ctx.calc.model_dump(mode="json") if ctx.calc else None, **pet_snapshot(ctx.pet),
                   clarified=ctx.clarified, scope=scope_rows(ctx.pet),
                   retrieved=retrieved_rows(ctx.sources, references, corpus=corpus, graph_refs=graph_refs,
                                            used_graph=used_graph),
                   model=model_of(ctx.session.mode), prompt_version=config.PROMPT_VERSION,
                   index_version=config.INDEX_VERSION, first_token_ms=ctx.first_token_ms,
                   latency_ms=int((time.monotonic() - ctx.started) * 1000), status=status, created_at=utc(now()))
