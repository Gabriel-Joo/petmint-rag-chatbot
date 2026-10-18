> 상태: 구축 완료. 터널과 Access 정책은 설정을 마쳤다(petmint는 시연용으로 로그인한 누구나 통과).
> cloudflared 매니페스트는 ronanlab-infra `platform/cloudflared`에 있다(2026-10-18, 4절). 구축 과정의 상세 기록은 "쿠버네티스 설치 / 03. Cloudflare Tunnel 연결" 문서에 있다.
> 

---

### 0. 한 줄 요약

사설망 안의 서버를 포트포워딩 없이 외부에 내고, **Cloudflare Access로 사내 계정 인증을 걸어 상담원 신원을 확인한다.** 앱은 로그인 화면을 만들지 않는다.

---

### 1. 최종 설계

#### 1-1. 요청이 흐르는 길

```
상담원 브라우저
  → Cloudflare 엣지 (Access 정책 검사 — 사내 계정 로그인)
  → ronanlab-tunnel (클러스터 내 cloudflared Pod 2개)
  → nginx-ingress
  → petmint 앱 (FastAPI + React 빌드물)
```

인바운드 포트를 하나도 열지 않는다. 서버가 Cloudflare로 **아웃바운드 연결을 먼저 걸고** 그 연결을 유지하므로, 공유기 설정이 필요 없고 학교·회사 망에서도 동작한다.

#### 1-2. 터널 구성

| 항목 | 값 |
| --- | --- |
| 터널 | ronanlab-tunnel (02ad6a13-ce45-4262-a32a-40241bf034dc) |
| 실행 방식 | 클러스터 내 Deployment, `replicas: 2`, livenessProbe |
| 바라보는 곳 | nginx-ingress 하나만 (`https://`, `noTLSVerify: true`). Service 타입을 LoadBalancer로 바꾼 뒤에도 터널은 ClusterIP를 보므로 영향이 없다(14번 1-7절) |
| 상위 문서 | 쿠버네티스 설치 / 03. Cloudflare Tunnel 연결 |

터널이 **앱을 직접 가리키지 않고 Ingress Controller만** 본다. 새 앱을 추가할 때 Ingress 리소스만 더하고 터널 설정은 건드리지 않는다.

#### 1-3. Access 정책

터널은 클러스터 공용이지만 **Access 정책은 호스트별로 건다.** 프로젝트마다 접근 정책이 다를 수 있기 때문이다.

| 호스트 | 정책 |
| --- | --- |
| petmint.ronanlab.dev | 로그인한 누구나(시연용). 통과한 사람의 이메일을 헤더로 전달 |
| argocd / harbor / jenkins | 운영자만. Application 하나로 묶어 세션을 공유한다 |

`ollama.ronanlab.dev`는 이 터널이 아니라 별도 터널(`ollama-tunnel`)로 나간다. Service Token으로 기구간 호출만 허용한다.

> 현재 petmint.ronanlab.dev의 정책은 시연용으로 로그인한 누구나 접근 가능하다. 단, 실무에서는 Include를 Emails나 Email domain으로 바꿔 상담원만 통과시킨다. 어느 쪽이든 통과한 사람의 이메일이 헤더로 전달되므로 앱 코드는 바뀌지 않는다.
> 

> 운영 도구 셋은 자체 로그인이 있지만 Access를 앞에 둔다. 로그인 화면 자체가 공격면이고, 인증 전에 터지는 취약점이 드물지 않기 때문이다. 정책이 같으므로 Application 하나에 묶었고, 하나를 인증하면 셋 다 통한다.
> 

앱은 `Cf-Access-Authenticated-User-Email` 헤더를 읽어 `sessions.agent_email`에 넣는다(12번). 로컬 개발에서는 그 헤더가 없으므로 기본값을 둔다.

**이 값은 기록용이면서 소유권 판정에도 쓰인다.** 세션을 바꾸는 작업(PATCH·DELETE·피드백)은 `agent_email`로 거르고, 남의 세션은 없는 세션과 같게 404다(09번 7-1절). WS는 연결 자체를 4404로 닫는다. 다만 **읽기(`GET /api/sessions/{id}`)는 고객이 있는 세션에 한해 남의 것도 열어준다** — 최근 상담 탭이 그 위에 서 있다. 따라서 **헤더가 위조되면 남의 상담을 바꾸거나 지울 수 있다** — 앱에 직접 닿는 경로를 막아 모든 요청이 엣지를 거치게 해야 한다.

> 다만 시연용 정책에서는 누구나 로그인할 수 있으므로 `agent_email`은 "그 브라우저로 로그인한 사람"을 뜻할 뿐이다. 상담원 명단으로 거르는 실무 정책에서만 이 구분이 본래 의미를 갖는다.
> 

---

### 2. 왜 이렇게 했나

#### 2-1. 앱에 로그인을 만들지 않는다

상담 내용에는 책임이 따른다 — 누가 어떤 답변을 했는지 남아야 한다. 그렇다고 앱이 직접 로그인을 만들 이유는 없다.

- 비밀번호 저장·세션 관리·재설정을 전부 떠안아야 한다
- 사내 계정 체계가 이미 있는데 또 하나를 만드는 셈이다. 퇴사자 처리도 두 곳에서 해야 한다
- 앱이 비밀번호를 다루지 않으면 유출될 것도 없다

실무에서도 사내 도구는 SSO로 묶는 것이 표준이다(Okta, Google Workspace 등). Cloudflare Access는 그 역할을 하고, Zero Trust 구성에서 흔히 쓰인다.

> **프로젝트마다 다르게 간다.** 펫민트는 사내 상담원만 쓰므로 Access, RUNSHOES처럼 불특정 사용자가 가입하는 공개 서비스는 자체 로그인이 맞다.
> 

#### 2-2. 터널을 호스트 프로세스가 아니라 Pod로

|  | 호스트 프로세스 | 클러스터 Pod (채택) |
| --- | --- | --- |
| 장애 복구 | 죽으면 수동 재시작 | livenessProbe로 자동 재시작 |
| 이중화 | 수동으로 프로세스 여러 개 | `replicas: 2` 한 줄 |
| 설정 관리 | 호스트 파일 | ConfigMap — ronanlab-infra `platform/cloudflared`, ArgoCD Sync |

RUNSHOES는 호스트 방식, 펫민트는 클러스터 방식으로 **발전한 흐름**이 되기도 한다.

#### 2-3. 터널 설정은 클러스터 단위, Access는 프로젝트 단위

터널 ConfigMap은 **네 호스트가 한 파일에 들어 있어 쪼갤 수 없다.** 호스트가 클러스터 단위로 묶이므로 `ronanlab-infra` 저장소도 프로젝트별이 아니라 클러스터 단위로 묶었다 — Harbor·Jenkins·ArgoCD·터널은 펫민트의 것이 아니라 클러스터의 것이다.

반면 **Access 정책은 호스트마다 따로 건다.** 프로젝트가 늘어나면 정책도 각각 추가하면 된다.

---

### 3. 시도했던 것들

상세한 트러블슈팅은 "03. Cloudflare Tunnel 연결" 문서에 있고, 요약하면 세 가지다.

| 문제 | 원인·해결 |
| --- | --- |
| 엉뚱한 터널로 CNAME이 연결됨 | `cloudflared`가 기본 config(`tunnel: ollama-tunnel`)를 읽어 명령줄 인자를 무시. `--config /dev/null`로 해결. **터널이 여러 개면 route dns 후 대시보드에서 Target을 반드시 확인** |
| ImagePullBackOff | Vagrant 박스의 기본 DNS(4.2.2.1 등)가 응답하지 않음. VM 4대에 8.8.8.8·1.1.1.1 설정, DNSSEC 끄기 |
| CrashLoopBackOff인데 에러가 없음 | Exit Code 0 — 에러가 아니라 "할 일을 마쳤다"고 종료. 전역 플래그(`--no-autoupdate`, `--config`)를 서브커맨드(`tunnel run`) 앞으로 옮겨 해결 |

> 세 번째가 가장 까다로웠다. 로그에는 "Environment is healthy"만 찍히고 에러가 없었다. **"CrashLoopBackOff = 에러"라고 단정하지 않고 `Exit Code`와 `Reason`을 확인한 것이 실마리였다.**
> 

---

### 4. 남은 한계

- **petmint는 시연용으로 열려 있다.** 로그인은 거치지만 상담원 명단으로 거르지 않으므로, `agent_email`은 "그 브라우저로 로그인한 사람"을 뜻할 뿐이다. 상담원만 통과시키는 실무 정책에서만 이 값이 본래 의미를 갖는다.
- **역할 구분이 없다.** 지금 설계는 "통과한 사람 = 상담원"이다. 관리자·상담원을 나누려면 Access 그룹을 나누고 앱에서도 구분해야 한다
- **터널 ConfigMap을 쪼갤 수 없다.** 호스트가 늘면 한 파일이 계속 커진다
- ~~cloudflared 매니페스트가 아직 저장소에 없다.~~ 2026-10-18 해결 — 2-3절의 판단대로 `petmint` 네임스페이스에서 `cloudflared` 네임스페이스로 옮겼다. 매니페스트는 ronanlab-infra `platform/cloudflared`, ArgoCD Application `cloudflared`(수동 Sync)가 관리한다. Secret `cloudflared-credentials`는 사람이 넣는다(같은 디렉터리 README.md)

---

### 5. 검증 항목

- [ ]  Access 정책을 건 뒤, 로그인 없이 접근하면 막히는가
- [x]  통과한 사용자의 이메일이 `Cf-Access-Authenticated-User-Email` 헤더로 도착하는가
- [x]  그 값이 `sessions.agent_email`에 들어가는가
- [ ]  헤더를 손으로 바꿔 남의 세션을 여는 요청이 엣지에서 막히는가
- [ ]  로컬 개발에서 헤더가 없을 때 기본값으로 동작하는가
- [x]  cloudflared Pod를 하나 지워도 서비스가 끊기지 않는가