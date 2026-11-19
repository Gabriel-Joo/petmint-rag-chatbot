# FAQ 검증과 학습 데이터 빌드 요약 (원자료는 git 밖)

원자료는 git 밖이다. 아래 다섯 곳이고, 크기는 2026-11-19 기준이다. 이 파일은 문서가 인용하는 숫자를 원자료에서 다시 뽑은 요약이다.

| 원자료 | 파일 수 | 크기(바이트) | `.gitignore` |
|---|---|---|---|
| `data/faq/checked/`(06번 첫 학습용 결과, `unit_coverage.json` 포함) | 8 | 27,078,715 | 10줄 `data/faq/` |
| `data/faq/rebuild/logs/`(첫 재구축 파이프라인 로그) | 10 | 2,380,198 | 10줄 `data/faq/` |
| `data/faq/rebuild/rewrite/final/`(첫 재구축 재작성 결과) | 2 | 10,644,197 | 10줄 `data/faq/` |
| `data/finetune/` 아래 `stats.json` 13개와 `na_judge_summary*.json` 5개 | 18 | 26,116 | 11줄 `data/finetune/` |
| `data/finetune/train.jsonl`(첫 학습 데이터) | 1 | 31,320,746 | 11줄 `data/finetune/` |

- 원자료는 올리지 않는다(2026-11-11 사용자 결정, `docs/README.md` 2절). 문서가 숫자를 인용할 때는 원자료 대신 이 파일을 가리킨다.
- 2026-11-19에 원본 폴더에서 파일을 읽어 다시 셌다. 질문과 답 본문, 약관 문장은 옮기지 않았다. 수, 분포, 파일 이름, 크기, 파일 수정 시각만 적는다.
- 7절의 `data/faq/rebuild3_b1p/rewrite_summary.json` 하나는 위 다섯 곳 밖이다. 문서(`docs/archive/next_rebuild_log.md` 8-1절)가 그 숫자를 인용해서 함께 적었다.
- 문서 줄 번호는 커밋 15f1f7a 판이다.

## 읽는 법

- **문서 값**과 **다시 센 값**이 같으면 **맞음** 칸이 「맞음」이다. 다르면 「다름」이고 까닭을 적는다. 문서에 없는 참고 값은 「참고」다.
- 「06번」은 `docs/02_pipeline/06_quality_check.md`, 「07번」은 `docs/02_pipeline/07_finetuning.md`, 「next_rebuild」는 `docs/next_rebuild.md`다.
- 시각은 모두 2026년이고 파일 수정 시각이다.

## 1. 06번 결과 파일 (`data/faq/checked/`)

| 파일 | 크기(바이트) | 시각 | 레코드 수 |
|---|---|---|---|
| petmint_강아지_faq_checked_all.json | 8,771,625 | 10-13 16:27 | 7,097 |
| petmint_고양이_faq_checked_all.json | 8,190,048 | 10-13 16:27 | 6,663 |
| petmint_강아지_faq_final.json | 2,803,633 | 10-13 16:27 | 2,779 |
| petmint_고양이_faq_final.json | 2,598,674 | 10-13 16:27 | 2,564 |
| petmint_강아지_review_queue.json | 223,796 | 10-13 16:27 | 156 |
| petmint_고양이_review_queue.json | 259,169 | 10-13 16:27 | 174 |
| unit_coverage.json | 227,924 | 10-13 16:27 | 단위 575(강아지 301, 고양이 274) |
| judge_cache.json | 4,003,846 | 10-13 16:27 | 판정 13,754 |

## 2. 06번 단계별 건수

`*_faq_checked_all.json`의 `checks`에서 `action == "drop"`인 첫 검사로 버린 사유를 셌다. `decision`은 pass, flag, drop 셋이다.

| 단계 | 문서 값(강아지 / 고양이 / 합계) | 다시 센 값 | 맞음 | 센 방법 | 문서 |
|---|---|---|---|---|---|
| 05번 생성 | 7,097 / 6,663 / 13,760 | 7,097 / 6,663 / 13,760 | 맞음 | checked_all 레코드 수 | 06번 1-4-1절 |
| 심판 버림 | 2,968 / 2,640 / 5,608 | 2,968 / 2,640 / 5,608 | 맞음 | 첫 버림 검사가 `judge` | 06번 1-4-1절 |
| 중복 제거 | 996 / 1,028 / 2,024 | 996 / 1,028 / 2,024 | 맞음 | 첫 버림 검사가 `duplicate` | 06번 1-4-1절 |
| 단위 상한 | 333 / 406 / 739 | 333 / 406 / 739 | 맞음 | 첫 버림 검사가 `unit_cap` | 06번 1-4-1절 |
| 제외 단위(도입 문장) | 21 / 24 / 45 | 21 / 24 / 45 | 맞음 | 첫 버림 검사가 `unit_excluded` | 06번 1-4-1절, 1-4-2절 |
| 메타데이터 버림 | 0 / 1 / 1 | 0 / 1 / 1 | 맞음 | 첫 버림 검사가 `grade_confusion`(고양이 1). 종 혼동 검사로 버린 것은 없다 | 06번 1-4-1절 |
| 최종 | 2,779(39%) / 2,564(38%) / 5,343 | 2,779 / 2,564 / 5,343 | 맞음 | final 레코드 수. pass 2,623 + flag 156, pass 2,390 + flag 174 | 06번 1-4-1절 |
| flag(사람 검수 대기열) | 156 / 174 / 330 | 156 / 174 / 330 | 맞음 | review_queue 레코드 수 = `decision == "flag"` | 06번 1-4-1절, 4절 |
| 비율: 심판, 중복, 상한 | 41%, 15%, 5% | 40.8%, 14.7%, 5.4% | 맞음 | 위 합계 ÷ 13,760 | 06번 4절 |

참고: 표시(flag) 검사 횟수는 강아지 needs_review 403, number_grounding 211, article_ref 36, care_type 1, judge_fail 1, limit_value 1이고, 고양이 needs_review 429, number_grounding 172, article_ref 13, limit_value 2, care_type 1이다. 한 QA에 여러 표시가 붙을 수 있어 flag 건수(156, 174)보다 많다.

참고: 라운드별 생성 수는 강아지 1~7라운드 803~828, 8~10라운드 470~481이고, 고양이 1~8라운드 709~735, 9~10라운드 434~436이다. 05번 표의 「7회(600자 이상 단위 10회)」, 「8회」와 맞는다.

참고: 1인칭 상황형 질문 비율(`docs/archive/07_finetuning_log.md` 9절 「06 심판은 무죄」 표). 문서 값은 통과 5,343건 1.10%, 탈락 8,417건 1.07%(2026-10-14)다. 그때 쓴 판별 정의는 git에 없다(지금 판별 함수 `data/faq_style.py`의 `SITUATIONAL`은 2026-10-15 커밋 8ebacfc에 처음 들어왔다). 그래서 문서 값은 지금 같은 방법으로 다시 낼 수 없다. 2026-11-19에 `checked_all` 두 파일 13,760건을 `decision != "drop"`으로 통과와 탈락을 가르고 `data.faq_style.is_situational(question)`으로 세면 통과 66/5,343 = 1.24%, 탈락 89/8,417 = 1.06%다. 둘 다 1% 안팎으로 차이가 작다는 문서의 결론은 같다.

## 3. 06번 단위 커버리지 (`unit_coverage.json`)

`generated`(생성), `capped`(단위 상한으로 버림), `kept`(최종에 남음)를 셌다. `drop_reasons`는 575개 단위 모두 비어 있다. 도입 문장 단위(45건을 낸 단위)는 이 파일에 없다(생성 합계가 7,076, 6,639로 checked_all보다 21, 24 적다).

| 항목 | 문서 값 | 다시 센 값 | 맞음 | 센 방법 | 문서 |
|---|---|---|---|---|---|
| 전체 단위 | 301, 274 | 301, 274 | 맞음 | 종별 레코드 수 | 06번 1-4-2절 |
| 생성 안 됨 | 0, 0 | 0, 0 | 맞음 | `generated == 0` | 06번 1-4-2절 |
| 전부 버려짐 | 0, 0 | 0, 0 | 맞음 | `generated > 0`이고 `kept == 0` | 06번 2-3절, 1-4-2절 |
| 잔여 25% 미만 | 36, 33(합계 69) | 36, 33 | 맞음 | `kept / (generated - capped) < 0.25`. 분모에 상한 버림을 넣으면 64, 55로 다르다 | 06번 2-3절, 1-4-2절 |

### 3-1. 잔여율이 낮은 섹션

`section_name`별로 `kept`와 `generated - capped`를 더했다. 문서 표 열 줄이 모두 이 정의로 맞는다. 분모에 상한 버림을 넣으면 고양이 지정대리청구서비스 특별약관이 50/186, 고양이 보험료 자동납입 특별약관이 19/72로 문서와 달라진다.

| 섹션 | 문서 값 | 다시 센 값 | 맞음 | 문서 |
|---|---|---|---|---|
| 고양이 【별표4】 민사소송 인지액 /【별표5】 송달료 | 3/15 (20%) | 3/15 | 맞음 | 06번 1-4-3절 |
| 강아지 보험금 지급 절차 | 9/40 (22%) | 9/40 | 맞음 | 06번 1-4-3절 |
| 강아지 【별표4】 민사소송 인지액 /【별표5】 송달료 | 3/12 (25%) | 3/12 | 맞음 | 06번 1-4-3절 |
| 고양이 가입자 유의사항 | 5/20 (25%) | 5/20 | 맞음 | 06번 1-4-3절 |
| 고양이 지정대리청구서비스 특별약관 | 50/172 (29%) | 50/172 | 맞음 | 06번 1-4-3절 |
| 강아지 보험용어 해설 | 6/20 (30%) | 6/20 | 맞음 | 06번 1-4-3절 |
| 고양이 보험료 자동납입 특별약관 | 19/62 (31%) | 19/62 | 맞음 | 06번 1-4-3절 |
| 강아지 【별표3】 소송목적의 값에 따른 변호사비용 | 5/16 (31%) | 5/16 | 맞음 | 06번 1-4-3절 |
| 고양이 【별표3】 소송목적의 값에 따른 변호사비용 | 5/16 (31%) | 5/16 | 맞음 | 06번 1-4-3절 |
| 고양이 특정질병 분류표(반려묘) | 32/100 (32%) | 32/100 | 맞음 | 06번 1-4-3절 |

참고: 같은 정의로 33% 아래인 섹션이 둘 더 있다. 고양이 보장성보험 보험료 납입유예 특별약관 77/239(32%), 강아지 지정대리청구서비스 특별약관 53/161(33%, 반올림 전 32.9%).

### 3-2. 중간 측정 값 (최종 파일과 다름)

06번 1-4-2절 일부는 생성 7~8라운드 때의 중간 측정이다(06번 1-4-2절). 최종 파일에는 그 시점 값이 남아 있지 않다.

| 항목 | 문서 값 | 최종 파일 값 | 맞음 | 문서 |
|---|---|---|---|---|
| 비용손해 일반조항 제2조 뒤쪽 단위 잔여 | 8~13/21 | 강아지 14, 20, 12, 12 / 30과 6/17, 고양이 13, 22, 12, 13 / 30과 6/16 | 다름(문서는 중간 측정, 최종은 10라운드 뒤) | 06번 1-4-2절 |
| 전부 버려진 단위 사유별 건수(21 → 0 등 네 줄) | 표 네 줄 | 최종 파일에 전부 버려진 단위 없음, `drop_reasons` 비어 있음 | 셀 수 없음 | 06번 1-4-2절 |
| 중복, 심판 순서 수정으로 되찾은 QA | +177 | 최종 파일로 셀 수 없음 | 셀 수 없음 | 06번 2-3절 |
| 측정 시점 전부 버려진 단위 | 4개 | 최종 파일로 셀 수 없음 | 셀 수 없음 | 06번 1-4-2절 |

## 4. 첫 재구축 파이프라인 (`data/faq/rebuild/logs/`)

| 파일 | 크기(바이트) | 시각 |
|---|---|---|
| pipeline.log | 5,234 | 10-15 18:06 |
| state.json | 1,771 | 10-15 18:06 |
| gen_20261014_205650.log | 38,676 | 10-15 03:54 |
| check_20261015_035419.log | 550 | 10-15 09:47 |
| rewrite_20261015_094744.log | 2,220,647 | 10-15 12:45 |
| build_20261015_124508.log | 6,848 | 10-15 13:44 |
| train_20261015_134443.log | 550 | 10-15 18:06 |
| 06_executed_20261015_0354.ipynb | 41,034 | 10-15 09:47 |
| 07_executed_20261015_1344.ipynb | 64,888 | 10-15 18:06 |
| rebuild.lock | 0 | 10-14 20:56 |

`pipeline.log`의 단계 끝 줄과 `state.json`의 `seconds`로 셌다.

| 단계 | 문서 값 | 다시 센 값 | 맞음 | 문서 |
|---|---|---|---|---|
| 생성 | 6.96h, 20,871건 | 6.96시간(25,048초), 다음 단계 입력 QA 20,871건 | 맞음 | `docs/archive/07_finetuning_log.md` 10-1절; next_rebuild 3절 |
| 심판(check) | 5.89h, 7,598건 | 5.89시간(21,205초), 최종 QA 7,598건 | 맞음 | `docs/archive/07_finetuning_log.md` 10-1절; next_rebuild 3절 |
| 재작성 | 2.96h, 7,598건, 상황형 1.7% → 30.3% | 2.96시간(10,644초), 학습용 QA 7,598건, 상황형 1.7% → 30.3% | 맞음 | `docs/archive/07_finetuning_log.md` 10-1절; next_rebuild 3절 |
| 빌드 | 0.99h, train 6,806 / val 792 | 0.99시간(3,575초), train 6,806 / val 792 | 맞음 | `docs/archive/07_finetuning_log.md` 10-1절; next_rebuild 3절 |
| 학습 | 4.36h, 어댑터 `rag-1_6806건_rebuild` | 4.36시간(15,712초), 같은 어댑터 이름 | 맞음 | `docs/archive/07_finetuning_log.md` 10-1절; next_rebuild 3절 |
| 합계 | 약 21.2시간 | 21.16시간 | 맞음 | next_rebuild 3절 |
| 생성 + 심판 + 재작성 | 약 15.8시간 | 15.81시간 | 맞음 | next_rebuild 3절 |
| 빌드 검사 | no_answer 중 판정이 no 아닌 것 0건 | 0/760(0.0%), 통과 | 맞음 | `docs/archive/07_finetuning_log.md` 10-1절 |

참고: 재작성 상태는 ok 4,007, reverted_rejudge 956, rejected 1,788, unchanged 847이다(5절과 같다). 라벨 누출은 06 뒤 23.3%, 재작성 뒤 21.9%다.

## 5. 첫 재구축 재작성 결과 (`data/faq/rebuild/rewrite/final/`)

| 파일 | 크기(바이트) | 시각 | QA 수 | rewrite_status |
|---|---|---|---|---|
| petmint_강아지_faq_final.json | 5,470,971 | 10-15 12:45 | 3,928 | ok 2,077, reverted_rejudge 509, rejected 931, unchanged 411 |
| petmint_고양이_faq_final.json | 5,173,226 | 10-15 12:45 | 3,670 | ok 1,930, reverted_rejudge 447, rejected 857, unchanged 436 |

| 항목 | 문서 값 | 다시 센 값 | 맞음 | 문서 |
|---|---|---|---|---|
| 학습용 final QA 수 | 7,598 | 7,598 | 맞음 | next_rebuild 3절, `docs/archive/next_rebuild_log.md` 8절 |
| 실제로 재작성된 것 | 4,007/7,598 | ok 4,007 | 맞음 | `docs/archive/next_rebuild_log.md` 8절 |

## 6. 빌드 통계 (`stats.json`, `na_judge_summary*.json`)

한 줄이 `stats.json` 하나다. 「합계」는 `kind_distract + kind_distract_pair + kind_gold_only + kind_no_answer`이고 train과 val을 합친 샘플 수다.

| 판(폴더) | 시각 | 합계 | train / val | distract / pair / gold_only / no_answer | no_answer 비율 | 겹침 0.2 미만 양성 |
|---|---|---|---|---|---|---|
| 첫 학습(`data/finetune/`) | 10-13 17:41 | 5,343 | 4,811 / 532 | 3,509 / - / 1,300 / 534 | - | - |
| search_base_20261014 | 10-14 16:28 | 4,356 | 3,948 / 408 | 2,788 / - / 1,132 / 436 | - | - |
| search_judge_v2_20261014 | 10-14 19:35 | 4,356 | 3,948 / 408 | 2,760 / - / 1,160 / 436 | - | - |
| rebuild | 10-15 13:44 | 7,598 | 6,806 / 792 | 4,097 / - / 2,741 / 760 | 10.0% | 기록 없음 |
| rebuild2 | 10-15 22:08 | 8,034 | 7,192 / 842 | 4,033 / 598 / 2,805 / 598 | 7.44% | 1.83% |
| rebuild3_b1(B-1) | 10-16 14:54 | 5,667 | 5,108 / 559 | 4,147 / 760 / 0 / 760 | 13.41% | 1.32% |
| rebuild3_b1p(B-1′) | 10-16 18:12 | 8,358 | 7,500 / 858 | 6,507 / 760 / 331 / 760 | 9.09% | 2.25% |
| rebuild3_b1pp(B-1″) | 10-16 18:50 | 8,358 | 7,500 / 858 | 6,507 / 760 / 331 / 760 | 9.09% | 2.25% |
| exp_r3smoke | 10-16 18:59 | 93 | 86 / 7 | 76 / 8 / 1 / 8 | 8.6% | 1.18% |
| rebuild3 | 10-17 16:00 | 7,932 | 7,099 / 833 | 6,331 / 721 / 159 / 721 | 9.09% | 4.85% |
| rebuild4 | 10-19 00:57 | 8,228 | 7,376 / 852 | 6,546 / 748 / 186 / 748 | 9.09% | 4.71% |
| rebuild5 | 10-22 13:46 | 6,291 | 5,640 / 651 | 기록 없음 | - | - |
| rebuild5b | 10-23 02:28 | 6,812 | 6,098 / 714 | 기록 없음 | - | - |

`na_judge_summary*.json` 다섯 개:

| 파일 | 시각 | 모델, 프롬프트 | 샘플 판정 | 발췌 판정 |
|---|---|---|---|---|
| search_base_20261014/na_judge_summary.json | 10-14 16:44 | gemma4:12b, 첫 판 | no 305, yes 92, unclear 39 (436) | no 618, yes 131, unclear 54 (803) |
| search_base_20261014/na_judge_summary_v2.json | 10-14 19:08 | gemma4:12b, v2 | no 326, yes 110 (436) | no 649, yes 154 (803) |
| search_judge_v2_20261014/na_judge_summary_v2.json | 10-14 19:35 | gemma4:12b, v2 | no 436 (436) | no 780 (780) |
| rebuild/na_judge_summary_v2.json | 10-15 13:44 | gemma4:12b, v2 | no 760 (760) | no 1,351 (1,351) |
| rebuild2/na_judge_summary_q2.json | 10-15 22:08 | qwen3:14b, q2(확인 검사) | no 598, yes 162 (760) | none 1,132, full 120, partial 97 (1,349) |

### 6-1. 문서가 인용하는 숫자

겹침 구간 비율은 `overlap_bins.bins`의 그 구간 `na / (pos + na)`다.

| 항목 | 문서 값 | 다시 센 값 | 맞음 | 원자료 | 문서 |
|---|---|---|---|---|---|
| rebuild 구성 | distract 4,097 / gold_only 2,741 / no_answer 760(10.0%) | 같음 | 맞음 | rebuild/stats.json | `docs/archive/07_finetuning_log.md` 10-1절 |
| 이전 데이터의 답 든 no_answer | 25.2% | 110/436 = 25.2% | 맞음 | search_base_20261014/na_judge_summary_v2.json의 샘플 yes | `docs/archive/07_finetuning_log.md` 10-1절 |
| rebuild 전체, no_answer | 7,598, 760(10.0%) | 같음 | 맞음 | rebuild/stats.json | `docs/archive/next_rebuild_log.md` 7절 |
| rebuild2 전체, train | 8,034(train 7,192) | 같음 | 맞음 | rebuild2/stats.json | `docs/archive/next_rebuild_log.md` 7절 |
| rebuild2 no_answer | 598(7.4%) | 598, 7.44% | 맞음 | rebuild2/stats.json | `docs/archive/next_rebuild_log.md` 7절 |
| rebuild2 q2 판정 | 새 호출 2,061, yes 893 / no 1,349 / unclear 1 | yes 893 / no 1,349 / unclear 1, 새 호출 칸은 0 | 다름(새 호출 2,061은 stats.json에 없다) | rebuild2/stats.json | `docs/archive/next_rebuild_log.md` 7절 |
| rebuild2 겹침 0.1~0.2, 0.2~0.3 구간 NA | 37.2%, 22.9% | 77/207 = 37.2%, 183/798 = 22.9% | 맞음 | rebuild2/stats.json | `docs/archive/next_rebuild_log.md` 7절 |
| rebuild 겹침 구간 NA, 0.2 미만 양성 | 41.2%, 27.2%, 1.8% | rebuild/stats.json에 `overlap_bins`가 없다 | 셀 수 없음 | - | `docs/archive/next_rebuild_log.md` 7절 |
| rebuild2 겹침 0.2 미만 양성, 쌍 | 1.8%, 100% | 1.83%, `pair_ratio` 1.0 | 맞음 | rebuild2/stats.json | `docs/archive/next_rebuild_log.md` 7절 |
| 확인 검사가 답 있음으로 본 것 | 760건 중 162건 = 21.3% | 162/760 = 21.3% | 맞음 | rebuild2/stats.json `na_confirm`, na_judge_summary_q2.json | `docs/archive/next_rebuild_log.md` 7절 |
| B-1 전체 샘플 | 5,667 | 5,667 | 맞음 | rebuild3_b1/stats.json | `docs/archive/next_rebuild_log.md` 8절 |
| B-1 방해 후보가 없어 버린 QA | 2,691 / 7,598(35%), 특별약관 2,555 | 2,691(`dropped_no_distractor`) | 맞음(특별약관 2,555는 stats.json에 없다) | rebuild3_b1/stats.json | `docs/archive/next_rebuild_log.md` 8절 |
| B-1 no_answer 비율 | 13.4% | 13.41% | 맞음 | rebuild3_b1/stats.json | `docs/archive/next_rebuild_log.md` 8절 |
| B-1 겹침 0.1~0.2 구간 NA | 56.9% | 82/144 = 56.9% | 맞음 | rebuild3_b1/stats.json | `docs/archive/next_rebuild_log.md` 8절 |
| B-1 겹침 0.2~0.3 구간 NA | 33.6% | 207/617 = 33.5% | 다름(0.1%p. 원자료로 나누면 33.549%라 반올림하면 33.5%다) | rebuild3_b1/stats.json | `docs/archive/next_rebuild_log.md` 8절 |
| B-1 겹침 0.2 미만 양성 | 1.3% | 1.32% | 맞음 | rebuild3_b1/stats.json | `docs/archive/next_rebuild_log.md` 8절 |
| B-1′ 전체 샘플 | 8,358(train 7,500, val 858) | 같음 | 맞음 | rebuild3_b1p/stats.json | `docs/archive/next_rebuild_log.md` 8-1절 |
| B-1′ gold_only | 331(4.0%) | 331, 3.96% | 맞음 | rebuild3_b1p/stats.json | `docs/archive/next_rebuild_log.md` 8-1절 |
| B-1′ no_answer 비율 | 9.1% | 9.09% | 맞음 | rebuild3_b1p/stats.json | `docs/archive/next_rebuild_log.md` 8-1절 |
| B-1′ 겹침 구간 NA(0.0~0.1, 0.1~0.2, 0.2~0.3) | 67.6%(25/37), 48.0%(147/306), 21.5%(231/1,075) | 같음 | 맞음 | rebuild3_b1p/stats.json | `docs/archive/next_rebuild_log.md` 8-1절 |
| B-1′ 겹침 0.2 미만 양성 | 2.2% | 2.25% | 맞음 | rebuild3_b1p/stats.json | `docs/archive/next_rebuild_log.md` 8-1절 |
| B-1″ 겹침 구간 NA(0.0~0.1, 0.1~0.2, 0.2~0.3) | 63.6%(21/33), 43.8%(124/283), 19.4%(203/1,047) | 같음 | 맞음 | rebuild3_b1pp/stats.json | `docs/archive/next_rebuild_log.md` 8-3절 |
| B-1″ 겹침 0.2 미만 양성 | 2.2% | 2.25% | 맞음 | rebuild3_b1pp/stats.json | `docs/archive/next_rebuild_log.md` 8-3절 |
| no_answer 겹침 평균 | 0.295 → 0.318 | 0.295, 0.318 | 맞음 | rebuild3_b1p, rebuild3_b1pp의 `overlap.no_answer.mean` | `docs/archive/next_rebuild_log.md` 8-3절 |
| 발췌 3개인 샘플 중 no_answer | 8.5%(643/7,552) | stats.json에 없다 | 셀 수 없음 | - | `docs/archive/next_rebuild_log.md` 8-3절 |

## 7. B-1′ 재작성 요약 (`data/faq/rebuild3_b1p/rewrite_summary.json`)

257바이트, 10-16 16:49. 위 다섯 곳 밖의 파일이다.

| 항목 | 문서 값 | 다시 센 값 | 맞음 | 문서 |
|---|---|---|---|---|
| 실패율 | 7.0%(rejected 531, unchanged 96) | `fail_rate` 0.0699, rejected 531, unchanged 96 | 맞음 | `docs/archive/next_rebuild_log.md` 8-1절 |
| 등급 어구 | 738건(9.7%) | `grade_ok` 738, 0.0971(대상 773) | 맞음 | `docs/archive/next_rebuild_log.md` 8-1절 |
| 상황형 | 57.6% | 0.5757 | 맞음 | `docs/archive/next_rebuild_log.md` 8-1절 |
| 질문 길이 중앙 | 48자 | 48.0 | 맞음 | `docs/archive/next_rebuild_log.md` 8-1절 |
| `label_leak` | 10.3%, 784건 | 0.1032 × 7,598 = 784 | 맞음 | `docs/archive/next_rebuild_log.md` 8-1절 |
| 재작성된 것 | 6,971건 | ok 6,971 | 맞음 | `docs/archive/next_rebuild_log.md` 8-1절 |

## 8. 첫 학습 데이터 (`data/finetune/train.jsonl`)

10-13 17:41, 31,320,746바이트, 4,811줄. 각 줄의 `meta`만 읽었다. 사람 대상 조항은 `data/faq_units.py`(커밋 15f1f7a 판)의 `is_human_target`을 `meta.unit_id`의 섹션, 섹션 이름, 조 번호에 걸어 셌다.

| 항목 | 문서 값 | 다시 센 값 | 맞음 | 문서 |
|---|---|---|---|---|
| train | 4,811(511단위) | 4,811, `stats.json`의 train_units 511 | 맞음 | `docs/archive/07_finetuning_log.md` 8-2절 |
| val | 532(55단위) | val.jsonl 532줄, val_units 55 | 맞음 | `docs/archive/07_finetuning_log.md` 8-2절 |
| distract, gold_only, no_answer | 3,164(65.8%), 1,163(24.2%), 484(10.1%) | 3,164, 1,163, 484 | 맞음 | `docs/archive/07_finetuning_log.md` 8-2절 |
| train과 val이 겹치는 단위 | 0개 | `unit_overlap` 0 | 맞음 | `docs/archive/07_finetuning_log.md` 8-2절 |
| 토큰 길이 | 평균 1,209 / 중앙 1,073 / p90 2,057 / 최대 3,064 | 같음(`meta.n_tokens`) | 맞음 | `docs/archive/07_finetuning_log.md` 8-2절 |
| 사람 대상 제외 조항 샘플 | 863건(18%) | 863(17.9%) | 맞음 | `docs/archive/07_finetuning_log.md` 9절 |
| 그중 보통약관 제24조 | 14건 | 14 | 맞음 | `docs/archive/07_finetuning_log.md` 9절 |
| 그중 장해분류표 | 561건 | 561(【별표2】 장해분류표) | 맞음 | `docs/archive/07_finetuning_log.md` 9절 |

참고: 863건의 나머지는 이륜자동차 운전중 상해 부보장 특별약관 54, 보통약관 제16조 36, 제22조 35, 제5조 34, 제9조 26, 제38조 22, 제10조 20, 제11조 19, 제25조 18, 제4조 14, 제3조 10이다. 종별로는 강아지 2,516, 고양이 2,295다.

참고: `stats.json`(첫 학습)의 kind 칸(3,509 / 1,300 / 534)은 train과 val을 합친 수다. 문서 `docs/archive/07_finetuning_log.md` 8-2절은 train만 센 수다.
