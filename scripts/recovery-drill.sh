#!/usr/bin/env bash
# 隔离恢复演练：生成备份包 → 独立 Compose 项目恢复 → 就绪/数据/登录核对。
# 用法：bash scripts/recovery-drill.sh [--bundle <已校验的包目录>] [--keep]
#   --bundle  使用已有备份包（需先通过 scripts/verify-backup.sh）；省略则现场生成
#   --keep    演练结束后保留独立项目与卷（默认 down -v 清理）
# 约束：只在独立 Compose 项目（默认 esa-drill）里操作，绝不触碰当前运行中的库；
#      只启动 db/prestart/backend（不启前端与 acme），不发布任何端口，避免与线上端口冲突。
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"

bundle=""
keep=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle) bundle="${2:?需要包目录}"; shift 2 ;;
    --keep) keep=1; shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

drill_project="esa-drill"
drill_db="recovery_drill_$(date +%Y%m%d)"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
log() { printf '%s\n' "$*"; }
now_ms() { python3 -c 'import time;print(int(time.time()*1000))'; }

# ---------- 0. 前置检查 ----------
docker compose version >/dev/null 2>&1 || { echo "需要 docker compose v2" >&2; exit 1; }
if docker ps --format '{{.Names}}' | grep -q "${drill_project}-"; then
  echo "独立项目 ${drill_project} 已在运行：先 'COMPOSE_PROJECT_NAME=${drill_project} docker compose down -v'" >&2
  exit 1
fi
running="$(docker compose ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk '$2=="running"{print $1}' | tr '\n' ' ')"
log "当前运行服务: ${running:-（无）}"
case "$running" in *db*|*backend*) ;; *) echo "源栈的 db/backend 未运行，无法生成备份包" >&2; exit 1 ;; esac

# ---------- 1. 备份包 ----------
if [[ -z "$bundle" ]]; then
  log "== 1/5 生成备份包 =="
  t0=$(now_ms)
  staging="$(mktemp -d "$project_dir/backups/.drill-XXXXXXXX")"
  trap 'rm -rf "$staging"' EXIT
  docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$staging/database.sql.gz"
  docker compose exec -T backend tar -C /app/audio -czf - . > "$staging/audio.tar.gz"
  cp .env "$staging/config.env"
  {
    echo 'format=1'
    echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "commit=$(git rev-parse HEAD)"
    echo 'consistency=online; stop writes for a consistent database/audio snapshot'
    echo 'source=recovery-drill.sh (local stack)'
  } > "$staging/metadata.txt"
  (cd "$staging" && sha256sum database.sql.gz audio.tar.gz config.env metadata.txt > manifest.sha256)
  suffix="$(python3 -c 'import secrets;print(secrets.token_hex(3))')"
  bundle="$project_dir/backups/bundle-drill-${stamp}-${suffix}"
  mv "$staging" "$bundle"
  trap - EXIT
  log "  包: $bundle"
  log "  生成耗时: $(( ($(now_ms)-t0)/1000 ))s"
fi

log "== 2/5 校验备份包 =="
bash scripts/verify-backup.sh "$bundle"
audio_files="$(tar -tzf "$bundle/audio.tar.gz" | grep -vc '/$' || true)"
log "  音频条目: ${audio_files}"

# ---------- 2. 独立环境 ----------
log "== 3/5 准备独立项目 ${drill_project} / ${drill_db} =="
drill_env="$(mktemp "$project_dir/backups/.drill-env-XXXXXXXX")"
trap 'rm -f "$drill_env"' EXIT
sed -e "s/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=${drill_project}/" \
    -e "s/^POSTGRES_DB=.*/POSTGRES_DB=${drill_db}/" \
    -e "s/^SMTP_HOST=.*/SMTP_HOST=/" \
    -e "s/^COST_ALERT_EMAIL=.*/COST_ALERT_EMAIL=/" \
    .env > "$drill_env"

export COMPOSE_PROJECT_NAME="$drill_project"
export COMPOSE_ENV_FILE="$drill_env"
# db 服务的库名来自 compose 变量插值（不是 env_file），必须用 --env-file 指向演练环境，
# 否则会出现 backend 连演练库、db 里却是原库名的错配。
compose=(docker compose -f compose.yml --env-file "$drill_env")

cleanup_env() { rm -f "${drill_env:-}"; }
trap 'cleanup_env' EXIT

# ---------- 3. 恢复数据库 ----------
t0=$(now_ms)
# 上一轮的残留容器不会自动消失，先按项目名清场，保证 db 用的是本轮 drill 库名
"${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
"${compose[@]}" up -d db
actual_db="$("${compose[@]}" exec -T db sh -c 'printf %s "$POSTGRES_DB"' | tr -d ' \r')"
if [[ "$actual_db" != "$drill_db" ]]; then
  echo "演练库名不符：容器内 POSTGRES_DB=${actual_db}，期望 ${drill_db}" >&2
  exit 1
fi
for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then break; fi
  sleep 2
done
set -o pipefail
gzip -dc "$bundle/database.sql.gz" | "${compose[@]}" exec -T db sh -c 'psql --quiet --set ON_ERROR_STOP=on -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null
log "  数据库导入完成: $(( ($(now_ms)-t0)/1000 ))s"

# ---------- 4. 恢复音频到空卷并拉起 ----------
t0=$(now_ms)
# 镜像已在本地（同机源栈构建过）就直接复用，避免演练被镜像仓库网络阻塞
if docker image inspect esa-backend >/dev/null 2>&1; then
  log "  复用本机已有镜像 esa-backend"
else
  log "  本机无 esa-backend，需构建（依赖可达的镜像仓库）"
  "${compose[@]}" build backend >/dev/null
fi
"${compose[@]}" run --rm --no-deps -T --entrypoint sh backend -c 'test -z "$(ls -A /app/audio)" && tar -C /app/audio -xzf -' < "$bundle/audio.tar.gz"
"${compose[@]}" up -d prestart backend
log "  音频恢复 + 拉起耗时: $(( ($(now_ms)-t0)/1000 ))s"

for _ in $(seq 1 90); do
  if "${compose[@]}" exec -T backend python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/utils/ready-check/')" >/dev/null 2>&1; then break; fi
  sleep 2
done
"${compose[@]}" exec -T backend python -c "import urllib.request;print('ready-check:', urllib.request.urlopen('http://localhost:8000/api/v1/utils/ready-check/').status)"

# ---------- 5. 业务核对 ----------
log "== 4/5 数据与登录核对 =="
# 动态枚举 public schema 所有基表并精确计数（表名进维护会变，硬编码列表迟早失效）
count_sql="select table_name, (xpath('/row/c/text()', query_to_xml('select count(*) as c from public.'||quote_ident(table_name), false, true, '')))[1]::text::int as cnt from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by table_name"
src_counts="$(docker compose exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"${count_sql}\"")"
dst_counts="$("${compose[@]}" exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"${count_sql}\"")"
printf '%-34s %10s %10s %s\n' 表 源 演练 一致
mismatch=0
tables=0
while IFS='|' read -r name src; do
  [[ -z "$name" ]] && continue
  tables=$((tables+1))
  dst="$(printf '%s\n' "$dst_counts" | awk -F'|' -v n="$name" '$1==n{print $2}')"
  flag="OK"; [[ "$src" = "$dst" ]] || { flag="DIFF"; mismatch=$((mismatch+1)); }
  printf '%-34s %10s %10s %s\n' "$name" "$src" "$dst" "$flag"
done <<< "$src_counts"
log "  比对表数: ${tables}；差异: ${mismatch}"

drill_audio="$("${compose[@]}" exec -T backend sh -c 'ls -A /app/audio | wc -l' | tr -d ' ')"
log "  演练库音频文件数: ${drill_audio}"

login_user="$(grep -E '^FIRST_SUPERUSER=' "$drill_env" | cut -d= -f2-)"
login_pass="$(grep -E '^FIRST_SUPERUSER_PASSWORD=' "$drill_env" | cut -d= -f2-)"
if "${compose[@]}" exec -T -e DRILL_USER="$login_user" -e DRILL_PASS="$login_pass" backend python - <<'PY' >/dev/null 2>&1
import os, urllib.parse, urllib.request
data = urllib.parse.urlencode({"username": os.environ["DRILL_USER"], "password": os.environ["DRILL_PASS"]}).encode()
req = urllib.request.Request("http://localhost:8000/api/v1/login/access-token", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
resp = urllib.request.urlopen(req)
assert b"access_token" in resp.read()
PY
then
  log "  登录 API: OK（${login_user}）"
  login_ok=1
else
  log "  登录 API: 失败（请人工核对凭据）"
  login_ok=0
fi

# ---------- 6. 结果 ----------
log "== 5/5 汇总 =="
log "  备份包: $bundle"
log "  独立库: ${drill_project} / ${drill_db}（与运行中库完全分离）"
log "  表计数差异: ${mismatch} 处；登录: $([[ ${login_ok} = 1 ]] && echo OK || echo FAIL)"
if [[ ${mismatch} -ne 0 || ${login_ok} -ne 1 ]]; then
  log "  演练未通过，保留现场以便排查（--keep 生效）"
  keep=1
fi

if [[ ${keep} -eq 1 ]]; then
  log "  保留独立项目；清理命令: COMPOSE_PROJECT_NAME=${drill_project} COMPOSE_ENV_FILE=${drill_env} docker compose down -v"
else
  "${compose[@]}" down -v >/dev/null 2>&1 || true
  log "  已清理独立项目与卷"
fi
