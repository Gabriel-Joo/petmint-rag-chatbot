14번 배포 편(docs/02_pipeline/14_deployment.md)에서 떼어 낸 구현 기록(2026-11-19 문서 정리 B단계). 지금 설계는 docs/02_pipeline/14_deployment.md

아래 절 번호와 절 안의 「n절」 참조는 떼어 내기 전 14번의 번호다.

#### 1-8. 이주 때 할 일

- ✓ MySQL을 StatefulSet + PVC로 올리고, 계정 정보를 Secret으로 주입 [code:db/conn.py:1-8] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/mysql/statefulset.yaml:5, :36-41, :63-71 -->
- ✓ 스키마는 초기화 Job으로 — 앱 이미지로 `python -m db.migrate`를 그대로 돌린다 [code:Dockerfile:10] [code:db/migrate.py]
- ✓ 환경변수만 바꾸고 연결 확인 [code:db/conn.py:20-24]
- ✓ `insurance_core`의 마이그레이션과 시드도 초기화 Job에 넣는다 [code:db/migrate.py:7] [code:db/seed_insurance_core.py:7-13] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/jobs/init-db.yaml:41-42 -->

실제 이주(2026-10-16)에서는 약관 청크와 그래프를 **NFS 읽기 전용 PV**로 붙였다. 호스트의 `/srv/nfs/petmint/`를 모든 Pod가 같은 파일로 읽으므로 replicas를 늘려도 드리프트가 없다. DB는 `mysqldump`를 쓰지 않고 픽스처 시드 Job으로 새로 시작했다. [c:afefd07] [code:deploy/scripts/host-nfs-setup.sh:7] [code:db/seed_insurance_core.py:7-13]

#### 1-9. 파이프라인 — CI (2026-10-15)

✓ 1-5절의 흐름 중 **빌드→push→pull 까지가 이 단계에서 돌아갔다. 배포 자동화는 1-10절이다.** [code:Jenkinsfile:95-121]

✓ **앱이 클러스터에서 돈다 (2026-10-16).** MySQL StatefulSet → 약관·시드 적재 → 초기화 Job → 앱 순으로 올렸고, Ingress 경유로 화면·고객 조회·조항 원문·WS 한 턴까지 응답한다. ✗ 약관 적재는 API 서버를 거쳐 Pod 안으로 tar를 흘려 넣어, m-k8s 디스크에 파일이 남지 않는다(아래 — 같은 날 NFS로 바꿨다). [c:afefd07] <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->

약관 데이터를 tar로 넣던 절차는 같은 날 NFS 읽기 전용 PV로 바꿨다(1-8절). ✓ 일반 모드는 클러스터에서 실제 답변을 확인했다(2026-10-18). ✓ search-service가 붙어 업무특화·사내규정도 답이 나온다(호스트 `petmint-search`). [c:afefd07] [code:deploy/host/petmint-search.service] <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->

#### 1-10. GitOps — ArgoCD (2026-10-16)

✓ 1-5절의 흐름이 **끝까지 돌아간다.** push 하나로 빌드·Harbor·매니페스트 커밋까지 가고, 반영은 Sync를 눌러 한다. [code:Jenkinsfile:123-151]

전환은 중단 없이 넘어갔다. 기존 Application 셋을 지우지 않고 같은 이름 · 같은 spec 을 루트가 apply 했다. cloudflared 만 path 가 `platform/cloudflared` → `apps/cloudflared` 로 바뀌었는데, 두 경로의 `kubectl kustomize` 출력이 0줄 차이라 Sync 없이 Synced 였다. 전환 뒤 세 앱의 파드 UID · 시작 시각, deploy · sts · cm · svc · ingress resourceVersion 이 전과 같고 자식 Sync 작업은 일어나지 않았다. 터널 커넥터 4/4, petmint · runshoes 공개 주소 200. 되돌리기와 전후 기록은 호스트 `~/k8s-cluster/backup/2026-11-02-app-of-apps/`. 폴더만으로 되는지는 시험 앱 `apps/zz-smoke/`(리소스 0개, 수동 Sync)를 push 해 확인했다 — 손대지 않아도 루트가 조회 주기(3분) 안에 Application `zz-smoke` 를 만들었다. 지울 때는 폴더를 지우는 커밋을 push 한 뒤 `kubectl -n argocd delete application zz-smoke` 를 따로 한다(prune 끔). (2026-11-02 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): zz-smoke 추가 1bce3fe, 지움 d6ad706, 호스트 ~/k8s-cluster/backup/2026-11-02-app-of-apps/ROLLBACK.md 와 pods-before, pods-after 가 같음 --> <!-- 확인 못 함: kustomize 출력 0줄 차이, 터널 커넥터 4/4, 공개 주소 200 은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->

#### 1-11. 검색·답 표시 플래그 운영 반영 (2026-10-23)

✓ **운영이 이미지 `f7991c90f22e` + 아래 플래그로 돈다.**(2026-10-23 판. 2026-11-19 지금 운영 이미지는 `39d2d6bb5ab8`) 그 전 운영 이미지(b6a7399)는 평가 220 기준선(자동 통과 117) 시점의 코드였다. 같은 평가에서 지금 코드는 플래그를 모두 끄고도 159, 모두 켜면 163이다(rebuild4, 3회 평균 — `data/review/rollout_measure.md`). 117 → 159는 코드(고객 사실·되묻기 정리·코드 답 카드)에서 오고, 플래그가 그 위에 판정 정확 +9.4·판정 거절 −8.3을 더한다. 틀림은 늘지 않았다. [code:data/review/rollout_measure.md] [c:f7991c9] [c:b6a7399] (2026-10-23 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/kustomization.yaml:31-32 (지금 39d2d6bb5ab8). 2026-10-23 플래그를 켠 7d05ff4 때 f7991c90f22e 였음 -->

| ConfigMap 키 | 값 | 하는 일 | 측정(그 플래그만 끈 것과 비교) |
| --- | --- | --- | --- |
| `PETMINT_CHUNKS_DIR`·`PETMINT_GRAPH_DIR` | `/var/lib/petmint/chunks/v3`·`graph/v3` | 청크 v3(약관 호·법령박스 분할). NFS 공유 안의 v3 폴더 | 아래 둘과 함께 [code:app/config.py:19-21] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml:35-36 (7d05ff4, 2026-10-23) --> |
| `PETMINT_SEARCH_VARIANT` | `v3` | search-service가 Milvus `petmint_*_v3`로 찾는다(약관만) | 정확 +3.0, 예외누락 −1.3, 거절 −1.0 [code:app/config.py:38] [code:app/services/retrieval.py:23-24] [code:data/review/rollout_measure.md] (2026-10-23 기준) |
| `PETMINT_DISPLAY_PARENT` | `1` | v3 조각으로 찾고 모델에게는 부모(원래 청크) 글을 보여 준다 | (v3와 함께) [code:app/config.py:40-41] |
| `PETMINT_SEARCH_EXPAND` | `1` | 질의 확장(고객 말 → 약관 말, BM25·리랭커 질의에만) | 정답이 프롬프트에 든 턴 62 → 73, 판정 거절 37.3 → 30.7, 정확 +5.0 [code:app/config.py:34] [code:data/review/rollout_measure.md] (2026-10-23 기준) |
| `PETMINT_EXPAND_DICT` | `v2` | 동의어 사전 v2(62항목) | 검색 회귀 hit@3 92 → 95, MRR 0.866 → 0.880. 답은 흔들림 안 [code:app/config.py:35] [code:data/query_expansion.py:17] [code:data/synonyms.py:41] [code:data/review/rollout_measure.md] (2026-10-23 기준) |
| `PETMINT_ANSWER_TABLES` | `1` | 답이 쓴 발췌의 표를 답 아래에 붙인다 | 답에는 영향 없음(답 뒤에 붙는다). 표 붙은 턴 회당 8.7 [code:app/config.py:36] [code:data/review/rollout_measure.md] (2026-10-23 기준) |

호스트는 할 일이 없었다. search-service(질의 확장·variant·사전 판 인자), Milvus v3 컬렉션, NFS의 v3 폴더가 이미 있었다. [code:search_service/main.py:55-63] <!-- 2026-11-19 잼: pymilvus list_collections 에 petmint_dog_v3, petmint_cat_v3 있음, ls 로 /srv/nfs/petmint/chunks/v3 와 /srv/nfs/petmint/graph/v3 있음 -->

**되돌리기.** ConfigMap의 다섯 키를 지우고 청크·그래프 경로를 `/var/lib/petmint/chunks`·`graph`로 돌린 뒤 Sync하고 `rollout restart`하면 "코드만" 상태(159)가 된다. 이미지 태그까지 b6a7399로 돌리면 반영 전 운영이다. [code:data/review/rollout_measure.md] [c:b6a7399]

✗ **반영 점검에서 찾은 결함 두 개.**

- variant를 켜면 **사내규정 검색이 503**이었다. Milvus에 `hr_regulation_v3` 컬렉션이 없다(v3는 약관만 다시 잘랐다). 평가 220에는 사내규정 턴이 없어 측정에 드러나지 않았다. Retriever가 variant를 강아지·고양이 검색에만 붙이게 고쳤다(f7991c9, `tests/test_retrieval_variant.py`) [c:f7991c9] [code:app/services/retrieval.py:23-24] [code:app/services/retrieval.py:53] [code:tests/test_retrieval_variant.py]
- **사내규정 답의 근거 조항을 열면 422**였다(반영 직후 운영 로그). 조항 원문 API가 처음부터 강아지·고양이만 받았다 — 이번 반영과 무관한 예전 버그다. 사내규정 코퍼스도 받게 고쳤다(f0279c2, `tests/test_articles_route.py`). 이 수정은 다음 push부터 운영에 들어간다 [c:f0279c2] [code:app/schemas.py:24] [code:app/routers/articles.py:25-26] [code:tests/test_articles_route.py]

✓ **반영 확인.** Pod 2개 Running, 로그에 오류 0. Pod 안에서 시험 스크립트로 모드마다 질문을 보냈다(시험 세션이 운영 DB에 남는다 — 사용자 허락). (2026-10-23 기준) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->

| 모드 | 질문 | 결과 |
| --- | --- | --- |
| 업무특화 | 보험금이 지급기일보다 40일 늦게 나오면 이자 얼마나 붙어요? | 답 + 【별표1】 적립이율 표가 붙음 <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) --> |
| 업무특화 | 보험수익자가 정확히 누구예요? | 답 + 용어 정의 표, 해당 행 강조 <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) --> |
| 사내규정 | 연차 개수는 얼마나 있어요?(사용자) · 지각을 몇 번 하면 징계를 받나요? | 답 + 근거 조항(제17·18·33조, 제13조) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) --> |
| 일반 | 반려견 산책은 하루에 몇 번이 좋아요? | 답 <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) --> |

#### 1-12. 보장 여부 질문 플래그 (2026-10-23, d64aea0)

1-11 위에 두 키를 더 켠다. 측정은 평가 220 보이는 세트 3회 평균이다(`data/review/coverage_measure.md`). 판정 정확과 틀림은 판정 대상 턴에 대한 비율로 쓴다. 코드 답이 늘면 판정 대상 턴이 줄기 때문이다. [code:data/review/coverage_measure.md]

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_RULE_FIRST` | `1` | 보험금 지급사유·보상하는 손해 조에서, 같은 조의 원칙(제1항)이 참조에만 있으면 본문 앞으로 옮긴다(1안) | 자동 통과 157.0 → 159.7. 정확 47.7% → 52.6%. 틀림 12.4% → 11.6%. 원칙이 참조에만 있던 턴은 회당 15 → 1 [code:app/config.py:42-43] [code:data/review/coverage_measure.md] [c:d64aea0] (2026-10-23 기준) |
| `PETMINT_COVERAGE_CODE` | `1` | 그 반려동물의 부담보에 걸리는 보장 질문은 코드가 특약 제2조 ①②④로 답한다. 대기기간에도 걸리면 그 줄을 붙인다. 분류 질문은 모델에게 남긴다(3안′) | 둘 다 켜면 자동 통과 163.0. 정확 53.5%, 틀림 12.1%. 부담보 대상 8문항은 거절 3.3 → 0, 예외누락 1.3 → 0. N축은 16/16 그대로 [code:app/config.py:44-45] [code:app/services/code_rules.py:86] [code:app/services/customer_facts.py:142] [code:data/review/coverage_measure.md] [c:d64aea0] (2026-10-23 기준) |

대기기간 결론까지 코드로 내던 첫 3안은 버렸다. 가입 30일 안인 반려동물의 질병 질문을 모두 "30일 이내" 답으로 가져가, 면책 질문(유전병·예방접종·치과)에서 오답이 났다. 그 코드(`customer_facts.waiting_answer`)는 남아 있지만 쓰지 않는다. [code:app/services/customer_facts.py:272] [code:tests/test_coverage_code.py:42-49] [code:data/review/coverage_measure.md]

표 청크의 깨진 글자를 정리한 청크 v4도 쟀지만 채택하지 않았다. 가입 나이 4문항(C51·C52·P09·S42)이 그대로였다. Milvus `petmint_*_v4`와 `data/chunks/v4`는 측정용으로만 남아 있다. [code:data/review/coverage_measure.md] [c:d64aea0] (2026-10-23 기준) [c:dcdecd9] <!-- 요약: data/review/chunks_graph_summary.md 30~32줄(v4 청크 파일)과 105줄(v4 그래프) --> <!-- 2026-11-19 잼: pymilvus list_collections 에 v4 컬렉션 있음 -->

**반영 순서.** 1-11과 같다. 앱(d64aea0까지)을 먼저 push하고 infra를 나중에 push한다. 옛 이미지는 두 키를 모르므로 순서가 바뀌어도 해는 없다. **되돌리기:** 두 키를 지우고 Sync한 뒤 `rollout restart`한다. [c:d64aea0] [code:app/config.py:42-45]

#### 1-13. 후보 깊이 50·신규 가입 나이 코드 답 (2026-10-24, f331617)

1-12 위에 두 키를 더 켠다. 비교는 07번 11-6의 흔들림 기준(3회 평균 차이 4 안쪽은 효과로 보지 않음)으로 판단했다. [docs:02_pipeline/07_finetuning.md]

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_SEARCH_POOL` | `50` | search-service 1차 후보 깊이(Dense·BM25 각각) 20 → 50 | 검색 회귀 78·95·95 / MRR 0.880 → 80·97·97 / 0.897. 발췌가 바뀐 평가 문항은 S05 살처분·P47 소음 배상이 거절 3 → 정확 3, S11 상병명 모름이 정확 3 → 거절 3. 판정 지표 변화는 흔들림 폭 안. 모델 턴 지연 중앙값 872 → 1,028ms (`data/review/pool_measure.md`) [code:app/config.py:37] [code:data/search_engine.py:154] [code:data/search_engine.py:165-167] [code:data/review/pool_measure.md:57-60] [c:f331617] (2026-10-24 기준) |
| `PETMINT_AGE_CODE` | `1` | 신규 가입 나이를 숫자로 묻는 질문은 코드가 약관 기준(일반조항 제2조 '반려동물' 1호: 만 8세, 실속형 만 10세 초과는 가입 대상 아님)과 비교해 답한다 | 코드가 답하는 조건은 셋이다: 나이 숫자가 있다, 신규 가입을 묻는다, 재가입·갱신이 아니다. 평가·회귀 307문장 중 P09·C51·C52에만 걸린다. 세 문항의 거절 3/3이 코드 답 3/3으로 바뀌었다. N축은 16/16 그대로다. 대상 밖 모델 턴 318개는 프롬프트가 같다 (`data/review/age_measure.md`) [code:app/config.py:46-47] [code:data/review/age_measure.md:59-60] [c:f331617] (2026-10-24 기준) |

**반영 순서.**
1. 앱(f331617까지)을 push한다 [c:f331617]
2. 새 이미지 태그 커밋을 받는다
3. ConfigMap을 push하고 Sync한다

**되돌리기.** 두 키를 지우고 Sync한 뒤 `rollout restart`한다.

#### 1-14. 면책 단서 코드 답 (2026-10-24, cbc78bf)

1-13 위에 키 하나를 더 켠다.

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_PROVISO_CODE` | `1` | 의료비 특약 제2조 면책 항목의 단서가 질문의 경우를 보장 쪽으로 빼 주면 코드가 답한다(⑫ 침술, ② 1년 이내 예방접종, ⑲ Ⅰ 유형의 치아 외 구강질환) | 평가 220에서 코드 답으로 바뀐 턴은 S10·S20·S27·M14-2뿐이다. 대상 밖 모델 턴 306개는 프롬프트가 같다. N축 16/16 그대로. 자동 통과 164.0 → 166.7. 탐침 대상 9턴은 직접 정답 0/27 → 27/27 (`data/review/proviso_measure.md`) [code:app/config.py:48-49] [code:data/review/proviso_measure.md:75] [code:data/review/proviso_measure.md:82] [c:cbc78bf] (2026-10-24 기준) |

코드가 답하는 조건은 두 가지다.
- 병명이나 치료를 가리키는 말이 지금 질문에 있어야 한다. "한약은요?"·"이빨 뽑는 건요?" 같은 후속은 모델이 답한다
- 예방접종은 질문에 접종 사실(시기 또는 미접종)이 있을 때만 답한다

**반영 순서.** 1-13과 같다. 앱(cbc78bf까지) push → 이미지 태그 커밋을 받는다 → ConfigMap push → Sync. 옛 이미지는 이 키를 모르므로 먼저 들어가도 해가 없다. **되돌리기:** 키를 지우고 Sync한 뒤 `rollout restart`. [c:cbc78bf]

#### 1-15. 같은 제목 의료비 특약 조 올리기 (2026-10-28, 5f1d48a)

1-14 위에 키 하나를 더 켠다.

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_TWIN_ARTICLE` | `1` | 업무특화 검색에서 질문에 특약 낱말(통원·입원·치료·진료·수술·의료비·병원·질병·특약)이 없고 상위 3에 보통약관 제3조·제5조가 있으면, 후보 20 안의 같은 제목 의료비 특약 조(제1조 보험금의 지급사유·제2조 보험금을 지급하지 않는 사유)를 그 앞으로 올린다. 보통약관은 사람 상해보험 약관이라 이 두 조는 반려동물 보장의 근거가 아니다 | 평가 220에서 발동 0(프롬프트 변화 0), N축 16/16, 검색 회귀 80·97·97 / MRR 0.897 그대로. 평가 밖 탐침 135턴에서 사람 보험 면책("자신을 해친 경우·임신·출산")을 답한 턴 16 → 0, 거절 32 → 30 (`data/review/human_article_measure.md`) [code:app/config.py:50-52] [code:data/rag_context.py:560-566] [code:data/rag_context.py:581-596] [code:app/services/answer.py:53] [code:app/services/answer.py:222-225] [code:data/review/human_article_measure.md:54-55] [c:5f1d48a] (2026-10-28 기준) |

같이 만든 `PETMINT_HUMAN_DEMOTE`(보통약관 제3·4·5조 점수 × 0.5)는 켜지 않는다. 탐침에서 "보장 안 되는 질병은 뭔가요?"를 거절 0/9 → 8/9로 바꿨다. 세 번째 발췌가 제5조 → 제19조로 바뀐 것만으로 모델이 거절했다. [code:app/config.py:51] [code:data/rag_context.py:563-564] [code:data/rag_context.py:582-586] [code:data/review/human_article_measure.md] [c:5f1d48a] (2026-10-28 기준)

효과는 "보험금 안 나오는 경우는?"·"지급 안 되는 사유가 뭐예요?" 같은 질문뿐이다. 의료비 질문이 보통약관 제19조·일반조항으로 가는 평가 9문항(회당 거절 7턴)은 이 키로 풀리지 않는다(`data/review/offtarget_search.md`). [code:data/review/offtarget_search.md] (2026-10-28 기준)

**반영 순서.** 1-14와 같다. 앱(5f1d48a까지) push → 이미지 태그 커밋을 받는다 → ConfigMap push → Sync. **되돌리기:** 키를 지우고 Sync한 뒤 `rollout restart`. [c:5f1d48a]

#### 1-16. 직원 원장과 앱 로그인 (2026-10-28)

- 초기화 Job이 하는 일이 늘어난다(매니페스트는 그대로): `db.migrate`가 petmint `0006_accounts`, `db.migrate --app insurance_core`가 `0003_employees`를 적용하고, `db.seed_insurance_core --if-empty`가 직원 테이블이 비어 있으면 가상 직원 11명(`db/fixtures/employees.json`, 이미지 안)을 깐다 [code:db/migrations/petmint/0006_accounts.sql] [code:db/migrations/insurance_core/0003_employees.sql] [code:db/migrate.py:7] [code:db/seed_insurance_core.py:16-17] [code:db/fixtures/employees.json] [code:Dockerfile:35] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/jobs/init-db.yaml:40-42 -->
- 앱 의존성에 `argon2-cffi`가 더해진다(이미지 재빌드) [code:app/requirements.txt:12]

#### 1-17. 사내규정 개인화 (2026-10-28)

1-16 위에 키 하나를 더 켠다. 앱 로그인(`PETMINT_AUTH: "app"`)과 같이 켠다 — 신원이 직원 이메일이어야 원장을 찾는다(access 모드의 헤더 없음·dev@local은 원장에 없어 모델이 답한다). [code:app/config.py:53-54] [code:app/config.py:85] [code:app/services/answer.py:212-218]

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_HR_PERSONAL` | `1` | 사내규정 모드에서 본인 지칭 + 연차 잔여·연차수당·퇴직금·자격수당·승진·급여·통상임금이면 인사 원장으로 코드가 답한다(2026-10-28 급여·통상임금 추가, 지급일은 개정 제25조) | 개인 탐침 32문항 96/96(기준은 우연 일치 19/96), 대상 밖 프롬프트(음성 8·HR 18) 78/78 같음. 업무특화·검색은 경로 밖 (`data/review/hr_personal_measure.md`) [code:app/config.py:53-54] [code:app/services/hr_personal.py] [code:data/review/hr_personal_measure.md:24-25] [c:13c1734] [c:7cfa08b] |

**반영 순서.** 앱(이 커밋까지) push → 이미지 태그 커밋을 받는다 → ConfigMap push → Sync. **되돌리기:** 키를 지우고 Sync한 뒤 `rollout restart`.

2026-10-28 운영 피드백으로 고쳤다(키는 같다, 이미지만): 본인 지칭 없는 후속("연차 미사용분은 얼마 받나요?")이 바로 앞 개인화 질문을 이어받는다, 미사용 연차수당 금액, 코드 답의 근거 조항은 검색 결과가 아니라 코드가 쓴 조항. 후속 15/15(전 2/15), 대상 밖 프롬프트 93/93 같음. 이어서 퇴직 예정일("퇴직 날짜가 2026년 12월 30일 입니다")을 받아 그날 기준으로 퇴직금·연차수당을 계산하고, 이어받기를 개인화 사슬 + 퇴직 예정일 정보로 넓혔다 — 후속 18/36 → 36/36, 모델로 가야 하는 후속 0/33 그대로, 대상 밖 프롬프트 114/114 같음(`data/review/hr_personal_measure.md`). [code:data/review/hr_personal_measure.md:53] [code:data/review/hr_personal_measure.md:86-88] [c:f91fb19] [c:33323cd]

#### 1-18. 가상 직원 이름·팀 바꾸기 (2026-10-28)

키는 그대로, 이미지와 마이그레이션 둘이다. 초기화 Job이 Sync 때 돌린다.
- insurance_core `0004_employee_rename`: 가상 직원 11명의 이름·이메일을 예시 이름(홍길동 등)에서 고객과 성까지 겹치지 않는 이름으로, 팀을 고객상담팀 하나로. **사번은 그대로**(입사연도 + 순번 — 이름과 상관없고 로그인 ID다) [code:db/migrations/insurance_core/0004_employee_rename.sql] [code:db/fixtures/employees.json] [c:4d3a65d]
- petmint `0007_agent_email_rename`: 상담 기록의 상담원 이메일(`sessions.agent_email`)을 새 이메일로 옮긴다 — 지난 채팅·세션 소유권이 이어진다. 로그인(accounts·auth_sessions)은 사번으로 묶여 있어 다시 로그인할 필요가 없다 [code:db/migrations/petmint/0007_agent_email_rename.sql:1-5]

로컬에서 확인: 바꾸기 전후로 직원별 세션 수가 같고(148·111·99…), 같은 비밀번호로 로그인해 지난 채팅이 그대로 보인다. [c:4d3a65d] (2026-10-28 기준) <!-- 확인 못 함: 지난 일이라 다시 잴 수 없음(2026-11-19 개발 DB 읽기 전용 COUNT 로 직원별 세션 수는 582, 288, 239, 211, 144, 30) -->

#### 1-19. 병명 되묻기 (2026-10-28)

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_ASK_DISEASE` | `1` | 업무특화에서 병명 없이 보장을 묻는 질문("○○가 입원했어요. 보장되나요?")은 가입 의료비 특약 원칙 + 병명 되묻기를 코드가 답한다(다섯 조건, 대기기간 안이면 발병일도) | 탐침 되묻기 0/24 → 24/24(거절 17 → 0), 되묻지 말아야 42/42 그대로, 후속 5/12 → 8/12. 평가 220: 바뀐 턴 L02·L14뿐(통과), 대상 밖 프롬프트 100개 같음, N축 16/16 (`data/review/disease_ask_measure.md`) [code:app/config.py:55-56] [code:data/review/disease_ask_measure.md:18-20] [c:2a13182] (2026-10-28 기준) |

**반영 순서.** 앱(이 커밋까지) push → 이미지 태그 커밋을 받는다 → ConfigMap push → Sync. **되돌리기:** 키를 지우고 Sync한 뒤 `rollout restart`.

같은 키로 되물은 뒤 상해로 답한 턴도 코드가 답한다(2026-10-28, 이미지만): 상해 보상 원칙·대기기간 없음·금액 되묻기. 탐침 후속 12/24 → 21/24(상해 0/9 → 9/9), 평가 220 프롬프트 100개 같음. [code:data/review/disease_ask_measure.md:34] [c:ed150c6]

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_ASK_DISEASE_LLM` | `1` | 병명 되묻기의 "병명·증상 이름이 있는가"를 베이스 모델(tri-7b)이 본다. 면책 사실은 코드가 막고, 모델 실패 시 정규식 | gemma 말투 무병명 되묻기 7/60 → 39/60(거절 46 → 16), 병명 잘못 되묻기 0, 평가 220 프롬프트·코드 답 같음 (`data/review/disease_ask_llm_measure.md`) [code:app/config.py:57-58] [code:app/services/name_check.py] [code:data/review/disease_ask_llm_measure.md:29] [c:130b1d6] (2026-10-28 기준) |

#### 1-20. 코드 답 규칙 운영 집계 (2026-10-29)

키는 없다 — 이미지와 마이그레이션 하나다. 초기화 Job이 Sync 때 petmint `0008_turn_code_rule`(`turns.code_rule` 칸 하나, 기존 행 그대로)을 적용하고, 그다음 턴부터 답한 규칙 이름이 남는다(모델 답은 NULL). [code:db/migrations/petmint/0008_turn_code_rule.sql] [code:db/rule_report.py:32]

#### 1-21. 병명 보장 대조 (2026-10-29)

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_NAMED_COVER` | `1` | 업무특화에서 병명이 있는 보장 질문("감기도 보장되나요?")은 그 반려동물 의료비 특약 제2조 면책 목록과 대조해 코드가 답한다 — 목록에 없으면 원칙 보상 + 단서, 있으면 그 조항. 금액 되묻기 뒤 "감기도 돼요?"는 금액 되묻기를 되풀이하지 않는다 | 내 탐침 47/81 → 81/81, gemma 80문항 거절 63 → 24, 평가 220 프롬프트가 바뀐 턴은 대상 8개뿐(대상 5/8 → 8/8), N축 16/16, 병명 되묻기 탐침 그대로 (`data/review/named_cover_measure.md`) [code:app/config.py:59-61] [code:app/services/named_cover.py] [code:data/review/named_cover_measure.md:29-31] [c:d3a8706] (2026-10-29 기준) |

**반영 순서.** 앱(이 커밋까지) push → 이미지 태그 커밋 → ConfigMap push → Sync. **되돌리기:** 키를 지우고 Sync한 뒤 `rollout restart`.

#### 1-22. GitHub 웹훅 — ArgoCD · Jenkins (2026-11-03)

- Jenkins 는 github 플러그인 1.47.0 을 더했다(helm revision 6, 재시작 46초). 새 플러그인은 github · github-api · json-path-api · token-macro 넷이고, 기존 10개(workflow-cps · workflow-job 등)가 작은 버전으로 같이 올랐다 — 차트가 재시작마다 `--latest true` 로 하는 것이다(github 없이 풀어도 같다). 받아 둔 asm-api 새 버전은 적용되지 않았다. 이 때문에 같은 날 플러그인을 고정했다(1-23절) (2026-11-03 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/jenkins/values.yaml:172-173, :184, :203, :216, :241, 호스트 ~/k8s-cluster/backup/2026-11-03-webhooks/ROLLBACK.md:6, :16 --> <!-- 확인 못 함: asm-api 새 버전이 적용되지 않은 것은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->
- 잰 값: infra 빈 커밋 push → argocd-server 가 push 이벤트를 받고 **6.2초 뒤** 루트가 새 커밋(217f81c)을 봤다. 같은 push 에 petmint(수동 Sync, OutOfSync 그대로) · cloudflared(수동) 는 Sync 되지 않았다 — 마지막 Sync 시각 · 파드 UID · resourceVersion 이 push 전과 같다 (2026-11-03 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 호스트 ~/k8s-cluster/backup/2026-11-03-webhooks/watch-2f1141b.txt(21:43:05.504 수신, 21:43:11.737 루트 새 커밋), 같은 폴더 ROLLBACK.md:20. 그때 해시 2f1141b 는 지금 main 217f81c -->
- 잰 값(Jenkins, 펫퍼민트 push 62216c0): Jenkins 웹훅 수신 21:45:32.1 → 잡 조회 · 변경 감지 · #46 트리거 21:45:34.7(2.6초) → 빌드 시작 21:45:42 · 60초 · SUCCESS("Started by GitHub push") → 태그 커밋 3bfdd06 21:46:37 → ArgoCD 웹훅 수신 21:46:42 → petmint OutOfSync. 앱 push 에서 OutOfSync 까지 약 70초(빌드 60초 포함) — 전에는 폴링 2분 + 빌드 + 조회 3분이었다. Sync 는 수동 그대로(사람이 21:47:24 에 눌렀다) [c:62216c0] (2026-11-03 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 호스트 ~/k8s-cluster/backup/2026-11-03-webhooks/ROLLBACK.md:21, docs/history/build_log/06_jenkins.md:457. 그때 해시 167ed37 은 지금 main 3bfdd06 -->

#### 1-23. Jenkins 플러그인 버전 고정 (2026-11-03)

- 고정 전 확인: 렌더된 `plugins.txt` 73개 = 실행 중 73개, 빈 디렉터리에서 `--latest false` 로 풀어도 결과가 같은 73개(더 받는 의존 없음) (2026-11-03 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 실행 중 73개는 호스트 ~/k8s-cluster/backup/2026-11-03-jenkins-pin/plugins-rev6.txt, 2026-11-03-webhooks/jenkins-plugins-running.txt --> <!-- 확인 못 함: 빈 디렉터리에서 --latest false 로 푼 시험은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->
- 적용 뒤: 재시작 35초, pluginManager API 73개 모두 활성이고 고정 목록과 한 줄도 다르지 않다. JCasC · githubPush 트리거 · 서명 설정 그대로, 웹훅 서명 시험 맞음 200 · 틀림 400 · 없음 400 (2026-11-03 기준) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->

#### 1-24. 가용성 — 워커 4대 · 8GB, 노드가 하나 죽으면 (2026-11-10)

- **증설 중 확인(호스트 → VIP, 1초마다)**: w2 · w3 정비 동안 `/` 실패 0. 앱 Pod는 Harbor가 살아 있을 때 먼저 옮겼다(w3 → w2, w1 → w4). (2026-11-10 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/08_scale_out.md:200, :224-225 --> <!-- 확인 못 함: 옮긴 방향(w3 에서 w2, w1 에서 w4)은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->
  w1 정비 때 MySQL(`mysql-0`, PV가 w1)이 19:35:15~19:36:59 KST 약 1분 40초 멈췄다 — `/`는 200이었지만 DB를 쓰는 API는 실패(사용자가 받아들인 중단). (2026-11-10 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/08_scale_out.md:228-229 (끝 시각은 기록대로 19:36:59) -->
  그 전 19:27:20~31 약 12초는 ingress-nginx 등을 재시작할 때 모든 호스트가 응답하지 않았다(원인 미확인, infra `docs/history/build_log/08_scale_out.md` 4절) (2026-11-10 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/08_scale_out.md:226, :249-253, :441 -->
- 펫퍼민트 Sync를 두 번 했다(Replica 추가 bda8638, 배치 고정 2298d61) — 사람 대신 인프라 세션이 했고, 그 Sync마다 초기화 Job이 다시 돌았다(멱등) [code:db/seed_insurance_core.py:9-13] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/08_scale_out.md:400-403, apps/petmint/jobs/init-db.yaml:15-16. 그때 해시 72d0716, 684774a 는 지금 main bda8638, 2298d61 --> <!-- 확인 못 함: 인프라 세션이 두 번 Sync 한 것은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->

#### 1-25. 자동 Sync (2026-11-11)

| 항목 | 값 |
| --- | --- |
| 켠 때 | 켜기 전 Synced(git 최신 `f2c28e6`과 같음) — 켜는 순간 반영될 것이 없었다. 켠 뒤 Synced · Healthy, 앱 Pod 재시작 없음 (2026-11-11 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 그때 해시 cd4ee1f 는 지금 main f2c28e6(2026-11-11 16:07:31), 자동 Sync 를 적은 a9cea97(16:23:42)보다 앞선 최신 --> <!-- 확인 못 함: 켜기 전후 Synced, Healthy 와 Pod 재시작 없음은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) --> |

#### 1-26. 검색 모델을 공용 model-service로 (2026-11-11, 0e31e94)

| 항목 | 값 |
| --- | --- |
| 전환 | model-service 등록 17:34:19 → petmint-search 재시작 17:38:24 정지 · 17:38:25 시작. 원격 모드라 모델을 올리지 않아 끊긴 시간은 약 6초(import 5.3초 + 청크 · BM25 0.1초) (2026-11-11 기준) <!-- 2026-11-19 잼: systemctl status 로 model-service 는 2026-11-11 17:34:19, petmint-search 는 2026-11-11 17:38:25 부터 active(문서의 등록과 시작 시각과 같음) --> <!-- 확인 못 함: logs/search_service.log 는 질문 원문이 들 수 있어 열지 않음, 끊긴 시간 약 6초는 지난 일이라 다시 잴 수 없음 --> |
| 전후 대조 | `scripts/search_parity.py`, 전환 전 운영(8100) ↔ 전환 뒤 391건 다름 0 — `/search` 258건(회귀 세트 약관 103 + 인사규정 26 × 운영 설정 · 기본 설정, top_k 200이라 리랭커 후보 전부) + `/embed` 133건. 값으로 비교한다(순서 · 필드 · float ==). Milvus가 청크 필드 키 순서를 호출마다 바꿔 바이트 비교는 쓸 수 없다 [code:scripts/search_parity.py:1-16] [code:scripts/search_parity.py:30] (2026-11-11 기준) <!-- 확인 못 함: 대조 결과 원자료 logs/parity/ 는 로컬에도 없음 --> |
| 검색 회귀 | 전후 같다(문항별 순위 · 상위 결과가 다른 문항 0). 약관 103: hit@1 80 · hit@3 97 · hit@5 97 · MRR 0.897 · 범위 위반 0. 인사규정 26: 25 · 26 · 26 · 0.981 · 0 [code:data/eval/search_regression.json] [code:data/eval/search_regression_hr.json] [code:data/review/pool_measure.md:57] (2026-11-11 기준) <!-- 확인 못 함: 전환 전후 회귀 결과는 그때 원자료가 남지 않음(data/eval/results/ 에 2026-11-11 판이 없음) --> |
| GPU(nvidia-smi) | 전환 전 search-service 6,216MiB. 전환 직후 model-service 3,498MiB 하나(전체 3,537MiB), 대조 부하 뒤 6,408MiB(늘어난 몫은 PyTorch 추론 캐시). 모델 무게는 KURE-v1 fp32 2.12GB · 리랭커 fp16 1.06GB (2026-11-11 기준) <!-- model-service 확인(2026-11-19): 8200/health 의 dtype 은 KURE float32, 리랭커 float16, 무게는 ~/AI_programming/model-service/README.md:29-30 의 2.12GB, 1.06GB --> <!-- 확인 못 함: 그날 MiB 값은 지난 일이라 다시 잴 수 없음(2026-11-19 nvidia-smi 로 model-service 6,424MiB, 전체 6,463MiB) --> |

#### 2-7. ArgoCD 에 넘길 때 지킨 세 가지

넘겨받는 순간은 안전했다. 처음 상태는 OutOfSync 였고, 14개 리소스의 diff 가 모두 ArgoCD 추적 라벨 하나뿐이었다. Sync 뒤에도 앱 Pod 와 mysql-0 의 UID 가 같아 교체되지 않았다. (2026-10-16~2026-10-18 사이) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답, 호스트 백업에는 2026-10-16-argocd/petmint-before.yaml 만 있음) -->
