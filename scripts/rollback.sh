#!/usr/bin/env bash
# 生产紧急回滚：把部署时保留的 :rollback 镜像切回运行（秒级，不重新构建）。
#
# 用法（服务器部署目录下）：bash scripts/rollback.sh
#
# 边界（动手前必读）：
# 1. 只回滚代码镜像，不回滚数据库。若待回退的版本区间里有 Alembic 迁移，
#    旧代码可能跑不动新 schema（典型症状：接口报缺列/unknown column）。
#    需要数据一并回退时，用 backups/ 里对应时点的 app-*-predeploy.sql.gz
#    快照单独恢复，别带着新 schema 硬跑旧代码。
# 2. 回滚只是争取处置时间：修复合入 master 后，下一次部署会重新前进，
#    rollback 标签随之更新，不影响后续部署。
set -euo pipefail
cd "$(dirname "$0")/.."

for img in esa-backend esa-frontend; do
  if ! docker image inspect "$img:rollback" >/dev/null 2>&1; then
    echo "❌ $img:rollback 不存在（从未部署过带 rollback 机制的版本，无旧镜像可回退）"
    exit 1
  fi
done

for img in esa-backend esa-frontend; do
  docker tag "$img:rollback" "$img:latest"
done

# --no-deps 只重建这两个容器：跳过 prestart（数据库已在新 schema 上，
# 旧迁移链对它执行 upgrade 可能因找不到 revision 直接失败），db/acme 不动。
docker compose -f compose.yml up -d --no-build --no-deps backend frontend

app_port=$(sed -n 's/^APP_PORT="\([0-9]*\)"$/\1/p' .env)
for i in $(seq 1 30); do
  if curl --connect-timeout 2 --max-time 5 -fsS \
      "http://localhost:${app_port:-80}/api/v1/utils/ready-check/" >/dev/null 2>&1; then
    echo "✅ 回滚完成并通过就绪检查（记得排查根因后重新走 CI 部署前进）"
    exit 0
  fi
  sleep 2
done

echo "❌ 回滚后就绪检查未通过。若日志是 schema 不兼容（见脚本头部边界 1），"
echo "   需恢复对应 predeploy 快照后重试。日志："
docker compose -f compose.yml logs backend --tail 50
exit 1
