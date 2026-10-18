"""
verify_cases.py
모드 검증 질문 묶음과 판정 기준(docs/모드검증.md와 같은 내용). 실행 코드(verify_modes.py)는 모드와 무관하게 이것만 읽는다.
문서를 고치면 여기도 고친다 — `python -m scripts.verify_modes --check-doc`이 질문 문장이 문서에 있는지 대조한다.

판정 기준 칸:
- must_include: 묶음마다 하나는 답변에 있어야 한다(묶음 안은 any-of, 묶음끼리는 and). 공백·쉼표를 지우고 비교한다
- must_not_include: 하나라도 있으면 실패(예: 자격수당을 더한 25만원)
- suspect_include: 있으면 '확인 필요'로 표시만(실패 아님 — 다른 표 행과 섞였을 수 있다)
- expect_refusal: 거절 문구(REFUSAL_PHRASES)가 나와야 한다
- expect_articles: 출처 패널(sources)에 이 조번호가 모두 있어야 한다
- sources_empty: 출처 패널이 비어 있어야 한다(일반 모드)
- corpus_only: 출처 패널의 코퍼스가 전부 이것이어야 한다(모드가 섞이지 않는가)
- session: 같은 값이면 한 세션(WS)에서 차례로 묻는다 — 멀티턴 검증 자리. None이면 질문마다 새 세션
- human: 사람이 볼 것 — 출력에 표시만 한다
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    expect: str                                          # 문서의 정답·보는 것(사람이 읽을 문장)
    must_include: tuple[tuple[str, ...], ...] = ()
    must_not_include: tuple[str, ...] = ()
    suspect_include: tuple[str, ...] = ()
    expect_refusal: bool = False
    expect_articles: tuple[int, ...] = ()
    sources_empty: bool = False
    corpus_only: str | None = None
    session: str | None = None
    pet_id: str | None = None                            # 업무특화만 — 세션 고객의 반려동물
    human: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModeSpec:
    key: str                                             # CLI --mode 값
    mode: str                                            # 서버 모드 이름(세션 생성 body)
    model: str                                           # 서버가 쓸 모델(기록용 — 서버 설정이 정한다)
    corpus: str | None                                   # 검색 코퍼스(기록용). 일반은 None
    order: str                                           # 메시지 순서 규약(verify_modes.ORDER_RULES의 키)
    cases: tuple[Case, ...]
    needs_customer: bool = False                         # 업무특화 — 세션에 customer_id, 질문에 pet_id


# 거절로 볼 문구 — 학습 목표 NO_ANSWER_TEXT(prompts.py)와 사내규정 시스템 프롬프트("인사부서에 확인")에서 온 것 + 흔한 변형.
# 문구 기준 자동 판정이라 사람이 한 번 더 본다
REFUSAL_PHRASES = ("확인되지 않", "확인되지않", "명시되어 있지 않", "명시되어있지않", "나와 있지 않", "규정에 없", "약관에 없",
                   "찾을 수 없", "포함되어 있지 않", "언급되어 있지 않", "인사부서에 확인", "인사부서에 문의")

HUMAN_MATCH = "답변 내용이 조항과 맞는가"

HR = ModeSpec(key="hr", mode="사내규정", model="PETMINT_MODEL_BASE(기본 tri-7b)", corpus="인사규정", order="plain", cases=(
    Case("HR1", "재택근무는 주에 며칠까지 할 수 있나요?",
         "주 2일, 임신 중이거나 만 8세 이하 자녀를 양육하면 주 3일 (제14조 제2항) — 예외 조건까지 말하는가",
         must_include=(("2일", "이틀"), ("3일", "사흘")), expect_articles=(14,), corpus_only="인사규정",
         human=(HUMAN_MATCH, "예외 조건(임신·만 8세 이하 자녀)을 말하는가 — '3일'은 '3일 전까지 신청'에서도 나올 수 있다")),
    Case("HR2", "배우자가 출산하면 휴가 며칠 나오나요?",
         "10일 (제19조 표 '출산 / 배우자 / 10일') — 표 숫자가 살아 있는가, 다른 행과 안 섞이는가",
         must_include=(("10일", "열흘"),), suspect_include=("5일", "1일", "3일"), expect_articles=(19,), corpus_only="인사규정",
         human=(HUMAN_MATCH, "다른 행(결혼 5일·사망 5일 등)과 섞이지 않았는가")),
    Case("HR3", "손해사정사랑 정보처리기사 둘 다 있으면 자격수당 얼마예요?",
         "월 20만원 — 금액이 큰 하나만 (제27조 제2항) — 25만원으로 더하면 실패",
         must_include=(("20만원", "200000원"),), must_not_include=("25만원", "250000원"), expect_articles=(27,),
         corpus_only="인사규정", human=(HUMAN_MATCH,)),
    Case("HR4", "병가를 다 쓰고도 더 쉬어야 하면 어떻게 하나요?",
         "질병휴직 1년 이내, 무급 (제20조 병가 · 제22조 휴직 표) — 검색이 둘 다 가져왔는가(잇지 못해도 실패 아님)",
         must_include=(("1년",), ("무급",)), expect_articles=(20, 22), corpus_only="인사규정",
         human=(HUMAN_MATCH, "두 조항을 잇는가 — 참조 간선이 없어 못 이어도 실패 아님")),
    Case("HR5", "회사 주차장은 몇 시까지 쓸 수 있나요?",
         "규정에 없음 → 거절 — 지어내지 않는가",
         expect_refusal=True, corpus_only="인사규정", human=("시간·장소를 지어내지 않았는가",)),
    Case("HR6", "통원 치료비 한도가 얼마예요?",
         "인사규정에 없음 → 거절 — 모드가 섞이지 않는가",
         expect_refusal=True, must_not_include=("30만원", "300000원", "15만원", "150000원", "10만원", "100000원"),
         corpus_only="인사규정", human=("약관 숫자(통원 한도)를 말하지 않았는가",)),
))

GENERAL = ModeSpec(key="general", mode="일반", model="PETMINT_MODEL_BASE(기본 tri-7b)", corpus=None, order="plain", cases=(
    Case("G1", "파이썬에서 리스트랑 튜플 차이가 뭐야?",
         "출처 패널이 비어 있어야 정상", sources_empty=True, session="g-tuple",
         human=("설명이 맞는가",)),
    Case("G2", "반려견 통원 치료비 한도가 얼마야?",
         "약관인 척 숫자를 지어내는지 관찰(통과/실패 아님)", sources_empty=True,
         human=("관찰: 숫자를 지어냈는가, 지어냈다면 무엇을(출력의 '답변 속 금액' 참고)",)),
    Case("G3", "쿠버네티스가 뭔지 자세히 설명해줘",
         "스트리밍이 끊기지 않는가", sources_empty=True,
         human=("끝까지 흘렀는가 — 300토큰(num_predict)에서 끊기는 것은 정상",)),
    Case("G4", "그럼 언제 튜플을 써?",
         "(G1 뒤, 같은 세션) 앞 대화를 기억하지 못하는 것이 기대 결과(멀티턴 없음)", sources_empty=True, session="g-tuple",
         human=("앞 대화를 기억하지 못하는가 — 기억했다면 어디서 이력이 들어갔는지 본다",)),
))

# 업무특화 — 저녁에 어댑터를 바꾼 뒤 채운다. 질문마다 pet_id를 두거나 --pet으로 한꺼번에 준다(세션 고객은 --customer)
RAG = ModeSpec(key="rag", mode="업무특화", model="PETMINT_MODEL_RAG(기본 tri-7b-rag-1)", corpus="강아지/고양이(pet의 종)",
               order="rag", needs_customer=True, cases=())

MODES = {m.key: m for m in (HR, GENERAL, RAG)}
