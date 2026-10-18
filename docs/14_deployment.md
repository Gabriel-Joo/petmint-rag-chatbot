> 상태: 설계 확정, 구현 중. 이미지·CI는 2026-10-15, 클러스터 이주·ArgoCD는 2026-10-16 완료.
> search-service와 답변 생성은 코드만 들어갔고(2026-10-18) 아직 배포 전이라, 클러스터의 WS는 더미 답변을 돌려준다.

#### 0. 한 줄 요약

GPU를 쓰는 것은 호스트에 남기고 나머지를 Pod로 올린다. **약관과 고객 데이터는 이미지에 담지 않는다** — 이미지가 레지스트리를 거쳐 도는 동안 데이터는 클러스터 안에만 있어야 한다.

---

#### 1. 최종 설계

#### 1-1. 무엇을 컨테이너로 만드는가

| 프로세스 | 위치 | 이유 |
| --- | --- | --- |
| Ollama | GPU 호스트 | 모델 추론에 GPU |
| search-service | GPU 호스트 | KURE 임베딩 + bge-reranker가 GPU. △ 코드 작성(2026-10-18, `search_service/`), 호스트 기동 전 |
| Milvus | 호스트 도커 → Pod 가능 | GPU를 쓰지 않는다. search-service와 함께 판단한다  |
| MySQL | 호스트 도커 → Pod | GPU를 쓰지 않는다(12번 1-2절). ✓ 2026-10-16 Pod로 이주 |
| FastAPI + React 빌드물 | Pod | GPU를 쓰지 않는다 |

**컨테이너화 대상은 FastAPI 앱과 React 빌드물뿐이다**(09번 7-3절). 둘을 한 이미지에 담는다 — FastAPI가 빌드물을 StaticFiles로 서빙하므로 Pod 하나로 끝난다.

#### 1-2. 이미지

멀티스테이지로 만든다.

```
1단계  node:20-alpine     web/ 를 빌드해 dist/ 를 만든다 (npm ci → npm run build)
2단계  python:3.14-slim   앱과 1단계의 dist/ 만 담는다. 비root(uid 10001)로 실행
```

최종 이미지 **528MB**. node·npm·tsc는 남지 않는다.

**이미지에 담는 것과 담지 않는 것**

| 담는다 | 담지 않는다 |
| --- | --- |
| `app/`, `db/`, `data/*.py` | `data/chunks/`, `data/graph/` — 약관 |
| `web/dist/` (1단계 산출물) |  `app/fixtures/` 전체 — 고객 원장은 시드 Job이 DB에 넣는다 |
|  | `models/` (47GB), `notebooks/`, `data/faq/`, `data/finetune/` |
|  | `.env` |

`.dockerignore`가 빌드 컨텍스트 단계에서 먼저 걸러낸다. 이미지에 안 들어가는 것과 빌드 과정에 아예 안 실리는 것은 다르다 — 후자여야 중간 레이어에도 남지 않는다.

#### 1-3. 데이터는 런타임에 붙인다

약관과 고객 데이터는 경로를 환경변수로 받아 런타임에 읽는다.

| 변수 | 기본값 | 내용 |
| --- | --- | --- |
| `PETMINT_CHUNKS_DIR` | `data/chunks` | 약관 청크
 `컨테이너에서는 /var/lib/petmint/chunks (Dockerfile ENV)` |
| `PETMINT_GRAPH_DIR` | `data/graph` | 참조 그래프
`컨테이너에서는 /var/lib/petmint/graph (Dockerfile ENV)` |

**없으면 기동이 실패한다.** `exit 3`과 함께 빠진 파일을 전부 밝히고, 파일이 있어도 청크가 비어 있으면 멈춘다. 조용히 0건이 되면 검색이 아무것도 못 찾는데 원인을 알 수 없다 — 09번 6-1절에서 로더가 `section_name` 불일치에 기동을 실패시키는 것과 같은 판단이다.

개발 중에는 `docker run -v`로 호스트 경로를 붙이고, 클러스터에서는 **NFS 읽기 전용 PV**로 붙인다. 호스트의 `data/chunks`·`data/graph`·`app/fixtures`를 `/srv/nfs/petmint/`에 읽기 전용 bind mount하고 사설망(192.168.122.0/24)에만 NFSv4로 공유한다. 복사본이 없으므로 재색인해도 어긋나지 않는다.

#### 1-4. 접속 정보는 전부 환경변수

| 변수 | 가리키는 곳 |
| --- | --- |
| `PETMINT_DB_HOST` / `PORT` / `NAME` / `USER` / `PASSWORD` | MySQL |
| `PETMINT_MILVUS_URL` | Milvus |
| `PETMINT_OLLAMA_URL` | GPU 호스트의 Ollama |
| `PETMINT_SEARCH_URL` | GPU 호스트의 search-service. △ 미배포라 지금 값은 `search-service-not-deployed.invalid` |
| `PETMINT_WEB_DIST` | React 빌드물 경로 |
| `PETMINT_CORE_DB_*` | 고객 원장(`insurance_core`). 실무에서는 다른 호스트일 수 있어 따로 둔다 |
| `PETMINT_DEFAULT_AGENT` | 내부망 직접 접속처럼 Access 헤더가 없을 때 쓸 상담원 ID |
| `PETMINT_TITLE_LLM` | 세션 제목을 LLM으로 지을지(0/1). 재구축 중이라 지금은 0 |
| `PETMINT_MODEL_BASE` | 일반·사내규정 모드와 재작성기가 쓸 모델 이름 (기본 tri-7b). △ 이미지 빌드·태그 커밋(9029301e8d8d), Sync 확인 전 |
| `PETMINT_MODEL_RAG` | 업무특화 모드가 쓸 어댑터 모델 이름 (기본 tri-7b-rag-1). △ 이미지 빌드·태그 커밋(9029301e8d8d), Sync 확인 전 |

DB 환경변수가 없으면 이름을 밝히며 기동이 실패한다. 코드에 접속 정보를 하드코딩하지 않는다(12번 1-2절).

**Pod에서 호스트를 가리키는 주소는 `localhost`가 아니다.** 클러스터가 VM 위에 있으므로 사설 네트워크의 게이트웨이 주소를 쓴다. Vagrantfile에 고정 IP가 박혀 있어 재부팅해도 바뀌지 않는다.

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

**앱 코드와 매니페스트를 다른 저장소에 둔다.** 한 저장소에 합치면 Jenkins가 태그를 바꿔 push할 때마다 빌드가 다시 돌아 무한루프가 된다. 매니페스트는 클러스터 공용 설정이 있는 `ronanlab-infra`의 `apps/petmint/`에 둔다(1-10절).

**이미지 태그에 버전을 박는다.** `latest`를 쓰지 않는다 — 롤링 중에 어느 Pod가 무엇을 부르는지 알 수 없게 된다(10번 8절).

push 하나로 **빌드 → Harbor → 매니페스트 태그 커밋**까지 자동으로 가고, 클러스터 반영은 ArgoCD에서 Sync를 눌러 한다. 매니페스트가 의도대로 들어갔는지 확인한 뒤 자동(`automated`)으로 바꾼다.

ArgoCD는 매니페스트만 본다. 이미지는 각 노드의 kubelet/containerd가 Harbor에서 직접 당기고, 경로는 `/etc/hosts`에 박은 `192.168.122.240`(MetalLB VIP)이다.

#### 1-6. 자동화 경로는 Access를 거치지 않는다

| 연결 | 어디로 | Access |
| --- | --- | --- |
| Jenkins → Harbor | 클러스터 내부 Service | 거치지 않음 |
| ArgoCD → Harbor | 클러스터 내부 Service | 거치지 않음 |
| ArgoCD → GitHub | 공개 인터넷 | 무관 |
| 사람 → ArgoCD·Harbor·Jenkins | 브라우저 | Access(운영자만) |

기계가 공개 호스트명으로 나갔다 들어오면 Access에 막힌다. 그래서 자동화는 전부 내부 주소로 간다. 사람이 브라우저로 들어가는 경로만 Access가 막는다(13번 1-3절).

> Ollama는 예외다. `ollama.ronanlab.dev`가 Service Token으로 열려 있지만, 그것은 클러스터 밖에서 부를 때의 경로다. Pod는 사설 네트워크로 직접 호출한다 — 같은 물리 머신 안인데 Cloudflare 엣지를 왕복하면 스트리밍 토큰마다 지연이 쌓인다.
> 

#### 1-7. 클러스터 진입점 — MetalLB + cert-manager

노드가 Harbor에서 이미지를 당기려면 **표준 포트(443)가 실제로 열려 있어야 한다.** Harbor는 토큰 주소를 `externalURL + /service/token`으로 알려주는데 그 값에 포트가 없으므로 노드는 443으로 간다. NodePort(31925)로는 닿을 수 없다.

MetalLB(L2)로 사설망에 VIP를 하나 두고, ingress-nginx를 LoadBalancer로 바꿔 그 VIP에 80·443을 연다.

| 항목 | 값 |
| --- | --- |
| VIP | 192.168.122.240 |
| IP 풀 | .240~.250, `autoAssign: false` |
| 알림 인터페이스 | eth1 (사설망) |
| 기존 NodePort | 30517 / 31925 유지 |
| 터널이 보는 곳 | ClusterIP — Service 타입을 바꿔도 영향이 없다 |

인증서는 cert-manager + Let's Encrypt **DNS-01**로 받는다. DNS-01이라 인바운드 포트를 열 필요가 없고, Cloudflare API 토큰(Zone·DNS·Edit / Zone·Zone·Read)만 있으면 된다.

설정은 `ronanlab-infra/platform/` 아래에 둔다 — `metallb/`, `ingress-nginx/{base,overlay}/`, `cert-manager/`, `coredns/`.

**ingress-nginx는 kustomize 로 묶는다.** 업스트림 매니페스트를 base 에 원본 그대로 두고 Service 패치를 overlay 로 얹는다. base 만 apply 하면 NodePort 로 돌아가므로 양쪽 주석에 "overlay 만 apply"를 적어 두었다. 패치에 `protocol: TCP` 가 없으면 Service ports 의 병합 키(port+protocol)가 맞물리지 않아 nodePort 가 무작위로 뽑힌다.

#### 1-8. 이주 때 할 일

- ✓ MySQL을 StatefulSet + PVC로 올리고, 계정 정보를 Secret으로 주입
- ✓ 스키마는 초기화 Job으로 — 앱 이미지로 `python -m db.migrate`를 그대로 돌린다
- ✓ 환경변수만 바꾸고 연결 확인
- ✓ `insurance_core`의 마이그레이션과 시드도 초기화 Job에 넣는다

실제 이주(2026-10-16)에서는 약관 청크와 그래프를 **NFS 읽기 전용 PV**로 붙였다. 호스트의 `/srv/nfs/petmint/`를 모든 Pod가 같은 파일로 읽으므로 replicas를 늘려도 드리프트가 없다. DB는 `mysqldump`를 쓰지 않고 픽스처 시드 Job으로 새로 시작했다.

#### 1-9. 파이프라인 — CI (2026-10-15)

✓ 1-5절의 흐름 중 **빌드→push→pull 까지가 이 단계에서 돌아갔다. 배포 자동화는 1-10절이다.**

| 항목 | 값 |
| --- | --- |
| 빌드 | BuildKit rootless v0.33.1. 특권 컨테이너 대신 seccomp·AppArmor만 푼다 |
| 태그 | 커밋 해시(예: 4e81fa250169). latest를 쓰지 않는다 |
| 트리거 | SCM 폴링 2분. webhook 은 Access 에 막힌다 |
| Jenkins 설정 | JCasC + job-dsl. 자격 증명과 Job 을 Helm values 가 만든다 |
| Harbor 계정 | robot 둘로 나눔 — jenkins(push+pull), pull(pull 전용, 노드용) |

**Jenkins 도 매니페스트로 남긴다.** UI 에서 자격 증명과 Job 을 만들면 Jenkins 안에만 남아 Pod 를 다시 만들면 사라지고, 무엇을 어떻게 설정했는지 기록도 안 남는다. MetalLB·cert-manager·ingress 를 전부 `ronanlab-infra` 에 남겨 두고 Jenkins 만 UI 로 하면 거기만 구멍이 된다.

**robot 계정을 둘로 나눈 이유**는 역할이 다르기 때문이다. Jenkins 는 push 하고 노드는 pull 만 한다. 노드 Secret 에 push 권한이 들어가면 Pod 가 레지스트리를 덮어쓸 수 있고, 하나를 바꿀 때 다른 쪽까지 영향받는다.

✓ **앱이 클러스터에서 돈다 (2026-10-16).** MySQL StatefulSet → 약관·시드 적재 → 초기화 Job → 앱 순으로 올렸고, Ingress 경유로 화면·고객 조회·조항 원문·WS 한 턴까지 응답한다. ✗ 약관 적재는 API 서버를 거쳐 Pod 안으로 tar를 흘려 넣어, m-k8s 디스크에 파일이 남지 않는다(아래 — 같은 날 NFS로 바꿨다).

약관 데이터를 tar로 넣던 절차는 같은 날 NFS 읽기 전용 PV로 바꿨다(1-8절). WS는 한 턴까지 응답하는 것을 확인했으나 클러스터에서는 더미 답변이다. △ `answer.py`와 search-service는 코드 작성(2026-10-18), 실행 확인 전 — 배포되어야 진짜 답이 나온다.

#### 1-10. GitOps — ArgoCD (2026-10-16)

✓ 1-5절의 흐름이 **끝까지 돌아간다.** push 하나로 빌드·Harbor·매니페스트 커밋까지 가고, 반영은 Sync를 눌러 한다.

**매니페스트 저장소는 `ronanlab-infra` 를 쓴다.** 새 저장소를 만들지 않는다.

```
ronanlab-infra/
  platform/        클러스터 공용
    metallb/  cert-manager/  ingress-nginx/  coredns/
    argocd/  harbor/  jenkins/
  apps/
    petmint/       앱 매니페스트
    runshoes/      △ 나중에
```

| 항목 | 값 |
| --- | --- |
| Sync 방식 | 수동. prune 꺼두고 finalizer 없음 |
| Namespace | ArgoCD 관리에서 제외. CreateNamespace=false |
| 인증 | deploy key 둘 — argocd-read(읽기), jenkins-write(쓰기) |
| 매니페스트 수신 | Jenkinsfile 에서 `sh 'git clone'` 으로 받는다 |
| 조회 주기 | 3분 |

배포는 이제 **ArgoCD 가 독점한다.** `kubectl apply` 나 `apply.sh` 를 쓰면 상태가 엇갈린다 — 실제로 `kubectl scale --replicas=3` 을 하자 즉시 OutOfSync 로 잡혔고 Sync 하니 Git 값인 2 로 돌아왔다.

---

#### 2. 왜 이렇게 했나

#### 2-1. GPU를 쓰는 것은 호스트에 남긴다

클러스터가 Vagrant VM 위에 있어 GPU가 VM 안으로 들어오지 않는다. PCI 패스스루를 하려면 호스트에서 GPU 드라이버를 떼어내야 하는데, 그러면 호스트의 Ollama를 포기해야 한다.

그래서 **GPU를 쓰는 것은 전부 호스트에, Pod는 네트워크로 호출한다**(09번 7-3절). 생성은 이미 호스트 Ollama를 부르는 구조였으므로 검색도 같은 방식으로 뺐다.

**이것이 임시방편만은 아니다.** 16GB 한 장에 모델 넷이 올라가고, `OLLAMA_MAX_LOADED_MODELS`와 `keep_alive`를 그 예산 안에서 정해야 한다(09번 7-3절). 그 배분을 쿠버네티스 스케줄러에 맡기는 것보다 직접 관리하는 편이 지금은 통제 가능하다. device plugin은 기본적으로 GPU를 통째로 Pod 하나에 주므로, Ollama와 search-service가 둘 다 필요하면 한쪽만 받는다 — time-slicing이나 MPS로 쪼갤 수 있지만 그 자체가 또 하나의 변수다.

현업에서도 GPU 노드를 따로 두고 앱은 일반 노드에 올린다. 구조로는 같다.

#### 2-2. 약관과 고객 데이터를 이미지에 담지 않는다

01번의 **"모델·데이터 사내 서버 상주, 외부 유출 0건"** 원칙 때문이다. 이미지는 Harbor를 거쳐 돌고, Jenkins가 빌드하려면 GitHub에도 있어야 한다. 데이터가 여기저기 복사된다.

private 저장소라도 "사내 서버 상주"는 아니다. 그리고 약관은 실제 보험 상품의 원문이다.

**부수 효과로 CI 문제가 함께 풀린다.** `data/chunks/`는 git에 없으므로, 이미지에 넣으려 하면 `git checkout`만 하는 Jenkins에서 `COPY`가 실패한다. 이미지에서 빼면 그 문제가 사라진다.

**고객 픽스처는 git 에서도 뺀다.** 가짜 데이터지만 이름·전화번호 모양을 하고 있어, 유출 0건 원칙을 데이터 성격이 아니라 모양 기준으로 적용했다. 대신 `app/fixtures/customers.example.json` 을 둔다 — 구조만 같고 값은 명백한 예시(홍길동, 000-0000-0000)다. 저장소를 받은 사람은 그것을 복사해 채운 뒤 시드를 돌린다.

#### 2-3. 고객 데이터는 별도 DB에 둔다

실무에서 고객 데이터는 보험사 기간계 시스템에 있고, 이 챗봇은 그것을 읽어 쓰는 쪽이다. 회사의 데이터인 것은 맞지만 **이 서비스가 소유하지는 않는다.**

복사해 두면 세 가지가 어긋난다 — 원본이 바뀌어도 모르고, 같은 데이터가 두 군데 있어 어느 쪽이 맞는지 생기고, 계약 변경·해지가 기간계에서 일어나는데 챗봇은 따라가지 못한다.

그래서 `insurance_core` DB를 따로 두고 `petmint_app` 계정에 **SELECT 권한만** 준다. 데이터베이스가 다르면 외래키를 걸 수도 없는데, 그것이 곧 경계가 있다는 표시다(12번 4절에서 `customer_id`를 외래키 없이 문자열로 둔 이유와 같다).

**12번 2-2절의 스냅샷 원칙을 실제로 시험할 수 있게 된다.** 고객 등급을 바꿔보려면 전에는 JSON을 고쳐야 했지만, 이제 `UPDATE` 한 줄이면 "외부에서 값이 바뀐 상황"이 그대로 재현된다.

#### 2-4. 데이터가 없으면 조용히 넘어가지 않고 멈춘다

파일이 없거나 비어 있으면 기동을 실패시킨다. 검색 코퍼스가 0건이어도 앱은 멀쩡히 뜨고 답변도 하는데, 모델이 발췌 없이 답하므로 **틀린 답을 자신 있게 한다.** 그 상태로 배포되면 로그를 보기 전까지 모른다.

09번 6-1절에서 고객 픽스처의 `section_name` 불일치에 기동을 실패시키는 것, 12번에서 검색 행 제약을 앱이 아니라 DB의 `CHECK`에 둔 것과 같은 판단이다 — **조용한 실패를 만들지 않는다.**

#### 2-5. 왜 MetalLB인가

세 가지 안이 있었다.

**노드마다 포워더를 두는 방법**은 손댈 범위가 가장 작다. 각 노드에서 443을 31925로 넘기면 클러스터를 전혀 건드리지 않고, 되돌리기도 서비스를 멈추고 hosts 한 줄을 지우면 끝이다. 그러나 인증서 검증을 건너뛰어야 하고, 설정이 노드 OS에 흩어져 GitOps 밖에 남는다. 노드를 늘릴 때마다 반복해야 한다.

**Harbor의 `externalURL`을 내부 주소로 바꾸는 방법**은 설정 한 줄이다. 그러나 그 값은 Harbor 전역이라 웹 UI의 pull/push 안내, 외부 `docker login`, 나중에 붙일 OIDC 리다이렉트까지 모두 내부 포트를 가리키게 된다. http라 자격 증명이 평문으로 오간다.

**MetalLB**는 컴포넌트가 하나 늘지만, 사설망 안의 누구나 표준 포트로 쓸 수 있고 설정이 전부 매니페스트에 남는다. 노드를 늘려도 추가 작업이 없다. 클라우드에서 LoadBalancer 타입이 하던 일을 사설 환경에서 대신하는 것이므로 구조로는 표준에 가깝다.

**바꾸기 전에 되돌릴 방법을 먼저 적었다.** ingress-nginx는 지금 돌고 있는 ArgoCD·Harbor·Jenkins가 모두 거치는 길목이다. 리소스 백업과 `ROLLBACK.md`를 `k8s-cluster/backup/`에 두고 단계마다 생존 확인을 거쳤다.

#### 2-6. Jenkins 가 Harbor 를 부르는 길 — CoreDNS 재작성

클러스터 DNS 에서 `harbor.ronanlab.dev` 를 ingress-nginx 내부 Service 로 돌린다. 노드의 `/etc/hosts` 와 같은 논리를 클러스터 안에서 하는 것이다.

내부 Service(harbor-core)를 직접 부르는 방법은 1-7절의 토큰 주소 문제에 다시 걸린다. 빌드 Pod 에 `hostAliases` 로 ClusterIP 를 박는 안도 있었으나, 그 IP 가 Jenkinsfile 안에 숨어 Service 를 다시 만들면 조용히 깨진다.

CoreDNS 는 **이미지 이름이 어디서나 같아진다는 점**이 크다. 노드도 Pod 도 빌드도 같은 주소를 쓰고, Let's Encrypt 인증서로 검증된다. 나중의 ArgoCD → Harbor 도 같이 풀린다.

적용 전에 같은 버전을 Docker 에 띄워 문법을 확인했고, 적용 뒤 argocd·jenkins·github·Docker Hub 는 공개 주소 그대로 풀리는 것과 터널 4/4 를 확인했다.

#### 2-7. ArgoCD 에 넘길 때 지킨 세 가지

**Namespace 를 ArgoCD 관리에서 뺀다.** `petmint` 네임스페이스에는 cloudflared 터널과 사람이 넣은 Secret 네 개가 있다. 터널이 죽으면 ArgoCD·Harbor·Jenkins 공개 주소까지 함께 죽는다. ArgoCD 가 네임스페이스를 소유하면 prune 이나 Application 삭제 한 번에 이것이 모두 사라질 수 있다. Secret 처럼 사람이 만드는 쪽으로 남긴다.

**deploy key 를 읽기·쓰기로 나눈다.** 토큰(fine-grained PAT)은 만료일이 있어 만료되면 배포가 **조용히 멈춘다** — 2-4절의 "조용한 실패를 만들지 않는다"와 어긋난다. 읽기와 쓰기를 나누는 것은 Harbor robot 을 pull 전용과 push 용으로 나눈 것과 같은 논리다. ArgoCD 키가 새도 저장소를 고칠 수 없다.

**처음엔 수동 Sync 로 둔다.** 매니페스트가 의도대로 반영되는지 눈으로 확인한 뒤 자동으로 바꾼다. 개발은 로컬(uvicorn + vite), 클러스터는 운영만으로 간다 — 단일 환경이라 개발·운영 네임스페이스를 가를 수 없다(4절).

넘겨받는 순간은 안전했다. 처음 상태는 OutOfSync 였고, 14개 리소스의 diff 가 모두 ArgoCD 추적 라벨 하나뿐이었다. Sync 뒤에도 앱 Pod 와 mysql-0 의 UID 가 같아 교체되지 않았다.

---

#### 3. 시도했던 것들

| 시도 | 결과 |
| --- | --- |
| 약관 데이터를 git에 올려 이미지에 담기 | 6.4MB라 크기는 문제가 아니었으나 01번의 외부 유출 0건 원칙에 어긋난다. 런타임 마운트로 바꿨다 |
| 단일 스테이지 이미지 | node와 python을 한 이미지에 담으면 빌드 도구가 최종 이미지에 남는다. 멀티스테이지로 528MB까지 줄였다 |
| `chown -R` 레이어 | 비root 실행을 위해 소유권을 바꿨더니 레이어가 크게 늘었다. 멀티스테이지에서 `--chown`으로 복사하도록 바꿔 569MB → 528MB로 줄였다 |
| `data/rag_context.py`의 pymilvus import를 함수 안으로 | 251MB를 줄일 수 있으나 05·06 노트북과 공유하는 모듈이다. 평가와 서비스가 같은 코드를 쓴다는 원칙(09번 3-3절)을 깨면서까지 줄일 이유가 없고, ContextBuilder를 붙이면 실제로 필요해진다. 손대지 않았다 |
| GPU 패스스루로 Ollama를 Pod에 | 호스트에서 GPU 드라이버를 떼어내야 한다. 호스트 Ollama를 포기하는 대가가 크다 |
| 검색을 CPU로 돌려 Pod에 | 리랭커가 후보를 쌍으로 비교하는 구조라 지연이 크게 늘어난다. 고객 전화를 받으며 쓰는 도구에 맞지 않는다 |
| 노드 `/etc/hosts`에 Ingress 주소 추가 | 이름은 풀렸으나 443이 열려 있지 않아 connection refused. NodePort는 30000~32767만 쓸 수 있다 |
| containerd mirror 설정 | 레지스트리 주소만 바꾸고 응답으로 받은 토큰 주소는 고치지 않는다. 토큰 단계에서 다시 443으로 간다 |
| MetalLB 기본 설치 | 0.16 차트가 frr-k8s(BGP)를 함께 깐다. Calico가 노드마다 179 포트를 쓰므로 충돌한다. BGP 데몬을 껐다 |
| libvirt DHCP 범위 그대로 | 기본이 .2~.254라 "범위 밖"이 없다. 임대 0건이고 노드는 고정 IP라 .100~.199로 줄였다 |
| DNS 리졸버 1.1.1.1 | 이 망에서 노드·Pod 모두 시간 초과. DNS-01 전파 확인용 리졸버를 8.8.8.8로 바꿨다 |
| Jenkins → Harbor를 내부 Service로 직접 | 토큰 주소가 https라 그대로는 안 된다. 빌드 Pod에 hostAliases로 ClusterIP를 박는 안도 있었으나 그 IP가 Jenkinsfile에 숨어 Service를 다시 만들면 깨진다. CoreDNS 재작성으로 갔다 |
| 매니페스트를 Jenkinsfile의 git 단계로 받기 | Jenkins 폴링은 git·checkout 단계로 받은 저장소까지 감시한다. 저장소를 나눠도 무한루프가 생긴다. `sh 'git clone'`으로 받아 폴링 대상에서 뺐다 |
| ArgoCD 인증을 토큰으로 | fine-grained PAT은 만료일이 있어 만료되면 배포가 조용히 멈춘다. 읽기·쓰기 deploy key 둘로 바꿨다 |

---

#### 4. 남은 한계

- [ ]  **단일 클러스터, 단일 환경이다.** 개발·스테이징·운영을 나누지 않았다. 네임스페이스로 가를 수 있지만 16GB 한 대에 다 올리는 것은 무리다
- [ ]  **GPU 호스트가 단일 장애점이다.** Ollama·search-service·Milvus가 모두 한 대에 있다. 그 머신이 죽으면 Pod가 멀쩡해도 서비스가 안 된다
- [ ]  **Milvus는 아직 호스트 도커다.** GPU를 쓰지 않으므로 Pod로 옮길 수 있으나, standalone이라도 etcd와 MinIO가 따라붙어 자원을 더 먹는다. search-service와 함께 옮길지 판단한다.
- [ ]  **이미지 크기의 절반이 pymilvus다.** pip 레이어 251MB 중 상당 부분이 pandas·numpy·grpc다. 3절 표의 이유로 두었다
- [ ]  **DB 마이그레이션은 되돌아가지 않는다.** 매니페스트는 ArgoCD가 Git 기준으로 되돌리지만 스키마는 아니다. 깨는 변경이 생기면 그때 정한다
- [ ]  **libvirt 관리망(192.168.121.x)은 DHCP다.** VM을 다시 만들면 주소가 바뀐다. 노드 설정에는 고정 IP인 사설망(192.168.122.x)을 쓴다
- [ ]  **ArgoCD는 `ssl-passthrough`를 뺀 상태다.** 나중에 그 플래그를 켜면 붙인 인증서가 쓰이지 않는다
- [ ]  **Jenkins 플러그인이 재시작마다 최신으로 올라간다.** 차트 기본값 `installLatestPlugins: true` 때문이다. 고정하려면 의존 플러그인까지 버전을 적어야 한다. 이미지 태그에 `latest`를 쓰지 않는 것과 같은 문제이므로 재현성이 필요해지면 끈다
- [ ]  **NFS가 호스트 단일 장애점에 더해진다.** 다만 Ollama·Milvus가 이미 거기 있어 호스트가 죽으면 어차피 서비스가 안 된다
- [ ]  **약관을 바꾸면 앱 재시작이 필요하다.** 파일은 Pod에서 바로 보이지만 앱이 기동할 때 메모리에 올린다. 재색인 뒤에는 `rollout restart`가 필요하다
- [ ]  **클러스터 DB는 픽스처 시드로 새로 시작했다.** 로컬 도커 MySQL의 개발 데이터는 옮기지 않았다
- [ ]  **롤링에 워커 3대가 다 필요하다.** 같은 노드에 두 Pod를 두지 않으므로, 롤링 중 잠깐 생기는 세 번째 Pod가 남은 워커에 떠야 한다. 워커 하나가 빠진 동안 롤링하면 새 Pod가 Pending에 멈춘다
- [ ]  앱 리포의 어떤 푸시에도 빌드가 돈다. docs만 고쳐도 새 이미지와 배포 커밋이 생긴다
- [ ]  ArgoCD 초기 admin 비밀번호 Secret이 남아 있다. 비밀번호를 바꾼 뒤 지우는 것이 권고다
- [ ]  **`PETMINT_TITLE_LLM`이 0이다.** 제목 생성이 호스트 GPU를 쓰는데 재구축 실험이 돌고 있어 꺼 두었다. 지금은 첫 질문 첫 줄이 제목이 된다. 실험이 끝나면 1로 돌린다
- [ ]  단일 장애점이 노드마다 흩어져 있다. MySQL은 w1, harbor-registry는 w2, Jenkins는 w3의 local-path에 묶여 있다. 노드 하나가 죽으면 그 서비스가 멈춘다

---

#### 5. 검증 항목

- [x]  빌드 도구가 최종 이미지에 남지 않는가
- [x]  Jenkins 에서 빌드가 끝까지 도는가
- [x]  Harbor 에 커밋 해시 태그가 올라가는가 (digest 일치)
- [x]  노드 세 대에서 그 태그를 당길 수 있는가
- [x]  자격 증명이 빌드 로그에 노출되지 않는가
- [x]  컨테이너를 띄워 `/`에 접속하면 React 화면이 나오는가
- [x]  `/api`와 `/ws`가 같은 포트에서 동작하는가
- [x]  `.env`가 이미지에 없는가
- [x]  환경변수로 DB·Milvus·Ollama·search-service 주소를 바꿀 수 있는가
- [x]  약관 데이터가 이미지에 없는가
- [x]  마운트 없이 띄우면 빠진 파일을 밝히며 기동이 실패하는가
- [x]  같은 이미지로 `python -m db.migrate`가 도는가
- [x]  MySQL을 StatefulSet으로 올린 뒤 pod를 지워도 데이터가 남는가
- [x]  이미지 태그를 바꾸면 롤링이 도는가 (태그 교체는 다음 빌드 후)
- [x]  앱 Pod 두 개가 서로 다른 노드에서 뜨는가
- [x]  호스트에서 청크를 고치면 Pod가 재적재 없이 보는가
- [x]  푸시하면 Jenkins가 빌드해 Harbor에 태그가 올라가는가
- [x]  Jenkins가 매니페스트 태그를 바꿔 push하는가
- [x]  ArgoCD가 그 변경을 감지하는가 (3분 조회)
- [x]  Sync하면 Pod가 한 대씩 새 태그로 교체되는가 (부하 중 HTTP 7,941건 실패 0)
- [x]  매니페스트 변경이 빌드를 다시 트리거하지 않는가
- [x]  kubectl로 바꾸면 ArgoCD가 OutOfSync로 잡는가
- [x]  Pod에서 호스트의 Ollama·Milvus에 닿는가 (search-service는 아직 없다)
- [x]  롤링 중 HTTP 요청이 실패하지 않는가 — drain 5,621건 실패 0. WS는 1012로 한 번 끊기고 다시 연결된다

### 다음에 할 일

**1. search-service** — △ 코드 작성(2026-10-18, `search_service/`), 호스트 기동과 ConfigMap 주소 교체 전. 이것이 붙어야 검색이 Pod에서 돌고, answer.py와 함께 더미 답변이 진짜 답변이 된다.

**2. 08번 Ragas** — △ 검색 품질 측정. 오늘 top 3 적중 81/97을 쟀고,
Context Recall을 제대로 보려면 이것이 필요하다.