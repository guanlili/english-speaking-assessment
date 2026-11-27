#!/usr/bin/env bash
# 上线 smoke 只读检查（#517）。默认 dry-run：只打印将执行的检查，不发网络/SSH 请求。
#
# 安全边界：
#   - 只发 GET；只读 SQL；只读 git / docker / nginx / 日志。
#   - 不登录、不写库、不发布、不重启、不部署。
#   - token 只从环境变量读取，不落盘、不回显；错误输出不打印 Authorization 头。
#
# 用法：
#   bash scripts/go-live-smoke.sh                 # dry-run，全部段落
#   bash scripts/go-live-smoke.sh --pre --execute # 部署前只读检查
#   bash scripts/go-live-smoke.sh --post --execute
#
# 常用环境变量见 docs/go-live-smoke-checklist.md；token 变量：
#   SMOKE_PLATFORM_TOKEN / SMOKE_PLATFORM_COOKIE（平台运营；也兼容 SMOKE_ADMIN_*）
#   SMOKE_SCHOOL_TOKEN   / SMOKE_SCHOOL_COOKIE  （学校管理员/教师，用于 403 与口语页）
#   SMOKE_SSH_TARGET, SMOKE_DEPLOY_PATH          （可选；服务器只读检查）
#
# 退出码：0 = 没有 FAIL（MANUAL 不算失败）；1 = 至少一项 FAIL；2 = 参数错误。

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="both"
EXECUTE=0

usage() {
  cat <<'EOF'
上线 smoke 只读检查（#517）。默认 dry-run：只打印将执行的检查，不发网络/SSH 请求。

安全边界：
  - 只发 GET；只读 SQL；只读 git / docker / nginx / 日志。
  - 不登录、不写库、不发布、不重启、不部署。
  - token 只从环境变量读取，不落盘、不回显；错误输出不打印 Authorization 头。

用法：
  bash scripts/go-live-smoke.sh                 # dry-run，全部段落
  bash scripts/go-live-smoke.sh --pre --execute # 部署前只读检查
  bash scripts/go-live-smoke.sh --post --execute

常用环境变量见 docs/go-live-smoke-checklist.md；token 变量：
  SMOKE_PLATFORM_TOKEN / SMOKE_PLATFORM_COOKIE（平台运营；也兼容 SMOKE_ADMIN_*）
  SMOKE_SCHOOL_TOKEN   / SMOKE_SCHOOL_COOKIE  （学校管理员/教师，用于 403 与口语页）
  SMOKE_SSH_TARGET, SMOKE_DEPLOY_PATH          （可选；服务器只读检查）

退出码：0 = 没有 FAIL（MANUAL 不算失败）；1 = 至少一项 FAIL；2 = 参数错误。
EOF
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pre) MODE="pre" ;;
    --post) MODE="post" ;;
    --all) MODE="both" ;;
    --execute) EXECUTE=1 ;;
    --dry-run) EXECUTE=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
  shift
done

BASE_URL="${SMOKE_BASE_URL:-}"
WEB_URL="${SMOKE_WEB_URL:-$BASE_URL}"
API_BASE="${SMOKE_API_BASE:-}"
if [[ -z "$API_BASE" && -n "$BASE_URL" ]]; then API_BASE="${BASE_URL%/}/api/v1"; fi
API_BASE="${API_BASE%/}"

PLATFORM_TOKEN="${SMOKE_PLATFORM_TOKEN:-${SMOKE_ADMIN_TOKEN:-}}"
PLATFORM_COOKIE="${SMOKE_PLATFORM_COOKIE:-${SMOKE_ADMIN_COOKIE:-}}"
SCHOOL_TOKEN="${SMOKE_SCHOOL_TOKEN:-}"
SCHOOL_COOKIE="${SMOKE_SCHOOL_COOKIE:-}"

EXPECTED_SHA="${SMOKE_EXPECTED_SHA:-}"
DEPLOYED_SHA="${SMOKE_DEPLOYED_SHA:-}"
BASELINE_REV="${SMOKE_DB_BASE:-e5f6a7b8c9d0}"
EXPECTED_DB_HEAD="${SMOKE_EXPECT_DB_HEAD:-d4e5f6a7b8c9}"
EXPECTED_CHAIN_LEN="${SMOKE_EXPECT_CHAIN_LEN:-6}"
APP_DB_USER="${SMOKE_APP_DB_USER:-esa_app}"
SSH_TARGET="${SMOKE_SSH_TARGET:-}"
DEPLOY_PATH="${SMOKE_DEPLOY_PATH:-/srv/english-speaking-assessment}"
EXPECT_VOCAB_STATUS="${SMOKE_EXPECT_VOCAB_STATUS:-403}"
EXPECT_VOCAB_MODULE="${SMOKE_EXPECT_VOCAB_MODULE:-off}"
LOG_SINCE="${SMOKE_LOG_SINCE:-30m}"
BACKUP_FILE="${SMOKE_BACKUP_FILE:-}"
AUDIO_URL="${SMOKE_AUDIO_URL:-}"
GH_BIN="${SMOKE_GH_BIN:-}"
if [[ -z "$GH_BIN" ]]; then
  GH_BIN="$(command -v gh 2>/dev/null || true)"
  [[ -z "$GH_BIN" && -x /opt/homebrew/bin/gh ]] && GH_BIN=/opt/homebrew/bin/gh
fi

PASS_N=0
FAIL_N=0
MANUAL_N=0
SKIP_N=0
FAIL_LINES=()

pass()  { PASS_N=$((PASS_N + 1));   printf 'PASS   %s\n' "$*"; }
fail()  { FAIL_N=$((FAIL_N + 1));   FAIL_LINES+=("$*"); printf 'FAIL   %s\n' "$*"; }
manual(){ MANUAL_N=$((MANUAL_N + 1)); printf 'MANUAL %s\n' "$*"; }
skip()  { SKIP_N=$((SKIP_N + 1));   printf 'SKIP   %s\n' "$*"; }
section(){ printf '\n== %s ==\n' "$*"; }

have_platform_auth() { [[ -n "$PLATFORM_TOKEN" || -n "$PLATFORM_COOKIE" ]]; }
have_school_auth()   { [[ -n "$SCHOOL_TOKEN" || -n "$SCHOOL_COOKIE" ]]; }
have_server()        { [[ -n "$SSH_TARGET" && -n "$DEPLOY_PATH" ]]; }

ssh_run() {
  ssh -o BatchMode=yes -o ConnectTimeout=8 \
    "$SSH_TARGET" "$@" 2>/dev/null
}

# 只读 GET。结果放 HTTP_CODE / HTTP_BODY，不打印请求头。
http_get() {
  local url="$1" who="${2:-none}" extra="${3:-}"
  local -a args=(-sS -m 15 -w $'\n%{http_code}')
  case "$who" in
    platform)
      if [[ -n "$PLATFORM_TOKEN" ]]; then args+=(-H "Authorization: Bearer $PLATFORM_TOKEN")
      elif [[ -n "$PLATFORM_COOKIE" ]]; then args+=(-H "Cookie: $PLATFORM_COOKIE")
      else return 2; fi ;;
    school)
      if [[ -n "$SCHOOL_TOKEN" ]]; then args+=(-H "Authorization: Bearer $SCHOOL_TOKEN")
      elif [[ -n "$SCHOOL_COOKIE" ]]; then args+=(-H "Cookie: $SCHOOL_COOKIE")
      else return 2; fi ;;
  esac
  [[ -n "$extra" ]] && args+=(-H "$extra")
  local resp
  if ! resp=$(curl "${args[@]}" "$url" 2>/dev/null); then
    HTTP_CODE="000"; HTTP_BODY=""
    return 1
  fi
  HTTP_CODE="${resp##*$'\n'}"
  HTTP_BODY="${resp%$'\n'*}"
  return 0
}

# 通过 SSH + docker compose 执行只读 SQL，SQL 走 stdin，避免嵌套引号。
# 用户名/库名在 db 容器内展开（POSTGRES_USER/POSTGRES_DB 是容器环境变量）；
# 不能在远端宿主 shell 展开——那里变量留空会落到默认角色 root，psql 直接报
# role "root" 不存在。
db_sql() {
  local sql="$1"
  printf '%s\n' "$sql" | ssh -o BatchMode=yes -o ConnectTimeout=8 \
    "$SSH_TARGET" \
    "cd '$DEPLOY_PATH' && docker compose exec -T db sh -c 'psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -X -tA -q -v ON_ERROR_STOP=1'" 2>&1
}

check_target_sha_ci() {
  local target head
  target="${EXPECTED_SHA:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"
  head="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  if [[ "$head" == "$target" ]]; then
    pass "P02 target SHA = ${target:0:12}"
  else
    fail "P02 target SHA 不符：HEAD=${head:0:12} expected=${target:0:12}"
  fi
  if [[ "$EXECUTE" -eq 0 ]]; then skip "P02 CI 成功记录（dry-run 不发 gh 请求）"; return; fi
  if [[ -z "$GH_BIN" ]]; then manual "P02 CI 成功记录：未找到 gh，人工核对 Actions"; return; fi
  local run_id
  run_id="$("$GH_BIN" run list --workflow CI --commit "$target" --status success --limit 1 --json databaseId --jq '.[0].databaseId // empty' 2>/dev/null || true)"
  if [[ -n "$run_id" ]]; then pass "P02 CI success run $run_id"; else fail "P02 该 SHA 没有成功的 CI run"; fi
}

check_worktree() {
  local dirty
  dirty="$(git -C "$ROOT_DIR" status --porcelain --untracked-files=no)"
  if [[ -z "$dirty" ]]; then pass "P03 已跟踪文件无未提交改动"; else fail "P03 工作树有未提交的已跟踪改动"; fi
}

check_prestart_order() {
  local file="$ROOT_DIR/backend/scripts/prestart.sh"
  if [[ ! -f "$file" ]]; then fail "P10 找不到 prestart.sh"; return; fi
  if ! grep -q 'alembic upgrade head' "$file" || ! grep -q 'ensure_db_roles.py' "$file"; then
    fail "P10 prestart 未包含 alembic + ensure_db_roles"; return
  fi
  local a b
  a="$(grep -n 'alembic upgrade head' "$file" | head -1 | cut -d: -f1)"
  b="$(grep -n 'ensure_db_roles.py' "$file" | head -1 | cut -d: -f1)"
  if [[ -n "$a" && -n "$b" && "$a" -lt "$b" ]]; then
    pass "P10 prestart 顺序：alembic($a) → ensure_db_roles($b)"
  else
    fail "P10 prestart 顺序错误：alembic=$a ensure_db_roles=$b"
  fi
}

check_migration_chain() {
  local out
  out="$(python3 - "$ROOT_DIR" "$BASELINE_REV" <<'PY'
import glob, os, re, sys
root, base = sys.argv[1], sys.argv[2]
revs = {}
for f in glob.glob(os.path.join(root, "backend/app/alembic/versions/*.py")):
    s = open(f, encoding="utf-8").read()
    m = re.search(r"^revision\s*(?::\s*str)?\s*=\s*['\"]([^'\"]+)", s, re.M)
    d = re.search(r"^down_revision\s*(?::[^=]+)?\s*=\s*(?:['\"]([^'\"]+)['\"]|\(([^)]*)\))", s, re.M)
    if not m:
        continue
    down = d.group(1) if d and d.group(1) else None
    revs[m.group(1)] = down
heads = [r for r in revs if r not in {v for v in revs.values() if v}]
nexts = {v: r for r, v in revs.items() if v}
chain = []
cur = base
while cur in nexts:
    cur = nexts[cur]
    chain.append(cur)
print(len(chain))
print(chain[-1] if chain else "")
print(" -> ".join(chain))
PY
)"
  local n head chain
  n="$(printf '%s\n' "$out" | sed -n '1p')"
  head="$(printf '%s\n' "$out" | sed -n '2p')"
  chain="$(printf '%s\n' "$out" | sed -n '3p')"
  if [[ "$n" == "$EXPECTED_CHAIN_LEN" && "$head" == "$EXPECTED_DB_HEAD" ]]; then
    pass "P07 迁移链 $n 支，head $head"
    printf '       %s\n' "$chain"
  else
    fail "P07 迁移链不符：n=$n head=${head}（期望 n=$EXPECTED_CHAIN_LEN head=${EXPECTED_DB_HEAD}）"
  fi
}

check_workflow_steps() {
  local f="$ROOT_DIR/.github/workflows/deploy-prod.yml"
  if [[ ! -f "$f" ]]; then fail "P11 找不到 deploy-prod.yml"; return; fi
  local ok=1
  grep -q 'predeploy.sql' "$f" || ok=0
  grep -q 'rollback' "$f" || ok=0
  grep -q 'prestart' "$f" || ok=0
  if [[ "$ok" -eq 1 ]]; then
    pass "P11 deploy-prod 含 predeploy 快照、:rollback 标签与 prestart 失败日志"
  else
    fail "P11 deploy-prod 缺少快照/rollback/prestart 关键步骤"
  fi
}

check_backup() {
  local f=""
  if [[ -n "$BACKUP_FILE" ]]; then
    f="$BACKUP_FILE"
  elif have_server && [[ "$EXECUTE" -eq 1 ]]; then
    f="$(ssh_run "cd '$DEPLOY_PATH' && ls -1t backups/app-*-predeploy.sql.gz 2>/dev/null | head -1" || true)"
    if [[ -z "$f" ]]; then
      local bundle
      bundle="$(ssh_run "cd '$DEPLOY_PATH' && ls -1td backups/bundle-* 2>/dev/null | head -1" || true)"
      [[ -n "$bundle" ]] && f="$bundle/database.sql.gz"
    fi
  fi
  if [[ -z "$f" ]]; then
    manual "P04/P05 备份文件：设置 SMOKE_BACKUP_FILE 或 SMOKE_SSH_TARGET 后自动检查"
    return
  fi
  if [[ ! -f "$f" && ! have_server ]]; then fail "P04 备份文件不存在：$f"; return; fi
  if [[ -f "$f" ]]; then
    if gzip -t "$f" 2>/dev/null; then pass "P04/P05 备份存在且 gzip -t 通过：$(basename "$f")"; else fail "P05 gzip -t 失败：$f"; fi
  else
    if ssh_run "cd '$DEPLOY_PATH' && gzip -t '$f'" >/dev/null; then pass "P04/P05 服务器备份存在且 gzip -t 通过：$(basename "$f")"; else fail "P05 服务器 gzip -t 失败：$f"; fi
  fi
  manual "P06 完整 bundle 的 verify-backup / 恢复演练：按命令人工执行"
}

check_rollback_images() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "P06 :rollback 镜像（dry-run）"; return; fi
  if have_server; then
    if ssh_run "docker image inspect esa-backend:rollback esa-frontend:rollback >/dev/null 2>&1"; then
      pass "P06 :rollback 镜像存在（backend/frontend）"
    else
      fail "P06 缺少 :rollback 镜像"
    fi
    return
  fi
  if command -v docker >/dev/null 2>&1 && docker image inspect esa-backend:rollback esa-frontend:rollback >/dev/null 2>&1; then
    pass "P06 本机 :rollback 镜像存在（仅本机参考，非生产证明）"
  else
    manual "P06 :rollback 镜像：设置 SMOKE_SSH_TARGET 或在服务器人工 docker image inspect"
  fi
}

check_tenant_modules() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "P09 tenant_module 现状（dry-run）"; return; fi
  if have_server; then
    local out
    out="$(db_sql "SELECT (SELECT count(*) FROM tenant), (SELECT count(*) FROM tenant_module WHERE module_key='speaking' AND enabled), (SELECT count(*) FROM tenant_module WHERE module_key='vocabulary' AND enabled);" || true)"
    if [[ "$out" =~ ^([0-9]+)\|([0-9]+)\|([0-9]+)$ ]]; then
      local tenants sp voc
      tenants="${BASH_REMATCH[1]}"; sp="${BASH_REMATCH[2]}"; voc="${BASH_REMATCH[3]}"
      if [[ "$EXPECT_VOCAB_MODULE" == "on" ]]; then
        if [[ "$sp" == "$tenants" && "$voc" == "$tenants" ]]; then
          pass "P09 tenant_module：$tenants 校，speaking on=$sp / vocabulary on=${voc}（期望 on）"
        else
          fail "P09 tenant_module：$tenants 校，speaking on=$sp / vocabulary on=${voc}（期望全 on）"
        fi
      else
        if [[ "$sp" == "$tenants" && "$voc" == "0" ]]; then
          pass "P09 tenant_module：$tenants 校，speaking on=$sp / vocabulary on=0"
        else
          fail "P09 tenant_module：$tenants 校，speaking on=$sp / vocabulary on=${voc}（期望 speaking 全 on、vocabulary 全 off）"
        fi
      fi
      return
    fi
    manual "P09 tenant_module SQL 无法判定（需 POSTGRES_USER owner 或手工核对）"
    return
  fi
  if have_school_auth; then
    if ! http_get "$API_BASE/modules/me" school; then manual "P09 /modules/me 请求失败"; return; fi
    if [[ "$HTTP_CODE" != "200" ]]; then fail "P09 /modules/me HTTP $HTTP_CODE"; return; fi
    local mods
    mods="$(python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin).get("modules",[])))' <<<"$HTTP_BODY" 2>/dev/null || true)"
    case " $mods " in
      *" speaking "*) : ;;
      *) fail "P09 当前学校 speaking 未启用（modules=${mods}）"; return ;;
    esac
    if [[ "$EXPECT_VOCAB_MODULE" == "on" ]]; then
      case " $mods " in *" vocabulary "*) pass "P09 当前学校 modules=${mods}（含 vocabulary，符合本地/开通预期）" ;; *) fail "P09 期望 vocabulary on，实际 modules=$mods" ;; esac
    else
      case " $mods " in *" vocabulary "*) fail "P09 期望 vocabulary off，实际 modules=$mods" ;; *) pass "P09 当前学校 modules=${mods}（vocabulary off）" ;; esac
    fi
  else
    manual "P09 tenant_module：设置 SMOKE_SCHOOL_TOKEN 或 SMOKE_SSH_TARGET"
  fi
}

check_speaking_login() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "S09 口语登录（dry-run）"; return; fi
  if ! have_school_auth; then manual "S09 口语登录：设置 SMOKE_SCHOOL_TOKEN / SMOKE_SCHOOL_COOKIE"; return; fi
  if ! http_get "$API_BASE/modules/me" school; then manual "S09 /modules/me 请求失败"; return; fi
  if [[ "$HTTP_CODE" != "200" ]]; then fail "S09 口语登录 /modules/me HTTP $HTTP_CODE"; return; fi
  local mods
  mods="$(python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin).get("modules",[])))' <<<"$HTTP_BODY" 2>/dev/null || true)"
  case " $mods " in
    *" speaking "*) pass "S09 口语登录 200，speaking 已启用" ;;
    *) fail "S09 口语登录 200，但 speaking 未启用（modules=${mods}）" ;;
  esac
}

check_ready_health() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "S01/S02 ready/health（dry-run）"; return; fi
  if [[ -z "$API_BASE" ]]; then fail "S01/S02 缺少 SMOKE_BASE_URL / SMOKE_API_BASE"; return; fi
  if ! http_get "$API_BASE/utils/ready-check/" none; then fail "S01 ready-check 请求失败"; else
    if [[ "$HTTP_CODE" == "200" && "$HTTP_BODY" == *"Ready"* ]]; then pass "S01 ready-check 200"; else fail "S01 ready-check HTTP $HTTP_CODE"; fi
  fi
  if ! http_get "$API_BASE/utils/health-check/" none; then fail "S02 health-check 请求失败"; else
    if [[ "$HTTP_CODE" == "200" && "$HTTP_BODY" == *"true"* ]]; then pass "S02 health-check 200"; else fail "S02 health-check HTTP $HTTP_CODE"; fi
  fi
}

check_version() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "S03 版本 SHA（dry-run）"; return; fi
  local actual=""
  if [[ -n "$DEPLOYED_SHA" ]]; then actual="$DEPLOYED_SHA"
  elif have_server; then actual="$(ssh_run "cd '$DEPLOY_PATH' && git rev-parse HEAD" || true)"
  fi
  if [[ -z "$actual" ]]; then manual "S03 版本 SHA：设置 SMOKE_DEPLOYED_SHA 或 SMOKE_SSH_TARGET"; return; fi
  if [[ -z "$EXPECTED_SHA" ]]; then manual "S03 已取到 ${actual:0:12}，但未设 SMOKE_EXPECTED_SHA"; return; fi
  if [[ "$actual" == "$EXPECTED_SHA" ]]; then pass "S03 部署 SHA = ${actual:0:12}"; else fail "S03 部署 SHA 不符：$actual != $EXPECTED_SHA"; fi
}

check_alembic_current() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "S04 alembic current（dry-run）"; return; fi
  if ! have_server; then manual "S04 alembic current：设置 SMOKE_SSH_TARGET"; return; fi
  local out
  out="$(ssh_run "cd '$DEPLOY_PATH' && docker compose exec -T backend alembic current 2>/dev/null | tail -1" || true)"
  if [[ "$out" == *"$EXPECTED_DB_HEAD"* ]]; then pass "S04 alembic current = $EXPECTED_DB_HEAD"; else fail "S04 alembic current 不是 ${EXPECTED_DB_HEAD}（实际：${out:-空}）"; fi
}

check_tables() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "S05 4 张新表（dry-run）"; return; fi
  if ! have_server; then manual "S05/S06 表与 DML：设置 SMOKE_SSH_TARGET"; return; fi
  local out
  out="$(db_sql "SELECT table_name, has_table_privilege('$APP_DB_USER', table_name, 'SELECT,INSERT,UPDATE,DELETE') FROM (VALUES ('vocabulary_leaderboard_setting'),('vocabulary_leaderboard_participant'),('vocabulary_license_audit'),('vocabulary_book_version')) AS t(table_name);" || true)"
  local rows
  rows="$(printf '%s\n' "$out" | grep -c '|' || true)"
  if [[ "$rows" != "4" ]]; then fail "S05 新表检查返回 $rows 行（期望 4）：${out:-空}"; return; fi
  if printf '%s\n' "$out" | grep -q '|f'; then fail "S06 $APP_DB_USER 对新表缺少 DML：$(printf '%s' "$out" | tr '\n' ' ')"; return; fi
  pass "S05/S06 4 张新表存在，$APP_DB_USER 均有 SELECT/INSERT/UPDATE/DELETE"
}

check_noctx_rls() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "S07/S08 RLS（dry-run）"; return; fi
  if ! have_server; then manual "S07 无租户上下文 0 行：设置 SMOKE_SSH_TARGET"; manual "S08 RLS 自检：设置 SMOKE_SSH_TARGET"; return; fi
  local out
  out="$(db_sql "SET ROLE $APP_DB_USER;
SELECT 'vocabulary_leaderboard_setting', count(*) FROM vocabulary_leaderboard_setting;
SELECT 'vocabulary_leaderboard_participant', count(*) FROM vocabulary_leaderboard_participant;
SELECT 'vocabulary_license_audit', count(*) FROM vocabulary_license_audit;
SELECT 'vocabulary_book_version', count(*) FROM vocabulary_book_version;
RESET ROLE;" || true)"
  local bad
  bad="$(printf '%s\n' "$out" | grep -v '|0$' | grep -v '^SET$' | grep -v '^RESET$' | sed '/^$/d' || true)"
  if printf '%s' "$out" | grep -q 'permission denied to set role'; then
    manual "S07 无法 SET ROLE ${APP_DB_USER}；请在服务器用 app 凭据手工验证 4 表 0 行"
  elif [[ -n "$bad" ]]; then
    fail "S07 无租户上下文读非 0 行：$(printf '%s' "$bad" | tr '\n' ' ')"
  else
    pass "S07 4 张新表无租户上下文均读 0 行"
  fi
  if ssh_run "cd '$DEPLOY_PATH' && bash scripts/prod-rls-selfcheck.sh"; then
    pass "S08 prod-rls-selfcheck 通过"
  else
    fail "S08 prod-rls-selfcheck 未通过（查看服务器输出）"
  fi
}

check_admin_http() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "S14-S17 授权台账 HTTP（dry-run）"; return; fi
  if [[ -z "$API_BASE" ]]; then fail "S14-S17 缺少 SMOKE_BASE_URL / SMOKE_API_BASE"; return; fi

  if have_platform_auth; then
    if ! http_get "$API_BASE/login/platform/me" platform; then manual "S14 平台 token 自检请求失败"; else
      case "$HTTP_CODE" in 200) pass "S14 平台运营 token /login/platform/me 200" ;; *) fail "S14 平台 token 自检 HTTP $HTTP_CODE" ;; esac
    fi
    if ! http_get "$API_BASE/admin/vocabulary/license/status?limit=1000" platform; then manual "S15 授权台账请求失败"; else
      if [[ "$HTTP_CODE" == "200" ]]; then
        local n
        n="$(python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d.get("items"),list); print(len(d["items"]))' <<<"$HTTP_BODY" 2>/dev/null || true)"
        if [[ -n "$n" ]]; then pass "S15 license/status 200，items=$n"; else fail "S15 license/status 200 但 JSON 结构不符"; fi
      else
        fail "S15 license/status HTTP $HTTP_CODE"
      fi
    fi
    if ! http_get "$API_BASE/admin/vocabulary/license/export.csv" platform; then manual "S16 CSV 请求失败"; else
      if [[ "$HTTP_CODE" != "200" ]]; then fail "S16 CSV HTTP $HTTP_CODE"; else
        local first
        first="$(printf '%s\n' "$HTTP_BODY" | head -n1 | awk -F, '{print $1}')"
        if printf '%s' "$first" | grep -q '学校'; then pass "S16 CSV 200，首列「学校」"; else fail "S16 CSV 首列不是「学校」：$first"; fi
      fi
    fi
  else
    manual "S14/S15/S16 未设置 SMOKE_PLATFORM_TOKEN / SMOKE_PLATFORM_COOKIE"
  fi

  if have_school_auth; then
    if ! http_get "$API_BASE/admin/vocabulary/license/status" school; then manual "S17 学校 token 拒绝检查请求失败"; else
      case "$HTTP_CODE" in
        401|403) pass "S17 学校 token 被平台端点拒绝（HTTP ${HTTP_CODE}；当前 aud 设计为 401，非 403）" ;;
        200) fail "S17 学校 token 竟可访问平台授权台账" ;;
        *) fail "S17 学校 token 拒绝检查异常 HTTP $HTTP_CODE" ;;
      esac
    fi
    if ! http_get "$API_BASE/vocabulary/books" school; then manual "S13 词汇门禁请求失败"; else
      if [[ "$HTTP_CODE" == "$EXPECT_VOCAB_STATUS" ]]; then
        pass "S13 词汇端点 HTTP ${HTTP_CODE}（符合 SMOKE_EXPECT_VOCAB_STATUS）"
      else
        fail "S13 词汇端点 HTTP ${HTTP_CODE}，期望 $EXPECT_VOCAB_STATUS"
      fi
    fi
    if ! http_get "$API_BASE/classes" school; then manual "S10 课堂列表请求失败"; else
      if [[ "$HTTP_CODE" != "200" ]]; then
        fail "S10 /classes HTTP $HTTP_CODE"
      else
        local n
        n="$(python3 -c 'import json,sys; d=json.load(sys.stdin); assert isinstance(d,list); print(len(d))' <<<"$HTTP_BODY" 2>/dev/null || true)"
        if [[ -z "$n" ]]; then fail "S10 /classes 200 但 JSON 非数组"; elif [[ "$n" == "0" ]]; then manual "S10 当前账号无课堂（0 条），人工确认生产有课堂"; else pass "S10 /classes 200，课堂数 $n"; fi
      fi
    fi
  else
    manual "S13/S17 未设置 SMOKE_SCHOOL_TOKEN / SMOKE_SCHOOL_COOKIE"
  fi

  if [[ -n "$AUDIO_URL" ]]; then
    if ! http_get "$AUDIO_URL" none; then fail "S12 音频回放请求失败"; else
      case "$HTTP_CODE" in 200|206) pass "S12 音频回放 HTTP $HTTP_CODE" ;; *) fail "S12 音频回放 HTTP $HTTP_CODE" ;; esac
    fi
  else
    manual "S12 音频回放：设置 SMOKE_AUDIO_URL 后自动 GET；否则人工播放"
  fi

  if [[ -z "$WEB_URL" ]]; then
    manual "S14 页面 HTML：未设置 SMOKE_WEB_URL"
  elif ! http_get "${WEB_URL%/}/admin/vocabulary-licenses" none; then
    manual "S14 页面 HTML 请求失败"
  else
    if [[ "$HTTP_CODE" == "200" && ( "$HTTP_BODY" == *"<html"* || "$HTTP_BODY" == *"id=\"root\""* ) ]]; then
      pass "S14 /admin/vocabulary-licenses 页面 HTML 200"
      manual "S14 只读视觉确认：页面无编辑/保存/删除入口（人工）"
    else
      fail "S14 授权台账页面 HTTP $HTTP_CODE 或非 HTML"
    fi
  fi
}

check_speaking_pages_manual() {
  manual "S11 口语作答提交/评分：写链路，按只读原则不自动提交；人工用测试账号完成一次作答"
}

check_390_manual() {
  manual "S18 390 宽关键页无横向溢出：用 DevTools/Playwright 打开 390×844，检查登录/学生首页/教师词汇/授权台账 scrollWidth==clientWidth"
}

check_logs() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "S19 日志 permission denied/500（dry-run）"; return; fi
  if ! have_server; then manual "S19 日志：设置 SMOKE_SSH_TARGET 后自动 grep"; return; fi
  local out count
  out="$(ssh_run "cd '$DEPLOY_PATH' && docker compose logs backend --since '$LOG_SINCE' --no-color 2>/dev/null | grep -E 'permission denied|HTTP/1.1\\\" 500|Internal Server Error' | head -10" || true)"
  count="$(printf '%s\n' "$out" | sed '/^$/d' | wc -l | tr -d ' ')"
  if [[ "$count" == "0" ]]; then pass "S19 最近 $LOG_SINCE 后端日志无 permission denied/500"; else fail "S19 最近 $LOG_SINCE 检测到 $count 条 permission denied/500"; fi
}

check_nginx() {
  if [[ "$EXECUTE" -eq 0 ]]; then skip "S20 nginx SSE（dry-run）"; return; fi
  if ! have_server; then manual "S20 nginx -T：设置 SMOKE_SSH_TARGET"; return; fi
  local out
  out="$(ssh_run "cd '$DEPLOY_PATH' && docker compose exec -T frontend nginx -T 2>/dev/null | grep -c 'vocabulary/pk/matches' " || true)"
  local n
  n="$(printf '%s' "$out" | tr -dc '0-9')"
  if [[ -n "$n" && "$n" -ge 1 ]]; then pass "S20 nginx -T 含 PK SSE location（匹配 $n 处）"; else fail "S20 nginx -T 未找到 PK SSE location"; fi
}

check_manual_ops() {
  manual "P01 部署审批：确认时间窗、当前无并发部署、用户已确认上线"
  manual "P08 生产 DB 基线：确认 alembic_version 当前为 ${BASELINE_REV}（部署前只读）"
  manual "P12 备份恢复演练：第 1 项尚未执行；按 docs/go-live-smoke-checklist.md 单独安排"
}

if [[ "$MODE" == "pre" || "$MODE" == "both" ]]; then
  section "部署前（pre）"
  check_target_sha_ci
  check_worktree
  check_prestart_order
  check_migration_chain
  check_workflow_steps
  check_backup
  check_rollback_images
  check_tenant_modules
  check_manual_ops
fi

if [[ "$MODE" == "post" || "$MODE" == "both" ]]; then
  section "部署后（post）"
  check_ready_health
  check_version
  check_alembic_current
  check_tables
  check_noctx_rls
  check_speaking_login
  check_admin_http
  check_speaking_pages_manual
  check_390_manual
  check_logs
  check_nginx
fi

printf '\n== 汇总 ==\n'
printf 'PASS=%d FAIL=%d MANUAL=%d SKIP=%d\n' "$PASS_N" "$FAIL_N" "$MANUAL_N" "$SKIP_N"
if [[ "$FAIL_N" -gt 0 ]]; then
  printf '失败项：\n'
  printf '  - %s\n' "${FAIL_LINES[@]}"
  exit 1
fi
exit 0
