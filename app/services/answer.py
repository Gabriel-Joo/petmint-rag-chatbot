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
# 사내규정(베이스 모델 + SYSTEM_PROMPT_HR)만 더 길게 — 300은 업무특화 학습 모델 평가와 맞춘 값이다. 사내규정은 규정에 없는 질문에
# "왜 없는지"를 설명하다 300에서 잘려 거절 문구 전에 끊겼다(2026-10-21 HR5). 프롬프트로 줄여도 0이 되지 않아 상한을 올린다
LLM_OPTIONS_HR = {"num_predict": 512}
# 사내규정만: 리랭커 점수가 1위의 이 배수 미만인 발췌는 뺀다 — 늘 3개를 채우느라 들어온 0.01대 발췌(배우자 출산에 제44조 해고 제한)를
# 모델이 답에 섞었다(HR2 7→10/10). 절대 하한은 못 쓴다 — 답 있는 HR4(0.008·0.003)와 답 없는 HR5(0.004)가 같은 높이다.
# 업무특화는 학습 때 발췌 3개 형식이라 적용하지 않는다
HR_REL_CUT = 0.1


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
            ctx.results = cut_weak_results(ctx.results, ctx.session.mode)   # 출처 패널도 모델이 본 발췌만
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
    # 카드 순서: 법률비용 → 의료비(치료비 금액 있음) → 한도표(금액 없이 한도만). 소송 낱말이 있으면 한도표는 나오지 않는다
    ctx.calc = (payout.legal_card(ctx.question, ctx.pet) or payout.estimate(ctx.question, ctx.pet, results, chosen)
                or payout.limit_card(ctx.question, ctx.pet, chosen))
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

    options = LLM_OPTIONS_HR if mode == "사내규정" else LLM_OPTIONS
    async for piece in deps.llm.stream(model_of(mode), messages, cancel=ctx.cancel, options=options):
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
