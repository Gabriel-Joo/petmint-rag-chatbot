#!/usr/bin/env bash
# Secret을 클러스터에 직접 만든다 — 값은 저장소·매니페스트에 남지 않는다(12번 1-2절).
# 이미 있는 Secret은 건드리지 않는다: MySQL root 비밀번호는 데이터 디렉터리를 처음 만들 때만 쓰이므로, 바꾸면 접속이 끊긴다.
# 앱 계정 비밀번호를 바꾸려면 Secret을 지우고 이 스크립트 → 초기화 Job(db.bootstrap이 ALTER USER로 맞춘다) 순서로.
#
#   deploy/scripts/create-secrets.sh                 # 무작위 비밀번호
#   HARBOR_USER=... HARBOR_PASSWORD=... deploy/scripts/create-secrets.sh   # Harbor pull Secret까지
#   robot 계정 이름에는 $가 들어 있다 — 작은따옴표로: HARBOR_USER='robot$petmint+pull'
set -euo pipefail
NS=${NS:-petmint}

kubectl get namespace "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS"

rand() { openssl rand -base64 33 | tr -d '/+=\n' | cut -c1-32; }

make() {  # make <이름> <키> — 없을 때만 무작위 값으로
  local name=$1 key=$2
  if kubectl -n "$NS" get secret "$name" >/dev/null 2>&1; then
    echo "있음  $name (그대로 둔다)"
  else
    kubectl -n "$NS" create secret generic "$name" --from-literal="$key=$(rand)" >/dev/null
    echo "만듦  $name"
  fi
}

make mysql-root        MYSQL_ROOT_PASSWORD
make petmint-db        password    # petmint_app — petmint 전체, insurance_core SELECT
make insurance-seed-db password    # insurance_seed — insurance_core 적재·수정

if [[ -n "${HARBOR_USER:-}" ]]; then
  if kubectl -n "$NS" get secret harbor-pull >/dev/null 2>&1; then
    echo "있음  harbor-pull (그대로 둔다)"
  else
    kubectl -n "$NS" create secret docker-registry harbor-pull --docker-server=harbor.ronanlab.dev \
      --docker-username="$HARBOR_USER" --docker-password="${HARBOR_PASSWORD:?HARBOR_PASSWORD 필요}" >/dev/null
    echo "만듦  harbor-pull"
  fi
fi
