#!/usr/bin/env bash
# 域名迁移：把主域名从 OLD 换成 NEW，并让 OLD 永久 301 到 NEW。
#
# 用法：scripts/switch-domain.sh <新域名> <旧域名> [SSH别名]
#   例：scripts/switch-domain.sh speakup.cn outman.website volc-belp
#
# 做的事（全部在服务器上执行，可重复运行，幂等）：
#   1. 把当前证书（OLD 域名）复制到 ssl/legacy/，并把 acme 的续期安装路径也改到那里
#      —— 否则 acme 续期 OLD 证书时会覆盖主证书文件
#   2. 用 DNS-01 签发 NEW 域名证书并安装为 ssl/fullchain.pem（主证书）
#   3. 更新 .env：TLS_DOMAIN / FRONTEND_HOST / LEGACY_DOMAIN / PRIMARY_DOMAIN
#   4. 重建 frontend 容器（entrypoint 渲染 301 配置）并做 nginx -t
#   5. 本机 --resolve 验证：NEW 返回 200、OLD 返回 301 指向 NEW
#
# 不含 DNS 切换与 GitHub Secrets 更新（脚本最后会打印对应命令）。
set -euo pipefail

NEW_DOMAIN="${1:?用法: switch-domain.sh <新域名> <旧域名> [SSH别名]}"
OLD_DOMAIN="${2:?用法: switch-domain.sh <新域名> <旧域名> [SSH别名]}"
SSH_HOST="${3:-volc-belp}"
PROJECT_DIR="/srv/english-speaking-assessment"

echo "== 迁移：${OLD_DOMAIN} → ${NEW_DOMAIN}（服务器 ${SSH_HOST}） =="

ssh -o ConnectTimeout=10 "$SSH_HOST" bash -s -- "$NEW_DOMAIN" "$OLD_DOMAIN" "$PROJECT_DIR" <<'REMOTE'
set -euo pipefail
NEW="$1"; OLD="$2"; DIR="$3"
cd "$DIR"
ts=$(date -u +%Y%m%dT%H%M%SZ)

echo "-- 1/5 备份并接管旧域名证书 --"
mkdir -p ssl/legacy
cp -f ssl/fullchain.pem "ssl/fullchain.pem.${OLD}.bak.${ts}"
cp -f ssl/privkey.pem   "ssl/privkey.pem.${OLD}.bak.${ts}"
cp -f ssl/fullchain.pem ssl/legacy/fullchain.pem
cp -f ssl/privkey.pem   ssl/legacy/privkey.pem
# 关键：让 acme 记住 OLD 的续期安装路径是 legacy 目录，避免续期时覆盖主证书
docker compose -f compose.yml run --rm acme --install-cert -d "$OLD" --ecc \
  --fullchain-file /ssl/legacy/fullchain.pem --key-file /ssl/legacy/privkey.pem >/dev/null
echo "   旧证书已落到 ssl/legacy/（并改写 acme 续期安装路径）"

echo "-- 2/5 签发新域名证书 --"
docker compose -f compose.yml run --rm acme --issue --dns dns_dp -d "$NEW" \
  --server letsencrypt --keylength ec-256

echo "-- 3/5 安装为主证书 --"
docker compose -f compose.yml run --rm acme --install-cert -d "$NEW" --ecc \
  --fullchain-file /ssl/fullchain.pem --key-file /ssl/privkey.pem >/dev/null
openssl x509 -in ssl/fullchain.pem -noout -subject -enddate

echo "-- 4/5 更新 .env 并重建 frontend --"
set_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=\"${val}\"|" .env
  else
    printf '%s="%s"\n' "$key" "$val" >> .env
  fi
}
set_env TLS_DOMAIN "$NEW"
set_env FRONTEND_HOST "https://${NEW}"
set_env LEGACY_DOMAIN "$OLD"
set_env PRIMARY_DOMAIN "$NEW"
docker compose -f compose.yml up -d --no-deps frontend >/dev/null
sleep 6
docker compose -f compose.yml ps --format '{{.Name}} {{.Status}}' | grep frontend
docker compose -f compose.yml exec -T frontend nginx -t

echo "-- 5/5 本机验证 --"
new_code=$(curl -sS --resolve "$NEW:443:127.0.0.1" -o /dev/null -w '%{http_code}' "https://$NEW/" || true)
old_jump=$(curl -sS --resolve "$OLD:443:127.0.0.1" -o /dev/null -w '%{http_code} %{redirect_url}' "https://$OLD/" || true)
echo "   NEW  https 状态: $new_code"
echo "   OLD  https 跳转: $old_jump"
[ "$new_code" = "200" ] || { echo "新域名本机验证失败（$new_code），先别改 DNS" >&2; exit 1; }
case "$old_jump" in
  301*) echo "   旧域名 301 生效 ✓" ;;
  *) echo "旧域名跳转异常：$old_jump" >&2; exit 1 ;;
esac
REMOTE

echo
echo "== 服务器侧完成。剩下两步 =="
echo "1) 更新 GitHub Environment production（否则下次部署会把 .env 改回去）："
echo "   printf '%s' 'https://${NEW_DOMAIN}' | gh secret set FRONTEND_HOST --env production"
echo "   printf '%s' '${NEW_DOMAIN}'          | gh secret set TLS_DOMAIN    --env production"
echo "   printf '%s' '${OLD_DOMAIN}'          | gh secret set LEGACY_DOMAIN --env production"
echo "   printf '%s' '${NEW_DOMAIN}'          | gh secret set PRIMARY_DOMAIN --env production"
echo "2) DNSPod 把 ${OLD_DOMAIN} 与 ${NEW_DOMAIN} 的 A 记录都指向同一台服务器，"
echo "   然后全量验证：curl -I https://${NEW_DOMAIN}/ 、curl -I https://${OLD_DOMAIN}/"
