next_rebuild 에서 떼어 낸 구현 기록(2026-11-19 문서 정리 B단계). 지금 설계는 docs/next_rebuild.md

절 번호(7, 8, 8-1, 8-2, 8-3)는 떼어 내기 전 docs/next_rebuild.md 의 번호 그대로다. 「2-1」, 「3절」, 「4번 기준」처럼 번호만 쓴 참조는 docs/next_rebuild.md 의 그 절을 가리킨다.

#### 7. 진행 기록 — 2026-10-15 rebuild2 (build·train만, gen·check·rewrite는 rebuild 재사용)

실행: `python -m data.rebuild run build train --name=rebuild2 --src=rebuild --na-judge=q2 --na-fill=refill --distractor-hard --pair-na --gate-max-na-judge-bad=0.15 --gate-max-low-overlap-na=off --gate-min-low-overlap-pos=off` [code:data/rebuild.py:418-419] [c:c8d9211]

진행 중 내린 결정(사용자 지시: "결정이 필요하면 가장 보수적인 쪽으로 정하고 진행한 뒤 보고"):

| 결정 | 내용 | 이유 |
|---|---|---|
| q2로 라벨링을 사람 확인 20건 전에 시작 | 확인지 `data/review/na_qjudge_q2_check20_20261015.md`는 따로 둔다 | q2가 과하게 잡으면 그 방해 발췌를 no_answer에 쓰지 않을 뿐(다른 후보·다른 QA로 채움) — 틀린 라벨을 만들지 않는 쪽의 오류다. 과함이 5건을 넘으면 손해는 no_answer 후보 손실이다 [code:data/review/na_qjudge_q2_check20_20261015.md:3-6] [c:c8d9211] |
| 판정 모델 | 라벨링 gemma4:12b(q2), 확인 검사 qwen3:14b | gemma4:12b는 06 심판으로 측정해 고른 모델(생성 모델 Tri-7B와 달라야 같은 곳에서 틀리지 않는다, Apache 2.0, 로컬). 학습할 모델(Tri-7B)로 라벨을 판정하면 학생의 독해 실수가 라벨에 들어간다. 확인 검사는 독립이어야 하므로 다른 모델(qwen3:14b, Apache 2.0, 로컬) [code:data/faq_judge.py:5] [code:data/na_qjudge.py:93] |
| 확인 검사 처리 | 답이 있다고 본 no_answer 비율 > 15%면 빌드 중단, 아니면 그 샘플과 쌍을 뺀다 | 두 판정기 중 하나라도 답이 있다고 본 발췌는 no_answer로 쓰지 않는다. 15%는 사용자가 정한 판정 수정 기준선과 같게 [code:data/finetune_data.py:76] [code:data/finetune_data.py:718-719] |
| 2-4 검사 중 겹침 구간 NA 비율·겹침 0.2 미만 양성 | 이번 build에서는 **끔(기록만)** | 이 두 항목은 2-2(짧은 구어체)·2-3(등급 어구) — rewrite 단계 — 로 맞추는 기준이다. 이번은 build 단계 변경(쌍·가까운 오답·판정)만의 효과를 재는 3절 C단계다. 켜 두면 확정적으로 미달이라 학습이 시작되지 않는다. 수치는 pipeline.log에 남는다 [code:data/rebuild.py:122-123] [c:c8d9211] |
| 2-4 쌍 비율 | 켬(0.9) | 이번 변경의 대상 [code:data/rebuild.py:124] |
| 가까운 오답 | 같은 조 제외 규칙을 풀고 proximity 순(같은 조 → 인접 조 → 같은 문서 → 다른 문서) | 지금까지 no_answer 방해 발췌 1,351개 중 다른 문서 970(72%), 같은 조 0. 같은 조 옆 청크는 답을 담기 쉬우므로 답 섞임은 q2·확인 검사가 거른다 [code:data/finetune_data.py:225-232] [c:c8d9211] (2026-10-15 기준) <!-- 확인 못 함: 방해 발췌 개수는 data/finetune/ 학습 데이터로 센 값인데 너무 커서(약 1.5GB) 올리지 않음 --> |
| 체크포인트 | 07 `save_total_limit=None` | rebuild는 3개(350·400·426)만 남아 100~250은 잴 수 없다. rebuild2부터 50 step마다 전부 남긴다(어댑터 193MB/개) [code:data/ckpt_select.py:116] [c:c8d9211] (2026-10-15 기준) <!-- 확인 못 함: 어댑터는 165GB 모델 가중치(models/)라 올리지 않음 --> |

학습 뒤 할 것: 세 모델(베이스·4811·rebuild)+rebuild2를 같은 코드로(청크 선택 수정 반영) 정답 발췌 입력·검색 입력(top 3) 두 가지로 잰다. [code:data/answer_eval.py:214] [c:c8d9211]
rebuild 체크포인트 350·400·426, rebuild2 체크포인트 전부를 잰다. [c:c8d9211]
검색 입력 사전 확인(모델 없이): gold 97건 중 정답 조문이 top 3 안 81건(1위 66), answerable 69/85. [code:data/review/answer_eval_rebuild2_20261016.md:35-43] [c:c8d9211] (2026-10-15 기준) <!-- 확인 못 함: 출처 기록을 찾지 못함(81건, 1위 66. 69/85만 걸어 둔 기록이 받친다) -->

**build 결과(22:08)** — 첫 실행은 확인 검사에서 멈췄다(qwen3:14b가 no_answer 760건 중 162건 = 21.3%를 답 있음으로 봄, 상한 15%). [code:data/review/na_confirm_qwen_check12_20261015.md:3] [code:data/finetune_data.py:76] [c:dcdecd9] (2026-10-15 기준) <!-- 요약: data/review/faq_build_summary.md 6-1절 185줄 -->
12건을 읽어 보니 과함 8 · 맞음 3 · 애매 1(`data/review/na_confirm_qwen_check12_20261015.md`) — 비율 대부분이 확인 모델의 과잉 판정이다. [code:data/review/na_confirm_qwen_check12_20261015.md:20] (2026-10-15 기준)
보수적으로 정했다: 162건과 그 쌍을 빼고(`--confirm-max-bad=1`) 다시 빌드, 이 build에 한해 `--gate-min-no-answer-ratio=0.07`·`--gate-max-na-judge-bad=0.25`. [code:data/review/na_confirm_qwen_check12_20261015.md:22] [code:data/rebuild.py:772] [c:c8d9211]

| 항목 | rebuild | rebuild2 |
|---|---|---|
| 전체 | 7,598 | 8,034 (train 7,192) [c:c8d9211] [c:dcdecd9] (2026-10-15 기준) <!-- 요약: data/review/faq_build_summary.md 6-1절 178~184줄(rebuild 칸의 겹침 구간 셋은 rebuild/stats.json에 없어 셀 수 없음) --> |
| no_answer | 760 (10.0%) | 598 (7.4%) [c:c8d9211] (2026-10-15 기준) |
| q2 판정(라벨링) | — | <!-- 「새 호출 2,061」은 stats.json(na_judge_new_calls 0)에도 다른 기록에도 없어 지웠다(2026-11-19) -->yes 893 / no 1,349 / unclear 1 (가까운 오답이라 yes가 많다) [c:c8d9211] (2026-10-15 기준) |
| 겹침 0.1~0.2 구간 NA 비율 | 41.2% | 37.2% [c:c8d9211] (2026-10-15 기준) |
| 겹침 0.2~0.3 구간 NA 비율 | 27.2% | 22.9% [c:c8d9211] (2026-10-15 기준) |
| 겹침 0.2 미만 양성 | 1.8% | 1.8% [c:c8d9211] (2026-10-15 기준) |
| 쌍이 있는 no_answer | 0% | 100% [code:data/finetune_data.py:314] [c:c8d9211] (2026-10-15 기준) |

쌍 구성만으로는 낮은 겹침 구간의 no_answer 비율이 거의 내려가지 않았다 — 쌍의 양성은 정답 발췌가 더해져 겹침이 높은 구간에 들어간다. [c:c8d9211]
이 구간은 2-2(짧은 구어체 양성)로 맞춰야 한다는 것이 확인됐다. [c:c8d9211]
확인 모델로서 qwen3:14b는 이대로 부적합 — 다음 재구축 전에 확인 검사 방식을 다시 정한다. [code:data/review/na_confirm_qwen_check12_20261015.md:23]

**train 결과(2026-10-16 02:51)** — 어댑터 `rag-1_7192건_rebuild2`, 4.71시간(예상 6.2), 450 step, 체크포인트 50~450 아홉 개(최종 = checkpoint-450). [c:55eb4bb] <!-- 확인 못 함: 학습 로그와 어댑터는 165GB 모델 가중치(models/)와 함께 있어 올리지 않음 -->
eval_loss는 끝까지 내려갔다(과적합 신호 없음). val 세트가 rebuild와 달라 두 줄의 절대값은 비교하지 않는다. [c:55eb4bb]

| step | 50 | 100 | 150 | 200 | 250 | 300 | 350 | 400 | 최종 |
|---|---|---|---|---|---|---|---|---|---|
| rebuild2 | 0.524 | 0.481 | 0.462 | 0.453 | 0.443 | 0.439 | 0.435 | 0.433 | 0.433 (450) [c:55eb4bb] (2026-10-16 기준) |
| rebuild | 0.521 | 0.474 | 0.455 | 0.440 | 0.434 | 0.430 | 0.425 | 0.423 | 0.423 (426) [c:55eb4bb] (2026-10-16 기준) |

**판정(2026-10-16)** — 기록 `data/review/answer_eval_rebuild2_20261016.md`. [code:data/review/answer_eval_rebuild2_20261016.md] [c:6e5a340]

| 기준 | 목표 | rebuild | rebuild2(최종 450) |
|---|---|---|---|
| A1 answerable 거절(깨진 발췌 5문항 뺀 범위, 기준선 21) | ≤ 12 | 21 | **12 (달성, 경계)** [code:data/review/answer_eval_rebuild2_20261016.md:25-26] (2026-10-16 기준) |
| answerable 거절(85문항 전체) | — | 25 | 16 [code:data/review/answer_eval_rebuild2_20261016.md:20-21] (2026-10-16 기준) |
| partial 해소 | 보고만 | 9 거절 | 7 거절(R036·R099 풀림) [code:data/review/answer_eval_rebuild2_20261016.md:28] (2026-10-16 기준) |
| 등급 어구 거절 | 절반 이하(≤11/23) | 17/23 | 15/23 (미달 — 2-3 미구현) [code:data/review/answer_eval_rebuild2_20261016.md:29] (2026-10-16 기준) |
| no_answer 거절 | ≥ 14/20 | 15 | 14 (경계) [code:data/review/answer_eval_rebuild2_20261016.md:30] (2026-10-16 기준) |
| 회귀(4811이 답했는데 거절) | 검토 | R064 | R064 (그대로) [code:data/review/answer_eval_rebuild2_20261016.md:31] |
| 검색 입력: 정답이 top 3에 있는 answerable 거절 | — | 14/69 | **8/69** (베이스 9) [code:data/review/answer_eval_rebuild2_20261016.md:35-40] (2026-10-16 기준) |

측정 중 버그: `answer_eval`에 어댑터 여러 개를 주면 0번 어댑터가 베이스로 생성됐다(`0 == False`). 고쳤고, 영향받은 세 결과는 다시 쟀다. [code:data/answer_eval.py:166] [code:data/review/answer_eval_rebuild2_20261016.md:9-11] [c:6e5a340]
체크포인트: 거절은 100 step 뒤 19~25를 오르내리는데 val loss는 계속 내려간다 → 다음 학습부터 `select` 단계를 넣었다 [code:data/review/answer_eval_rebuild2_20261016.md:46-55] [code:data/rebuild.py:79] (2026-10-16 기준)
(`data/ckpt_select.py`, 고정 선택 세트 30문항 — answerable 22 + no_answer 8, 판정 보고는 선택 세트를 뺀 나머지도 따로). [code:data/ckpt_select.py:8-11] [code:data/eval/ckpt_select_set.json]

#### 8. rebuild3 — B-1 사전 확인(2026-10-16, 본 실행 전)

설정(사용자 확정): 생성·재작성 qwen3:14b(think:false), 순서 B(생성 → 재작성 → 06 → build), 구성 90/0/10, 방해 발췌 1:2, [code:data/rebuild.py:52] [c:657dcab]
q2 판정(gemma4:12b), 확인 검사 끔 → 빌드 뒤 사람 표본 검수, 겹침 구간 검사 켬, select. [code:data/rebuild.py:35-39] [code:data/rebuild.py:52] [code:data/rebuild.py:82] [c:657dcab]

B-1: rebuild의 학습용 final(7,598 QA)에 새 build 설정만 적용(`--name=rebuild3_b1 --src=rebuild --composition=90/0/10 --n-distract=2 --no-confirm`). [code:data/rebuild.py:420-421] [c:657dcab]

| 항목 | rebuild2 | B-1 | 기준 |
|---|---|---|---|
| 전체 샘플 | 8,034 | 5,667 | — [c:657dcab] [c:dcdecd9] (2026-10-16 기준) <!-- 요약: data/review/faq_build_summary.md 6-1절 186~191줄 --> |
| 방해 후보가 없어 버린 QA | — | **2,691 / 7,598 (35%)**(특별약관 2,555) | — [code:data/finetune_data.py:107] [c:657dcab] (2026-10-16 기준) |
| no_answer 비율 | 7.4% | 13.4% | — [c:657dcab] (2026-10-16 기준) |
| 겹침 0.1~0.2 구간 NA | 37.2% | **56.9%** | ≤ 전체 × 1.5 = 20.1% [code:data/rebuild.py:122] [c:657dcab] (2026-10-16 기준) |
| 겹침 0.2~0.3 구간 NA | 22.9% | **33.5%** | ≤ 20.1% [c:657dcab] [c:dcdecd9] (2026-10-16 기준) <!-- 요약: data/review/faq_build_summary.md 6-1절 190줄(207/617) --> |
| 겹침 0.2 미만 양성 | 1.8% | **1.3%** | ≥ 10% [code:data/rebuild.py:123] [c:657dcab] (2026-10-16 기준) |
| 쌍 | 100% | 100% | ≥ 90% [code:data/rebuild.py:124] [c:657dcab] (2026-10-16 기준) |

→ **미달. 본 실행 전에 멈춤.** [c:657dcab]
- 버린 2,691건은 검색 top 6이 전부 정답 단위이거나 답이 글자로 든 발췌였다. 60건 표본을 다시 검색해 보니 top 12에서 40건, [code:data/rebuild.py:38] [c:657dcab] (2026-10-16 기준)
  top 20에서 47건이 방해 후보를 얻었다. [c:657dcab] (2026-10-16 기준)
- B-1은 rebuild의 질문을 썼다. 이 중 실제로 재작성된 것은 4,007/7,598뿐이다. 순서 B에서는 05 QA 전부를 재작성하므로 [c:657dcab] [c:dcdecd9] (2026-10-16 기준) <!-- 요약: data/review/faq_build_summary.md 5절 138줄 -->
  질문과 정답 발췌의 겹침이 낮아진다. 실험 G(n≈40)에서 겹침 0.2 미만 비율은 rebuild final 5.3%, A(재작성 없음) 2.3%, [c:657dcab] (2026-10-16 기준) <!-- 확인 못 함: 출처 기록을 찾지 못함 -->
  B_qwen(qwen 재작성) 11.1%였다. B-1은 이 변화를 반영하지 못해 비관적인 쪽으로 기운 예측이다. [c:657dcab] <!-- 확인 못 함: 출처 기록을 찾지 못함 -->

사용자 결정(B-1 뒤): 방해 후보는 top 20으로 늘리고 그래도 없으면 gold_only로 남긴다 · B-1′(qwen 재작성 후 build) 실행 · [code:data/rebuild.py:38] [c:026a7b9]
등급 어구는 재작성의 대체 방식(전체 10%) · 미달이면 07번 10-7절 3번(짧은 구어체 양성). [code:data/rebuild.py:52] [docs:02_pipeline/07_finetuning.md:565] [c:026a7b9]

#### 8-1. B-1′ — rebuild 06 final 7,598건을 qwen3:14b로 재작성한 뒤 build(2026-10-16)

재작성(106분, 0.84초/건): 실패 7.0%(rejected 531 · unchanged 96), 등급 어구 738건(9.7%), 상황형 57.6%, 질문 길이 중앙 48자. [c:026a7b9] [c:dcdecd9] (2026-10-16 기준) <!-- 요약: data/review/faq_build_summary.md 7절 208~211줄(원자료 data/faq/rebuild3_b1p/rewrite_summary.json) -->
요약의 `label_leak` 10.3%는 "답변 누출"이 아니라 질문 속 `약관·특약·제N조·별표` 표현 비율이다. 784건 모두 원래 질문에 있던 것이고 [code:data/faq_rewrite.py:120-123] [c:026a7b9] [c:dcdecd9] (2026-10-16 기준) <!-- 요약: data/review/faq_build_summary.md 7절 212줄 -->
재작성이 새로 넣은 것은 0건(재작성 전 23.3%). [c:026a7b9] (2026-10-16 기준)

| 항목 | B-1 | B-1′ | 기준 |
|---|---|---|---|
| 전체 샘플 | 5,667 | 8,358 (train 7,500 · val 858) | — [c:026a7b9] [c:dcdecd9] (2026-10-16 기준) <!-- 요약: data/review/faq_build_summary.md 6-1절 192~196줄 --> |
| gold_only(top 20에도 방해 후보 없음) | — | 331 (4.0%) | — [code:data/rebuild.py:38] [c:026a7b9] (2026-10-16 기준) |
| no_answer 비율 | 13.4% | 9.1% | — [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.0~0.1 구간 NA | — | 67.6% (25/37) | ≤ 13.6% [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.1~0.2 구간 NA | 56.9% | **48.0%** (147/306) | ≤ 13.6% [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.2~0.3 구간 NA | 33.6% | **21.5%** (231/1,075) | ≤ 13.6% [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.2 미만 양성 | 1.3% | **2.2%** | ≥ 10% [c:026a7b9] (2026-10-16 기준) |

→ **미달.** 학습 시간 예측: 학습 데이터 글자 수가 rebuild2의 1.28배(4.71시간) → 약 6시간. [c:026a7b9] (2026-10-16 기준)

**답변 누출 검사 추가**(사용자 확정): 재작성 질문에 원래 질문에 없던 답변의 숫자, 또는 명사형 4자 이상 어구가 들어가면 거절 [code:data/faq_rewrite.py:144-149] [c:026a7b9]
(`faq_rewrite.answer_leak`). B-1′ 재작성 6,971건 중 120건(1.7%)이 걸린다. 숫자 46건 중 29건이 실제 누출("연간 총 보상한도는 [code:data/faq_rewrite.py:126-129] [c:026a7b9] [c:dcdecd9] (2026-10-16 기준) <!-- 요약: data/review/faq_build_summary.md 7절 213줄(6,971건) -->
750만원인가요?"), 17건은 고객 상황 숫자다. 거절해도 원래 질문이 06으로 가므로 QA는 잃지 않는다(구어체만 잃는다). [code:data/faq_rewrite.py:127] (2026-10-16 기준)
4자 조각 규칙은 1,611건(23%)이 걸려 너무 넓었다. [code:data/faq_rewrite.py:129] (2026-10-16 기준)

#### 8-2. 짧은 구어체 재작성 예측(10-7절 3번, 300건)

B-1′ final에서 등급 어구가 아닌 QA 300건(seed 42)을 20~35자·원문 표현 피하기 프롬프트로 qwen3:14b 재작성 → 06 심판(gemma4:12b) [code:data/faq_judge.py:19] [c:026a7b9]
→ B-1′ 빌드 샘플의 발췌는 그대로 두고 질문만 바꿔 겹침 재계산. 스크립트·결과는 저장소 밖(세션 scratchpad). [c:026a7b9] <!-- 확인 못 함: 그때 원자료가 남지 않음(예측 스크립트와 결과는 세션 scratchpad에만 있었음) -->

- 재작성 ok 270 · 06 통과 237(79%, incomplete 14 · wrong_term 9 · clause_mix 6). **길이 중앙 44자** — 20~35자 지시를 거의 따르지 않았다. [c:026a7b9] (2026-10-16 기준)
- 양성 겹침 평균 0.435 → 0.445. 거의 그대로다. 대체 비율을 100%로 해도 0.1~0.2 구간 NA 30.9%, 겹침 0.2 미만 양성 2.8%. [c:026a7b9] (2026-10-16 기준)
- 원인: 양성의 발췌 묶음이 길다(중앙 3,008자 = 정답 + 방해 2). 겹침은 "질문 바이그램 중 발췌에 있는 비율"이라 발췌가 길고 [code:data/finetune_data.py:284] [c:026a7b9] (2026-10-16 기준)
  주제가 맞으면 질문을 바꿔도 내려가지 않는다. no_answer 발췌는 중앙 1,260자(방해 2개 이하). [c:026a7b9] (2026-10-16 기준)
- **더 큰 문제 — 발췌 개수가 라벨을 알려 준다.** B-1′ train에서 발췌 3개: 양성 6,226 / no_answer 0, 2개: 양성 291 / no_answer 649. [c:026a7b9] (2026-10-16 기준)
  `--n-distract 2`로 양성은 정답 + 방해 2가 됐는데 no_answer는 방해 2개까지만 쓴다. 겹침보다 직접적인 지름길이다. [code:data/rebuild.py:36-37]
  → 3번(짧은 구어체)으로는 검사를 통과할 수 없다. no_answer 방해 발췌를 3개로 맞추는 `--na-items 3`을 B-1″로 측정한다. [code:data/rebuild.py:37] [code:data/rebuild.py:423] [c:026a7b9]

#### 8-3. B-1″ — B-1′ + no_answer 방해 발췌 3개(`--na-items 3`)

| 항목 | B-1′ | B-1″ | 기준 |
|---|---|---|---|
| 겹침 0.0~0.1 구간 NA | 67.6% | 63.6% (21/33) | ≤ 13.6% [c:026a7b9] [c:dcdecd9] (2026-10-16 기준) <!-- 요약: data/review/faq_build_summary.md 6-1절 197~200줄(발췌 3개인 샘플 중 no_answer 8.5%는 stats.json에 없어 셀 수 없음) --> |
| 겹침 0.1~0.2 구간 NA | 48.0% | **43.8%** (124/283) | ≤ 13.6% [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.2~0.3 구간 NA | 21.5% | **19.4%** (203/1,047) | ≤ 13.6% [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.2 미만 양성 | 2.2% | 2.2% | ≥ 10% [c:026a7b9] (2026-10-16 기준) |
| no_answer 겹침 평균 | 0.295 | 0.318 | — [c:026a7b9] (2026-10-16 기준) |
| 발췌 3개인 샘플 중 no_answer | 0% | 8.5% (643/7,552) — 전체 9.1%와 같다 | — [c:026a7b9] (2026-10-16 기준) |

→ 겹침 검사는 세 번 모두 미달(방향은 맞다: 0.1~0.2 구간 56.9 → 48.0 → 43.8%). **사용자 결정(2026-10-16): 본 실행은 겹침 검사를 끄고 간다.** [c:026a7b9]
기준 13.6%(전체 × 1.5)는 근거 없이 정한 값이고, rebuild2가 이미 answerable 거절 12건으로 목표를 맞췄다. 구간별 비율은 `stats.json`의 [code:data/rebuild.py:122] [code:data/review/answer_eval_rebuild2_20261016.md:25-26]
`overlap_bins`에 남는다. 발췌 개수 지름길은 `--na-items 3`으로 없앴다. [code:data/finetune_data.py:608] [code:data/rebuild.py:37]

본 실행 설정(사용자 확정): `--order=B --name=rebuild3 --composition=90/0/10 --n-distract=2 --na-items=3 --no-confirm --search-top-k=20
--na-judge=q2 --na-fill=refill --distractor-hard --pair-na --gate-max-na-judge-bad=off --gate-max-low-overlap-na=off --gate-min-low-overlap-pos=off`. [code:data/rebuild.py:35-39] [code:data/rebuild.py:418-423] [c:026a7b9]
판정 기준: answerable 거절 ≤ 12 · 등급 어구 거절 ≤ 11/23 · no_answer 거절 ≥ 14/20 · 검색 입력 정답 top 3 answerable 거절 ≤ **8**/69. [code:data/review/answer_eval_rebuild2_20261016.md:21] [code:data/review/answer_eval_rebuild2_20261016.md:40]
