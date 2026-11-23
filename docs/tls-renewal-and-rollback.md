# 生产 TLS 证书：自动续期、部署与回滚（outman.website）

> 适用环境：火山云北京 `115.190.122.24`，目录 `/srv/english-speaking-assessment`，compose 项目 `esa`。
> 最后核验：2026-11-23 20:05 CST。生产业务代码仍为 `fe4a6b4`，本次只动 TLS / 续期 / 监控，不改业务代码。

## 0. 结论

- `https://outman.website` 使用独立域名证书，SAN 为 `DNS:outman.website`，不再使用 IP 证书。
- 续期走 **DNS-01（DNSPod）**，复用既有 `outman.website_ecc` 的 DNSPod API 凭据；不新建、不复用不明凭据。
- 证书发布到 `ssl/domain/current`，只有指纹变化才原子切换并 `nginx -t` + reload；失败自动回滚上一版。
- 旧 `belp-ip-tls-renew.timer` 已 `stop` + `disable`，旧 IP 安装脚本已改为只维护 `ssl/ip/current`，不会再覆盖顶层 `ssl/fullchain.pem`。
- 新 `belp-domain-tls-deploy.timer` 每 12 小时运行（带 2 小时随机延迟），已 `enable --now`。
- `ops-watch.yml` 已改为 HTTPS 强制 TLS 校验；TLS/证书失败直接红灯，不再回落到本机 200 假绿；新增证书 SAN / 链 / 剩余 21 天 / 现役证书一致性 / timer 状态巡检。
- 服务器 `.env` 与 GitHub production environment Secrets 已切到域名；下次部署不会再生成 IP 的 `FRONTEND_HOST` / CORS。

## 1. 当前证书与路径

| 项 | 值 |
|---|---|
| 证书主题 / SAN | `CN=outman.website` / `DNS:outman.website` |
| 有效期 | `2026-11-23 10:54:15 GMT` → `2027-02-21 10:54:14 GMT` |
| SHA-256 指纹 | `46:63:5B:40:4A:09:B4:C1:83:A8:E0:86:79:1F:C3:EA:F5:B0:F9:9F:CA:ED:E3:3E:B3:8F:33:1A:51:1B:6E:48` |
| serial | `0675347B10F76D3FD13D96D6EC2117E72AAB` |
| 发布目录 | `ssl/domain/releases/0675347B10F76D3FD13D96D6EC2117E72AAB/` |
| 现役链接 | `ssl/domain/current -> releases/<serial>`；`ssl/fullchain.pem -> domain/current/fullchain.pem` |
| 私钥 | `ssl/privkey.pem -> domain/current/privkey.pem` |
| 旧域名证书（已被替换，保留作历史） | 指纹 `E7:B8:E7:4D:EC:CA:28:BC:90:DA:B9:6D:54:0F:39:AF:63:89:76:65:DE:42:FC:65:0D:55:8C:C0:DB:3D:1F:19`，到期 `2027-02-17` |
| IP 证书（仅回滚件） | `ssl/ip/current`，SAN `IP:115.190.122.24`，到期 `2026-11-29 06:55:06Z`；旧 timer 已停，不再自动续 |

## 2. 自动续期链路

```text
acme.sh（容器 esa-acme-1，DNS-01 / DNSPod）
  └─ 证书目录 /acme.sh/outman.website_ecc/
       └─ 由容器内 acme cron（23 1,7,13,19 * * *）续期
            ↓
/opt/belp-domain-tls/deploy.sh
  ├─ 读 fullchain.cer / outman.website.key
  ├─ 校验 SAN、链、证书/私钥匹配、剩余 > 21 天
  ├─ 指纹未变 → 记日志后跳过
  └─ 变化 → ssl/domain/releases/<serial>/ → 原子切 current + 顶层链接
       → nginx -t → reload
       → 失败恢复上一版链接并 reload
            ↑
belp-domain-tls-deploy.timer（每日 00/12 点 + 0–2h 随机延迟，Persistent）
```

关键资产：

- acme：容器 `esa-acme-1`，`/acmebin/acme.sh` v3.1.7；证书目录 `/acme.sh/outman.website_ecc/`，`Le_Webroot='dns_dp'`，`Le_API` 为 Let’s Encrypt **production**。
- DNSPod 凭据：`/acme.sh/account.conf` 的 `SAVED_DP_Id` / `SAVED_DP_Key`，来源是当初签发归档域名证书的既有账户；值不写入仓库、不回显。
- 部署器：`/opt/belp-domain-tls/deploy.sh`；锁 `/var/lock/belp-domain-tls.lock`；日志 `/var/log/belp-domain-tls/deploy.log`；日志轮转 `/etc/logrotate.d/belp-domain-tls`。
- 权限：`ssl/domain` 与 `releases/*` 为 `755`（GitHub 巡检用非 root 的 `deploy` 用户，需要可遍历）；`privkey.pem` 保持 `600 root`，巡检不读私钥。`/var/log/belp-domain-tls` 为 `755`，`deploy.log` 为 `644`，logrotate 固定 `create 0644 root root`。
- systemd：`/etc/systemd/system/belp-domain-tls-deploy.service`（`Type=simple`，`Restart=on-failure`，`RestartSec=300`，`StartLimitBurst=3`）；`belp-domain-tls-deploy.timer`（`OnCalendar=*-*-* 00,12:00:00`，`RandomizedDelaySec=2h`，`Persistent=true`）。
- 常用检查：

```bash
systemctl status belp-domain-tls-deploy.timer
systemctl status belp-ip-tls-renew.timer      # 应为 inactive/disabled
readlink -f /srv/english-speaking-assessment/ssl/domain/current
tail -n 20 /var/log/belp-domain-tls/deploy.log
```

## 3. 防覆盖改造（重要）

旧 IP 续期链路已切断：

1. `belp-ip-tls-renew.timer` 已 `systemctl stop` + `disable`。停前 `active/enabled`、next `2026-11-24 00:14:23 CST`；停后 `inactive/disabled`，无 next。
2. `/opt/belp-ip-tls/install_certificate.py` 已改为**只维护 `ssl/ip/current`**，不再写顶层 `ssl/fullchain.pem` / `privkey.pem`。
3. `/opt/belp-ip-tls/renew.sh` 最后检查改为 `ssl/ip/current/fullchain.pem`。
4. 原脚本备份：`/opt/belp-ip-tls/backups/pre-domain-20261123-195320/`（`install_certificate.py`、`renew.sh`）。
5. 系统 `certbot.timer` 虽每天 09:06 运行，但 `/etc/letsencrypt/renewal` 不存在，无续期目标；acme 容器 cron 只续 acme 自身证书，不直接写顶层。
6. 不要在部署时使用 `/opt/belp-ip-tls/compose.ip.yml` overlay——它会把 backend 的 `FRONTEND_HOST` / `BACKEND_CORS_ORIGINS` 强制回 IP。当前生产只用 `compose.yml`。

## 4. 部署配置（服务器 `.env` 与 GitHub Secrets）

服务器 `.env` 已切换（备份 `backups/env-domain-20261123-195500/env.before`）：

```dotenv
FRONTEND_HOST="https://outman.website"
BACKEND_CORS_ORIGINS="https://outman.website"
TLS_DOMAIN="outman.website"
```

GitHub production environment Secrets 已设置：

- `FRONTEND_HOST=https://outman.website`
- `TLS_DOMAIN=outman.website`
- `BACKEND_CORS_ORIGINS=https://outman.website`

说明：`scripts/generate-deploy-env.sh` 里 `BACKEND_CORS_ORIGINS="$FRONTEND_HOST"`，所以 CORS 最终由 `FRONTEND_HOST` 派生；单独设置 CORS Secret 是为了配置一致性，真正决定值的是 `FRONTEND_HOST`。部署流水线只映射 `FRONTEND_HOST` / `TLS_DOMAIN`，未单独映射 CORS。

改完已只重建 backend（不动 DB/frontend），容器 `healthy`，health 200；backend 环境变量确认为域名。下次部署会重新生成同样的域名配置，不会再落回 IP。

## 5. 监控规则

`ops-watch.yml` 每小时第 7 分钟运行，失败即 GitHub Actions 红灯 + owner 邮件：

1. **外部存活性**：`HEALTH_URL=https://outman.website/api/v1/utils/health-check/`，`curl` 默认校验证书，**不使用 `-k`**。
   - 200 且 TLS 校验通过 → 绿。
   - TLS/证书错误（curl `51/58/59/60/64/66/77/80/82/83/90/91`，或 stderr 明确报证书问题）→ **立即红灯，禁止回落本机自检**。
   - 非 `000` 的 HTTP 状态（如 5xx / 301）→ 红灯，不回落；只有纯网络不可达（HTTP `000` / 超时）才回落服务器本机 200，仅证明进程活着。
2. **证书与续期（`tls-cert` job）**：SSH 到服务器，直接读 `ssl/domain/current/fullchain.pem`，并用 `127.0.0.1:443 + SNI outman.website` 验证 nginx 实际提供的证书。
   - SAN 必须含 `DNS:outman.website`；
   - 链校验必须通过；
   - 剩余天数 `< 21` → 红灯；
   - nginx 现役证书指纹必须等于 `ssl/domain/current`；
   - 顶层 `ssl/fullchain.pem` 必须指向 `ssl/domain/current`；
   - `belp-domain-tls-deploy.timer` 必须 `active/enabled`；
   - `belp-ip-tls-renew.timer` 若重新 `active` → 红灯；
   - 部署 service 若 `failed` → 红灯；
   - 部署日志超过 30 小时未更新 → 红灯。
3. **磁盘水位 / 备份新鲜度**：沿用原有规则。

仓库变量：

```bash
gh variable set HEALTH_URL --body 'https://outman.website/api/v1/utils/health-check/'
```

## 6. 验证记录（2026-11-23）

- 强制续期：acme 容器 `--renew -d outman.website --force` 成功；新指纹 `46:63…6E:48`，到期 `2027-02-21`。
- 部署：`deploy.sh` 检测到指纹变化，发布 `serial=0675347B10F76D3FD13D96D6EC2117E72AAB`；`nginx -t` 通过、reload 成功，backend `restarts=0`。
- **真实 DNS-01**：acme staging + 独立 `--cert-home /tmp/acme-staging` 跑通，成功添加并清理 `_acme-challenge.outman.website` TXT，签发 staging 证书；生产证书指纹未变，acme `Le_API` 仍为 production。
- HTTPS：`curl https://outman.website` 200；HSTS `max-age=31536000`；证书链 `Verify return code: 0`。
- CORS：`OPTIONS /api/v1/utils/health-check/` 带 `Origin: https://outman.website` 返回 `access-control-allow-origin: https://outman.website`。
- 登录：域名 SNI 下管理员登录 200，`/users/me` 200（`school_admin`）。
- 回放：域名 SNI 下 `GET /api/v1/attempts/<id>/audio` 返回 200、`content-type: audio/wav`、188718 bytes，`file` 识别为 RIFF/WAVE，HSTS 保留。
- 上传门禁：生产匿名 `POST /api/v1/attempts` 返回 403「演示提交未开放，请登录后使用」，未写入任何作答；真实学生录音上传需用学生账号在 UI 里复验。

## 7. 故障处理与回滚

### 7.1 证书已更新但未部署

```bash
systemctl start belp-domain-tls-deploy.service
tail -n 30 /var/log/belp-domain-tls/deploy.log
```

### 7.2 强制重新签发（production）

```bash
cd /srv/english-speaking-assessment
docker compose exec -T acme /acmebin/acme.sh --renew -d outman.website --force
systemctl start belp-domain-tls-deploy.service
```

注意：如果 ACME authorization 仍有效，`--renew --force` 可能复用 authz、跳过 DNS-01 TXT 写入；要验证 DNS API，用 staging 独立目录：

```bash
docker compose exec -T acme sh -lc '
  rm -rf /tmp/acme-staging && mkdir -p /tmp/acme-staging
  /acmebin/acme.sh --issue --staging --dns dns_dp -d outman.website \
    --keylength ec-256 --cert-home /tmp/acme-staging --force
  rm -rf /tmp/acme-staging
'
```

### 7.3 回滚到上一版域名证书

`deploy.sh` 在切换后 `nginx -t` / reload 失败会自动恢复上一版链接。手动回滚：

```bash
cd /srv/english-speaking-assessment/ssl/domain
prev=$(ls -1dt releases/* | sed -n '2p')   # 取上一版；先 ls 确认
ln -sfn "$prev" current.tmp && mv -Tf current.tmp current
cd ..
ln -sfn domain/current/fullchain.pem fullchain.pem.tmp && mv -Tf fullchain.pem.tmp fullchain.pem
ln -sfn domain/current/privkey.pem privkey.pem.tmp && mv -Tf privkey.pem.tmp privkey.pem
docker compose exec -T frontend nginx -t
docker compose exec -T frontend nginx -s reload
```

每次部署前的域名证书与旧链接也备份在 `ssl/domain/backups/<timestamp>/`；首次域名切换前的完整备份在 `backups/cert-domain-20261123-191426/`（含旧 IP/域名证书、原链接目标、`default.conf`、`nginx-T.txt`）。

### 7.4 回滚 `.env`

```bash
cd /srv/english-speaking-assessment
cp backups/env-domain-20261123-195500/env.before .env
chmod 600 .env
docker compose up -d --no-deps --no-build backend
```

### 7.5 极端回滚到 IP 证书（不推荐）

仅在域名证书不可用、必须先用 IP 恢复访问时：

```bash
cd /srv/english-speaking-assessment/ssl
ln -sfn ip/current/fullchain.pem fullchain.pem.tmp && mv -Tf fullchain.pem.tmp fullchain.pem
ln -sfn ip/current/privkey.pem privkey.pem.tmp && mv -Tf privkey.pem.tmp privkey.pem
docker compose exec -T frontend nginx -t && docker compose exec -T frontend nginx -s reload
```

该操作会让域名访问重新出现证书不匹配警告；恢复域名证书后再切回 `domain/current`。不要重新启用 `belp-ip-tls-renew.timer`，除非整体回退到 IP 方案。

## 8. 遗留与注意事项

- **火山云接入备案**：`outman.website` 的 ICP 备案为 `京ICP备2022033467号-1`（主体为个人，2022-11-25 通过）；火山云控制台的“接入备案”是否完成无法从公开渠道确认，仍需用户在火山控制台核对。这不影响 TLS，但是合规项。
- **DNS-01 真实写入**：本次已用 staging 端到端验证 DNSPod API；生产强制续期因 authz 复用未重跑 TXT。下一次生产续期（ARI 建议 `2027-01-23` 附近）应观察 `deploy.log` 与 acme 输出，确认 TXT 写入/清理正常。
- **IP 访问**：`https://115.190.122.24` 现在只能用 `-k` 访问；不加 `-k` 会证书不匹配。这是单证书无法同时覆盖域名与 IP 的预期代价，IP 证书仅作回滚件。
- **真实录音上传**：生产禁止匿名提交，本次只验证了上传接口 TLS 可达与 403 门禁；真实学生录音上传/回放需用学生账号在 UI 复验。
- 本次未改生产 env/nginx/DNS/备案主体，未重启 DB；只重建 backend 使域名 CORS 生效。
