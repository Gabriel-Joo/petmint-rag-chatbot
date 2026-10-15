#!/usr/bin/env bash
# kubectl로 직접 적용할 때 쓴다(ArgoCD를 붙이기 전). ArgoCD는 Job을 Sync hook(BeforeHookCreation)으로 지우고 다시 만드므로 필요 없다.
# Job의 Pod 템플릿은 바꿀 수 없다 — 이미지 태그를 바꾸고 그냥 apply하면 "field is immutable"로 Job만 실패한다.
# 그래서 끝난 Job을 먼저 지우고 적용한다. Job은 여러 번 돌려도 결과가 같다(bootstrap·migrate 멱등, 시드는 --if-empty).
#
#   deploy/scripts/apply.sh [kustomize 디렉터리]       # 기본: deploy/
set -euo pipefail
NS=${NS:-petmint}
DIR=${1:-$(cd "$(dirname "$0")/.." && pwd)}

kubectl -n "$NS" delete job petmint-init-db --ignore-not-found --wait=true
# shellcheck disable=SC2086
kubectl kustomize ${KUSTOMIZE_ARGS:-} "$DIR" | kubectl apply -f -
kubectl -n "$NS" wait --for=condition=complete job/petmint-init-db --timeout=600s
kubectl -n "$NS" rollout status deploy/petmint-app --timeout=600s
