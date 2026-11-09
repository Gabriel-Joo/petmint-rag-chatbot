// 앱 이미지 빌드 → Harbor push → 매니페스트(ronanlab-infra apps/petmint) 태그 갱신 push (docs/14 1-5절). 배포는 ArgoCD Sync.
//
// - Job·자격 증명·트리거(GitHub 웹훅 + 폴링 15분 안전망)는 ronanlab-infra platform/jenkins/values.yaml 의 JCasC 가 만든다
// - FOREMAN 빌드 알림(2026-11-03): 시작 · 끝을 foremanNotify 가 FOREMAN 에 알린다(맨 아래). 실패해도 빌드 결과에 영향 없다 —
//   try/catch · || true · 연결 3초/전체 5초 · post 의 맨 마지막(cleanup). 각 stage 첫 줄의 env.STAGE 는 실패한 스테이지 이름을 알리려고
// - 빌드는 BuildKit rootless — Pod 안에 Docker 데몬이 없다. 특권 컨테이너 대신 seccomp·AppArmor 만 푼다
//   (rootlesskit 이 사용자 네임스페이스를 만든다)
// - Harbor 는 harbor.ronanlab.dev 그대로 부른다. 클러스터 CoreDNS 가 이 이름을 ingress-nginx 내부 Service 로
//   돌려 Access 를 거치지 않는다(docs/14 1-6절, ronanlab-infra platform/coredns)
// - 태그는 커밋 해시 12자리. latest 를 쓰지 않는다 — 같은 커밋이면 같은 태그, 태그로 코드를 찾아갈 수 있다
// - 약관·고객 시드는 git 에 없어 이미지에도 들어가지 않는다(.dockerignore 와 이중으로)
// - ronanlab-infra 는 git/checkout 단계가 아니라 sh 'git clone' 으로 받는다. Jenkins 폴링은 빌드 중 git 단계로 받은 저장소를
//   전부 감시한다 — git 단계로 받으면 태그 push 가 빌드를 다시 부르고, 그 빌드가 또 push 하는 루프가 된다
// - 문서만 바뀐 빌드는 이미지 빌드 · 태그 커밋을 건너뛴다(2026-11-09 사용자, 런슈즈 5d11d2e 와 같은 방식). 바뀐 파일(직전 성공
//   빌드의 커밋 → 이번 커밋)이 모두 docs/ · data/review/ · 루트 *.md 이면 — Dockerfile 이 COPY 하지 않고 .dockerignore 로도 빠져,
//   구워도 같은 이미지에 태그만 새로 붙어 수동 Sync 대기가 쌓였다(11-09 #50 · #51). 빌드 자체는 돌고 결과는 SUCCESS,
//   끝 알림에 "skipped": true(FOREMAN 이 태그 · Harbor · ArgoCD 를 기다리지 않는다).
//   손으로 누른 빌드, 직전 성공 커밋이 없거나 못 찾을 때, 바뀐 파일을 못 셀 때는 늘 빌드한다

pipeline {
  agent {
    kubernetes {
      yaml '''
apiVersion: v1
kind: Pod
spec:
  containers:
    - name: buildkit
      image: moby/buildkit:v0.33.1-rootless
      command: ["cat"]          # 단계가 exec 로 들어올 때까지 살아 있게(이미지의 busybox sleep 은 infinity 를 모른다)
      tty: true
      env:
        - name: BUILDKITD_FLAGS
          value: --oci-worker-no-process-sandbox
      securityContext:
        runAsUser: 1000
        runAsGroup: 1000
        seccompProfile: { type: Unconfined }
        appArmorProfile: { type: Unconfined }
      resources:
        requests: { cpu: 500m, memory: 1536Mi }
        limits: { memory: 3Gi }
      volumeMounts:
        - { name: buildkitd, mountPath: /home/user/.local/share/buildkit }
  volumes:
    - { name: buildkitd, emptyDir: {} }
'''
    }
  }

  options {
    disableConcurrentBuilds()
    timeout(time: 30, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }

  environment {
    REGISTRY = 'harbor.ronanlab.dev'
    IMAGE    = 'harbor.ronanlab.dev/petmint/petmint-app'
    INFRA_REPO    = 'git@github.com:Gabriel-Joo/ronanlab-infra.git'
    KUSTOMIZATION = 'apps/petmint/kustomization.yaml'
  }

  stages {
    stage('태그') {
      steps {
        script {
          env.STAGE = env.STAGE_NAME
          env.TAG = env.GIT_COMMIT.take(12)
          currentBuild.description = "${env.IMAGE}:${env.TAG}"
          // 문서만 바뀌었나 — 출력 첫 줄이 skip 이면 건너뛴다. 모르면 build(안전한 쪽)
          String verdict = buildCause() == 'manual' ? 'build (손으로 누름)' : sh(returnStdout: true, script: '''
            set +e +x
            P="${GIT_PREVIOUS_SUCCESSFUL_COMMIT:-}"
            [ -n "$P" ] || { echo "build (직전 성공 커밋 없음)"; exit 0; }
            git cat-file -e "$P^{commit}" 2>/dev/null || { echo "build (직전 성공 커밋 $P 을 못 찾음)"; exit 0; }
            F=$(git -c core.quotePath=false diff --name-only "$P" "$GIT_COMMIT") || { echo "build (바뀐 파일을 못 셈)"; exit 0; }
            [ -n "$F" ] || { echo "build (바뀐 파일 없음 — 같은 커밋 다시)"; exit 0; }
            N=$(printf '%s\\n' "$F" | wc -l)
            R="$(printf %.12s "$P")..$(printf %.12s "$GIT_COMMIT")"
            if printf '%s\\n' "$F" | grep -Evq '^(docs/|data/review/)|^[^/]+\\.md$'; then
              echo "build ($R 파일 $N개, 문서 밖 포함)"
            else
              echo "skip ($R 파일 $N개, 모두 문서)"
            fi
          ''').trim()
          echo "문서만 바뀌었나: ${verdict}"
          env.SKIP = verdict.startsWith('skip') ? 'true' : 'false'
          if (env.SKIP == 'true') currentBuild.description = "건너뜀 — 문서만(${env.TAG})"
        }
        foremanNotify('started')
      }
    }

    stage('빌드·push') {
      when { expression { env.SKIP != 'true' } }
      steps {
        script { env.STAGE = env.STAGE_NAME }
        container('buildkit') {
          withCredentials([usernamePassword(credentialsId: 'harbor-robot-petmint-jenkins',
                                            usernameVariable: 'HARBOR_USER', passwordVariable: 'HARBOR_PASSWORD')]) {
            // 작은따옴표 — 자격 증명을 Groovy 가 문자열에 끼워 넣지 않고 셸 환경변수로만 받는다.
            // set +x: Jenkins sh 는 -x 로 돈다. 아래 printf 가 펼쳐져 로그에 찍히지 않게 끈다
            sh '''
              set +x
              export DOCKER_CONFIG="$WORKSPACE_TMP/docker"
              mkdir -p "$DOCKER_CONFIG"
              AUTH=$(printf '%s:%s' "$HARBOR_USER" "$HARBOR_PASSWORD" | base64 | tr -d '\\n')
              printf '{"auths":{"%s":{"auth":"%s"}}}' "$REGISTRY" "$AUTH" > "$DOCKER_CONFIG/config.json"
              unset AUTH
              echo "push → $IMAGE:$TAG"
              buildctl-daemonless.sh build --progress=plain \
                --frontend dockerfile.v0 --local context=. --local dockerfile=. \
                --opt label:org.opencontainers.image.revision="$GIT_COMMIT" \
                --opt label:org.opencontainers.image.source=https://github.com/Gabriel-Joo/petmint-rag-chatbot \
                --output type=image,name="$IMAGE:$TAG",push=true
            '''
          }
        }
      }
    }

    stage('매니페스트 태그') {
      // jnlp 컨테이너(git·ssh 있음)에서 돈다. deploy key 는 ronanlab-infra 에만 쓸 수 있다(ronanlab-infra scripts/make-deploy-keys.sh)
      when { expression { env.SKIP != 'true' } }
      steps {
        script { env.STAGE = env.STAGE_NAME }
        withCredentials([sshUserPrivateKey(credentialsId: 'ronanlab-infra-deploy-key', keyFileVariable: 'INFRA_KEY')]) {
          sh '''
            set -eu
            # GitHub 호스트 키를 박아 둔다(처음 본 키를 믿지 않는다). https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
            KH="$WORKSPACE_TMP/known_hosts"
            echo 'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' > "$KH"
            export GIT_SSH_COMMAND="ssh -i $INFRA_KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=$KH -o StrictHostKeyChecking=yes"
            D="$WORKSPACE_TMP/infra"
            rm -rf "$D"
            git clone -q --depth 1 --branch main "$INFRA_REPO" "$D"
            cd "$D"
            git config user.name 'Jenkins petmint-app'
            git config user.email 'jenkins@ronanlab.dev'
            for i in 1 2 3; do
              sed -E -i 's/^(    newTag: )"[0-9a-f]{12}"/\\1"'"$TAG"'"/' "$KUSTOMIZATION"
              grep -q '^    newTag: "'"$TAG"'"' "$KUSTOMIZATION" || { echo "newTag 줄을 못 찾았다: $KUSTOMIZATION"; exit 1; }
              if git diff --quiet; then echo "이미 $TAG — 커밋할 것 없음"; exit 0; fi
              git commit -q -am "petmint: 이미지 태그 $TAG" -m "petmint-rag-chatbot $GIT_COMMIT, Jenkins petmint-app #$BUILD_NUMBER"
              if git push -q origin HEAD:main; then echo "push → $KUSTOMIZATION newTag $TAG"; exit 0; fi
              # 사람이 먼저 push 했다 — 최신 main 위에서 다시 바꾼다
              git fetch -q --depth 1 origin main && git reset -q --hard FETCH_HEAD
            done
            echo "push 3번 실패"; exit 1
          '''
        }
      }
    }
  }

  post {
    always {
      // 자격 증명 파일은 Pod 와 함께 사라지지만, 그 전에 지운다
      sh 'rm -rf "$WORKSPACE_TMP/docker" "$WORKSPACE_TMP/infra" "$WORKSPACE_TMP/known_hosts"'
    }
    cleanup {
      // post 블록 중 맨 마지막에 돈다 — 결과가 정해진 뒤
      foremanNotify('completed')
    }
  }
}

// FOREMAN 빌드 알림(foreman log/stage8_cicd_result.md). 실패해도 빌드 결과에 영향 없다:
// 단계 예외는 try/catch, curl 실패는 || true, 연결 3초 · 전체 5초. 토큰은 셸 환경변수로만(Groovy 문자열에 넣지 않는다),
// curl 인자가 아니라 표준 입력 설정(-K -)으로 넘겨 프로세스 목록 · 로그에 안 남는다.
// 받는 쪽: FOREMAN 브리지 192.168.122.1:8001(virbr0, VM 망 IP만). 자격 증명 foreman-webhook-token(ronanlab-infra JCasC)
String buildCause() {
  def causes = currentBuild.getBuildCauses().collect { it._class as String }
  return causes.any { it.endsWith('GitHubPushCause') } ? 'webhook'
       : causes.any { it.contains('SCMTrigger') }      ? 'poll'
       : causes.any { it.contains('UserIdCause') }     ? 'manual' : 'other'
}

// "skipped": true 는 문서만 바뀌어 건너뛴 빌드의 끝 알림에만
def foremanNotify(String phase) {
  try {
    String cause = buildCause()
    String skipped = (phase == 'completed' && env.SKIP == 'true') ? ',"skipped":true' : ''
    withEnv(["F_PHASE=${phase}", "F_CAUSE=${cause}", "F_STAGE=${env.STAGE ?: ''}",
             "F_RESULT=${phase == 'completed' ? currentBuild.currentResult : ''}",
             "F_DURATION=${currentBuild.duration}", "F_SKIPPED=${skipped}"]) {
      withCredentials([string(credentialsId: 'foreman-webhook-token', variable: 'F_TOKEN')]) {
        sh '''
          set +x
          body=$(printf '{"job":"%s","number":%s,"phase":"%s","result":"%s","commit":"%s","stage":"%s","cause":"%s","url":"%s","timestamp":%s000,"duration":%s%s}' \\
            "$JOB_NAME" "$BUILD_NUMBER" "$F_PHASE" "$F_RESULT" "${GIT_COMMIT:-}" "$F_STAGE" "$F_CAUSE" "$BUILD_URL" "$(date +%s)" "$F_DURATION" "$F_SKIPPED")
          printf 'header = "Authorization: Bearer %s"\\n' "$F_TOKEN" |
            curl -sS -o /dev/null --connect-timeout 3 --max-time 5 -K - \\
              -H 'Content-Type: application/json' --data "$body" \\
              http://192.168.122.1:8001/webhooks/jenkins || true
        '''
      }
    }
  } catch (e) {
    echo "FOREMAN 알림 실패(빌드 결과와 무관): ${e}"
  }
}
