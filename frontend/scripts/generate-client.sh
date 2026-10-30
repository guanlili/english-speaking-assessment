#!/usr/bin/env bash
# 从运行中的 backend 容器导出最新 OpenAPI 规范，再重新生成前端客户端。
# 用法：cd frontend && npm run generate-client
# 独立 worktree：npm run generate-client -- --local（先 uv sync）

set -e
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--local" ]]; then
  # 独立 worktree 可从本地源码导出，避免读取另一 checkout 的容器接口。
  (cd ../backend && uv run --no-sync python -c \
    "import json, app.main; print(json.dumps(app.main.app.openapi()))") > openapi.json
elif ! docker compose ps --status running backend | grep -q backend; then
  echo "❌ backend 容器未运行，请先执行 docker compose up -d" >&2
  exit 1
else
  echo "=== 1/2 从 backend 导出 openapi.json ==="
  docker compose exec -T backend python -c \
    "import json, app.main; print(json.dumps(app.main.app.openapi()))" > openapi.json
fi

echo "=== 2/3 生成客户端代码 ==="
npx openapi-ts

echo "=== 3/3 0.99 迁移补丁（ThrowOnError 默认值与运行时导出）==="
# SDK 方法泛型默认 ThrowOnError=false（0.99 已无插件级全局开关），后处理为
# true 以保持「await 直接拿数据、错误抛 ApiError」的既有调用形态；运行时
# 默认由 main.tsx 的 client.setConfig({ throwOnError: true }) 同步兜底
perl -pi -e 's/<ThrowOnError extends boolean = false>/<ThrowOnError extends boolean = true>/g' src/client/sdk.gen.ts
# FastAPI 给所有带请求体的端点声明 422，[keyof Responses] 会把校验错误类型
# 并进返回值联合——throwOnError 下错误只抛不返回，收窄到 200 载荷（旧语义）
perl -pi -e 's/\[keyof (\w+Responses)\]/[200 & keyof \1]/g' src/client/types.gen.ts
# barrel 追加运行时导出（幂等）：client 实例与 ApiError 兼容类
# （内联 client-fetch 抛裸响应体，由 main.tsx 错误拦截器包装成 ApiError）
grep -q "api-compat-exports" src/client/index.ts || printf '\n// api-compat-exports（0.99 迁移补丁，由本脚本追加）\nexport { client } from "./client.gen";\nexport { ApiError } from "../lib/api-error";\n' >> src/client/index.ts

echo "✅ 完成，检查 src/client/ 的变更"
