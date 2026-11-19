<!--
다루는 곳: Dockerfile, .dockerignore, Jenkinsfile, app/config.py, app/main.py, app/services/policy_data.py, app/fixtures/customers.example.json, db/conn.py, db/bootstrap.py, db/migrate.py, db/employees.py, db/rule_report.py, db/seed_insurance_core.py, db/migrations/, db/fixtures/employees.json, deploy/host/petmint-search.service, deploy/scripts/host-nfs-setup.sh, search_service/, data/model_client.py, scripts/search_parity.py, scripts/rollout_measure.sh, scripts/rollout_table.py, scripts/coverage_measure.sh, scripts/coverage_chain.sh, scripts/coverage_table.py, scripts/crowding_count.py, scripts/pool_chain.sh, scripts/sibling_sim.py, scripts/offtarget_probe.py, scripts/rejudge_chain.sh, tests/test_coverage_code.py, tests/test_rule_first.py
읽은 커밋: 6710b83
-->
> 상태: 운영 중. 이미지·CI는 2026-10-15, 클러스터 이주·ArgoCD는 2026-10-16, App of Apps는 2026-11-02, GitHub 웹훅은 2026-11-03 완료. ArgoCD 자동 Sync는 2026-11-11(1-15절). 남은 것은 4절의 한계. [code:Dockerfile] [code:Jenkinsfile] [c:afefd07] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/06_jenkins.md:448, docs/history/build_log/04_argocd.md:377, :379, bootstrap/root-app.yaml:1, apps/petmint/app.yaml:4-6 -->
> search-service는 호스트 systemd 유닛 `petmint-search`(192.168.122.1:8100)로 돌고, 클러스터 WS는 실제 답변을 돌려준다. 검색 모델(KURE · 리랭커)은 2026-11-11부터 공용 model-service(192.168.122.1:8200)에 있다(1-16절). [code:deploy/host/petmint-search.service:1-2] [code:deploy/host/petmint-search.service:33] [code:search_service/main.py:39-41] [c:0e31e94] <!-- 2026-11-19 잼: 공개 주소 체험 로그인으로 사내규정 질문 1회를 WS로 보내 답이 옴(코드 답 경로라 생성 모델과 검색은 타지 않음), curl 로 192.168.122.1:8100/health 와 :8200/health ok -->

#### 0. 한 줄 요약

GPU를 쓰는 것은 호스트에 남기고 나머지를 Pod로 올린다. **약관과 고객 데이터는 이미지에 담지 않는다** — 이미지가 레지스트리를 거쳐 도는 동안 데이터는 클러스터 안에만 있어야 한다.

---

#### 1. 최종 설계

#### 1-1. 무엇을 컨테이너로 만드는가

| 프로세스 | 위치 | 이유 |
| --- | --- | --- |
| Ollama | GPU 호스트 | 모델 추론에 GPU [code:app/config.py:66] |
| model-service(공용) | GPU 호스트 | KURE 임베딩 + bge-reranker가 GPU. ✓ 호스트 systemd `model-service`(192.168.122.1:8200, 2026-11-11부터). 런슈즈 챗봇도 같이 쓴다. 저장소 `~/AI_programming/model-service`(1-16절) [code:deploy/host/petmint-search.service:2] [code:deploy/host/petmint-search.service:33] [code:search_service/main.py:12-15] [c:0e31e94] <!-- model-service 확인(2026-11-19): ~/AI_programming/model-service/model_service/main.py:32, systemctl status model-service 로 2026-11-11 17:34:19부터 active. 런슈즈는 runshoes chatbot/search/embed.py:3, :18 이 MODEL_SERVICE_URL 을 씀(읽기만) --> |
| search-service | 호스트 | BM25 · Milvus 조회 · 정렬. 모델은 model-service를 부른다 — 2026-11-11부터 GPU를 쓰지 않는다. ✓ 호스트 systemd `petmint-search`(192.168.122.1:8100, 2026-11-02부터 유닛). 코드는 `search_service/` [code:search_service/main.py:1-21] [code:deploy/host/petmint-search.service:1-5] [code:deploy/host/petmint-search.service:20-48] |
| Milvus | 호스트 도커 → Pod 가능 | GPU를 쓰지 않는다. search-service와 함께 판단한다 [code:deploy/host/milvus/docker-compose.yml] |
| MySQL | 호스트 도커 → Pod | GPU를 쓰지 않는다(12번 1-2절). ✓ 2026-10-16 Pod로 이주 [docs:02_pipeline/12_data_storage.md] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/mysql/statefulset.yaml (65b9abb, 2026-10-16), docs/history/build_log/07_project_deploy.md:5 --> |
| FastAPI + React 빌드물 | Pod | GPU를 쓰지 않는다 [code:Dockerfile:12-47] |

**컨테이너화 대상은 FastAPI 앱과 React 빌드물뿐이다**(09번 1-15절). 둘을 한 이미지에 담는다 — FastAPI가 빌드물을 StaticFiles로 서빙하므로 Pod 하나로 끝난다. [code:app/main.py:96-98] [code:Dockerfile:37] [docs:02_pipeline/09_ui_design.md]

#### 1-2. 이미지

멀티스테이지로 만든다.

```
1단계  node:20-alpine     web/ 를 빌드해 dist/ 를 만든다 (npm ci → npm run build)
2단계  python:3.14-slim   앱과 1단계의 dist/ 만 담는다. 비root(uid 10001)로 실행
```

최종 이미지 **528MB**. node·npm·tsc는 남지 않는다. [code:Dockerfile:12-30] (2026-10-15~2026-10-18 사이) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답), 이미지 크기는 Harbor에서 봐야 함 -->

**이미지에 담는 것과 담지 않는 것**

| 담는다 | 담지 않는다 |
| --- | --- |
| `app/`, `db/`, `data/*.py` | `data/chunks/`, `data/graph/` — 약관 [code:Dockerfile:34-36] [code:.dockerignore:22-24] |
| `web/dist/` (1단계 산출물) |  `app/fixtures/` 전체 — 고객 원장은 시드 Job이 DB에 넣는다 [code:Dockerfile:37] [code:.dockerignore:25-26] [code:db/seed_insurance_core.py:7-13] |
|  | `models/` (47GB), `notebooks/`, `data/faq/`, `data/finetune/` [code:.dockerignore:1] [code:.dockerignore:15-21] (2026-10-15 이전) |
|  | `.env` [code:.dockerignore:6-8] |

`.dockerignore`가 빌드 컨텍스트 단계에서 먼저 걸러낸다. 이미지에 안 들어가는 것과 빌드 과정에 아예 안 실리는 것은 다르다 — 후자여야 중간 레이어에도 남지 않는다. [code:.dockerignore:1-2]

#### 1-3. 데이터는 런타임에 붙인다

약관과 고객 데이터는 경로를 환경변수로 받아 런타임에 읽는다. [code:app/config.py:19-21]

| 변수 | 기본값 | 내용 |
| --- | --- | --- |
| `PETMINT_CHUNKS_DIR` | `data/chunks` | 약관 청크. `컨테이너에서는 /var/lib/petmint/chunks (Dockerfile ENV)` [code:app/config.py:20] [code:Dockerfile:40] |
| `PETMINT_GRAPH_DIR` | `data/graph` | 참조 그래프. `컨테이너에서는 /var/lib/petmint/graph (Dockerfile ENV)` [code:app/config.py:21] [code:Dockerfile:41] |

**없으면 기동이 실패한다.** `exit 3`과 함께 빠진 파일을 전부 밝히고, 파일이 있어도 청크가 비어 있으면 멈춘다. 조용히 0건이 되면 검색이 아무것도 못 찾는데 원인을 알 수 없다 — 09번 1-10절에서 로더가 `section_name` 불일치에 기동을 실패시키는 것과 같은 판단이다. [code:app/services/policy_data.py:28-43] [code:app/main.py:41] [docs:02_pipeline/09_ui_design.md] <!-- 공개 출처: https://raw.githubusercontent.com/encode/uvicorn/master/uvicorn/config.py 의 STARTUP_FAILURE = 3 과 server.py 의 sys.exit(STARTUP_FAILURE) (2026-11-19 확인) -->

개발 중에는 `docker run -v`로 호스트 경로를 붙이고, 클러스터에서는 **NFS 읽기 전용 PV**로 붙인다. 호스트의 `data/chunks`·`data/graph`·`app/fixtures`를 `/srv/nfs/petmint/`에 읽기 전용 bind mount하고 사설망(192.168.122.0/24)에만 NFSv4로 공유한다. 복사본이 없으므로 재색인해도 어긋나지 않는다. [code:Dockerfile:8-9] [code:deploy/scripts/host-nfs-setup.sh:7-17] [code:deploy/scripts/host-nfs-setup.sh:39] [c:afefd07]

- [ ]  **약관을 바꾸면 앱 재시작이 필요하다.** 파일은 Pod에서 바로 보이지만 앱이 기동할 때 메모리에 올린다. 재색인 뒤에는 `rollout restart`가 필요하다 [code:app/main.py:41] [code:app/services/policy_data.py:28-43]
- [ ]  **클러스터 DB는 픽스처 시드로 새로 시작했다.** 로컬 도커 MySQL의 개발 데이터는 옮기지 않았다

#### 1-4. 접속 정보는 전부 환경변수

| 변수 | 가리키는 곳 |
| --- | --- |
| `PETMINT_DB_HOST` / `PORT` / `NAME` / `USER` / `PASSWORD` | MySQL [code:db/conn.py:43-46] [code:app/config.py:26] |
| `PETMINT_MILVUS_URL` | Milvus [code:app/config.py:67] |
| `PETMINT_OLLAMA_URL` | GPU 호스트의 Ollama [code:app/config.py:66] |
| `PETMINT_SEARCH_URL` | GPU 호스트의 search-service. 지금 값은 `http://192.168.122.1:8100` [code:app/config.py:33] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml:26 --> |
| `PETMINT_WEB_DIST` | React 빌드물 경로 [code:app/config.py:24] |
| `PETMINT_CORE_DB_*` | 고객 원장(`insurance_core`). 실무에서는 다른 호스트일 수 있어 따로 둔다 [code:app/config.py:15-17] |
| `PETMINT_DEFAULT_AGENT` | 내부망 직접 접속처럼 Access 헤더가 없을 때 쓸 상담원 ID [code:app/config.py:83-85] |
| `PETMINT_TITLE_LLM` | 세션 제목을 LLM으로 지을지(0/1). 지금은 1(업무특화는 늘 첫 질문 첫 줄) [code:app/config.py:73-74] [code:app/services/titles.py:40] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml:67 --> |
| `PETMINT_MODEL_BASE` | 일반·사내규정 모드와 재작성기가 쓸 모델 이름 (기본 tri-7b). ✓ 이미지 빌드·태그 커밋·Sync 확인(2026-10-18) [code:app/config.py:70] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml:29 (키는 abf1758, 2026-10-18) --> |
| `PETMINT_MODEL_RAG` | 업무특화 모드가 쓸 어댑터 모델 이름 (기본 tri-7b-rag-1). ✓ 이미지 빌드·태그 커밋·Sync 확인(2026-10-18). 지금 값은 `kabyul-tri-7b-rag1-rebuild4-ckpt462`(Ollama에 있다) [code:app/config.py:71] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/configmap.yaml:30 (키는 abf1758, 2026-10-18) --> <!-- 2026-11-19 잼: docker exec ollama ollama list 에 kabyul-tri-7b-rag1-rebuild4-ckpt462 있음 --> |

DB 환경변수가 없으면 이름을 밝히며 기동이 실패한다. 코드에 접속 정보를 하드코딩하지 않는다(12번 1-2절). [code:db/conn.py:20-24] [code:db/conn.py:1-8] [docs:02_pipeline/12_data_storage.md]

**Pod에서 호스트를 가리키는 주소는 `localhost`가 아니다.** 클러스터가 VM 위에 있으므로 사설 네트워크의 게이트웨이 주소를 쓴다. Vagrantfile에 고정 IP가 박혀 있어 재부팅해도 바뀌지 않는다. [code:app/config.py:32-33] [code:search_service/main.py:39] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): cluster/Vagrantfile:4-9, :17, :39 (호스트 ~/k8s-cluster/Vagrantfile 과 같은 사본) -->

#### 1-5. 배포 흐름

```
GitHub (코드)
   ↓ push
Jenkins          이미지 빌드
   ↓ push
Harbor           이미지 저장소
   ↓
Jenkins          매니페스트의 태그를 새 버전으로 바꿔 push
   ↓
ArgoCD           변경을 보고 클러스터에 반영
   ↓ pull
Harbor           이미지를 당겨 Pod 교체
```

**앱 코드와 매니페스트를 다른 저장소에 둔다.** 한 저장소에 합치면 Jenkins가 태그를 바꿔 push할 때마다 빌드가 다시 돌아 무한루프가 된다. 매니페스트는 클러스터 공용 설정이 있는 `ronanlab-infra`의 `apps/petmint/`에 둔다(1-9절). [code:Jenkinsfile:12-13] [code:Jenkinsfile:60-61]

**이미지 태그에 버전을 박는다.** `latest`를 쓰지 않는다 — 롤링 중에 어느 Pod가 무엇을 부르는지 알 수 없게 된다(10번 1-9절). [code:Jenkinsfile:10] [code:Jenkinsfile:69] [docs:02_pipeline/10_consultation_flow.md]

push 하나로 **빌드 → Harbor → 매니페스트 태그 커밋 → 클러스터 반영**까지 자동으로 간다. 반영은 2026-11-10까지 ArgoCD에서 Sync를 눌러 했고, 매니페스트가 의도대로 들어가는 것을 확인한 뒤 2026-11-11 자동(`automated`)으로 바꿨다(1-15절). [code:Jenkinsfile:1] [code:Jenkinsfile:95-154] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app.yaml:4-6, :25-28 -->

ArgoCD는 매니페스트만 본다. 이미지는 각 노드의 kubelet/containerd가 Harbor에서 직접 당기고, 경로는 `/etc/hosts`에 박은 `192.168.122.240`(MetalLB VIP)이다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): cluster/Vagrantfile:32-36, platform/ingress-nginx/overlay/service-patch.yaml:11-12 -->

#### 1-6. 자동화 경로는 Access를 거치지 않는다

| 연결 | 어디로 | Access |
| --- | --- | --- |
| Jenkins → Harbor | 클러스터 내부 Service | 거치지 않음 [code:Jenkinsfile:8-9] |
| ArgoCD → Harbor | 부르지 않는다(ArgoCD는 매니페스트만 보고, 이미지는 노드가 Harbor에서 당긴다. 1-5절) | 해당 없음 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): ArgoCD가 Harbor에 붙는 설정은 인프라 저장소에 없음. 클러스터 안 Pod가 harbor.ronanlab.dev 를 ingress-nginx 내부 Service로 푸는 것은 platform/coredns/configmap.yaml:3-5, :22-25 --> |
| ArgoCD → GitHub | 공개 인터넷 | 무관 |
| GitHub → ArgoCD · Jenkins 웹훅 | 공개 호스트명의 웹훅 경로만 | Bypass — 서명(HMAC SHA-256)이 지킨다(1-12절, 13번 1-3절) [code:Jenkinsfile:3] [docs:02_pipeline/13_access_and_tunnel.md] <!-- 확인 못 함: Cloudflare 대시보드 설정이라 저장소와 서버에서 읽을 수 없음 --> |
| 사람 → ArgoCD·Harbor·Jenkins | 브라우저 | Access(운영자만) [docs:02_pipeline/13_access_and_tunnel.md] |

기계가 공개 호스트명으로 나갔다 들어오면 Access에 막힌다. 그래서 자동화는 전부 내부 주소로 간다. 사람이 브라우저로 들어가는 경로만 Access가 막는다(13번 1-3절). [docs:02_pipeline/13_access_and_tunnel.md]

> Ollama는 예외다. `ollama.ronanlab.dev`(호스트 터널 `ollama-tunnel`, Service Token `ollama-school-pc`로만 통과 — 13번 1-3절)는 학교 PC가 클러스터 밖에서 부를 때의 경로다. 런슈즈·펫퍼민트 Pod는 이 터널을 쓰지 않는다. Pod는 사설 네트워크로 직접 호출한다 — 같은 물리 머신 안인데 Cloudflare 엣지를 왕복하면 스트리밍 토큰마다 지연이 쌓인다. [docs:02_pipeline/13_access_and_tunnel.md] [code:app/config.py:66] <!-- 확인 못 함: Cloudflare 대시보드 설정이라 저장소와 서버에서 읽을 수 없음, 호스트 ~/.cloudflared 는 열지 않음 -->
> 

#### 1-7. 클러스터 진입점 — MetalLB + cert-manager

노드가 Harbor에서 이미지를 당기려면 **표준 포트(443)가 실제로 열려 있어야 한다.** Harbor는 토큰 주소를 `externalURL + /service/token`으로 알려주는데 그 값에 포트가 없으므로 노드는 443으로 간다. NodePort(31925)로는 닿을 수 없다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/harbor/values.yaml:18, platform/coredns/configmap.yaml:5-7, platform/ingress-nginx/overlay/service-patch.yaml:1, :20-23 -->

MetalLB(L2)로 사설망에 VIP를 하나 두고, ingress-nginx를 LoadBalancer로 바꿔 그 VIP에 80·443을 연다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/metallb/pool.yaml:13-22, platform/ingress-nginx/overlay/service-patch.yaml:14-23 -->

| 항목 | 값 |
| --- | --- |
| VIP | 192.168.122.240 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/ingress-nginx/overlay/service-patch.yaml:12 --> |
| IP 풀 | .240~.250, `autoAssign: false` <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/metallb/pool.yaml:9-10 --> |
| 알림 인터페이스 | eth1 (사설망) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/metallb/pool.yaml:12, :21-22 --> |
| 기존 NodePort | 30517 / 31925 유지 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/ingress-nginx/overlay/service-patch.yaml:2, :19, :23 --> |
| 터널이 보는 곳 | ClusterIP — Service 타입을 바꿔도 영향이 없다 |

인증서는 cert-manager + Let's Encrypt **DNS-01**로 받는다. DNS-01이라 인바운드 포트를 열 필요가 없고, Cloudflare API 토큰(Zone·DNS·Edit / Zone·Zone·Read)만 있으면 된다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/cert-manager/cluster-issuer.yaml:13-19, platform/cert-manager/values.yaml:38, docs/history/build_log/02_metrics_storage_ingress.md:149 --> <!-- 확인 못 함: API 토큰 권한 범위는 Cloudflare 대시보드 설정이라 저장소와 서버에서 읽을 수 없음 -->

설정은 `ronanlab-infra/platform/` 아래에 둔다 — `metallb/`, `ingress-nginx/{base,overlay}/`, `cert-manager/`, `coredns/`. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/ 아래에 있음. 지금은 argocd, harbor, jenkins, versions.yaml 도 platform/ 아래(platform/versions.yaml) -->

**ingress-nginx는 kustomize 로 묶는다.** 업스트림 매니페스트를 base 에 원본 그대로 두고 Service 패치를 overlay 로 얹는다. base 만 apply 하면 NodePort 로 돌아가므로 양쪽 주석에 "overlay 만 apply"를 적어 두었다. 패치에 `protocol: TCP` 가 없으면 Service ports 의 병합 키(port+protocol)가 맞물리지 않아 nodePort 가 무작위로 뽑힌다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/ingress-nginx/base/kustomization.yaml:1-4, platform/ingress-nginx/overlay/kustomization.yaml:1-2, platform/ingress-nginx/overlay/service-patch.yaml:3, :18, :22 -->

#### 1-8. 파이프라인 — CI (2026-10-15)

| 항목 | 값 |
| --- | --- |
| 빌드 | BuildKit rootless v0.33.1. 특권 컨테이너 대신 seccomp·AppArmor만 푼다 [code:Jenkinsfile:6-7] [code:Jenkinsfile:28-39] |
| 태그 | 커밋 해시(예: 4e81fa250169). latest를 쓰지 않는다 [code:Jenkinsfile:10] [code:Jenkinsfile:69] |
| 트리거 | ~~SCM 폴링 2분. webhook 은 Access 에 막힌다~~ 2026-11-03부터 GitHub 웹훅(githubPush) + 폴링 15분 안전망 — 1-12절 [code:Jenkinsfile:3] [code:Jenkinsfile:173-178] |
| Jenkins 설정 | JCasC + job-dsl. 자격 증명과 Job 을 Helm values 가 만든다 [code:Jenkinsfile:3] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/jenkins/values.yaml:54-110, :182 --> |
| Harbor 계정 | robot 둘로 나눔 — jenkins(push+pull), pull(pull 전용, petmint 네임스페이스의 imagePullSecret harbor-pull) [code:Jenkinsfile:100-101] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/05_harbor.md:133, platform/jenkins/values.yaml:30, :75-76, apps/petmint/scripts/create-secrets.sh:8, :31-36, apps/petmint/app/deployment.yaml:34 --> <!-- 확인 못 함: jenkins robot 의 pull 권한은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) --> |

**Jenkins 도 매니페스트로 남긴다.** UI 에서 자격 증명과 Job 을 만들면 Jenkins 안에만 남아 Pod 를 다시 만들면 사라지고, 무엇을 어떻게 설정했는지 기록도 안 남는다. MetalLB·cert-manager·ingress 를 전부 `ronanlab-infra` 에 남겨 두고 Jenkins 만 UI 로 하면 거기만 구멍이 된다. [code:Jenkinsfile:3]

**robot 계정을 둘로 나눈 이유**는 역할이 다르기 때문이다. Jenkins 는 push 하고 노드는 pull 만 한다. 노드 Secret 에 push 권한이 들어가면 Pod 가 레지스트리를 덮어쓸 수 있고, 하나를 바꿀 때 다른 쪽까지 영향받는다.

- [x]  ~~앱 리포의 어떤 푸시에도 빌드가 돈다. docs만 고쳐도 새 이미지와 배포 커밋이 생긴다.~~ 2026-11-09 해결 — 바뀐 파일(직전 성공 빌드의 커밋 → 이번 커밋)이 모두 `docs/`·`data/review/`·루트 `*.md`이면 빌드는 SUCCESS로 끝나되 이미지 빌드·태그 커밋을 건너뛴다(빌드 설명 "건너뜀 — 문서만", FOREMAN 끝 알림 `"skipped": true`). 손으로 누른 빌드, 직전 성공 커밋이 없거나 못 찾을 때는 늘 빌드한다. 이 경로들은 Dockerfile이 COPY하지 않고 `.dockerignore`로도 뺀다(`Jenkinsfile` 머리 주석) [code:Jenkinsfile:14-18] [code:Jenkinsfile:71-89] [code:Jenkinsfile:180-184] [code:.dockerignore:30] [code:.dockerignore:32-34] [c:9a72e2a]

#### 1-9. GitOps — ArgoCD (2026-10-16)

**매니페스트 저장소는 `ronanlab-infra` 를 쓴다.** 새 저장소를 만들지 않는다. [code:Jenkinsfile:60-61]

```
ronanlab-infra/
  platform/        클러스터 공용
    metallb/  cert-manager/  ingress-nginx/  coredns/
    argocd/  harbor/  jenkins/
  apps/
    petmint/       앱 매니페스트
    runshoes/      런슈즈 앱 매니페스트
```

| 항목 | 값 |
| --- | --- |
| Sync 방식 | 자동(2026-11-11~, 그 전 수동 — 1-15절). prune·selfHeal 꺼두고 finalizer 없음 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app.yaml:4-8, :25-28 --> |
| Namespace | ArgoCD 관리에서 제외. CreateNamespace=false <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app.yaml:9, :29-30 --> |
| 인증 | deploy key 둘 — argocd-read(읽기), jenkins-write(쓰기) [code:Jenkinsfile:124] [code:Jenkinsfile:128] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): scripts/make-deploy-keys.sh:29, :39, :50-51, apps/petmint/app.yaml:10 --> <!-- 확인 못 함: GitHub 쪽 키 등록은 GitHub 저장소 설정이라 저장소와 서버에서 읽을 수 없음 --> |
| 매니페스트 수신 | Jenkinsfile 에서 `sh 'git clone'` 으로 받는다 [code:Jenkinsfile:12-13] [code:Jenkinsfile:137] |
| 조회 주기 | 3분 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): bootstrap/root-app.yaml:3, docs/history/build_log/04_argocd.md:379 --> |

**App of Apps (2026-11-02).** Application 을 손으로 `kubectl apply` 하지 않는다. 루트 `bootstrap/root-app.yaml` 하나만 사람이 넣었고, 루트가 `apps/*/app.yaml` 을 읽어 Application 을 만든다. 새 앱은 `apps/<이름>/` 에 `app.yaml` + 매니페스트를 넣고 push 하면 된다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): bootstrap/root-app.yaml:1-4 -->

```
ronanlab-infra/
  bootstrap/root-app.yaml     루트 — 이것만 사람이 kubectl apply (한 번)
  apps/                       ArgoCD 가 배포하는 것. 폴더마다 app.yaml + 매니페스트
    cloudflared/  petmint/  runshoes/  monitoring/(자리만 — 루트 exclude)
  platform/                   ArgoCD 밖 기반(ArgoCD 보다 먼저 깔았다)
    argocd/ingress.yaml  cert-manager/  coredns/  ingress-nginx/  metallb/  harbor/  jenkins/
```

| 루트 설정 | 값 · 이유 |
| --- | --- |
| 읽는 것 | `apps/` recurse, include `*/app.yaml` — Application 객체만. 앱 리소스의 Sync 방식은 각 app.yaml 이 정한다(cloudflared 수동, runshoes · petmint · monitoring 자동 — 뒤 둘은 2026-11-11부터. harbor-backup 도 2026-11-10부터 자동) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): bootstrap/root-app.yaml:6, :25-28, apps/harbor-backup/app.yaml:2, :19-22 --> |
| Sync | 자동, prune 끔(폴더를 지워도 Application 이 남는다), selfHeal 끔, finalizer 없음(루트를 지워도 자식 · 리소스가 남는다) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): bootstrap/root-app.yaml:11-12, :38-41 --> |
| 자식 syncPolicy | 덮지 않는다(ignoreDifferences + RespectIgnoreDifferences) — 자동 Sync 켜고 끄기는 지금처럼 클러스터에서 patch 가 스위치다. 그러지 않으면 Jenkins 태그 커밋 하나에 루트가 다시 Sync 해 스키마 배포 중 꺼 둔 자동 Sync 를 도로 켠다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): bootstrap/root-app.yaml:8-10, :33-43 --> |
| monitoring | app.yaml 자리만. 루트 `exclude: 'monitoring/app.yaml'` 한 줄을 지우면 만들어진다(2026-11-02 판. 2026-11-10에 그 줄을 지워 지금은 monitoring Application이 있다) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): bootstrap/root-app.yaml:29, apps/monitoring/app.yaml:2, docs/history/build_log/04_argocd.md:381 --> |

배포는 이제 **ArgoCD 가 독점한다.** `kubectl apply` 나 `apply.sh` 를 쓰면 상태가 엇갈린다 — 실제로 `kubectl scale --replicas=3` 을 하자 즉시 OutOfSync 로 잡혔고 Sync 하니 Git 값인 2 로 돌아왔다. (2026-10-16 기준) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답), 다시 재려면 서비스가 끊길 수 있어 사람 승인이 필요함 -->

- [ ]  **ArgoCD는 `ssl-passthrough`를 뺀 상태다.** 나중에 그 플래그를 켜면 붙인 인증서가 쓰이지 않는다


#### 1-10. 운영 플래그 반영

플래그는 코드 기본값을 바꾸지 않고 ConfigMap에서만 켠다 — 되돌릴 때 ConfigMap만 고치면 된다. 모델(rebuild4)·고객 사실·숫자 가드레일은 그대로다. [code:app/config.py:34-41] [code:app/config.py:39] [code:app/config.py:65]

**반영 순서 — 앱 먼저, infra 나중.** infra를 먼저 올리면 옛 이미지가 v3 청크 파일을 읽으면서 검색은 옛 Milvus 컬렉션으로 해, 검색 결과와 청크 파일이 어긋난다. [code:app/services/retrieval.py:53]

1. petmint 저장소 push → Jenkins가 이미지를 빌드하고 ronanlab-infra에 태그 커밋을 올린다 [code:Jenkinsfile:95-151]
2. ronanlab-infra에서 `git pull --rebase`로 그 태그 커밋을 받은 뒤 ConfigMap 변경을 push
3. ArgoCD Sync → 초기화 Job(청구 이력 테이블 0002_claims, 비어 있을 때만 시드) → 앱 롤링 재시작. 이미지 태그가 같이 바뀌므로 `rollout restart`는 따로 하지 않는다 [code:db/migrations/insurance_core/0002_claims.sql] [code:db/seed_insurance_core.py:9-13] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/jobs/init-db.yaml:15-17, :42, apps/petmint/app/deployment.yaml:15 -->

옛 이미지는 `PETMINT_AGE_CODE`를 모르므로 먼저 들어가도 해가 없다. 이미지 태그가 함께 바뀌면 재시작은 따로 하지 않는다. ConfigMap만 바뀌는 경우에는 Sync 뒤 `kubectl -n petmint rollout restart deploy/petmint-app`이 필요하다. [code:app/config.py:46-47]

평가 전용 `PETMINT_TODAY`는 운영 ConfigMap에 넣지 않는다. 운영은 실제 날짜를 쓴다. [code:app/config.py:62-64]

집계는 Pod 안에서 숫자만 낸다(질문·답 글, 세션·상담원·고객 값은 어떤 옵션으로도 찍지 않는다 — 16번 5절): [code:db/rule_report.py] [docs:02_pipeline/16_code_answers.md]

```bash
kubectl -n petmint exec deploy/petmint-app -- python -m db.rule_report                                       # 0008 적용 시각부터
kubectl -n petmint exec deploy/petmint-app -- python -m db.rule_report --since 2026-11-01 --until 2026-11-08 --json
```

모드별 턴·코드 답·모델 거절, 규칙별 발동·되묻기·👍/👎·다음 턴(없음/코드/모델(거절)/실패), 모델이 거절한 턴의 놓침 후보 갈래(병명 되묻기 앞 조건 중 어디서 막혔나, 상해 낱말, 사내규정 개인화 주제 낱말)를 낸다. 모델은 부르지 않는다. **되돌리기:** 이미지만 되돌리면 된다 — 칸은 NULL 허용이라 옛 이미지가 쓰지 않아도 그대로 돈다. [code:db/rule_report.py] [code:db/migrations/petmint/0008_turn_code_rule.sql] [c:82d86f0]

#### 1-11. 앱 로그인

앱 로그인을 켤 때(`PETMINT_AUTH: "app"`): [code:app/config.py:87-89]

| ConfigMap 키 | 값 | 비고 |
| --- | --- | --- |
| `PETMINT_AUTH` | `app` | 사번·비밀번호 로그인. 되돌리면(`access`) 로그인 화면이 사라지고 Access 헤더가 신원이다 [code:app/config.py:83-91] |
| `PETMINT_COOKIE_SECURE` | 기본 `1` | HTTPS(Access·ingress TLS) 뒤라 그대로. 로컬 http 개발만 `0` [code:app/config.py:93] |
| `PETMINT_ALLOWED_ORIGINS` | 기본은 개발 서버 둘 | 같은 Host의 Origin은 늘 허용 — 운영 도메인은 넣지 않아도 된다 [code:app/config.py:99-102] [code:app/deps.py:44-47] |

첫 관리자는 사람이 Pod 안에서 만든다(비밀번호는 화면에 안 보이게 두 번 묻는다). [code:db/employees.py:5] [code:db/employees.py:24-29]

```bash
kubectl -n petmint exec -it deploy/petmint-app -- python -m db.employees add E2001003 --role 관리자   # 권태호(가상)
kubectl -n petmint exec -it deploy/petmint-app -- python -m db.employees list
```

Access 정책은 그대로 둘 수 있다(로그인 두 번). 외부 데모로 열 때는 petmint 호스트의 Access 정책을 풀어야 앱 로그인 화면이 바로 보인다 — 이것은 Cloudflare 대시보드에서 사람이 한다(13번 1-3절). [docs:02_pipeline/13_access_and_tunnel.md] <!-- 확인 못 함: Cloudflare 대시보드 설정이라 저장소와 서버에서 읽을 수 없음 -->

---

#### 1-12. GitHub 웹훅 — ArgoCD · Jenkins (2026-11-03)

push 하면 주기 조회(ArgoCD 3분 · Jenkins 폴링 2분)를 기다리지 않고 바로 반영된다. [code:Jenkinsfile:3] [c:62216c0]

| | ArgoCD | Jenkins |
| --- | --- | --- |
| 받는 곳 | `https://argocd.ronanlab.dev/api/webhook` | `https://jenkins.ronanlab.dev/github-webhook/`(끝 `/`까지) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/06_gitops.md:16, platform/jenkins/values.yaml:92 --> <!-- 확인 못 함: GitHub 쪽 웹훅 등록은 GitHub 저장소 설정이라 저장소와 서버에서 읽을 수 없음 --> |
| 거는 저장소 | `ronanlab-infra`(ArgoCD 가 보는 저장소는 이것뿐) | `petmint-rag-chatbot` · `runshoes` <!-- 확인 못 함: GitHub 저장소 설정이라 저장소와 서버에서 읽을 수 없음 --> |
| 시크릿 | `argocd/argocd-secret` 키 `webhook.github.secret` | Secret `jenkins/github-webhook-secret` → JCasC 자격 증명 `github-webhook-secret`, `hookSecretConfigs` SHA256 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/04_argocd.md:59, platform/jenkins/values.yaml:45-47, :89-91, :96-98 --> |
| 하는 일 | 저장소가 맞는 앱을 refresh 만 한다. Sync 는 각 앱 설정대로 | 저장소 URL 이 맞는 잡에 SCM 조회 한 번(githubPush). 안전망 pollSCM 15분 [code:Jenkinsfile:3] [code:Jenkinsfile:173-178] |

- 시크릿은 둘로 나눴다(ArgoCD 하나, Jenkins 하나). 하나가 새도 다른 쪽은 받지 않는다 — 서로의 값으로 서명한 요청이 거부되는 것을 확인했다 (2026-11-03 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 두 시크릿이 다른 값 docs/history/build_log/04_argocd.md:59, docs/history/build_log/06_jenkins.md:76, :470 --> <!-- 확인 못 함: 서로의 값으로 서명한 요청이 거부된 시험 결과는 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->
- **ArgoCD 는 웹훅 시크릿을 argocd-server 가 뜰 때 한 번 읽는다**(v2.13 `NewHandler`). 키를 넣은 뒤 재시작 전에는 같은 본문이 한 번 맞게 들어온 뒤 틀린 서명(`00`)도 200 으로 처리됐다. `rollout restart deploy/argocd-server` 뒤에는 맞는 서명 10/10, 틀린 · 다른 값 · 무작위 · 없는 서명 0/40 통과(Jenkins 도 같은 시험 10/10 · 0/40). **시크릿을 바꾸면 argocd-server 를 다시 띄운다** (2026-11-03 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/04_argocd.md:387-391, docs/06_gitops.md:96, 호스트 ~/k8s-cluster/backup/2026-11-03-webhooks/ROLLBACK.md:17-18 -->
- Access 는 웹훅 경로만 Bypass 한다(13번 1-3절). 되돌리기와 측정 기록은 호스트 `~/k8s-cluster/backup/2026-11-03-webhooks/` [docs:02_pipeline/13_access_and_tunnel.md] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 호스트 백업 폴더 ~/k8s-cluster/backup/2026-11-03-webhooks/ROLLBACK.md 있음 --> <!-- 확인 못 함: Access Bypass 는 Cloudflare 대시보드 설정이라 저장소와 서버에서 읽을 수 없음 -->

#### 1-13. Jenkins 플러그인 버전 고정 (2026-11-03)

차트 기본(`installLatestPlugins: true` → `jenkins-plugin-cli --latest true`)은 재시작할 때마다 의존 플러그인을 최신으로 올린다. 빌드가 어느 날 깨져도 무엇이 바뀌었는지 알 수 없어서 고정했다(helm revision 7, infra 770979a). <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/jenkins/values.yaml:172-173, 호스트 ~/k8s-cluster/backup/2026-11-03-jenkins-pin/ROLLBACK.md:3. 그때 해시 5f4c6c3 은 지금 main 770979a -->

| values | 값 | 뜻 |
| --- | --- | --- |
| `installPlugins` | 73개 전부 `이름:버전` — 직접 쓰는 6개 + 의존 67개 | 실행 중이던 목록 그대로(pluginManager API에서 뽑았다) (2026-11-03 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/jenkins/values.yaml:177-184, docs/history/build_log/06_jenkins.md:33, 호스트 ~/k8s-cluster/backup/2026-11-03-jenkins-pin/plugins-rev6.txt --> |
| `installLatestPlugins` | false | 목록에 없는 의존이 생기면 최신이 아니라 요구 최소 버전. 목록이 빠짐없어 받을 것이 없다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/jenkins/values.yaml:175 --> |
| `overwritePlugins` | true | 기동마다 `JENKINS_HOME/plugins` 를 비우고 목록으로 다시 채운다 — 설치 = 목록 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/jenkins/values.yaml:176 --> |

- **찾은 것:** 그 전에는 `JENKINS_HOME/plugins` 에 `.jpi.pinned` 표시가 있어 받아 둔 새 버전이 적용되지 않는 경우가 있었다(asm-api). 받은 것(ref)과 실행 중인 것이 달라 "무엇이 깔려 있나"를 디스크로는 알 수 없었다 — 이제 overwritePlugins 로 둘이 같다. 목록은 디스크가 아니라 API(`/pluginManager/api/json`)로 뽑는다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 설치 = 목록은 platform/jenkins/values.yaml:176 --> <!-- 확인 못 함: .jpi.pinned 표시는 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->
- **되돌리기:** 고정한 뒤로는 `helm rollback <이전 rev>` 가 플러그인 버전까지 되돌린다(overwritePlugins). 고정 전(rev6)으로 되돌리면 다시 `--latest true` 라 그때의 최신으로 오른다 — rev6 때 파일 그대로가 필요하면 호스트 `~/k8s-cluster/backup/2026-11-03-jenkins-pin/` 의 `JENKINS_HOME/plugins` 묶음(ROLLBACK.md) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/jenkins/values.yaml:176, 호스트 ~/k8s-cluster/backup/2026-11-03-jenkins-pin/ROLLBACK.md 와 jenkins-home-plugins-rev6.tgz -->
- 플러그인을 올릴 때: 올릴 것과 그 의존을 목록에서 같이 고치고 helm upgrade. 재시작마다 73개를 업데이트 센터에서 다시 받는다(전에도 ref 는 emptyDir 이라 매번 받았다) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/jenkins/values.yaml:174 -->

#### 1-14. 가용성 — 워커 4대 · 8GB, 노드가 하나 죽으면 (2026-11-10)

인프라 가용성 묶음 1(사용자 2026-11-10). 상세 원본은 ronanlab-infra `docs/history/build_log/08_scale_out.md` — 여기는 펫퍼민트에 닿는 것만 둔다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/02_availability.md 는 2026-11-12 docs/08_scale_out.md, 2026-11-16 docs/history/build_log/08_scale_out.md 로 옮겨짐(그 파일 :8) -->

```
m-k8s 4GB (컨트롤 플레인)   w1 · w2 · w3 4 → 8GB   w4 8GB(새로)   — VM 합 16 → 36GB
```

| 바뀐 것 | 펫퍼민트에 |
| --- | --- |
| 워커 3 → 4대 | 앱 Pod 둘(required anti-affinity)의 롤링 2+1이 워커 하나가 빠진 동안에도 된다 — 전에는 Pending에 멈췄다(4절) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): cluster/Vagrantfile:8-9, apps/petmint/app/deployment.yaml:17, :46-47 --> |
| 워커 4 → 8GB | 노드 메모리 여유(앱 limits 1Gi × 롤링 3개 · MySQL)가 생겼다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): cluster/Vagrantfile:5-9, apps/petmint/app/deployment.yaml:102 --> |
| Harbor DB 백업(infra `apps/harbor-backup/`, 매일 03:45 KST) | Harbor가 망가져도 프로젝트 · robot 계정(`robot$petmint+pull`)이 돌아온다. 이미지 레이어는 백업하지 않는다 — 다시 빌드한다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/harbor-backup/cronjob.yaml:3-4, :17-18, docs/07_registry.md:129 --> |

- **이미 있던 것 그대로**: replicas 2 · required anti-affinity · PDB minAvailable 1 — 매니페스트와 클러스터를 Sync 없이 읽어 같음을 확인했다. 런슈즈도 같은 구성으로 맞췄다 [c:afefd07] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/deployment.yaml:17, :45-51, apps/petmint/app/pdb.yaml:11 -->
- **정비 중에는 Sync하지 않는다**(사용자) — 워커가 하나 빠진 동안이다. 이번 증설 중 펫퍼민트 Sync는 없었다(08:54 UTC 사람이 한 Sync가 마지막) (2026-11-10 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/08_scale_out.md:105, :213 --> <!-- 확인 못 함: 08:54 UTC 사람 Sync 가 마지막인지는 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답, ArgoCD 이력은 최근 10번만) -->
- **묶음 2(같은 날 저녁)** — 노드마다 역할을 고정했다. 상세는 infra `docs/history/build_log/08_scale_out.md` · `docs/runbooks/mysql-replica.md` <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/08_scale_out.md:12-35, :255, docs/runbooks/mysql-replica.md -->

| 바뀐 것 | 펫퍼민트에 |
| --- | --- |
| 앱은 app 노드(w1 · w2)에만(nodeSelector) | app 노드가 둘이라 롤링을 **옛 Pod 하나 먼저 내리고 새 Pod**로 바꿨다(maxSurge 0 · maxUnavailable 1, 10번 1-9절의 maxSurge 1 · maxUnavailable 0 에서). 롤링 동안 잠깐 Pod 하나 — 1초 탐침 실패 0, `rollout restart` 23초 [docs:02_pipeline/10_consultation_flow.md] (2026-11-10 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/deployment.yaml:4-7, :20-23, :43-44, docs/history/build_log/08_scale_out.md:66, :368 --> |
| MySQL Replica `mysql-replica-0`(w2) | binlog 복제(파일 · 위치, GTID 꺼짐 — Primary 재시작 없이). 자동 전환은 없다 — 사람이 승격(SQL 0.2초 · Service 전환 0.1초, 시험은 runshoes로). 복제 계정 Secret `mysql-repl` (2026-11-10 기준) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/runbooks/mysql-replica.md:9, :13, :15, apps/petmint/mysql/replica.yaml:3-7, docs/history/build_log/08_scale_out.md:356, :365-366 --> |
| Harbor · Jenkins · ArgoCD는 w3, 모니터링은 w4 | 배포 · 빌드는 w3가, 모니터링은 w4가 죽어도 상담은 돈다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/harbor/values.yaml:56-72, platform/jenkins/values.yaml:21-22, platform/argocd/pin-infra.sh:7, apps/monitoring/kustomization.yaml:11, cluster/label-nodes.sh:6-8 --> <!-- 클러스터 확인(2026-11-19 인프라 관리자 답): 실제 배치가 이와 같음 --> |
| 모니터링(15번) | Grafana가 턴 로그를 **Replica에서** 읽는다 — 계정 `grafana_ro`는 컬럼 단위 SELECT만(질문 · 답 · 코멘트 · 고객 · 상담원 컬럼 권한 없음) [docs:02_pipeline/15_monitoring.md] <!-- 클러스터 확인(2026-11-19 인프라 관리자 답): grafana_ro 는 USAGE 와 feedback, sessions, turns 의 글 아닌 칼럼에 대한 열 단위 SELECT 뿐, 글 칼럼 권한 없음 --> |

#### 1-15. 자동 Sync (2026-11-11)

petmint Application을 자동 Sync로 바꿨다(사용자 지시). 앱 push → Jenkins 빌드 → 태그 커밋까지 오면 ArgoCD가 Sync를 누르지 않아도 반영한다. 2026-10-16부터 11-10까지는 수동으로 두고 반영 결과를 눈으로 확인했다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app.yaml:4-6, docs/history/build_log/07_project_deploy.md:260 -->

| 항목 | 값 |
| --- | --- |
| 설정 | `automated: {prune: false, selfHeal: false}` — runshoes와 같다. git에서 지운 리소스는 남고, kubectl로 바꾼 것을 되돌리지 않는다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app.yaml:25-28, apps/runshoes/app.yaml:28-31 --> |
| 스위치 | 클러스터의 `kubectl -n argocd patch application petmint …`가 실제 스위치다. 루트가 자식 `syncPolicy`를 덮지 않으므로(1-9절) ronanlab-infra `apps/petmint/app.yaml`은 기록이다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app.yaml:5, bootstrap/root-app.yaml:8-10 --> |
| 바뀌는 것 | **초기화 Job(마이그레이션)도 Sync마다 돈다.** 마이그레이션이 든 앱 커밋은 push만으로 운영 DB에 적용된다. 문서만 바꾼 커밋은 이미지 빌드부터 건너뛰므로(1-8절) 배포가 일어나지 않는다 [code:Jenkinsfile:14-18] [code:Jenkinsfile:71-89] [code:Jenkinsfile:96] [code:Jenkinsfile:125] [code:db/migrate.py] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/jobs/init-db.yaml:15-16, apps/petmint/README.md:31, :65, apps/petmint/app.yaml:25-28 --> |
| monitoring | 같은 날 같은 설정으로 자동 Sync를 켰다 — petmint가 자동인데 대시보드만 수동인 것은 맞지 않고, 대시보드는 깨져도 서비스에 영향이 없고 되돌리기 쉽다. 켤 때 밀려 있던 대시보드 ConfigMap 하나가 바로 반영됐다 [docs:02_pipeline/15_monitoring.md] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/app.yaml:5-6 (17fadc7, 2026-11-11), docs/history/build_log/09_monitoring.md:200 --> |
| cloudflared | **수동으로 둔다(2026-11-11 사용자 결정).** 클러스터 터널 하나가 공개 주소 7개(petmint · runshoes · argocd · harbor · jenkins · grafana · prometheus)를 모두 낸다. 터널이 깨지면 서비스만 멈추는 게 아니라 고칠 도구(ArgoCD UI)와 볼 도구(Grafana)도 같이 사라지고, 되돌리기는 m-k8s에서 kubectl로만 된다. 잘못된 커밋이 사람 손을 거치지 않고 그 상태를 만들지 않게, 사람이 Sync를 누르고 롤링을 지켜본다(13번 2-2절, ronanlab-infra `apps/cloudflared/README.md`) [docs:02_pipeline/13_access_and_tunnel.md] [c:46454fe] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/cloudflared/app.yaml:4-8, apps/cloudflared/README.md:21-23 --> |
| 끌 때 | 사람이 지켜보며 넣어야 하는 배포(되돌리기 어려운 스키마 변경, DB 복구 — 12번 1-5절)는 먼저 끄고 끝나면 켠다. 명령은 ronanlab-infra `apps/petmint/README.md` [docs:02_pipeline/12_data_storage.md] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/README.md:32-36 --> |

#### 1-16. 검색 모델을 공용 model-service로 (2026-11-11, 0e31e94)

KURE-v1 · bge-reranker-v2-m3를 search-service에서 떼어 공용 model-service로 옮겼다(사용자 결정). 런슈즈 챗봇도 같은 model-service를 쓴다. 모델 셋은 그대로이고 도는 자리만 바뀌었다. [c:0e31e94] [code:search_service/main.py:12-15] [code:deploy/host/petmint-search.service:1-4]

| 항목 | 값 |
| --- | --- |
| model-service | 독립 저장소 `~/AI_programming/model-service`(28717bc, 원격 없음), systemd `model-service`, 192.168.122.1:8200에만 bind. 유닛 원본은 그 저장소에 있다. 모델 판은 HF 캐시 스냅숏으로 고정(KURE `8b418a58…`, 리랭커 `953dc6f6…`), 유닛에 `HF_HUB_OFFLINE=1` [code:deploy/host/petmint-search.service:2] [code:deploy/host/petmint-search.service:33] <!-- model-service 확인(2026-11-19): ~/AI_programming/model-service HEAD 28717bc, git remote 없음, model_service/main.py:32, :37-38, deploy/model-service.service:29 (설치된 유닛과 같은 파일) --> |
| search-service | `PETMINT_MODEL_URL`이 있으면 model-service를 부르고(`data/model_client.py`), 없으면 예전처럼 로컬에 모델을 올린다(노트북 · 오프라인 스크립트 · 되돌리기). `/health`의 `models`는 model-service 장치를 옮기고 `"model_service"` 키가 붙는다. 전환 뒤 GPU를 쓰지 않는다 [code:search_service/main.py:12-15] [code:search_service/main.py:41] [code:search_service/main.py:103-124] [code:data/model_client.py] [code:data/search_engine.py:78] |
| 되돌리기 | 분리 전 유닛 판은 46454fe의 `deploy/host/petmint-search.service`. 런북은 model-service 저장소 `docs/runbook-cutover.md` [c:46454fe] [code:deploy/host/petmint-search.service:3-4] <!-- model-service 확인(2026-11-19): ~/AI_programming/model-service/docs/runbook-cutover.md:99-111 --> |

**재부팅 순서가 한 단계 늘었다.**

- 후: `network → docker · libvirtd → model-service → Milvus 대기 → petmint-search` [code:deploy/host/petmint-search.service:12]

model-service는 `After=libvirtd`이고 `ExecStartPost`가 `/health` 200을 기다린다 — "시작됨"이 곧 모델이 올라온 때다. petmint-search는 `After`/`Wants=model-service`(Requires가 아니라 model-service를 재시작해도 따라 내려가지 않는다)이고, `ExecStartPre`가 model-service `/health`를 최대 240초 기다린 뒤 Milvus를 기다린다. `TimeoutStartSec=540`. [code:deploy/host/petmint-search.service:12-15] [code:deploy/host/petmint-search.service:22-23] [code:deploy/host/petmint-search.service:35-37] [code:deploy/host/petmint-search.service:45] <!-- model-service 확인(2026-11-19): ~/AI_programming/model-service/deploy/model-service.service:17, :32 -->

**실제 재부팅 시험은 하지 않았다(2026-11-11 사용자).** 다음 재부팅 때 확인할 것: 두 유닛이 순서대로 뜨는지, model-service가 늦게 뜨거나 Restart될 때 petmint-search가 기다리는지, virbr0가 늦을 때 bind 실패 뒤 Restart로 회복하는지. 볼 명령은 model-service 런북 8절. [code:deploy/host/petmint-search.service:16-18] [code:deploy/host/petmint-search.service:41-42] <!-- model-service 확인(2026-11-19): ~/AI_programming/model-service/docs/runbook-cutover.md:113-134 -->

#### 2. 왜 이렇게 했나

#### 2-1. GPU를 쓰는 것은 호스트에 남긴다

클러스터가 Vagrant VM 위에 있어 GPU가 VM 안으로 들어오지 않는다. PCI 패스스루를 하려면 호스트에서 GPU 드라이버를 떼어내야 하는데, 그러면 호스트의 Ollama를 포기해야 한다.

그래서 **GPU를 쓰는 것은 전부 호스트에, Pod는 네트워크로 호출한다**(09번 1-15절). 생성은 이미 호스트 Ollama를 부르는 구조였으므로 검색도 같은 방식으로 뺐다. [code:app/config.py:32-33] [code:app/config.py:66] [docs:02_pipeline/09_ui_design.md]

**이것이 임시방편만은 아니다.** 16GB 한 장에 모델 넷이 올라가고, `OLLAMA_MAX_LOADED_MODELS`와 `keep_alive`를 그 예산 안에서 정해야 한다(09번 1-15절). [code:search_service/main.py:16] [docs:02_pipeline/09_ui_design.md] 그 배분을 쿠버네티스 스케줄러에 맡기는 것보다 직접 관리하는 편이 지금은 통제 가능하다. device plugin은 기본적으로 GPU를 통째로 Pod 하나에 주므로, Ollama와 search-service가 둘 다 필요하면 한쪽만 받는다 — time-slicing이나 MPS로 쪼갤 수 있지만 그 자체가 또 하나의 변수다.

현업에서도 GPU 노드를 따로 두고 앱은 일반 노드에 올린다. 구조로는 같다.

#### 2-2. 약관과 고객 데이터를 이미지에 담지 않는다

01번의 **"모델·데이터 사내 서버 상주, 외부 유출 0건"** 원칙 때문이다. 이미지는 Harbor를 거쳐 돌고, Jenkins가 빌드하려면 GitHub에도 있어야 한다. 데이터가 여기저기 복사된다. [docs:requirements.md] [code:Dockerfile:4] [code:app/services/policy_data.py:3]

private 저장소라도 "사내 서버 상주"는 아니다. 그리고 약관은 실제 보험 상품의 원문이다. [docs:requirements.md]

**부수 효과로 CI 문제가 함께 풀린다.** `data/chunks/`는 git에 없으므로, 이미지에 넣으려 하면 `git checkout`만 하는 Jenkins에서 `COPY`가 실패한다. 이미지에서 빼면 그 문제가 사라진다. [code:Jenkinsfile:11] [code:.dockerignore:22-24]

**고객 픽스처는 git 에서도 뺀다.** 가짜 데이터지만 이름·전화번호 모양을 하고 있어, 유출 0건 원칙을 데이터 성격이 아니라 모양 기준으로 적용했다. 대신 `app/fixtures/customers.example.json` 을 둔다 — 구조만 같고 값은 명백한 예시(홍길동, 000-0000-0000)다. 저장소를 받은 사람은 그것을 복사해 채운 뒤 시드를 돌린다. [code:.gitignore:39] [code:app/fixtures/customers.example.json] [code:db/seed_insurance_core.py:7]

#### 2-3. 고객 데이터는 별도 DB에 둔다

실무에서 고객 데이터는 보험사 기간계 시스템에 있고, 이 챗봇은 그것을 읽어 쓰는 쪽이다. 회사의 데이터인 것은 맞지만 **이 서비스가 소유하지는 않는다.**

복사해 두면 세 가지가 어긋난다 — 원본이 바뀌어도 모르고, 같은 데이터가 두 군데 있어 어느 쪽이 맞는지 생기고, 계약 변경·해지가 기간계에서 일어나는데 챗봇은 따라가지 못한다.

그래서 `insurance_core` DB를 따로 두고 `petmint_app` 계정에 **SELECT 권한만** 준다. 데이터베이스가 다르면 외래키를 걸 수도 없는데, 그것이 곧 경계가 있다는 표시다(12번 1-3절에서 `customer_id`를 외래키 없이 문자열로 둔 이유와 같다). [code:db/bootstrap.py:39-46] [code:db/migrate.py:7] [code:app/config.py:15-17] [docs:02_pipeline/12_data_storage.md]

**12번 2-2절의 스냅샷 원칙을 실제로 시험할 수 있게 된다.** 고객 등급을 바꿔보려면 전에는 JSON을 고쳐야 했지만, 이제 `UPDATE` 한 줄이면 "외부에서 값이 바뀐 상황"이 그대로 재현된다. [docs:02_pipeline/12_data_storage.md] [code:app/config.py:15-17]

#### 2-4. 데이터가 없으면 조용히 넘어가지 않고 멈춘다

파일이 없거나 비어 있으면 기동을 실패시킨다. 검색 코퍼스가 0건이어도 앱은 멀쩡히 뜨고 답변도 하는데, 모델이 발췌 없이 답하므로 **틀린 답을 자신 있게 한다.** 그 상태로 배포되면 로그를 보기 전까지 모른다. [code:app/services/policy_data.py:6-7] [code:app/services/policy_data.py:28-43]

09번 1-10절에서 고객 픽스처의 `section_name` 불일치에 기동을 실패시키는 것, 12번에서 검색 행 제약을 앱이 아니라 DB의 `CHECK`에 둔 것과 같은 판단이다 — **조용한 실패를 만들지 않는다.** [docs:02_pipeline/09_ui_design.md] [docs:02_pipeline/12_data_storage.md] [code:app/main.py:43]

#### 2-5. 왜 MetalLB인가

세 가지 안이 있었다.

**노드마다 포워더를 두는 방법**은 손댈 범위가 가장 작다. 각 노드에서 443을 31925로 넘기면 클러스터를 전혀 건드리지 않고, 되돌리기도 서비스를 멈추고 hosts 한 줄을 지우면 끝이다. 그러나 인증서 검증을 건너뛰어야 하고, 설정이 노드 OS에 흩어져 GitOps 밖에 남는다. 노드를 늘릴 때마다 반복해야 한다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/02_metrics_storage_ingress.md:195 -->

**Harbor의 `externalURL`을 내부 주소로 바꾸는 방법**은 설정 한 줄이다. 그러나 그 값은 Harbor 전역이라 웹 UI의 pull/push 안내, 외부 `docker login`, 나중에 붙일 OIDC 리다이렉트까지 모두 내부 포트를 가리키게 된다. http라 자격 증명이 평문으로 오간다.

**MetalLB**는 컴포넌트가 하나 늘지만, 사설망 안의 누구나 표준 포트로 쓸 수 있고 설정이 전부 매니페스트에 남는다. 노드를 늘려도 추가 작업이 없다. 클라우드에서 LoadBalancer 타입이 하던 일을 사설 환경에서 대신하는 것이므로 구조로는 표준에 가깝다.

**바꾸기 전에 되돌릴 방법을 먼저 적었다.** ingress-nginx는 지금 돌고 있는 ArgoCD·Harbor·Jenkins가 모두 거치는 길목이다. 리소스 백업과 `ROLLBACK.md`를 `k8s-cluster/backup/`에 두고 단계마다 생존 확인을 거쳤다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/02_metrics_storage_ingress.md:331, 호스트 ~/k8s-cluster/backup/2026-10-15-before-metallb/ROLLBACK.md 와 health.sh -->

#### 2-6. Jenkins 가 Harbor 를 부르는 길 — CoreDNS 재작성

클러스터 DNS 에서 `harbor.ronanlab.dev` 를 ingress-nginx 내부 Service 로 돌린다. 노드의 `/etc/hosts` 와 같은 논리를 클러스터 안에서 하는 것이다. [code:Jenkinsfile:8-9] [code:Jenkinsfile:58-59] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/coredns/configmap.yaml:3-5, :22-25 -->

내부 Service(harbor-core)를 직접 부르는 방법은 1-7절의 토큰 주소 문제에 다시 걸린다. 빌드 Pod 에 `hostAliases` 로 ClusterIP 를 박는 안도 있었으나, 그 IP 가 Jenkinsfile 안에 숨어 Service 를 다시 만들면 조용히 깨진다. [code:Jenkinsfile:21-48]

CoreDNS 는 **이미지 이름이 어디서나 같아진다는 점**이 크다. 노드도 Pod 도 빌드도 같은 주소를 쓰고, Let's Encrypt 인증서로 검증된다. 나중의 ArgoCD → Harbor 도 같이 풀린다.

적용 전에 같은 버전을 Docker 에 띄워 문법을 확인했고, 적용 뒤 argocd·jenkins·github·Docker Hub 는 공개 주소 그대로 풀리는 것과 터널 4/4 를 확인했다. (2026-10-15 이전) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->

#### 2-7. ArgoCD 에 넘길 때 지킨 세 가지

**Namespace 를 ArgoCD 관리에서 뺀다.** `petmint` 네임스페이스에는 사람이 넣은 Secret 네 개가 있다(cloudflared 터널도 처음엔 여기 있었으나 2026-10-18 `cloudflared` 네임스페이스로 옮겼다). 2026-11-10 Replica부터 `mysql-repl` 하나가 더해져 지금은 다섯이다(mysql-root, petmint-db, insurance-seed-db, harbor-pull, mysql-repl). <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/README.md:38, apps/petmint/kustomization.yaml:13, :15, apps/petmint/mysql/replica.yaml:6, docs/runbooks/mysql-replica.md:15, :21 --> <!-- 클러스터 확인(2026-11-19 인프라 관리자 답): petmint 네임스페이스에 Secret 다섯이 다 있음 --> 터널이 죽으면 ArgoCD·Harbor·Jenkins 공개 주소까지 함께 죽는다. ArgoCD 가 네임스페이스를 소유하면 prune 이나 Application 삭제 한 번에 이것이 모두 사라질 수 있다. Secret 처럼 사람이 만드는 쪽으로 남긴다.

**deploy key 를 읽기·쓰기로 나눈다.** 토큰(fine-grained PAT)은 만료일이 있어 만료되면 배포가 **조용히 멈춘다** — 2-4절의 "조용한 실패를 만들지 않는다"와 어긋난다. 읽기와 쓰기를 나누는 것은 Harbor robot 을 pull 전용과 push 용으로 나눈 것과 같은 논리다. ArgoCD 키가 새도 저장소를 고칠 수 없다. [code:Jenkinsfile:124] [code:Jenkinsfile:128]

**처음엔 수동 Sync 로 둔다.** 매니페스트가 의도대로 반영되는지 눈으로 확인한 뒤 자동으로 바꾼다(2026-11-11 바꿨다, 1-15절). 개발은 로컬(uvicorn + vite), 클러스터는 운영만으로 간다 — 단일 환경이라 개발·운영 네임스페이스를 가를 수 없다(4절). [code:web/vite.config.ts] [code:app/config.py:99-102] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app.yaml:4-6 -->
---

#### 3. 시도했던 것들

| 시도 | 결과 |
| --- | --- |
| 약관 데이터를 git에 올려 이미지에 담기 | 6.4MB라 크기는 문제가 아니었으나 01번의 외부 유출 0건 원칙에 어긋난다. 런타임 마운트로 바꿨다 [docs:requirements.md] [code:.dockerignore:22-24] [code:app/services/policy_data.py:1-8] (2026-10-15~2026-10-18 사이) |
| 단일 스테이지 이미지 | node와 python을 한 이미지에 담으면 빌드 도구가 최종 이미지에 남는다. 멀티스테이지로 528MB까지 줄였다 [code:Dockerfile:12-37] (2026-10-15~2026-10-18 사이) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답), 이미지 크기는 Harbor에서 봐야 함 --> |
| `chown -R` 레이어 | 비root 실행을 위해 소유권을 바꿨더니 레이어가 크게 늘었다. 소유권을 바꾸지 않고 파일은 root 소유로 COPY하며 실행만 비root(uid 10001)로 바꿨다. 569MB → 528MB로 줄었으나 무엇으로 줄었는지는 기록에 없다 [code:Dockerfile:29-30] [code:Dockerfile:33-37] [code:Dockerfile:43] (2026-10-15~2026-10-18 사이) |
| `data/rag_context.py`의 pymilvus import를 함수 안으로 | 251MB를 줄일 수 있으나 05·06 노트북과 공유하는 모듈이다. 평가와 서비스가 같은 코드를 쓴다는 원칙(09번 1-6절)을 깨면서까지 줄일 이유가 없고, ContextBuilder를 붙이면 실제로 필요해진다. 손대지 않았다 [code:data/rag_context.py:15] [code:app/main.py:21] [code:app/main.py:46] [docs:02_pipeline/09_ui_design.md] (2026-10-15~2026-10-18 사이) |
| GPU 패스스루로 Ollama를 Pod에 | 호스트에서 GPU 드라이버를 떼어내야 한다. 호스트 Ollama를 포기하는 대가가 크다 |
| 검색을 CPU로 돌려 Pod에 | 리랭커가 후보를 쌍으로 비교하는 구조라 지연이 크게 늘어난다. 고객 전화를 받으며 쓰는 도구에 맞지 않는다 |
| 노드 `/etc/hosts`에 Ingress 주소 추가 | 이름은 풀렸으나 443이 열려 있지 않아 connection refused. NodePort는 30000~32767만 쓸 수 있다 <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) --> |
| containerd mirror 설정 | 레지스트리 주소만 바꾸고 응답으로 받은 토큰 주소는 고치지 않는다. 토큰 단계에서 다시 443으로 간다 <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) --> |
| MetalLB 기본 설치 | 0.16 차트가 frr-k8s(BGP)를 함께 깐다. Calico가 노드마다 179 포트를 쓰므로 충돌한다. BGP 데몬을 껐다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/metallb/values.yaml:1-8, platform/versions.yaml:39-42 --> |
| libvirt DHCP 범위 그대로 | 기본이 .2~.254라 "범위 밖"이 없다. 임대 0건이고 노드는 고정 IP라 .100~.199로 줄였다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/02_metrics_storage_ingress.md:77, :161-163, 호스트 백업 libvirt-net-default.xml:13 --> <!-- 확인 못 함: 임대 0건은 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) --> |
| DNS 리졸버 1.1.1.1 | 이 망에서 노드·Pod 모두 시간 초과. DNS-01 전파 확인용 리졸버를 8.8.8.8로 바꿨다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): platform/cert-manager/values.yaml:41-44 --> |
| Jenkins → Harbor를 내부 Service로 직접 | 토큰 주소가 https라 그대로는 안 된다. 빌드 Pod에 hostAliases로 ClusterIP를 박는 안도 있었으나 그 IP가 Jenkinsfile에 숨어 Service를 다시 만들면 깨진다. CoreDNS 재작성으로 갔다 [code:Jenkinsfile:8-9] |
| 매니페스트를 Jenkinsfile의 git 단계로 받기 | Jenkins 폴링은 git·checkout 단계로 받은 저장소까지 감시한다. 저장소를 나눠도 무한루프가 생긴다. `sh 'git clone'`으로 받아 폴링 대상에서 뺐다 [code:Jenkinsfile:12-13] [code:Jenkinsfile:137] |
| ArgoCD 인증을 토큰으로 | fine-grained PAT은 만료일이 있어 만료되면 배포가 조용히 멈춘다. 읽기·쓰기 deploy key 둘로 바꿨다 [code:Jenkinsfile:124] [code:Jenkinsfile:128] |

---

#### 4. 남은 한계

- [ ]  **단일 클러스터, 단일 환경이다.** 개발·스테이징·운영을 나누지 않았다. 네임스페이스로 가를 수 있지만 VM 합 36GB(2026-11-10 증설 뒤) 한 대에 다 올리는 것은 무리다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): cluster/Vagrantfile:4-9 (4096 + 8192 x 4 = 36GB) --> 까닭: 한 대에 다 올리는 것은 무리다(이 줄)
- [ ]  **model-service가 죽으면 펫퍼민트와 런슈즈 둘 다 검색이 멈춘다. 전에는 펫퍼민트만 멈췄다(2026-11-11 분리 뒤).** 이때 search-service는 `/search` · `/embed` · `/health`가 503(models "unreachable")이 되고 앱은 `search_unavailable`을 낸다. model-service 없이 search-service를 띄우면 기동이 실패하고 systemd Restart가 다시 시도한다(시험에서 확인) [code:search_service/main.py:14] [code:search_service/main.py:81-82] [code:search_service/main.py:98-99] [code:search_service/main.py:106-124] [code:app/services/answer.py:226-228] [code:deploy/host/petmint-search.service:41-42] 까닭: 1-16절 「공용 model-service로 옮겼다(사용자 결정)」
- [ ]  **재부팅 순서가 한 단계 늘었는데 실제 재부팅 시험은 하지 않았다(2026-11-11 사용자).** 확인할 것은 1-16절 [code:deploy/host/petmint-search.service:12] 까닭: 2026-11-11 사용자 지시(이 줄)
- [ ]  **Milvus는 아직 호스트 도커다.** GPU를 쓰지 않으므로 Pod로 옮길 수 있으나, standalone이라도 etcd와 MinIO가 따라붙어 자원을 더 먹는다. search-service와 함께 옮길지 판단한다. 까닭: etcd와 MinIO가 따라붙어 자원을 더 먹는다(이 줄)
- [ ]  **이미지 크기의 절반이 pymilvus다.** pip 레이어 251MB 중 상당 부분이 pandas·numpy·grpc다. 3절 표의 이유로 두었다 [code:app/requirements.txt] [code:data/rag_context.py:15] (2026-10-15~2026-10-18 사이) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답), 레이어 크기는 Harbor에서 봐야 함 --> 까닭: 3절 표 pymilvus 줄(평가와 서비스가 같은 코드를 쓴다는 원칙)
- [ ]  **DB 마이그레이션은 되돌아가지 않는다.** 매니페스트는 ArgoCD가 Git 기준으로 되돌리지만 스키마는 아니다. 깨는 변경이 생기면 그때 정한다 까닭: 깨는 변경이 생기면 그때 정한다(이 줄)
- [ ]  **NFS가 호스트 단일 장애점에 더해진다.** 다만 Ollama·Milvus가 이미 거기 있어 호스트가 죽으면 어차피 서비스가 안 된다 까닭: 호스트가 죽으면 어차피 서비스가 안 된다(이 줄)
- [x]  ~~ArgoCD 초기 admin 비밀번호 Secret이 남아 있다.~~ 지워졌다(2026-11-09 확인 — 없음) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/04_argocd.md:18, :234 (argocd-initial-admin-secret 없음, 기록은 2026-11-12 조회) -->
- [ ]  **MySQL 자동 장애 전환이 없다.** Operator가 필요한데 자원 제약으로 Replica(w2, 2026-11-10) + 수동 승격을 택했다. w1이 죽으면 사람이 런북(infra `docs/runbooks/mysql-replica.md`)대로 승격한다 — 기계 쪽 약 2분, 나머지는 알아채고 판단하는 시간. 앱 트래픽까지 옮기는 전환은 아직 해 보지 않았다. Replica는 백업이 아니다(지운 것은 Replica에서도 지워진다) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/history/build_log/08_scale_out.md:79, :371, :432, docs/runbooks/mysql-replica.md:3-4 --> 까닭: Operator가 필요한데 자원 제약(이 줄)

**조건: 우리가 고르지 않은 것**

- [ ]  **GPU 호스트가 단일 장애점이다.** Ollama·model-service·search-service·Milvus가 모두 한 대에 있다. 그 머신이 죽으면 Pod가 멀쩡해도 서비스가 안 된다
- [ ]  **libvirt 관리망(192.168.121.x)은 DHCP다.** VM을 다시 만들면 주소가 바뀐다. 노드 설정에는 고정 IP인 사설망(192.168.122.x)을 쓴다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): docs/02_nodes.md:34, platform/metallb/pool.yaml:12, cluster/Vagrantfile:17 -->
- [ ]  **백업이 운영 DB와 같은 물리 디스크에 있다.** 백업 NFS(`~/backup/mysql/petmint`)와 MySQL PV(VM 디스크)가 같은 호스트 · 같은 NVMe다(12번 1-5절) [docs:02_pipeline/12_data_storage.md] [code:deploy/scripts/host-nfs-backup-setup.sh] <!-- 2026-11-19 잼: findmnt, virsh domblklist, lsblk 로 ~/backup, /srv/nfs/backup/petmint, w1 VM 디스크가 모두 /dev/nvme0n1p2 -->
- [ ]  **VM이 모두 같은 물리 서버에 있다.** 노드 분산은 VM · kubelet 장애만 막는다 — 서버 자체가 죽으면 전부 멈춘다(위 GPU 호스트 단일 장애점과 같은 머신)

---

#### 5. 검증 항목

- [x]  빌드 도구가 최종 이미지에 남지 않는가
- [x]  Jenkins 에서 빌드가 끝까지 도는가
- [x]  Harbor 에 커밋 해시 태그가 올라가는가 (digest 일치)
- [x]  노드 세 대에서 그 태그를 당길 수 있는가
- [x]  자격 증명이 빌드 로그에 노출되지 않는가 [code:Jenkinsfile:102-110]
- [x]  컨테이너를 띄워 `/`에 접속하면 React 화면이 나오는가 [code:app/main.py:96-98]
- [x]  `/api`와 `/ws`가 같은 포트에서 동작하는가 [code:app/main.py:89-98]
- [x]  `.env`가 이미지에 없는가 [code:.dockerignore:6-8]
- [x]  환경변수로 DB·Milvus·Ollama·search-service 주소를 바꿀 수 있는가 [code:app/config.py:26] [code:app/config.py:33] [code:app/config.py:66-67]
- [x]  약관 데이터가 이미지에 없는가 [code:.dockerignore:22-24]
- [x]  마운트 없이 띄우면 빠진 파일을 밝히며 기동이 실패하는가 [code:app/services/policy_data.py:28-35]
- [x]  같은 이미지로 `python -m db.migrate`가 도는가 [code:Dockerfile:10] [code:Dockerfile:35]
- [x]  MySQL을 StatefulSet으로 올린 뒤 pod를 지워도 데이터가 남는가
- [x]  이미지 태그를 바꾸면 롤링이 도는가 (태그 교체는 다음 빌드 후)
- [x]  앱 Pod 두 개가 서로 다른 노드에서 뜨는가
- [x]  호스트에서 청크를 고치면 Pod가 재적재 없이 보는가
- [x]  푸시하면 Jenkins가 빌드해 Harbor에 태그가 올라가는가
- [x]  Jenkins가 매니페스트 태그를 바꿔 push하는가
- [x]  ArgoCD가 그 변경을 감지하는가 (3분 조회) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): bootstrap/root-app.yaml:3 -->
- [x]  Sync하면 Pod가 한 대씩 새 태그로 교체되는가 (부하 중 HTTP 7,941건 실패 0) (2026-10-16~2026-10-18 사이) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답), 다시 재려면 서비스가 끊길 수 있어 사람 승인이 필요함 -->
- [x]  매니페스트 변경이 빌드를 다시 트리거하지 않는가 [code:Jenkinsfile:12-13] [code:Jenkinsfile:137]
- [x]  kubectl로 바꾸면 ArgoCD가 OutOfSync로 잡는가
- [x]  Pod에서 호스트의 Ollama·Milvus·search-service에 닿는가
- [x]  롤링 중 HTTP 요청이 실패하지 않는가 — drain 5,621건 실패 0. WS는 1012로 한 번 끊기고 다시 연결된다 [c:afefd07] (2026-10-16 기준) <!-- 확인 못 함: 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답, 펫퍼민트 쪽 기록은 afefd07 의 deploy/README.md), 다시 재려면 서비스가 끊길 수 있어 사람 승인이 필요함 -->