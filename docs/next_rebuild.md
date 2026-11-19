<!--
다루는 곳: data/finetune_data.py, data/rebuild.py, data/faq_rewrite.py, data/na_judge.py, data/na_qjudge.py, data/answer_eval.py, data/ckpt_select.py, data/search_scope.py, data/faq_style.py
읽은 커밋: 6710b83
-->
#### 0. 한 줄 요약

파인튜닝 모델은 질문의 형태(발췌와의 단어 겹침·길이·등급 어구)를 보고 거절을 정한다. 다음 재구축은 **같은 질문을 양성과 no_answer 양쪽에 넣어** 질문 형태로는 라벨을 맞힐 수 없게 하고, 같은 분포가 다시 나오면 **학습 전에 build 검사에서 멈춘다**. [code:data/review/refusal_overlap_20261015.md:15-25] [code:data/rebuild.py:121-124] [c:14ba033]

- 상태: 2026-10-15 채택한 변경(2-1·2-4)은 rebuild2(7절)·rebuild3(8절)에 들어갔다. 운영은 rebuild4, rebuild5·5b(C)는 불채택(07 11절). 9·10절이 다음 재구축에 남은 것이다. [docs:02_pipeline/07_finetuning.md:574] [c:12a4e2b]
- 2026-10-15 당시 순서: **no_answer 판정 확인(3절 0단계) → (필요하면 판정 수정) → 2-4 검사 → 2-1 쌍 구성 → build**. [c:14ba033]
- 근거 측정: `data/review/refusal_overlap_20261015.md` (스크립트 `data/review/refusal_overlap_20261015_probe{1,2}.py`) [code:data/review/refusal_overlap_20261015.md] [code:data/review/refusal_overlap_20261015_probe1.py] [code:data/review/refusal_overlap_20261015_probe2.py]
- 관련: 09번 1-1절(등급이 프롬프트에 들어간 뒤에는 되돌릴 방법이 없다 — 추론 단계 실험 A·B 실패) [docs:02_pipeline/09_ui_design.md:32]

---

#### 1. 배경 — 측정에서 확인한 것

| 항목 | 값 |
| --- | --- |
| gold 거절 | 4811건 36 → rebuild 35 (해소 4, 새 거절 3). 등급 어구 거절 15/15 그대로 [code:data/review/refusal_overlap_20261015.md:17] [code:data/review/refusal_overlap_20261015.md:31] (2026-10-15 기준) |
| no_answer 거절 | 베이스 2 → 4811건 14 → rebuild 15 [code:data/review/refusal_overlap_20261015.md:33] (2026-10-15 기준) |
| 평가 거절 문항 겹침 중앙 | 0.188 = 학습 양성의 하위 1.4% [code:data/review/refusal_overlap_20261015.md:67] [code:data/review/refusal_overlap_20261015.md:99] (2026-10-15 기준) |
| 겹침 0.3 이상 / 미만 | 거절 2/28 / 33/69 [code:data/review/refusal_overlap_20261015.md:80] (2026-10-15 기준) |
| 학습 no_answer 비율 (전체 10%) | 겹침 0.1~0.2 구간 44%, 0.2~0.3 구간 27% [code:data/review/refusal_overlap_20261015.md:107-108] [code:data/review/refusal_overlap_20261015.md:114] (2026-10-15 기준) |
| 겹침 0.2 미만 학습 양성 | 108/6,116 (1.8%) — 평가 gold는 43/97 [code:data/review/refusal_overlap_20261015.md:125] [code:data/review/refusal_overlap_20261015.md:78] (2026-10-15 기준) |
| 30자 미만 학습 질문 | 2.4% — 평가 gold 중앙 26자 [code:data/review/refusal_overlap_20261015.md:120] [code:data/review/refusal_overlap_20261015.md:87] (2026-10-15 기준) |
| 같은 질문이 양성·no_answer 양쪽에 | 고유 질문 6,743개 중 11개 [code:data/review/refusal_overlap_20261015.md:25] (2026-10-15 기준) |
| 등급 어구 + 공통 조항 양성 | 138건 — 평가에서 등급 어구 문항 17/23 거절 [code:data/review/refusal_overlap_20261015.md:126] [code:data/review/refusal_overlap_20261015.md:86] (2026-10-15 기준) |

- 길이("짧게 답하기")는 원인이 아니다. 거절은 52자 고정 문장이고, 답(80자)은 학습 답(중앙 105자)만큼 짧다. [code:data/review/refusal_overlap_20261015.md:52-57] (2026-10-15 기준)
- 질문 재작성은 원인이 아니다. 낮은 구간의 no_answer 비율을 77%→44%, 50%→27%로 오히려 낮췄다. **되돌리지 않는다.** [code:data/review/refusal_overlap_20261015.md:142] (2026-10-15 기준)
- 구조적 원인: 질문은 gold 조문을 보고 만든다. no_answer는 gold를 뺀 발췌를 쓰므로, 겹침 차이는 no_answer를 만드는 방식에서 생긴다. [code:data/review/refusal_overlap_20261015.md:24]
- 기존 검사 `--gate-max-overlap-gap`(평균 차이 ≤ 0.30)은 0.174로 통과했다. 평균은 꼬리를 숨긴다. [code:data/rebuild.py:118] [code:data/review/refusal_overlap_20261015.md:129] (2026-10-15 기준)

---

#### 2. 변경 사항 (우선순위 순)

#### 2-1. [1순위] 같은 질문으로 양성·no_answer 쌍을 만든다 — build 단계

**무엇을**: no_answer로 뽑힌 QA마다 같은 질문의 양성 샘플을 하나 더 만든다. 양성 쪽 발췌는 **그 no_answer의 방해 발췌 + gold 발췌**다. 두 샘플의 차이는 gold 발췌가 있느냐 하나뿐이다. 그러면 모델은 질문이 아니라 발췌를 읽어야 라벨을 맞힐 수 있다. [code:data/finetune_data.py:369-378] [code:data/finetune_data.py:597] [code:data/finetune_data.py:764]

**어디**: `data/finetune_data.py` — `assign_kinds`(종류 배정) 뒤, `build_sample`(샘플 조립). [code:data/finetune_data.py:331] [code:data/finetune_data.py:369]

**정할 것 / 제안**:
- 쌍의 양성은 **추가**한다(기존 distract를 대체하지 않는다). train이 약 +690건(+10%) 늘고, no_answer 비율은 10% → 약 9.2%(690/7,496)가 된다. `--gate-min-no-answer-ratio` 기본값 0.08 안이다. [code:data/rebuild.py:116] [code:data/review/refusal_overlap_20261015.md:57] (2026-10-15 기준)
- meta에 `pair_id`를 두 샘플 모두에 넣는다. 양성 쪽 kind는 `distract_pair`로 따로 둔다. 그래야 `overlap_report`·07 노트북의 종류별 출력에서 따로 보인다. [code:data/finetune_data.py:417-418] [code:data/finetune_data.py:307] [code:data/finetune_data.py:317]
- gold 위치는 기존 distract와 같은 방식(해시)으로 섞는다. 쌍은 같은 unit이라 val/train 분할(`is_val(unit_id)`)이 자동으로 같다. [code:data/finetune_data.py:133]
- 쌍 양성의 발췌 토큰이 `MAX_LENGTH`를 넘으면 기존 `fit_to_budget` 규칙을 따른다. 버려지면 그 쌍의 no_answer도 버리지 말고 건수만 기록한다. [code:data/finetune_data.py:112] [code:data/prompts.py:136] [code:data/finetune_data.py:597-600]
- no_answer 방해 발췌 판정(`--na-judge=v2`)은 그대로다. 쌍의 양성은 그 판정을 통과한 같은 방해 발췌를 쓴다. [code:data/finetune_data.py:75]

#### 2-2. [2순위] 짧은 구어체 양성 질문을 추가한다 — rewrite 단계

**무엇을**: 재작성에 변형을 하나 더 둔다. 20~35자 고객 말투에, 발췌 원문 어휘를 피하는 질문이다(평가 질문과 같은 성질). 기존 재작성 질문을 바꾸지 않고 **같은 답의 추가 질문**으로 넣는다. [c:14ba033]

**어디**: `data/faq_rewrite.py` — 프롬프트 변형, 재심판, `export_final`(추가 질문을 별도 행으로). `faq_style`에 길이·겹침 통계 열을 추가한다. [code:data/faq_rewrite.py:475] [code:data/faq_style.py]

**목표(제안)**: 겹침 0.3 미만 양성을 603건에서 1,500건 이상으로 늘린다. 근거는 다음과 같다. 0.3 미만 no_answer 263건 기준으로 이 구간 NA 비율을 15%(전체의 1.5배) 이하로 맞추려면 양성이 약 1,490건 필요하다. 30자 미만 질문은 2.4%에서 10% 이상으로. [code:data/review/refusal_overlap_20261015.md:125] [code:data/review/refusal_overlap_20261015.md:120] (2026-10-15 기준)

**주의**:
- 재심판(gemma4:12b)을 그대로 통과해야 채택한다. [code:data/faq_judge.py:19] 짧아지면서 조건이 빠지면 `incomplete`로 떨어지는 것이 정상이다.
- 이 변형의 질문도 2-1의 쌍 대상이 될 수 있어야 한다(no_answer 쪽에도 짧은 질문이 들어가야 짧음이 라벨 신호가 되지 않는다).
- 평가 97문항을 few-shot 예시로 쓰지 않는다. 빌드 후 평가 질문이 학습셋에 없는지 검사한다(이번처럼 부분 문자열 검사). [code:data/review/refusal_overlap_20261015.md:5] [code:data/eval/search_regression.json]

#### 2-3. [3순위] 등급 어구 + 공통 조항 양성을 늘린다 — rewrite(또는 gen) 단계

**무엇을**: 등급과 무관한 조항(gold unit `coverage_type` None)에 "고급형인데…", "Ⅲ유형인데…" 같은 등급·유형 어구가 붙은 질문을 만든다. 이 질문들도 2-1의 쌍에 섞어 no_answer 쪽에도 들어가게 한다. [code:data/search_scope.py:58-66] [c:14ba033]

**어디**: `data/faq_rewrite.py`(질문 앞에 어구를 붙이는 변형) 또는 05 주제 지정 회차. 어구 판정은 `search_scope.mentioned_grade`·`mentioned_type`을 그대로 쓴다. [code:data/search_scope.py:58] [code:data/search_scope.py:66]

**규칙**:
- 의료비 특약(`MEDICAL_SECTIONS`)은 유형이 섹션 이름에 박혀 있으므로 **등급만** 붙인다. 유형은 그 섹션의 유형과 같아야 한다. `answer_eval.common_note`가 COMMON_NOTE / COMMON_NOTE_MEDICAL로 나누는 기준과 같다. [code:data/search_scope.py:22-27] [code:data/answer_eval.py:56-57] [code:data/answer_eval.py:87]
- 등급 지정 단위(`coverage_type` 있음)에는 붙이지 않는다. 거기서는 등급이 답을 바꾸는 정보다.

**목표(제안)**: 138건 → 양성의 5% 이상(약 300건). no_answer의 등급 어구 질문(현재 30건)도 같은 비율로. [code:data/review/refusal_overlap_20261015.md:126] (2026-10-15 기준)

**연결**: 09번 1-1절의 운영 원칙(등급은 UI에서 확정해 프롬프트에 넣지 않는다)은 그대로다. [docs:02_pipeline/09_ui_design.md:32] 이 변경은 고객이 말로 등급을 꺼낸 경우에 모델이 거절하지 않게 하는 보완이다.

#### 2-4. [필수] build 검사에 겹침 구간별 no_answer 비율을 넣는다

**무엇을**: `rebuild.py` build 검사(기존 `--gate-*` 옆)에 아래를 넣는다. 기존 규칙을 따라 미달이면 build를 실패로 기록하고 train으로 넘어가지 않는다. 기준 값이 None(미설정)이면 미달로 본다. [code:data/rebuild.py:113-124]

| 옵션(제안 이름) | 내용 | 제안 기본값 | 현재 rebuild 값 → 판정 |
| --- | --- | --- | --- |
| `--gate-max-low-overlap-na=<배수>` | 겹침 0.1 폭 구간 중 0.3 미만 구간마다: 구간 NA 비율 ≤ 배수 × 전체 NA 비율. 표본 30건 미만 구간은 판정 제외(출력은 함) | 1.5 | 0.1~0.2 44%, 0.2~0.3 27% (상한 15%) → **미달** [code:data/rebuild.py:122] [code:data/review/refusal_overlap_20261015.md:107-108] (2026-10-15 기준) |
| `--gate-min-low-overlap-pos=<비율>` | 겹침 0.2 미만 양성 / 전체 양성 하한 | 0.10 | 1.8% → **미달** [code:data/rebuild.py:123] [code:data/review/refusal_overlap_20261015.md:125] (2026-10-15 기준) |
| `--gate-min-pairs=<비율>` | 쌍이 있는 no_answer / 전체 no_answer 하한 (2-1) | 0.9 | 양쪽에 나오는 질문 11개 → **미달** [code:data/rebuild.py:124] [code:data/review/refusal_overlap_20261015.md:25] (2026-10-15 기준) |
| (보고만) | 30자 미만 질문 비율(양성·NA 각각), 등급 어구 + 공통 조항 양성 수, 구간별 표 전체 | — | 2.4% / 138건 [code:data/review/refusal_overlap_20261015.md:120] [code:data/review/refusal_overlap_20261015.md:126] (2026-10-15 기준) |

- 구간별 표(구간·양성·NA·NA 비율)는 `stats.json`과 `logs/pipeline.log`에 모두 남긴다. [code:data/finetune_data.py:290] [code:data/finetune_data.py:608] [code:data/rebuild.py:547-551]
- **검사부터 구현하고, 현재 `data/finetune/rebuild/` 산출물에 돌려 미달이 나오는지 확인한다.** 이번 데이터를 통과시키는 검사라면 의미가 없다.
- 기존 `--gate-max-overlap-gap`은 남긴다. 그 docstring에 적힌 대로, 답이 든 발췌를 걷어내면 차이가 벌어진다. 그래서 이 검사를 맞추는 방법은 **양성을 늘리는 것(2-1·2-2)이 먼저**다. 낮은 겹침 no_answer를 버리는 것은 no_answer 분별(14~15/20)을 깎을 수 있어 마지막 수단이다. [code:data/rebuild.py:47] [code:data/review/refusal_overlap_20261015.md:33] (2026-10-15 기준)
- 조기 경고(선택): rewrite 단계 리포트에 "질문-gold 발췌 겹침 0.2 미만 양성 비율"을 찍는다. 방해 발췌 없이 계산되므로, build 전에 2-2가 모자란지 알 수 있다.

---

#### 3. 진행 순서 — 21시간을 다시 쓰지 않도록

지난 재구축 소요 시간(`data/faq/rebuild/logs/pipeline.log`): gen 6.96 + check 5.89 + rewrite 2.96 + build 0.99 + train 4.36 = **약 21.2시간**. [c:14ba033] (2026-10-15 기준) <!-- 확인 못 함: pipeline.log는 git 밖 -->

2-1과 2-4는 **build 단계만** 바꾼다. 기존 `data/faq/rebuild/rewrite/final`을 그대로 입력으로 쓸 수 있어서 gen·check·rewrite(약 15.8시간)를 다시 돌릴 필요가 없다. [code:data/rebuild.py:79] [c:14ba033] <!-- 확인 못 함: data/faq/ 산출물과 pipeline.log는 git 밖 -->

| 단계 | 할 일 | 비용 |
| --- | --- | --- |
| 0 | **no_answer 라벨 확인(먼저)** — rebuild no_answer 200건 사람 표본 검수로 "방해 발췌에 답이 (일부라도) 있는" 비율을 잰다. 높으면 판정(`data/na_judge.py`) 방식을 고친 뒤 넘어간다. 틀린 라벨을 2-1 쌍으로 복제하면 지금보다 나빠진다 | 사람 검수 [code:data/na_judge.py] [code:data/review/na_qjudge_rebuild_200_20261015_2041.md:3-5] [c:253734d] |
| A | 2-4 검사 구현 → 현재 rebuild 산출물에 돌려 **미달 확인** | 모델 없음 |
| B | 2-1 쌍 구성 구현 → 기존 final로 build만 다시(`--name`을 새로) → 검사 수치 확인 | build 약 1시간 [c:14ba033] |
| C | (선택) B 데이터로 train + answer_eval — 쌍 구성만의 효과를 따로 본다 | 약 4.4시간 + 평가 [c:14ba033] |
| D | 2-2·2-3 구현 → `run --from=rewrite` (gen·check 재사용) | rewrite 약 3시간 + build + train [code:data/rebuild.py:28] [c:14ba033] |
| E | answer_eval → 4번 기준으로 판정 → GGUF 변환 여부 결정 | |

C를 하면 쌍 구성(build)과 질문 추가(rewrite)의 효과가 섞이지 않는다. 비용은 학습 한 번이다.

---

#### 4. 판정 — 학습 후

- 같은 조건으로 잰다: `python -m data.answer_eval --adapter <새 어댑터>`(양자화 전 4-bit nf4 + LoRA, greedy, 300토큰). 베이스 답 117/117 동일이 입력 동일의 확인이다. [code:data/answer_eval.py:53] [code:data/answer_eval.py:156] [code:data/answer_eval.py:527] [code:data/review/refusal_overlap_20261015.md:4]
- no_answer 20건은 `data/finetune/val.jsonl`(2026-10-13)에서 계속 뽑는다. 새 빌드의 val로 바꾸면 비교가 끊긴다. [code:data/answer_eval.py:199] <!-- 확인 못 함: val.jsonl은 git 밖 -->
- 대조: `python -m data.answer_eval --compare <rebuild 결과 json> <새 결과 json>` — 어댑터 대조 모드(2026-10-15 추가)로 해소·새 거절이 문항 단위로 나온다. [code:data/answer_eval.py:538]
- 세 모델(베이스·4811건·rebuild)을 **새 어댑터와 같은 코드로 한 번에** 다시 잰다. answer_eval 청크 선택 수정(2026-10-15, 제목 줄 제외)으로 [code:data/answer_eval.py:75-76]
  R004·R009·R062·R063·R090의 입력이 바뀌었다 — 그 전 결과와는 이 5건을 비교할 수 없다. [code:data/answer_eval.py:75-76] [code:data/answer_eval.py:487-492]
- gold 문항 라벨: `data/eval/answer_eval_labels.json` (2026-10-15 전수 점검, `data/review/eval_set_audit_20261015.md`). [code:data/eval/answer_eval_labels.json] [code:data/review/eval_set_audit_20261015.md] [code:data/answer_eval.py:51]
  answerable 85 / partial 10 / flawed 2. 결과 md와 `--compare`가 라벨별로 집계한다. [code:data/answer_eval.py:344-350] [code:data/review/answer_eval_rebuild2_20261016.md:16-21] (2026-10-15 기준)
- 기준(2026-10-15 확정): [c:253734d]
  - **A1. answerable 거절 21 → 12 이하.** 21은 rebuild의 엄밀한 거절 오류(발췌가 깨졌던 5건 제외)다. [code:data/review/answer_eval_rebuild2_20261016.md:25-26] [c:253734d]
    재측정에서 rebuild의 answerable 거절이 21과 다르게 나오면(수정된 5건이 더해지므로) 기준선을 그 값으로 다시 보고, 12는 사용자가 다시 정한다. [c:253734d]
  - partial(거절도 변호 가능) — 목표에 넣지 않는다. 몇 건이 풀렸는지만 보고한다.
  - 등급 어구 문항 거절 17/23 → 절반 이하 [code:data/review/refusal_overlap_20261015.md:86] (2026-10-15 기준)
  - no_answer 거절 14/20 이상 유지 [code:data/review/refusal_overlap_20261015.md:33]
  - 새 거절 중 근거 있는 정답이 거절로 바뀐 회귀(R099 유형)는 건별로 사람이 확인 [code:data/review/refusal_overlap_20261015.md:40]
  - 해소된 답은 evidence 문구 포함 여부를 확인(자동 표시는 참고용)

---

#### 5. 하지 않는 것

- 심판 구조를 이번에 정리하지 않는다. 파이프라인의 심판은 네 겹이다 — 06 심판, 재작성 재심판, na_judge, na_judge 확인 검사. [code:data/faq_judge.py] [code:data/faq_rewrite.py] [code:data/na_judge.py] [code:data/finetune_data.py:683] [c:7142395]
  각각 이유가 있어 붙었지만 전체로 보면 층이 쌓였고, 그중 둘(na_judge와 확인 검사)은 같은 판정기·같은 캐시라 독립이 아니었다
  (자기가 거른 것을 자기가 검사해 "0건"이 나왔다 — docs/14 2-4절 "조용한 실패를 만들지 않는다"에 어긋난 경우). [docs:02_pipeline/14_deployment.md:533-537] [c:7142395]
  이번 재구축에서는 na_judge 기준을 질문 기준으로 바꾸고 확인 검사만 독립시킨다. [code:data/na_qjudge.py:93] [code:data/finetune_data.py:75] [c:7142395] 구조 정리는 이번 재구축 결과를 본 뒤에 한다 — 지금 바꾸면 효과 측정이 섞인다.

- 질문 재작성을 되돌리지 않는다(1절).
- 추론 프롬프트로 보정하지 않는다. 실험 A·B가 이미 실패했다(09번 1-1절). [docs:02_pipeline/09_ui_design.md:32]
- 평가 97문항을 학습·few-shot·재작성 예시에 쓰지 않는다. [code:data/eval/search_regression.json]
- 낮은 겹침 no_answer를 버려서 검사를 맞추지 않는다(2-4, 마지막 수단).

#### 6. 정하지 못한 것

- 2-2·2-3·2-4의 목표 수치(제안값 그대로 갈지)
- 0단계 결과에 따른 na_judge 수정 범위
- 2-1 쌍 양성을 추가할지, distract 일부를 대체해 총량을 유지할지(제안: 추가)
- 3절 C(쌍 구성만 따로 학습)를 할지

---

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
| 가까운 오답 | 같은 조 제외 규칙을 풀고 proximity 순(같은 조 → 인접 조 → 같은 문서 → 다른 문서) | 지금까지 no_answer 방해 발췌 1,351개 중 다른 문서 970(72%), 같은 조 0. 같은 조 옆 청크는 답을 담기 쉬우므로 답 섞임은 q2·확인 검사가 거른다 [code:data/finetune_data.py:225-232] [c:c8d9211] (2026-10-15 기준) <!-- 확인 못 함: 방해 발췌 개수는 git 밖 학습 데이터로 센 값 --> |
| 체크포인트 | 07 `save_total_limit=None` | rebuild는 3개(350·400·426)만 남아 100~250은 잴 수 없다. rebuild2부터 50 step마다 전부 남긴다(어댑터 193MB/개) [code:data/ckpt_select.py:116] [c:c8d9211] (2026-10-15 기준) <!-- 확인 못 함: 어댑터 폴더는 git 밖 --> |

학습 뒤 할 것: 세 모델(베이스·4811·rebuild)+rebuild2를 같은 코드로(청크 선택 수정 반영) 정답 발췌 입력·검색 입력(top 3) 두 가지로 잰다. [code:data/answer_eval.py:214] [c:c8d9211]
rebuild 체크포인트 350·400·426, rebuild2 체크포인트 전부를 잰다. [c:c8d9211]
검색 입력 사전 확인(모델 없이): gold 97건 중 정답 조문이 top 3 안 81건(1위 66), answerable 69/85. [code:data/review/answer_eval_rebuild2_20261016.md:35-43] [c:c8d9211] (2026-10-15 기준)

**build 결과(22:08)** — 첫 실행은 확인 검사에서 멈췄다(qwen3:14b가 no_answer 760건 중 162건 = 21.3%를 답 있음으로 봄, 상한 15%). [code:data/review/na_confirm_qwen_check12_20261015.md:3] [code:data/finetune_data.py:76] (2026-10-15 기준)
12건을 읽어 보니 과함 8 · 맞음 3 · 애매 1(`data/review/na_confirm_qwen_check12_20261015.md`) — 비율 대부분이 확인 모델의 과잉 판정이다. [code:data/review/na_confirm_qwen_check12_20261015.md:20] (2026-10-15 기준)
보수적으로 정했다: 162건과 그 쌍을 빼고(`--confirm-max-bad=1`) 다시 빌드, 이 build에 한해 `--gate-min-no-answer-ratio=0.07`·`--gate-max-na-judge-bad=0.25`. [code:data/review/na_confirm_qwen_check12_20261015.md:22] [code:data/rebuild.py:772] [c:c8d9211]

| 항목 | rebuild | rebuild2 |
|---|---|---|
| 전체 | 7,598 | 8,034 (train 7,192) [c:c8d9211] (2026-10-15 기준) <!-- 확인 못 함: build 통계(stats.json, pipeline.log)는 git 밖 --> |
| no_answer | 760 (10.0%) | 598 (7.4%) [c:c8d9211] (2026-10-15 기준) |
| q2 판정(라벨링) | — | 새 호출 2,061 · yes 893 / no 1,349 / unclear 1 (가까운 오답이라 yes가 많다) [c:c8d9211] (2026-10-15 기준) |
| 겹침 0.1~0.2 구간 NA 비율 | 41.2% | 37.2% [c:c8d9211] (2026-10-15 기준) |
| 겹침 0.2~0.3 구간 NA 비율 | 27.2% | 22.9% [c:c8d9211] (2026-10-15 기준) |
| 겹침 0.2 미만 양성 | 1.8% | 1.8% [c:c8d9211] (2026-10-15 기준) |
| 쌍이 있는 no_answer | 0% | 100% [code:data/finetune_data.py:314] [c:c8d9211] (2026-10-15 기준) |

쌍 구성만으로는 낮은 겹침 구간의 no_answer 비율이 거의 내려가지 않았다 — 쌍의 양성은 정답 발췌가 더해져 겹침이 높은 구간에 들어간다. [c:c8d9211]
이 구간은 2-2(짧은 구어체 양성)로 맞춰야 한다는 것이 확인됐다. [c:c8d9211]
확인 모델로서 qwen3:14b는 이대로 부적합 — 다음 재구축 전에 확인 검사 방식을 다시 정한다. [code:data/review/na_confirm_qwen_check12_20261015.md:23]

**train 결과(2026-10-16 02:51)** — 어댑터 `rag-1_7192건_rebuild2`, 4.71시간(예상 6.2), 450 step, 체크포인트 50~450 아홉 개(최종 = checkpoint-450). [c:55eb4bb] <!-- 확인 못 함: 학습 로그와 어댑터는 git 밖 -->
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
| 전체 샘플 | 8,034 | 5,667 | — [c:657dcab] (2026-10-16 기준) <!-- 확인 못 함: build 통계는 git 밖 --> |
| 방해 후보가 없어 버린 QA | — | **2,691 / 7,598 (35%)**(특별약관 2,555) | — [code:data/finetune_data.py:107] [c:657dcab] (2026-10-16 기준) |
| no_answer 비율 | 7.4% | 13.4% | — [c:657dcab] (2026-10-16 기준) |
| 겹침 0.1~0.2 구간 NA | 37.2% | **56.9%** | ≤ 전체 × 1.5 = 20.1% [code:data/rebuild.py:122] [c:657dcab] (2026-10-16 기준) |
| 겹침 0.2~0.3 구간 NA | 22.9% | **33.6%** | ≤ 20.1% [c:657dcab] (2026-10-16 기준) |
| 겹침 0.2 미만 양성 | 1.8% | **1.3%** | ≥ 10% [code:data/rebuild.py:123] [c:657dcab] (2026-10-16 기준) |
| 쌍 | 100% | 100% | ≥ 90% [code:data/rebuild.py:124] [c:657dcab] (2026-10-16 기준) |

→ **미달. 본 실행 전에 멈춤.** [c:657dcab]
- 버린 2,691건은 검색 top 6이 전부 정답 단위이거나 답이 글자로 든 발췌였다. 60건 표본을 다시 검색해 보니 top 12에서 40건, [code:data/rebuild.py:38] [c:657dcab] (2026-10-16 기준)
  top 20에서 47건이 방해 후보를 얻었다. [c:657dcab] (2026-10-16 기준)
- B-1은 rebuild의 질문을 썼다. 이 중 실제로 재작성된 것은 4,007/7,598뿐이다. 순서 B에서는 05 QA 전부를 재작성하므로 [c:657dcab] (2026-10-16 기준)
  질문과 정답 발췌의 겹침이 낮아진다. 실험 G(n≈40)에서 겹침 0.2 미만 비율은 rebuild final 5.3%, A(재작성 없음) 2.3%, [code:data/review/exp_g_gen_model_20261016_1253.md] [c:657dcab] (2026-10-16 기준)
  B_qwen(qwen 재작성) 11.1%였다. B-1은 이 변화를 반영하지 못해 비관적인 쪽으로 기운 예측이다. [c:657dcab]

사용자 결정(B-1 뒤): 방해 후보는 top 20으로 늘리고 그래도 없으면 gold_only로 남긴다 · B-1′(qwen 재작성 후 build) 실행 · [code:data/rebuild.py:38] [c:026a7b9]
등급 어구는 재작성의 대체 방식(전체 10%) · 미달이면 07번 10-7절 3번(짧은 구어체 양성). [code:data/rebuild.py:52] [docs:02_pipeline/07_finetuning.md:565] [c:026a7b9]

#### 8-1. B-1′ — rebuild 06 final 7,598건을 qwen3:14b로 재작성한 뒤 build(2026-10-16)

재작성(106분, 0.84초/건): 실패 7.0%(rejected 531 · unchanged 96), 등급 어구 738건(9.7%), 상황형 57.6%, 질문 길이 중앙 48자. [c:026a7b9] (2026-10-16 기준) <!-- 확인 못 함: 재작성 요약은 git 밖 산출물 -->
요약의 `label_leak` 10.3%는 "답변 누출"이 아니라 질문 속 `약관·특약·제N조·별표` 표현 비율이다. 784건 모두 원래 질문에 있던 것이고 [code:data/faq_rewrite.py:120-123] [c:026a7b9] (2026-10-16 기준)
재작성이 새로 넣은 것은 0건(재작성 전 23.3%). [c:026a7b9] (2026-10-16 기준)

| 항목 | B-1 | B-1′ | 기준 |
|---|---|---|---|
| 전체 샘플 | 5,667 | 8,358 (train 7,500 · val 858) | — [c:026a7b9] (2026-10-16 기준) <!-- 확인 못 함: build 통계는 git 밖 --> |
| gold_only(top 20에도 방해 후보 없음) | — | 331 (4.0%) | — [code:data/rebuild.py:38] [c:026a7b9] (2026-10-16 기준) |
| no_answer 비율 | 13.4% | 9.1% | — [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.0~0.1 구간 NA | — | 67.6% (25/37) | ≤ 13.6% [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.1~0.2 구간 NA | 56.9% | **48.0%** (147/306) | ≤ 13.6% [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.2~0.3 구간 NA | 33.6% | **21.5%** (231/1,075) | ≤ 13.6% [c:026a7b9] (2026-10-16 기준) |
| 겹침 0.2 미만 양성 | 1.3% | **2.2%** | ≥ 10% [c:026a7b9] (2026-10-16 기준) |

→ **미달.** 학습 시간 예측: 학습 데이터 글자 수가 rebuild2의 1.28배(4.71시간) → 약 6시간. [c:026a7b9] (2026-10-16 기준)

**답변 누출 검사 추가**(사용자 확정): 재작성 질문에 원래 질문에 없던 답변의 숫자, 또는 명사형 4자 이상 어구가 들어가면 거절 [code:data/faq_rewrite.py:144-149] [c:026a7b9]
(`faq_rewrite.answer_leak`). B-1′ 재작성 6,971건 중 120건(1.7%)이 걸린다. 숫자 46건 중 29건이 실제 누출("연간 총 보상한도는 [code:data/faq_rewrite.py:126-129] [c:026a7b9] (2026-10-16 기준)
750만원인가요?"), 17건은 고객 상황 숫자다. 거절해도 원래 질문이 06으로 가므로 QA는 잃지 않는다(구어체만 잃는다). [code:data/faq_rewrite.py:127] (2026-10-16 기준)
4자 조각 규칙은 1,611건(23%)이 걸려 너무 넓었다. [code:data/faq_rewrite.py:129] (2026-10-16 기준)

#### 8-2. 짧은 구어체 재작성 예측(10-7절 3번, 300건)

B-1′ final에서 등급 어구가 아닌 QA 300건(seed 42)을 20~35자·원문 표현 피하기 프롬프트로 qwen3:14b 재작성 → 06 심판(gemma4:12b) [code:data/faq_judge.py:19] [c:026a7b9]
→ B-1′ 빌드 샘플의 발췌는 그대로 두고 질문만 바꿔 겹침 재계산. 스크립트·결과는 저장소 밖(세션 scratchpad). [c:026a7b9] <!-- 확인 못 함: 예측 스크립트와 결과는 저장소 밖 -->

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
| 겹침 0.0~0.1 구간 NA | 67.6% | 63.6% (21/33) | ≤ 13.6% [c:026a7b9] (2026-10-16 기준) <!-- 확인 못 함: build 통계는 git 밖 --> |
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

---

#### 9. 다음 재구축에 넣을 것 — 2026-10-28 추가 (지금 하지 않는다)

**9-1. 도구 호출 학습 (docs/16 4절 C안).** 코드 답 규칙의 트리거(이 질문이 어느 계산을 원하는가)를 모델 안으로 옮긴다. 계산 함수는 지금 코드 그대로 도구로 노출한다 — 보험금 계산(payout), 부담보·면책 단서·대기기간 확인(customer_facts), 한도표, 연차·퇴직금·급여(hr_personal). [docs:02_pipeline/16_code_answers.md:136] [code:app/services/payout.py] [code:app/services/customer_facts.py] [code:data/limit_table.py] [code:app/services/hr_personal.py:431] [c:130b1d6]
- 학습 데이터: 지금 코드 답 규칙이 답한 턴을 "질문 → 도구 호출(인자) → 결과 → 답"으로 바꿔 넣는다(규칙이 정답 호출을 만든다). 규칙이 안 걸리는 말투는 gemma 생성(disease_ask_gemma 방식)으로 보탠다 [code:data/eval/disease_ask_gemma.json] [c:130b1d6]
- 판정: 도구 선택 정확도·인자 정확도를 규칙과 같은 탐침(병명 되묻기·사내규정 개인화·면책 단서)과 평가 220으로 대조. 규칙보다 나쁘면 규칙을 남긴다(지금 등록부 `code_rules.py`가 그대로 대비책) [code:app/services/code_rules.py:69] [code:data/eval/disease_ask_probe.json] [code:data/eval/hr_personal.json] [code:data/eval/eval220.json]
- 비용: 학습 데이터 생성 + 재학습 + 전면 재평가. 7B의 함수 호출 정확도가 관건이라 소규모 예비 학습으로 먼저 본다

**9-2. PDF 줄바꿈을 전처리에서 고친다 (data/review/article_display_survey.md 3절).** 지금은 근거 패널 표시만 고쳤다. 운영 모델이 줄바꿈이 든 발췌로 학습했으므로, 전처리를 고치려면 학습 데이터도 같은 판으로 다시 만들어야 한다 — 다음 재구축에서 함께 한다. 약관 컬렉션 8개 재색인·검색 회귀 포함. [code:data/review/article_display_survey.md:59] [code:app/services/article_display.py] [c:d84958c]

---

#### 10. 다음 재학습에서도 지키는 것 — 2026-11-09 정리

재학습·재구축이 다시 열릴 때마다 나온 사용자 결정 중 문서에 없던 것(세션 압축으로 빠진 것을 원문에서 되살림). [c:1cf1479]

- **모델 셋은 고정한다.** 생성 모델(Tri-7B + LoRA)·임베딩(KURE-v1)·리랭커(bge-reranker-v2-m3)는 교체하지 않는다(2026-10-21: "생성 모델 교체, 임베딩 교체, 리랭커 교체는 하지 않는다"). 8-1절의 qwen3:14b 재작성은 rebuild3 때의 실험 기록이고 기본값이 아니다 [code:data/search_engine.py:23-24] [code:app/config.py:70-71] [c:1cf1479] <!-- 확인 못 함: 사용자 결정 원문은 세션 기록이라 저장소 밖 -->
- **구현 → 소규모 시험 → 본 실행 순서로 한다.** 시험(`--smoke`)에서 무엇을 확인할지 먼저 알리고, 시험이 실패하면 본 실행(전량 생성·학습) 전에 멈추고 보고한다(2026-10-16: "구현 → 소규모 시험 → 본 실행 순서로 진행해라. 소규모 시험에서 무엇을 확인할지 먼저 알려 달라") [code:data/rebuild.py:54] [code:data/rebuild.py:782] [c:1cf1479]
- **체크포인트는 select가 고른 것을 쓴다.** 변동 폭 안의 차이를 보고 눈으로 뒤집지 않는다 — 고르는 방식은 docs/07 11-2절(평가 220 보이는 세트 점수)(2026-10-16: "눈으로 뒤집으면 select 단계를 만든 의미가 없다") [code:scripts/ckpt_select220.py:3-9] [docs:02_pipeline/07_finetuning.md:589] [c:1cf1479]
- 판정 선은 rebuild4 체크포인트 표다(같은 114턴 정확 51 · 틀림 10 · 거절 31, docs/07 11-4절) — 거절만 줄이는 것으로는 채택하지 않는다 [docs:02_pipeline/07_finetuning.md:635-639] [c:1cf1479]

