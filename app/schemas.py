"""
schemas.py
09 UI 데이터 모델 — 고객(6-1)·세션(6-2)·턴 로그(6-3)·REST 본문(7-1)·WS 메시지(7-2).

- 모든 모델은 extra="forbid": 설계에 없는 필드가 조용히 들어오지 않게 한다
  (Policy에 type을 넣거나, 세션에 pet_id를, 로그에 이름·전화번호를 넣으면 검증에서 막힌다).
- Policy.type은 저장하지 않고 section_name에서 계산한다(6-1) — 값을 두 곳에 두면 어긋날 수 있다.
- WS 메시지는 type으로 구분하는 discriminated union. 서버 → 클라이언트 메시지는 전부 turn_id를 가진다(6-3).
"""

from datetime import date, datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, computed_field, model_validator

from data.rag_context import infer_type_from_section_name
from data.search_scope import GRADES

Mode = Literal["일반", "사내규정", "업무특화"]
Species = Literal["강아지", "고양이"]
Grade = Literal[GRADES]           # 고급형 / 기본형 / 실속형
Corpus = Literal["강아지", "고양이", "인사규정"]   # 검색 코퍼스. 사내규정 근거는 인사규정이라 Species로는 못 담는다


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ----- 6-1 고객 -----

class Policy(_Model):
    """가입 특약 하나. 등급은 특약마다 따로 정의되므로 특약 단위로 둔다.
    약관 식별자(doc_id·product_name·policy_version)는 같은 상품의 개정판을 구별하려고 둔다 — 값은 청크 메타와 같아야 한다.
    effective_date·expiry_date는 약관 문서의 속성이라 복사하지 않는다(개정 시 어긋남). 필요하면 doc_id로 청크 메타에서 조회"""
    doc_id: str                                    # 청크 doc_id(예: petmint_dog_2604). 아직 검색 필터로는 쓰지 않는다
    product_name: str
    policy_version: str
    section_name: str                              # 그 약관 청크의 section_name과 같은 문자열(로더가 검증)
    coverage_type: Grade | None = None             # 의료비 특약만. 검색 필터 + 계산 카드
    copay: int | None = None                       # 자기부담금(3만/5만). 계산 카드
    contract_date: date                            # 보장개시·면책기간 판단. 약관 effective_date 이후여야 한다(로더가 검증)
    renewal: str | None = None
    excluded_conditions: list[str] = Field(default_factory=list)   # 부담보. 코드가 질문과 대조해 배너

    @computed_field
    @property
    def type(self) -> str | None:
        """유형(Ⅰ/Ⅱ/Ⅲ) — section_name에서 계산. 의료비 특약이 아니면 None"""
        return infer_type_from_section_name(self.section_name)


class Pet(_Model):
    pet_id: str
    name: str
    species: Species
    breed: str | None = None
    age: int | None = None
    policies: list[Policy]


class Customer(_Model):
    customer_id: str
    name: str
    phone: str
    pets: list[Pet] = Field(min_length=1)

    @computed_field
    @property
    def card(self) -> Literal["둘 다 보유", "강아지만", "고양이만"]:
        """2-2 고객 조회 카드 종류 — '둘 다 보유'일 때만 상담 화면에 종 토글이 뜬다"""
        species = {p.species for p in self.pets}
        if len(species) == 2:
            return "둘 다 보유"
        return "강아지만" if species == {"강아지"} else "고양이만"


# ----- 6-2 세션 (MySQL sessions, 12번) -----

class SessionTurn(_Model):
    """대화 문맥(5절 재작성·앞 턴 발췌 이월)에 쓰는 앞 턴 하나 — turns·retrieved에서 복원한다"""
    turn_id: str
    pet_id: str | None                             # 6-2: pet_id는 세션이 아니라 메시지(턴)에 담는다
    question: str
    rewritten_question: str | None = None          # 5절 재작성 결과
    answer: str | None = None
    source_keys: list[str] = Field(default_factory=list)   # 답변이 쓴 근거(retrieved.used)의 graph_key


class Session(_Model):
    session_id: str
    mode: Mode
    customer_id: str | None                        # 업무특화만. 일반·사내규정은 고객 조회를 거치지 않는다
    agent_email: str                               # 13번: Cf-Access 헤더. 지난 채팅 필터·책임 추적
    title: str | None = None                       # 첫 질문 요약. 질문 전에는 None이고 목록에 안 나온다
    pinned: bool = False
    started_at: datetime
    ended_at: datetime | None = None               # 업무특화만 채운다. NULL = 이어 쓸 수 있다
    deleted_at: datetime | None = None             # 목록에서 제거(12번 1-4절). 로그는 남는다


# ----- 6-3 턴 로그 (MySQL turns·turn_scope·retrieved, 12번) -----
# 고객 이름·전화번호는 넣지 않는다(extra=forbid로 막힘). 반려동물·가입 내용은 그 턴의 스냅샷이다(12번 2-2절)

class ScopeRow(_Model):
    """turn_scope 한 줄 — 그 턴에 적용된 특약 하나. 가정 질문이면 질문에 쓴 등급이 들어간다"""
    section_name: str
    coverage_type: Grade | None = None
    copay: int | None = None
    excluded_conditions: list[str] = Field(default_factory=list)


class RetrievedRow(_Model):
    """retrieved 한 줄 — 모델이 받은 발췌 하나(12번 1-1절). 두 종류다.
    검색 행(via_graph=False): 벡터 검색 결과. graph_key가 조문 식별 기준이고 rank·section·score가 반드시 있다.
    그래프 행(via_graph=True): 참조 그래프로 따라간 조문·법령 박스. 청크가 아니라 rank·graph_key·section·score가 없을 수 있다 —
      content·article_title·citation_label로 읽고, 법령 박스는 citation_label로 식별한다.
    DB의 CHECK(ck_retrieved_kind)와 같은 규칙을 여기서도 먼저 본다"""
    rank: int | None = None                        # 검색 순위(0부터). 그래프 행은 None
    via_graph: bool = False
    graph_key: str | None = None                   # rag_context.graph_key — Milvus auto_id는 재색인하면 바뀐다
    corpus: Corpus
    section: str | None = None
    section_name: str | None
    article_num: int | None
    article_title: str | None = None
    coverage_type: Grade | None = None
    paragraph_num: int | None = None
    score: float | None = None                     # 검색 점수. 그래프 행은 None
    content: str                                   # 08 Ragas 컨텍스트 — 재색인 뒤에도 그때 본 것이 남는다
    used: bool = False                             # 답변이 실제로 쓴 근거
    citation_label: str | None = None              # 검색 행은 used일 때만, 그래프 행은 늘(인용 표기이자 식별)

    @model_validator(mode="after")
    def _kind(self) -> "RetrievedRow":
        if self.via_graph:
            if self.rank is not None:
                raise ValueError("그래프 행은 rank가 없다")
        elif None in (self.rank, self.graph_key, self.section, self.score):
            raise ValueError("검색 행은 rank·graph_key·section·score가 있어야 한다")
        return self


class TurnLog(_Model):
    """한 턴의 기록. 세션 쪽 값(mode·customer_id·agent_email)은 sessions에 있으므로 여기 두지 않는다"""
    turn_id: str
    session_id: str
    question: str
    rewritten_question: str | None = None
    answer: str
    payout: dict | None = None                     # 계산 카드(CalcResult.model_dump) 그대로 — 재계산하지 않고 저장한다
    pet_id: str | None = None
    pet_name: str | None = None
    species: Species | None = None
    breed: str | None = None
    pet_age: int | None = None
    is_hypothetical: bool = False                  # 가정 질문(질문에 쓴 등급으로 검색, 09번 4절)
    clarified: bool = False                        # 되묻기 발동(09번 4절). 기록 경로는 되묻기 구현 때 붙인다
    scope: list[ScopeRow] = Field(default_factory=list)       # 일반·사내규정은 비어 있다
    retrieved: list[RetrievedRow] = Field(default_factory=list)
    model: str
    prompt_version: str
    index_version: str
    first_token_ms: int | None = None
    latency_ms: int
    status: Literal["ok", "cancelled", "error"] = "ok"
    created_at: datetime


# ----- 7-1 REST -----

class SessionCreate(_Model):
    mode: Mode
    customer_id: str | None = None                 # 업무특화면 필수


class SessionOut(_Model):
    session_id: str
    mode: Mode
    customer_id: str | None
    started_at: datetime


class SessionSummary(_Model):
    """GET /api/sessions 목록 한 줄(지난 채팅)"""
    session_id: str
    mode: Mode
    title: str
    pinned: bool
    started_at: datetime
    last_active_at: datetime                       # 마지막 턴 시각(턴이 없으면 started_at). 정렬·상대 시간 기준


class SessionPatch(_Model):
    """PATCH /api/sessions/{id} — 보낸 필드만 바꾼다"""
    title: str | None = Field(default=None, max_length=200)
    pinned: bool | None = None


class CalcResult(_Model):
    """계산 카드(09번 2-3절) — limit_table.calculate_payout 결과. WS calc 메시지·과거 턴(TurnOut.payout)·turns.payout이 같은 모양"""
    section_name: str
    coverage_type: Grade
    claimed: int                                   # 청구 치료비(질문 속 금액)
    copay: int                                     # 가입 정보의 자기부담금
    limit: int                                     # 그 상황의 1일 지급 한도
    payout: int
    note: str


class TurnOut(_Model):
    """지난 대화를 다시 열 때 화면에 그릴 턴 — turns·turn_scope·retrieved에서 복원.
    반려동물·가입 내용은 그 턴의 스냅샷이다(12번 2-2절) — 과거 상담 화면은 지금 고객 데이터가 아니라 이 값으로 그린다"""
    turn_id: str
    question: str
    pet_id: str | None
    pet_name: str | None = None
    species: Species | None = None
    scope: list[ScopeRow] = Field(default_factory=list)   # 그때 적용된 특약·등급·자기부담금·부담보
    answer: str
    payout: CalcResult | None = None               # 그 턴의 계산 카드(turns.payout). 없으면 None
    sources: list["SourceItem"]
    references: list["ReferenceItem"]
    latency_ms: int | None
    first_token_ms: int | None
    timestamp: datetime


class SessionDetail(SessionOut):
    """GET /api/sessions/{id} — 세션과 그 턴(오래된 순). 고객이 있는 세션은 남의 것도 열린다(09번 7-1절) —
    agent_email로 누가 안내한 내용인지 보인다. 연 쪽에서는 소유자와 무관하게 읽기 전용이다"""
    agent_email: str                               # 그 상담을 담당했던 상담원
    title: str | None
    pinned: bool
    ended_at: datetime | None
    turns: list[TurnOut]


class CustomerSessionSummary(_Model):
    """GET /api/customers/{id}/sessions 한 줄 — 그 고객의 과거 상담(09번 2-2절)"""
    session_id: str
    mode: Mode
    title: str
    agent_email: str                               # 담당 상담원 — 남이 받은 상담도 목록에 있다
    started_at: datetime
    ended_at: datetime | None                      # None이면 아직 진행 중(누군가 통화 중이거나 종료 없이 닫힘)


class RecentConsultation(_Model):
    """고객별 마지막 상담 시각 — 고객 조회 '최근 상담' 탭"""
    customer_id: str
    last_consulted_at: datetime


class ArticleOut(_Model):
    species: Species
    section: str
    section_name: str | None
    article_num: int | None
    coverage_type: Grade | None = None
    paragraph_num: int | None = None
    content: str


class FeedbackIn(_Model):
    rating: Literal["up", "down"]
    comment: str | None = None


class FeedbackOut(_Model):
    turn_id: str
    accepted: bool


# ----- 7-2 WebSocket: 클라이언트 → 서버 -----

class QuestionMsg(_Model):
    type: Literal["question"]
    text: str = Field(min_length=1)
    pet_id: str | None = None                      # 업무특화면 필수 — 서버가 세션 고객의 반려동물인지 검증


class CancelMsg(_Model):
    type: Literal["cancel"]


class ClarifyAnswerMsg(_Model):
    type: Literal["clarify_answer"]
    turn_id: str
    choice: str


ClientMessage = Annotated[Union[QuestionMsg, CancelMsg, ClarifyAnswerMsg], Field(discriminator="type")]
client_message_adapter = TypeAdapter(ClientMessage)


# ----- 7-2 WebSocket: 서버 → 클라이언트 (전부 turn_id를 가진다) -----

class SourceItem(_Model):
    """근거 패널 한 줄. 구조 경로(species~article_num)로 /api/articles 원문을 연다"""
    graph_key: str
    species: Corpus                                # 이름은 species지만 코퍼스 값이다(KNOWN_ISSUES: corpus로 이름 변경)
    section: str
    section_name: str | None
    article_num: int | None
    article_title: str | None = None
    coverage_type: Grade | None = None
    score: float
    content: str


class ReferenceItem(_Model):
    """답변이 실제로 쓴 근거(rag_context.used_references)"""
    citation_label: str
    species: Corpus
    section: str | None                            # 법령 박스(그래프로 따라간 약관 밖 법령)는 None
    section_name: str | None
    article_num: int | None
    paragraph_num: int | None = None


class _ServerMsg(_Model):
    turn_id: str


class SourcesMsg(_ServerMsg):
    type: Literal["sources"] = "sources"
    items: list[SourceItem]


class TokenMsg(_ServerMsg):
    type: Literal["token"] = "token"
    text: str


class ClarifyMsg(_ServerMsg):
    type: Literal["clarify"] = "clarify"
    options: list[str]


class ReferencesMsg(_ServerMsg):
    type: Literal["references"] = "references"
    items: list[ReferenceItem]


class DoneMsg(_ServerMsg):
    type: Literal["done"] = "done"
    latency_ms: int
    first_token_ms: int | None = None


class CalcMsg(_ServerMsg):
    """계산 카드 — 치료비가 들어간 질문이면 sources 다음에 한 번"""
    type: Literal["calc"] = "calc"
    result: CalcResult


class ErrorMsg(_ServerMsg):
    """잘못된 메시지·남의 pet_id·검색/생성 실패. 질문 전 오류면 turn_id는 빈 문자열"""
    type: Literal["error"] = "error"
    code: str
    message: str


ServerMessage = Annotated[Union[SourcesMsg, TokenMsg, ClarifyMsg, ReferencesMsg, CalcMsg, DoneMsg, ErrorMsg],
                          Field(discriminator="type")]


TurnOut.model_rebuild()                            # SourceItem·ReferenceItem이 뒤에 정의돼 있다
SessionDetail.model_rebuild()
