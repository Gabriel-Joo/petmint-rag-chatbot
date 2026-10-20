"""
prompts.py
펫퍼민트 약관 RAG 프롬프트 — 07(파인튜닝 학습 데이터)·09(서비스 추론)·08(평가)이 공통으로 import하는 "진실의 원천" 모듈.
학습 때 본 형식과 추론 때 받는 형식이 같아야 하므로, 발췌 포맷·시스템 프롬프트·길이 예산 규칙을 여기 한 곳에 둔다.

설계 근거(이전 파인튜닝 시도에서 확인한 것 — 옛 청크·옛 FAQ로 한 별개 작업이라 수치는 참조하지 않는다):
- 발췌 없이 질문→답만 학습하면 사실을 외우려 한다. 발췌 없는 질문에 원문에 없는 사실("특별약관은 5영업일")을 단정했다.
- "발췌만 근거로 답하라"는 지시와 발췌 없는 데이터가 모순이면 지시가 무시된다 → 학습 샘플에도 항상 발췌를 넣는다.
- 고정 패딩(768)으로 계산의 약 2/3가 낭비됐다 → 길이 관리는 동적 패딩 + 아래 fit_to_budget으로.

결정(2026-10-13):
- 학습 샘플 = 정답 발췌 + 방해 발췌 + 일부 답 없음(NO_ANSWER_TEXT). 섞기·고르기는 finetune_data.py, 이 모듈은 포맷만.
- 고객 정보(등급·자기부담금·부담보·가입일)는 프롬프트에 넣지 않는다 — 등급은 검색 필터가, 나머지는 코드·UI가 처리.
  추론 때만 넣으면 학습에 없던 블록이 되므로, 넣으려면 학습 데이터부터 바꿔야 한다(build_messages의 customer 자리).
- 금액 계산은 답변 옆 계산 카드(limit_table)로 분리한다 — 05 측정: 코드 계산표를 프롬프트에 넣으니 오류 16% → 21%.
- "근거:" 표기는 모델이 쓰지 않는다. 학습 목표에서 떼고(strip_citation), 서비스는 rag_context.used_references로 코드가 단다.
- 대화 이력은 프롬프트에 넣지 않는다. 멀티턴은 백엔드가 처리한다(KNOWN_ISSUES "설계 결정: 멀티턴"):
  후속 질문은 베이스 모델(또는 규칙)이 독립 질문으로 재작성하고, 앞 턴 발췌는 이번 items에 함께 넣는다.
  업무특화 모델에는 늘 [발췌 + 완결된 질문 하나]만 간다 → 학습 형식이 그대로 유지된다.
"""

import re
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable

from data.faq_units import main_label, unit_id
from data.rag_context import display_text, graph_key

PROMPT_VERSION = "rag-1"   # 로그·어댑터 디렉토리 이름에 남긴다. 아래 문구·포맷을 바꾸면 올린다

SYSTEM_PROMPT = (
    "당신은 메리츠 펫보험 상담원입니다. 친절한 태도를 유지하되, 반드시 [약관 발췌]에 있는 내용만 근거로 답변하세요. "
    "발췌가 여러 개이면 질문과 관련된 발췌만 쓰고, 관련 없는 발췌는 무시하세요. "
    "발췌에 없는 내용은 추측하거나 단정하지 말고, 발췌에서 확인되지 않는다고 안내하세요. "
    "보험금은 발췌에 있는 계산 예시만 그대로 옮기고, 새 금액으로 직접 계산하지 마세요. "
    "답변은 2~4문장으로 하고, 근거 조항 표기는 쓰지 마세요."
)

# 사내규정 모드(베이스 모델 + 인사규정 RAG, 파인튜닝 없음 — 학습 형식과 맞출 필요가 없어 따로 둔다). 발췌 형식은 같다
# 순서: 찾고 → 적용 → 결론. "결론(금액)을 먼저"이던 때는 근거를 찾기 전에 숫자부터 써서 "금액이 큰 하나만"을 표 전체 최댓값
# (공인회계사 30만원)으로 적용했고(HR3 0/10), 답이 없는 질문도 근무시간 조항으로 유추해 답을 지어냈다(HR5).
# 2026-10-21 같은 발췌로 10회씩 비교 — data/review/hr_answer_fix_survey_20261021.md
SYSTEM_PROMPT_HR = (
    "당신은 펫퍼민트손해보험 인사부서 안내 담당입니다. 반드시 [규정 발췌]에 있는 내용만 근거로 직원의 질문에 답하세요. "
    "먼저 질문에 나온 항목(자격·대상·사유)을 발췌의 표나 조문에서 찾아 그 값을 그대로 옮기고, 그다음 조건·예외 규정을 적용해 "
    "결론을 내리세요. 질문에 나온 대상이 발췌에 직접 나오지 않으면 비슷한 조항으로 유추하지 말고 "
    "'규정에서 확인되지 않습니다. 인사부서에 확인하세요.'라고만 답하세요. 질문과 관계없는 발췌는 언급하지 마세요. "
    "발췌를 하나씩 차례로 설명하지 마세요. 답변은 2~4문장으로 하세요."
)
# "차례로 설명하지 마세요"는 2026-10-21 추가 — 찾고→적용→결론 순서로 바꾼 뒤 발췌를 하나씩 설명하는 답이 늘어
# num_predict 300에서 잘렸다(HR5 거절 문구 전에 끊김). 18문항 × 20회: 넣기 전과 같은 344/360, 가장 긴 답 329 → 309토큰.
# 더 세게 줄이면 역효과였다 — "답에 쓴 내용만 바로 말하라"는 결론부터 쓰던 버릇이 돌아와 표 최댓값을 다시 골랐고(HR3),
# "첫 문장에 값을 옮겨라"는 답이 없는 질문도 근무시간을 옮겨 적었고(구내식당 0/10),
# "답이 없으면 한 문장만"을 끝에 두면 해외 숙박비(HR15)가 3/20으로 떨어졌다. 나쁜 예('[발췌 1]은 …')를 지시에 적으면 오히려 따라 했다.
# 잘림은 프롬프트로 0이 되지 않아 사내규정(과 일반)은 num_predict를 512로 둔다(answer.LLM_OPTIONS_BASE)
HR_EXCERPT_HEADER = "[규정 발췌]"

# 답 없음 샘플(정답 발췌를 뺀 학습 샘플)의 목표 답변 — 추론 때 검색이 실패하면 기대하는 문장과 같다
NO_ANSWER_TEXT = "제공된 약관 발췌에서는 확인되지 않는 내용입니다. 정확한 안내를 위해 추가 확인이 필요합니다."

EXCERPT_HEADER = "[약관 발췌]"   # 이전 시도의 RAG 테스트 표기를 이어받는다
QUESTION_HEADER = "[질문]"
NO_EXCERPT_TEXT = "(검색된 발췌 없음)"

# 05 finalize_answer와 같은 정규식 — 05가 코드로 붙인 "근거: …"를 뗀다
_CITATION_SUFFIX = re.compile(r"\s*근거\s*:.*$", re.DOTALL)


@dataclass
class Reference:
    label: str      # rag_context가 만든 citation_label ("제13조(…) 제1항", "소득세법 제59조의4(…)")
    content: str


@dataclass
class ExcerptItem:
    """발췌 하나. 학습(05 단위)과 추론(검색 결과)이 이 같은 모양으로 수렴한다 — 형식 불일치를 막는 지점."""
    label: str
    content: str
    references: list[Reference] = field(default_factory=list)
    key: str | None = None   # 학습: faq_units.unit_id / 추론: rag_context.graph_key — 로그·중복 판단용, 프롬프트엔 안 나감

    @classmethod
    def from_unit(cls, unit: dict, refs: list[dict]) -> "ExcerptItem":
        """05 FAQ 단위 + resolve_references(unit, sp, source_chunks=unit["records"]) 결과.
        앞 단위에 합친 준용규정(merged_refs)도 05 프롬프트처럼 참조로 붙인다."""
        return cls(label=item_label(unit), content=display_text(unit),
                   references=_references(list(refs) + unit.get("merged_refs", [])), key=unit_id(unit))

    @classmethod
    def from_search_result(cls, r: dict) -> "ExcerptItem":
        """rag_context.build_full_context 결과 한 건(reference_contents 포함)."""
        return cls(label=item_label(r), content=display_text(r),
                   references=_references(r.get("reference_contents", [])), key=graph_key(r))


def _references(refs: Iterable[dict]) -> list[Reference]:
    out, seen = [], set()
    for ref in refs:
        content = (ref.get("content") or "").strip()
        if not content or (ref["citation_label"], content) in seen:
            continue
        seen.add((ref["citation_label"], content))
        out.append(Reference(ref["citation_label"], content))
    return out


def item_label(d: dict) -> str:
    """'펫퍼민트 반려견 통원의료비Ⅱ보장 특별약관 제1조(보험금의 지급사유) 고급형'.
    조번호 없는 단위(안내류·별표)는 main_label이 이미 섹션명이라 그대로. 검색 결과의 article_title은 줄바꿈을 정리한다.
    보통약관은 section_name이 None이라 section을 붙인다 — '제21조'만으로는 일반조항 제21조와 구분되지 않는다."""
    title = (d.get("article_title") or "").replace("\n", " ").strip() or None
    label = main_label({**d, "article_title": title})
    if d.get("article_num") is not None and d.get("section") != "법규":
        label = f"{d.get('section_name') or d['section']} {label}"
    return label


def format_item(n: int, item: ExcerptItem) -> str:
    lines = [f"[발췌 {n}] {item.label}", item.content.strip()]
    for ref in item.references:
        lines += [f"[참조] {ref.label}", ref.content]
    return "\n".join(lines)


def format_excerpt(items: list[ExcerptItem]) -> str:
    if not items:
        return NO_EXCERPT_TEXT
    return "\n\n".join(format_item(i, item) for i, item in enumerate(items, 1))


def build_user_content(question: str, items: list[ExcerptItem], excerpt_header: str = EXCERPT_HEADER) -> str:
    return f"{excerpt_header}\n{format_excerpt(items)}\n\n{QUESTION_HEADER}\n{question.strip()}"


def fit_to_budget(question: str, items: list[ExcerptItem], budget: int, count_tokens: Callable[[str], int],
                  protected: frozenset[int] = frozenset()) -> list[ExcerptItem]:
    """user 메시지(발췌+질문)가 budget 토큰 안에 들도록 줄인다. 학습과 추론이 같은 규칙으로 잘라야 형식이 같다.
    ① 뒤쪽(하위) 발췌의 참조를 끝에서부터 하나씩 뺀다 ② 뒤쪽 발췌를 통째로 뺀다.
    protected(원래 위치 번호 — 학습 시 정답 발췌)는 참조까지 그대로 둔다 — 답의 근거가 참조에 있을 수 있다.
    다 빼도 넘치면 남은 것을 그대로 돌려준다(버릴지는 호출 측이 count_tokens로 다시 재서 판단)."""
    kept = [(i, replace(item, references=list(item.references))) for i, item in enumerate(items)]

    def over() -> bool:
        return count_tokens(build_user_content(question, [it for _, it in kept])) > budget

    while over():
        with_refs = [it for i, it in reversed(kept) if i not in protected and it.references]
        if with_refs:
            with_refs[0].references.pop()
            continue
        droppable = [k for k, (i, _) in enumerate(kept) if i not in protected]
        if not droppable:
            break
        kept.pop(droppable[-1])
    return [it for _, it in kept]


def build_messages(question: str, items: list[ExcerptItem], *, budget: int | None = None,
                   count_tokens: Callable[[str], int] | None = None, protected: frozenset[int] = frozenset(),
                   customer: dict | None = None, history: list[dict] | None = None,
                   system: str = SYSTEM_PROMPT, excerpt_header: str = EXCERPT_HEADER) -> list[dict]:
    """추론용 chat 메시지. budget은 user 메시지 토큰 상한(시스템 프롬프트·생성 길이는 호출 측이 num_ctx에서 뺀다)."""
    if customer is not None:
        # 고객 정보는 프롬프트에 넣지 않기로 했다(모듈 docstring). 넣으려면 학습 데이터에 같은 블록을 먼저 넣어야 한다
        raise NotImplementedError("고객 정보 블록은 학습 데이터에 없다 — 검색 필터·계산 카드·UI 배너로 처리할 것")
    if history is not None:
        # 대화 이력도 넣지 않는다(모듈 docstring). 넣으려면 이력이 든 학습 샘플로 재학습해야 한다
        raise NotImplementedError("대화 이력은 학습 데이터에 없다 — 베이스 모델로 독립 질문 재작성 + 앞 턴 발췌를 items에 추가할 것")
    if budget is not None:
        if count_tokens is None:
            raise ValueError("budget을 쓰려면 count_tokens가 필요하다")
        items = fit_to_budget(question, items, budget, count_tokens, protected)
    # system·excerpt_header: 사내규정 모드는 SYSTEM_PROMPT_HR·HR_EXCERPT_HEADER. 업무특화(파인튜닝) 모드는 기본값만 쓸 것
    return [{"role": "system", "content": system},
            {"role": "user", "content": build_user_content(question, items, excerpt_header)}]


def build_training_messages(question: str, answer: str, items: list[ExcerptItem], **kwargs) -> list[dict]:
    """학습 샘플 = 추론 메시지 + 목표 답변("근거:" 제거). 답 없음 샘플은 answer=NO_ANSWER_TEXT로 부른다.
    loss는 assistant 토큰에만 걸 것(07) — 발췌에 걸면 약관 원문을 외우는 학습이 된다."""
    return build_messages(question, items, **kwargs) + [{"role": "assistant", "content": strip_citation(answer)}]


def strip_citation(answer: str) -> str:
    return _CITATION_SUFFIX.sub("", answer).strip()
