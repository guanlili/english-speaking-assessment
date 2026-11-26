#!/usr/bin/env bash
# Local disaster-recovery bundle: database + audio volume + deployment config.
set -euo pipefail
umask 077
project_dir="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$project_dir"
mkdir -p backups
chmod 700 backups
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
# Only complete bundles expire; failed/in-progress files are never usable backups.
find "$PWD/backups" -maxdepth 1 -type d -name 'bundle-*' -mtime +14 -exec rm -rf {} +
find "$PWD/backups" -maxdepth 1 -type f \( -name 'app-*.sql.gz' -o -name 'env-*.env' \) -mtime +14 -delete
echo "Backup complete: $bundle"
