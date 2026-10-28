"""
lexicon.py
코드 답 규칙의 트리거 낱말(정규식)을 한 곳에(2026-10-28, docs/16 4절 A안). customer_facts·hr_personal의 정의를 글자 그대로 옮겼다 —
동작은 같다. 같은 개념(질병·보장 질문·금액)이 규칙마다 다르게 정의된 것이 여기서 보인다. 합치면 동작이 바뀌므로 합칠 때는 따로 잰다.
다음 턴이 앞 답을 알아보는 문구(MARKERS)도 여기 적는다 — 문구를 바꾸면 tests/test_rule_registry.py가 깨진다.
"""

import re

# ----- 질병·병명 — 셋이 다르다(아래 주석). 합치면 동작이 바뀌므로 합칠 때는 측정한다
DISEASE_NOTE = re.compile(r"질병|병(?!원)|감기|장염|염증|[가-힣]염\b|아프|아파|증상|걸렸|걸리|설사|구토|진단|감염|질환")   # 고객 사실(notes) — 대기기간 줄을 붙일지: 질병 낱말·증상·[가-힣]염  (customer_facts._DISEASE)
# 상해 후속에서 빼는 말 — 슬관절·고관절·면책 사유(고의·자연재해…) + 질병 낱말 일부  (customer_facts._INJURY_NOT)
INJURY_EXCLUDE = re.compile(r"슬관절|슬개골|고관절|탈구|형성부전|무릎뼈|고의|일부러|지진|분화|해일|홍수|태풍|폭우|자연재해|전쟁|폭동|방사|핵|"
                         r"감기|장염|염증|질병|병이|암|종양|구토|설사|피부병|알레르기|기침|열이")
# 병명 되묻기 — 이 말들을 지우고 한글이 남으면 '이름이 있다'(병명·상해·치료)  (customer_facts._ASK_FILLER)
NO_NAME_FILLER = re.compile(r"입원|통원|수술|병원|치료|다쳤|다쳐서|아파서|아프다|아파요|아파|다녀왔|데려갔|갔는데|갔어요|왔는데|는데|했어요|했는데|했고|했다|받았는데|"
                         r"받았어요|받고|중인데|중이에요|보장|보상|보험|처리|되나요|돼요|되나|될까요|되죠|나와요|나오나요|나올까요|청구|가능|할\s*수\s*있|있나요|"
                         r"있어요|있을까요|해요|이에|이에요|인데|예요|요|어제|오늘|지금|방금|이번에|지난주|저희|우리|애가|아이가|강아지|고양이|혹시|근데|그런데|좀|"
                         r"이거|이건|그거|제가|[이가은는을를도에의로]\b")

# ----- 상해·겪은 일
# 상해 낱말(상해 후속·chat_ws가 앞 턴을 읽을지)  (customer_facts._INJURY)
INJURY = re.compile(r"다쳤|다쳐|부딪|떨어져|떨어졌|넘어져|넘어졌|미끄러|물려|물렸|베였|베여|찔렸|찔려|골절|부러|삐었|삐끗|접질|화상|데었|데여|"
                     r"교통사고|차에\s*치|치였|끼였|끼어서|긁혔|찢어|상처")
# 실제로 겪은 일(입원했·통원했·수술했·다쳤·병원 갔…) — 병명 되묻기  (customer_facts._ASK_EVENT)
EVENT_HAPPENED = re.compile(r"입원\s*(?:했|중|해\s*있|시켰)|통원\s*(?:했|치료\s*받)|수술\s*(?:했|받)|다쳤|다쳐서|아파서|아프다|아파요|"
                        r"병원\s*(?:에\s*)?(?:갔|다녀|데려|왔)|치료\s*(?:를\s*)?받(?:았|고)")
LIABILITY = re.compile(r"물었|물어|물림|물렸|물려|배상|피해자|다치게")   # 배상책임(물었·피해자…) — 미가입 특약  (customer_facts._LIAB_WORDS)

# ----- 금액
AMOUNT_UPSELL = re.compile(r"얼마|금액|\d|만\s*원|보험금")   # 금액·숫자 — 병명 되묻기·상해 후속에서 빼는 것(금액은 payout 되묻기)  (customer_facts._ASK_AMOUNT)
AMOUNT_HR = re.compile(r"얼마|금액|받|나와|나오")   # 사내규정 연차수당 — 얼마·받·나와  (hr_personal._AMOUNT)

# ----- 보장을 묻는 말 — 셋이 다르다
COVERAGE_Q = re.compile(r"보장|보상|보험\s*(?:되|돼|처리)|나와|나오|되나요|돼요|되죠|받을\s*수|청구|언제부터|언제까지|부담보")   # 부담보 코드 답 — 보장·보상·언제부터·부담보…  (customer_facts._COVERAGE_Q)
COVERAGE_Q_STRICT = re.compile(r"보장|보상|보험\s*(?:이|은|으로)?\s*(?:되|돼|처리)|보험\s*처리|나와요|나오나요|나올까요|청구\s*(?:되|돼|할\s*수|가능)")   # 병명 되묻기 — 보장 질문만(언제부터·언제까지 없음)  (customer_facts._ASK_COVER)
MEDICAL_INTENT = re.compile(r"치료|병원|진료|수술|보험금|한도|얼마|보장|보상|나와|나오|청구|입원비|통원비")   # 미가입 특약 — 의료비를 묻는가  (customer_facts._MEDICAL_INTENT)

# ----- 부위·질환
KNEE = re.compile(r"슬개골|슬관절|고관절|무릎|탈구")   # 슬관절·고관절(반려견 1년)  (customer_facts._KNEE)
URINARY = re.compile(r"비뇨|방광|요로|신장|결석|소변|오줌|복막염|FIP", re.I)   # 비뇨기·복막염(반려묘 90일)  (customer_facts._URINARY)
GUM = re.compile(r"잇몸|구내염|구강|치은")   # 치아 외 구강질환(⑲)  (customer_facts._GUM)
TOOTH = re.compile(r"치아|이빨|스케일링|발치|뽑|치석|충치|치주")   # 치아(⑲에서 뺀다)  (customer_facts._TOOTH)

# ----- 가입·나이
AGE_TALK = re.compile(r"나이|몇\s*살|\d+\s*살|살이|살인데|살\s*넘|재가입|가입\s*(?:되|돼|할\s*수|가능|이\s*되)")   # 나이·가입 이야기(고객 사실 나이 줄)  (customer_facts._AGE)
AGE_NUM = re.compile(r"(\d+|열다섯|열네|열세|열두|열한|다섯|여섯|일곱|여덟|아홉|열|한|두|세|네)\s*(?:살|세)(\s*(?:넘|초과|이상))?")   # 숫자 나이  (customer_facts._AGE_NUM)
NEW_JOIN = re.compile(r"(?:새로|신규|처음|지금)\s*(?:보험\s*)?가입|가입\s*(?:할\s*수|돼|되|가능|이\s*되|하려|받아)")   # 신규 가입  (customer_facts._NEW_JOIN)
NOT_NEW_JOIN = re.compile(r"재가입|갱신|이어서|계속|연장|만기")   # 재가입·갱신  (customer_facts._NOT_NEW)

# ----- 면책 단서(침술·예방접종)
ACUPUNCTURE = re.compile(r"침술|침\s*(?:을|도|은|만)?\s*(?:맞|치료|시술|놓)|한방\s*침")   # 침술  (customer_facts._ACU)
NOT_ACUPUNCTURE = re.compile(r"한약|뜸|부항|약침|재활|물리\s*치료")   # 침술이 아닌 한방·재활  (customer_facts._NOT_ACU)
FOLLOW_TAIL = re.compile(r"이면요|라면요|은요|는요")   # 후속 꼬리(이면요·은요)  (customer_facts._FOLLOW)
VACCINE = re.compile(r"접종|백신|예방\s*주사")   # 예방접종  (customer_facts._VAC_WORD)
VACCINE_NONE = re.compile(r"(?:접종|백신|예방\s*주사)[을를은는도]?\s*(?:안|못|한\s*적\s*없|기록\s*없|없)|안\s*맞|못\s*맞")   # 접종 안 함  (customer_facts._VAC_NONE)
VACCINE_WHEN = re.compile(r"(\d+|열한|열두|다섯|여섯|일곱|여덟|아홉|한|두|세|네|열)\s*(개월|달|년|주|일)\s*(전|안|이내|됐|지났|만)")   # 접종 시기  (customer_facts._VAC_TIME)

# ----- 법률
LEGAL = re.compile(r"소송|변호사|법률\s*비용|송달료|인지액")   # 소송·변호사·송달료·인지액  (customer_facts._LEGAL_WORDS)

# ----- 사내규정 개인화
SELF_REF = re.compile(r"(?:^|[\s,])(?:내|제|저|나)(?:\s|가|는|도|의)|저희\s*직원으로서|본인")   # 본인 지칭(내·제·저·나 + 조사)  (hr_personal._SELF)
LEAVE = re.compile(r"연차|휴가")   # 연차·휴가  (hr_personal._LEAVE)
LEAVE_ASK = re.compile(r"남|잔여|몇\s*(?:일|개)|며칠|얼마")   # 남은·잔여·며칠  (hr_personal._LEAVE_ASK)
NOT_LEAVE = re.compile(r"경조|병가|출산|육아|특별휴가|재택|휴직")   # 연차가 아닌 휴가·휴직  (hr_personal._NOT_LEAVE)
UNUSED_PAY = re.compile(r"미사용|수당")   # 미사용·수당  (hr_personal._UNUSED)
SEVERANCE = re.compile(r"퇴직금")   # 퇴직금  (hr_personal._SEVERANCE)
GRADE = re.compile(r"사원|대리|과장|차장|부장")   # 직급 이름  (hr_personal._GRADE)
PAY = re.compile(r"월급|급여|봉급|임금|월급날")   # 월급·급여  (hr_personal._PAY)
ORDINARY_WAGE = re.compile(r"통상\s*임금|통상\s*시급|시급|일급")   # 통상임금·시급  (hr_personal._ORDINARY)
PAY_NOT = re.compile(r"세금|공제|실수령|떼|퇴직금|자격\s*수당|연차|평균\s*임금|통상|시급|일급")   # 급여 주제에서 빼는 말  (hr_personal._PAY_NOT)
WHEN = re.compile(r"언제|며칠|날짜|급여일|월급날|들어와|들어오|입금")   # 언제·입금  (hr_personal._WHEN)
RETIRE = re.compile(r"퇴직|퇴사|그만\s*두|그만두|관두|그만\s*나|마지막\s*(?:근무|출근)")   # 퇴직·퇴사·그만두  (hr_personal._RETIRE)
DATE_YMD = re.compile(r"(\d{4})\s*[년./-]\s*(\d{1,2})\s*[월./-]\s*(\d{1,2})\s*일?")   # 연월일  (hr_personal._YMD)
DATE_MD = re.compile(r"(?:(올해|내년|후년)\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일")   # 월일  (hr_personal._MD)
DATE_M = re.compile(r"(?:(올해|내년|후년)\s*)?(\d{1,2})\s*월\s*(말|초|중순|에|달)?")   # 월(말·초)  (hr_personal._M)
CERT_ALLOWANCE = re.compile(r"자격\s*수당")   # 자격수당  (hr_personal._CERT)
CERT_IF = re.compile(r"따면|취득하면|있으면|생기면|붙으면")   # 자격 가정(따면…)  (hr_personal._CERT_IF)
PROMOTION = re.compile(r"승진|진급|(?:대리|과장|차장|부장)\s*(?:이|가)?\s*(?:되|될|돼|달)")   # 승진·진급  (hr_personal._PROMO)

# ----- 병명 되묻기 ⑤를 모델로 볼 때(2026-10-28 B안, name_check) — 모델이 못 보는 것을 코드가 막는다
# 면책·자격을 가르는 사실(자연재해·해외·가입 전·고의) — 병명이 없어도 이것이 있으면 되묻지 않는다(평가 S01 태풍·S06 일본: 모델은 '이름 없음'이라 했다)
EXEMPT_FACT = re.compile(r"태풍|지진|홍수|해일|폭우|폭설|자연재해|화재|불이|전쟁|해외|외국|일본|중국|미국|유럽|동남아|괌|여행|가입\s*(?:하기\s*)?전|계약\s*전|전부터|원래|고의|일부러")
# 부탁하는 말·어미 — 모델이 뽑은 '이름'이 이것뿐이면 이름이 아니다. gemma 생성 train 세트(시험 세트와 따로)에서 모았다
POLITE_FILLER = re.compile(r"되는지|되는거|되는건지|되는건가|되냐|됨|적용|확인|알려|봐줘|봐주|부탁|궁금|물어봐|갔어|갔거든|갔다와|아픈거|아픈데|한거|한지|해주|나오는지|들어가는지|범위|에서")
POLITE_ENDINGS = frozenset({"어", "여", "요", "야", "임", "비", "용", "삼", "세", "세여", "세용"})
EVENT_WORDS = frozenset({"다쳤다", "아프다", "아파서", "치료받았다", "수술", "입원", "통원"})

# ----- 다음 턴이 앞 답을 알아보는 문구
ASKED_MARK = "어떤 질병이나 상해로"   # 병명 되묻기 답에 늘 든다(상해 후속이 본다)
