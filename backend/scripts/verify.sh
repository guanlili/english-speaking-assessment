#!/usr/bin/env bash
# 一条命令跑完本仓所有本地可验证的闸门。人和 AI 用同一个入口。
#
#   bash scripts/verify.sh                     # 全量：lint → 全量测试 → 覆盖率门禁
#   bash scripts/verify.sh -k question_bank    # 只跑匹配用例（改完单个模块时）
#   bash scripts/verify.sh --openapi           # 额外做 openapi 零漂移校验
#   bash scripts/verify.sh --openapi-update    # 确认路由变更有意后更新基线
#
# 退出码 0 表示全绿。任何一步失败立刻停，并打印「哪一步、为什么」——
# AI 拿到失败就照着改，不用再去翻 CI 日志（一轮往返 10 分钟）。
set -euo pipefail

cd "$(dirname "$0")/.."

OPENAPI=0
OPENAPI_UPDATE=0
PYTEST_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --openapi) OPENAPI=1; shift ;;
    --openapi-update) OPENAPI=1; OPENAPI_UPDATE=1; shift ;;
    *) PYTEST_ARGS+=("$1"); shift ;;
  esac
done

step() { printf '\n\033[1m── %s ──\033[0m\n' "$1"; }
fail() { printf '\033[31m❌ %s\033[0m\n' "$1"; exit 1; }

# CI 里 POSTGRES_SERVER 由 workflow 注入（localhost:5432）。本地开发不设，
# 靠 docker compose 映射的 5433。这里自动探测，省掉「为什么全绿变全红」的排查。
if [ -z "${POSTGRES_SERVER:-}" ]; then
  if nc -z localhost 5433 2>/dev/null; then
    export POSTGRES_SERVER=localhost POSTGRES_PORT=5433
  else
    fail "本地数据库未就绪（5433 不通）。先执行：open -a Docker && docker compose up -d db，再重跑；或显式 export POSTGRES_SERVER/POSTGRES_PORT"
  fi
fi

step "1/4 格式"
ruff format app tests --check || fail "格式不符：先跑 bash scripts/format.sh"

step "2/4 Lint（ruff + ty）"
bash scripts/lint.sh || fail "Lint 未过，按上面的报错改"

step "3/4 测试 + 覆盖率门禁"
if [ ${#PYTEST_ARGS[@]} -gt 0 ]; then
  # 定向跑：不走覆盖率门禁（子集必然低于阈值），只验证这批用例本身
  pytest "${PYTEST_ARGS[@]}" -q
else
  bash scripts/test.sh
fi

if [ "$OPENAPI" = "1" ]; then
  step "4/4 openapi 契约"
  if [ "$OPENAPI_UPDATE" = "1" ]; then
    python scripts/openapi_diff.py --update
  else
    python scripts/openapi_diff.py || fail "openapi 与基线不一致，见上面的差异清单"
  fi
else
  step "4/4 openapi 契约（跳过，加 --openapi 开启）"
fi

printf '\n\033[32m✅ 全部闸门通过\033[0m\n'
