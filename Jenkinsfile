// 앱 이미지 빌드 → Harbor push → 매니페스트(ronanlab-infra apps/petmint) 태그 갱신 push (docs/14 1-5절). 배포는 ArgoCD Sync.
//
// - Job·자격 증명·폴링(2분)은 ronanlab-infra platform/jenkins/values.yaml 의 JCasC 가 만든다
// - 빌드는 BuildKit rootless — Pod 안에 Docker 데몬이 없다. 특권 컨테이너 대신 seccomp·AppArmor 만 푼다
//   (rootlesskit 이 사용자 네임스페이스를 만든다)
// - Harbor 는 harbor.ronanlab.dev 그대로 부른다. 클러스터 CoreDNS 가 이 이름을 ingress-nginx 내부 Service 로
//   돌려 Access 를 거치지 않는다(docs/14 1-6절, ronanlab-infra platform/coredns)
// - 태그는 커밋 해시 12자리. latest 를 쓰지 않는다 — 같은 커밋이면 같은 태그, 태그로 코드를 찾아갈 수 있다
// - 약관·고객 시드는 git 에 없어 이미지에도 들어가지 않는다(.dockerignore 와 이중으로)
// - ronanlab-infra 는 git/checkout 단계가 아니라 sh 'git clone' 으로 받는다. Jenkins 폴링은 빌드 중 git 단계로 받은 저장소를
//   전부 감시한다 — git 단계로 받으면 태그 push 가 빌드를 다시 부르고, 그 빌드가 또 push 하는 루프가 된다

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

    stage('매니페스트 태그') {
      // jnlp 컨테이너(git·ssh 있음)에서 돈다. deploy key 는 ronanlab-infra 에만 쓸 수 있다(ronanlab-infra scripts/make-deploy-keys.sh)
      steps {
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
  }
}
