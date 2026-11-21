# 割接手册：腾讯云 → 火山引擎（测试环境转正）

> 目标：把生产从 `49.232.156.221`（`/opt/speakup`，`outman.website`）切到
> `115.190.122.24`（`/srv/english-speaking-assessment`），旧机保留 2 周后释放。
>
> 设计原则：**切换只改 GitHub Environment `production` 的 8 个键**，代码零改动；
> 回滚是把这 8 个键改回去，旧机数据在释放前不动。

## 0. 前置条件（缺一不可）

| 项 | 判定标准 | 谁来做 |
|---|---|---|
| 域名归属 | `outman.website` 继续用，还是换 `zhiguan.online` | 决策 |
| ICP 备案 | 工信部能查到该域名；若备案在腾讯云，需在火山做**接入备案变更**（1–3 工作日） | 外部 |
| 演练 | 在低峰期完整跑一遍第 1–3 步（不切 DNS） | 运维 |
| 备份 | `scripts/backup-offsite.sh` 至少成功一次，TOS 上有可用包；新机已装 `tosutil` 并配好 `~/.tosutilconfig`（或 `TOS_AK/TOS_SK/TOS_BUCKET` 环境变量） | 运维 |
| 监控 | 仓库变量 `HEALTH_URL` 指向待切换域名 | 运维 |

## 1. 割接前 24 小时

```bash
# 1.1 确认两边版本一致（除 docs 外应无差异）
ssh esa-prod  'cd /opt/speakup && git log --oneline -1'
ssh volc-belp 'su - deploy -c "cd /srv/english-speaking-assessment && git log --oneline -1"'

# 1.2 记录基线（割接后要比对）
ssh esa-prod  'docker exec speakup-db-1 psql -U postgres -d app -tAc "
  select (select count(*) from \"user\")||\"/\"||(select count(*) from student)||\"/\"||
         (select count(*) from attempt)||\"/\"||(select count(*) from vocab_level_entry)"
ssh esa-prod  'docker exec speakup-backend-1 sh -c "find /app/audio -type f | wc -l; du -sh /app/audio"'

# 1.3 备份可恢复性演练（新机恢复到一个临时库，不覆盖现有 app）
bash scripts/recovery-drill.sh   # 按该脚本提示操作
```

## 2. 割接窗口（预计 25 分钟）

### 2.1 停写（T+0）

```bash
ssh esa-prod 'cd /opt/speakup && docker compose -f compose.yml stop backend'
ss -lnt | grep -q ':8000' && echo "backend 仍在监听" || echo "backend 已停"
```

前端继续提供静态页，用户提交会失败但不会写入脏数据。

### 2.2 最终数据同步（T+3，约 3 分钟）

```bash
# Mac Mini 上执行；脚本内做 pg_dump 流式传输 + 音频增量 + 校验
PROD_SSH=esa-prod NEW_SSH=volc-belp bash scripts/cutover-sync.sh --final
```

脚本结束会打印两边的行数与音频文件数，必须完全一致。

### 2.3 校验（T+6）

```bash
ssh volc-belp 'cd /srv/english-speaking-assessment && bash scripts/prod-rls-selfcheck.sh'
ssh volc-belp 'docker exec esa-db-1 psql -U postgres -d app -tAc "select version_num from alembic_version"'
# 期望：与旧机一致（当前 e6f2c8a3d5b1）
```

### 2.4 先签正式域名证书（T+8，约 1 分钟）

**必须在切指向之前**：DNS-01 走 TXT 记录，与 A 记录指向谁无关，所以可以在旧机还在服务时就签好；
等切完 nginx 才拿得到新域名的证书，否则上线瞬间会报证书错误。

```bash
ssh volc-belp 'cd /srv/english-speaking-assessment && \
  docker compose -f compose.yml run --rm acme --issue --dns dns_dp -d outman.website --server letsencrypt --keylength ec-256 && \
  docker compose -f compose.yml run --rm acme --install-cert -d outman.website --ecc \
    --fullchain-file /ssl/fullchain.pem --key-file /ssl/privkey.pem && \
  openssl x509 -in ssl/fullchain.pem -noout -subject -dates'
```

### 2.5 切换生产指向（T+9，一条命令）

```bash
# 只改 8 个键；其余 41 个（应用密钥、DB 密码、ARK/ASR）不动
GH=/opt/homebrew/bin/gh
REPO=guanlili/english-speaking-assessment
for kv in \
  SERVER_HOST=115.190.122.24 \
  SERVER_USER=deploy \
  DEPLOY_PATH=/srv/english-speaking-assessment \
  COMPOSE_PROJECT_NAME=esa \
  FRONTEND_HOST=https://outman.website \
  APP_PORT=80 \
  TLS_DOMAIN=outman.website ; do
  printf '%s' "${kv#*=}" | $GH secret set "${kv%%=*}" --env production
done
printf '%s' "$(cat ~/.ssh/lilimacmini.pem)" | $GH secret set SERVER_SSH_KEY --env production
```

### 2.6 部署并验证（T+10，约 4 分钟）

```bash
/opt/homebrew/bin/gh workflow run deploy.yml     # 手动触发生产部署
/opt/homebrew/bin/gh run watch                   # 等就绪检查通过
```

此时新机已按新 .env 重建（`TLS_DOMAIN=outman.website`、`COMPOSE_PROJECT_NAME=esa`），
但公网流量还在旧机，先本机验证：

```bash
ssh volc-belp 'curl -sS -H "Host: outman.website" --resolve outman.website:443:127.0.0.1 \
  https://outman.website/api/v1/utils/ready-check/'
# 期望 {"message":"Ready"}
```

### 2.7 改 DNS（T+14）

DNSPod 把 `outman.website` 的 A 记录从 `49.232.156.221` 改为 `115.190.122.24`，
TTL 已为 600 秒（10 分钟内全球生效）。

```bash
dig +short @223.5.5.5 outman.website   # 应返回 115.190.122.24
```

### 2.8 公网验证清单

逐项打勾，任一失败即回滚（第 3 节）：

- [ ] `curl -I https://outman.website/` → 200，证书 CN=outman.website
- [ ] `curl -s https://outman.website/api/v1/utils/ready-check/` → `{"message":"Ready"}`
- [ ] 浏览器登录教师账号，能看到原有班级与学生
- [ ] 手机端录音 → 提交 → 评分返回（验证 ASR + ARK 链路在新机可用）
- [ ] `docker ps` 四个容器均 healthy
- [ ] `bash scripts/prod-rls-selfcheck.sh` 通过
- [ ] 观察 30 分钟：错误日志无新增 5xx

## 3. 回滚（任一验证失败）

```bash
# 3.1 把 8 个键改回旧机
for kv in SERVER_HOST=49.232.156.221 SERVER_USER=ubuntu \
  DEPLOY_PATH=/opt/speakup COMPOSE_PROJECT_NAME=speakup \
  FRONTEND_HOST=https://outman.website APP_PORT=80 TLS_DOMAIN=outman.website ; do
  printf '%s' "${kv#*=}" | /opt/homebrew/bin/gh secret set "${kv%%=*}" --env production
done
printf '%s' "$(cat ~/.ssh/esa_ops)" | /opt/homebrew/bin/gh secret set SERVER_SSH_KEY --env production

# 3.2 DNS 改回 49.232.156.221
# 3.3 旧机恢复服务
ssh esa-prod 'cd /opt/speakup && docker compose -f compose.yml start backend frontend'
```

旧机在割接窗口内**只停写、不删数据**，回滚是分钟级。

## 4. 转正后收尾

1. 旧机保持停机只读 **2 周**（建议 `docker compose stop backend frontend`，DB 保留）
2. 仓库变量 `HEALTH_URL` 改到正式域名
3. 新建 `test` 环境（原测试域名保留），使用**独立 SECRET_KEY 与独立 ARK key**，
   避免测试环境继续借用生产令牌和真实计费额度
4. 备份上 TOS 确认连续 3 天成功
5. 两周后释放旧机：`pg_dump` 最后一次存档到 TOS → 关机 → 退订

## 5. 已知风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| ICP 备案未迁 | 火山可能拦截 80/443，或合规风险 | 割接前完成接入备案变更 |
| DNS 缓存 | 部分地区仍指向旧机 10–30 分钟 | TTL 600；旧机保持可服务 |
| 录音文件丢失 | 割接窗口内的上传 | 停写期间不接受新上传；增量同步含 audio 全量校验 |
| 新机单点 | 无冗余 | 旧机 2 周冷备 + 每日 TOS 备份 |
