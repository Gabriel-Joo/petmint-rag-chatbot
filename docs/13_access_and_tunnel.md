> 상태: 구축 완료. 터널과 Access 정책은 설정을 마쳤다(petmint는 시연용으로 로그인한 누구나 통과).
> 2026-10-28: 앱 자체 인증(사번·비밀번호)을 더했다 — `PETMINT_AUTH=app`. 기본(`access`)은 아래 Access 설계 그대로다(2-1절).
> cloudflared 매니페스트는 ronanlab-infra `platform/cloudflared`에 있다(2026-10-18, 4절). 구축 과정의 상세 기록은 "쿠버네티스 설치 / 03. Cloudflare Tunnel 연결" 문서에 있다.
> 

---

### 0. 한 줄 요약

사설망 안의 서버를 포트포워딩 없이 외부에 내고, **Cloudflare Access로 사내 계정 인증을 걸어 상담원 신원을 확인한다.**
초기엔 사내 SSO(Cloudflare Access)를 전제로 설계했으나, 외부 데모 요구가 생기면서 앱 자체 인증으로 전환했다. 운영 환경에서는 Access를 앞단에 두는 구성도 가능하다.

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

#### 2-1. 처음에는 앱에 로그인을 만들지 않았다 → 앱 자체 인증으로 전환(2026-10-28)

**초기 설계.** 상담 내용에는 책임이 따른다 — 누가 어떤 답변을 했는지 남아야 한다. 그래도 앱이 직접 로그인을 만들 이유는 없다고 봤다.

- 비밀번호 저장·세션 관리·재설정을 전부 떠안아야 한다
- 사내 계정 체계가 이미 있는데 또 하나를 만드는 셈이다. 퇴사자 처리도 두 곳에서 해야 한다
- 앱이 비밀번호를 다루지 않으면 유출될 것도 없다

사내 도구는 SSO로 묶는 것이 표준이고(Okta, Google Workspace 등), Cloudflare Access가 그 역할을 했다.

**전환.** 초기엔 사내 SSO(Cloudflare Access)를 전제로 설계했으나, 외부 데모 요구가 생기면서 앱 자체 인증으로 전환했다. 운영 환경에서는 Access를 앞단에 두는 구성도 가능하다.

요구가 바뀐 지점은 둘이다.
- 데모를 보는 사람은 사내 계정이 없다. Access 정책을 "로그인한 누구나"로 열면 상담원 명단으로 거르지 못하고(4절), 계정을 만들어 주면 사내 계정 체계 밖의 사람을 SSO에 넣게 된다
- 상담원 명단·역할·재직 여부를 앱이 알아야 한다. 다음 단계의 사내규정 개인화(퇴직금·연차·자격수당)는 로그인한 사람이 누구인지 사번 단위로 알아야 한다

그래서 직원 원장을 두고 앱이 그 직원을 직접 인증한다. 위의 세 가지 비용은 그대로 떠안되, 이렇게 줄였다.

| 항목 | 구현 |
| --- | --- |
| 신원 | 기간계 `insurance_core.employees`(인사 원장, 앱은 SELECT만). 앱 쪽은 `petmint.accounts`(역할·해시·잠금)·`auth_sessions` — 12번 1-1절 |
| 비밀번호 | argon2id. 최소 10자, 관리자가 준 임시 비밀번호는 첫 로그인 때 바꾼다. 바꾸면 그 직원의 다른 로그인을 모두 끊는다 |
| 세션 | 32바이트 난수 토큰을 HttpOnly·SameSite=Lax·Secure 쿠키로, DB에는 SHA-256만. 미사용 2시간·절대 12시간. JWT를 쓰지 않는다 — 퇴직·비밀번호 변경·로그아웃 때 즉시 끊어야 한다 |
| 무차별 대입 | 5회 실패 → 15분 잠금. 실패 문구는 하나("사번 또는 비밀번호가 올바르지 않습니다") — 없는 사번도 같은 해시 시간 |
| 퇴사 | 기간계 `retired_on`이 지나면 다음 요청부터 401, 앱만 끊을 때는 `accounts.disabled_at` |
| CSRF·WS 위조 | 상태를 바꾸는 `/api` 요청과 WS 연결은 Origin이 같은 Host이거나 허용 목록이어야 한다(`PETMINT_ALLOWED_ORIGINS`) |
| 신원 기록 | 로그인한 직원의 이메일이 그대로 `sessions.agent_email`에 들어간다 — 세션 소유권 판정(1-3절)은 코드가 바뀌지 않았다 |

`PETMINT_AUTH`로 고른다. `access`(기본)는 지금처럼 Access 헤더가 신원이고, `app`은 로그인 쿠키가 있어야 한다. 둘 다 `GET /api/auth/me`가 답하고 프런트는 `auth_mode`를 보고 로그인 화면을 띄울지 정한다. 계정은 관리 화면 대신 `python -m db.employees add|reset|disable|enable|list`로 다룬다(비밀번호는 명령줄에 쓰지 않고 두 번 묻는다).

> **프로젝트마다 다르게 간다.** RUNSHOES처럼 불특정 사용자가 가입하는 공개 서비스는 처음부터 자체 로그인이다. 펫민트는 사내 상담원용이지만 직원 원장을 앱이 갖게 되면서 자체 인증이 됐다 — 가입은 없고 관리자가 계정을 만든다.

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

- ~~petmint는 시연용으로 열려 있다(명단으로 거르지 않는다).~~ `PETMINT_AUTH=app`에서 해결 — 직원 원장에 있고 계정이 있는 사람만 들어온다. `access` 모드에서는 여전히 Access 정책이 명단 역할을 한다
- **역할은 칸만 있다.** `accounts.role`(상담원·관리자)을 두었지만 관리자 화면(직원 관리·전체 상담)은 아직 없다. 계정 관리는 명령(`db.employees`)으로 한다
- **잠금이 사번 단위다.** 없는 사번을 돌려 가며 시도하는 것은 막지 못한다(IP 단위 제한 없음). 잠긴 계정은 "잠겼다"고 알려 주므로 그 사번이 있다는 것은 드러난다
- **Access를 앞에 두면 로그인을 두 번 한다.** 운영에서 Access를 함께 쓰려면 Access 이메일로 앱 세션을 여는 연결(SSO 연동)이 따로 필요하다
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
- [x]  (app 모드) 로그인 안 하면 `/api` 401·WS 4401, 다른 출처 POST 403·WS 4403 — `tests/test_auth.py`, 로컬 curl
- [x]  (app 모드) 임시 비밀번호 → 변경 강제 → 앱, 세션 행을 지우면 다음 요청에서 로그인 화면, 로그아웃 — 로컬 브라우저 1440·400px
- [x]  (app 모드) 로그인한 직원 이메일이 `sessions.agent_email`에 들어간다
- [x]  (access 모드) 로그인 화면 없이 지금과 같다 — `/api/auth/login` 404, 헤더 이메일이 원장에 있으면 이름이 붙는다