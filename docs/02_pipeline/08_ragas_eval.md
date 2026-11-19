<!--
다루는 곳: data/ragas_pilot.py, data/eval/requirements-ragas.txt, data/answer_eval.py, data/search_regression.py, data/prompts.py, data/eval/answer_eval_labels.json
읽은 커밋: 6710b83
-->
> 상태: △ 설계(2026-10-18). ✓ contexts 저장(answer_eval) 구현. △ 준비 코드 — Ragas 전용 venv(~/ragas_env, ragas 0.4.3), 파일럿(data/ragas_pilot.py). △ 파일럿 1회 실행(2026-10-18 22:43, `data/review/ragas_pilot_20261018_2243.json`) — 판정 90회 중 55회가 JSON 파싱 실패(`RagasOutputParserException`)였다. 결과 정리·통과 판단 전. [code:data/answer_eval.py:299-324] [code:data/eval/requirements-ragas.txt:76] [code:data/ragas_pilot.py] [code:data/review/ragas_pilot_20261018_2243.json] [c:c5a11f5] [c:12a4e2b]
> 본 평가 러너(Ollama 생성 → Ragas 판정)는 아직 없다 — 파일럿 결과를 보고 짠다. [code:data/ragas_pilot.py:1-4]

### 0. 한 줄 요약

RAG 답변의 품질을 숫자로 잰다. 원본/LoRA × RAG 있음/없음 네 조합을 같은 질문으로 비교해, 파인튜닝과 검색이 각각 무엇을 바꾸는지 가른다.

---

### 1. 최종 설계

#### 1-1. 지표 정의와 목표치

| 지표 | 정의 | 실무 기준선 | 우리 목표 |
| --- | --- | --- | --- |
| faithfulness | 답변을 진술(문장)로 나누고, 각 진술이 발췌(contexts)로 뒷받침되는지 판정한 비율. 0~1 | 0.85 | △ 파일럿 뒤에 정한다 [code:data/ragas_pilot.py:121-137] |
| answer_relevancy | 답변에서 질문을 거꾸로 몇 개 만들어 원래 질문과 임베딩 코사인 유사도 평균. 얼버무린 답(noncommittal)은 0 | 0.80 | △ 파일럿 뒤에 정한다 |
| hit@5 · MRR(검색) | gold any-of 중 하나라도 상위 5개 안 / 첫 정답 순위의 역수 평균 | — | △ 지금 서빙 경로로 다시 잰 값을 기준선으로 [code:data/search_regression.py:146] [code:data/search_regression.py:173-177] |

**거절 답변은 따로 센다.** "제공된 약관 발췌에서는 확인되지 않는 내용입니다…"는 faithfulness에서 진술이 없거나 판정이 갈리고, answer_relevancy에서는 얼버무림으로 0이 된다. 거절을 점수에 섞으면 "많이 거절하는 모델"이 점수로 벌을 받는지 상을 받는지 알 수 없다 → 조합마다 **거절률을 따로 보고**하고, 생성 지표는 거절이 아닌 답에서 잰다(거절 판정은 answer_eval의 `refused` 규칙). △ [code:data/prompts.py:59] [code:data/answer_eval.py:132]

#### 1-2. 비교 조합

| 조합 | 생성 모델 | 발췌 | 재는 것 |
| --- | --- | --- | --- |
| 원본 + RAG | `tri-7b`(GGUF) | 검색 상위 3개 | faithfulness · answer_relevancy · 거절률 [code:app/services/answer.py:53] [code:data/answer_eval.py:213] |
| LoRA + RAG | 파인튜닝 어댑터(GGUF) | 같은 검색 결과 | faithfulness · answer_relevancy · 거절률 |
| 원본, RAG 없음 | `tri-7b` | 없음 | answer_relevancy · 거절률 (faithfulness는 근거가 없어 정의되지 않는다) |
| LoRA, RAG 없음 | 어댑터 | 없음 | **거절률만** 해석한다 — 학습 때 늘 발췌가 있었으므로 분포 밖이고 거절이 예상된다 |

- **생성 경로는 Ollama(GGUF)**. 서비스가 실제로 도는 경로와 같아야 평가에 의미가 있다. ✗ answer_eval의 HF 4bit 경로는 이 평가에 쓰지 않는다(과거 수치와의 비교용으로만 남는다). [code:data/answer_eval.py:147-157]
- 검색은 문항마다 한 번 — 두 RAG 조합이 같은 검색 결과(같은 scope·top_k)를 쓴다. 검색이 같으므로 검색 지표도 조합마다 다시 잴 필요가 없다.
- 프롬프트는 서비스와 같은 `prompts.build_messages`(시스템 프롬프트 `SYSTEM_PROMPT`, 예산 2400토큰). [code:data/prompts.py:31] [code:data/prompts.py:159-178] [code:app/services/answer.py:54] [code:data/answer_eval.py:214]

#### 1-3. 준비 작업

| 일 | 상태 |
| --- | --- |
| 평가 결과에 모델이 본 발췌(contexts)를 남긴다 | ✓ 구현(2026-10-18) — `answer_eval.contexts_of`가 렌더된 user 메시지(fit_to_budget 뒤, 참조 포함)를 블록으로 되돌려 rows의 `contexts`에 넣는다. 학습 프롬프트 8,464개로 바이트 단위 왕복 일치 확인, 실제 평가 실행 전 [code:data/answer_eval.py:299-324] [code:data/answer_eval.py:584-589] [c:c5a11f5] <!-- 확인 못 함: 그때 원자료가 남지 않음(8,464개 왕복 확인은 실행 결과) --> |
| Ragas 설치 | △ 전용 venv `~/ragas_env`에 ragas 0.4.3(고정 목록 `data/eval/requirements-ragas.txt`), import·`pip check` 확인. 판정 실행 전 [code:data/eval/requirements-ragas.txt:1-4] [code:data/eval/requirements-ragas.txt:76] <!-- 2026-11-19 잼: ~/ragas_env/bin/pip show ragas 는 0.4.3, pip check 는 No broken requirements found. --> |
| 파일럿(심판이 한국어를 제대로 판정하나) | △ 1회 실행(2026-10-18, `data/ragas_pilot.py` 1-5절) — 90회 중 55회 파싱 실패, 5절 확인 항목은 아직 채우지 않았다 [code:data/review/ragas_pilot_20261018_2243.json] [code:data/ragas_pilot.py:133-135] |
| Ollama 생성 러너(네 조합 생성 → rows에 질문·답·contexts) | △ 코드 없음 — 파일럿 통과 뒤 |
| LoRA 어댑터 GGUF 변환 | ✓ rebuild4 체크포인트 462 → `kabyul-tri-7b-rag1-rebuild4-ckpt462`(10번 8절 절차, Ollama 등록, 운영 모델) [docs:02_pipeline/10_consultation_flow.md:164] [c:3f49bb5] <!-- 근거 파일: models/gguf/Modelfile.kabyul-tri-7b-rag1-rebuild4-ckpt462 --> <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml:30 --> |
| answer_relevancy 임베딩 | △ 정하지 않았다(4-1절) |

#### 1-4. 실행 절차와 예상 시간

| 단계 | 내용 | 횟수 | 예상 시간 |
| --- | --- | --- | --- |
| 1 | 검색 지표 — `python -m data.search_regression` | 103문항 | 수 분(GPU) [code:data/search_regression.py] [code:data/eval/search_regression.json] |
| 2 | 생성 — 네 조합, Ollama | 97 × 4 = 388회(no_answer 20문항을 넣으면 468회) | 30~40분 추정 — 짧은 FT 답 2~3초, 긴 원본 답 5~8초로 어림(00번 실측 1.8~3.0초는 짧은 답 기준) [docs:02_pipeline/00_model_setup.md:95] [code:data/answer_eval.py:30] |
| 3 | 판정 — faithfulness(두 RAG 조합) | 답변 194개 × 호출 2회(분해·검증) = 388회 | 파일럿에서 잰 호출당 초로 다시 계산 |
| 3 | 판정 — answer_relevancy(네 조합) | 답변 388개 × 질문 생성 1~3회 = 388~1,164회 | 같음 |

- 생성과 판정은 같은 GPU를 쓴다(Ollama가 모델을 갈아 끼운다) — 생성을 전부 끝낸 뒤 판정한다.
- 판정 호출이 776~1,552회라, 호출당 5~10초면 1.1~4.3시간이다(추정). 파일럿의 실측으로 바꾼다.

#### 1-5. 파일럿, 로컬 심판이 한국어를 제대로 판정하나

Ragas 내부 프롬프트는 영어이고 내용은 한국어다. 12B 심판이 한국어 답변을 진술로 제대로 나누고 판정하는지 먼저 본다. **안 되면 평가자 모델부터 다시 정한다** — 본 평가보다 먼저 돌린다. [code:data/ragas_pilot.py:3-4] [code:data/ragas_pilot.py:208]

**세트**: 10문항(R005·R010·R018·R020·R027·R030·R037·R042·R052·R059 — answerable, FT·원본 답이 둘 다 근거 문구를 담았고 범주가 겹치지 않는 것). 발췌는 answer_eval의 정답 발췌(gold_item)와 같다. 문항마다 답 세 가지. [code:data/ragas_pilot.py:39-53] [code:data/ragas_pilot.py:76-78]

| 답 | 내용 | 기대 |
| --- | --- | --- |
| grounded_ft | rebuild2 평가의 FT 답(짧다) | 높다 [code:data/ragas_pilot.py:36] [code:data/ragas_pilot.py:82] |
| grounded_base | 같은 문항의 원본 답(119~722자, 문장이 많다 — 분해를 보기 좋다) | 높다(원본은 발췌 밖 일반론을 섞기도 해 FT보다 낮을 수 있다) [code:data/ragas_pilot.py:82] [code:data/review/ragas_pilot_20261018_2243.json] (2026-10-18 기준) |
| fabricated | 발췌와 어긋나게 손으로 쓴 답(숫자·범위·예외를 뒤집음) | 낮다 [code:data/ragas_pilot.py:40-52] |

같은 입력을 3번씩 돌린다(10문항 × 3종 × 3번 = 90회, 판정 호출 약 180회). [code:data/ragas_pilot.py:149-154] [code:data/ragas_pilot.py:210]

**실행**

```
python -m data.ragas_pilot prepare                        # llm_env — Milvus 필요, GPU 안 씀
~/ragas_env/bin/python -m data.ragas_pilot score          # ~/ragas_env — Ollama gemma4:12b, 기본 3회 반복
```

결과는 `data/review/ragas_pilot_<시각>.json`과 화면 요약. answer_relevancy는 임베딩을 정한 뒤 붙인다(파일럿은 faithfulness만). [code:data/ragas_pilot.py:219-223] [code:data/ragas_pilot.py:143-145]

---

### 2. 왜 이렇게 했나

#### 2-1. 무엇을 왜 재는가, 검색 층과 생성 층을 나눈다

답변이 틀렸을 때 원인은 둘 중 하나다 — 맞는 조항을 못 찾았거나(검색), 찾은 조항을 잘못 옮겼거나(생성). 한 숫자로 섞으면 어느 쪽을 고쳐야 하는지 모른다.

| 층 | 무엇을 | 도구 | 이유 |
| --- | --- | --- | --- |
| 검색 | 정답 조항이 상위 k개에 들어왔나 | 기존 `data/search_regression.py`의 hit@k·MRR | gold가 **any-of**다(정답 조항 중 하나만 찾으면 맞음). Ragas의 ID 기반 recall은 "정답 ID 중 몇 개를 찾았나"로 계산해 정의가 어긋난다. LLM 기반 context recall은 참조 정답 문장이 필요한데 없다 [code:data/search_regression.py] [code:data/eval/search_regression.json] |
| 생성 | 답이 근거에 붙어 있나, 질문에 맞나 | Ragas faithfulness · answer_relevancy | 둘 다 참조 정답이 필요 없다 — 97문항 정답 문장은 쓰지 않는다 [code:data/ragas_pilot.py:143-151] [code:data/eval/answer_eval_labels.json] |

검색 지표의 2026-10-13 값: 103문항 세트 상위 5개 안 88/97, MRR 0.745(`data/review/eval_results_summary.md` 2절의 10-13 17:12 줄). 그 뒤 청크 v3·질의 확장으로 검색이 바뀌어 지금 값은 다시 재야 한다. ✗ 검색 층에는 Ragas를 쓰지 않는다. [code:data/review/eval_results_summary.md:110] [c:4d62bf3]

#### 2-2. Ragas 환경과 심판 호출

**Ragas를 llm_env에 넣지 않은 이유**: ragas 0.4.3이 끌어오는 instructor 1.3.2가 `openai<2`·`rich<14`·`tenacity<9`를 요구해, llm_env의 openai 3.13.0·rich 15.0.0·tenacity 9.1.4·langchain-openai 1.6.2를 내린다(최신 instructor 1.17.0은 `rich<15`라 llm_env와 안 맞는다). 학습·서비스 환경을 건드리지 않게 따로 둔다. 같은 venv에서 langchain-community 0.4는 `chat_models.vertexai`가 빠져 ragas import가 깨지므로 0.3.31로 고정했다. [code:data/eval/requirements-ragas.txt:1-3] [code:data/eval/requirements-ragas.txt:34] [code:data/eval/requirements-ragas.txt:40] [code:data/eval/requirements-ragas.txt:76]

**심판 호출 방식**: Ollama 네이티브 API(`langchain-ollama`의 ChatOllama, `num_ctx` 8192, temperature 0). OpenAI 호환 엔드포인트(`/v1`)는 `num_ctx`를 못 정해 긴 발췌가 기본 문맥에서 소리 없이 잘린다. [code:data/ragas_pilot.py:37] [code:data/ragas_pilot.py:141-145] [code:data/eval/requirements-ragas.txt:42]

---

### 4. 남은 한계

#### 4-1. 정하지 않은 것

- partial·flawed 처리(4-2절)
- answer_relevancy 임베딩 — KURE-v1을 쓰려면 ~/ragas_env에 sentence-transformers·torch를 더 넣거나(무겁다), 공용 model-service의 `/embed`(192.168.122.1:8200, 2026-11-11부터)를 부르거나, Ollama 임베딩 모델을 새로 받는다 [code:data/model_client.py:3] [code:data/model_client.py:36] [c:13f82da]
- 생성 온도 — 서비스는 Modelfile 값(tri-7b 0.3)을 따른다. 평가를 재현하려면 0으로 고정할지 [c:3f49bb5] <!-- 근거 파일: models/gguf/Modelfile.tri7b 3줄 PARAMETER temperature 0.3 -->
- RAG 없음 조합의 입력 — 질문만 보낼지(일반 모드와 같음), `build_messages(question, [])`로 "(검색된 발췌 없음)"을 넣을지 [code:data/prompts.py:63]
- RAG 조합의 발췌 조립 — 서비스와 answer_eval `--search`(2026-10-21부터) 모두 `build_full_context`(참조 조문 포함). 예전 경로(`search_with_graph`, 참조 없음)는 `--search-legacy`로만 남았다 [code:data/answer_eval.py:217-224] [code:data/answer_eval.py:243] [code:data/answer_eval.py:277] [code:data/answer_eval.py:529-530] [code:app/services/answer.py:14] [c:cf7f368]
- 목표치(1-1절) — 파일럿 뒤
- no_answer 20문항을 생성 평가에 넣을지 — 넣으면 거절률 비교가 늘고 생성 횟수가 468회가 된다 [code:data/answer_eval.py:30] [code:data/answer_eval.py:200]

#### 4-2. partial과 flawed 12문항 처리

`data/eval/answer_eval_labels.json` — partial 10(발췌가 핵심 일부만 담아 거절도 변호 가능), flawed 2(질문이 등급·특약을 특정하지 않아 답이 하나로 정해지지 않음). [code:data/eval/answer_eval_labels.json]

- 제안 A: 본 집계는 answerable 85문항으로 하고, partial·flawed는 따로 표에 둔다(answer_eval·ckpt_select와 같은 처리라 숫자가 서로 이어진다) [code:data/eval/answer_eval_labels.json] [code:data/ckpt_select.py:9]
- 제안 B: 97문항 전체로 집계하고 partial·flawed를 표시만 한다(문항 수가 더 많지만 거절이 정답일 수 있는 문항이 섞인다) [code:data/eval/answer_eval_labels.json]

결정: (비워 둠)

---

### 5. 검증 항목

파일럿(1-5절)의 확인 항목이다.

**확인 항목**

- [ ]  문장 분해가 한국어에서 제대로 되는가 — 출력의 분해 목록을 사람이 읽는다(대명사·문장 쪼개기·누락) [code:data/ragas_pilot.py:181-185]
- [ ]  근거 있는 답과 지어낸 답을 가르는가 — grounded 최솟값 > fabricated 최댓값이면 겹치지 않음 [code:data/ragas_pilot.py:191-195]
- [ ]  호출 한 번에 몇 초인가 — 1-4절 판정 시간을 다시 계산한다 [code:data/ragas_pilot.py:196-197]
- [ ]  같은 입력을 여러 번 돌렸을 때 점수·분해 문장 수가 흔들리는가 [code:data/ragas_pilot.py:175-177]
- [ ]  num_ctx(8192)를 넘은 호출이 없는가 — 넘으면 Ollama가 앞을 잘라 판정이 망가진다 [code:data/ragas_pilot.py:37] [code:data/ragas_pilot.py:174]
- [ ]  JSON 파싱 실패(오류) 횟수 [code:data/ragas_pilot.py:170] [code:data/ragas_pilot.py:198]

**통과 기준(2026-10-18 확정)**: 분해가 사람 눈에 맞는 답이 대부분 · grounded 평균 0.8 이상이고 fabricated 평균 0.3 이하, 겹치는 문항 0~1개 · 반복 간 점수 차 0.1 이하 · num_ctx 초과 0.

**실패하면**: (1) Ragas 프롬프트를 한국어로 옮겨 `set_prompts`로 바꿔 끼운다 (2) 16GB에 들어가는 더 큰 로컬 심판을 찾는다 (3) 외부 API — 요구사항 "외부 API 호출 0건"의 예외로 둘지부터 정해야 한다. [docs:requirements.md:21]

---

#### 옛 절 번호 (코드 주석이 가리키는 것)

2026-11-19 문서 정리 B단계에서 절을 옮겼다. 저장소 안 주석이 옛 번호를 가리키는 곳만 적는다.

| 옛 절 | 지금 자리 | 옛 번호를 쓰는 곳 |
| --- | --- | --- |
| 6절(파일럿) | 1-5절, 확인 항목과 통과 기준은 5절 | data/ragas_pilot.py:3 |
