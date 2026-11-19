<!--
다루는 곳: data/refusal.py, scripts/refusal_rescore.py, db/migrations/petmint/0009_turn_refused_search_ms.sql, deploy/host/milvus/docker-compose.yml, tests/test_refusal.py, tests/test_turn_metrics.py, scripts/verify_cases.py, scripts/verify_modes.py
읽은 커밋: 6710b83
-->
> 상태: ✓ 설치(2026-11-10, 인프라 가용성 묶음 2 — 전부 w4). 원본은 ronanlab-infra `apps/monitoring/README.md`. 아래 2절 이후는 처음 설계(2026-10-18)이고, 설치하며 바뀐 것은 이 상자에만 적는다: <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/README.md:4, :6 -->
> - 보존 Prometheus **15일**(10Gi, 9GB) · Loki **7일**(서버 로그만 — 대화 기록은 넣지 않는다. runshoes 챗봇의 질문 원문 줄과 Jenkins 빌드 Pod 로그는 수집기 Alloy가 버린다) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/prometheus/statefulset.yaml:36-37, :69, apps/monitoring/loki/loki.yaml:34, apps/monitoring/alloy/alloy.yaml:3-4, :49-59, :96-100 -->
> - 앱 `/metrics`가 없어 HTTP 요청 수 · 에러율은 **ingress-nginx 메트릭**(같은 날 켬)에서, 질문 · 답 지표는 **턴 로그(DB Replica)**를 Grafana MySQL 데이터소스로 읽는다. [code:app/main.py:80-94] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/README.md:16-22, apps/monitoring/grafana/datasource.yaml:29-36 -->
>   읽기 계정 `grafana_ro`는 컬럼 단위 SELECT만 — turns(분류 · 시간 · 상태) · sessions(mode) · feedback(rating). 질문 · 답 · 코멘트는 권한이 없다(시험: ERROR 1143) [code:db/migrations/petmint/0009_turn_refused_search_ms.sql:2] <!-- 클러스터 확인(2026-11-19 인프라 관리자 답): grafana_ro는 USAGE와 열 단위 SELECT만(feedback, sessions, turns의 분류, 시간, 상태 칸), 글 칼럼 없음 -->
> - 대시보드 `petmint 운영`: 서비스 상태 · 접속량 / 질문량 / 답변 품질 · 속도(확인 불가 응답 비율 · 답변 실패 · 중단 비율 · 규칙별 답 · 답한 방식 · 상담원 평가 · 답변 걸린 시간 · 조항 검색 걸린 시간) / AI 서버(GPU). <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/grafana/dashboards/gen_petmint.py:210, apps/monitoring/grafana/dashboards/petmint.json:3, :19, :531, :589 -->
>   2026-11-11 비개발자가 보는 전제로 패널 이름 · 호버 설명을 바꿨다 — 이름은 무엇을 세는지, 설명은 무엇이 섞였나 · 높거나 낮으면 무슨 뜻인가 · 언제부터인가. 칸 이름은 설명 끝 「출처」에만. 같은 날 「답변 실패 · 중단 비율」(turns.status — 답 생성 실패가 어디에도 안 보이던 구멍)을 더하고, 규칙 이름을 한글로(code_rules.RULES 이름) 바꿨다 [code:app/services/code_rules.py:69-96] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/grafana/dashboards/gen_petmint.py:64, :66-75, :97 -->
> - **거절률 · 검색 지연**은 2026-11-11 앱이 턴마다 `turns.refused` · `turns.search_ms`를 적게 했다(마이그레이션 0009, 12번 1-1절). 거절 판정은 평가와 같은 함수(`data/refusal.py`, 2026-11-12부터 C안 — 4-1절). 그 전 턴은 NULL이라 패널에 나오지 않는다. GPU exporter(호스트 컨테이너 nvidia-gpu-exporter 1.3.1, 192.168.122.1:9835)는 2026-11-11부터 돌고 Prometheus `nvidia-gpu` up=1이다 [code:db/migrations/petmint/0009_turn_refused_search_ms.sql:5-11] [code:app/services/answer.py:549] [code:app/services/answer.py:555] [code:data/refusal.py:42-51] [docs:02_pipeline/12_data_storage.md:15] [c:327c913] [c:6078a79] <!-- 2026-11-19 잼: docker ps, docker inspect nvidia-gpu-exporter(만든 때 2026-11-11 09:22 KST, 192.168.122.1:9835) --> <!-- 클러스터 확인(2026-11-19 인프라 관리자 답): Prometheus nvidia-gpu up=1 -->
> - **Milvus 9091**: 2026-11-11 호스트 compose에서 `192.168.122.1:9091`에도 게시(19530과 같은 방식, 컨테이너 재생성 8초) → Prometheus `up{job="milvus"}` = 1. etcd 2379는 그대로 닫혀 있다 [code:deploy/host/milvus/docker-compose.yml:69-72] [code:deploy/host/milvus/docker-compose.yml:9] [c:327c913] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/README.md:60, apps/monitoring/prometheus/configmap.yaml:80-83 --> <!-- 확인 못 함: 재생성 8초는 지난 일이라 다시 잴 수 없음, 인프라 저장소와 기록에도 없음(2026-11-19 인프라 관리자 답) -->
> - Ollama 응답은 json-exporter가 `/api/ps`를 읽는 것으로 본다(blackbox-exporter 대신 — 올라간 모델까지 보인다) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/json-exporter/json-exporter.yaml:1-3, apps/monitoring/prometheus/configmap.yaml:99-113 -->

### 0. 목표

클러스터(노드·Pod)와 앱의 상태를 한곳에서 본다. 이번 단계는 **보는 것까지**다 — 알림(Alertmanager)은 무엇을 누구에게 알릴지 정한 뒤에 붙인다.

| 구성 | 하는 일 |
| --- | --- |
| Prometheus | 지표 수집·저장(보존 15일 또는 9GB) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/prometheus/statefulset.yaml:36-37 --> |
| Grafana | 대시보드 |
| node-exporter | 노드 CPU·메모리·디스크 |
| kube-state-metrics | 쿠버네티스 객체 상태(재시작·OOMKilled·Requests/Limits·노드 Ready) |
| (kubelet cAdvisor) | 컨테이너 CPU·메모리 사용량 — 따로 띄우지 않고 kubelet이 이미 낸다 |

---

### 1. 수집 지표 (초안)

**노드**

| 지표 | 출처 | 상태 |
| --- | --- | --- |
| CPU 사용률 | node-exporter `node_cpu_seconds_total` | △ |
| 메모리 사용률 | node-exporter `node_memory_MemAvailable_bytes` / `node_memory_MemTotal_bytes` | △ |
| 디스크 사용률 | node-exporter `node_filesystem_avail_bytes` / `node_filesystem_size_bytes` (`/`) | △ |
| 노드 Ready 상태 | kube-state-metrics `kube_node_status_condition{condition="Ready"}` | △ |

**Pod**

| 지표 | 출처 | 상태 |
| --- | --- | --- |
| 재시작 횟수 | kube-state-metrics `kube_pod_container_status_restarts_total` | △ |
| OOMKilled | kube-state-metrics `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}`, cAdvisor `container_oom_events_total` | △ |
| CPU 사용량 대 Requests | cAdvisor `container_cpu_usage_seconds_total` ÷ kube-state-metrics `kube_pod_container_resource_requests{resource="cpu"}` | △ |
| 메모리 사용량 대 Requests | cAdvisor `container_memory_working_set_bytes` ÷ `kube_pod_container_resource_requests{resource="memory"}` | △ |

**앱(petmint)** — △ `/metrics` 엔드포인트가 아직 없다. 필요한 계측: [code:app/main.py:80-94] [code:app/requirements.txt]

- HTTP 응답 시간·상태코드: FastAPI 미들웨어로 요청마다 히스토그램(경로 템플릿·메서드·상태코드 라벨) — 예: `prometheus-client` + 미들웨어, 또는 `prometheus-fastapi-instrumentator`. 경로는 `/api/sessions/{session_id}`처럼 **템플릿으로** 남긴다(세션 id를 라벨에 넣으면 시계열이 끝없이 는다) [code:app/routers/sessions.py]
- WebSocket 연결 수: `chat_ws`의 accept·close에서 올리고 내리는 Gauge. 턴 지연(`latency_ms`·`first_token_ms`)도 히스토그램으로 내면 좋다 [code:app/routers/chat_ws.py:94-110] [code:app/schemas.py:188-189]
- `/metrics` 경로를 앱에 두고, Pod에 `prometheus.io/scrape: "true"`, `prometheus.io/port`, `prometheus.io/path` 주석 — Prometheus의 `kubernetes-pods` 작업은 이미 이 주석을 찾도록 써 두었다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/prometheus/configmap.yaml:58-69 -->
- replicas 2라 Pod마다 따로 긁힌다. uvicorn worker를 늘리면 multiprocess 모드가 필요하다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/petmint/app/deployment.yaml:17 -->

**외부 의존(GPU 호스트)** — 응답 가능 여부

| 대상 | 방법 | 상태 |
| --- | --- | --- |
| Milvus | 호스트 `192.168.122.1:9091/metrics`를 긁어 `up`만 남긴다(내부 지표는 버림) | ✓ 2026-11-11부터 9091은 `127.0.0.1`과 `192.168.122.1`(VM 사설망)에 열려 있어 클러스터에서 닿는다 [code:deploy/host/milvus/docker-compose.yml:71-72] [c:327c913] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/README.md:60, apps/monitoring/prometheus/configmap.yaml:80-83 --> <!-- 클러스터 확인(2026-11-19 인프라 관리자 답): Prometheus milvus up=1 --> |
| Ollama | `/metrics`가 없다 — json-exporter가 `GET /api/ps`를 읽는다(올라간 모델까지 보인다) | ✓ 구성 있음 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/prometheus/configmap.yaml:99-113, apps/monitoring/json-exporter/json-exporter.yaml:1-3 --> |
| search-service | `GET /health`(ok 필드) — blackbox-exporter 또는 search-service에 `/metrics` 추가 | △ 구성 없음(search-service는 호스트 `petmint-search`로 돈다) [code:search_service/main.py:103-124] [code:deploy/host/petmint-search.service] |
| model-service(공용) | `GET http://192.168.122.1:8200/health` — blackbox-exporter. 죽으면 펫퍼민트와 런슈즈 둘 다 검색이 멈춘다(14번 4절). search-service `/health`도 model-service에 닿지 않으면 503이라 간접으로는 보인다 | △ 구성 없음(2026-11-11 분리 뒤, search-service와 같은 상태) [code:search_service/main.py:106-124] [docs:02_pipeline/14_deployment.md:594] |

---

### 2. 구성 — 매니페스트로 남긴다

helm install로 넣지 않는다 — 설정이 클러스터 안에만 남아 Pod를 다시 만들면 무엇을 어떻게 했는지 모르게 된다(14번 1-9절의 Jenkins와 같은 이유). kube-prometheus-stack의 Operator·CRD 없이 Prometheus 설정 파일 하나로 긁는다 — 지표 출처가 넷뿐이라 Operator가 줄여 주는 일보다 늘리는 구성이 많다. [docs:02_pipeline/14_deployment.md:147] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/README.md:4. 다름: 지표 출처는 넷이 아니라 지금 scrape 여덟(apps/monitoring/prometheus/configmap.yaml:16-113). 2절이라 글은 B단계로 둠 -->

```
ronanlab-infra/
  apps/monitoring/
    kustomization.yaml       namespace monitoring, 리소스 목록
    README.md                처음 한 번(Namespace·Secret·Application), 크기 근거
    prometheus/              ServiceAccount·RBAC·ConfigMap(scrape 설정)·StatefulSet(PVC 5Gi)·Service
    grafana/                 Deployment·Service·데이터소스 ConfigMap
    node-exporter/           DaemonSet(hostNetwork :9100)·headless Service
    kube-state-metrics/      ServiceAccount·RBAC·Deployment·Service
    app.yaml                 Application(자동 Sync 2026-11-11~·prune·selfHeal 없음·finalizer 없음) — 루트(bootstrap/root-app.yaml)가 만든다
```

| 항목 | 값 |
| --- | --- |
| 이미지 | prometheus v3.15.0, grafana 13.2.3, node-exporter v1.12.1, kube-state-metrics v2.19.1(client-go 1.35 = 클러스터 v1.35.9) <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/prometheus/statefulset.yaml:32, apps/monitoring/grafana/deployment.yaml:26, apps/monitoring/node-exporter/daemonset.yaml:26, apps/monitoring/kube-state-metrics/deployment.yaml:25 --> |
| 수집 주기 | 30초 |
| 보존 | 7일, 그리고 4GB(PVC 5Gi보다 먼저 지운다) |
| 저장소 | local-path PVC 5Gi — PV가 처음 붙은 노드에 묶인다 |
| 노출 | 전부 ClusterIP. 확인은 port-forward |
| Namespace | 사람이 만든다(Secret grafana-admin이 거기 있다). Application은 `CreateNamespace=false` |
| 배치 제약 | 없다. node-exporter만 control-plane taint를 견딘다(m-k8s 지표가 빠지지 않게) |

**긁는 것**: Prometheus 자신, node-exporter, kubelet cAdvisor(1절에 쓰는 지표 7개만 남김), kube-state-metrics(객체 12종만), 주석 단 Pod, Milvus(`up`만).
**긁지 않는 것**: apiserver·kubelet `/metrics` — 시계열이 가장 많고 1절에 쓰지 않는다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/README.md:80 -->

**Requests/Limits** (근거는 `apps/monitoring/README.md` "크기") <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/README.md:65-100 -->

| 구성 | requests | limits |
| --- | --- | --- |
| Prometheus | 100m / 384Mi | 500m / 768Mi |
| Grafana | 50m / 128Mi | 250m / 256Mi |
| node-exporter(노드마다) | 20m / 32Mi | 100m / 64Mi |
| kube-state-metrics | 20m / 64Mi | 100m / 128Mi |
| 합 | 270m / 704Mi | 1,370m / 1,408Mi |

**왜 8192 뒤인가**: 2026-10-18 실측으로 w3의 limits 합이 3,412Mi(노드 3,912Mi의 89%)다. Prometheus가 w3에 뜨면 limits가 4,244Mi로 노드 용량을 넘는다. requests로는 어느 노드든 들어가지만, 여러 Pod가 동시에 limit까지 쓰면 OOM이 난다. 배치 제약으로 피하지 않는다 — 8192에서는 필요 없고, 넣으면 다시 걷어내야 한다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/README.md:67-68, :99-100 -->

---

### 3. 대시보드

△ 없다. Grafana의 `/var/lib/grafana`는 emptyDir라 UI에서 만든 대시보드는 Pod를 다시 만들면 사라진다. 남길 대시보드는 JSON을 ConfigMap으로 넣어 provisioning한다 — 데이터소스와 같은 방식. 1절 지표를 정한 뒤 노드·Pod·앱 세 장으로 만든다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 다름: emptyDir와 ConfigMap provisioning은 맞고(apps/monitoring/grafana/deployment.yaml:2, :72-85), 대시보드는 「없다」가 아니라 petmint, runshoes 두 장이 있다(apps/monitoring/kustomization.yaml:31-35). 3절이라 글은 B단계로 둠 -->

**외부 노출**: △ 정하지 않았다. grafana.ronanlab.dev로 열려면 터널 ConfigMap에 호스트를 더하고 Access 정책을 붙여야 한다 — 터널 설정은 다섯 호스트가 한 파일에 있어 함께 다룬다(13번 2-3절). [docs:02_pipeline/13_access_and_tunnel.md:125]

---

### 4. 남은 한계

- [ ]  Grafana 대시보드가 emptyDir에 있다 — 대시보드 ConfigMap을 만들기 전까지 UI에서 만든 것은 재시작하면 사라진다
- [ ]  Prometheus가 한 대다 — PV가 묶인 노드를 비우면(drain) Prometheus도 그동안 멈춘다
- [ ]  Ollama·search-service·model-service 응답 여부는 blackbox-exporter가 없어 보지 못한다
- [ ]  앱 지표가 없다 — petmint `/metrics`부터 붙여야 1절 앱 항목이 들어온다 [code:app/main.py:80-94]
- [ ]  알림이 없다 — Alertmanager는 알림 설계 뒤
- [ ]  **Milvus 9091에 인증 없는 운영용 경로가 있다.** 지표(`/metrics`)·`/healthz` 말고도 `/debug/pprof`(프로파일)·`/log/level`(로그 수준 조회·변경)이 응답한다(2026-11-11 확인, 200). 지표를 긁으려고 VM 사설망(192.168.122.0/24)에도 열었으므로 클러스터 Pod에서 닿는다. 19530(벡터 조회·쓰기)이 이미 같은 망에 인증 없이 열려 있어 새로 생기는 위험은 작다고 판단했다(사용자 동의 2026-11-11). LAN에는 열지 않는다. 좁히려면 호스트에서 지표 경로만 넘기는 프록시를 두거나 NetworkPolicy로 Prometheus만 나가게 한다 [code:deploy/host/milvus/docker-compose.yml:9-12] [code:deploy/host/milvus/docker-compose.yml:69-72] <!-- 2026-11-19 잼: 127.0.0.1과 192.168.122.1의 9091에 curl로 /metrics, /healthz, /debug/pprof, /log/level 모두 200, docker inspect milvus-standalone 포트 bind는 두 주소뿐 -->
- [ ]  거절률은 문구 판정이다 — 거절 문구 없이 얼버무린 답은 거절로 세지 않고, 거절 문구가 들어간 부분 답은 거절로 센다(평가와 같은 한계). 2026-11-12에 확실히 잘못 찍히던 셋은 뺐다 — 아래 4-1절. 부분 답은 4-1절 「다음 단계」 [code:data/refusal.py:42-51]


#### 4-1. 거절 판정 — 2026-11-12에 바꿨다

`turns.refused`와 평가(`scripts/eval_serving`), `db/rule_report`는 같은 함수 `data/refusal.refused`를 쓴다(`verify_cases`, `verify_modes`는 같은 파일의 문구 목록 `REFUSAL_PHRASES`만 쓴다). **2026-11-12 배포분부터 C안**이다. 그 전 턴의 `turns.refused`는 다시 계산하지 않았다 — 11-12 이전 값은 예전 판정(v1)이다. [code:app/services/answer.py:549] [code:scripts/eval_serving.py:146-150] [code:db/rule_report.py:29-35] [code:data/refusal.py:28] [c:6078a79] [code:scripts/verify_cases.py:23] [code:scripts/verify_modes.py:93-95] <!-- 확인 못 함: 운영 DB 원문이라 규칙상 못 읽음 -->

| | v1(~2026-11-12) | 현재(C안) |
| --- | --- | --- |
| 문구 위치 | 답 어디든 | 답 어디든(그대로) [code:data/refusal.py:42-57] |
| 코드가 덧붙인 「참고:」 줄 | 본다 — 나이 참고 줄 "(구체 나이는 **약관에 없**음)"이 붙은 모델 답이 모두 거절로 찍혔다 | 보지 않는다(그 앞이 모델 답) [code:data/refusal.py:27] [code:data/refusal.py:44] [code:app/services/customer_facts.py:134-135] |
| "인사부서에 확인/문의" | 있으면 거절 — 사내규정 프롬프트 탓에 다 답한 뒤에도 붙는다 | 다른 답이 있으면 거절이 아니다. 맺음말뿐이면 거절 [code:data/refusal.py:25] [code:data/refusal.py:39] [code:data/refusal.py:48-51] |
| 코드 답(`code_rule`) | 문구로 판정 — 병명 보장 대조 답의 나이 참고 줄이 거절로 찍혔다 | 판정하지 않고 0(분모는 그대로 — 정상으로 끝난 답 전부) [code:app/services/answer.py:549] |

계기: 권태호 "저는 언제 정년이에요?"(11-11)가 정년을 바르게 답했는데 거절로 찍혔다. 걸린 것은 "규정에서 직접 확인되지는 않습니다"가 아니라(그 말은 "확인되지 않"과 글자가 다르다) 맨 끝 맺음말 "인사부서에 확인"이었다. [code:data/refusal.py:23-24] [code:data/refusal.py:31-32] <!-- 확인 못 함: 운영 DB 원문이라 규칙상 못 읽음 -->

**바꾸기 전에 잰 것**
- 운영(`refused`가 있는 85턴, 대부분 시드 상담): 거절 22 → 18(25.9% → 21.2%). 빠진 넷 — 정년 · 남은 연차 수당 · 부산 출장비(맺음말), 백내장(코드 답 + 나이 참고 줄). 남은 18은 NO_ANSWER 그대로 9 · NO_ANSWER + 참고 줄 4 · "규정에 없다"가 답인 것 1(칠순 경조휴가) · 부분 답 4(아래) (2026-11-11~2026-11-12 사이) <!-- 확인 못 함: 운영 DB 원문이라 규칙상 못 읽음 -->
- 과거 평가(저장된 `eval_serving` 38회분, 모델 답 11,279턴): 거절 4,568 → 4,321(247턴 바뀜, 32회분). **바뀐 247턴은 모두 나이 참고 줄 때문**이었고 gemma 판정(`.judge.json`)이 "거절"로 본 것은 0. gemma "거절"과의 일치 9,079 → 9,325 / 9,592. 합격 · 불합격이 바뀌는 것은 거절해야 하는 N축뿐이고 1,517 → 1,516 / 1,590(한 문항 — 모델은 답했는데 참고 줄로 거절 처리되던 것). 그래서 **과거 보고의 거절 건수는 나이 참고 줄을 넣은 뒤(2026-10-24 `AGE_CODE`) 회차마다 몇 건~10여 건 많게 적혀 있다**. 다른 합격 수는 그대로다 (2026-11-11~2026-11-12 사이) [code:scripts/refusal_rescore.py:1-8] [c:98c24de] [c:6078a79] <!-- 확인 못 함: 저장된 eval_serving 결과는 logs/ 아래(143MB)라 너무 커서 올리지 않음 -->
- 쓰지 않은 안 — 위치로 가르기(거절 문장이 본문 앞일 때만): gemma 일치는 98.8%로 더 오르지만 베이스 모델 회차의 N축 통과가 18 → 1 · 15 → 0으로 무너졌다. 서두를 깐 뒤 "…명시되어 있지 않습니다"로 거절하는 진짜 거절을 놓친다(사용자 — 쓰지 않는다) (2026-11-11~2026-11-12 사이) [code:data/refusal.py:15] <!-- 확인 못 함: 원자료는 logs/ 아래(143MB)라 너무 커서 올리지 않음 -->

**과거 수치 다시 내기**: `data.refusal.refused_v1`가 예전 판정 그대로다. 새로 잴 때 `python -m scripts.eval_serving … --refusal v1`(결과 JSON에 `refusal_judge`가 남는다), 저장된 결과를 다시 셀 때 `python -m scripts.refusal_rescore <eval_serving_*.json …>`(두 판 · gemma 일치 · N축을 나란히 낸다). [code:data/refusal.py:54-57] [code:scripts/eval_serving.py:360-366] [code:scripts/refusal_rescore.py:1-8]

**다음 단계 — 부분 답(하지 않음, 사용자 2026-11-12)**: 일부는 답하고 일부는 "규정에 없다"고 한 답(운영: 올해 남은 연차 · 직책수당의 통상임금 포함 · 경조금 · 승진 시기)은 낱말로도 위치로도 가를 수 없다. 문구는 걸렸지만 NO_ANSWER 그대로가 아니고 거절 문장이 본문 앞도 아닌 애매한 턴만 gemma가 거절 · 부분 · 답함으로 가르고, 답변 경로를 막지 않게 나중에 몰아서(하루 몇 건) 판정해 Grafana에 확실한 거절과 부분 답을 따로 보이는 안. 운영이 하루 몇 건이라 급하지 않고 gemma 판정을 붙이는 일이 커서 미뤘다 <!-- 확인 못 함: 운영 DB 원문이라 규칙상 못 읽음 -->
---

### 5. 검증 항목 (8192로 올린 뒤 저녁에 실행)

**적용 전**

- [ ]  노드 네 대 모두 8192로 올라왔는가(`kubectl top nodes`, `free -m`) — 다시 재서 2절 판단이 그대로인지 본다
- [ ]  `kubectl create namespace monitoring`, Secret `grafana-admin` 생성(README "처음 한 번")
- [ ]  `bootstrap/root-app.yaml`의 `exclude: 'monitoring/app.yaml'` 줄을 지우고 push → 루트가 Application을 만든 뒤 monitoring만 Sync — petmint Application은 건드리지 않는다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 다름: exclude 줄은 2026-11-10에 지워 monitoring Application이 이미 들어갔고(bootstrap/root-app.yaml:29, apps/monitoring/app.yaml:2) 2026-11-11부터 자동 Sync다(apps/monitoring/app.yaml:5-6). 5절이라 글은 B단계로 둠 -->

**뜨는가**

- [ ]  Pod 전부 Running·Ready: prometheus-0, grafana, kube-state-metrics, node-exporter ×4(m-k8s 포함)
- [ ]  PVC `data-prometheus-0`가 Bound(local-path)
- [ ]  Prometheus Status → Targets: node-exporter 4/4, kubelet-cadvisor 4/4, kube-state-metrics 1/1, prometheus 1/1 모두 UP
- [x]  milvus 대상이 UP(호스트 :9091에 닿는가) — 2026-11-11, 게시 주소를 192.168.122.1로 더한 뒤 [code:deploy/host/milvus/docker-compose.yml:72] [c:327c913] <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): apps/monitoring/README.md:60, :62 -->
- [ ]  Grafana가 뜨고(port-forward 3000) admin으로 로그인되는가
- [ ]  Grafana 데이터소스 Prometheus가 연결 성공(Save & test)

**1절 지표가 들어오는가** (Prometheus에서 쿼리)

- [ ]  노드 CPU·메모리·디스크 사용률이 노드 4대 모두 나온다
- [ ]  `kube_node_status_condition{condition="Ready",status="true"}`가 4대 모두 1
- [ ]  `kube_pod_container_status_restarts_total`이 Pod별로 나온다
- [ ]  `kube_pod_container_status_last_terminated_reason` 시계열이 있다(OOMKilled가 없으면 비어 있을 수 있다)
- [ ]  Pod별 CPU·메모리 사용량 ÷ requests 비율 쿼리가 값을 낸다

**다른 Pod에 해가 없는가**

- [ ]  적용 뒤 10분 동안 다른 네임스페이스 Pod의 재시작·OOMKilled가 늘지 않는다
- [ ]  노드 메모리 증가량을 잰다(적용 전후 `kubectl top nodes`) — 2절 requests 합 704Mi와 비교
- [ ]  Prometheus 실사용 메모리·시계열 수(`prometheus_tsdb_head_series`)를 재서 2절 추정(약 1만)과 비교 — 크게 다르면 requests를 고친다
- [ ]  하루 뒤 TSDB 크기(`prometheus_tsdb_storage_blocks_bytes`)로 7일치를 다시 어림해 PVC 5Gi가 맞는지 본다
