#!/usr/bin/env bash
# 호스트(GPU 머신)에서 리포의 약관·시드 디렉터리를 NFS로 읽기 전용 공유한다 — 클러스터 PV(ronanlab-infra apps/petmint/data/nfs.yaml)가 붙는 곳.
# sudo로 사람이 한 번 돌린다. 여러 번 돌려도 같다.
#
#   sudo deploy/scripts/host-nfs-setup.sh            # 리포 경로는 이 스크립트 위치에서 찾는다
#
# - 공유 대상은 /srv/nfs/petmint/{chunks,graph,fixtures} — 리포 디렉터리를 읽기 전용 bind mount(/etc/fstab)한 것.
#   PV에 홈 경로가 박히지 않고, 리포를 옮기면 fstab만 바꾼다
# - 사설망(192.168.122.0/24)에만 연다: exports 대상 대역 + ufw는 virbr0에서 오는 2049만 허용
# - NFSv4만 쓴다(v3 끔) — 2049 하나만 열면 되고 rpcbind(111)·mountd·statd를 띄우지 않는다
# - all_squash: 클라이언트 uid와 상관없이 nobody로 읽는다. 파일이 644·디렉터리가 755여야 한다(지금 그렇다)
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "sudo로 돌린다" >&2; exit 1; }
REPO=$(cd "$(dirname "$0")/../.." && pwd)
NET=192.168.122.0/24
ROOT=/srv/nfs/petmint
declare -A SRC=([chunks]=data/chunks [graph]=data/graph [fixtures]=app/fixtures)
declare -A FSID=([chunks]=101 [graph]=102 [fixtures]=103)   # bind mount는 같은 파일시스템이다 — export마다 fsid를 따로 준다

for d in "${!SRC[@]}"; do [[ -d "$REPO/${SRC[$d]}" ]] || { echo "없음: $REPO/${SRC[$d]}" >&2; exit 1; }; done

echo "--- 1. 패키지"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nfs-kernel-server >/dev/null

echo "--- 2. NFSv4만"
mkdir -p /etc/nfs.conf.d
cat > /etc/nfs.conf.d/petmint.conf <<'EOF'
# petmint: NFSv4만(2049). v3·UDP를 끄면 rpcbind·mountd·statd 포트를 열 필요가 없다
[nfsd]
vers3=n
udp=n
EOF
systemctl mask --now rpc-statd.service rpcbind.service rpcbind.socket >/dev/null 2>&1 || true

echo "--- 3. 읽기 전용 bind mount ($ROOT)"
sed -i "\#[[:space:]]$ROOT/#d" /etc/fstab
for d in chunks graph fixtures; do
  mkdir -p "$ROOT/$d"
  echo "$REPO/${SRC[$d]} $ROOT/$d none bind,ro 0 0" >> /etc/fstab
  findmnt -n "$ROOT/$d" >/dev/null && umount "$ROOT/$d"
  mount "$ROOT/$d"
done

echo "--- 4. exports ($NET 만)"
mkdir -p /etc/exports.d
: > /etc/exports.d/petmint.exports
for d in chunks graph fixtures; do
  echo "$ROOT/$d $NET(ro,all_squash,no_subtree_check,sec=sys,fsid=${FSID[$d]})" >> /etc/exports.d/petmint.exports
done
systemctl enable -q nfs-server
systemctl restart nfs-server
exportfs -ra

echo "--- 5. ufw: virbr0에서 오는 2049만"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow in on virbr0 from "$NET" to 192.168.122.1 port 2049 proto tcp comment 'petmint nfs' >/dev/null
  ufw status | grep -E "2049" || true
fi

echo "--- 확인"
exportfs -v
for d in chunks graph fixtures; do findmnt -n -o TARGET,SOURCE,OPTIONS "$ROOT/$d"; done
echo "듣는 포트(2049만 있어야 한다):"
ss -ltnup | grep -E ':(111|2049|20048|662|875)\b' || true
