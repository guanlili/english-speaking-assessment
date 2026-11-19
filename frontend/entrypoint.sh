#!/bin/sh
# 证书存在（生产：acme.sh 已签发并挂载 ./ssl）→ 启用 TLS 配置；
# 不存在（本地开发 / 首次部署未配 DNSPod 密钥）→ 保持纯 HTTP 配置。
set -e
if [ -f /etc/nginx/ssl/fullchain.pem ]; then
  cp /etc/nginx/nginx-tls.conf /etc/nginx/conf.d/default.conf
  echo "entrypoint: 检测到 TLS 证书，启用 https 配置"
fi
# 遇己域名：outman.press 证书链齐全才挂入 conf.d（缺 privkey 时 nginx -t 会失败）
if [ -f /etc/nginx/ssl/outman.press/fullchain.pem ] \
  && [ -f /etc/nginx/ssl/outman.press/privkey.pem ] \
  && [ -f /etc/nginx/outman.press.conf ]; then
  cp /etc/nginx/outman.press.conf /etc/nginx/conf.d/outman.press.conf
  echo "entrypoint: 检测到 outman.press 证书，启用反代到 host.docker.internal:8080"
else
  rm -f /etc/nginx/conf.d/outman.press.conf 2>/dev/null || true
fi
# 域名迁移期：旧域名 301 → 主域名。两个环境变量与旧域名证书齐备才启用，
# 默认（变量为空）不生成任何配置，行为与迁移前完全一致。
if [ -n "${LEGACY_DOMAIN:-}" ] && [ -n "${PRIMARY_DOMAIN:-}" ] \
  && [ -f /etc/nginx/ssl/legacy/fullchain.pem ] \
  && [ -f /etc/nginx/ssl/legacy/privkey.pem ] \
  && [ -f /etc/nginx/legacy-redirect.conf ]; then
  sed -e "s|__LEGACY_DOMAIN__|${LEGACY_DOMAIN}|g" \
      -e "s|__PRIMARY_DOMAIN__|${PRIMARY_DOMAIN}|g" \
      /etc/nginx/legacy-redirect.conf > /etc/nginx/conf.d/legacy-redirect.conf
  if nginx -t >/dev/null 2>&1; then
    echo "entrypoint: 旧域名 ${LEGACY_DOMAIN} 301 → ${PRIMARY_DOMAIN}"
  else
    rm -f /etc/nginx/conf.d/legacy-redirect.conf
    echo "entrypoint: 旧域名跳转配置校验失败，已回退（不影响主域名）" >&2
  fi
else
  rm -f /etc/nginx/conf.d/legacy-redirect.conf 2>/dev/null || true
fi
exec /docker-entrypoint.sh "$@"
