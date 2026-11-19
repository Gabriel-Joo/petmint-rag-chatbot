02_embedding_index.md 에서 떼어 낸 구현 기록(2026-11-19 문서 정리 B단계). 지금 설계는 docs/02_pipeline/02_embedding_index.md

## 인사규정 개정 반영 — 제25조 ① 지급일(2026-10-28, 옛 3-1절)

"매월 1일부터 말일까지를 산정기간으로 하여 **당월 25일**에 지급한다"는 산정기간이 끝나기 전에 지급하는 셈이라 "**익월 10일**에 지급한다"로 고쳤다. ②항(휴일이면 전일)은 그대로다. [code:app/services/hr_personal.py:173] [code:app/services/hr_personal.py:184-185] [c:b719cdb]

**원본.** `data/raw_pdf/펫퍼민트손해보험_인사규정.pdf`(10쪽, LibreOffice 24.2 Writer로 내보낸 PDF). Writer 원본(.odt/.docx)은 이 머신에 없고 LibreOffice도 설치돼 있지 않다. 전처리(`data/hr_preprocess.py`)는 PDF를 읽으므로 PDF가 원천이다. PDF·청크는 git 밖(.gitignore)이라 고치기 전 원본과 청크·그래프 8벌을 `backups/hr_regulation_art25_20261028/`에 두었다(되돌리기는 같은 폴더 `ROLLBACK.md`). [code:data/hr_preprocess.py:31] [code:data/hr_preprocess.py:91] [c:3f49bb5] <!-- 올린 파일: backups/hr_regulation_art25_20261028/ROLLBACK.md --> <!-- 2026-11-19 잼: command -v soffice 와 dpkg -l 에 LibreOffice 없음 --> <!-- 확인 못 함: 인사규정 PDF와 청크 사본은 올리지 않음(PDF는 출처가 정해지지 않은 과목 자료, 청크는 원문 사본). Writer 원본이 없다는 것은 지난 일이라 다시 잴 수 없음 -->

**고친 방법 — PDF 내용 스트림의 글자 코드만 바꾼다.**
- 처음엔 세 글자를 지우고(redact) 새로 써 넣었다. 그림은 맞았지만 새 글자가 쪽 내용의 맨 끝에 붙어, 추출하면 "…하여 / 월 / 일에 지급한다." 뒤에 "익 10"이 따로 나왔다. 전처리는 내용 순서(`sort=False`)를 따르므로 청크가 깨진다 → 버렸다 [code:data/hr_preprocess.py:9-10]
- 대신 5쪽 내용 스트림에서 그 줄의 텍스트 연산자를 직접 고쳤다. '당'(F3 `A1`)이 든 `TJ`를 그 앞에서 끊고 같은 글꼴의 다른 부분집합(F5)에 이미 있는 '익'(`2B`, 7·10쪽 "이익"·"불이익"에 쓰인 글리프)을 넣은 뒤 F3로 돌아간다. "25"(DejaVu F4 `0B0F`)는 같은 부분집합의 "10"(`0A12`)으로. 전각 한글·같은 폭 숫자라 위치가 그대로다 <!-- 확인 못 함: 인사규정 PDF라 올리지 않음(출처가 정해지지 않은 과목 자료) -->
- 확인: 10쪽 추출 글자 중 바뀐 것은 그 세 글자뿐(같은 위치), 다시 만든 청크 49개 중 바뀐 칸은 제25조 content 하나, 그래프는 같다 [code:data/hr_preprocess.py:266-280] (2026-10-28 기준) [c:dcdecd9] <!-- 요약: data/review/chunks_graph_summary.md 2절 인사규정 청크 49 --> <!-- 확인 못 함: 바뀐 글자와 칸을 견준 결과는 그때 원자료가 남지 않음 -->

**반영.** 청크·그래프를 로컬 4벌(기본·v2·v3·v4)과 NFS(같은 저장소)에 → `python -m data.hr_index`(Milvus `hr_regulation` 재적재 — 적재 직후 행을 세던 검사가 0행으로 나와 실패처럼 보였다. flush·강한 일관성으로 고쳤다) → search-service 재시작(BM25를 기동 때 만든다). 운영 앱은 청크를 기동 때 읽으므로 Pod가 다시 떠야 새 본문이 근거 패널·발췌에 나온다. [code:data/hr_index.py:71-73] [code:search_service/main.py:47-48] [c:b719cdb] <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답). 다시 재려면 서비스가 끊길 수 있어 사람 승인이 필요함 -->

**회귀.** 인사규정 검색 회귀 기존 24문항 순위·상위 3 그대로 + 새 2문항(H025 월급 지급일·H026 휴일) 1위. 약관 103문항 순위 그대로(80·97·97 / MRR 0.897). 사내규정 답 프롬프트 38개 중 바뀐 것은 발췌에 제25조가 든 HR13 하나(답의 결론 같음). "10월분 급여는 언제?" → 11월 10일. [code:data/eval/search_regression_hr.json:501] [code:data/eval/search_regression_hr.json:520] [code:data/eval/search_regression.json] (2026-10-28 기준) [c:b719cdb] <!-- 확인 못 함: 그때 원자료가 남지 않음(어느 결과 파일인지 문서에 없고 data/eval/results/에도 그날 파일이 없음) -->

**다른 조항과의 관계(고치지 않음).**
- 제45조 ② 퇴직일부터 14일 이내 금품 청산 — 퇴직자는 이것이 지급일보다 먼저다(예: 10월 15일 퇴직 → 10월 29일까지, 정기 지급일 11월 10일 전). 특칙이지 충돌은 아니다 <!-- 확인 못 함: 인사규정 PDF라 올리지 않음(출처가 정해지지 않은 과목 자료) -->
- 제3조 4호 평균임금 = 이전 3개월 동안 **지급된** 임금 — 익월 10일 지급이므로 그 달 급여는 다음 달 10일부터 '지급된' 것이다. 개인화 계산(`hr_personal.paid_by`)을 이 기준으로 맞췄다(매달 1~9일에만 달라진다) [code:app/services/hr_personal.py:192-199]
