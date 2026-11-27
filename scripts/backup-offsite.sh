#!/usr/bin/env bash
# 异地备份：把最新本地 bundle 推到阿里云 OSS（S3 兼容协议，rclone）。
#
# 日常由 cron 在本地备份之后运行（见 deploy-prod.yml 注册，04:00）。
# 未配置 OSS 凭证时安全跳过（退出 0），不让巡检/ cron 变红；配齐后自动启用。
#
# 用法（服务器上）：
#   bash scripts/backup-offsite.sh                 # 真实上传 + 远端保留清理
#   DRY_RUN=1 bash scripts/backup-offsite.sh      # 演练：只打印动作，不写远端
#   OSS_WITH_AUDIO=0 bash scripts/backup-offsite.sh  # 只传 db/config/metadata/manifest
#
# 需要的环境变量（走受限 .env / Secret，不进仓库、不进命令行历史）：
#   OSS_ACCESS_KEY_ID      RAM AccessKey ID
#   OSS_ACCESS_KEY_SECRET  RAM AccessKey Secret
#   OSS_ENDPOINT           例：https://oss-cn-beijing.aliyuncs.com（同地域可用内网 endpoint）
#   OSS_BUCKET             例：my-esa-backup
#   OSS_PREFIX             可选，默认 esa/<hostname>
#   OSS_RETENTION_DAYS     可选，默认 14（按包名时间戳）
#   OSS_WITH_AUDIO         可选，默认 1（含 audio.tar.gz；0 只传关键小文件）
#   DRY_RUN                可选，1 = 不写远端
set -euo pipefail
umask 077

project_dir="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$project_dir"

DRY_RUN="${DRY_RUN:-0}"
OSS_WITH_AUDIO="${OSS_WITH_AUDIO:-1}"
RETENTION_DAYS="${OSS_RETENTION_DAYS:-14}"
OSS_PREFIX="${OSS_PREFIX:-esa/$(hostname)}"

failure_log=backups/offsite-failure.log
log_failure() {
  mkdir -p backups
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$failure_log"
}

# cron 环境不带 .env；这里只把 OSS_* 从受限 .env 补进环境（不全量 source，避免
# compose 序列化的 $$ 被 shell 二次展开）。已在环境里显式设置的变量不覆盖。
if [ -f .env ]; then
  while IFS='=' read -r k v; do
    case "$k" in
      OSS_*)
        v="${v%\"}"; v="${v#\"}"
        eval "current=\${$k:-}"
        [ -z "$current" ] && eval "$k=\$v"
        ;;
    esac
  done < <(grep -E '^OSS_' .env || true)
fi

# 1. 凭证齐备性检查：缺任一项即跳过（不算失败），提示需要补哪些。
missing=0
for k in OSS_ACCESS_KEY_ID OSS_ACCESS_KEY_SECRET OSS_ENDPOINT OSS_BUCKET; do
  if [ -z "${!k:-}" ]; then
    echo "⏭ 未配置 $k，异地备份跳过"
    missing=1
  fi
done
if [ "$missing" = 1 ]; then
  echo "提示：配齐 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_ENDPOINT / OSS_BUCKET 后自动启用。"
  exit 0
fi

command -v rclone >/dev/null 2>&1 || {
  echo "❌ 未安装 rclone。Ubuntu: apt-get install -y rclone；或按 rclone 官方静态包装到 /usr/local/bin。" >&2
  exit 1
}

# 2. 选最新完整包（按包名时间戳，排除 BROKEN），复用本地校验脚本核验可恢复性。
latest=$(ls -1d backups/bundle-* 2>/dev/null | grep -v '\.BROKEN$' | sort | tail -n1 || true)
[ -n "$latest" ] || { echo "❌ backups/ 下没有 bundle-*，先跑 scripts/backup-local.sh" >&2; exit 1; }
[ -f "$latest/manifest.sha256" ] || { echo "❌ $latest 不是完整备份包（缺 manifest）" >&2; exit 1; }

bash scripts/verify-backup.sh "$latest"
stamp="$(basename "$latest")"

# 3. rclone 远端从环境变量注入，不在磁盘留 rclone 配置文件。
export RCLONE_CONFIG_ESAOSS_TYPE=s3
export RCLONE_CONFIG_ESAOSS_PROVIDER=Alibaba
export RCLONE_CONFIG_ESAOSS_ENDPOINT="$OSS_ENDPOINT"
export RCLONE_CONFIG_ESAOSS_ACCESS_KEY_ID="$OSS_ACCESS_KEY_ID"
export RCLONE_CONFIG_ESAOSS_SECRET_ACCESS_KEY="$OSS_ACCESS_KEY_SECRET"
export RCLONE_CONFIG_ESAOSS_ACL=private

remote_dir="esaoss:${OSS_BUCKET}/${OSS_PREFIX}/${stamp}"
rclone_args=()
[ "$DRY_RUN" = "1" ] && rclone_args+=(--dry-run)

# 4. 上传整包（默认含音频）；--no-traverse 避免列举整桶。
echo "待上传：$stamp → oss://${OSS_BUCKET}/${OSS_PREFIX}/${stamp}（$(du -sh "$latest" | cut -f1)，$( [ "$OSS_WITH_AUDIO" = 1 ] && echo 含音频 || echo 不含音频)）"
if [ "$OSS_WITH_AUDIO" = "1" ]; then
  if ! rclone copy "$latest" "$remote_dir" "${rclone_args[@]}" --no-traverse; then
    log_failure "upload failed: $stamp (with audio)"
    echo "❌ 上传失败（含音频），详见上方 rclone 输出" >&2
    exit 1
  fi
else
  if ! rclone copy "$latest" "$remote_dir" "${rclone_args[@]}" --no-traverse \
    --include "database.sql.gz" --include "config.env" --include "metadata.txt" --include "manifest.sha256"; then
    log_failure "upload failed: $stamp (db only)"
    echo "❌ 上传失败（仅关键文件），详见上方 rclone 输出" >&2
    exit 1
  fi
fi

# 5. 远端保留策略：按包名时间戳清理超期 bundle（与本地 14 天窗口一致）。
#    时间戳定宽 ISO，字符串字典序即时间顺序；dry-run 下只列不删。
if date -d '1 second ago' +%s >/dev/null 2>&1; then
  cutoff_stamp=$(date -u -d "@$(( $(date -u +%s) - RETENTION_DAYS * 86400 ))" +%Y%m%dT%H%M%SZ)
else
  cutoff_stamp=$(date -u -v-"${RETENTION_DAYS}"d +%Y%m%dT%H%M%SZ)
fi

remote_prefix="esaoss:${OSS_BUCKET}/${OSS_PREFIX}"
for remote_stamp in $(rclone lsf "$remote_prefix" "${rclone_args[@]}" --dirs-only 2>/dev/null || true); do
  stamp_only="${remote_stamp%/}"
  ts=$(printf '%s' "$stamp_only" | sed -nE 's/^bundle-([0-9]{8}T[0-9]{6}Z)-.*/\1/p')
  [ -n "$ts" ] || continue
  if [[ "$ts" < "$cutoff_stamp" ]]; then
    echo "清理超期远端包：$stamp_only"
    rclone delete "$remote_prefix/$stamp_only" "${rclone_args[@]}" --rmdirs || {
      log_failure "prune failed: $stamp_only"
      echo "❌ 远端清理失败：$stamp_only" >&2
      exit 1
    }
  fi
done

echo "✅ 异地备份完成：$remote_dir$( [ "$DRY_RUN" = 1 ] && echo '（dry-run，未实际写入）' )"
