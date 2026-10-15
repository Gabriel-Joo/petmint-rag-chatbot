// 앱 이미지 빌드 → Harbor push (docs/14 1-5절 앞 절반). 매니페스트 태그 갱신·ArgoCD 연결은 아직 없다.
//
// - Job·자격 증명·폴링(2분)은 ronanlab-infra platform/jenkins/values.yaml 의 JCasC 가 만든다
// - 빌드는 BuildKit rootless — Pod 안에 Docker 데몬이 없다. 특권 컨테이너 대신 seccomp·AppArmor 만 푼다
//   (rootlesskit 이 사용자 네임스페이스를 만든다)
// - Harbor 는 harbor.ronanlab.dev 그대로 부른다. 클러스터 CoreDNS 가 이 이름을 ingress-nginx 내부 Service 로
//   돌려 Access 를 거치지 않는다(docs/14 1-6절, ronanlab-infra platform/coredns)
// - 태그는 커밋 해시 12자리. latest 를 쓰지 않는다 — 같은 커밋이면 같은 태그, 태그로 코드를 찾아갈 수 있다
// - 약관·고객 시드는 git 에 없어 이미지에도 들어가지 않는다(.dockerignore 와 이중으로)

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
  }

  stages {
    stage('태그') {
      steps {
        script {
          env.TAG = env.GIT_COMMIT.take(12)
          currentBuild.description = "${env.IMAGE}:${env.TAG}"
        }
      }
    }

    stage('빌드·push') {
      steps {
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
  }

  post {
    always {
      // 자격 증명 파일은 Pod 와 함께 사라지지만, 그 전에 지운다
      sh 'rm -rf "$WORKSPACE_TMP/docker"'
    }
  }
}
