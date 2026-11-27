#!/usr/bin/env bash
# 隔离恢复演练：生成备份包 → 独立 Compose 项目恢复 → 就绪/数据/登录核对。
# 用法：bash scripts/recovery-drill.sh [--bundle <已校验的包目录>] [--keep] [--expected-revision <rev>]
#   --bundle             使用已有备份包（需先通过 scripts/verify-backup.sh）；省略则现场生成
#   --keep               演练结束后保留独立项目与卷（默认 down -v 清理）
#   --expected-revision  基线落后 head 的迁移演练：导入后先校验演练库 alembic_version
#                        等于该 revision；跳过启动前逐表计数，改在 prestart 迁移完成、
#                        backend 启动之前再做一次源/演练逐表计数比对；不匹配则失败
# 约束：只在独立 Compose 项目（默认 esa-drill）里操作，绝不触碰当前运行中的库；
#      只启动 db/prestart/backend（不启前端与 acme），不发布任何端口，避免与线上端口冲突。
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"

bundle=""
keep=0
expected_revision=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle) bundle="${2:?需要包目录}"; shift 2 ;;
    --keep) keep=1; shift ;;
    --expected-revision) expected_revision="${2:?需要 revision}"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

drill_project="esa-drill"
drill_db="recovery_drill_$(date +%Y%m%d)"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
log() { printf '%s\n' "$*"; }
now_ms() { python3 -c 'import time;print(int(time.time()*1000))'; }

# 源栈 compose 项目名：后面要 export 演练项目名，源侧核对必须显式指回它，
# 否则 `docker compose exec` 会读到演练栈，表计数比对退化成「自己比自己」。
src_project="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$(docker compose ps -q backend)" 2>/dev/null || true)"
src_project="${src_project:-$(printf '%s' "$(basename "$project_dir")" | tr '[:upper:]' '[:lower:]')}"
src_compose() { env -u COMPOSE_ENV_FILE COMPOSE_PROJECT_NAME="$src_project" docker compose "$@"; }

# 音频卷指纹：文件名 + 内容全量 sha256，用于证明逐字节还原（数量相同不代表内容相同）
audio_digest_py='import hashlib,pathlib
files=sorted(p for p in pathlib.Path("/app/audio").rglob("*") if p.is_file())
h=hashlib.sha256()
for p in files:
    h.update(str(p.relative_to("/app/audio")).encode())
    h.update(p.read_bytes())
print(len(files), h.hexdigest())'

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

# 等待一次性 prestart 容器退出 0；非 0 退出或超时即失败。
wait_prestart() {
  local cid status exit_code _
  cid="$("${compose[@]}" ps -q prestart)"
  [[ -n "$cid" ]] || { echo "prestart 容器不存在" >&2; return 1; }
  for _ in $(seq 1 120); do
    status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || true)"
    if [[ "$status" == "exited" ]]; then
      exit_code="$(docker inspect -f '{{.State.ExitCode}}' "$cid" 2>/dev/null || true)"
      if [[ "$exit_code" == "0" ]]; then
        log "  prestart 迁移完成（ExitCode=0）"
        return 0
      fi
      echo "prestart 迁移失败（ExitCode=${exit_code}）" >&2
      return 1
    fi
    sleep 2
  done
  echo "等待 prestart 退出超时" >&2
  return 1
}

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
# 备份包里的对象属主是受限角色 esa_app/esa_platform（生产同构），空集群里没有这些角色，
# 直接 psql 导入会在第一条 OWNER TO 上失败。先用 admin 连接按演练 env 建角色再导入。
# 不用 ensure_db_roles.py：那需要 backend 镜像，而镜像在下一步才准备。
app_user="$(sed -n 's/^APP_POSTGRES_USER=//p' "$drill_env" | tr -d '\r')"
app_pw="$(sed -n 's/^APP_POSTGRES_PASSWORD=//p' "$drill_env" | tr -d '\r')"
plat_user="$(sed -n 's/^PLATFORM_POSTGRES_USER=//p' "$drill_env" | tr -d '\r')"
plat_pw="$(sed -n 's/^PLATFORM_POSTGRES_PASSWORD=//p' "$drill_env" | tr -d '\r')"
role_sql=""
if [[ -n "$app_user" && -n "$app_pw" ]]; then
  role_sql+="CREATE ROLE ${app_user} LOGIN PASSWORD '${app_pw}' NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;"$'\n'
fi
if [[ -n "$plat_user" && -n "$plat_pw" ]]; then
  role_sql+="CREATE ROLE ${plat_user} LOGIN PASSWORD '${plat_pw}' NOSUPERUSER BYPASSRLS NOCREATEROLE NOCREATEDB;"$'\n'
fi
if [[ -n "$role_sql" ]]; then
  printf '%s' "$role_sql" | "${compose[@]}" exec -T db sh -c 'psql --quiet --set ON_ERROR_STOP=on -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null
  log "  已按演练 env 建角色: ${app_user:-} ${plat_user:-}"
fi
gzip -dc "$bundle/database.sql.gz" | "${compose[@]}" exec -T db sh -c 'psql --quiet --set ON_ERROR_STOP=on -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null
log "  数据库导入完成: $(( ($(now_ms)-t0)/1000 ))s"

# 基线落后 head 的迁移演练：导入后先核对 alembic_version，不匹配直接失败。
if [[ -n "${expected_revision}" ]]; then
  actual_rev="$("${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select version_num from alembic_version"' | tr -d ' \r')"
  if [[ "${actual_rev}" != "${expected_revision}" ]]; then
    echo "演练库 alembic revision 不符：导入后为 ${actual_rev:-（空）}，期望 ${expected_revision}" >&2
    exit 1
  fi
  log "  导入后 alembic revision: ${actual_rev}（与期望一致）"
fi

# ---------- 3b. 逐表计数比对 ----------
# 必须在 prestart/backend 启动之前比：启动会回填派生快照（如 admin_metrics_daily
# 的历史行），那是"启动行为"不是"还原结果"，混在一起会误判成备份差异。
# 基线落后 head（--expected-revision）时跳过启动前比对：旧基线必然缺 head 新表，
# 属预期迁移范围；改在 prestart 跑完迁移、backend 启动之前再比一次。
count_sql="select table_name, (xpath('/row/c/text()', query_to_xml('select count(*) as c from public.'||quote_ident(table_name), false, true, '')))[1]::text::int as cnt from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by table_name"
mismatch=0

compare_counts() {
  local label="$1"
  local src_counts dst_counts name src dst flag tables diff
  src_counts="$(src_compose exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"${count_sql}\"")"
  dst_counts="$("${compose[@]}" exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"${count_sql}\"")"
  printf '%-34s %10s %10s %s\n' 表 源 演练 一致
  tables=0; diff=0
  while IFS='|' read -r name src; do
    [[ -z "$name" ]] && continue
    tables=$((tables+1))
    dst="$(printf '%s\n' "$dst_counts" | awk -F'|' -v n="$name" '$1==n{print $2}')"
    flag="OK"; [[ "$src" = "$dst" ]] || { flag="DIFF"; diff=$((diff+1)); }
    printf '%-34s %10s %10s %s\n' "$name" "$src" "$dst" "$flag"
  done <<< "$src_counts"
  mismatch=$((mismatch+diff))
  log "  ${label}：比对表数 ${tables}；差异 ${diff} 处"
}

if [[ -z "${expected_revision}" ]]; then
  compare_counts "还原后比对（启动前口径）"
fi

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
if [[ -n "${expected_revision}" ]]; then
  # 先只起 prestart（一次性迁移容器），等它 Exit 0 再做迁移后计数，最后才起 backend；
  # 避免 backend 启动回填干扰计数比对。
  "${compose[@]}" up -d prestart
  wait_prestart
  compare_counts "迁移后比对（prestart 完成、backend 启动前口径）"
  "${compose[@]}" up -d backend
else
  "${compose[@]}" up -d prestart backend
fi
log "  音频恢复 + 拉起耗时: $(( ($(now_ms)-t0)/1000 ))s"

for _ in $(seq 1 90); do
  if "${compose[@]}" exec -T backend python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/utils/ready-check/')" >/dev/null 2>&1; then break; fi
  sleep 2
done
"${compose[@]}" exec -T backend python -c "import urllib.request;print('ready-check:', urllib.request.urlopen('http://localhost:8000/api/v1/utils/ready-check/').status)"

# ---------- 5. 业务核对 ----------
log "== 4/5 数据与登录核对 =="
# 逐表计数已在 3b（或迁移后口径）完成；这里只做启动后的可用性验证。

drill_audio="$("${compose[@]}" exec -T backend sh -c 'ls -A /app/audio | wc -l' | tr -d ' ')"
log "  演练库音频文件数: ${drill_audio}"

# 音频逐字节校验：数量相同不代表内容相同（0.5s 占位 wav 也可能同名不同内容）
src_audio_digest="$(src_compose exec -T backend python -c "$audio_digest_py" | tr -d '\r')"
dst_audio_digest="$("${compose[@]}" exec -T backend python -c "$audio_digest_py" | tr -d '\r')"
audio_flag="OK"
if [[ "$src_audio_digest" = "$dst_audio_digest" ]]; then
  log "  音频指纹: OK（${src_audio_digest%% *} 个文件逐字节一致）"
else
  audio_flag="DIFF"; mismatch=$((mismatch+1))
  log "  音频指纹: DIFF（源 ${src_audio_digest} / 演练 ${dst_audio_digest}）"
fi

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

# 业务可用性探针：种子学生登录 → 拉一条作答音频 → 断言字节数 >0
# （表计数只证明行在，这条证明「行 + 角色 + RLS + 音频卷」连起来还能用）
probe_aid="$(src_compose exec -T db sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"select a.id from attempt a join student s on s.id=a.student_id join public.\\\"user\\\" u on u.id=s.user_id where u.username='s10001' limit 1\"" | tr -d ' \r')"
if [[ -n "$probe_aid" ]]; then
  if "${compose[@]}" exec -T -e DRILL_AID="$probe_aid" backend python - <<'PY' >/dev/null 2>&1
import json, os, urllib.parse, urllib.request
base = "http://localhost:8000/api/v1"
data = urllib.parse.urlencode({"username": "s10001", "password": "SeedPilot2026"}).encode()
req = urllib.request.Request(base + "/login/access-token?school=seedpilot-01", data=data,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
token = json.load(urllib.request.urlopen(req))["access_token"]
req = urllib.request.Request(f"{base}/attempts/{os.environ['DRILL_AID']}/audio",
                             headers={"Authorization": f"Bearer {token}"})
body = urllib.request.urlopen(req).read()
assert len(body) > 1000, f"audio too small: {len(body)}"
PY
  then
    log "  业务探针: OK（种子学生登录 + 作答音频可回放，attempt=${probe_aid:0:8}）"
    probe_ok=1
  else
    log "  业务探针: FAIL（种子学生登录或音频回放失败）"
    probe_ok=0
  fi
else
  log "  业务探针: 跳过（源库无 s10001 作答）"
  probe_ok=1
fi

# ---------- 6. 结果 ----------
log "== 5/5 汇总 =="
log "  备份包: $bundle"
log "  独立库: ${drill_project} / ${drill_db}（与运行中库完全分离）"
log "  表计数差异: ${mismatch} 处；音频指纹: ${audio_flag}；登录: $([[ ${login_ok} = 1 ]] && echo OK || echo FAIL)；业务探针: $([[ ${probe_ok} = 1 ]] && echo OK || echo FAIL)"
drill_ok=1
if [[ ${mismatch} -ne 0 || ${login_ok} -ne 1 || ${probe_ok} -ne 1 ]]; then
  log "  演练未通过，保留现场以便排查（--keep 生效）"
  keep=1
  drill_ok=0
fi

if [[ ${keep} -eq 1 ]]; then
  log "  保留独立项目；清理命令: COMPOSE_PROJECT_NAME=${drill_project} COMPOSE_ENV_FILE=${drill_env} docker compose down -v"
else
  "${compose[@]}" down -v >/dev/null 2>&1 || true
  log "  已清理独立项目与卷"
fi

# 失败必须以非 0 退出：即使 --keep 保留现场，CI/上线自动化也不能把失败误判成成功。
if [[ ${drill_ok} -eq 1 ]]; then
  exit 0
else
  exit 1
fi
