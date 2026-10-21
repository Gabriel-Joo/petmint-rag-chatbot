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

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, TypeAdapter, computed_field, model_validator

from data.rag_context import infer_type_from_section_name
from data.search_scope import GRADES

Mode = Literal["일반", "사내규정", "업무특화"]
# 멀티턴 처리 종류(09번 5절) — rewrite: 사내규정, 베이스 모델 재작성 / concat: 업무특화, 앞 질문과 이어 붙여 검색 / history: 일반, 이력 전달
ContextKind = Literal["rewrite", "concat", "history"]
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


class Claim(_Model):
    """청구 이력 한 건(insurance_core.claims) — 연간 총 한도에서 이미 받은 금액, Ⅲ MRI가 올해 몇 번째인지를 여기서 센다"""
    claim_id: str
    section_name: str                              # 청구한 의료비 특약(가입 특약 중 하나 — 로더가 검증)
    claim_date: date                               # 청구일
    treatment_date: date                           # 치료(첫날) — 보험연도는 이 날짜로 가른다
    treatment_type: Literal["통원", "입원"]
    days: int                                      # 치료 일수(통원 횟수)
    treatment_cost: int                            # 치료비 합계
    paid: int                                      # 지급액
    surgery: bool = False                          # 수술한 날이 있었다
    mri: bool = False                              # MRI·CT·내시경을 받은 날이 있었다(수술하지 않은 날, 1일로 센다)


class Pet(_Model):
    pet_id: str
    name: str
    species: Species
    breed: str | None = None
    age: int | None = None
    policies: list[Policy]
    claims: list[Claim] = Field(default_factory=list)   # 청구 이력(오래된 순). 계산 카드의 연간 한도·MRI 회차


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
    rewritten_question: str | None = None          # 기준 질문 — 사내규정 재작성 / 업무특화 이어 붙인 앞 질문(09번 5절)
    follow_up: str | None = None                   # 후속으로 본 규칙(followup.follow_up_reason). None이면 단독
    context_kind: ContextKind | None = None
    context_turns: int | None = None               # 일반 — 전달한 이력 턴 수
    answer: str
    payout: dict | None = None                     # 계산 카드(CalcResult.model_dump) 그대로 — 재계산하지 않고 저장한다
    pet_id: str | None = None
    pet_name: str | None = None
    species: Species | None = None
    breed: str | None = None
    pet_age: int | None = None
    is_hypothetical: bool = False                  # 가정 질문(질문에 쓴 등급으로 검색, 09번 4절)
    clarified: bool = False                        # 되묻기 발동(09번 4절)
    chosen_section: str | None = None              # 되묻기로 고르거나 앞 턴에서 이어 쓴 특약
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


class DayRow(_Model):
    """날짜별 계산 한 줄(daycalc.DayOut)"""
    cost: int
    surgery: bool = False
    mri: bool = False
    limit: int                                     # 그날 한도
    label: str                                     # 한도 이름 — 수술한 날 / 수술 안 한 날 / MRI 등 연간 첫 번째…
    payout: int


class MedicalCalc(_Model):
    """의료비 계산 카드(09번 2-3절) — 날마다 (치료비 - 자기부담금) × 보상비율을 그날 한도까지, 합계에 연간 남은 한도(daycalc).
    exact=False면 날짜별 금액을 몰라 범위(range_min~range_max)이고 payout은 고르게 나뉘었다고 본 추정이다.
    days 이하 필드는 2026-10-21 여러 날 계산 전에 저장된 카드에는 없다(기본값 = 하루·정확)"""
    kind: Literal["medical"] = "medical"
    section_name: str
    coverage_type: Grade
    claimed: int                                   # 청구 치료비(합계)
    copay: int                                     # 가입 정보의 자기부담금(1일당)
    limit: int                                     # 수술하지 않은 날 1일 한도(하루면 그날 상황의 한도)
    payout: int                                    # 연간 한도까지 적용한 예상 지급액(범위면 고르게 나뉜 추정)
    note: str
    rate_pct: int | None = None                    # 보상비율(%). 예전 카드엔 없다
    setting: Literal["통원", "입원"] | None = None
    days: int = 1                                  # 일수(통원 횟수)
    days_known: bool = True                        # 일수를 들었다 — False면 일수를 몰라 하루로 계산했다
    exact: bool = True
    day_rows: list[DayRow] = Field(default_factory=list)   # 날짜별 계산(정확하고 2일 이상, 또는 범위에서 금액을 아는 날)
    range_min: int | None = None                   # 범위 — 연간 한도까지 적용
    range_max: int | None = None
    even: int | None = None                        # 고르게 나뉘었다면 — 연간 한도까지 적용
    annual_total: int | None = None                # 연간 총 보상한도
    annual_used: int | None = None                 # 올해(보험연도) 이미 받은 보험금(청구 이력)
    annual_remaining: int | None = None
    year_start: date | None = None                 # 이번 보험연도 시작일
    capped: bool = False                           # 남은 연간 한도에 걸려 줄었다
    mri_before: int | None = None                  # Ⅲ — 올해 이미 받은 MRI·CT·내시경 날 수
    assumptions: list[str] = Field(default_factory=list)   # 계산에 둔 가정(일수를 하루로 봄, 3번 = 서로 다른 3일 …)
    flow: Literal["question", "ask"] = "question"  # ask: 금액 되묻기 흐름에서 코드가 답한 턴(다음 턴에 일수·날짜별 금액을 이어 받는다)


class DayInput(_Model):
    """날짜별 금액 입력칸 하나의 미리 채운 값"""
    cost: int | None = None
    surgery: bool = False
    mri: bool = False


class DaysAskCalc(_Model):
    """날짜별 치료비 되묻기 카드 — 일수 2~5일이고 총액만 받았을 때. 화면이 일수만큼 입력칸(수술한 날·MRI 표시)을 띄우고
    상담원이 채우면 "300,000원(수술), 300,000원, 100,000원" 같은 질문으로 보낸다(멀티턴 — payout.reply_turn이 읽는다)"""
    kind: Literal["days_ask"] = "days_ask"
    section_name: str
    coverage_type: Grade
    setting: Literal["통원", "입원"]
    days: int
    total: int                                     # 앞서 말한 총액
    type: str                                      # Ⅰ/Ⅱ/Ⅲ — Ⅲ이면 MRI 표시도 둔다
    prefill: list[DayInput]                        # 칸마다 미리 채운 값(수술한 날 금액을 들었으면 그 칸)
    surgery_mentioned: bool = False                # 수술했다고 했는데 그날 금액은 모른다
    note: str


class LegalCalc(_Model):
    """법률비용 계산 카드 — 민사소송법률비용 특약 【별표3·4·5】(limit_table, payout.legal_card).
    소송 금액 없이 심급만 말하면 claim_value 이하 금액 칸은 비고 송달료만 있다"""
    kind: Literal["legal"] = "legal"
    section_name: str
    claim_value: int | None                        # 소송목적의 값(질문 속 소송 금액)
    bracket: str | None                            # 【별표3】 적용 구간 — "2,000만원 초과 5,000만원까지 · 200만원 + 초과분 × 8%"
    lawyer_limit: int | None                       # 【별표3】 소송비용에 산입되는 변호사비용
    lawyer_max: int | None                         # 변호사 보수 보험금 최대 = min(별표3 한도, 1소송당 상한)
    lawyer_copay: int                              # 실제 보수에서 빼는 자기부담금(1소송당)
    lawyer_cap: int                                # 변호사비용 1소송당 상한
    stamp: int | None                              # 【별표4】 인지액
    instance: str | None                           # 1심/항소심/상고심
    case_kind: str | None                          # 민사소액/민사단독/민사합의(1심만)
    service: int | None                            # 【별표5】 송달료 — 심급(1심은 사건 종류까지)을 알 때만
    stamp_service_cap: int                         # 인지액+송달료 1소송당 상한
    note: str


class LimitRow(_Model):
    """한도 카드 한 줄 — 가입한 의료비 특약 하나(limit_table.get_limit)"""
    section_name: str
    coverage_type: Grade
    type: str                                      # Ⅰ/Ⅱ/Ⅲ(section_name에서)
    copay: int | None                              # 가입 정보의 자기부담금
    rate_pct: int                                  # 보상비율(%)
    non_surgery: int                               # 수술하지 않은 날 1일 한도(Ⅲ은 MRI·CT·내시경 없는 날)
    surgery: int                                   # 수술한 날 1일 한도
    mri_1st: int | None = None                     # Ⅲ만 — MRI·CT·내시경 연간 첫 번째
    mri_2nd_plus: int | None = None                # Ⅲ만 — 두 번째 이상
    annual_total: int                              # 연간 총 보상한도(특약별)


class LimitsCalc(_Model):
    """한도 카드 — 치료비 금액 없이 한도를 물으면 가입한 의료비 특약의 한도표(payout.limit_card)"""
    kind: Literal["limits"] = "limits"
    pet_name: str
    rows: list[LimitRow]
    highlight: Literal["non_surgery", "surgery", "mri"] | None = None   # 질문이 짚은 줄(수술·MRI 등)
    note: str


def _calc_kind(v) -> str:
    """kind가 없으면 의료비 — 법률비용 카드 전에 저장된 turns.payout에는 kind가 없다"""
    k = v.get("kind") if isinstance(v, dict) else getattr(v, "kind", None)
    return k or "medical"


# 계산 카드 — WS calc 메시지·과거 턴(TurnOut.payout)·turns.payout이 같은 모양. kind로 의료비·법률비용을 가른다
CalcResult = Annotated[Union[Annotated[MedicalCalc, Tag("medical")], Annotated[LegalCalc, Tag("legal")],
                             Annotated[LimitsCalc, Tag("limits")], Annotated[DaysAskCalc, Tag("days_ask")]],
                       Discriminator(_calc_kind)]


class TurnOut(_Model):
    """지난 대화를 다시 열 때 화면에 그릴 턴 — turns·turn_scope·retrieved에서 복원.
    반려동물·가입 내용은 그 턴의 스냅샷이다(12번 2-2절) — 과거 상담 화면은 지금 고객 데이터가 아니라 이 값으로 그린다"""
    turn_id: str
    question: str
    pet_id: str | None
    pet_name: str | None = None
    species: Species | None = None
    scope: list[ScopeRow] = Field(default_factory=list)   # 그때 적용된 특약·등급·자기부담금·부담보
    rewritten_question: str | None = None          # 기준 질문(멀티턴). 단독 질문이면 None
    follow_up: str | None = None
    context_kind: ContextKind | None = None
    context_turns: int | None = None
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


class ContextMsg(_ServerMsg):
    """멀티턴 — 후속 질문을 앞 대화로 어떻게 풀었는지(09번 5절). 후속 질문이면 sources 앞에 한 번.
    rewrite: text = 재작성된 질문 / concat: text = 이어 붙인 앞 질문(기준 질문) / history: turns = 전달한 이력 턴 수"""
    type: Literal["context"] = "context"
    kind: ContextKind
    reason: str                                    # 후속으로 본 규칙
    text: str | None = None
    turns: int | None = None


class CalcMsg(_ServerMsg):
    """계산 카드 — 치료비(의료비)·소송 금액이나 심급(법률비용)·한도(한도표)를 묻는 질문이면 sources 다음에 한 번"""
    type: Literal["calc"] = "calc"
    result: CalcResult


class ExclusionsMsg(_ServerMsg):
    """질문에 걸리는 부담보(payout.matched_exclusions — 분류표·같은 부위 이름까지). 화면 배너가 이것을 쓴다. 걸린 것이 있을 때만"""
    type: Literal["exclusions"] = "exclusions"
    items: list[str]


class ErrorMsg(_ServerMsg):
    """잘못된 메시지·남의 pet_id·검색/생성 실패. 질문 전 오류면 turn_id는 빈 문자열"""
    type: Literal["error"] = "error"
    code: str
    message: str


ServerMessage = Annotated[Union[ContextMsg, SourcesMsg, TokenMsg, ClarifyMsg, ReferencesMsg, CalcMsg, DoneMsg, ErrorMsg,
                                ExclusionsMsg],
                          Field(discriminator="type")]


TurnOut.model_rebuild()                            # SourceItem·ReferenceItem이 뒤에 정의돼 있다
SessionDetail.model_rebuild()
