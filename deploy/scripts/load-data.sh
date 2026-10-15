#!/usr/bin/env bash
# 약관(chunks, graph)과 고객 시드 픽스처를 PVC petmint-data에 넣는다 — 리포가 있는 호스트에서 돌린다.
# kubectl cp는 API 서버를 거쳐 사설 네트워크 안에서만 오간다. 약관이 외부(GitHub·Harbor)로 나가지 않는다(01번).
#
#   deploy/scripts/load-data.sh [리포 경로]
#
# 넣은 뒤 MANIFEST.sha256을 함께 남긴다 — 호스트의 Milvus 색인과 같은 청크인지 나중에 대조할 수 있게.
# 앱이 이미 떠 있으면 다시 넣은 뒤 재시작해야 읽는다(기동 때 읽는다): kubectl -n petmint rollout restart deploy/petmint-app
set -euo pipefail
NS=${NS:-petmint}
REPO=${1:-$(cd "$(dirname "$0")/../.." && pwd)}
POD=petmint-data-loader

for f in data/chunks/petmint_강아지.json data/chunks/petmint_고양이.json data/chunks/hr_인사규정.json \
         data/graph/petmint_강아지_graph.json data/graph/petmint_고양이_graph.json data/graph/hr_인사규정_graph.json \
         app/fixtures/customers.json; do
  [[ -s "$REPO/$f" ]] || { echo "없음: $REPO/$f" >&2; exit 1; }
done

kubectl apply -f "$REPO/deploy/data/loader-pod.yaml"
trap 'kubectl -n "$NS" delete pod "$POD" --wait=false >/dev/null 2>&1 || true' EXIT
kubectl -n "$NS" wait --for=condition=Ready "pod/$POD" --timeout=180s

for d in chunks graph; do
  for f in "$REPO"/data/$d/*.json; do kubectl -n "$NS" cp "$f" "$POD:/data/$d/$(basename "$f")"; done
done
kubectl -n "$NS" cp "$REPO/app/fixtures/customers.json" "$POD:/data/fixtures/customers.json"

MANIFEST=$(mktemp)
(cd "$REPO" && sha256sum data/chunks/*.json data/graph/*.json app/fixtures/customers.json) > "$MANIFEST"
kubectl -n "$NS" cp "$MANIFEST" "$POD:/data/MANIFEST.sha256"
rm -f "$MANIFEST"

echo "--- 볼륨 내용"
kubectl -n "$NS" exec "$POD" -- sh -c 'cd /data && ls -l chunks graph fixtures && cat MANIFEST.sha256'
