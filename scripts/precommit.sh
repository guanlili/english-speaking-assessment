#!/usr/bin/env bash
# .pre-commit-config.yaml 的本地 hook 入口。
#
# 只跑「秒级」的静态检查（格式 + lint），与 CI 同口径：
#   - backend：backend/scripts/lint.sh（ruff + ty，约 0.3s）
#   - frontend：biome check（约 0.9s）
# 测试与覆盖率不在此处跑（backend/scripts/test.sh 约 2 分钟），提交前
# 需要完整闸门时用 backend/scripts/verify.sh。
#
# 用法：bash scripts/precommit.sh backend|frontend

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-}"

case "$TARGET" in
backend)
	cd "$ROOT/backend"
	if [ -x .venv/bin/ruff ]; then
		export PATH="$PWD/.venv/bin:$PATH"
	elif ! command -v ruff >/dev/null 2>&1; then
		echo "❌ 找不到 ruff：先 cd backend && uv sync" >&2
		exit 1
	fi
	bash scripts/lint.sh
	;;
frontend)
	cd "$ROOT/frontend"
	if [ ! -d node_modules ]; then
		echo "❌ 缺少 node_modules：先 cd frontend && npm ci" >&2
		exit 1
	fi
	npx biome check --no-errors-on-unmatched --files-ignore-unknown=true ./
	;;
*)
	echo "用法：bash scripts/precommit.sh backend|frontend" >&2
	exit 2
	;;
esac
