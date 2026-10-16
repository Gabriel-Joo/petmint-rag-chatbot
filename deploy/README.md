# deploy — 펫퍼민트 K8s 매니페스트

14번 1-7절 "이주 때 할 일"의 매니페스트. 네임스페이스 `petmint`. Jenkins를 붙이면 별도 매니페스트 저장소로 옮긴다(14번 1-5절).

```
kustomization.yaml     네임스페이스·이미지 태그(images.newTag) — 태그는 여기서만 바꾼다
namespace.yaml
mysql/                 StatefulSet + headless Service. PVC(local-path 10Gi)는 Pod·StatefulSet을 지워도 남는다(Retain)
data/nfs.yaml          약관(chunks, graph)·고객 시드 픽스처 — 호스트 NFS 읽기 전용 PV 3개(ReadOnlyMany) + PVC
app/configmap.yaml     비밀 아닌 접속 정보. GPU 호스트(Ollama·Milvus)는 192.168.122.1, search-service는 아직 없어 자리만(.invalid)
jobs/init-db.yaml      초기화 Job: bootstrap → migrate(petmint) → migrate(insurance_core) → seed --if-empty
app/                   Deployment(replicas 2, 노드 분산, 한 Pod씩 롤링) · PDB(minAvailable 1) · Service · Ingress(petmint.ronanlab.dev)
scripts/               host-nfs-setup.sh(호스트, sudo) · create-secrets.sh · apply.sh
```

## 처음 적용하는 순서

**`app/fixtures/customers.json`은 저장소에 없다.** 가짜 데이터지만 고객 이름·전화번호 모양이라 git에서 뺐다(01번 "외부 유출 0건"을 모양 기준으로).
`app/fixtures/customers.example.json`을 복사해 채운 뒤 시드를 돌린다 — 로컬은 `python -m db.seed_insurance_core`, 클러스터는 초기화 Job이
호스트 NFS로 같은 파일을 읽는다(아래 0).

```bash
cp app/fixtures/customers.example.json app/fixtures/customers.json   # 그리고 값을 채운다
```

```bash
# 0. 호스트(GPU 머신)에서 약관·시드 디렉터리를 NFS 읽기 전용으로 공유한다 — 한 번만. 워커에는 nfs-common이 있어야 한다(Vagrantfile provision)
sudo deploy/scripts/host-nfs-setup.sh

#    ConfigMap의 GPU 호스트 주소(app/configmap.yaml) — VM 사설 네트워크의 호스트 쪽 주소(14번 1-4절)
#    PETMINT_OLLAMA_URL·PETMINT_MILVUS_URL은 192.168.122.1로 채웠다. PETMINT_SEARCH_URL은 search-service를 띄우면 채운다

# 1. Secret — 무작위 값으로 클러스터에 직접 만든다. 이미 있으면 건드리지 않는다
deploy/scripts/create-secrets.sh
#    Harbor 프로젝트가 private이면: HARBOR_USER=... HARBOR_PASSWORD=... deploy/scripts/create-secrets.sh

# 2. 전체 적용 — MySQL·볼륨·Job·앱이 한꺼번에 들어간다. 약관은 NFS에 이미 있으므로 적재 단계가 없다
deploy/scripts/apply.sh
#    Job이 시드까지 끝내면 앱 initContainer(wait-db)가 풀려 앱이 뜬다
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

## 약관·시드 — 호스트 NFS 읽기 전용 (2026-10-16부터. 그 전에는 local-path PVC + kubectl cp)

약관은 외부로 나가면 안 된다(01번). NFS는 사설망(192.168.122.0/24)에만 열고, 호스트 ufw는 virbr0에서 오는 2049만 받는다.

```
호스트 리포 data/chunks ─ bind,ro ─ /srv/nfs/petmint/chunks ─┐
           data/graph  ─ bind,ro ─ /srv/nfs/petmint/graph  ─┼─ NFSv4.2 ro, all_squash ─ PV(ReadOnlyMany) ─ 앱 Pod 2개
           app/fixtures ─ bind,ro ─ /srv/nfs/petmint/fixtures ┘                          └─ fixtures는 초기화 Job만
```

- **드리프트가 없다.** Milvus 색인을 만든 그 파일을 앱이 읽는다. 복사본·적재 절차(`load-data.sh`)가 없어졌다
- **약관을 바꾸면 앱을 재시작한다.** 파일은 Pod에서 바로 보이지만 앱은 기동 때 메모리에 올린다:
  `kubectl -n petmint rollout restart deploy/petmint-app` (한 Pod씩 바뀐다 — 요청은 끊기지 않는다)
- **노드에 묶이지 않는다.** replicas 2를 required anti-affinity로 노드 둘에 둔다. 롤링 때는 2+1개라 워커 3대가 다 필요하다 —
  워커 하나가 빠진 동안 롤링하면 새 Pod가 Pending인 채 멈춘다(옛 Pod 둘이 계속 받는다)
- **읽기 전용은 세 겹이다.** 호스트 export `ro` · PV `readOnly`·mountOptions `ro` · Pod volumeMount `readOnly`.
  워커에서 rw로 마운트해도 서버가 `Read-only file system`으로 막는다
- **호스트가 단일 장애점이 하나 더 는다.** 다만 Ollama·Milvus가 이미 거기 있어 호스트가 죽으면 어차피 서비스가 안 된다(14번 4절).
  마운트는 `hard`(기본값)라 호스트가 사라지면 파일 읽기가 멈춰 기다린다 — 기동 중이면 startupProbe가 3분 뒤 재시작한다
- **파일 권한**: all_squash라 nobody로 읽는다. 파일 644·디렉터리 755여야 한다 — 600으로 만들어진 파일은 Pod에서 못 읽는다
- **노드 drain**: 워커마다 local-path PVC를 쓰는 Pod(MySQL·Harbor·Jenkins)가 있어 노드 전체 drain은 그 Pod들을 Pending으로 만든다.
  앱만 옮길 때는 `kubectl drain <노드> --pod-selector=app.kubernetes.io/name=petmint-app --ignore-daemonsets` → `kubectl uncordon <노드>`

## 확인할 것(적용 전에)

- **Harbor 이미지 당기기**(2026-10-15 해결): kubelet은 클러스터 DNS를 쓰지 않아 노드 `/etc/hosts`로 간다.
  노드 4대가 `192.168.122.240 harbor.ronanlab.dev`(ingress-nginx의 MetalLB VIP, 80/443)를 갖고, Harbor Ingress는
  Let's Encrypt 인증서(cert-manager DNS-01)를 단다 — containerd 설정 없이 검증을 켠 채 당긴다(설정은 ronanlab-infra `platform/`).
  남은 것은 인증 하나: Harbor `petmint` 프로젝트가 비공개라 pull 전용 robot 계정으로
  `HARBOR_USER=... HARBOR_PASSWORD=... deploy/scripts/create-secrets.sh` 를 돌려 `harbor-pull`을 만들어야 한다
  (없으면 `pull access denied … no basic auth credentials`)
- **GPU 호스트 방화벽**: VM 사설 네트워크에서 11434·8100·19530(도커 포트 — ufw를 거치지 않는다)과 2049(NFS, `host-nfs-setup.sh`가 ufw에 연다)
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

## 검증 기록 (2026-10-16, 실제 클러스터 — 태그 4e81fa250169)

위 순서대로 적용. kubectl은 m-k8s에만 있어 호스트에서 `kubectl kustomize deploy/`로 렌더해 m-k8s의 `kubectl apply -f -`로 넣었다.
적재는 당시 `load-data.sh`와 같은 경로(API 서버 → exec)로 tar를 흘려 넣었다 — m-k8s 디스크에 약관을 남기지 않는다(같은 날 NFS로 바꿨다).

- GPU 호스트: 워커 3대의 Pod에서 `192.168.122.1:11434/api/tags` 200, `:19530` 컬렉션 목록(petmint_dog, petmint_cat). 앱 Pod 안에서도 같다. 8100은 닫힘(search-service 없음)
- 적재: 9개 파일 sha256 전부 일치(MANIFEST.sha256). Job 5초 완료 — 마이그레이션 petmint 4개·insurance_core 1개, 고객 10·반려동물 15·특약 37
- 앱: MetalLB VIP·터널 원점(ClusterIP:443) 경유로 `/`·`/api/customers`(10명)·조항 원문(Milvus에서 읽음) 200, WS 한 턴(더미) 끝까지
- MySQL: 상담 1건·턴 1건을 남기고 Pod 삭제 → 같은 PVC로 다시 떠 그대로(앱 재시작 없이 재접속). StatefulSet까지 지우고 다시 만들어도 같은 PV가 붙어 그대로
- 롤링: Harbor에 태그가 하나뿐이라 같은 이미지를 digest 표기(`@sha256:204ed1…`)로 바꿔 Pod 스펙을 바꿨다 → 새 ReplicaSet 준비 뒤 옛 Pod 종료.
  태그 표기로 되돌리는 롤링까지 두 번, 부하(HTTP 3종 동시·WS 5초마다 질문) 속에서 HTTP 6675건·5012건 실패 0.
  WS는 매번 옛 Pod가 내려갈 때 1012(service restart)로 한 번 끊기고 다시 연결해 이어졌다(설계대로 — 위 Deployment 주석). Job은 다시 돌아 시드를 건너뜀
- 검증용 상담·턴은 지웠다(sessions·turns·turn_scope·retrieved·feedback 0건). 원장은 고객 10명 그대로
- `PETMINT_TITLE_LLM`은 GPU 실험 중이라 "0" — 제목은 첫 질문 첫 줄

## 검증 기록 (2026-10-16, 실제 클러스터 — 호스트 NFS 읽기 전용 + replicas 2)

- 호스트: exports 3개 `192.168.122.0/24(ro,all_squash)`, bind mount 3개 ro, 듣는 포트 2049 하나. v3 마운트는 `Connection refused`
- 워커에서 rw로 마운트 → root·일반 사용자 모두 `Read-only file system`. nobody로 읽은 바이트 수가 호스트 파일 합과 같다
- 적용(부하 중): HTTP 6719건 실패 0. 앱 Pod 2개가 w3·w1에 — 둘 다 NFS ro 마운트, 약관 8개 sha256 호스트와 일치, 조항 원문·고객 10명 응답,
  `chunks/`·`graph/`에 touch → `Read-only file system`. fixtures도 Job과 같은 uid로 읽힘(sha256 일치)·쓰기 막힘
- 호스트에서 `data/chunks`에 파일을 만들고·고치고·지우면 두 Pod가 재적재 없이 바로 본다(실제 청크는 건드리지 않고 .txt로)
- w3 drain(`--pod-selector`, 앱 Pod만) 중 HTTP 5621건 실패 0, 대체 Pod는 w2에. PDB ALLOWED DISRUPTIONS 1. uncordon
- local-path PVC `petmint-data` 삭제 → Job 재실행·`rollout restart`(부하 중 HTTP 5606건 실패 0, 롤링 때 세 번째 Pod는 w3), 앱 로그 오류 0
- WS는 롤링·restart 때 옛 Pod가 내려가며 1012로 한 번 끊기고 다시 연결된다(위와 같음). drain 때는 붙어 있던 Pod가 남아 끊기지 않았다
- 검증용 상담(`no-access-header@petmint`)과 턴 로그는 지웠다. 브라우저에서 만든 상담 3건은 그대로
