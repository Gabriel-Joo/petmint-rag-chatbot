15_monitoring.md 에서 떼어 낸 구현 기록(2026-11-19 문서 정리 B단계). 지금 설계는 docs/02_pipeline/15_monitoring.md

아래는 처음 설계(2026-10-18)다. 설치(2026-11-10)하며 바뀐 값이 많아 지금 구성과 다르다. 지금 구성은 본문 1절에 있다.

## 구성, 매니페스트로 남긴다 (처음 설계, 옛 2절)

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

## 대시보드 (처음 설계, 옛 3절)

△ 없다. Grafana의 `/var/lib/grafana`는 emptyDir라 UI에서 만든 대시보드는 Pod를 다시 만들면 사라진다. 남길 대시보드는 JSON을 ConfigMap으로 넣어 provisioning한다 — 데이터소스와 같은 방식. 1절 지표를 정한 뒤 노드·Pod·앱 세 장으로 만든다. <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 다름: emptyDir와 ConfigMap provisioning은 맞고(apps/monitoring/grafana/deployment.yaml:2, :72-85), 대시보드는 「없다」가 아니라 petmint, runshoes 두 장이 있다(apps/monitoring/kustomization.yaml:31-35). 처음 설계 기록이라 글은 그대로 둠 -->

**외부 노출**: △ 정하지 않았다. grafana.ronanlab.dev로 열려면 터널 ConfigMap에 호스트를 더하고 Access 정책을 붙여야 한다 — 터널 설정은 다섯 호스트가 한 파일에 있어 함께 다룬다(13번 2-3절). [docs:02_pipeline/13_access_and_tunnel.md:125]

## 검증 항목, 8192로 올린 뒤 저녁에 실행 (처음 설계, 옛 5절)

**적용 전**

- [ ]  노드 네 대 모두 8192로 올라왔는가(`kubectl top nodes`, `free -m`) — 다시 재서 2절 판단이 그대로인지 본다
- [ ]  `kubectl create namespace monitoring`, Secret `grafana-admin` 생성(README "처음 한 번")
- [ ]  `bootstrap/root-app.yaml`의 `exclude: 'monitoring/app.yaml'` 줄을 지우고 push → 루트가 Application을 만든 뒤 monitoring만 Sync — petmint Application은 건드리지 않는다 <!-- 인프라 확인(2026-11-19 인프라 관리자 답, ronanlab-infra fd9c6cc 판): 다름: exclude 줄은 2026-11-10에 지워 monitoring Application이 이미 들어갔고(bootstrap/root-app.yaml:29, apps/monitoring/app.yaml:2) 2026-11-11부터 자동 Sync다(apps/monitoring/app.yaml:5-6). 처음 설계 기록이라 글은 그대로 둠 -->

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
