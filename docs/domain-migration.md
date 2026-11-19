# 域名迁移手册（outman.website → 新域名）

> 场景：保留旧域名不断链，新域名成为主站。旧域名永久 301 到新域名。
> 目标耗时：备案下来后 **20 分钟**，其中技术操作约 6 分钟。

## 0. 前置条件（缺一不可）

- [ ] 新域名已完成**实名认证**，持有者与备案主体一致
- [ ] 新域名**备案已通过**（火山引擎接入）
- [ ] 新域名在 DNSPod 有解析权限（或能改 NS 到 DNSPod）
- [ ] 确认旧域名 `outman.website` 的证书仍在有效期内（当前至 2027-02-17）

## 1. 执行（一条命令）

```bash
cd ~/Projects/english-speaking-assessment
bash scripts/switch-domain.sh <新域名> outman.website
```

脚本在服务器上完成五件事：旧证书落到 `ssl/legacy/`（并改写 acme 续期路径，避免续期覆盖主证书）→ 签发新域名证书 → 安装为主证书 → 改 `.env` 四个键 → 重建 frontend 并 `nginx -t`，最后用 `--resolve` 本机验证「新域名 200 / 旧域名 301」。

## 2. 更新 GitHub Secrets（脚本会打印这四条，必须做）

```bash
GH=/opt/homebrew/bin/gh
printf '%s' 'https://<新域名>' | $GH secret set FRONTEND_HOST  --env production
printf '%s' '<新域名>'          | $GH secret set TLS_DOMAIN     --env production
printf '%s' 'outman.website'   | $GH secret set LEGACY_DOMAIN  --env production
printf '%s' '<新域名>'          | $GH secret set PRIMARY_DOMAIN --env production
```

**为什么必须做**：每次部署都会用 Secrets 重新生成 `.env`，不改 Secrets，下次部署就把域名改回旧的，且 `LEGACY_DOMAIN` 丢失 → 301 消失。

## 3. DNS 切换

| 记录 | 值 | TTL |
|---|---|---|
| `<新域名>` A | `115.190.122.24` | 600 |
| `outman.website` A | **保持不变**（继续指 `115.190.122.24`） | 600 |

旧域名不能删，301 靠它承接老链接。

## 4. 验证清单

```bash
curl -I https://<新域名>/           # 200
curl -s https://<新域名>/api/v1/utils/ready-check/   # {"message":"Ready"}
curl -I https://outman.website/     # 301 → https://<新域名>/...
openssl s_client -connect <新域名>:443 -servername <新域名> </dev/null 2>/dev/null | openssl x509 -noout -subject
```

浏览器侧再走一遍：登录 → 上传一段录音 → 回放（音频与麦克风权限只在 https 下可用）。

## 5. 回滚（3 分钟）

```bash
# 服务器
cd /srv/english-speaking-assessment
cp ssl/fullchain.pem.outman.website.bak.<时间戳> ssl/fullchain.pem
cp ssl/privkey.pem.outman.website.bak.<时间戳>   ssl/privkey.pem
sed -i 's|^LEGACY_DOMAIN=.*|LEGACY_DOMAIN=""|;s|^PRIMARY_DOMAIN=.*|PRIMARY_DOMAIN=""|' .env
docker compose up -d --no-deps frontend
# GitHub：把 FRONTEND_HOST/TLS_DOMAIN 改回 https://outman.website / outman.website
```

DNS 若要回滚，把新域名 A 记录改回原值（旧域名没动过，天然可用）。

## 6. 收尾（迁移满 6 个月后再做）

- 旧域名继续 301，**不要提前下线**（外部链接、用户收藏夹、搜索引擎都靠它）
- 期间可在旧域名上挂一个 `410 Gone`？不建议——301 比 410 对搜索友好
- 6 个月后：删 `ssl/legacy/`，把 `.env` 的 `LEGACY_DOMAIN` 置空，重建 frontend，旧的 301 配置自动消失（entrypoint 检测不到就移除）

## 7. 容易被忽略的连带项

- [ ] 邮件模板里的站点链接（登录/重置密码邮件）
- [ ] 前端 `APP_NAME` 或分享文案里的域名
- [ ] 第三方回调地址（如 OAuth、支付回调、Sentry 允许域）
- [ ] 后端 `BACKEND_CORS_ORIGINS`：部署脚本自动等于 `FRONTEND_HOST`，改 Secrets 即可，无需单独改
- [ ] `ops-watch.yml` 的 `HEALTH_URL`：已支持 `vars.HEALTH_URL` 覆盖，换域名时改仓库变量即可

## 实现细节备忘

- 301 配置在 `nginx-extra/legacy-redirect.conf`，由 `frontend/entrypoint.sh` 在「`LEGACY_DOMAIN`/`PRIMARY_DOMAIN` 非空 + `ssl/legacy/` 证书齐备」时渲染；默认关闭，行为与迁移前一致。
- 渲染后会先 `nginx -t`，失败则自动移除该配置，不影响主域名启动。
- 两份证书并行续期：主域名 → `/ssl/fullchain.pem`，旧域名 → `/ssl/legacy/fullchain.pem`。
