> 상태: △ 매니페스트 작성(2026-10-18, ronanlab-infra `platform/monitoring/`) — 적용·Sync 전. VM 메모리를 4096 → 8192로 올린 뒤 적용한다.
> 아무것도 돌려보지 않았다. 앱(petmint) 지표와 Ollama·search-service 응답 여부는 계측이 없어 설계만 있다.

### 0. 목표

클러스터(노드·Pod)와 앱의 상태를 한곳에서 본다. 이번 단계는 **보는 것까지**다 — 알림(Alertmanager)은 무엇을 누구에게 알릴지 정한 뒤에 붙인다.

| 구성 | 하는 일 |
| --- | --- |
| Prometheus | 지표 수집·저장(보존 7일) |
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

**앱(petmint)** — △ `/metrics` 엔드포인트가 아직 없다. 필요한 계측:

- HTTP 응답 시간·상태코드: FastAPI 미들웨어로 요청마다 히스토그램(경로 템플릿·메서드·상태코드 라벨) — 예: `prometheus-client` + 미들웨어, 또는 `prometheus-fastapi-instrumentator`. 경로는 `/api/sessions/{session_id}`처럼 **템플릿으로** 남긴다(세션 id를 라벨에 넣으면 시계열이 끝없이 는다)
- WebSocket 연결 수: `chat_ws`의 accept·close에서 올리고 내리는 Gauge. 턴 지연(`latency_ms`·`first_token_ms`)도 히스토그램으로 내면 좋다
- `/metrics` 경로를 앱에 두고, Pod에 `prometheus.io/scrape: "true"`, `prometheus.io/port`, `prometheus.io/path` 주석 — Prometheus의 `kubernetes-pods` 작업은 이미 이 주석을 찾도록 써 두었다
- replicas 2라 Pod마다 따로 긁힌다. uvicorn worker를 늘리면 multiprocess 모드가 필요하다

**외부 의존(GPU 호스트)** — 응답 가능 여부

| 대상 | 방법 | 상태 |
| --- | --- | --- |
| Milvus | 호스트 `192.168.122.1:9091/metrics`를 긁어 `up`만 남긴다(내부 지표는 버림) | △ 설정만 |
| Ollama | `/metrics`가 없다 — blackbox-exporter로 `GET /api/version` 프로브가 필요하다 | △ 구성 없음 |
| search-service | `GET /health`(ok 필드) — blackbox-exporter 또는 search-service에 `/metrics` 추가 | △ 구성 없음, search-service도 미기동 |

---

### 2. 구성 — 매니페스트로 남긴다

helm install로 넣지 않는다 — 설정이 클러스터 안에만 남아 Pod를 다시 만들면 무엇을 어떻게 했는지 모르게 된다(14번 1-9절의 Jenkins와 같은 이유). kube-prometheus-stack의 Operator·CRD 없이 Prometheus 설정 파일 하나로 긁는다 — 지표 출처가 넷뿐이라 Operator가 줄여 주는 일보다 늘리는 구성이 많다.

```
ronanlab-infra/
  platform/monitoring/
    kustomization.yaml       namespace monitoring, 리소스 목록
    README.md                처음 한 번(Namespace·Secret·Application), 크기 근거
    prometheus/              ServiceAccount·RBAC·ConfigMap(scrape 설정)·StatefulSet(PVC 5Gi)·Service
    grafana/                 Deployment·Service·데이터소스 ConfigMap
    node-exporter/           DaemonSet(hostNetwork :9100)·headless Service
    kube-state-metrics/      ServiceAccount·RBAC·Deployment·Service
  platform/argocd/applications/monitoring.yaml   Application(수동 Sync·prune 없음·finalizer 없음)
```

| 항목 | 값 |
| --- | --- |
| 이미지 | prometheus v3.15.0, grafana 13.2.3, node-exporter v1.12.1, kube-state-metrics v2.19.1(client-go 1.35 = 클러스터 v1.35.9) |
| 수집 주기 | 30초 |
| 보존 | 7일, 그리고 4GB(PVC 5Gi보다 먼저 지운다) |
| 저장소 | local-path PVC 5Gi — PV가 처음 붙은 노드에 묶인다 |
| 노출 | 전부 ClusterIP. 확인은 port-forward |
| Namespace | 사람이 만든다(Secret grafana-admin이 거기 있다). Application은 `CreateNamespace=false` |
| 배치 제약 | 없다. node-exporter만 control-plane taint를 견딘다(m-k8s 지표가 빠지지 않게) |

**긁는 것**: Prometheus 자신, node-exporter, kubelet cAdvisor(1절에 쓰는 지표 7개만 남김), kube-state-metrics(객체 12종만), 주석 단 Pod, Milvus(`up`만).
**긁지 않는 것**: apiserver·kubelet `/metrics` — 시계열이 가장 많고 1절에 쓰지 않는다.

**Requests/Limits** (근거는 `platform/monitoring/README.md` "크기")

| 구성 | requests | limits |
| --- | --- | --- |
| Prometheus | 100m / 384Mi | 500m / 768Mi |
| Grafana | 50m / 128Mi | 250m / 256Mi |
| node-exporter(노드마다) | 20m / 32Mi | 100m / 64Mi |
| kube-state-metrics | 20m / 64Mi | 100m / 128Mi |
| 합 | 270m / 704Mi | 1,370m / 1,408Mi |

**왜 8192 뒤인가**: 2026-10-18 실측으로 w3의 limits 합이 3,412Mi(노드 3,912Mi의 89%)다. Prometheus가 w3에 뜨면 limits가 4,244Mi로 노드 용량을 넘는다. requests로는 어느 노드든 들어가지만, 여러 Pod가 동시에 limit까지 쓰면 OOM이 난다. 배치 제약으로 피하지 않는다 — 8192에서는 필요 없고, 넣으면 다시 걷어내야 한다.

---

### 3. 대시보드

△ 없다. Grafana의 `/var/lib/grafana`는 emptyDir라 UI에서 만든 대시보드는 Pod를 다시 만들면 사라진다. 남길 대시보드는 JSON을 ConfigMap으로 넣어 provisioning한다 — 데이터소스와 같은 방식. 1절 지표를 정한 뒤 노드·Pod·앱 세 장으로 만든다.

**외부 노출**: △ 정하지 않았다. grafana.ronanlab.dev로 열려면 터널 ConfigMap에 호스트를 더하고 Access 정책을 붙여야 한다 — 터널 설정은 네 호스트가 한 파일에 있어 함께 다룬다(13번 2-3절).

---

### 4. 남은 한계

- [ ]  Grafana 대시보드가 emptyDir에 있다 — 대시보드 ConfigMap을 만들기 전까지 UI에서 만든 것은 재시작하면 사라진다
- [ ]  Prometheus가 한 대다 — PV가 묶인 노드를 비우면(drain) Prometheus도 그동안 멈춘다
- [ ]  Ollama·search-service 응답 여부는 blackbox-exporter가 없어 보지 못한다
- [ ]  앱 지표가 없다 — petmint `/metrics`부터 붙여야 1절 앱 항목이 들어온다
- [ ]  알림이 없다 — Alertmanager는 알림 설계 뒤

---

### 5. 검증 항목 (8192로 올린 뒤 저녁에 실행)

**적용 전**

- [ ]  노드 네 대 모두 8192로 올라왔는가(`kubectl top nodes`, `free -m`) — 다시 재서 2절 판단이 그대로인지 본다
- [ ]  `kubectl create namespace monitoring`, Secret `grafana-admin` 생성(README "처음 한 번")
- [ ]  `kubectl apply -f platform/argocd/applications/monitoring.yaml` 뒤 monitoring만 Sync — petmint Application은 건드리지 않는다

**뜨는가**

- [ ]  Pod 전부 Running·Ready: prometheus-0, grafana, kube-state-metrics, node-exporter ×4(m-k8s 포함)
- [ ]  PVC `data-prometheus-0`가 Bound(local-path)
- [ ]  Prometheus Status → Targets: node-exporter 4/4, kubelet-cadvisor 4/4, kube-state-metrics 1/1, prometheus 1/1 모두 UP
- [ ]  milvus 대상이 UP(호스트 :9091에 닿는가)
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
