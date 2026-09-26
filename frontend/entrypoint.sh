#!/bin/sh
# 证书存在（生产：acme.sh 已签发并挂载 ./ssl）→ 启用 TLS 配置；
# 不存在（本地开发 / 首次部署未配 DNSPod 密钥）→ 保持纯 HTTP 配置。
set -e
if [ -f /etc/nginx/ssl/fullchain.pem ]; then
  cp /etc/nginx/nginx-tls.conf /etc/nginx/conf.d/default.conf
  echo "entrypoint: 检测到 TLS 证书，启用 https 配置"
fi
exec /docker-entrypoint.sh "$@"
