# deploy — 펫퍼민트 K8s 매니페스트

14번 1-7절 "이주 때 할 일"의 매니페스트. 네임스페이스 `petmint`. Jenkins를 붙이면 별도 매니페스트 저장소로 옮긴다(14번 1-5절).

```
kustomization.yaml     네임스페이스·이미지 태그(images.newTag) — 태그는 여기서만 바꾼다
namespace.yaml
mysql/                 StatefulSet + headless Service. PVC(local-path 10Gi)는 Pod·StatefulSet을 지워도 남는다(Retain)
data/pvc.yaml          약관(chunks, graph) + 고객 시드 픽스처 볼륨 petmint-data
data/loader-pod.yaml   적재용 임시 Pod — kustomization에 없다(scripts/load-data.sh가 띄우고 지운다)
app/configmap.yaml     비밀 아닌 접속 정보. GPU 호스트 주소 3개는 자리만(gpu-host.invalid) — 채워야 한다
jobs/init-db.yaml      초기화 Job: bootstrap → migrate(petmint) → migrate(insurance_core) → seed --if-empty
app/                   Deployment(replicas 1, 한 Pod씩 롤링) · Service · Ingress(petmint.ronanlab.dev)
scripts/               create-secrets.sh · load-data.sh · apply.sh
```

## 처음 적용하는 순서

```bash
# 0. ConfigMap의 GPU 호스트 주소 3개를 채운다(app/configmap.yaml) — VM 사설 네트워크의 호스트 쪽 주소(14번 1-4절)
#    PETMINT_OLLAMA_URL / PETMINT_SEARCH_URL / PETMINT_MILVUS_URL. 안 채우면 Milvus 접속에서 기동이 실패한다

# 1. Secret — 무작위 값으로 클러스터에 직접 만든다. 이미 있으면 건드리지 않는다
deploy/scripts/create-secrets.sh
#    Harbor 프로젝트가 private이면: HARBOR_USER=... HARBOR_PASSWORD=... deploy/scripts/create-secrets.sh

# 2. 전체 적용 — MySQL·볼륨·Job·앱이 한꺼번에 들어간다
deploy/scripts/apply.sh
#    이 시점에는 볼륨이 비어 있어 Job이 "시드 픽스처가 없다"로 재시도하고, 앱은 initContainer(wait-db)에서 기다린다.
#    apply.sh는 Job 완료를 기다리므로 3을 다른 터미널에서 하거나, 2를 kubectl apply -k deploy/로 대신한다

# 3. 약관·시드 적재 — 리포가 있는 호스트에서
deploy/scripts/load-data.sh
#    → Job이 다음 재시도에서 시드까지 끝내고 → wait-db가 풀려 앱이 뜬다
```

이후 배포(이미지 태그 변경)는 `kustomization.yaml`의 `newTag`를 바꾸고 `deploy/scripts/apply.sh`.

## 순서 보장 — 초기화 Job이 앱보다 먼저

| 적용 방식 | 무엇이 보장하나 |
| --- | --- |
| ArgoCD | sync-wave: namespace(-1) → MySQL·볼륨·ConfigMap(0) → Job(1, Sync hook — 끝날 때까지 기다린다) → 앱(2) |
| kubectl 직접 | 앱 Pod의 initContainer `db.wait_ready`가 petmint·insurance_core 마이그레이션 전부 + 원장 시드를 확인할 때까지 기다린다 |

Job의 Pod 템플릿은 바꿀 수 없어서, 태그를 바꾸고 `kubectl apply -k`만 하면 Job이 `field is immutable`로 실패한다.
`apply.sh`는 끝난 Job을 지우고 적용한다. Job은 여러 번 돌려도 같다 — bootstrap·migrate는 멱등이고 시드는 `--if-empty`라
원장(손으로 바꾼 등급 등)을 픽스처로 되돌리지 않는다. ArgoCD는 hook의 `BeforeHookCreation`이 같은 일을 한다.

## 약관·시드 적재 — 제안: 지금은 kubectl cp, 다음 단계는 호스트 NFS 읽기 전용

약관은 외부로 나가면 안 된다(01번). 두 방법 다 사설 네트워크 안에서만 오간다.

| | kubectl cp (`load-data.sh`, 채택) | 초기화 Job이 당겨오기 |
| --- | --- | --- |
| 경로 | 호스트 → API 서버 → 임시 Pod → PVC | Job → (호스트의 어떤 서버) → PVC |
| 새로 여는 것 | 없음 | 호스트에 약관을 내주는 서버(HTTP·rsync 등) — 또 하나의 노출면이고 인증을 붙여야 한다 |
| 자동화 | 사람이 돌린다(약관이 바뀔 때만) | sync마다 자동 |
| 재현성 | `MANIFEST.sha256`을 볼륨에 함께 남긴다 | 같음 |

약관은 재색인할 때만 바뀌고, 그때는 어차피 호스트에서 사람이 파이프라인을 돌린다. 그 끝에 `load-data.sh` 한 줄을
붙이는 것이 새 서버를 여는 것보다 노출면이 작다.

**남는 문제는 드리프트다.** 검색(Milvus 색인)은 호스트의 `data/chunks`로 만들고, 앱은 PVC의 복사본을 읽는다.
재색인하고 적재를 잊으면 둘이 어긋난다 — 그래프·청크 정합성은 ContextBuilder가 기동 때 보지만, 청크와 Milvus의
정합성은 아무도 보지 않는다. 다음 단계로 **호스트의 data/chunks·data/graph를 NFS로 읽기 전용 export하고 PV(ReadOnlyMany)로
붙이는 것**을 제안한다. 복사본이 없어져 드리프트가 사라지고, ReadOnlyMany라 앱 replicas를 노드 여러 대에 펼칠 수도 있다
(지금 local-path는 노드 하나에 묶인다).

## 확인할 것(적용 전에)

- **Harbor 이미지 당기기**(2026-10-15 해결): kubelet은 클러스터 DNS를 쓰지 않아 노드 `/etc/hosts`로 간다.
  노드 4대가 `192.168.122.240 harbor.ronanlab.dev`(ingress-nginx의 MetalLB VIP, 80/443)를 갖고, Harbor Ingress는
  Let's Encrypt 인증서(cert-manager DNS-01)를 단다 — containerd 설정 없이 검증을 켠 채 당긴다(설정은 ronanlab-infra `platform/`).
  남은 것은 인증 하나: Harbor `petmint` 프로젝트가 비공개라 pull 전용 robot 계정으로
  `HARBOR_USER=... HARBOR_PASSWORD=... deploy/scripts/create-secrets.sh` 를 돌려 `harbor-pull`을 만들어야 한다
  (없으면 `pull access denied … no basic auth credentials`)
- **GPU 호스트 방화벽**: VM 사설 네트워크에서 11434·8100·19530이 열려 있어야 한다
- **WebSocket**: Ingress 읽기·쓰기 제한을 1시간으로 늘렸다. 그 사이 연결은 uvicorn ping(20초)이 유지한다.
  Cloudflare 쪽 WebSocket 제한은 별도다 — 끊기면 프런트가 다음 질문 때 다시 연결한다

## 검증 기록 (2026-10-15, 로컬 kind 클러스터 — 실제 클러스터에는 적용하지 않음)

kind v0.27.0(k8s 1.32) + ingress-nginx 1.12.0, `local-path` StorageClass, 앱 이미지를 Harbor 이름·태그로 넣어 위 순서대로 적용.

- Secret 평문 없음 — 매니페스트에는 Secret 이름·키만
- 빈 볼륨: Job이 bootstrap·migrate 두 벌까지 하고 "시드 픽스처가 없다 … 볼륨에 넣었는지 확인"으로 재시도, 앱은 wait-db에서 대기(크래시 없음)
- 시드만 넣음: Job 완료 → 앱이 `PolicyDataError: 약관 데이터가 없다 … /var/lib/petmint/chunks/petmint_강아지.json, …`로 CrashLoopBackOff
- 전부 넣음: 앱 Ready. Ingress 경유 `/`(React)·`/api/customers`(10명)·조항 원문 응답
- WS: Ingress 경유로 질문 → 75초 쉼(클라이언트 ping 끔, nginx 기본 제한 60초) → 같은 연결로 다음 턴 정상
- 태그 0.1.0 → 0.1.1: 새 ReplicaSet 준비 뒤 옛 Pod 종료, 롤링 중 90초간 요청 415건 실패 0. Job도 0.1.1로 다시 돌고 시드는 건너뜀
- MySQL Pod 삭제 → 같은 PVC로 다시 떠 세션·턴 그대로(앱 재시작 없이 재접속). StatefulSet까지 지워도 PVC가 남아 그대로
