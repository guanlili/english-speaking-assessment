#!/usr/bin/env bash
# 把生产数据同步到新机器（割接专用；平时不跑）。
#
# 用法（在 Mac Mini / 有两条 SSH 通道的机器上执行）：
#   PROD_SSH=esa-prod NEW_SSH=volc-belp bash scripts/cutover-sync.sh --final
#
# 前置：--final 要求生产 backend 已停写（割接手册 2.1）。未停写时脚本拒绝执行，
# 除非显式加 --force（那会得到一份可能不一致的数据库 + 音频快照）。
#
# 做四件事：
#   1) pg_dump --clean --if-exists 流式恢复（新机先停 backend，避免对象被占用）
#   2) 音频目录增量同步（tar 流式，跨云约 1MB/s）
#   3) 对账：用户/学生/答题/词表/练习会话行数 + 音频文件数
#   4) 迁移版本比对 + RLS 自检
set -euo pipefail

PROD_SSH="${PROD_SSH:-esa-prod}"
NEW_SSH="${NEW_SSH:-volc-belp}"
PROD_PROJECT="${PROD_PROJECT:-/opt/speakup}"
NEW_PROJECT="${NEW_PROJECT:-/srv/english-speaking-assessment}"
PROD_DB="${PROD_DB:-speakup-db-1}"
NEW_DB="${NEW_DB:-esa-db-1}"
PROD_APP="${PROD_APP:-speakup-backend-1}"
NEW_APP="${NEW_APP:-esa-backend-1}"
NEW_HOST="${NEW_HOST:-115.190.122.24}"
FINAL=0
FORCE=0
for a in "$@"; do
  case "$a" in
    --final) FINAL=1 ;;
    --force) FORCE=1 ;;
    *) echo "未知参数: $a" >&2; exit 2 ;;
  esac
done

say() { printf '\n=== %s ===\n' "$*"; }
die() { echo "❌ $*" >&2; exit 1; }
counts() { # $1=ssh 目标 $2=容器
  ssh "$1" "docker exec $2 psql -U postgres -d app -tA \
    -c 'select count(*) from \"user\"' \
    -c 'select count(*) from student' \
    -c 'select count(*) from attempt' \
    -c 'select count(*) from vocab_level_entry' \
    -c 'select count(*) from practice_session' | tr '\n' '/'"
}

say "0/4 前置检查"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$PROD_SSH" 'true' || die "连不上生产机 $PROD_SSH"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$NEW_SSH" 'true' || die "连不上新机 $NEW_SSH"
prod_running=$(ssh "$PROD_SSH" "docker inspect -f '{{.State.Running}}' $PROD_APP 2>/dev/null || echo false")
if [ "$prod_running" = "true" ]; then
  if [ "$FINAL" = "1" ] && [ "$FORCE" != "1" ]; then
    die "生产 backend 仍在运行：先执行 docker compose stop backend（割接手册 2.1），或加 --force 接受不一致快照"
  fi
  echo "⚠️  生产 backend 仍在运行（--force）：快照可能不一致"
else
  echo "生产 backend 已停写 ✓"
fi
echo "生产提交: $(ssh "$PROD_SSH" "cd $PROD_PROJECT && git rev-parse --short HEAD")"
echo "新机提交: $(ssh "$NEW_SSH" "su - deploy -c 'cd $NEW_PROJECT && git rev-parse --short HEAD'")"

say "1/4 数据库：dump 流式恢复（先停新机 backend）"
ssh "$NEW_SSH" "cd $NEW_PROJECT && docker compose -f compose.yml stop backend >/dev/null 2>&1 || true"
ssh "$PROD_SSH" "docker exec $PROD_DB sh -c 'pg_dump -U \"\$POSTGRES_USER\" --clean --if-exists \"\$POSTGRES_DB\" | gzip -1'" \
  | ssh "$NEW_SSH" "docker exec -i $NEW_DB sh -c 'gunzip | psql -v ON_ERROR_STOP=1 -q -U \"\$POSTGRES_USER\" \"\$POSTGRES_DB\"' > /tmp/cutover-restore.log 2>&1" \
  || { echo "--- 恢复日志尾部 ---"; ssh "$NEW_SSH" 'tail -25 /tmp/cutover-restore.log'; die "数据库恢复失败"; }
echo "恢复完成（日志 /tmp/cutover-restore.log）"

say "2/4 音频：增量同步（tar 流式）"
ssh "$NEW_SSH" "cd $NEW_PROJECT && docker compose -f compose.yml start backend >/dev/null" || die "新机 backend 启动失败"
for i in $(seq 1 30); do
  ssh "$NEW_SSH" "docker exec $NEW_APP true" 2>/dev/null && break
  sleep 2
done
ssh "$PROD_SSH" "docker exec $PROD_APP tar -C /app/audio -cf - ." \
  | ssh "$NEW_SSH" "docker exec -i $NEW_APP tar -C /app/audio -xf -"
echo "音频同步完成"

say "3/4 对账（行数 + 音频文件数）"
prod_rows=$(counts "$PROD_SSH" "$PROD_DB")
new_rows=$(counts "$NEW_SSH" "$NEW_DB")
prod_files=$(ssh "$PROD_SSH" "docker exec $PROD_APP sh -c 'find /app/audio -type f | wc -l'")
new_files=$(ssh "$NEW_SSH" "docker exec $NEW_APP sh -c 'find /app/audio -type f | wc -l'")
echo "生产: user/student/attempt/vocab/practice = $prod_rows；音频 $prod_files"
echo "新机: user/student/attempt/vocab/practice = $new_rows；音频 $new_files"
[ "$prod_rows" = "$new_rows" ] || die "数据库行数不一致"
[ "$prod_files" = "$new_files" ] || die "音频文件数不一致（$prod_files vs $new_files）"

say "4/4 迁移版本 + RLS 自检"
prod_rev=$(ssh "$PROD_SSH" "docker exec $PROD_DB psql -U postgres -d app -tAc 'select version_num from alembic_version'")
new_rev=$(ssh "$NEW_SSH" "docker exec $NEW_DB psql -U postgres -d app -tAc 'select version_num from alembic_version'")
[ "$prod_rev" = "$new_rev" ] || die "迁移版本不一致（$prod_rev vs $new_rev）"
echo "迁移版本一致: $prod_rev"
ssh "$NEW_SSH" "cd $NEW_PROJECT && bash scripts/prod-rls-selfcheck.sh" >/dev/null && echo "RLS 自检通过"

cat <<TXT

✅ 同步完成且对账一致。接下来按割接手册 2.4 起执行：
   1. 把 Environment production 的 8 个键指到 $NEW_HOST
   2. 签发正式域名证书（TLS_DOMAIN 改为正式域名后触发一次部署）
   3. 改 DNS A 记录
   4. 手动触发 deploy.yml，走验证清单
TXT
