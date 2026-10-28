"""
turn_log.py
턴 로그 — 한 턴마다 turns + turn_scope + retrieved를 한 트랜잭션으로 쓴다(12번). 피드백도 여기서 쓴다.

- 로그는 고치지 않는다. 피드백은 feedback에 따로 쌓고, 지난 채팅 제거는 sessions.deleted_at만 찍는다.
- 반려동물·가입 내용은 그 턴의 스냅샷이다(12번 2-2절) — 고객 데이터가 바뀌어도 과거 로그는 그대로.
- retrieved는 근거 패널에 보낸 SourceItem을 그대로 펼쳐 남긴다. 답변이 쓴 근거(references)와 같은 조문이면 used.
- 동기 메서드다. WS는 asyncio.to_thread로 부른다.
"""

import json
from dataclasses import dataclass

from sqlalchemy import Engine, text

from app.db import now, utc
from app.schemas import (FeedbackIn, Pet, ReferenceItem, RetrievedRow, ScopeRow, SourceItem, TurnLog, TurnOut)


def pet_snapshot(pet: Pet | None) -> dict:
    """TurnLog의 반려동물 칸 — 일반·사내규정은 전부 None"""
    if pet is None:
        return {}
    return dict(pet_id=pet.pet_id, pet_name=pet.name, species=pet.species, breed=pet.breed, pet_age=pet.age)


def scope_rows(pet: Pet | None, hypothetical_grade: str | None = None) -> list[ScopeRow]:
    """그 턴에 적용된 가입 내용 — 특약 하나당 한 줄. 가정 질문이면 등급 있는 특약(의료비)을 질문에 쓴 등급으로 바꿔 남긴다"""
    if pet is None:
        return []
    return [ScopeRow(section_name=p.section_name,
                     coverage_type=hypothetical_grade if hypothetical_grade and p.coverage_type else p.coverage_type,
                     copay=p.copay, excluded_conditions=list(p.excluded_conditions)) for p in pet.policies]


def _article(x: SourceItem | ReferenceItem) -> tuple:
    return (x.species, x.section, x.section_name, x.article_num)


def retrieved_rows(sources: list[SourceItem], references: list[ReferenceItem], *, corpus: str | None = None,
                   graph_refs: list[dict] = (), used_graph: list[dict] = ()) -> list[RetrievedRow]:
    """모델이 받은 발췌 전부를 retrieved 행으로(12번 1-1절).

    sources: 근거 패널에 보낸 검색 결과 — 순서대로 rank. 같은 조문을 인용한 답변이면 used + citation_label·paragraph_num
      (처음 인용한 것). SourceItem에는 항 번호가 없어 used가 아닌 행의 paragraph_num은 비운다(항은 graph_key에 있다).
    graph_refs: 참조 그래프로 따라가 프롬프트에 넣은 조문·법령 박스(rag_context.resolve_references의 항목 그대로).
      검색 결과에 없어도 남겨야 08 평가가 실제 컨텍스트를 본다. used_graph는 그중 답변이 쓴 것(used_references의 반환)
    corpus: 그래프 행의 코퍼스 — 그 턴의 리트리버 코퍼스(법령 박스도 그 약관에서 뽑은 것이다)"""
    cited: dict[tuple, ReferenceItem] = {}
    for r in references:
        cited.setdefault(_article(r), r)
    rows = []
    for i, s in enumerate(sources):
        ref = cited.get(_article(s))
        rows.append(RetrievedRow(rank=i, graph_key=s.graph_key, corpus=s.species, section=s.section,
                                 section_name=s.section_name, article_num=s.article_num, article_title=s.article_title,
                                 coverage_type=s.coverage_type, paragraph_num=ref.paragraph_num if ref else None,
                                 score=s.score, content=s.content, used=ref is not None,
                                 citation_label=ref.citation_label if ref else None))
    if graph_refs and corpus is None:
        raise ValueError("그래프 행을 남기려면 corpus가 필요하다")
    for g in graph_refs:
        rows.append(RetrievedRow(via_graph=True, graph_key=g.get("graph_key"), corpus=corpus, section=g.get("section"),
                                 section_name=g.get("section_name"), article_num=g.get("article_num"),
                                 article_title=g.get("article_title"), coverage_type=g.get("coverage_type"),
                                 paragraph_num=g.get("paragraph_num"), content=g["content"],
                                 used=any(g is u or g == u for u in used_graph), citation_label=g["citation_label"]))
    return rows


def _json(v):
    """MySQL JSON 칸 — 드라이버에 따라 문자열이나 이미 풀린 값으로 온다"""
    return json.loads(v) if isinstance(v, str) else v


@dataclass(frozen=True)
class PriorTurn:
    """멀티턴이 보는 앞 턴 하나. anchor = 기준 질문(재작성·이어 붙인 질문, 없으면 질문 그대로)"""
    question: str
    anchor: str
    answer: str
    pet_id: str | None
    chosen_section: str | None
    payout: dict | None = None                     # 그 턴의 계산 카드 — 코드가 되물은 턴의 총액·일수(payout.reply_stage)


class TurnLogStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def record(self, log: TurnLog) -> None:
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO turns (turn_id, session_id, question, rewritten_question, follow_up, context_kind, context_turns,"
                " answer, payout, pet_id, pet_name, species, breed, pet_age, is_hypothetical, clarified, code_rule, chosen_section,"
                " model, prompt_version, index_version, first_token_ms, latency_ms, status, created_at)"
                " VALUES (:turn_id, :session_id, :question, :rewritten_question, :follow_up, :context_kind, :context_turns,"
                " :answer, :payout, :pet_id, :pet_name, :species, :breed, :pet_age, :is_hypothetical, :clarified, :code_rule, :chosen_section,"
                " :model, :prompt_version, :index_version, :first_token_ms, :latency_ms, :status, :created_at)"),
                log.model_dump(exclude={"scope", "retrieved"}) | {
                    "created_at": log.created_at.replace(tzinfo=None),
                    "payout": None if log.payout is None else json.dumps(log.payout, ensure_ascii=False)})
            if log.scope:
                c.execute(text("INSERT INTO turn_scope (turn_id, section_name, coverage_type, copay, excluded_conditions)"
                               " VALUES (:turn_id, :section_name, :coverage_type, :copay, :excluded_conditions)"),
                          [s.model_dump() | {"turn_id": log.turn_id,
                                             "excluded_conditions": json.dumps(s.excluded_conditions, ensure_ascii=False)}
                           for s in log.scope])
            if log.retrieved:
                c.execute(text(
                    "INSERT INTO retrieved (turn_id, `rank`, via_graph, graph_key, corpus, section, section_name, article_num,"
                    " article_title, coverage_type, paragraph_num, score, content, used, citation_label)"
                    " VALUES (:turn_id, :rank, :via_graph, :graph_key, :corpus, :section, :section_name, :article_num,"
                    " :article_title, :coverage_type, :paragraph_num, :score, :content, :used, :citation_label)"),
                    [r.model_dump() | {"turn_id": log.turn_id} for r in log.retrieved])

    def turns_of(self, session_id: str) -> list[TurnOut]:
        """지난 대화 — 화면에 그릴 턴(오래된 순). 근거 패널은 검색 행(rank 순), 인용은 used 행(검색 → 그래프 순)"""
        with self.engine.connect() as c:
            turns = c.execute(text("SELECT turn_id, question, rewritten_question, follow_up, context_kind, context_turns,"
                                   " pet_id, pet_name, species, answer, payout, latency_ms,"
                                   " first_token_ms, created_at FROM turns WHERE session_id = :sid"
                                   " ORDER BY created_at, turn_id"), dict(sid=session_id)).all()
            scopes = c.execute(text("SELECT sc.turn_id, sc.section_name, sc.coverage_type, sc.copay, sc.excluded_conditions"
                                    " FROM turn_scope sc JOIN turns t USING (turn_id) WHERE t.session_id = :sid"
                                    " ORDER BY sc.id"), dict(sid=session_id)).all()
            rows = c.execute(text("SELECT r.* FROM retrieved r JOIN turns t USING (turn_id)"
                                  " WHERE t.session_id = :sid ORDER BY r.turn_id, r.via_graph, r.`rank`, r.id"),
                             dict(sid=session_id)).all()
        scope: dict[str, list[ScopeRow]] = {}
        for sc in scopes:
            excl = sc.excluded_conditions
            scope.setdefault(sc.turn_id, []).append(ScopeRow(
                section_name=sc.section_name, coverage_type=sc.coverage_type, copay=sc.copay,
                excluded_conditions=json.loads(excl) if isinstance(excl, str) else (excl or [])))
        sources: dict[str, list[SourceItem]] = {}
        refs: dict[str, list[ReferenceItem]] = {}
        for r in rows:
            if not r.via_graph:
                sources.setdefault(r.turn_id, []).append(SourceItem(
                    graph_key=r.graph_key, species=r.corpus, section=r.section, section_name=r.section_name,
                    article_num=r.article_num, article_title=r.article_title, coverage_type=r.coverage_type,
                    score=r.score, content=r.content))
            if r.used:
                refs.setdefault(r.turn_id, []).append(ReferenceItem(
                    citation_label=r.citation_label or "", species=r.corpus, section=r.section,
                    section_name=r.section_name, article_num=r.article_num, paragraph_num=r.paragraph_num))
        return [TurnOut(turn_id=t.turn_id, question=t.question, rewritten_question=t.rewritten_question, follow_up=t.follow_up,
                        context_kind=t.context_kind, context_turns=t.context_turns,
                        pet_id=t.pet_id, pet_name=t.pet_name, species=t.species,
                        scope=scope.get(t.turn_id, []), answer=t.answer, payout=_json(t.payout),
                        sources=sources.get(t.turn_id, []), references=refs.get(t.turn_id, []),
                        latency_ms=t.latency_ms, first_token_ms=t.first_token_ms, timestamp=utc(t.created_at))
                for t in turns]

    def contexts_of(self, turn_id: str) -> list[RetrievedRow]:
        """08 평가 입력 — 그 턴에 모델이 받은 발췌 전부(검색 행 rank 순 → 그래프 행 기록 순)"""
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT `rank`, via_graph, graph_key, corpus, section, section_name, article_num,"
                                  " article_title, coverage_type, paragraph_num, score, content, used, citation_label"
                                  " FROM retrieved WHERE turn_id = :tid ORDER BY via_graph, `rank`, id"),
                             dict(tid=turn_id)).all()
        return [RetrievedRow(**(r._asdict() | {"via_graph": bool(r.via_graph), "used": bool(r.used)})) for r in rows]

    def has_turns(self, session_id: str) -> bool:
        with self.engine.connect() as c:
            return c.execute(text("SELECT 1 FROM turns WHERE session_id = :sid LIMIT 1"),
                             dict(sid=session_id)).first() is not None

    def save_feedback(self, turn_id: str, agent_email: str, body: FeedbackIn) -> bool:
        """그 상담원 세션의 턴이면 평가를 남긴다(다시 누르면 덮어쓴다). 턴이 없거나 남의 것이면 False"""
        with self.engine.begin() as c:
            own = c.execute(text("SELECT 1 FROM turns t JOIN sessions s USING (session_id)"
                                 " WHERE t.turn_id = :tid AND s.agent_email = :agent"),
                            dict(tid=turn_id, agent=agent_email)).first()
            if own is None:
                return False
            c.execute(text("INSERT INTO feedback (turn_id, rating, comment, created_at)"
                           " VALUES (:tid, :rating, :comment, :at) AS new"
                           " ON DUPLICATE KEY UPDATE rating = new.rating, comment = new.comment,"
                           " created_at = new.created_at"),
                      dict(tid=turn_id, rating=body.rating, comment=body.comment, at=now()))
        return True

    def recent_turns(self, session_id: str, n: int) -> list[PriorTurn]:
        """멀티턴의 앞 턴 — 정상으로 끝난(ok) 턴만, 오래된 순으로 최근 n개. 되묻기 대기·취소·실패 턴은 건너뛴다"""
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT question, rewritten_question, answer, pet_id, chosen_section, payout FROM turns"
                                  " WHERE session_id = :sid AND status = 'ok' ORDER BY created_at DESC, turn_id DESC LIMIT :n"),
                             dict(sid=session_id, n=n)).all()
        return [PriorTurn(question=r.question, anchor=r.rewritten_question or r.question, answer=r.answer, pet_id=r.pet_id,
                          chosen_section=r.chosen_section,
                          payout=json.loads(r.payout) if isinstance(r.payout, str) else r.payout) for r in reversed(rows)]
