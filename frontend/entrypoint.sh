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
exec /docker-entrypoint.sh "$@"
