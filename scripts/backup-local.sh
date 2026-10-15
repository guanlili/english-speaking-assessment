#!/usr/bin/env bash
# Local disaster-recovery bundle: database + audio volume + deployment config.
set -euo pipefail
umask 077
project_dir="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$project_dir"
mkdir -p backups
chmod 700 backups
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
cp .env "$staging/config.env"
{
  echo 'format=1'
  echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "commit=$(git rev-parse HEAD)"
  echo 'consistency=online; stop writes for a consistent database/audio snapshot'
} > "$staging/metadata.txt"
(cd "$staging" && sha256sum database.sql.gz audio.tar.gz config.env metadata.txt > manifest.sha256)
bundle="$PWD/backups/bundle-$(date -u +%Y%m%dT%H%M%SZ)-${staging##*-}"
mv "$staging" "$bundle"
# Only complete bundles expire; failed/in-progress files are never usable backups.
find "$PWD/backups" -maxdepth 1 -type d -name 'bundle-*' -mtime +14 -exec rm -rf {} +
find "$PWD/backups" -maxdepth 1 -type f \( -name 'app-*.sql.gz' -o -name 'env-*.env' \) -mtime +14 -delete
echo "Backup complete: $bundle"
