> 상태: 설계 확정, 구현 중. 스키마(마이그레이션 0001~0004)는 2026-10-15 완료, 그 뒤 0005 후속 판별·0006 로그인·0007 상담원 이메일 옮기기·0008 code_rule·0009 refused·search_ms(2026-11-11). 클러스터 MySQL(StatefulSet + PVC) 이주는 2026-10-16 완료.
> 검색 결과·계산 카드·되묻기를 턴 로그에 쓰는 경로는 search-service 연결(2026-10-21) 뒤 운영에서 돈다.
> 

---

### 0. 한 줄 요약

상담 세션과 모든 턴의 로그를 MySQL에 남긴다. **"그때 어떤 조건에서 무엇을 보고 어떻게 답했는가"를 나중에 그대로 재현할 수 있게** 하는 것이 목표다.

---

### 1. 최종 설계

#### 1-1. 테이블 다섯(+ 로그인 둘)

```
sessions (상담 1건)
   └─ turns (질문 여러 개)
         ├─ turn_scope (그 질문에 적용된 가입 내용, 여러 줄)
         ├─ retrieved (검색된 조문, 여러 줄)
         └─ feedback (평가, 0~1줄)
```

**sessions — 상담 한 건**

| 칼럼 | 내용 |
| --- | --- |
| session_id | PK |
| mode | 일반 / 사내규정 / 업무특화 |
| customer_id | 업무특화만. 상담 중 바뀌지 않는다 |
| agent_email | 상담원 신원 — 앱 로그인(`PETMINT_AUTH=app`, 운영 2026-10-28)이면 로그인한 직원의 이메일, `access`면 Cloudflare Access 헤더(13번). 헤더가 없으면 기본값(`PETMINT_DEFAULT_AGENT`) |
| started_at | 상담 시작 |
| ended_at | 업무특화만 채워진다. 일반·사내규정은 닫히지 않아 NULL로 남고, 그것이 곧 "이어 쓸 수 있다"는 표시다 |
| title | 지난 대화 목록과 과거 상담 목록에 보일 제목. 자동으로 한 번 넣는다 — 일반·사내규정은 첫 질문을 베이스 모델로 요약하고(실패하거나 늦으면 첫 줄), 업무특화는 늘 첫 질문 첫 줄이다(베이스로 지으면 모델 교체로 첫 답이 약 5초 늦어졌다, `app/services/titles.py` `uses_llm`). 그 뒤에는 상담원이 바꿀 수 있다(PATCH). **세 모드 모두 채운다** — 업무특화도 고객 조회의 과거 상담 목록에서 제목을 쓴다(09번 2-2절) |
| deleted_at | 상담원이 목록에서 치운 시각. 로그는 지우지 않는다(1-4절) |
| pinned | 지난 대화 목록 상단 고정. 상담원 개인 설정이라 일반·사내규정에만 쓴다 |

인덱스: `customer_id`(고객별 상담 내역), `started_at`(최근 상담 탭), `(agent_email, mode, deleted_at, started_at)`(지난 대화 목록 — 상담원 자기 것만, 모드별로, 치운 것 제외)

**turns — 질문 하나와 그 답**

| 칼럼 | 내용 |
| --- | --- |
| turn_id | PK |
| session_id | FK |
| question / rewritten_question / answer | 원문 질문, 재작성된 질문, 답변 |
| pet_id / pet_name / species / breed / pet_age | 이 턴이 누구 얘기였나 — 상담 중에 바뀐다 |
| is_hypothetical | 가정 질문 여부(09번 4절) |
| clarified | 되묻기가 발동했는지(09번 4절) — 등급 되묻기, 그리고 코드가 되물은 턴(금액·병명 되묻기, 날짜별 금액 칸) |
| code_rule | 답한 코드 규칙(`code_rules.Rule.key` 14개 또는 `hr_personal`). NULL이면 모델이 답했다. 2026-10-29 `0008_turn_code_rule` — 그 전 턴도 NULL이라 규칙별 집계(`db.rule_report`, 16번 5절)는 적용 시각 이후만 본다 |
| model / prompt_version / index_version | 재현에 필요한 버전 |
| refused | 답이 거절 문구인가(0/1). 판정은 `data/refusal.refused` — 평가(`scripts/eval_serving`·`verify_modes`)와 운영 집계(`db.rule_report`)가 같은 함수를 쓴다. `status=ok` 턴만 채우고 cancelled·error는 NULL. 코드 답 턴도 판정한다. 2026-11-11 `0009_turn_refused_search_ms` — 그 전 턴은 NULL이고 다시 채우지 않는다. Grafana 「거절률」이 읽는다(15번) |
| first_token_ms / latency_ms / created_at | 첫 토큰까지의 시간, 전체 지연 시간, 시각. `first_token_ms`는 모델 스왑 지연 측정에 쓴다(09번 7-3절) |
| search_ms | 그 턴에서 search-service(`/search`·`/embed`)를 기다린 시간 합(ms). 부르지 않은 턴(일반 모드, 사내규정 개인화)은 NULL. **업무특화 코드 답 턴도 값이 있다** — 코드 답 규칙은 검색 결과를 받은 뒤에 돈다(`answer._generate`). 실패한 호출도 기다린 시간은 더한다. 턴마다 `answer.TimedRetriever`가 공용 리트리버를 감싸 다른 턴과 섞이지 않는다. 2026-11-11 `0009`, Grafana 「검색 지연」이 읽는다 |
| status | `ok` / `cancelled` / `error`. 08 평가가 미완성 턴을 걸러낼 수 있어야 한다 |
| payout | 계산 카드 결과(JSON, `CalcResult` — 의료비·법률비용·한도·날짜별 입력). 카드가 없는 턴은 NULL |

> **계산 결과도 저장한다.** `turn_scope`에 등급·자기부담금이 당시 값으로 남아 있어 다시 계산할 수도 있지만, `limit_table`이나 약관이 개정되면 같은 scope로도 다른 숫자가 나온다. 2-2절의 스냅샷 원칙이 여기에도 걸린다 — "그때 5만원이라고 안내했다"가 재현되어야 한다.
> 

인덱스: `session_id`, `created_at`

**turn_scope — 그 질문에 적용된 가입 내용**

| 칼럼 | 내용 |
| --- | --- |
| turn_id | FK |
| section_name | 특약 이름 |
| coverage_type | 고급형 / 기본형 / 실속형 |
| copay | 자기부담금 |
| excluded_conditions | 부담보 |

특약 하나당 한 줄. 고객이 세 개에 가입했으면 세 줄.

**retrieved — 그 질문에 검색된 조문**

`turn_id`, `rank`, `graph_key`, `score`, `content`, `used`. 턴당 3~10줄(검색 `top_k` 설정에 따른다. 답변 경로의 top_k는 3이다(`answer.SEARCH_TOP_K`). 일반 모드는 검색이 없어 0줄). `used`는 답변에 실제로 쓰인 근거인지 — 08 평가에서 쓴다.

**조문 식별은 `graph_key`가 기준이다.** Milvus auto_id는 재색인하면 바뀌므로 쓰지 않는다(09번 6-3절). `section_name`+`article_num`만으로는 조문이 특정되지 않는다 — 강아지·고양이 약관에 같은 조합이 있고, 보통약관은 `section_name`이 NULL이며, 사내규정은 별도 코퍼스다.

여기에 표시·복원용 값을 함께 박아둔다: `corpus`(강아지/고양이/인사규정), `section`, `article_num`, `article_title`, `coverage_type`, `paragraph_num`, 그리고 `used` 행에만 `citation_label`. 2-3절의 스냅샷 원칙과 같은 이유다 — 지난 대화를 다시 열었을 때 근거 패널과 인용이 그때 모습 그대로 나와야 한다.

`corpus`는 문자열로 둔다. 모드마다 리트리버가 달라지고 코퍼스가 늘어날 수 있다(09번 9절).

**그래프로 따라간 조문도 여기 남는다.** 답변이 인용한 조문이 벡터 검색 결과에 없으면 저장할 곳이 없어진다 — 참조 그래프로 따라간 조문이나 소득세법 박스가 그렇다. `via_graph`로 구분해 함께 넣는다.

**그래프 확장분은 청크가 아니다.** 여러 청크를 이어 붙인 본문이거나(참조 조문), 약관 밖의 법령이다(소득세법 박스). 그래서 청크 하나의 `graph_key`도 `section`도 없다. 청크용 제약을 걸 대상이 아니므로 행의 종류로 제약을 갈라 `CHECK`로 강제한다. 따라서 위의 "`graph_key`가 기준 키"는 검색 행에 한정된다.

| via_graph | rank | graph_key · section | 식별 |
| --- | --- | --- | --- |
| FALSE (검색 결과) | NOT NULL | NOT NULL | graph_key |
| TRUE (그래프 확장) | NULL | NULL 허용 | citation_label · article_title |

`content`는 두 경우 모두 NOT NULL이다 — 재현의 핵심이다. `score` 역시 그래프 행에는 없으므로 NULL이다 — 0을 넣으면 진짜 0점과 구분되지 않고, 없는 값을 지어내는 셈이 된다. `rank`는 검색 순위이므로 그래프 확장분에는 없다 — 기본키는 대리키 `id`로 두고 `(turn_id, rank)`는 인덱스로 남긴다.

**제약을 앱이 아니라 DB에 두는 이유**는, 검색 행의 보장이 조용히 풀리면 08 평가가 틀어지기 때문이다.

참조 조문의 개별 청크 키를 만들어 넣는 안은 버렸다. `data/rag_context.py`는 05·06 노트북과 공유하는 모듈이라, 저장 스키마를 맞추려고 그 출력을 바꾸면 평가와 서비스가 같은 코드를 쓴다는 원칙(09번 3-3절)이 깨진다. 합성 키도 Milvus에 대응이 없는 발명이라 나중에 무엇을 가리키는지 알 수 없게 된다.

08 Ragas가 "모델이 받은 발췌"를 입력으로 쓰므로, 그래프 확장분이 빠지면 컨텍스트가 실제보다 짧게 기록된다.

**feedback — 상담원 평가**

`turn_id`(PK/FK), `rating`, `comment`, `created_at`. 원본 로그는 고치지 않고 따로 쌓는다.

**accounts·auth_sessions — 앱 로그인(2026-10-28, 0006)**

직원 신원은 기간계 인사 원장(아래)에 있고, 여기에는 앱이 쓰는 값만 둔다. `employee_id`는 다른 데이터베이스라 외래키를 걸지 않는다(`customer_id`와 같은 경계). `sessions.agent_email`도 그대로다 — 로그인한 직원의 이메일이 들어가고, 퇴직자의 상담 기록이 남아야 하므로 외래키를 걸지 않는다.

| 테이블 | 칼럼 |
| --- | --- |
| accounts | `employee_id`(PK) · `role`(상담원·관리자) · `password_hash`(argon2id, NULL이면 로그인 불가) · `must_change_password` · `failed_count` · `locked_until` · `disabled_at` · `password_changed_at` · `last_login_at` · `created_at` |
| auth_sessions | `token_hash`(PK, 쿠키 토큰의 SHA-256) · `employee_id`(FK → accounts, CASCADE) · `created_at` · `last_seen_at` · `expires_at` · `ip` · `user_agent` |

**인사 원장 — insurance_core 0003(2026-10-28)**

고객 원장과 같은 기간계 흉내다(`petmint_app`은 SELECT만). 로그인 신원과, 다음 단계의 **사내규정 개인화**(업무특화가 고객 원장을 쓰듯)가 이 사실을 쓴다. 칸은 인사규정이 계산에 쓰는 것에서 정했다. 계산 규칙은 저장하지 않는다 — 인사규정 본문(청크)에 있다.

| 테이블 | 칼럼 | 쓰는 규정 |
| --- | --- | --- |
| employees | `employee_id`(사번) · `name` · `email` · `team` · `grade`(사원~부장) · `grade_since` · `employment_type`(정규직·계약직·파견직) · `hire_date` · `career_hire` · `birth_date` · `retired_on` | 근속(제3조 5호) · 수습 90%와 경력직 면제(제7조) · 계약직은 급여·퇴직 개별계약(제2조 ③) · 승진 체류연수(제33조 ②) · 정년 만 60세(제43조) · 출장비 직급(별표1) |
| employee_certificates | `cert_name` · `acquired_on` · `submitted_on` | 자격수당 — 사본 낸 다음 달부터, 둘 이상이면 큰 것 하나(제27조) |
| employee_payroll | `pay_month` · `base_pay` · `fixed_allowances` · `overtime_pay` · `bonus` · `ordinary_wage` · `total_pay`(생성 칼럼) | 평균임금 = 이전 3개월 임금총액 ÷ 총일수(제3조 4호) → 퇴직금(제28조), 미사용 연차수당·가산수당은 통상임금(제17조 ⑤·제12조) |
| employee_leaves | `leave_type`(연차·병가·경조·특별) · `start_date` · `end_date` · `days`(반차 0.5) | 연차 잔여 = 부여(제17조) − 사용(제18조 ②) · 병가 연 60일·유급 30일(제20조) |
| employee_absences | `kind`(질병·육아·가족돌봄·학업·병역휴직) · `start_date` · `end_date` | 육아·병역만 근속 산입(제22조 ④) |
| employee_evaluations | `period`('2026-H1') · `grade`(S~D) | 최근 2회 연속 D면 승진 제외(제33조 ③) |

직원은 전부 가상이다 — `db/fixtures/employees.json`(11명, `make_employees.py`가 만든다). 이름은 고객 10명과 성까지 겹치지 않게 지었고(2026-10-28, 예시 이름 홍길동 등에서 바꿈), 팀은 고객상담팀 하나다 — 상담원 전용 도구라 부서가 여럿일 이유가 없다. `team` 칸은 나중에 부서가 생길 수 있어 남겼다. 근속 25년(정년 임박)부터 수습 중 2개월까지, 사원~부장, 체류연수를 채운 사람과 못 채운 사람, 2회 연속 D, 자격 없음·하나·둘·사본 미제출·제출 다음 달, 육아(산입)·질병·가족돌봄(불산입) 휴직, 계약직, 퇴직자가 고루 들어 있다. 고객 픽스처와 달리 저장소에 둔다(가상이라 개인정보가 없다). 시드는 `db.seed_insurance_core`가 함께 깔고, `--if-empty`면 직원 테이블이 비어 있을 때만 깐다.

**쓰는 곳(2026-10-28)**: 사내규정 모드에서 로그인한 직원 본인의 연차 잔여·연차수당·퇴직금(퇴직 예정일 포함)·자격수당·승진 시점·급여·통상임금을 코드가 계산해 답한다(`app/services/hr_personal.py`, `PETMINT_HR_PERSONAL`). 모델은 이 원장을 받지 않는다. 범위와 측정은 `data/review/hr_personal_measure.md`.

출근율(제17조 ① 80%)과 1년 미만 월 개근(제17조 ②)은 담지 않았다 — 근태 기록이 없으면 개근으로 본다. 개인화 단계에서 필요하면 근태 테이블을 더한다.

#### 1-2. 개발은 호스트 도커, 배포는 K8s

| 단계 | 구성 |
| --- | --- |
| 개발  | 호스트 도커 컨테이너. 데이터는 호스트 볼륨에, `--restart unless-stopped` |
| 배포(지금) | StatefulSet + PVC. 계정은 Secret, 스키마는 초기화 Job |

**처음부터 K8s로 가지 않은 이유**는 두 가지였다. 당시 백엔드가 호스트에서 돌고 Dockerfile도 없어서, MySQL만 Pod에 있으면 개발 내내 포트포워딩을 유지해야 했다. 그리고 스키마가 자주 바뀌는 시기라 만들고 지우고 다시 만드는 것을 PVC 붙은 StatefulSet에서 하면 번거로웠다.

**이주를 설정 변경 수준으로 만드는 것은 환경변수다.** 호스트·포트·사용자·비밀번호·DB 이름을 전부 환경변수로 뺀다. 코드에 접속 정보를 하드코딩하지 않는다.

**이주 때 할 일** (상세는 14번)

- ✓ StatefulSet + PVC로 올리고, 계정 정보를 Secret으로 주입(2026-10-16)
- ✓ 스키마 초기화 Job 또는 마이그레이션 실행(2026-10-16)
- ✗ `mysqldump`로 개발 데이터를 넣는다. 다만 **개발 중 쌓인 로그를 가져갈지는 그때 정한다** — 테스트 대화가 섞여 있으면 버리는 편이 낫다
- ✓ 환경변수만 바꾸고 연결 확인(2026-10-16)

실제로는 `mysqldump`를 쓰지 않았다. 클러스터 DB는 픽스처 시드로 새로 시작했고, 개발 중 쌓인 테스트 대화는 가져가지 않았다.

#### 1-3. 인스턴스 구성

클러스터에 MySQL 인스턴스 **하나**만 둔다(StatefulSet + PVC). 데이터베이스를 `petmint`와 `insurance_core`로 나누고, 계정도 나눠 각자 자기 데이터베이스만 접근하게 한다. `insurance_core`는 고객 원장이고 `petmint_app` 계정은 SELECT만 가진다(4절). Secret은 네임스페이스별로 둔다. RUNSHOES를 같은 클러스터에 올릴 때 `runshoes` 데이터베이스와 계정을 같은 방식으로 추가한다 — 초기화 Job의 `BOOTSTRAP_APPS`에 넣으면 된다.

#### 1-4. 지난 대화 삭제는 숨김이다

일반·사내규정 모드의 지난 대화 목록에서 항목을 치우면 `sessions.deleted_at`에 시각을 찍는다. 목록과 조회에서만 빠지고 `turns`·`retrieved`·`feedback`은 그대로 남는다. 외래키에 `ON DELETE CASCADE`를 걸지 않는다.

`GET /api/sessions`는 `agent_email` 일치, 모드 일치, `title IS NOT NULL`, **그리고** `deleted_at IS NULL`로 걸러낸다. 정렬은 고정한 것 먼저, 그다음 마지막 활동 순이다.

UI 라벨은 "삭제"가 아니라 **"목록에서 제거"**다. 사내 도구라 로그가 남는 것은 맞지만, 버튼이 "삭제"인데 실제로 안 지워지면 상담원이 오해한다.

지난 대화 목록은 일반·사내규정에만 있다. 업무특화는 고객 조회 화면의 "최근 상담" 탭이 그 자리를 대신하므로(09번 2-2절) 제거 기능도 없다. 다만 `deleted_at`은 모드와 무관하게 `sessions`에 둔다 — 최근 상담 탭과 고객별 과거 상담 목록도 같은 필터를 쓴다.

#### 1-5. 백업과 복구 (2026-11-10)

클러스터 MySQL(`petmint/mysql-0`)을 **하루 한 번 `mysqldump`로 떠서 호스트에 둔다.**

| 항목 | 값 |
| --- | --- |
| 무엇을 | CronJob `petmint/mysql-backup` — ronanlab-infra `apps/petmint/backup/cronjob.yaml` |
| 언제 | 매일 03:30 KST(`timeZone: Asia/Seoul`). 겹치면 건너뛴다(`concurrencyPolicy: Forbid`) |
| 대상 | `petmint`·`insurance_core` 두 데이터베이스. `mysql` 시스템 DB(계정)는 뜨지 않는다 — 계정·권한은 초기화 Job(`db.bootstrap`)이 Secret 값으로 다시 만든다 |
| 방식 | `mysqldump --single-transaction --quick --routines --triggers --events --no-tablespaces --set-gtid-purged=OFF --hex-blob` → gzip. 모든 테이블이 InnoDB라 일관 스냅샷이 되고 테이블 락이 없다 — 앱이 계속 쓴다 |
| 어디에 | 호스트 `~/backup/mysql/petmint/petmint-YYYYMMDD-HHMMSS.sql.gz`(+ `.sha256`). 클러스터에서는 NFS 쓰기 export `/srv/nfs/backup/petmint`(호스트 설정 `deploy/scripts/host-nfs-backup-setup.sh`, sudo로 사람이 한 번)로 붙는다 |
| 보존 | 30일. 단 최신 7개는 날짜와 상관없이 남긴다 — CronJob이 오래 멈췄다가 다시 돌아도 백업이 한꺼번에 사라지지 않는다 |
| 비밀번호 | Secret `mysql-root`를 환경변수 `MYSQL_PWD`로 받는다. 명령 인자에 넣지 않는다 |
| 실패 | 반쯤 쓴 파일을 남기지 않는다. `.part`로 쓰고 `gzip -t`와 끝 줄 `-- Dump completed`를 확인한 뒤 이름을 바꾼다. 확인이 안 되면 Job이 실패한다 |

크기는 하루 약 136KB다(2026-11-10, 19개 테이블). 30일을 남겨도 5MB가 안 된다.

**수동으로 뜨기** — 호스트에서 한다. CronJob과 같은 옵션을 쓴다:

```bash
K="ssh -i ~/k8s-cluster/.vagrant/machines/m-k8s/libvirt/private_key vagrant@192.168.122.10"
F=~/backup/mysql/petmint/petmint-$(date +%Y%m%d-%H%M%S).sql.gz
$K 'kubectl -n petmint exec mysql-0 -c mysql -- sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" exec mysqldump -uroot --single-transaction --quick --routines --triggers --events --no-tablespaces --set-gtid-purged=OFF --hex-blob --databases petmint insurance_core"' \
  | gzip -9 > "$F.part" && gzip -t "$F.part" && zcat "$F.part" | tail -1 | grep -q '^-- Dump completed' \
  && mv "$F.part" "$F" && (cd "$(dirname "$F")" && sha256sum "$(basename "$F")" > "$(basename "$F").sha256")
```

CronJob을 지금 한 번 돌리려면 `kubectl -n petmint create job --from=cronjob/mysql-backup mysql-backup-manual-$(date +%s)`.

**복구 절차** — 운영 DB 전체를 백업 시점으로 되돌린다. 아래 `$K`는 위와 같다.

1. **고를 파일을 확인한다.** `cd ~/backup/mysql/petmint && sha256sum -c petmint-<시각>.sql.gz.sha256`, `zcat petmint-<시각>.sql.gz | tail -1`이 `-- Dump completed`
2. **자동 Sync를 끄고 앱을 멈춘다.** 자동 Sync(2026-11-11~)가 켜져 있으면 복구 중에 들어온 커밋이 앱을 다시 띄우고 초기화 Job을 돌린다. 끄는 명령은 ronanlab-infra `apps/petmint/README.md`. 그다음 `$K 'kubectl -n petmint scale deploy/petmint-app --replicas=0'`. 복구 중에 앱이 쓰면 테이블이 섞인다. ArgoCD가 OutOfSync로 잡는 것은 정상이다 — 6에서 Sync하면 git 값(2)으로 돌아온다
3. **지금 상태를 먼저 뜬다.** 위 "수동으로 뜨기"를 그대로 한다(파일 이름에 `-before-restore`를 붙여 두면 보존 정리에서 헷갈리지 않는다). 복구를 되돌릴 유일한 길이다
4. **두 데이터베이스를 지운다.** `$K 'kubectl -n petmint exec mysql-0 -c mysql -- sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysql -uroot -e \"DROP DATABASE petmint; DROP DATABASE insurance_core\""'`. 덤프는 테이블마다 `DROP TABLE IF EXISTS`만 하므로, 지우지 않으면 백업 뒤에 생긴 테이블이 남고 `schema_migrations`와 어긋난다. 계정 권한(`mysql` DB)은 데이터베이스를 지워도 남는다
5. **넣는다.** `zcat petmint-<시각>.sql.gz | $K 'kubectl -n petmint exec -i mysql-0 -c mysql -- sh -c "MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" exec mysql -uroot"'`
6. **ArgoCD에서 petmint를 Sync한다.** 초기화 Job이 돈다 — `db.bootstrap`이 계정·권한을 맞추고, `db.migrate`가 백업 뒤에 생긴 마이그레이션만 적용하고, 시드는 비어 있지 않으므로 건너뛴다. Deployment가 replicas 2로 돌아온다. 확인(7)이 끝나면 자동 Sync를 다시 켠다
7. **확인한다.** 테이블별 행 수가 백업 시점과 같은지(아래 복구 시험과 같은 방법), 화면에서 지난 대화·고객 조회가 열리는지, 로그인이 되는지

**로컬 개발 DB(호스트 도커 `mysql`, 127.0.0.1:3306)는 주 1회 뜬다.** 클러스터에서 닿지 않으므로 CronJob이 아니라 호스트 사용자 crontab이 `deploy/host/dev-mysql-backup.sh`를 일요일 05:00에 돌린다(FOREMAN 백업 04:30과 겹치지 않게). 같은 두 데이터베이스, 같은 옵션이고, `~/backup/mysql/petmint-dev/`에 최신 4개를 남긴다(로그 `backup.log`). 평가·측정 기록이 쌓여 운영보다 크다 — `petmint` 198MB, 백업 22MB, 4초(2026-11-10). 운영 백업과 디렉터리를 나눈 것은 CronJob의 보존 정리가 `petmint-*.sql.gz`를 지우기 때문이다. 복구는 위 4·5를 `docker exec -i mysql …`로 한다(앱을 멈추고, 지금 상태를 먼저 뜬다).

**복구 시험(2026-11-10).** 첫 수동 백업(`petmint-20261110-173427.sql.gz`)을 호스트의 빈 임시 컨테이너(`mysql:8.0.46`, 네트워크 없음)에 넣었다. 두 데이터베이스 19개 테이블의 행 수가 운영과 모두 같았다(sessions 169, turns 162, retrieved 464 등). CronJob 스크립트는 같은 이미지·uid 999로 돌려 보았다. 정상이면 파일과 `.sha256`이 생기고, 30일 지난 가짜 파일 10개 중 최신 7개만 남았으며, 비밀번호가 틀리면 exit 2로 실패하고 완성 파일을 만들지 않았다. 개발 DB 첫 백업도 같은 방법으로 19개 테이블 행 수가 같았다(sessions 21,473, turns 24,603, retrieved 87,394). 임시 컨테이너는 초기화 뒤 서버를 한 번 다시 띄우므로, 로그에 `ready for connections … port: 3306`이 찍힌 뒤에 넣는다 — 먼저 넣으면 `Lost connection`으로 끊긴다.

---

### 2. 왜 이렇게 했나

#### 2-1. scope를 세션이 아니라 턴에 둔다

상담 한 건 동안 고객은 바뀌지 않으니 가입 내용도 세션에 붙이면 될 것 같다. 그러나 **같은 상담 안에서도 검색 범위가 바뀌는 경우가 둘** 있다.

- **반려동물 전환**(10번 6절) — 초코 얘기하다 보리로 넘어가면 종·특약·등급이 전부 바뀐다
- **가정 질문**(09번 4절) — 고급형 가입자가 "실속형이면 어때요?"라고 물으면 그 턴만 범위가 달라진다

세션에 고정하면 이 둘이 기록되지 않는다. 중복은 늘어나지만(턴당 두세 줄) 로그는 추측이 섞이면 쓸모가 없다.

#### 2-2. 외래키만으로는 "그때 조건"이 남지 않는다

로그에 `pet_id`만 적어두면, 반년 뒤에 해피가 고급형에서 실속형으로 바뀌었을 때 과거 로그를 열어보면 **실속형으로 보인다.** 외래키는 "P001을 찾아가라"는 화살표일 뿐, 그 시점 값을 얼려두지 않는다.

그러면 평가가 틀어진다. "수술비 5만원"이 맞는 답인지 보려면 **그 순간의 등급·자기부담금·부담보**를 알아야 하기 때문이다.

그래서 판단에 필요한 값은 턴에 그대로 박아둔다(스냅샷). 주문서에 상품 가격을 복사해 두는 것과 같은 이치다 — 상품 가격이 올라도 작년 주문서의 금액은 그대로여야 한다.

`pet_id`도 함께 남긴다. 둘은 역할이 다르다 — **하나는 연결, 하나는 기록.**

#### 2-3. 검색된 조문 본문을 통째로 저장한다

조문 번호만 남기고 나중에 Milvus에서 다시 꺼내는 방법도 있다. 가벼워지지만 **약관을 다시 색인하면 그때 무엇을 봤는지 알 수 없게 된다.** 08 Ragas 평가가 "모델이 받은 발췌"를 입력으로 쓰므로 재현이 되어야 한다.

크기를 가늠해 보면 턴당 약 5KB(검색 3개 × 평균 1,500자)다. 하루 500턴이면 2.5MB, 1년이면 900MB — 상담원 몇 명 규모에서는 버틸 수준이다. `top_k`를 7로 올리면 두 배가 조금 넘는다.

△ 다만 오래된 로그는 본문만 비우고 조문 번호는 남기는 보관 정책을 나중에 붙인다. IT팀이 품질을 보는 것은 대개 최근 로그이고, 파인튜닝 데이터로 쓸 만한 것은 그 전에 따로 뽑으면 된다.

#### 2-4. 인스턴스를 나누지 않는다

데이터베이스가 다르면 데이터는 섞이지 않지만, 같은 프로세스라 한쪽이 죽으면 둘 다 죽는다. 그런데 둘 다 포트폴리오고 트래픽도 없으므로, 16GB에 GPU 모델들이 올라가는 것을 생각하면 인스턴스 둘은 아깝다. 계정 분리로 최소 권한은 지킨다.

#### 2-5. 언제 MySQL로 옮기는가

초안은 JSONL 파일이었다 — 쓰기만 하고 08 평가에서 통째로 읽으면 충분했기 때문이다. 그러나 세 가지가 걸렸다.

- **상담 내역 조회** — 고객별·기간별로 뽑으려면 매번 파일을 처음부터 훑어야 한다
- **세션 재시작 소멸** — 메모리 세션은 서버 한 번 재시작에 대화가 다 날아간다. 일반·사내규정을 하루 종일 쓰는 구조라 곤란하다
- **책임 추적** — 누가 어떤 답변을 했는지 턴 단위로 남아야 한다

세션도 같은 DB에 넣으면서 두 번째 문제가 풀렸다.

#### 2-6. 지우기를 숨김으로 바꾸는 이유

상담원 화면에서 대화를 치웠다고 턴·검색 결과·평가까지 사라지면, 0절의 재현 목표와 2-5절의 책임 추적이 동시에 깨진다. 그 둘은 MySQL로 온 이유 자체다.

목록에서 치우는 것은 상담원의 작업 공간 정리이지 기록 폐기가 아니다. 둘을 같은 동작으로 묶으면 한쪽을 포기해야 한다.

`deleted_at`은 4절의 보관 정책이 붙을 때 기준값이 된다 — 치운 지 N일 지난 세션부터 본문을 비우면 된다.

---

### 3. 시도했던 것들

| 시도 | 결과 |
| --- | --- |
| JSONL 파일로 로그 보관 | 쓰기만 할 때는 충분했으나 조회가 생기면 매번 전수 탐색. 세션 재시작 소멸도 해결되지 않는다 |
| SQLite | 파일 하나라 간편하지만 K8s에서 Pod가 여러 개면 파일을 공유해야 한다 |
| PostgreSQL | JSONB가 편하지만 MySQL도 JSON 타입이 있어 결정적이지 않았다. 더 흔하고 채용 공고에도 자주 나오는 MySQL로 갔다 |
| scope를 JSON 한 덩어리로 | 모양이 바뀌어도 상관없어 편하나 "고급형 고객 질문만" 같은 조회가 번거롭다. 칼럼으로 펼치고 테이블을 나눈다. |
| scope를 sessions에 붙임 | 상담 중 고객이 안 바뀐다는 생각에서 출발했으나, 반려동물 전환과 가정 질문을 담지 못한다(2-1절) |

---

### 4. 남은 한계

- **중복이 있다.** 같은 scope가 턴마다 반복된다. 정확성과 바꿔 받은 것이다
- **보관 정책이 없다.** 일단 전부 남기고, 데이터가 쌓인 뒤에 오래된 본문을 비우는 정책을 붙인다
- **인사 원장도 별도 DB다.** 직원 신원·급여·휴가는 `insurance_core`, 앱 계정·로그인 세션은 `petmint`. 로그인할 때 두 데이터베이스를 따로 읽는다(조인하지 않는다)
- **고객 원장은 별도 DB다.** `insurance_core`에 기간계를 흉내 낸 테이블을 두고 `petmint_app`은 SELECT만 한다. 데이터베이스가 다르므로 `customer_id`에 외래키를 걸 수 없고, 그것이 경계가 있다는 표시다. 내용은 여전히 픽스처 10명이다. 상세는 14번 2-3절.
- **백업이 같은 물리 디스크에 있다.** MySQL PVC(w1 VM 디스크)와 백업(호스트 `~/backup`)이 같은 호스트 NVMe 위다. 실수로 지운 데이터·잘못된 마이그레이션은 되돌리지만 디스크 고장에는 못 버틴다. 바깥 사본은 아직 없다(1-5절)
- **백업은 root 계정으로 뜬다.** 백업 전용 계정(SELECT·SHOW VIEW·TRIGGER·EVENT만)을 만들면 Secret이 하나 늘고 `db.bootstrap`을 고쳐야 해 미뤘다
- **백업 실패를 알리지 않는다.** Job 실패는 `kubectl -n petmint get jobs`와 ArgoCD에서만 보인다
- **하루 단위다.** 바이너리 로그로 특정 시각까지 되감는 복구(PITR)는 없다 — 마지막 백업 뒤의 대화는 잃는다

---

### 5. 검증 항목

- [ ]  반려동물을 바꿔 질문했을 때 turn마다 다른 scope가 남는가
- [ ]  가정 질문이 `is_hypothetical`로 구분되는가
- [ ]  고객 등급을 바꿔도 과거 로그의 등급은 그대로인가
- [ ]  `agent_email`이 턴마다 추적 가능한가
- [x]  계정이 자기 데이터베이스만 보는가(교차 접근 차단)
- [x]  서버 재시작 후에도 일반·사내규정 세션이 남아 있는가
- [x]  지난 대화를 목록에서 제거한 뒤에도 `turns`·`retrieved`가 남아 있는가
- [ ]  재색인 후에도 과거 턴의 근거 패널이 그때 모습으로 복원되는가
- [ ]  검색 행(via_graph=FALSE)에 graph_key 없이 들어가는 쓰기가 CHECK에 막히는가
- [ ]  취소된 턴이 `status`로 구분되어 08 평가 입력에서 빠지는가
- [ ]  약관 개정 후에도 과거 턴의 계산 카드가 당시 금액으로 보이는가
- [x]  백업 파일로 빈 MySQL에 복구하면 테이블별 행 수가 운영과 같은가(2026-11-10, 19/19)
- [x]  CronJob이 03:30에 돌아 호스트 `~/backup/mysql/petmint`에 파일이 생기는가 — 2026-11-11 03:30:00 KST `petmint-20261111-033000.sql.gz`(135,942바이트, 3초). sha256 OK, 끝 줄 `Dump completed`, 소유자 uid 1000(all_squash), 권한 640
- [ ]  복구 절차 1~7을 운영 DB에 그대로 해 본 적이 있는가(지금은 임시 컨테이너 시험만)