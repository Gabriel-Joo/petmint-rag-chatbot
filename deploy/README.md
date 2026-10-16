# deploy — 매니페스트는 ronanlab-infra로 옮겼다

2026-10-16부터 펫퍼민트 K8s 매니페스트는 **ronanlab-infra `apps/petmint/`** 에 있다(14번 1-5절). ArgoCD Application `petmint`가 그 디렉터리를 본다.
이 리포에 남은 것은 호스트(GPU 머신)에서 돌리는 `scripts/host-nfs-setup.sh` 하나 — 약관·시드 디렉터리가 이 리포에 있어서다.

## 배포 흐름

```
이 리포 main push
  → Jenkins petmint-app (2분 폴링) — 이미지 빌드 → harbor.ronanlab.dev/petmint/petmint-app:<커밋 12자리>
  → 같은 빌드가 ronanlab-infra apps/petmint/kustomization.yaml 의 newTag 를 바꿔 push (Jenkinsfile '매니페스트 태그')
  → ArgoCD 가 OutOfSync 로 표시 → 사람이 Sync (지금은 수동) → 한 Pod씩 교체
```

ronanlab-infra는 Jenkinsfile에서 `sh 'git clone'`으로 받는다 — `git` 단계로 받으면 Jenkins가 그 저장소까지 폴링해서
태그 push가 빌드를 다시 부르는 루프가 된다.

## kubectl apply·apply.sh를 쓰지 않는다

ArgoCD가 넘겨받은 뒤로는 매니페스트를 `kubectl apply`로 넣지 않는다. 이 리포에 있던 `scripts/apply.sh`도 없앴다.
손으로 넣으면 클러스터가 git과 엇갈린다 — ArgoCD가 OutOfSync로 잡고, 다음 Sync 때 git 쪽으로 되돌린다(손으로 한 변경이 조용히 사라진다).
설정을 바꾸려면 ronanlab-infra `apps/petmint/`를 고쳐 push하고 Sync한다. 자세한 것은 그쪽 README.

## 호스트 NFS (약관·시드)

```bash
sudo deploy/scripts/host-nfs-setup.sh    # 한 번만. data/chunks·data/graph·app/fixtures 를 사설망에 읽기 전용 공유
```

약관을 바꾸면(재색인) 앱은 기동 때 읽으므로 `kubectl -n petmint rollout restart deploy/petmint-app` — 복사·적재는 없다.

옮기기 전 매니페스트와 검증 기록(kind·실제 클러스터, 2026-10-15~16)은 이 리포의 커밋 afefd07 `deploy/`에 있다.
