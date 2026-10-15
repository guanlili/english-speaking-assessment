#!/usr/bin/env bash
# Read-only verification before any restore operations.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash scripts/verify-backup.sh /path/to/bundle-directory' >&2
  exit 2
fi
cd "$1"
# Require the fixed file set; do not accept arbitrary paths from a manifest.
test "$(wc -l < manifest.sha256 | tr -d ' ')" = 4
for name in database.sql.gz audio.tar.gz config.env metadata.txt; do
  test -f "$name" && test ! -L "$name"
  escaped=${name//./[.]}
  [[ $(grep -Ec "^[a-f0-9]{64}  $escaped$" manifest.sha256) = 1 ]]
done
sha256sum --check manifest.sha256
gzip -t database.sql.gz audio.tar.gz
tar -tzf audio.tar.gz > /dev/null
echo 'Backup verification passed; no data was restored.'
