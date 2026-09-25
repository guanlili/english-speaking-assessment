#!/usr/bin/env bash
# 从运行中的 backend 容器导出最新 OpenAPI 规范，再重新生成前端客户端。
# 用法：cd frontend && npm run generate-client

set -e
cd "$(dirname "$0")/.."

if ! docker compose ps --status running backend | grep -q backend; then
  echo "❌ backend 容器未运行，请先执行 docker compose up -d" >&2
  exit 1
fi

echo "=== 1/2 从 backend 导出 openapi.json ==="
docker compose exec -T backend python -c \
  "import json, app.main; print(json.dumps(app.main.app.openapi()))" > openapi.json

echo "=== 2/2 生成客户端代码 ==="
npx openapi-ts

echo "✅ 完成，检查 src/client/ 的变更"
