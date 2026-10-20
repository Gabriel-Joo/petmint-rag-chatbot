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
- expect_context: 멀티턴 처리 종류(context 메시지). 같은 session 값의 앞 질문 뒤에 묻는다
- expect_calc: 계산 카드 종류("medical"/"legal"/"limits", 카드가 없어야 하면 "none").
  calc_values: 그 카드의 필드 값(예: lawyer_limit=2800000, 한도표 줄은 rows.0.non_surgery처럼 점으로)
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
    expect_calc: str | None = None                       # 업무특화만 — "medical" 의료비 / "legal" 법률비용 / "limits" 한도표 / "none" 없음
    calc_values: tuple[tuple[str, int | str | None], ...] = ()
    expect_context: str | None = None                    # 멀티턴 — "rewrite"/"concat"/"history"(후속), "none"(단독으로 처리)
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
# 규정에 없는 질문의 금지 값 — 비교 전에 공백·쉼표를 지운다(norm). 시각: 근무시간·휴게시간으로 유추한 답, 금액: 다른 조의 금액을 끌어온 답
TIMES = ("오전", "오후", "6시", "9시", "12시", "1시", "18시")
AMOUNTS = ("만원", "000원")

HR = ModeSpec(key="hr", mode="사내규정", model="PETMINT_MODEL_BASE(기본 tri-7b)", corpus="인사규정", order="plain", cases=(
    Case("HR1", "재택근무는 주에 며칠까지 할 수 있나요?",
         "주 2일, 임신 중이거나 만 8세 이하 자녀를 양육하면 주 3일 (제14조 제2항) — 예외 조건까지 말하는가",
         must_include=(("2일", "이틀"), ("3일", "사흘")), expect_articles=(14,), corpus_only="인사규정",
         human=(HUMAN_MATCH, "예외 조건(임신·만 8세 이하 자녀)을 말하는가 — '3일'은 '3일 전까지 신청'에서도 나올 수 있다")),
    Case("HR2", "배우자가 출산하면 휴가 며칠 나오나요?",
         "10일 (제19조 표 '출산 / 배우자 / 10일') — 표 숫자가 살아 있는가, 다른 행과 안 섞이는가",
         must_include=(("10일", "열흘"),), must_not_include=("제44조", "해고"), suspect_include=("5일", "1일", "3일"),
         expect_articles=(19,), corpus_only="인사규정",
         human=(HUMAN_MATCH, "다른 행(결혼 5일·사망 5일 등)과 섞이지 않았는가")),
    Case("HR3", "손해사정사랑 정보처리기사 둘 다 있으면 자격수당 얼마예요?",
         "월 20만원 — 금액이 큰 하나만 (제27조 제2항) — 25만원으로 더하거나 표 전체 최댓값(공인회계사 30만원·변호사 40만원)을 고르면 실패",
         must_include=(("20만원", "200000원"),),
         must_not_include=("25만원", "250000원", "30만원", "300000원", "40만원", "400000원"), expect_articles=(27,),
         corpus_only="인사규정", human=(HUMAN_MATCH,)),
    Case("HR4", "병가를 다 쓰고도 더 쉬어야 하면 어떻게 하나요?",
         "질병휴직 1년 이내, 무급 (제20조 병가 · 제22조 휴직 표) — 검색이 둘 다 가져왔는가(잇지 못해도 실패 아님)",
         must_include=(("1년",), ("무급",)), expect_articles=(20, 22), corpus_only="인사규정",
         human=(HUMAN_MATCH, "두 조항을 잇는가 — 참조 간선이 없어 못 이어도 실패 아님")),
    Case("HR5", "회사 주차장은 몇 시까지 쓸 수 있나요?",
         "규정에 없음 → 거절 — 지어내지 않는가(근무시간 9시~6시로 유추하면 실패)",
         expect_refusal=True, must_not_include=TIMES, corpus_only="인사규정", human=("시간·장소를 지어내지 않았는가",)),
    Case("HR6", "통원 치료비 한도가 얼마예요?",
         "인사규정에 없음 → 거절 — 모드가 섞이지 않는가",
         expect_refusal=True, must_not_include=("30만원", "300000원", "15만원", "150000원", "10만원", "100000원"),
         corpus_only="인사규정", human=("약관 숫자(통원 한도)를 말하지 않았는가",)),
    # ---- 2026-10-21 추가 — 표(HR7~10) · 규정에 없음(HR11~13) · 여러 조항(HR14~18). 정답은 data/chunks/hr_인사규정.json ----
    Case("HR7", "과장이 출장 가서 하루 자면 숙박비 얼마까지 나와요?",
         "1박 120,000원 (별표1 '차장·과장') — 부장 150,000원·대리 100,000원 행과 안 섞이는가",
         must_include=(("120000원", "12만원"),), must_not_include=("150000원", "15만원"), suspect_include=("100000원", "10만원"),
         corpus_only="인사규정", human=(HUMAN_MATCH,)),
    Case("HR8", "할머니가 돌아가시면 경조휴가 며칠이에요?",
         "3일 (제19조 표 '사망 / 본인 및 배우자의 조부모, 형제자매 / 3일') — 부모 사망 5일과 안 섞이는가",
         must_include=(("3일", "사흘"),), must_not_include=("5일",), expect_articles=(19,), corpus_only="인사규정",
         human=(HUMAN_MATCH,)),
    Case("HR9", "개인정보보호 교육은 1년에 몇 시간 들어야 해요?",
         "연 2시간 (제30조 표) — 성희롱 예방 1시간·산업안전 분기별 3시간과 안 섞이는가",
         must_include=(("2시간", "두시간"),), suspect_include=("1시간", "3시간"), expect_articles=(30,), corpus_only="인사규정",
         human=(HUMAN_MATCH,)),
    Case("HR10", "대리에서 과장 되려면 최소 몇 년 있어야 해요?",
         "4년 (제33조 ② 표 '대리 → 과장') — 현저한 공적이면 특별승진 가능(④)",
         must_include=(("4년",),), must_not_include=("5년",), expect_articles=(33,), corpus_only="인사규정",
         human=(HUMAN_MATCH, "특별승진(④)을 말하는가 — 안 말해도 실패 아님")),
    Case("HR11", "사내 동호회 활동비 지원되나요?",
         "규정에 없음 → 거절 — 자기계발 지원(제31조) 금액을 끌어오면 실패",
         expect_refusal=True, must_not_include=AMOUNTS, corpus_only="인사규정",
         human=("동호회 지원을 지어내지 않았는가",)),
    Case("HR12", "회사 구내식당은 몇 시에 열어요?",
         "규정에 없음 → 거절 — 휴게시간(오후 12시~1시)으로 유추하면 실패",
         expect_refusal=True, must_not_include=TIMES, corpus_only="인사규정",
         human=("식당 시간을 지어내지 않았는가",)),
    Case("HR13", "명절 상여금은 얼마나 나와요?",
         "규정에 없음 → 거절 — 제24조는 상여금이 급여 구성이라고만 한다(금액·명절 없음)",
         expect_refusal=True, must_not_include=AMOUNTS + ("%", "퍼센트"), corpus_only="인사규정",
         human=("금액·지급률을 지어내지 않았는가",)),
    Case("HR14", "육아휴직 다녀오면 그 기간도 근속연수에 들어가요?",
         "들어간다 — 육아휴직·병역휴직은 근속연수에 산입 (제22조 ④, 제3조 5호가 제22조를 따른다)",
         must_include=(("산입한다", "산입됩니다", "산입되", "포함됩니다", "포함되", "들어갑니다", "들어가요"),),
         expect_articles=(22,), corpus_only="인사규정",
         human=(HUMAN_MATCH, "'그 밖의 휴직은 산입하지 않는다'와 뒤바꾸지 않았는가")),
    Case("HR15", "해외 출장 가면 대리 숙박비는 얼마까지예요?",
         "1박 200,000원 한도 — 대리·사원 100,000원의 2배 (별표1 ※ 해외출장) — 표 값과 각주를 같이 써야 한다",
         must_include=(("200000원", "20만원"),), must_not_include=("300000원", "30만원", "240000원", "24만원"),
         corpus_only="인사규정", human=(HUMAN_MATCH, "지역별 별도 기준이 있다는 말을 하는가")),
    Case("HR16", "징계 받은 게 억울하면 며칠 안에 재심 청구해야 해요?",
         "통지받은 날부터 14일 이내 (제39조 ①) — 인사평가 재심 7일(제32조 ④)과 섞이지 않는가",
         must_include=(("14일",),), suspect_include=("7일",), expect_articles=(39,), corpus_only="인사규정",
         human=(HUMAN_MATCH,)),
    Case("HR17", "임신 중인데 재택근무는 며칠까지 되고 야근은 해야 하나요?",
         "재택 주 3일까지(제14조 ②) + 연장·야간근로를 시키지 않는다(제12조 ④) — 두 조항을 잇는가",
         must_include=(("3일", "사흘"), ("시키지", "하지 않", "할 수 없", "금지", "안 해도")),
         expect_articles=(14, 12), corpus_only="인사규정", human=(HUMAN_MATCH, "두 조항을 다 말하는가")),
    Case("HR18", "정직 처분을 받으면 언제부터 다시 승진할 수 있어요?",
         "처분일부터 2년간 승진 대상에서 제외 (제36조 ② 3호) — 견책 6개월·감급 1년·강등 3년과 안 섞이는가",
         must_include=(("2년",),), suspect_include=("6개월", "3년"), expect_articles=(36,), corpus_only="인사규정",
         human=(HUMAN_MATCH,)),
    # ---- 멀티턴(2026-10-21) — 같은 세션에서 차례로. 후속은 베이스 모델이 재작성한다 ----
    Case("HR19", "재택근무는 며칠까지 돼요?", "멀티턴 앞 질문 — 주 2일(임신·만 8세 이하 자녀 양육은 주 3일)",
         must_include=(("2일", "이틀"),), corpus_only="인사규정", session="hr-mt"),
    Case("HR20", "그럼 신청은 언제까지 해야 돼요?",
         "(HR19 뒤) 재택근무 신청 — 근무 예정일 3일 전까지(제14조 ③). ↳ 재작성된 질문에 '재택근무'가 들어가는가",
         must_include=(("3일전", "3일 전"),), expect_articles=(14,), corpus_only="인사규정", session="hr-mt", expect_context="rewrite",
         human=("재작성된 질문이 재택근무 신청을 묻는가",)),
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
         human=("끝까지 흘렀는가 — 512토큰(num_predict)에서 끊기는 것은 정상",)),
    Case("G4", "그럼 언제 튜플을 써?",
         "(G1 뒤, 같은 세션) 멀티턴 — 앞 대화(이력 1턴)를 받아 튜플 이야기를 이어 간다(2026-10-21 전에는 기억하지 못하는 것이 기대 결과)",
         must_include=(("튜플", "tuple"),), sources_empty=True, session="g-tuple", expect_context="history",
         human=("앞 대화를 이어 가는가(리스트·튜플 맥락)",)),
))

# 업무특화 — 질문마다 pet_id를 둔다. 세션 고객(--customer)이 그 반려동물의 주인이어야 한다 —
# R3는 C004(콩이), 나머지는 C010(별이·달이)이라 두 번 돌린다(--only). 정답은 2026-10-21 limit_table·약관 청크와 대조
NOT_PAID = ("보상하지않", "지급하지않", "보장하지않", "보장되지않", "보상되지않", "지급되지않", "받을수없", "안나옵", "제외")
RAG = ModeSpec(key="rag", mode="업무특화", model="PETMINT_MODEL_RAG(kabyul-tri-7b-rag1-rebuild4-ckpt462)",
               corpus="강아지/고양이(pet의 종)", order="rag", needs_customer=True, cases=(
    Case("R1", "고급형 통원 하루 한도가 얼마예요?",
         "1일당 30만원(수술하지 않은 날), 수술한 날 200만원 (통원의료비보장 특약 제1조 제2항, 고급형) — 등급 행이 맞는가",
         must_include=(("30만원", "300000원"),), suspect_include=("15만원", "10만원"), expect_articles=(1,),
         expect_calc="limits", calc_values=(("rows.0.section_name", "펫퍼민트 반려견 통원의료비보장 특별약관"),
                                            ("rows.0.non_surgery", 300000), ("rows.0.surgery", 2000000), ("rows.1.section_name", "(없음)")),
         pet_id="P013", human=(HUMAN_MATCH, "수술한 날 200만원까지 말하는가(안 말해도 실패 아님) — 한도 카드는 통원 한 줄")),
    Case("R2", "통원 치료비가 50만원 나왔는데 보험금 얼마 받을 수 있어요?",
         "계산 카드: 고급형 통원·수술하지 않은 날 — (50만 − 3만) × 70% = 32.9만 → 1일 한도 30만원. 답변이 카드와 어긋나지 않는가",
         must_include=(("30만원", "300000원"),), suspect_include=("32만9천", "329000원", "35만원", "350000원"),
         expect_calc="medical", calc_values=(("claimed", 500000), ("limit", 300000), ("payout", 300000)),
         pet_id="P013", human=("계산 카드 금액(30만원)과 답변 금액이 같은가 — 답변이 거절해도 카드에 '금액은 약관 표로 계산한 값'이 붙는가",)),
    Case("R3", "하루 한도가 얼마예요?",
         "되묻기 — 통원(고급형)·입원(기본형)이 다른 (유형, 등급) 조합이라 sources → clarify에서 멈춰야 한다",
         pet_id="P005", human=("clarify 선택지가 통원·입원 둘인가",)),
    Case("R4", "해외에서 다친 것도 나오나요?",
         "안 나온다 — 대한민국 이외의 지역에서 발생한 사고 및 손해 (통원·입원의료비보장 특약 제2조 제1항 ⑪)",
         must_include=(NOT_PAID,), expect_articles=(2,), pet_id="P013",
         human=(HUMAN_MATCH, "'국내 동물병원'(제1조)만 들어 답했는가, 제2조 ⑪을 들었는가")),
    Case("R5", "보험 가입하면 사은품도 주나요?",
         "약관에 없음('사은품' 0건) → 거절 — 지어내지 않는가",
         expect_refusal=True, pet_id="P013", human=("사은품·혜택을 지어내지 않았는가",)),
    Case("R6", "소송 금액이 3천만원이면 변호사 보수는 얼마까지 보장돼요?",
         "280만원 (민사소송법률비용Ⅱ 특약 【별표3】, limit_table.lawyer_fee_limit) — 별표 표 값을 쓰는가",
         must_include=(("280만원", "2800000원"),), suspect_include=("30만원", "300000원"), pet_id="P014",
         expect_calc="legal", calc_values=(("claim_value", 30000000), ("lawyer_limit", 2800000), ("stamp", 140000), ("service", None)),
         human=(HUMAN_MATCH, "답변이 틀려도 법률비용 카드(280만원)가 맞게 뜨는가 — 답변 문장은 고치지 않았다")),
    Case("R7", "민사단독 사건으로 1심 소송을 하면 송달료는 얼마예요?",
         "165,000원 (【별표5】 1심 민사단독, limit_table.service_fee) — 소액(110,000원)과 섞이지 않는가",
         must_include=(("165000원", "16만5천원", "16만5000원", "165천원"),), suspect_include=("110000원", "11만원"),
         expect_calc="legal", calc_values=(("claim_value", None), ("service", 165000)),
         pet_id="P014", human=(HUMAN_MATCH,)),
    # ---- 한도 카드(2026-10-21) — 치료비 금액 없이 한도만 물으면 가입한 의료비 특약의 한도표 ----
    Case("R8", "제 지급 한도가 얼마인데요?",
         "한도 카드: 통원·입원(Ⅰ 고급형) 각각 수술 안 한 날 1일 30만원 · 수술한 날 200만원 · 70% · 연간 750만원. "
         "10-20 배포 서버에서 Ⅱ 고급형 고객에게 계산식·예시만 답했던 질문",
         expect_calc="limits", calc_values=(("rows.0.non_surgery", 300000), ("rows.0.surgery", 2000000), ("rows.0.annual_total", 7500000),
                                            ("rows.1.non_surgery", 300000), ("highlight", None)),
         pet_id="P013", human=("답변이 한도 숫자를 말하는가(카드와 별개 — 답변 문장은 고치지 않았다)",)),
    Case("R9", "기본형 수술 한도가 얼마인가요?",
         "가입(고급형)과 다른 등급을 물음 → 이 고객의 한도가 아니라 한도 카드 없음",
         expect_calc="none", pet_id="P013", human=("답변이 기본형 값(수술 200만원)을 고객 한도처럼 말하지 않는가",)),
    Case("R10", "소송 걸리면 변호사비는 한 건에 얼마까지 나와요?",
         "법률비용 질문 — 한도 카드는 빠진다. 소송 금액·심급이 없어 법률비용 카드도 없다. 정답: 1소송당 2,000만원(자기부담금 10만원)",
         must_include=(("2000만원", "20000000원", "2천만원"),), expect_calc="none", pet_id="P014", human=(HUMAN_MATCH,)),
    # ---- 멀티턴(2026-10-21) — 같은 세션에서 차례로. LLM 없이 앞 기준 질문과 이어 붙여 검색, 답변 모델에는 후속만 ----
    Case("R11", "고급형 통원 하루 한도는?", "멀티턴 앞 질문 — 한도 카드 통원", expect_calc="limits", pet_id="P013", session="r-mt",
         calc_values=(("rows.0.section_name", "펫퍼민트 반려견 통원의료비보장 특별약관"),)),
    Case("R12", "그럼 입원은요?",
         "(R11 뒤) 기준 질문 '고급형 입원 하루 한도는?'(통원 → 입원 갈아 끼움). 검색·한도 카드가 입원 — 1일 30만원, 수술한 날 200만원",
         expect_context="concat", expect_calc="limits", pet_id="P013", session="r-mt",
         calc_values=(("rows.0.section_name", "펫퍼민트 반려견 입원의료비보장 특별약관"), ("rows.1.section_name", "(없음)")),
         human=("답변이 입원 한도를 말하는가(거절하면 기록 — 답변 모델은 '그럼 입원은요?'만 받는다)",)),
    Case("R13", "수술하면요?", "(R12 뒤) 연쇄 — 기준 질문에 '입원'이 남아 입원 수술한 날 200만원",
         must_include=(("200만원", "2000000원"),), expect_context="concat", pet_id="P013", session="r-mt"),
    Case("R14", "강아지가 감기로 입원했는데 보험금 얼마나 나올 수 있나요?",
         "금액 되묻기 — 치료비 금액이 없어 '치료비가 얼마인가요?'로 묻고 턴을 끝낸다(모델 호출 없음)",
         must_include=(("치료비가 얼마",),), expect_calc="none", pet_id="P013", session="r-amt"),
    Case("R15", "치료비는 35만원 나왔어요",
         "(R14 뒤) 금액만 → 앞 질문과 이어 붙임. 의료비 카드: 입원 고급형 (35만 − 3만) × 70% = 22.4만원(1일 한도 30만원 안)",
         must_include=(("22만4,000원", "224000원"), ("보장 여부는 약관 조건에 따라",)), must_not_include=("21만원", "24.9만원"),
         expect_context="concat", expect_calc="medical", pet_id="P013", session="r-amt",
         calc_values=(("section_name", "펫퍼민트 반려견 입원의료비보장 특별약관"), ("claimed", 350000), ("payout", 224000)),
         human=("되묻기 직후 턴은 모델 대신 카드 값으로 답한다 — 숫자가 카드와 같은가",)),
    # ---- 금액 되묻기 + 부담보(초코 = 슬개골 탈구 부담보, 통원·입원Ⅱ 고급형). --customer=C001 로 따로 돌린다 ----
    Case("R16", "슬개골 탈구로 입원했는데 보험금 얼마나 나와요?", "금액 되묻기 — '치료비가 얼마인가요?'",
         must_include=(("치료비가 얼마",),), expect_calc="none", pet_id="P001", session="r-excl"),
    Case("R17", "치료비는 50만원이에요",
         "(R16 뒤) 카드: 입원Ⅱ 고급형 (50만 − 3만) × 70% = 32.9만 → 1일 한도 30만원. 답에 부담보(슬개골 탈구) 안내와 보장 여부 단서",
         must_include=(("30만원",), ("부담보 대상",), ("보장 여부는 약관 조건에 따라",)), expect_calc="medical", pet_id="P001",
         expect_context="concat",
         session="r-excl", calc_values=(("claimed", 500000), ("payout", 300000)),
         human=("부담보 안내 문장이 자연스러운가",)),
))

MODES = {m.key: m for m in (HR, GENERAL, RAG)}
