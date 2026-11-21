#!/usr/bin/env bash
# 把最新备份 bundle 推到火山引擎 TOS（异地留存）。
#
# 日常只推「小而关键」的部分：database.sql.gz + config.env + metadata.txt（约 30MB），
# 因为音频本身有 TTL（AUDIO_TTL_DAYS 到期即删），不是长期资产；
# 需要完整包时加 --with-audio（体积 = 全量音频，约 1.7GB）。
#
# 用法（在服务器上执行）：
#   TOS_BUCKET=xxx bash scripts/backup-offsite.sh
#   TOS_BUCKET=xxx bash scripts/backup-offsite.sh --with-audio
#
# 需要的环境变量：
#   TOS_BUCKET   必填，例如 my-esa-backup
#   TOS_PREFIX   可选，默认 esa/<hostname>
#   TOS_ENDPOINT 可选，默认 tos-cn-beijing.volces.com（同地域 ECS 可用内网
#                tos-cn-beijing.ivolces.com 省公网流量）
#   TOS_REGION   可选，默认 cn-beijing
# 凭据：优先读 ~/.tosutilconfig（由 `tosutil config` 生成，600 权限）；
#       也可以用 TOS_AK/TOS_SK + tosutil 命令行参数，但推荐配置文件（不进命令行历史）。
#
# 依赖：tosutil（需在 PATH）。安装：
#   wget -O /usr/local/bin/tosutil https://tos-tools.tos-cn-beijing.volces.com/linux/tosutil \
#     && chmod +x /usr/local/bin/tosutil
set -euo pipefail
umask 077

project_dir="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$project_dir"
WITH_AUDIO=0
[ "${1:-}" = "--with-audio" ] && WITH_AUDIO=1

: "${TOS_BUCKET:?缺少 TOS_BUCKET（例：TOS_BUCKET=my-esa-backup）}"
TOS_PREFIX="${TOS_PREFIX:-esa/$(hostname)}"
TOS_ENDPOINT="${TOS_ENDPOINT:-tos-cn-beijing.volces.com}"
TOS_REGION="${TOS_REGION:-cn-beijing}"

command -v tosutil >/dev/null 2>&1 || {
  echo "❌ 未安装 tosutil。安装：wget -O /usr/local/bin/tosutil \\
https://tos-tools.tos-cn-beijing.volces.com/linux/tosutil && chmod +x /usr/local/bin/tosutil" >&2
  exit 1
}

latest=$(ls -1dt backups/bundle-* 2>/dev/null | head -n1 || true)
[ -n "$latest" ] || { echo "❌ backups/ 下没有 bundle-*，先跑 scripts/backup-local.sh" >&2; exit 1; }
[ -f "$latest/manifest.sha256" ] || { echo "❌ $latest 不是完整备份包（缺 manifest）" >&2; exit 1; }

stamp="$(basename "$latest")"
files=(database.sql.gz config.env metadata.txt manifest.sha256)
[ "$WITH_AUDIO" = "1" ] && files+=(audio.tar.gz)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tar -C "$latest" -czf "$tmp/payload.tar.gz" "${files[@]}"
size=$(du -h "$tmp/payload.tar.gz" | cut -f1)
echo "待上传：$stamp（${size}，$( [ "$WITH_AUDIO" = 1 ] && echo 含音频 || echo 不含音频)）"

remote="tos://${TOS_BUCKET}/${TOS_PREFIX}/${stamp}-$( [ "$WITH_AUDIO" = 1 ] && echo full || echo db).tar.gz"
common_args=(-e "$TOS_ENDPOINT" -re "$TOS_REGION")
if [ -n "${TOS_AK:-}" ] && [ -n "${TOS_SK:-}" ]; then
  common_args+=(-i "$TOS_AK" -k "$TOS_SK")
fi

if tosutil cp -f "$tmp/payload.tar.gz" "$remote" "${common_args[@]}" >/tmp/tosutil.log 2>&1; then
  echo "✅ 已上传 $remote"
else
  echo "❌ 上传失败，tosutil 输出：" >&2
  tail -12 /tmp/tosutil.log >&2
  exit 1
fi

echo "提示：远端保留策略建议在 TOS 控制台给该前缀配生命周期规则（如 30 天自动过期），"
echo "      脚本不做远端删除，避免误删唯一的异地副本。"
