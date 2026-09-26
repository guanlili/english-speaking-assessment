#!/usr/bin/env bash
# 演示前一键重置：清学生/作答/音频，保留内容（篇目/情景/词表）与课堂码 DEMO01。
# 用法：bash scripts/reset-demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose exec -T db psql -U postgres -d app -c \
  "DELETE FROM attempt; DELETE FROM practice_session; DELETE FROM student;"
docker compose exec -T backend sh -c "rm -f /app/audio/*"

echo "✅ 演示数据已重置（学生、作答、音频已清空；DEMO01 课堂码与内容保留）"
echo "   学生入口: http://localhost:5173/j/DEMO01"
echo "   老师面板: http://localhost:5173/t/DEMO01"
echo "   单页演示: http://localhost:5173/practice"
