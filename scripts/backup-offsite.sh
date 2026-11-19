#!/usr/bin/env bash
# 把最新备份 bundle 推到阿里云 OSS（异地留存）。
#
# 日常只推「小而关键」的部分：database.sql.gz + config.env + metadata.txt（约 30MB），
# 因为音频本身有 TTL（AUDIO_TTL_DAYS 到期即删），不是长期资产；
# 需要完整包时加 --with-audio（体积 = 全量音频，约 1.7GB）。
#
# 用法（在服务器上执行）：
#   OSS_BUCKET=xxx bash scripts/backup-offsite.sh
#   OSS_BUCKET=xxx bash scripts/backup-offsite.sh --with-audio
#
# 需要的环境变量：
#   OSS_BUCKET   必填，例如 my-esa-backup
#   OSS_PREFIX   可选，默认 esa/<hostname>
#   OSS_ENDPOINT 可选，默认 oss-cn-beijing.aliyuncs.com
# 凭据：优先读 ~/.ossutilconfig（由 `ossutil config` 生成，600 权限）；
#       也可以用 OSS_AK/OSS_SK + ossutil 命令行参数，但推荐配置文件（不进命令行历史）。
#
# 依赖：ossutil（v1/v2 均可，需在 PATH）
set -euo pipefail
umask 077

project_dir="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$project_dir"
WITH_AUDIO=0
[ "${1:-}" = "--with-audio" ] && WITH_AUDIO=1

: "${OSS_BUCKET:?缺少 OSS_BUCKET（例：OSS_BUCKET=my-esa-backup）}"
OSS_PREFIX="${OSS_PREFIX:-esa/$(hostname)}"
OSS_ENDPOINT="${OSS_ENDPOINT:-oss-cn-beijing.aliyuncs.com}"

command -v ossutil >/dev/null 2>&1 || {
  echo "❌ 未安装 ossutil。安装：curl -fsSL -o /usr/local/bin/ossutil \\
    https://gosspublic.alicdn.com/ossutil/1.7.19/ossutil64 && chmod +x /usr/local/bin/ossutil" >&2
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

remote="oss://${OSS_BUCKET}/${OSS_PREFIX}/${stamp}-$( [ "$WITH_AUDIO" = 1 ] && echo full || echo db).tar.gz"
if ossutil cp -f "$tmp/payload.tar.gz" "$remote" -e "$OSS_ENDPOINT" -i "${OSS_AK:-}" -k "${OSS_SK:-}" >/tmp/ossutil.log 2>&1; then
  echo "✅ 已上传 $remote"
elif ossutil cp -f "$tmp/payload.tar.gz" "$remote" -e "$OSS_ENDPOINT" >/tmp/ossutil.log 2>&1; then
  echo "✅ 已上传（用 ~/.ossutilconfig 凭据）$remote"
else
  echo "❌ 上传失败，ossutil 输出：" >&2
  tail -12 /tmp/ossutil.log >&2
  exit 1
fi

echo "提示：远端保留策略建议在 OSS 控制台给该前缀配生命周期规则（如 30 天自动过期），"
echo "      脚本不做远端删除，避免误删唯一的异地副本。"
