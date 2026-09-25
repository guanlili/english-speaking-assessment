#!/usr/bin/env bash
set -euo pipefail

# 部署通道必填（缺失时给出明确错误，而不是让 ssh-action 报晦涩的连接失败）
for k in SERVER_HOST SERVER_USER SERVER_SSH_KEY DEPLOY_PATH; do
  v="${!k:-}"
  if [[ -z "${v//[[:space:]]/}" ]]; then
    echo "❌ Secret $k 缺失或为空白，无法部署"
    exit 1
  fi
done
# .env 必填键：缺失/空/纯空白一律失败（失败发生在触碰服务器之前）
for k in FRONTEND_HOST SECRET_KEY FIRST_SUPERUSER FIRST_SUPERUSER_PASSWORD POSTGRES_PASSWORD APP_PORT PROJECT_NAME COMPOSE_PROJECT_NAME; do
  v="${!k:-}"
  if [[ -z "${v//[[:space:]]/}" ]]; then
    echo "❌ Secret $k 缺失或为空白（.env 必填项）"
    exit 1
  fi
done

if [[ ! "$APP_PORT" =~ ^[0-9]+$ ]] || (( 10#$APP_PORT < 1 || 10#$APP_PORT > 65535 )); then
  echo "APP_PORT must be an integer between 1 and 65535" >&2
  exit 1
fi

# dotenv 序列化：双引号包裹，$ → $$（防 compose 插值）、" → \"、\ → \\。
# 换行值 .env 无法表达，直接报错（Secret 里出现换行基本是配错了）
serialize() {
  local key=$1 value
  value="${!key}"
  if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
    echo "❌ Secret $key 的值包含换行符，.env 不支持" >&2
    return 1
  fi
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//\$/\$\$}"
  printf '%s="%s"' "$key" "$value"
}

keys=(PROJECT_NAME COMPOSE_PROJECT_NAME SECRET_KEY FIRST_SUPERUSER FIRST_SUPERUSER_PASSWORD POSTGRES_PASSWORD FRONTEND_HOST ENVIRONMENT BACKEND_CORS_ORIGINS USERS_OPEN_REGISTRATION SMTP_HOST SMTP_USER SMTP_PASSWORD EMAILS_FROM_EMAIL SMTP_TLS SMTP_SSL SMTP_PORT POSTGRES_SERVER POSTGRES_PORT POSTGRES_DB POSTGRES_USER SENTRY_DSN APP_PORT WORKERS SCORING_PROVIDER ARK_API_KEY ARK_ASR_MODEL ARK_RUBRIC_MODEL ARK_TTS_API_KEY ARK_TTS_MODEL ARK_TTS_VOICE)

# 固定值 / 派生值（不来自 Secrets 的键在此赋值）
ENVIRONMENT=production
POSTGRES_SERVER=db
POSTGRES_PORT=5432
POSTGRES_DB=app
POSTGRES_USER=postgres
SENTRY_DSN=
SCORING_PROVIDER=${SCORING_PROVIDER:-mock}
ARK_API_KEY=${ARK_API_KEY:-}
# 方舟 API 调用名必须带日期后缀，广场短名（doubao-seed-2-0-lite）会 404
ARK_ASR_MODEL=${ARK_ASR_MODEL:-doubao-seed-2-0-lite-260428}
ARK_RUBRIC_MODEL=${ARK_RUBRIC_MODEL:-doubao-seed-2-0-lite-260428}
# TTS 走 vei AI 网关（与方舟两套密钥）；未配时 TTS 生成 503，上传通道不受影响
ARK_TTS_API_KEY=${ARK_TTS_API_KEY:-}
ARK_TTS_MODEL=${ARK_TTS_MODEL:-doubao-tts}
ARK_TTS_VOICE=${ARK_TTS_VOICE:-}
# CORS 与前端同源（沿用原部署行为）
BACKEND_CORS_ORIGINS="$FRONTEND_HOST"

output=${1:?Output path required}
umask 077
tmp=$(mktemp "${output}.XXXXXX")
trap 'rm -f "$tmp"' EXIT
for k in "${keys[@]}"; do
  serialize "$k" >> "$tmp"
  printf '\n' >> "$tmp"
done
mv "$tmp" "$output"
