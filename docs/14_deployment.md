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
| search-service | GPU 호스트 | KURE 임베딩 + bge-reranker가 GPU. ✗ 호스트 기동 전(코드는 2026-10-18 작성, `search_service/`) |
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
| `PETMINT_SEARCH_URL` | GPU 호스트의 search-service. ✗ 미배포라 지금 값은 `search-service-not-deployed.invalid` |
| `PETMINT_WEB_DIST` | React 빌드물 경로 |
| `PETMINT_CORE_DB_*` | 고객 원장(`insurance_core`). 실무에서는 다른 호스트일 수 있어 따로 둔다 |
| `PETMINT_DEFAULT_AGENT` | 내부망 직접 접속처럼 Access 헤더가 없을 때 쓸 상담원 ID |
| `PETMINT_TITLE_LLM` | 세션 제목을 LLM으로 지을지(0/1). 재구축 중이라 지금은 0 |
| `PETMINT_MODEL_BASE` | 일반·사내규정 모드와 재작성기가 쓸 모델 이름 (기본 tri-7b). ✓ 이미지 빌드·태그 커밋·Sync 확인(2026-10-18) |
| `PETMINT_MODEL_RAG` | 업무특화 모드가 쓸 어댑터 모델 이름 (기본 tri-7b-rag-1). ✓ 이미지 빌드·태그 커밋·Sync 확인(2026-10-18). ✗ 지금 값 tri-7b-rag-1은 Ollama에 없다 |

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

약관 데이터를 tar로 넣던 절차는 같은 날 NFS 읽기 전용 PV로 바꿨다(1-8절). ✓ 일반 모드는 클러스터에서 실제 답변을 확인했다(2026-10-18). ✗ search-service는 기동 전 — 업무특화·사내규정은 이것이 붙어야 답이 나온다.

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


#### 1-11. 검색·답 표시 플래그 운영 반영 (2026-10-23)

✓ **운영이 이미지 `f7991c90f22e` + 아래 플래그로 돈다.** 그 전 운영 이미지(b6a7399)는 평가 220 기준선(자동 통과 117) 시점의 코드였다. 같은 평가에서 지금 코드는 플래그를 모두 끄고도 159, 모두 켜면 163이다(rebuild4, 3회 평균 — `data/review/rollout_measure.md`). 117 → 159는 코드(고객 사실·되묻기 정리·코드 답 카드)에서 오고, 플래그가 그 위에 판정 정확 +9.4·판정 거절 −8.3을 더한다. 틀림은 늘지 않았다.

| ConfigMap 키 | 값 | 하는 일 | 측정(그 플래그만 끈 것과 비교) |
| --- | --- | --- | --- |
| `PETMINT_CHUNKS_DIR`·`PETMINT_GRAPH_DIR` | `/var/lib/petmint/chunks/v3`·`graph/v3` | 청크 v3(약관 호·법령박스 분할). NFS 공유 안의 v3 폴더 | 아래 둘과 함께 |
| `PETMINT_SEARCH_VARIANT` | `v3` | search-service가 Milvus `petmint_*_v3`로 찾는다(약관만) | 정확 +3.0, 예외누락 −1.3, 거절 −1.0 |
| `PETMINT_DISPLAY_PARENT` | `1` | v3 조각으로 찾고 모델에게는 부모(원래 청크) 글을 보여 준다 | (v3와 함께) |
| `PETMINT_SEARCH_EXPAND` | `1` | 질의 확장(고객 말 → 약관 말, BM25·리랭커 질의에만) | 정답이 프롬프트에 든 턴 62 → 73, 판정 거절 37.3 → 30.7, 정확 +5.0 |
| `PETMINT_EXPAND_DICT` | `v2` | 동의어 사전 v2(62항목) | 검색 회귀 hit@3 92 → 95, MRR 0.866 → 0.880. 답은 흔들림 안 |
| `PETMINT_ANSWER_TABLES` | `1` | 답이 쓴 발췌의 표를 답 아래에 붙인다 | 답에는 영향 없음(답 뒤에 붙는다). 표 붙은 턴 회당 8.7 |

플래그는 코드 기본값을 바꾸지 않고 ConfigMap에서만 켠다 — 되돌릴 때 ConfigMap만 고치면 된다. 모델(rebuild4)·고객 사실·숫자 가드레일은 그대로다.

**반영 순서 — 앱 먼저, infra 나중.** infra를 먼저 올리면 옛 이미지가 v3 청크 파일을 읽으면서 검색은 옛 Milvus 컬렉션으로 해, 검색 결과와 청크 파일이 어긋난다.

1. petmint 저장소 push → Jenkins가 이미지를 빌드하고 ronanlab-infra에 태그 커밋을 올린다
2. ronanlab-infra에서 `git pull --rebase`로 그 태그 커밋을 받은 뒤 ConfigMap 변경을 push
3. ArgoCD Sync → 초기화 Job(청구 이력 테이블 0002_claims, 비어 있을 때만 시드) → 앱 롤링 재시작. 이미지 태그가 같이 바뀌므로 `rollout restart`는 따로 하지 않는다

호스트는 할 일이 없었다. search-service(질의 확장·variant·사전 판 인자), Milvus v3 컬렉션, NFS의 v3 폴더가 이미 있었다.

**되돌리기.** ConfigMap의 다섯 키를 지우고 청크·그래프 경로를 `/var/lib/petmint/chunks`·`graph`로 돌린 뒤 Sync하고 `rollout restart`하면 "코드만" 상태(159)가 된다. 이미지 태그까지 b6a7399로 돌리면 반영 전 운영이다.

✗ **반영 점검에서 찾은 결함 두 개.**

- variant를 켜면 **사내규정 검색이 503**이었다. Milvus에 `hr_regulation_v3` 컬렉션이 없다(v3는 약관만 다시 잘랐다). 평가 220에는 사내규정 턴이 없어 측정에 드러나지 않았다. Retriever가 variant를 강아지·고양이 검색에만 붙이게 고쳤다(f7991c9, `tests/test_retrieval_variant.py`)
- **사내규정 답의 근거 조항을 열면 422**였다(반영 직후 운영 로그). 조항 원문 API가 처음부터 강아지·고양이만 받았다 — 이번 반영과 무관한 예전 버그다. 사내규정 코퍼스도 받게 고쳤다(f0279c2, `tests/test_articles_route.py`). 이 수정은 다음 push부터 운영에 들어간다

✓ **반영 확인.** Pod 2개 Running, 로그에 오류 0. Pod 안에서 시험 스크립트로 모드마다 질문을 보냈다(시험 세션이 운영 DB에 남는다 — 사용자 허락).

| 모드 | 질문 | 결과 |
| --- | --- | --- |
| 업무특화 | 보험금이 지급기일보다 40일 늦게 나오면 이자 얼마나 붙어요? | 답 + 【별표1】 적립이율 표가 붙음 |
| 업무특화 | 보험수익자가 정확히 누구예요? | 답 + 용어 정의 표, 해당 행 강조 |
| 사내규정 | 연차 개수는 얼마나 있어요?(사용자) · 지각을 몇 번 하면 징계를 받나요? | 답 + 근거 조항(제17·18·33조, 제13조) |
| 일반 | 반려견 산책은 하루에 몇 번이 좋아요? | 답 |

#### 1-12. 보장 여부 질문 플래그 (2026-10-23, d64aea0)

1-11 위에 두 키를 더 켠다. 측정은 평가 220 보이는 세트 3회 평균이다(`data/review/coverage_measure.md`). 판정 정확과 틀림은 판정 대상 턴에 대한 비율로 쓴다. 코드 답이 늘면 판정 대상 턴이 줄기 때문이다.

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_RULE_FIRST` | `1` | 보험금 지급사유·보상하는 손해 조에서, 같은 조의 원칙(제1항)이 참조에만 있으면 본문 앞으로 옮긴다(1안) | 자동 통과 157.0 → 159.7. 정확 47.7% → 52.6%. 틀림 12.4% → 11.6%. 원칙이 참조에만 있던 턴은 회당 15 → 1 |
| `PETMINT_COVERAGE_CODE` | `1` | 그 반려동물의 부담보에 걸리는 보장 질문은 코드가 특약 제2조 ①②④로 답한다. 대기기간에도 걸리면 그 줄을 붙인다. 분류 질문은 모델에게 남긴다(3안′) | 둘 다 켜면 자동 통과 163.0. 정확 53.5%, 틀림 12.1%. 부담보 대상 8문항은 거절 3.3 → 0, 예외누락 1.3 → 0. N축은 16/16 그대로 |

대기기간 결론까지 코드로 내던 첫 3안은 버렸다. 가입 30일 안인 반려동물의 질병 질문을 모두 "30일 이내" 답으로 가져가, 면책 질문(유전병·예방접종·치과)에서 오답이 났다. 그 코드(`customer_facts.waiting_answer`)는 남아 있지만 쓰지 않는다.

표 청크의 깨진 글자를 정리한 청크 v4도 쟀지만 채택하지 않았다. 가입 나이 4문항(C51·C52·P09·S42)이 그대로였다. Milvus `petmint_*_v4`와 `data/chunks/v4`는 측정용으로만 남아 있다.

**반영 순서.** 1-11과 같다. 앱(d64aea0까지)을 먼저 push하고 infra를 나중에 push한다. 옛 이미지는 두 키를 모르므로 순서가 바뀌어도 해는 없다. **되돌리기:** 두 키를 지우고 Sync한 뒤 `rollout restart`한다.

#### 1-13. 후보 깊이 50·신규 가입 나이 코드 답 (2026-10-24, f331617)

1-12 위에 두 키를 더 켠다. 비교는 07번 11-6의 흔들림 기준(3회 평균 차이 4 안쪽은 효과로 보지 않음)으로 판단했다.

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_SEARCH_POOL` | `50` | search-service 1차 후보 깊이(Dense·BM25 각각) 20 → 50 | 검색 회귀 78·95·95 / MRR 0.880 → 80·97·97 / 0.897. 발췌가 바뀐 평가 문항은 S05 살처분·P47 소음 배상이 거절 3 → 정확 3, S11 상병명 모름이 정확 3 → 거절 3. 판정 지표 변화는 흔들림 폭 안. 모델 턴 지연 중앙값 872 → 1,028ms (`data/review/pool_measure.md`) |
| `PETMINT_AGE_CODE` | `1` | 신규 가입 나이를 숫자로 묻는 질문은 코드가 약관 기준(일반조항 제2조 '반려동물' 1호: 만 8세, 실속형 만 10세 초과는 가입 대상 아님)과 비교해 답한다 | 코드가 답하는 조건은 셋이다: 나이 숫자가 있다, 신규 가입을 묻는다, 재가입·갱신이 아니다. 평가·회귀 307문장 중 P09·C51·C52에만 걸린다. 세 문항의 거절 3/3이 코드 답 3/3으로 바뀌었다. N축은 16/16 그대로다. 대상 밖 모델 턴 318개는 프롬프트가 같다 (`data/review/age_measure.md`) |

**반영 순서.**
1. 앱(f331617까지)을 push한다
2. 새 이미지 태그 커밋을 받는다
3. ConfigMap을 push하고 Sync한다

옛 이미지는 `PETMINT_AGE_CODE`를 모르므로 먼저 들어가도 해가 없다. 이미지 태그가 함께 바뀌면 재시작은 따로 하지 않는다. ConfigMap만 바뀌는 경우에는 Sync 뒤 `kubectl -n petmint rollout restart deploy/petmint-app`이 필요하다.

**되돌리기.** 두 키를 지우고 Sync한 뒤 `rollout restart`한다.


#### 1-14. 면책 단서 코드 답 (2026-10-24, cbc78bf)

1-13 위에 키 하나를 더 켠다.

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_PROVISO_CODE` | `1` | 의료비 특약 제2조 면책 항목의 단서가 질문의 경우를 보장 쪽으로 빼 주면 코드가 답한다(⑫ 침술, ② 1년 이내 예방접종, ⑲ Ⅰ 유형의 치아 외 구강질환) | 평가 220에서 코드 답으로 바뀐 턴은 S10·S20·S27·M14-2뿐이다. 대상 밖 모델 턴 306개는 프롬프트가 같다. N축 16/16 그대로. 자동 통과 164.0 → 166.7. 탐침 대상 9턴은 직접 정답 0/27 → 27/27 (`data/review/proviso_measure.md`) |

코드가 답하는 조건은 두 가지다.
- 병명이나 치료를 가리키는 말이 지금 질문에 있어야 한다. "한약은요?"·"이빨 뽑는 건요?" 같은 후속은 모델이 답한다
- 예방접종은 질문에 접종 사실(시기 또는 미접종)이 있을 때만 답한다

평가 전용 `PETMINT_TODAY`는 운영 ConfigMap에 넣지 않는다. 운영은 실제 날짜를 쓴다.

**반영 순서.** 1-13과 같다. 앱(cbc78bf까지) push → 이미지 태그 커밋을 받는다 → ConfigMap push → Sync. 옛 이미지는 이 키를 모르므로 먼저 들어가도 해가 없다. **되돌리기:** 키를 지우고 Sync한 뒤 `rollout restart`.

#### 1-15. 같은 제목 의료비 특약 조 올리기 (2026-10-28, 5f1d48a)

1-14 위에 키 하나를 더 켠다.

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_TWIN_ARTICLE` | `1` | 업무특화 검색에서 질문에 특약 낱말(통원·입원·치료·진료·수술·의료비·병원·질병·특약)이 없고 상위 3에 보통약관 제3조·제5조가 있으면, 후보 20 안의 같은 제목 의료비 특약 조(제1조 보험금의 지급사유·제2조 보험금을 지급하지 않는 사유)를 그 앞으로 올린다. 보통약관은 사람 상해보험 약관이라 이 두 조는 반려동물 보장의 근거가 아니다 | 평가 220에서 발동 0(프롬프트 변화 0), N축 16/16, 검색 회귀 80·97·97 / MRR 0.897 그대로. 평가 밖 탐침 135턴에서 사람 보험 면책("자신을 해친 경우·임신·출산")을 답한 턴 16 → 0, 거절 32 → 30 (`data/review/human_article_measure.md`) |

같이 만든 `PETMINT_HUMAN_DEMOTE`(보통약관 제3·4·5조 점수 × 0.5)는 켜지 않는다. 탐침에서 "보장 안 되는 질병은 뭔가요?"를 거절 0/9 → 8/9로 바꿨다. 세 번째 발췌가 제5조 → 제19조로 바뀐 것만으로 모델이 거절했다.

효과는 "보험금 안 나오는 경우는?"·"지급 안 되는 사유가 뭐예요?" 같은 질문뿐이다. 의료비 질문이 보통약관 제19조·일반조항으로 가는 평가 9문항(회당 거절 7턴)은 이 키로 풀리지 않는다(`data/review/offtarget_search.md`).

**반영 순서.** 1-14와 같다. 앱(5f1d48a까지) push → 이미지 태그 커밋을 받는다 → ConfigMap push → Sync. **되돌리기:** 키를 지우고 Sync한 뒤 `rollout restart`.

#### 1-16. 직원 원장과 앱 로그인 (2026-10-28)

코드와 스키마만 들어간다. **기본은 지금 그대로(`PETMINT_AUTH=access`)** — ConfigMap을 바꾸지 않으면 동작이 같다.

- 초기화 Job이 하는 일이 늘어난다(매니페스트는 그대로): `db.migrate`가 petmint `0006_accounts`, `db.migrate --app insurance_core`가 `0003_employees`를 적용하고, `db.seed_insurance_core --if-empty`가 직원 테이블이 비어 있으면 가상 직원 11명(`db/fixtures/employees.json`, 이미지 안)을 깐다
- 앱 의존성에 `argon2-cffi`가 더해진다(이미지 재빌드)

앱 로그인을 켤 때(`PETMINT_AUTH: "app"`):

| ConfigMap 키 | 값 | 비고 |
| --- | --- | --- |
| `PETMINT_AUTH` | `app` | 사번·비밀번호 로그인. 되돌리면(`access`) 로그인 화면이 사라지고 Access 헤더가 신원이다 |
| `PETMINT_COOKIE_SECURE` | 기본 `1` | HTTPS(Access·ingress TLS) 뒤라 그대로. 로컬 http 개발만 `0` |
| `PETMINT_ALLOWED_ORIGINS` | 기본은 개발 서버 둘 | 같은 Host의 Origin은 늘 허용 — 운영 도메인은 넣지 않아도 된다 |

첫 관리자는 사람이 Pod 안에서 만든다(비밀번호는 화면에 안 보이게 두 번 묻는다).

```bash
kubectl -n petmint exec -it deploy/petmint-app -- python -m db.employees add E2001003 --role 관리자
kubectl -n petmint exec -it deploy/petmint-app -- python -m db.employees list
```

Access 정책은 그대로 둘 수 있다(로그인 두 번). 외부 데모로 열 때는 petmint 호스트의 Access 정책을 풀어야 앱 로그인 화면이 바로 보인다 — 이것은 Cloudflare 대시보드에서 사람이 한다(13번 1-3절).

#### 1-17. 사내규정 개인화 (2026-10-28)

1-16 위에 키 하나를 더 켠다. 앱 로그인(`PETMINT_AUTH: "app"`)과 같이 켠다 — 신원이 직원 이메일이어야 원장을 찾는다(access 모드의 헤더 없음·dev@local은 원장에 없어 모델이 답한다).

| ConfigMap 키 | 값 | 하는 일 | 측정 |
| --- | --- | --- | --- |
| `PETMINT_HR_PERSONAL` | `1` | 사내규정 모드에서 본인 지칭 + 연차 잔여·퇴직금·자격수당·승진이면 인사 원장으로 코드가 답한다(근거 조항 제17·18·3·28·27·33조) | 개인 탐침 32문항 96/96(기준은 우연 일치 19/96), 대상 밖 프롬프트(음성 8·HR 18) 78/78 같음. 업무특화·검색은 경로 밖 (`data/review/hr_personal_measure.md`) |

**반영 순서.** 앱(이 커밋까지) push → 이미지 태그 커밋을 받는다 → ConfigMap push → Sync. **되돌리기:** 키를 지우고 Sync한 뒤 `rollout restart`.

2026-10-28 운영 피드백으로 고쳤다(키는 같다, 이미지만): 본인 지칭 없는 후속("연차 미사용분은 얼마 받나요?")이 바로 앞 개인화 질문을 이어받는다, 미사용 연차수당 금액, 코드 답의 근거 조항은 검색 결과가 아니라 코드가 쓴 조항. 후속 15/15(전 2/15), 대상 밖 프롬프트 93/93 같음.

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

**1. search-service** — ✗ 호스트 기동과 ConfigMap 주소 교체 전(코드는 2026-10-18 작성, `search_service/`). 이것이 붙어야 검색이 Pod에서 돌고, answer.py와 함께 더미 답변이 진짜 답변이 된다.

**2. 08번 Ragas** — △ 검색 품질 측정. 오늘 top 3 적중 81/97을 쟀고,
Context Recall을 제대로 보려면 이것이 필요하다.