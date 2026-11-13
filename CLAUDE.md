답변은 항상 한국어로 한다. 코드·명령어·경로·로그는 원문 그대로 둔다.

# 펫퍼민트 RAG 챗봇 — 세션 규칙

이 저장소에서 도는 Claude 세션(관리자 · 작업 세션)이 읽는 규칙이다. 2026-11-13 관리자 체제에 맞춰 절을 더했다(본: `~/ronanlab-infra/CLAUDE.md` · `~/AI_programming/runshoes/CLAUDE.md`).
모르는 것은 「정해지지 않음」으로 둔다 — 지어내지 않는다.

## 이 저장소가 무엇인가

- 반려동물 보험 약관(메리츠화재 '펫퍼민트', 강아지 · 고양이)과 가상 인사규정에 답하는 상담원용 RAG 챗봇(`README.md`). 원격 `https://github.com/Gabriel-Joo/petmint-rag-chatbot.git`
- 앱 `app/`(FastAPI) · `web/`(React) · `search_service/`(호스트 검색 서비스) · `db/`(MySQL 접속 · 마이그레이션 · 시드) · 데이터 구축 파이프라인(`scripts/` · `notebooks/`, 단계 문서 `docs/02_pipeline/00~16`). 모델 · 데이터 · GPU는 모두 로컬, 외부 LLM API는 부르지 않는다
- **push가 하는 일**: `main` push → GitHub 웹훅(안전망 폴링 15분) → Jenkins `petmint-app`이 이미지(`harbor.ronanlab.dev/petmint/petmint-app`, 태그 = 커밋 해시 12자리)를 Harbor로 → **ronanlab-infra** `apps/petmint/kustomization.yaml`에 태그 커밋 → ArgoCD **자동 Sync**(2026-11-11~, `docs/02_pipeline/14_deployment.md` 1-25절). Jenkins는 이 저장소에 커밋하지 않는다
- **Sync마다 초기화 Job이 돈다**(infra `apps/petmint/jobs/init-db.yaml`: bootstrap → `db.migrate` → `db.migrate --app insurance_core` → 시드 `--if-empty`). 그래서 `db/migrations/`에 새 파일이 든 push는 **push만으로 운영 DB 스키마가 바뀌고, 이미지를 되돌려도 스키마는 돌아오지 않는다**(14번 4절)
- **문서만 바뀐 push**(바뀐 파일이 모두 `docs/` · `data/review/` · 루트 `*.md`)는 빌드는 돌지만 이미지 · 태그를 건너뛴다(`Jenkinsfile` 머리 주석). 손으로 누른 빌드, 직전 성공 커밋을 못 찾을 때는 늘 빌드한다
- 호스트에서 도는 것(클러스터 밖): Ollama 컨테이너 `ollama`, Milvus, search-service(`deploy/host/petmint-search.service`), 로컬 개발 DB 컨테이너 `mysql`(127.0.0.1:3306)
- **클러스터 일(Sync · 자동 Sync 스위치 · ConfigMap 플래그 · kubectl)은 이 저장소 일이 아니다** — 매니페스트는 ronanlab-infra `apps/petmint/`에 있다. 인프라 관리자에게 부탁한다

## 작업 규칙

- 진행 중 판단이 갈리면 가장 보수적인 쪽으로 정하고 진행한 뒤, 무엇을 어떻게 정했는지 보고한다(2026-10-15·16 사용자 지시).
- 생성 모델(Tri-7B)·임베딩(KURE-v1)·리랭커(bge-reranker-v2-m3)는 교체하지 않는다(2026-10-21 사용자 결정). 재학습·검색 개선은 이 셋을 고정하고 한다 — `docs/next_rebuild.md` 10절.
- 하지 않는 것(2026-11-09 사용자 지시):
  - 서버를 재부팅하지 않는다.
  - `~/.cloudflared/`를 손대지 않는다.
  - ollama 터널(`cloudflared-ollama`, ollama.ronanlab.dev)을 끄지 않는다 — 학교 PC가 쓴다(`docs/02_pipeline/13_access_and_tunnel.md` 1-3절).
  - 런슈즈 파일은 읽기만 한다.
  - 비밀값(토큰·비밀번호·키)을 출력하지 않는다.
- **push는 관리자가 한다**(2026-11-13 사용자 결정 — FOREMAN · 인프라 · 런슈즈와 같게). 작업 세션은 worktree에서 커밋까지만 한다. 관리자가 사람 답을 전하고 합치기를 대신 승인하며, 관리자끼리 부탁을 주고받는다(아래 「관리자」). 다만 force push · 마이그레이션 · 설정 파일처럼 「늘 사람에게」인 것은 그대로 사람에게 간다(아래 「사람 승인이 필요한 것」).
  - 2026-11-09 ~ 11-12에는 관리자가 없어 「push는 사용자가 이 세션에서 직접 말할 때만 한다. FOREMAN이나 다른 세션이 전한 승인은 승인으로 치지 않는다」였다(2026-11-09 사용자 — "커밋까지만. push는 내가 말할 때"). 11-13에 위 줄로 바꿨다.
- 기본 제공 Explore 서브에이전트는 `.claude/agents/Explore.md`로 덮어써 sonnet으로 돈다(2026-11-09 사용자 지시). `CLAUDE_CODE_SUBAGENT_MODEL`은 쓰지 않으므로 다른 서브에이전트는 부모 모델을 따른다.

## 일하는 방식

- 코드 일은 worktree에서 커밋까지 한다. **push는 관리자가 한다**
- 커밋 전 `git status` — 남이 고친 것(커밋 안 된 변경 · 추적 안 하는 파일)은 건드리지 않고 **자기 파일만 `git add`**. 원본 폴더에는 추적 안 하는 평가 기록(`data/review/answer_eval_*` 등)이 쌓여 있다 — 지우거나 올리지 않는다
- 인계문이 가리키는 작업 자리(worktree)와 세션이 뜬 자리가 다르면 멈추고 알린다
- 막히면 혼자 우회하지 말고 멈추고 알린다
- 지워도 되는 것은 시험용으로 자기가 만든 것뿐이다. 지우기 · 덮어쓰기 전에 대상을 먼저 본다
- **push할 때 볼 것**(관리자):
  - 원격과 같은지(`git ls-remote origin refs/heads/main`)를 push 전에 먼저 본다
  - 바뀐 파일이 문서뿐인지(빌드를 건너뛰는지)
  - 바뀐 파일에 `db/migrations/**/*.sql`이 들었는지 — 들었으면 push 전에 사람에게 묻는다(아래)
  - push 뒤 FOREMAN 빌드 알림이 오는지. 「push했는데 빌드 없음」이면 Jenkins를 확인한다

## 사람 승인이 필요한 것

하지 않고 사용자에게 묻는다. 관리자가 대신 승인하지 않는다:
- 위 「하지 않는 것」(재부팅 · `~/.cloudflared/` · ollama 터널 · 비밀값 출력)은 그대로 하지 않는다
- **force push**(이력 다시 쓰기). Jenkins는 직전 성공 커밋과 새 커밋의 차이로 건너뜀을 정하므로(`Jenkinsfile` 「태그」) 직전 성공 커밋이 원격에서 사라지면 전체 빌드 → 태그 커밋 → 자동 Sync가 된다
- **마이그레이션이 든 push**(`db/migrations/petmint/` · `db/migrations/insurance_core/`의 새 `NNNN_*.sql`). 자동 Sync라 push가 곧 운영 DB 스키마 변경이고 되돌아가지 않는다. 사람이 지켜봐야 하는 스키마 변경은 자동 Sync를 먼저 끄고 넣는다(14번 1-25절, 끄는 명령은 infra `apps/petmint/README.md`)
- **설정 파일** — 이 저장소에서 그렇게 보는 것: `Jenkinsfile`(CI), `deploy/host/`(호스트 systemd 유닛 · 백업 스크립트), `.claude/`(세션 설정), `.env.example`(키 목록). 운영 플래그 ConfigMap은 infra 저장소다. 이 목록 밖의 것을 설정으로 볼지는 **정해지지 않음**
- **운영 DB** 쓰기 · 지우기 · 복구(`kubectl … exec mysql-0`, 12번 1-5절). 운영 DB의 질문 원문을 직접 읽지 않는다(2026-10-28 개인정보 — 16번 「운영 로그로 확인하는 방법」)
- **배포 되돌리기**(이미지 태그 · ConfigMap 키 되돌리기). 절차는 14번의 반영마다 적힌 「되돌리기」이고 클러스터 쪽은 인프라 관리자가 한다. 이 저장소용 한 벌짜리 되돌리기 런북은 없다 — 둘지는 **정해지지 않음**
- `sudo`가 필요한 호스트 명령(`deploy/scripts/host-*.sh`, systemd 유닛 넣기 등) — 직접 치지 않고 사용자에게 한 줄로 알린다

## 시험 DB

2026-11-13 사실만 적는다. **어떻게 할지는 정해지지 않음.**

- `tests/`의 `test_admin` · `test_auth` · `test_rule_report`의 DB 쪽 시험은 `PETMINT_DB_TESTS=1`일 때만 돈다(`unittest.skipUnless`, 기본은 건너뜀)
- 켜면 시험 전용 DB가 아니라 **로컬 개발 DB(호스트 도커 `mysql`, 127.0.0.1:3306의 `petmint` · `petmint_core`)에 직접 쓴다** — 가상 직원으로 세션 · 계정 · 열람 기록을 만들었다 지운다(`DELETE FROM sessions/turns/feedback/accounts/admin_views …`)
- 개발 DB는 평가 · 측정 기록이 쌓인 자리다(12번 1-5절 — 주 1회 `deploy/host/dev-mysql-backup.sh`가 뜬다). 시키지 않았으면 켜지 않는다

## 비밀값

- 토큰 · DB 암호 · 자격 증명을 화면 · 로그 · 커밋에 내지 않는다. `.env`는 열지 않고 키 이름은 `.env.example`로 본다. 비밀값이 든 파일은 Edit · Write로 고치지 않는다
- 값이 있는지는 개수로만 센다 — `/usr/bin/grep -c`. 셸의 `grep`은 CC 실행 파일에 기대는 함수라 CC가 스스로 업데이트하는 순간 실패한다(개수 0이 못 센 것일 수 있다)
- DB 접속은 모두 환경변수(`db/conn.py` — 개발은 루트 `.env`, 운영은 K8s Secret이 같은 이름). 클러스터 Secret은 사람이 만든다(infra `apps/petmint/README.md`)

## 문서 자리

- `docs/README.md` — 문서 표와 이름 규칙. 설계 문서(`requirements.md` · `pipeline.md` · `02_pipeline/00~16`)는 **저장소가 원천, Notion은 사본**(2026-10-18~)
- 진실의 원천 순서는 **코드 → docs → Notion**이다 — 코드와 docs가 다르면 코드가 맞고 docs를 고친다. Notion은 docs를 따라간다(2026-11-09 사용자, FOREMAN 교장 노트 510 · dispatch #91)
- 설계 문서 20개는 push 30분 뒤 FOREMAN이 Notion에 옮긴다(2026-11-09~, `origin/main` 기준). 파일을 옮기거나 이름을 바꾸면 짝이 끊긴다 — `git mv` · 이름 변경은 FOREMAN과 먼저 맞춘다
- `docs/TODO.md`(남은 일) · `docs/next_rebuild.md`(재학습 계획) · `docs/ops/`(배포기록 · 모드검증 · 저녁실행) · `docs/img/`
- `data/review/` — 평가 · 검수 · 측정 기록(`answer_eval_<날짜>_<시각>_…md` 등). 추적하는 것과 원본 폴더에만 있는 것이 섞여 있다
- `KNOWN_ISSUES.md` — 알려진 문제
- 바꾼 설계는 그 단계 문서에 날짜와 함께 적고, 무엇을 고쳤는지(파일 · 절) 알린다

## 커밋 메시지

런슈즈 · FOREMAN · 인프라와 같은 규칙을 쓴다(2026-11-13 사용자 결정).

꼴: `타입: 설명`. 범위 표시(`타입(범위):`)는 쓰지 않는다. 타입은 아래 열한 개뿐이다.

| 타입 | 쓰는 곳 |
| --- | --- |
| feat | 새 기능 |
| fix | 버그 고침 |
| docs | 문서만 |
| refactor | 동작은 그대로, 구조만 바꿈 |
| perf | 빠르게 만든 것 |
| test | 시험 추가 · 고침 |
| ops | 배포 · 운영 · 호스트 서비스 |
| build | 빌드 · 의존성 |
| ci | CI 설정(`Jenkinsfile`) |
| chore | 나머지 잡일 |
| revert | 되돌리기 |

- 제목(설명)은 한글로, 50자 안, 마침표 없이
- 제목과 본문에 em dash(`—`)와 가운뎃점(`·`)을 쓰지 않는다
- 본문은 한 줄 비우고 자연어 문장으로 쓴다. 처음 보는 사람이 읽어도 알게, 무엇을 했는지보다 왜 그렇게 했는지를 쓴다(무엇은 diff가 말한다)
- 줄임말과 숫자 코드(단계 문서 번호 · 절 번호 · 세션 번호 · dispatch 번호 등)는 그대로 두지 말고 풀어서 쓴다
- 한 줄에 안 들어가면 커밋을 나눈다. 메시지가 길다는 것은 커밋이 크다는 뜻이다
- 예전에 쓰던 review · eval · style · exp · deploy 타입은 새 커밋에 쓰지 않는다 — 위 열한 개 중 가장 가까운 것을 고른다
- 이 저장소에는 기계가 만드는 커밋이 없다(Jenkins 이미지 태그 커밋은 인프라 저장소에 들어간다)
- 지난 커밋: 2026-11-13 `origin/main` 210개(9c57673까지)를 셌다. 모두 사람(ronanlabs) 커밋이고, em dash나 가운뎃점이 든 것 197개(제목에 든 것 173개), 범위 표시 75개, 표 밖 타입 19개(review 6 · eval 4 · style 4 · deploy 3 · exp 2), 타입 없는 꼴 36개. 지난 메시지를 고칠지는 따로 정한다(지금은 고치지 않는다)

## 공통 규칙

- 항상 한국어로 답하고 쓴다
- 파일은 Edit · Write로 고친다 — `sed -i` · `perl -i` · heredoc 덧붙이기(`cat >> f <<EOF`) · `tee` · `cp`로 넣기 · `python -c`로 쓰기를 저장소 파일을 고치는 데 쓰지 않는다. 읽기만 하는 것(`sed -n` · `grep` 등)은 괜찮다. 임시 파일은 세션 스크래치에
- 다른 저장소(foreman · runshoes · ronanlab-infra · model-service)는 읽기만 한다. 그쪽 일은 그 프로젝트 관리자에게 부탁한다(아래)

## 알림

텔레그램 알림은 FOREMAN 브리지가 턴이 끝날 때 보낸다(Stop hook, 접두어 `[펫퍼민트]`, 2026-11-02부터). 이 세션에서 직접 보내지 않는다 — `scripts/notify-telegram.sh`는 지웠다.
규칙은 `~/AI_programming/foreman/config/notify.toml`.

## 관리자

- 이 저장소 관리자는 원본 폴더 `~/AI_programming/petmint-rag-chatbot`의 `main`에서 도는 역할 manager 세션 하나다(2026-11-13 사용자 결정)
- FOREMAN API는 이 프로젝트 토큰으로만 부른다: `T=$(/usr/bin/grep -E '^FOREMAN_TOKEN_PETMINT_RAG_CHATBOT=' ~/AI_programming/foreman/.env.project_tokens | cut -d= -f2-)` — 셸 변수로만 쓰고 값은 화면 · 로그 · 커밋에 내지 않는다. `-H "Authorization: Bearer $T"`로 싣는다. 이 토큰은 펫퍼민트 세션 · 방 · 게시 API만 연다
  - 토큰 파일: 있음(2026-11-13 확인 — 권한 600, 소유 kopo17, `FOREMAN_TOKEN_PETMINT_RAG_CHATBOT=` 줄 1개)
- 다른 프로젝트에 부탁: `curl -s -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"text": "…"}' http://127.0.0.1:8000/api/managers/<프로젝트>/ask`. 관리자가 없으면 사람에게 텔레그램으로 간다. 클러스터 일은 인프라(`ronanlab-infra`)에 부탁한다
- 작업 세션의 보고 · 물음은 관리자에게만 간다. 관리자는 사람에게 올릴 것을 `POST /api/sessions/{자기 세션 id}/escalate` `{"kind": "report"|"question", "text": "…"}`로 올린다(프로젝트 토큰). 응답 글로 쓰기만 하면 사람 화면에도 알림에도 뜨지 않는다. 물음은 바로 알림, 보고는 21:00 묶음(펫퍼민트는 2026-11-13부터 묶음이 켜져 있다 — `notify.toml`)
- 교장이 넘긴 계획(입력 칸에 「[교장 계획 #N …]」)은 고칠 것이 없으면 적힌 명령(`/api/foreman/start` `{"dispatch_id": N, "use_saved": true}`)으로 띄운다. 틀렸으면 띄우지 말고 사람에게 묻는다
- 개발 자원(로컬 DB `mysql` · Ollama · Milvus · search-service · GPU)은 호스트에 하나라 worktree 둘이 동시에 쓰면 겹칠 수 있다 — 「한 번에 한 세션」 규칙을 둘지는 **정해지지 않음**
