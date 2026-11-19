<!--
다루는 곳: data/prompts.py, data/finetune_data.py, data/rebuild.py, data/answer_eval.py, data/ckpt_select.py, data/faq_rag.py, data/faq_units.py, data/eval/answer_eval_labels.json, data/eval220.py, scripts/rebuild5_chain.sh, scripts/rebuild5b_chain.sh, scripts/ckpt_select220.py, scripts/rebuild5_verdict.py, scripts/eval_judge.py, scripts/prod_measure.sh, notebooks/07_파인튜닝.ipynb, scripts/eval_serving.py, scripts/eval_check_prompts.py, scripts/stage_eval.sh, scripts/stage6_chain.sh, scripts/stage7_pre.sh, scripts/probe_length.py, scripts/probe_train_gold.py, tests/test_stage4.py, tests/test_stage5.py
읽은 커밋: 6710b83
-->
> 학습·평가 완료. 재구축은 rebuild(2026-10-15, 10절)부터 rebuild5b까지 했고, 운영 모델은 rebuild4(`kabyul-tri-7b-rag1-rebuild4-ckpt462`)다. rebuild5·5b는 불채택(11절). [code:data/rebuild.py:1-3] [code:scripts/prod_measure.sh:6] [code:data/review/rebuild5_verdict.md] [code:data/review/rebuild5b_verdict.md] [c:c5c1ca7] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml:30 -->
> 

---

### 0. 한 줄 요약

06번이 검증한 FAQ로 Tri-7B를 QLoRA 파인튜닝한다. [code:data/finetune_data.py:1-3] [code:notebooks/07_파인튜닝.ipynb:149-170]

**학습시키는 것**: 주어진 약관 발췌를 읽고 상담원 말투로 답하는 능력

**학습시키지 않는 것**: 약관 내용 자체. 사실 근거는 RAG(검색+그래프)가 매번 공급한다

---

### 1. 최종 설계

#### 1-1. 학습과 추론의 형식을 코드로 묶는다

가장 중요한 설계 결정이다. 형식이 어긋나면 파인튜닝 효과가 사라지는데, 두 곳에 따로 쓰면 어긋나기 쉽다.

`data/prompts.py` 하나를 **07번 학습, 09번 앱 추론, 08번 평가가 함께 import**한다. [code:data/prompts.py:84-95] [code:data/prompts.py:119-157] [code:app/services/answer.py:352-357] [code:data/answer_eval.py:245-247] [code:data/finetune_data.py:557]

```
ExcerptItem.from_unit()           학습용 — 05번 FAQ 단위
ExcerptItem.from_search_result()  추론용 — 04번 검색 결과
     ↓ 같은 모양
format_item() / build_user_content() / fit_to_budget()   하나씩만 존재
```

출력 형식:

```
[약관 발췌]
[발췌 1] 펫퍼민트 반려견 통원의료비Ⅱ보장 특별약관 제1조(보험금의 지급사유) 고급형
회사가 보상하는 비용은...
  [참조] 반려동물 비용손해 관련 특별약관 일반조항 제15조(재가입) 제6항
  ...

[질문]
수술 한도가 얼마인가요?
```

**길이 예산을 넘을 때 뭘 빼는지도 한 곳에서 정한다.** 아래쪽 발췌의 참조부터 빼고, 그다음 아래쪽 발췌를 통째로 뺀다. 학습 시 정답 발췌는 `protected`로 지정해 참조까지 보존한다. [code:data/prompts.py:136-157]

#### 1-2. 학습 데이터 구성

**구성**: 정답+방해 70% / 정답만 20% / 답 없음 10% [code:data/finetune_data.py:5-8] [code:data/finetune_data.py:82]

#### 1-3. 학습 설정

3-1~3-3절에서 확인한 문제들을 고친다.

| 항목 | 이전 | 이번 | 이유 |
| --- | --- | --- | --- |
| loss 범위 | 전체 | 답변 토큰만 | 발췌를 넣으면 loss 대부분이 원문 암기에 쓰인다 [code:data/prompts.py:179-182] |
| 패딩 | 고정 768 | 동적 + `group_by_length` | 계산의 2/3가 패딩이었다 [code:notebooks/07_파인튜닝.ipynb:335] [code:notebooks/07_파인튜닝.ipynb:395] |
| val 분할 | 무작위 | `unit_id` 단위 | 같은 조항의 비슷한 질문이 train/val에 나뉘면 val loss가 실제보다 낮게 나온다 [code:data/finetune_data.py:11] [code:data/finetune_data.py:133-134] |
| 목표 답변 | "근거: …" 포함 | 제거 | 근거 표기는 코드가 조립한다 [code:data/finetune_data.py:12] [code:data/prompts.py:185-186] |

**메모리**: batch 1, MAX_LENGTH 3072. 평균 샘플이 이전의 약 2배라 OOM 여부는 첫 20 step으로 확인한다. [code:data/finetune_data.py:112] [code:notebooks/07_파인튜닝.ipynb:376]

#### 1-4. 고객 정보, 계산, 대화 이력을 프롬프트에 넣지 않는다

09번 UI는 고객을 조회해 가입 정보(등급·유형·자기부담금·부담보)를 들고 있다. 그런데 그걸 모델에게 주지 않는다.

**대신 코드가 처리한다**

| 정보 | 처리하는 곳 |
| --- | --- |
| 등급·유형 | 검색 필터 (SearchScope) [code:data/search_scope.py:106] |
| 자기부담금 | 계산 카드 [code:app/services/payout.py:1-11] |
| 부담보 | 코드가 질문과 대조해 경고 배너 [code:app/services/payout.py:666-668] [code:app/services/answer.py:236-238] |
| 가입일 | 코드가 경과일을 계산해 카드에 표시 [code:app/services/customer_facts.py:8-9] |

`build_messages(customer=...)`에 값을 넘기면 `NotImplementedError`가 난다. 결정을 코드에 박아, 나중에 흔들리지 않게 했다. [code:data/prompts.py:163-166]

그래서 계산은 **답변 옆 카드로 분리**한다. 모델은 계산에 손대지 않는다. "계산 카드를 참고하세요" 같은 안내 문장도 모델이 아니라 UI가 붙인다. [code:app/services/payout.py:1-3]

"그럼 입원은요?" 같은 후속 질문은 그대로는 검색이 안 된다. 그런데 **대화 이력을 프롬프트에 넣는 방식은 쓰지 않는다.**

**"더 짧게", "고객에게 말하듯이 다시" 같은 고쳐쓰기**는 검색 질의 문제가 아니라 직전 답변을 입력으로 받는 다른 작업이다. UI 버튼으로 받아 베이스 모델에 넘긴다. 약관 사실은 이미 직전 답변 안에 있으므로 베이스 모델로도 된다.

`build_messages(history=...)`도 `NotImplementedError`를 낸다. [code:data/prompts.py:167-169]

#### 1-5. 측정 흔들림 기준, 3회 평균 차이 4 안쪽은 효과로 보지 않는다 (2026-10-24)

평가 220 보이는 세트를 3회 돌린 평균끼리 비교할 때, **지표 차이가 회당 4턴 안쪽이면 효과로 보지 않는다.** 이 기준은 다음 지표에 쓴다. [code:data/review/age_measure.md:69] [c:d6906f1]

- 자동 통과
- 판정 정확·틀림·예외누락·거절
- 거절(전체)
- 정답이 있는데 거절

판정 대상 턴에 대한 비율로 비교할 때는 약 4.5%p다(판정 대상 약 90턴 기준). [code:data/review/age_measure.md:9] (2026-10-24 기준)

근거는 신규 가입 나이 코드 답 측정이다(`data/review/age_measure.md`). 대상 3문항 밖의 모델 턴 318개는 프롬프트가 기준 측정과 글자까지 같았다. 그런데도 3회 평균이 이만큼 움직였다. [code:data/review/age_measure.md:60] [c:d6906f1] (2026-10-24 기준)

| 지표 | 기준(pool 50) | 같은 프롬프트로 다시 잼 | 차이 |
|---|---|---|---|
| 판정 정확 | 53.0 | 49.0 | −4.0 (2026-10-24 기준) |
| 판정 예외누락 | 5.7 | 8.0 | +2.3 (2026-10-24 기준) |
| 자동 통과 | 164.0 | 162.0 | −2.0 [code:data/review/age_measure.md:5] [code:data/review/age_measure.md:10] [code:data/review/age_measure.md:12] (2026-10-24 기준) |

생성(temperature 0.3)과 판정 모델이 흔들린 것이다. 3-8의 실행별 SD(정확 1.8)로 보면 평균 하나의 흔들림은 1 정도지만, 독립된 두 3회 평균 사이는 4까지 벌어졌다. [code:data/review/rebuild5_stage7_config.md:50] [code:data/review/age_measure.md:69] [c:3f49bb5] <!-- 근거 파일: models/gguf/Modelfile.kabyul-tri-7b-rag1-rebuild4-ckpt462 3줄 PARAMETER temperature 0.3 -->

**효과로 인정하는 것**은 세 가지다.
1. 프롬프트가 바뀐 턴만 따로 본 변화다. 서버 프롬프트 기록(`PETMINT_PROMPT_LOG`)으로 바뀐 턴을 가린다 [code:app/config.py:76]
2. 같은 문항이 3회 모두 같은 쪽으로 바뀐 경우다. 예: S05 거절 3/3 → 정확 3/3 [code:data/review/pool_measure.md:58] (2026-10-24 기준)
3. 코드 답으로 넘어간 턴이다. 답이 정해져 있어 흔들리지 않는다

**적용 예.** pool 50의 판정 정확 +4.3(48.7 → 53.0)은 이 폭 안이라 효과로 보지 않는다. 확실한 효과는 둘이다. [code:data/review/age_measure.md:69] (2026-10-24 기준)
- 발췌가 바뀐 문항: S05·P47은 좋아지고 S11은 나빠졌다 [code:data/review/pool_measure.md:58] (2026-10-24 기준)
- 검색 회귀: @1·@3·@5 78·95·95 / MRR 0.880 → 80·97·97 / 0.897 [code:data/review/pool_measure.md:57] (2026-10-24 기준)

차이가 4 안쪽이고 위 세 가지에도 해당하지 않으면 "변화 없음"으로 적는다. 판단이 걸리면 실행 횟수를 늘려 다시 잰다.

#### 1-6. 판정에 "질문에 직접 답했나" 추가, 결론없음 (2026-10-24)

조건만 되풀이하고 질문의 경우가 된다/안 된다를 말하지 않은 답을 예전 판정은 정확으로 받았다. 예: S10 "1년 이내 접종 기록이 있으면 보상합니다" — 질문은 "8개월 전에 접종했어요"였다. 이런 답은 **결론없음**으로 센다(`scripts/eval_judge.py`). [code:scripts/eval_judge.py:3-5] [c:7814508]

- 기본 판정이 정확·예외누락이어도 아래 둘 중 하나면 결론없음이다 [code:scripts/eval_judge.py:7-8]
  1. 판정 모델의 결론 분류가 "조건만"이고, 질문이 된다/안 된다를 묻는다
  2. 질문의 기간 사실을 대입하지 않은 조건부 보상 문장이다(규칙) [code:data/review/judge_direct_answer.md:8-10]
- 결론 분류를 모든 질문에 쓰면 값·절차를 직접 답한 턴까지 깎였다(49턴 중 27턴). 그래서 된다/안 된다 질문으로 좁혔다 [code:scripts/eval_judge.py:13] [code:data/review/judge_direct_answer.md:15-16] (2026-10-24 기준)
- 같은 답을 다시 판정하니 판정 정확이 이렇게 바뀌었다(회당, 판정 대상 턴 대비)

| 측정 | 판정 정확 v1 → 새 |
|---|---|
| 3안′ | 53.5% → 47.6% (2026-10-24 기준) |
| pool 50 | 58.2% → 52.0% (2026-10-24 기준) |
| 지금 운영 설정 | 55.7% → 50.0% [code:data/review/judge_direct_answer.md:20-24] (2026-10-24 기준) |

결론없음은 회당 약 6턴(7%)이다. 이 날 이전의 "판정 정확"은 v1 기준이다. 이후 비교는 새 기준끼리 한다(예전 판정은 각 측정 폴더의 `judge_v1.json`). 기록은 `data/review/judge_direct_answer.md`에 있다. [code:data/review/judge_direct_answer.md:7] [code:data/review/judge_direct_answer.md:22-24] (2026-10-24 기준)

#### 1-7. 평가 기준일 고정과 문항 다섯 고침 (2026-10-24)

평가 서버가 실제 날짜로 대기기간·보험연도를 셌다. 그래서 같은 문항의 정답이 날마다 바뀌었다. 예를 들어 망고의 30일 창은 10-23에 끝났고, 별이는 10-30에 끝난다.

- 평가 전용 `PETMINT_TODAY`(`payout.today()`)를 두었다. 평가는 평가 파일의 기준일 2026-10-21로 돈다(`scripts/prod_measure.sh`). 운영은 비워 두어 실제 날짜를 쓴다 [code:app/config.py:64] [code:app/services/payout.py:120-121] [code:scripts/prod_measure.sh:6] [code:data/eval220.py:21] [c:80bfebe] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml 에 PETMINT_TODAY 키 없음, apps/petmint/app/deployment.yaml:77-83 -->
- S09·S10·S20·S27·M14(면책 단서 문항)를 별이에서 콩이로 바꿨다. 콩이는 Ⅰ 통원 고급형이고 2026-08-11에 가입했다 [code:data/eval220.py:133-134]
  - 별이는 기준일에 30일 대기기간 안이라, 질병이면 참고 답("보장된다")과 결론이 뒤집혔다 [code:data/eval220.py:133-134]
  - 대기기간은 C축이 잰다 [code:data/eval220.py:134]
- 대기기간 줄이 붙는 다른 문항도 살펴봤다. 참고 답이 이미 "안 된다"이거나 분류·금액을 묻는 문항이라 결론이 같다
- 숨긴 세트와 manifest는 그대로다(`data/eval220.py`에서 다시 만들어 글자까지 같은지 확인했다) [code:data/eval220.py:13] [code:data/eval220.py:23]

이날부터 기준선은 `logs/coverage/base2`다. 조건은 운영 설정, 기준일 고정, 고친 평가 파일, 결론없음 판정이다. 이 기준선은 판정 정확 44.7 / 판정 대상 88턴(50.8%), 자동 통과 164.0, N축 16/16이다. [code:data/review/eval_results_summary.md:171] [code:scripts/prod_measure.sh:6] (2026-10-24 기준)

---

### 2. 왜 이렇게 했나

#### 2-1. 학습 데이터 형식 — 왜 발췌를 넣는가

세 가지를 비교했다.

|  | A. 발췌 없음 | B. 정답 발췌 | C. 정답 + 방해 발췌 + 답 없음 |
| --- | --- | --- | --- |
| 모델이 배우는 것 | 사실을 외움 | 읽고 옮기기 | 읽기 + 관계없는 발췌 무시 + "확인 필요"라고 하기 |
| 샘플당 토큰(추정) | 약 250 | 약 850 | 약 1,500 |
| 학습 시간(추정) | 약 30분 | 약 1.6시간 | 약 3~3.5시간 |

**C를 선택했다.** 이유는 실제 RAG 상황과 같기 때문이다.

추론할 때 검색은 top_k개를 가져오는데 그중 일부는 질문과 관련이 없다. 정답 발췌만 주고 학습하면(B) 모델은 "주어진 건 전부 관련 있다"고 배운다. 방해 발췌를 섞어야 **무시하는 법**을 배운다.

"답 없음" 샘플은 검색이 실패했을 때를 위한 것이다. 발췌에 답이 없으면 지어내지 말고 "확인이 필요하다"고 말하도록 가르친다.

> 학습 시간이 생각보다 덜 늘어나는 이유: 3-2의 고정 패딩을 고치면 그만큼이 상쇄된다.
> 

#### 2-2. 고객 정보를 프롬프트에 넣지 않는 이유

**이유 ①: 검색 필터가 이미 처리한다**

```
넣는 방식    "이 고객은 고급형Ⅱ입니다. [발췌: 통원Ⅰ·Ⅱ·Ⅲ 전부] 질문: 수술비?"
             → 모델이 "고급형Ⅱ니까 Ⅱ를 봐야지"를 추론해야 함

지금 설계    검색이 이미 Ⅱ·고급형만 가져옴
             "[발췌: 통원Ⅱ 고급형] 질문: 수술비?"
             → 모델은 주어진 발췌만 읽으면 됨
```

01번부터 지켜온 **"모델이 추론할 필요를 없앤다"** 원칙을 그대로 이은 것이다.

**이유 ②: 학습에 없던 블록은 추론 때 쓸 수 없다**

추론 때만 넣는 선택지는 없다. 넣으려면 학습 데이터 전체에 고객 정보 블록을 붙여 다시 만들어야 한다.

**이유 ③: 7B가 가장 많이 틀리는 유형이다**

부담보("슬개골 탈구는 보장 제외")나 면책기간("가입 후 30일 이내 질병은 제외") 판단은 예외·단서 추론이다. 06번 심판 결과를 보면 모델이 가장 많이 틀리는 영역이다. <!-- 확인 못 함: 아래 28%, 18%, 17%는 06번 편에도 data/review에도 같은 숫자가 없어 근거를 찾지 못했다 -->

```
incomplete (핵심 조건 누락)  28%
reversal (결론 뒤집기)       18%
clause_mix (예외·단서 섞기)  17%
```

#### 2-3. 계산을 프롬프트에 넣지 않는 이유

05번에서 측정한 결과다.

| 조건 | 계산 오류율 | 파싱 실패 |
| --- | --- | --- |
| 아무 조치 없음 | 35% | 2/48 [docs:02_pipeline/05_faq_generation.md:82] |
| "직접 계산하지 말 것" 지시만 | 16% | 1/48 [docs:02_pipeline/05_faq_generation.md:83] |
| 지시 + 코드가 계산한 표를 프롬프트에 | 21% | 15/48 [docs:02_pipeline/05_faq_generation.md:84] |

**코드 계산표를 넣으니 오류가 오히려 올랐다**(16% → 21%). 그리고 프롬프트가 길어지면서 JSON 출력이 31% 깨졌다. [docs:02_pipeline/05_faq_generation.md:80-84]

이렇게 하면 **학습 데이터를 건드릴 필요가 없다.** 프롬프트에 계산값을 넣기로 하면 계산형 QA 289건 이상을 다시 만들어야 하고, 한도표가 바뀔 때마다 재학습해야 한다. <!-- 확인 못 함: 계산형 QA 289건은 05번 편에도 data/review에도 같은 숫자가 없어 근거를 찾지 못했다 -->

#### 2-4. 대화 이력을 넣지 않는 이유

학습 데이터는 전부 `[system, user]` 2턴이다. 이력을 넣으면 학습에 없던 형식이 되고 재학습이 필요하다. [code:data/prompts.py:176-182]

#### 2-5. rebuild5에서 남긴 원칙

- 판정 기준을 결과 전에 고정하고, 같은 날 같은 코드로 기준 모델을 다시 잰 것은 유지한다. rebuild5의 정확 +3.3은 그것만 보면 좋아 보였지만 틀림 +11이 함께 왔다 [code:data/review/rebuild5_verdict.md:12-13] (2026-10-22 기준)
- 체크포인트는 3-8절 점수로 select가 고른 것을 쓰고, 눈으로 뒤집지 않는다(2026-10-16 사용자 결정, docs/next_rebuild.md 10절) [docs:next_rebuild.md:310] [code:scripts/ckpt_select220.py:82]
- 거절 신호는 같은 질문의 짝(정답 있음/없음)으로 가르쳐야 하고, 짝이 없는 거절 샘플을 늘리면 맞히던 답까지 거절한다(5b)
- 코드: `data/faq_rag.py`(C 생성·판정·5b), `scripts/rebuild5_chain.sh`·`rebuild5b_chain.sh`(생성부터 판정까지 연쇄), `scripts/ckpt_select220.py`, `scripts/rebuild5_verdict.py`. 모델 `kabyul-tri-7b-rag1-rebuild5-ckpt250`·`-rebuild5b-ckpt250`은 Ollama에 등록만 되어 있다 [code:data/faq_rag.py] [code:scripts/rebuild5_chain.sh] [code:scripts/rebuild5b_chain.sh] [code:scripts/ckpt_select220.py] [code:scripts/rebuild5_verdict.py] <!-- 2026-11-19 잼: docker exec ollama ollama list 에 둘 다 있고(각 4.6GB) ollama ps 는 비어 있음 -->

---

### 3. 시도했던 것들

이 프로젝트에서 파인튜닝을 시도한 적이 있다. 옛 청크·옛 FAQ로 한 것이라 지금 데이터와 연결이 없어 별개 작업으로 보지만, 거기서 확인한 세 가지는 이번 설계의 근거가 됐다.

첫 재구축(rebuild)부터 rebuild4까지의 경과는 본문에 두지 않는다. rebuild는 docs/archive/07_finetuning_log.md 10절, rebuild2와 rebuild3는 docs/archive/next_rebuild_log.md 7, 8절, rebuild4 평가는 data/review/rebuild4_eval_compare_20261019.md에 있다. [code:data/review/rebuild4_eval_compare_20261019.md]

#### 3-1. 지시와 데이터가 모순이면 지시가 무시된다

```
system 프롬프트:  "발췌에 있는 내용만 근거로 답하라"
학습 데이터:      발췌 없음. question → answer
```

발췌를 주지 않으면서 "발췌만 보라"고 지시한 셈이다. 모델은 **사실을 가중치에 외우는 법**을 배웠고, 테스트에서 원문에 없는 "특별약관은 5영업일 이내"를 단정했다. <!-- 확인 못 함: 그때 원자료가 남지 않음(이전 시도의 테스트 기록, 노트북 설정 칸 주석에 요지만 있다) -->

"말투만 배우고 사실은 RAG가 담당한다"는 역할 분담과 정반대 결과다.

#### 3-2. 고정 패딩으로 계산의 2/3가 낭비됐다

모든 샘플을 768토큰으로 패딩했는데 실제 길이는 평균 250 정도였다. 동적 패딩과 `group_by_length`로 바꾸면 그만큼이 줄어든다. <!-- 확인 못 함: 그때 원자료가 남지 않음(이전 시도의 768토큰 패딩과 평균 250) -->

#### 3-3. loss를 전체에 걸면 안 된다

system 프롬프트와 질문에도 loss가 걸려 있었다. 발췌를 넣고 그대로 두면 **loss 대부분이 약관 원문을 외우는 데** 쓰인다.

#### 3-4. 메모리 문제, 쓰지 않을 logits를 만들고 있었다

첫 실행에서 step 2를 넘지 못하고 멈췄다.

```
[W] expandable_segments: memory mapping failed with OOM on device 0
    while trying to map 20971520 bytes (free: 7864320, total: 16608133120)
```

2분 동안 step 2에 머물렀고 free 메모리가 7.8MB → 3.6MB로 줄었다. GPU에 다른 프로세스는 없었다. (2026-10-13 기준) <!-- 확인 못 함: 그때 원자료가 남지 않음(첫 실행 로그) -->

**원인 ① 설정 실수**: 사전 점검(최대 할당 14.1GiB / 예약 15.1GiB)은 `expandable_segments` 없이 측정했는데, 그 뒤에 이 설정을 테스트 없이 넣었다. 여유가 0.4GiB뿐이라 메모리 매핑에 실패해도 OOM으로 멈추지 않고 재시도를 반복하며 진행하지 못했다. (2026-10-13 기준) [code:notebooks/07_파인튜닝.ipynb:337]

**원인 ② 진짜 병목**: loss는 답변 토큰(평균 45개)에만 거는데, 모델은 **시퀀스 전체(최대 3,064위치) × 어휘 128,256개의 logits를 fp32로** 만들고 있었다. (2026-10-13 기준) [code:notebooks/07_파인튜닝.ipynb:84] [code:notebooks/07_파인튜닝.ipynb:338-339]

```
logits 한 벌  3,072 × 128,256 × 4B ≈ 1.6GB
log_softmax와 gradient까지 2~3벌
```

`prepare_model_for_kbit_training`이 `lm_head`를 fp32로 올리기 때문이다. **쓰지도 않을 3,000개 위치를 계산하느라 메모리를 다 쓰고 있었다.**

**해결**: 답변은 항상 시퀀스 끝에 있으므로, `logits_to_keep=K`로 끝 K위치만 `lm_head`를 통과시킨다.

python

```python
def collate(features):    batch = data_collator(features)    first = (batch["labels"] != -100).float().argmax(dim=1)    batch["logits_to_keep"] = int(batch["labels"].shape[1] - first.min()) + 1    return batch
```

loss 정의는 바꾸지 않았다. HF 기본 loss와 `tail_loss`를 같은 샘플로 계산해 상대오차 1e-3 이하임을 확인했다. (2026-10-13 기준) [code:notebooks/07_파인튜닝.ipynb:337]

|  | 수정 전 | 수정 후 |
| --- | --- | --- |
| GPU 최대 할당 | 14.1GiB | 9.89GiB (2026-10-13 기준) |
| 예약 | 15.1GiB | 10.67GiB (2026-10-13 기준) <!-- 확인 못 함: 그때 원자료가 남지 않음(예약 10.67GiB는 노트북 출력에 없다) --> |
| 메모리 경고 | 반복 | 0건 |

> `gradient_checkpointing`을 켜는 것이 첫 대응이었지만, 확인해보니 이미 켜져 있었다(셀 4와 `prepare_model_for_kbit_training` 양쪽에서). [code:notebooks/07_파인튜닝.ipynb:394] [code:notebooks/07_파인튜닝.ipynb:167] 증상만 보고 흔한 처방을 하기 전에 **실제로 무엇이 메모리를 쓰는지** 확인해야 했다.
> 

#### 3-5. 실험 B — 발췌에 공통 적용 표기 추가 (폐기)

coverage_type이 None인 단위의 발췌 끝에 "이 조항은 가입 등급·유형과 관계없이 공통 적용됩니다" 한 줄을 추가했다. 의료비 특약은 유형이 특약명에 고정돼 있어 다른 문구를 썼다. [code:data/answer_eval.py:87] [code:data/answer_eval.py:534]

| 그룹 | 해소 |
| --- | --- |
| 등급 거절 15건 | **1건 (6.7%)** (2026-10-14 기준) |
| 등급 외 거절 21건 | **7건 (33%)** (2026-10-14 기준) [code:data/review/answer_eval_compare_20261014_1222_answer_eval_20261014_1011_rag-1_4811건_vs_answer_eval_20261014_1210_rag-1_4811건_note.md:10-11] |

**대조군이 더 많이 풀렸다.** 등급 정보를 채운 효과가 아니라 프롬프트가 한 줄 길어진 효과다.

베이스 모델도 전 구간에서 거절 수가 변했고(0→3, 2→5, 7→6), 답변 동일은 8/117에 그쳤다. 한 줄 추가로 생성 전체가 흔들렸다는 뜻이다. (2026-10-14 기준)

no_answer 거절은 14→15로 유지됐고 근거 반영도 53→62로 올랐지만, [code:data/review/eval_results_summary.md:34-35] (2026-10-14 기준) **왜 좋아졌는지 설명할 수 없는 설정**이라 채택하지 않았다.

> 대조군을 미리 정해둔 것이 결론을 뒤집었다. 등급 거절만 봤다면 "1건 해소, 효과 미미" 정도로 넘어갔을 것이다. 등급 외 21건이 더 많이 풀린 것을 보고서야 가설 자체가 틀렸음을 알았다.
> 

#### 3-6. 실험 A — 질문에서 등급 어구 제거

반대 방향. 발췌가 아니라 질문을 고친다.

```
"고급형인데 해지하면 환급금 있나요?"  →  "해지하면 환급금 있나요?"
```

등급은 이미 SearchScope가 검색 필터로 소비했다. [code:data/answer_eval.py:114-127] [code:data/answer_eval.py:535] "종·등급·유형은 UI/필터가 확정하고 모델은 추론하지 않는다"는 설계 원칙을 추론 단계까지 적용하는 것이다.

coverage_type이 지정된 단위(R026~029, R080 "고급형 수술 한도가 얼마인가요?")는 등급이 답을 가르므로 건드리지 않았다.

변환 19건 중 5건은 어구를 떼면 어색해진다("기본형 가입했는데" → "가입했는데"). 문법은 깨지지 않으나 결과 해석 시 따로 본다. (2026-10-14 기준) [code:data/review/answer_eval_20261014_1326_rag-1_4811건_qnorm_questions.md:3] <!-- 확인 못 함: 어색해지는 5건은 이 기록에 따로 세어져 있지 않다 -->

B와 달리 **등급 외 21건과 no_answer 20건은 프롬프트가 완전히 동일**하다. 이 두 그룹에서 답이 달라지면 정규화와 무관한 흔들림이다. [code:data/answer_eval.py:26-27]

**결과: 15건 중 3건 해소, 새 거절 2건.** [code:data/review/eval_results_summary.md:36] (2026-10-14 기준) 등급 어구를 떼는 것만으로는 풀리지 않는다. 등급 문제는 추론 단계가 아니라 학습 데이터에서 다뤄야 한다(docs/archive/07_finetuning_log.md 10-7절 3번).

#### 3-7. rebuild5와 5b, 답을 서빙 발췌로 다시 만들기(C), 불채택 (2026-10-22~23)

rebuild4(`kabyul-tri-7b-rag1-rebuild4-ckpt462`)가 운영 모델로 남는다. 학습 답을 서빙과 같은 검색 발췌로 다시 만드는 방향(C)을 두 번 시도했고 둘 다 채택 기준을 넘지 못해 접었다(2026-10-23 사용자 결정). 측정 기록은 `data/review/rebuild5_progress_20261021.md`, 판정표는 `data/review/rebuild5_verdict.md`·`rebuild5b_verdict.md`에 있다. [code:data/review/rebuild5_progress_20261021.md:318-320] [code:data/review/rebuild5_verdict.md:7] [code:data/review/rebuild5b_verdict.md:7] [c:c5c1ca7]

rebuild4까지는 05가 원문 단위(조항 하나)를 보고 쓴 답을 학습 목표로 썼다. 학습 때 모델이 보는 발췌는 서빙 검색 결과와 달랐고, 서빙 평가에서 **정답 조항이 프롬프트에 있는데도 거절하는 턴**이 회당 15턴 안팎 남았다. C는 학습 발췌를 서빙 발췌와 같게 맞추려 했다. [code:data/review/rebuild5_verdict.md:11] (2026-10-22 기준)

- 질문은 05·06에서 통과한 final 7,483건을 그대로 쓴다. 06에서 incomplete로 버린 4,769건은 쓰지 않았다(파일럿에서 효율이 나빴다) [code:data/review/rebuild5_progress_20261021.md:253-255] [code:data/faq_rag.py:300-304] (2026-10-22 기준)
- 질문마다 서빙 B 경로(청크 v3 조각으로 찾고 부모를 보여 줌, 질의 확장, 1차 후보 20, 상위 3, 예산 2,400)로 발췌를 만든다 [code:data/faq_rag.py:8] [code:data/faq_rag.py:12] [code:data/faq_rag.py:19-20]
- 그 발췌만 보고 qwen3:14b가 "결론 + 단서"로 답을 새로 쓴다. 발췌에 답이 없으면 거절 문장을 쓴다 [code:data/faq_rag.py:13] [code:data/faq_rag.py:42]
- 판정 ①은 발췌를 기준으로 gemma4:12b가 본다. 판정 ②는 원문 단위를 기준으로 06 심판이 보되 뒤집힘·값·용어만 센다. 그 뒤 숫자가 발췌에 있는지와 계산을 코드로 검사한다 [code:data/faq_rag.py:14-16]
- 판정 정책(사용자 확정): unsupported·reversal·wrong_value·잘못된 거절·발췌에 없는 숫자·계산 오류는 버린다. ①의 clause_mix·missing_condition만 걸린 답은 경고(answer_warn)로 남긴다(표본 판독에서 오탐이 절반이었다) [code:data/faq_rag.py:142-170] [code:data/review/rebuild5_progress_20261021.md:242-243] (2026-10-22 기준)
- 파일럿 세 번을 거쳤다. 1차에서 "단서는 '다만'으로"라는 생성 규칙이 단서를 지어내게 만들어 이 규칙을 뺐다. 2차에서 등급이 없는 질문에 한 등급의 한도를 일반 답처럼 쓰는 문제가 나와, 등급 단위 질문은 그 등급 가입 고객으로 범위를 좁혔다. 3차에서 버린 비율은 70건 중 9건으로 줄었다 [code:data/review/rebuild5_progress_20261021.md:235] [code:data/review/rebuild5_progress_20261021.md:249-252] (2026-10-22 기준)

#### 3-8. rebuild5와 5b 채택 기준, 미리 고정

같은 날 같은 코드로 rebuild4와 새 모델을 평가 220 보이는 세트에서 3회 재고 평균을 비교한다. 기준은 결과를 보기 전에 정해 `data/review/rebuild5_stage7_config.md`에 고정했다. 실행 사이 흔들림(SD)은 정확 1.8 · 틀림 1.4 · 예외누락 1.7 · 거절 1.0 · 정답 있는데 거절 0.8이다. [code:data/review/rebuild5_stage7_config.md:32-34] [code:data/review/rebuild5_stage7_config.md:50]

| # | 기준 | 선 |
|---|---|---|
| 1 | 정답이 프롬프트에 있는데 거절 | 5 이상 줄어야 함 |
| 2 | 판정 정확 | +5 이상 |
| 3 | 판정 틀림 | +2 이하 |
| 4 | 판정 예외누락 | +3 이하 |
| 5 | N축(답이 없는 질문) 거절 | 15/16 이상 |
| 6 | 축별 정확 | 어느 축도 −3 넘게 떨어지지 않음 |
| 7 | 숨긴 세트 정확 비율 | 보이는 세트보다 10%p 넘게 낮지 않음(경보만) [code:data/review/rebuild5_stage7_config.md:37-45] |

1~6을 모두 넘으면 채택한다. 1·2만 못 넘고 3~6을 넘으면 보류한다. 3이나 5를 어기면 불채택이다. 체크포인트는 평가 220 보이는 세트로 고른다(점수 = 정확 − 2×틀림 + 거절해야 할 턴을 거절한 수). [code:data/review/rebuild5_stage7_config.md:47-49] [code:scripts/rebuild5_verdict.py] [code:scripts/ckpt_select220.py:8] [code:scripts/ckpt_select220.py:79]

#### 3-9. rebuild5와 5b 결과

| 기준 | rebuild4 | rebuild5 | rebuild5b |
|---|---|---|---|
| 1 정답이 프롬프트에 있는데 거절 | 14.7 | 7.0 ✅ | 21.3 ❌ (2026-10-22~2026-10-23 사이) |
| 2 판정 정확 | 50.7 | 54.0 ❌ | 44.3 ❌ (2026-10-22~2026-10-23 사이) |
| 3 판정 틀림 | 9.0 | **20.0 ❌** | **13.3 ❌** (2026-10-22~2026-10-23 사이) |
| 4 판정 예외누락 | 7.3 | 10.7 ❌ | 4.7 ✅ (2026-10-22~2026-10-23 사이) |
| 5 N축 거절 | 16/16 | 16/16 ✅ | 16/16 ✅ (2026-10-22~2026-10-23 사이) |
| 6 축별 정확 최저 | | −0.7 ✅ | S축 −6.0 ❌ [code:data/review/rebuild5_verdict.md:9-16] [code:data/review/rebuild5b_verdict.md:9-16] (2026-10-22~2026-10-23 사이) |
| 학습 샘플(train) | 7,376 | 5,640 | 6,098 [code:data/review/eval_results_summary.md:82] [code:data/review/rebuild5_progress_20261021.md:266] [code:data/review/rebuild5_progress_20261021.md:302] (2026-10-19~2026-10-23 사이) |
| 거절 샘플 비율 | 10% | 4.8% | 24.2% [code:data/review/rebuild5_progress_20261021.md:287] (2026-10-22~2026-10-23 사이) |
| 선택 체크포인트 | 462 | 250 | 250 [code:data/review/eval_results_summary.md:17] [code:data/review/rebuild5_progress_20261021.md:267] [code:data/review/rebuild5_progress_20261021.md:304] |

**rebuild5** — C 전량을 그대로 학습했다(answer 4,161 · 경고 1,831 · 거절 299 · 버림 1,192). 거절은 크게 줄었지만 줄어든 거절이 대부분 틀린 답이 되었다. 판정 이동(3회 합)은 거절→틀림 33, 거절→정확 12였다. [code:data/review/rebuild5_progress_20261021.md:266] [code:data/review/rebuild5_progress_20261021.md:281] (2026-10-22 기준)

- 정답이 프롬프트에 없는 턴: 거절 19.0 → 9.7, 틀림 4.0 → 10.0. 근거 없이 답하기 시작했다(가족 간 소송을 "보상됩니다", 토요일을 영업일로) [code:data/review/rebuild5_progress_20261021.md:282] (2026-10-22 기준)
- 정답이 프롬프트에 있는 턴: 틀림 5.0 → 10.0. 결론을 먼저 단정하고 뒤의 단서가 그 결론과 어긋난다("보장됩니다. 다만 … 지급 대상이 아닙니다"). 나이와 기간 비교도 틀린다 [code:data/review/rebuild5_progress_20261021.md:283-284] (2026-10-22 기준)
- 원인: **정답 조항이 발췌에 없는데 답한 샘플이 743건(train의 13%)**인데 거절 샘플은 258건이었다. rebuild4에는 같은 질문을 정답 있는 발췌와 없는 발췌로 짝지은 거절 748건(10%)이 있어 "정답이 없으면 거절"이라는 신호가 강했다. C에서는 판정 ①이 "다른 발췌로 뒷받침된다"고 본 답을 그대로 남겼고, 그 결과 이 신호가 뒤집혔다 [code:data/review/rebuild5_progress_20261021.md:286-288] (2026-10-22 기준)

**rebuild5b** — 사용자 지시로 세 가지를 한꺼번에 고쳤다(`faq_rag.prep5b`·`build5b`). [code:data/faq_rag.py:442] [code:data/faq_rag.py:471] [code:scripts/rebuild5b_chain.sh]

- 정답 조항이 발췌에 없는 답(826건, val 몫 포함)을 모두 거절로 바꿨다 [code:data/review/rebuild5_progress_20261021.md:293] [code:data/review/rebuild5_progress_20261021.md:302] (2026-10-23 기준)
- 짝 거절을 되살렸다. 같은 질문을 서빙 경로로 검색하되 정답 조항이 든 결과를 빼고 다음 순위로 채운 발췌를 만들고, 판정 ①이 "답할 수 없다"고 본 521건을 넣었다(900건 중) [code:data/faq_rag.py:382] [code:data/review/rebuild5_progress_20261021.md:294-295] [code:data/review/rebuild5_progress_20261021.md:301] (2026-10-23 기준)
- 결론 단정을 완화했다. 정답이 있고 단서·예외가 붙은 답 2,357건의 첫 문장을 조건부로 다시 썼고, 검사를 통과해 바뀐 1,365건을 썼다 [code:data/review/rebuild5_progress_20261021.md:296-297] [code:data/review/rebuild5_progress_20261021.md:301] (2026-10-23 기준)

그러자 거절이 너무 늘었다(정확→거절 27). 틀림은 여전히 rebuild4보다 많았고(정확→틀림 13), "보장됩니다. 다만 … 보장하지 않습니다" 모순도 남았다(S07·S11). [code:data/review/rebuild5_progress_20261021.md:314] (2026-10-23 기준)

#### 3-10. rebuild5와 5b 왜 안 됐나, 체크포인트와 거절 비율 탓이 아니다

체크포인트 선택표(같은 114턴, 1회차 모델 답 턴)에서 rebuild4는 정확 51 · 틀림 10 · 거절 31이다. rebuild5(50~354)와 5b(50~382)의 체크포인트 중 이를 넘은 것은 하나도 없다. [code:data/review/rebuild5_progress_20261021.md:315-316] [code:scripts/ckpt_select220.py:68-88] (2026-10-23 기준)

| 후보 | 정확 | 틀림 | 거절 |
|---|---|---|---|
| rebuild4 ckpt462 | 51 | 10 | 31 (2026-10-23 기준) |
| rebuild5 ckpt250 | 51 | 18 | 18 (2026-10-23 기준) |
| rebuild5 ckpt50 | 34 | 13 | 40 (2026-10-22 기준) [code:data/review/ckpt_select220_rag-1_5640건_rebuild5_20261022_1930.md:7] |
| rebuild5b ckpt300 | 46 | 13 | 30 (2026-10-23 기준) |
| rebuild5b ckpt250 | 43 | 9 | 41 [code:data/review/rebuild5_progress_20261021.md:316] (2026-10-23 기준) |

거절을 rebuild4와 비슷한 수준으로 맞춰도(5b ckpt300) 정확은 낮고 틀림은 많다. 거절 비율을 어느 쪽으로 옮겨도 rebuild4의 선 위로 올라가지 못했다. [code:data/review/rebuild5_progress_20261021.md:315-317] (2026-10-23 기준) 그래서 **C로 다시 만든 답 자체가 rebuild4의 05 답보다 학습 목표로 나쁘다**고 판단했다. 이유로 보이는 것은 다음과 같다(직접 분리해 재지는 않았다).

- 05 답은 원문 단위 전체를 보고 쓰고 06이 원문 단위와 대조해 걸렀다. C 답은 잘린 발췌 셋만 보고 쓰고, 판정 ①도 같은 발췌만 본다. 발췌 밖의 단서를 빠뜨린 답을 잡을 수 없다
- 경고 답 1,831건(24%)을 학습에 넣었다. clause_mix·missing_condition은 평가의 예외누락·틀림과 같은 종류의 결함이다 [code:data/review/rebuild5_progress_20261021.md:266] [code:data/faq_rag.py:58-59] (2026-10-22 기준)
- 생성 모델(qwen3:14b)이 "결론부터"라는 형식에서 단서와 어긋나는 결론을 자주 썼고, 이 형식이 학습된 모델에 그대로 옮았다

#### 3-11. 멀티턴 처리를 바꾼 까닭

업무특화 멀티턴에서 LLM 재작성을 쓰지 않고 앞 기준 질문에 이어 붙이게 바꾼 까닭은 09번 「업무특화는 LLM 재작성을 하지 않는다」 문단에 있다. [docs:02_pipeline/09_ui_design.md]

---

### 4. 남은 한계

- 학습 발췌를 서빙과 맞추는 것만으로는 "정답이 있는데 거절"이 풀리지 않는다. 거절이 줄어든 만큼 틀림이 늘었다. 이 지표 하나만 목표로 삼지 않는다. 까닭: 3-10절 「C로 다시 만든 답 자체가 rebuild4의 05 답보다 학습 목표로 나쁘다」

