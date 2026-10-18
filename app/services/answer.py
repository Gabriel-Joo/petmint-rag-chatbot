"""
answer.py
한 턴의 파이프라인(09 8절): scope → 검색·조립 → 되묻기 판정 → 계산 카드 → 생성 → used_references.
결과는 WS 서버 메시지로 흘려보낸다 — sources → (calc) → token… → references, 되묻기면 sources → clarify에서 멈춘다,
실패면 error. done은 chat_ws가 턴 로그(ctx.log)를 쓴 뒤 보낸다.

고정된 결정(구현 때 바꾸지 말 것):
- 고객 정보·대화 이력은 프롬프트에 넣지 않는다(5절). prompts.build_messages(customer=, history=)는 NotImplementedError —
  등급은 SearchScope가, 자기부담금·부담보는 계산 카드·배너(코드)가, 멀티턴은 재작성 + 앞 턴 발췌 이월이 맡는다.
- 재작성기는 베이스 모델(5절). 재작성된 질문은 화면에 보여준다.
- 되묻기: 상위 결과의 section_name이 서로 다른 (유형, 등급) 조합일 때만. 가정 질문은 안 한다(4절).
- 금액 계산은 limit_table이 하고 모델은 손대지 않는다.

검색·조립은 노트북·평가와 같은 코드다(3-3절) — rag_context.build_full_context에 SearchEngine 대신 Retriever(HTTP)를 넘긴다.
build_full_context·used_references가 동기(HTTP·Milvus·SequenceMatcher)라 asyncio.to_thread로 돌린다 — 그냥 부르면
이벤트 루프가 막혀 다른 세션의 수신이 멈춘다.

아직 없는 것: 질문 재작성(rewrite_question), 앞 턴 발췌 이월, 가정 질문 판정(is_hypothetical), 부담보 배너.
"""

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field, replace
from typing import AsyncIterator

import httpx

from data import prompts
from data.rag_context import ContextBuilder, build_full_context, graph_key, infer_type_from_section_name, used_references
from data.search_scope import MEDICAL_SECTIONS, SearchScope

from app import config
from app.db import now, utc
from app.schemas import (CalcMsg, CalcResult, ClarifyMsg, ErrorMsg, Mode, Pet, ReferenceItem, ReferencesMsg, ServerMessage,
                         Session, SessionTurn, SourceItem, SourcesMsg, TokenMsg, TurnLog)
from app.services import payout
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


def count_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass
class TurnDeps:
    """턴이 쓰는 앱 상태(lifespan이 만든 것)"""
    retriever: Retriever
    builder: ContextBuilder
    llm: OllamaClient


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


async def rewrite_question(history: list[SessionTurn], question: str) -> str:
    """후속 질문 → 독립 질문(베이스 모델). 이력이 없으면 그대로"""
    raise NotImplementedError("5절 질문 재작성")


async def run_turn(ctx: TurnContext, deps: TurnDeps) -> AsyncIterator[ServerMessage]:
    """한 턴을 실행하며 서버 메시지를 순서대로 낸다. 끝나면 ctx.log(TurnLog)를 채운다 — 되묻기로 멈추면 비워 두고
    ctx.clarify에 선택지를 남긴다(resume_clarified 또는 abandon이 마무리한다)"""
    try:
        if ctx.scope is not None:
            try:
                ctx.results = await asyncio.to_thread(build_full_context, deps.retriever, deps.builder, ctx.question,
                                                      ctx.scope, SEARCH_TOP_K)
            except httpx.HTTPError as e:        # search-service가 없거나 실패 — Milvus(조립) 오류는 아래 internal
                yield _fail(ctx, e, "search_unavailable")
                return
            ctx.sources = [_source_item(r, ctx.scope.species) for r in ctx.results]
        yield SourcesMsg(turn_id=ctx.turn_id, items=ctx.sources)

        options = clarify_options(ctx.results, ctx.scope)
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
    ctx.clarify, ctx.started = None, time.monotonic()
    medical = MEDICAL_SECTIONS[ctx.scope.species]
    kept = [r for r in ctx.results if r.get("section_name") == chosen or r.get("section_name") not in medical]
    try:
        async for m in _generate(ctx, deps, kept, chosen):
            yield m
    except Exception as e:
        yield _fail(ctx, e)


def abandon(ctx: TurnContext) -> None:
    """끝나지 않은 턴(되묻기 응답 전에 새 질문·연결 끊김, 생성 중 끊김)을 cancelled로 남긴다"""
    if ctx.log is None:
        ctx.log = _turn_log(ctx, "cancelled", [], [], [])


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
    ctx.calc = payout.estimate(ctx.question, ctx.pet, results, chosen)
    if ctx.calc is not None:
        yield CalcMsg(turn_id=ctx.turn_id, result=ctx.calc)

    items: list[prompts.ExcerptItem] = []
    if ctx.scope is None:                      # 일반 — 검색 없이 질문만
        messages = [{"role": "user", "content": ctx.question}]
    else:
        # key는 결과 위치 — graph_key는 조번호 없는 청크(안내·별표·별첨)끼리 겹친다. 프롬프트에는 안 나간다
        items = prompts.fit_to_budget(ctx.question, [replace(prompts.ExcerptItem.from_search_result(r), key=str(i))
                                                     for i, r in enumerate(results)],
                                      PROMPT_BUDGET, count_tokens)
        hr = mode == "사내규정"
        messages = prompts.build_messages(ctx.question, items,
                                          system=prompts.SYSTEM_PROMPT_HR if hr else prompts.SYSTEM_PROMPT,
                                          excerpt_header=prompts.HR_EXCERPT_HEADER if hr else prompts.EXCERPT_HEADER)

    async for piece in deps.llm.stream(model_of(mode), messages, cancel=ctx.cancel, options=LLM_OPTIONS):
        if ctx.first_token_ms is None:
            ctx.first_token_ms = int((time.monotonic() - ctx.started) * 1000)
        ctx.answer += piece
        yield TokenMsg(turn_id=ctx.turn_id, text=piece)
    if ctx.cancel.is_set():
        ctx.log = _turn_log(ctx, "cancelled", [], [], [])
        return

    corpus = ctx.scope.species if ctx.scope else None
    references, graph_refs, used_graph = await asyncio.to_thread(_used, ctx.answer, results, items, corpus)
    yield ReferencesMsg(turn_id=ctx.turn_id, items=references)
    ctx.log = _turn_log(ctx, "ok", references, graph_refs, used_graph)


def _used(answer: str, results: list[dict], items: list[prompts.ExcerptItem],
          corpus: str | None) -> tuple[list[ReferenceItem], list[dict], list[dict]]:
    """답변이 실제로 쓴 근거(08 Ragas가 쓴다). 프롬프트에 들어간 발췌만 본다(fit_to_budget이 뺀 것은 모델이 못 봤다).
    - 검색 결과 자체: 답변과 발췌 본문이 used_references 기준(8자 이상 일치 또는 조문 언급)으로 겹치면
    - 참조 조문·법령 박스: rag_context.used_references(검색 결과 본문에서 온 구간은 빼고 본다)
    반환: (ReferenceItem 목록, 프롬프트에 들어간 그래프 참조 전부, 그중 쓴 것) — 뒤 둘은 retrieved 그래프 행"""
    if corpus is None:
        return [], [], []
    by_key = {it.key: it for it in items}           # 위치("0", "1", …) → 프롬프트에 남은 발췌(_generate가 key를 매긴다)
    refs: list[ReferenceItem] = []
    graph_refs, used_graph = [], []
    for i, r in enumerate(results):
        item = by_key.get(str(i))
        if item is None:
            continue
        label = item.label
        if used_references(answer, [{"citation_label": label, "content": r["content"]}], ""):
            refs.append(ReferenceItem(citation_label=label, species=corpus, section=r["section"],
                                      section_name=r.get("section_name"), article_num=r.get("article_num"),
                                      paragraph_num=r.get("paragraph_num")))
        in_prompt = {(ref.label, ref.content) for ref in item.references}
        kept = [_with_section(g, r.get("references", [])) for g in r.get("reference_contents", [])
                if (g["citation_label"], (g.get("content") or "").strip()) in in_prompt]
        used = used_references(answer, kept, r["content"], unit_article=r.get("article_num"))
        graph_refs += kept
        used_graph += used
        refs += [ReferenceItem(citation_label=g["citation_label"], species=corpus, section=g["section"],
                               section_name=g.get("section_name"), article_num=g.get("article_num"),
                               paragraph_num=g.get("paragraph_num")) for g in used]
    return refs, graph_refs, used_graph


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


def _source_item(r: dict, corpus: str) -> SourceItem:
    return SourceItem(graph_key=graph_key(r), species=corpus, section=r["section"], section_name=r.get("section_name"),
                      article_num=r.get("article_num"), article_title=r.get("article_title"),
                      coverage_type=r.get("coverage_type"), score=float(r["score"]), content=r["content"])


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
    return TurnLog(turn_id=ctx.turn_id, session_id=ctx.session.session_id, question=ctx.question, answer=ctx.answer,
                   payout=ctx.calc.model_dump() if ctx.calc else None, **pet_snapshot(ctx.pet),
                   clarified=ctx.clarified, scope=scope_rows(ctx.pet),
                   retrieved=retrieved_rows(ctx.sources, references, corpus=corpus, graph_refs=graph_refs,
                                            used_graph=used_graph),
                   model=model_of(ctx.session.mode), prompt_version=config.PROMPT_VERSION,
                   index_version=config.INDEX_VERSION, first_token_ms=ctx.first_token_ms,
                   latency_ms=int((time.monotonic() - ctx.started) * 1000), status=status, created_at=utc(now()))
