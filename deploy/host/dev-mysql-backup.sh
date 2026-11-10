#!/usr/bin/env bash
# 호스트 도커 MySQL(로컬 개발, 컨테이너 mysql, 127.0.0.1:3306)의 주 1회 백업 — 12번 1-5절.
# 사용자 crontab(일 05:00)이 돌린다. 운영 백업(클러스터 CronJob)과 다른 디렉터리에 둔다 —
# 운영 쪽 보존 정리가 petmint-*.sql.gz를 지우므로 같은 곳에 두면 서로 지운다.
#
#   0 5 * * 0 /home/kopo17/AI_programming/petmint-rag-chatbot/deploy/host/dev-mysql-backup.sh >> /home/kopo17/backup/mysql/petmint-dev/backup.log 2>&1
#
# - --single-transaction: 락 없이(개발 서버가 떠 있어도 된다)
# - 비밀번호는 컨테이너 안의 MYSQL_ROOT_PASSWORD를 MYSQL_PWD로 — 명령 인자 · 이 파일에 값이 없다
# - .part로 쓰고 gzip -t · 끝 줄 확인 뒤 이름을 바꾼다. 보존은 최신 KEEP(기본 4)개
set -euo pipefail
umask 027
D=${BACKUP_DIR:-$HOME/backup/mysql/petmint-dev}
KEEP=${KEEP:-4}
C=${CONTAINER:-mysql}
mkdir -p "$D"; chmod 750 "$D"
F="petmint-dev-$(date +%Y%m%d-%H%M%S).sql.gz"
echo "[$(date '+%F %T')] 시작 $F"
find "$D" -maxdepth 1 -name '.petmint-dev-*.part' -mmin +60 -delete
docker exec "$C" sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --quick --routines --triggers --events --no-tablespaces --set-gtid-purged=OFF --hex-blob --databases petmint insurance_core' \
  | gzip -6 > "$D/.$F.part"
gzip -t "$D/.$F.part"
zcat "$D/.$F.part" | tail -n 1 | grep -q '^-- Dump completed' || { echo "덤프 끝 줄이 없다"; exit 1; }
mv "$D/.$F.part" "$D/$F"
(cd "$D" && sha256sum "$F" > "$F.sha256")
echo "[$(date '+%F %T')] 백업 $F $(stat -c %s "$D/$F")바이트"
ls -1t "$D"/petmint-dev-*.sql.gz | tail -n +$((KEEP + 1)) | while read -r f; do
  rm -f "$f" "$f.sha256"; echo "지움 $(basename "$f")"
done
echo "남은 백업 $(ls -1 "$D"/petmint-dev-*.sql.gz | wc -l)개"
