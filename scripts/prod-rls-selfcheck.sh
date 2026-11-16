#!/usr/bin/env bash
# RLS 运行时自检：确认「受限角色真的在限、且真的在管」。
#
# 用途：部署后在生产主机跑一次，把结果打进 CI 日志——这样生产隔离状态是
# 可验证的，不依赖谁去登录主机手工查。
#
# 判据（任一不满足即退出码 1，让部署流程红灯）：
#   1. APP 角色存在且 rolsuper=0 / rolbypassrls=0
#   2. PLATFORM 角色存在且 rolbypassrls=1
#   3. 至少一张业务表处于 FORCE RLS（策略对表 owner 也生效）
#   4. 受限角色在**缺租户上下文**时读业务表返回 0 行
#   5. 业务连接不是以 owner（BYPASSRLS）身份跑的
# 仅打印不判失败的信息：上下文内可见行数、当前连接身份分布。
#
# 用法：bash scripts/prod-rls-selfcheck.sh [--env .env]
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=".env"
if [ "${1:-}" = "--env" ] && [ -n "${2:-}" ]; then
  ENV_FILE="$2"
fi
if [ ! -f "${ENV_FILE}" ]; then
  echo "❌ 找不到 ${ENV_FILE}"
  exit 1
fi

# .env 两种形态都要吃：部署流水线生成的是 KEY="value"，本地手写的是 KEY=value
get() {
  sed -n "s/^$1=\"\\(.*\\)\"$/\\1/p;s/^$1=\\(.*\\)$/\\1/p" "${ENV_FILE}" | head -1
}

COMPOSE="docker compose -f compose.yml"
OWNER_USER="$(get POSTGRES_USER)"
DB_NAME="$(get POSTGRES_DB)"
APP_USER="$(get APP_POSTGRES_USER)"
APP_PW="$(get APP_POSTGRES_PASSWORD)"
PLATFORM_USER="$(get PLATFORM_POSTGRES_USER)"
PLATFORM_PW="$(get PLATFORM_POSTGRES_PASSWORD)"

fail=0
ok()   { echo "  ✔ $1"; }
bad()  { echo "  ✖ $1"; fail=1; }
info() { echo "  · $1"; }

owner_sql() {
  ${COMPOSE} exec -T db psql -U "${OWNER_USER}" -d "${DB_NAME}" -X -tA -c "$1"
}

app_sql() {
  ${COMPOSE} exec -T -e PGPASSWORD="${APP_PW}" db \
    psql -h 127.0.0.1 -U "${APP_USER}" -d "${DB_NAME}" -X -tA -c "$1" 2>&1
}

echo "== RLS 运行时自检（${ENV_FILE}）=="

if [ -z "${APP_USER}" ] || [ -z "${APP_PW}" ]; then
  echo "  ⚠ APP_POSTGRES_USER/PASSWORD 未配置：受限角色未启用，业务连接回落 owner"
  echo "    → 此时 RLS 对应用不生效（仅 FORCE 策略对 owner 仍生效，但 owner 可关闭）"
  exit 1
fi

echo "[1] 角色属性"
row="$(owner_sql "select rolsuper::int||'|'||rolbypassrls::int from pg_roles where rolname='${APP_USER}'" || true)"
if [ -z "${row}" ]; then
  bad "APP 角色 ${APP_USER} 不存在"
else
  case "${row}" in
    0\|0) ok "${APP_USER}：NOSUPERUSER + NOBYPASSRLS" ;;
    *)    bad "${APP_USER} 属性不对（super|bypassrls = ${row}）" ;;
  esac
fi
if [ -n "${PLATFORM_USER}" ]; then
  prow="$(owner_sql "select rolbypassrls::int from pg_roles where rolname='${PLATFORM_USER}'" || true)"
  case "${prow}" in
    1) ok "${PLATFORM_USER}：BYPASSRLS（平台通道）" ;;
    "") bad "PLATFORM 角色 ${PLATFORM_USER} 不存在" ;;
    *)  bad "${PLATFORM_USER} 应带 BYPASSRLS，实际 rolbypassrls=${prow}" ;;
  esac
fi

echo "[2] FORCE RLS 覆盖"
n_force="$(owner_sql "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r' and c.relforcerowsecurity" || echo 0)"
if [ "${n_force:-0}" -gt 0 ]; then
  ok "${n_force} 张表 FORCE RLS（策略对表 owner 同样生效）"
else
  bad "没有任何表处于 FORCE RLS"
fi

echo "[3] 受限角色：缺上下文 / 有上下文"
noctx="$(app_sql "select count(*) from classroom" || true)"
case "${noctx}" in
  0) ok "缺租户上下文读 classroom = 0 行（策略生效）" ;;
  "") bad "受限角色连不上或查询失败（检查密码与 GRANT）" ;;
  *)  bad "缺上下文仍读到 ${noctx} 行——策略未生效" ;;
esac
ctx="$(app_sql "select set_config('app.tenant_id','00000000-0000-0000-0000-000000000001',false); select count(*) from classroom" || true)"
info "默认校上下文内可见 classroom 行数：$(printf '%s' "${ctx}" | tail -1)"

echo "[4] 业务连接身份"
conns="$(owner_sql "select usename, count(*) from pg_stat_activity where datname=current_database() and pid <> pg_backend_pid() group by 1" | tr '\n' ' ')"
info "当前连接：${conns}"
if printf '%s' "${conns}" | grep -q " ${OWNER_USER} "; then
  bad "存在以 owner（${OWNER_USER}，BYPASSRLS）身份的业务连接：应用可能未切换到受限角色"
else
  ok "无 owner 身份的业务连接"
fi

echo
if [ "${fail}" -ne 0 ]; then
  echo "❌ 自检未通过"
  exit 1
fi
echo "✅ RLS 自检通过"
