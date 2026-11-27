#!/usr/bin/env bash
# Local disaster-recovery bundle: database + audio volume + deployment config.
set -euo pipefail
umask 077
project_dir="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$project_dir"
mkdir -p backups
# 目录 750 / 文件 640：属主可读写，同组（巡检监控用户）可读 manifest 与归档，
# 其他用户不可进入。旧版 700/600 + root:root 手工包会让 deploy 身份的巡检
# 无法读取清单（2026-11-27「备份新鲜度」红灯根因）。
chmod 750 backups
# flock availability check: refuse to run lockless instead of silently racing.
# Linux ships flock in util-linux; macOS has no flock by default (see message below).
if ! command -v flock >/dev/null 2>&1; then
  cat >&2 <<'EOF'
flock not found on PATH: refusing to run without an exclusive backup lock.
  - Linux: install util-linux (provides flock), e.g. `apt install util-linux` or `yum install util-linux`.
  - macOS: `brew install flock`, or run this backup on a Linux host/container where flock is available.
Do not continue without a lock: concurrent cron/manual backups can produce a corrupted bundle.
EOF
  exit 1
fi
# Daily cron and manual runs must not race with each other or retention cleanup.
exec 9>backups/.backup.lock
flock -n 9 || { echo 'A backup is already running' >&2; exit 1; }
staging=$(mktemp -d "$PWD/backups/.bundle-XXXXXXXX")
trap 'rm -rf "$staging"' EXIT
compose=(docker compose -f compose.yml)
"${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$staging/database.sql"
test -s "$staging/database.sql"
gzip "$staging/database.sql"
"${compose[@]}" exec -T backend tar -C /app/audio -czf - . > "$staging/audio.tar.gz"
gzip -t "$staging/database.sql.gz" "$staging/audio.tar.gz"
tar -tzf "$staging/audio.tar.gz" > /dev/null
# Size/structure floors: gzip -t and tar -tzf both pass on empty archives, so a
# 17K dump or a 105-byte audio tar used to land as a "green" bundle that restored
# to nothing. A real production dump is ~2.3MB and the audio volume is ~1.6GB.
min_db_bytes="${BACKUP_MIN_DB_BYTES:-500000}"
min_audio_bytes="${BACKUP_MIN_AUDIO_BYTES:-102400}"
min_tables="${BACKUP_MIN_TABLES:-25}"
db_bytes=$(wc -c < "$staging/database.sql.gz")
audio_bytes=$(wc -c < "$staging/audio.tar.gz")
[ "$db_bytes" -ge "$min_db_bytes" ] || {
  echo "Backup aborted: database dump is ${db_bytes}B, below floor ${min_db_bytes}B" >&2
  exit 1
}
[ "$audio_bytes" -ge "$min_audio_bytes" ] || {
  echo "Backup aborted: audio archive is ${audio_bytes}B, below floor ${min_audio_bytes}B" >&2
  exit 1
}
# gzip -dc instead of zcat: macOS zcat treats .gz as compress .Z and fails here,
# which used to abort the bundle as "0 tables". gzip -dc works on both Linux and macOS.
tables=$(gzip -dc "$staging/database.sql.gz" | grep -c '^CREATE TABLE' || true)
[ "$tables" -ge "$min_tables" ] || {
  echo "Backup aborted: dump only carries ${tables} tables, expected >= ${min_tables}" >&2
  exit 1
}
attempt_rows=$("${compose[@]}" exec -T db sh -c \
  'psql -U "$POSTGRES_USER" "$POSTGRES_DB" -tAc "select count(*) from attempt"' 2>/dev/null \
  | tr -d '[:space:]' || true)
attempt_rows="${attempt_rows:-0}"
cp .env "$staging/config.env"
{
  echo 'format=1'
  echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit=$(git rev-parse HEAD)"
  echo 'consistency=online; stop writes for a consistent database/audio snapshot'
  echo "attempt_rows=${attempt_rows}"
  echo "database_bytes=${db_bytes}"
  echo "audio_bytes=${audio_bytes}"
} > "$staging/metadata.txt"
(cd "$staging" && sha256sum database.sql.gz audio.tar.gz config.env metadata.txt > manifest.sha256)
bundle="$PWD/backups/bundle-$(date -u +%Y%m%dT%H%M%SZ)-${staging##*-}"
mv "$staging" "$bundle"

# 属主/权限归一：以 backups 目录当前属主为目标（cron 下即 deploy:deploy），
# 手工以 root 跑也会把产物交回运行用户；可用 BACKUP_OWNER/BACKUP_GROUP 覆盖。
# 非 root 无权 chown，此时产物本就属于当前用户，跳过属主变更只收敛权限位。
bundle_owner="${BACKUP_OWNER:-$(ls -ld backups | awk '{print $3}')}"
bundle_group="${BACKUP_GROUP:-$(ls -ld backups | awk '{print $4}')}"
if [ "$(id -u)" = 0 ]; then
  chown -R "$bundle_owner:$bundle_group" "$bundle"
fi
chmod 750 "$bundle"
find "$bundle" -type f -exec chmod 640 {} +

# 保留策略：按包名 `bundle-YYYYMMDDTHHMMSSZ-*` 里的时间戳判定年龄，不看目录
# mtime（历史上批量拷贝/恢复会把 mtime 重置成同一天，按 mtime 判定会让超期包滞留）。
# 时间戳定宽 ISO 格式，字符串字典序即时间顺序，无需转 epoch（兼容 GNU/BSD date）。
retention_days="${BACKUP_RETENTION_DAYS:-14}"
if date -d '1 second ago' +%s >/dev/null 2>&1; then
  cutoff_stamp=$(date -u -d "@$(( $(date -u +%s) - retention_days * 86400 ))" +%Y%m%dT%H%M%SZ)
else
  cutoff_stamp=$(date -u -v-"${retention_days}"d +%Y%m%dT%H%M%SZ)
fi

for dir in "$PWD"/backups/bundle-*; do
  [ -d "$dir" ] || continue
  base=$(basename "$dir")
  # .BROKEN 是失败残留，任何年龄都不作为可用备份，直接清掉。
  if [[ "$base" == *.BROKEN ]]; then
    echo "Removing broken bundle: $base"
    rm -rf "$dir"
    continue
  fi
  stamp=$(printf '%s' "$base" | sed -nE 's/^bundle-([0-9]{8}T[0-9]{6}Z)-.*/\1/p')
  if [ -z "$stamp" ]; then
    echo "Skipping retention for unparseable bundle name: $base" >&2
    continue
  fi
  if [[ "$stamp" < "$cutoff_stamp" ]]; then
    echo "Removing expired bundle (${retention_days}d by name timestamp): $base"
    rm -rf "$dir"
  fi
done
# 旧版单文件快照（predeploy pg_dump / env 快照）仍按 mtime 保留 14 天。
find "$PWD/backups" -maxdepth 1 -type f \( -name 'app-*.sql.gz' -o -name 'env-*.env' \) -mtime +14 -delete
echo "Backup complete: $bundle"
