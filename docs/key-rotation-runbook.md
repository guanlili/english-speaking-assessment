# 密钥轮换手册 / Key rotation runbook

> 位置：所有密钥只存在于两处——GitHub 仓库 Secrets（部署时由流水线写入生产 `.env`）与生产服务器 `/opt/speakup/.env`。**任何情况下不进仓库、不进聊天记录、不进截图。**轮换后旧值立即视为泄露处理。

> All secrets live in exactly two places: GitHub repository Secrets (written into the production `.env` by the deploy pipeline) and the server's `/opt/speakup/.env`. They never enter the repo, chats, or screenshots. Treat old values as compromised once rotated.

## 轮换速查 / Quick reference

| 密钥 | 作用 | 轮换影响 | 建议周期 |
|---|---|---|---|
| `SECRET_KEY` | JWT 签名 | **全员登出**（所有 token 失效，重新登录即恢复） | 季度，或疑似泄露立即 |
| `POSTGRES_PASSWORD` | 数据库 | 需与 `.env` 同步改并重启容器；改错会拖垮后端 | 半年 |
| `ARK_API_KEY` | ASR/LLM 评分与出题 | 旧 key 失效则评分失败（队列堆积告警会响） | 按火山侧策略（泄露立即） |
| `ARK_TTS_API_KEY` | 标准音合成（vei 网关） | 失效则 TTS 返回 503，上传现成音频不受影响 | 按火山侧策略 |
| `SMTP_PASSWORD` | 告警/邮件 | 失效则告警邮件发不出（页面红黄标不受影响） | 按邮箱服务商 |
| 部署 SSH 私钥（runner→服务器） | 流水线部署 | 轮换需服务器换公钥 + 更新对应 Secret，否则部署失败 | 半年 |
| `FIRST_SUPERUSER_PASSWORD` | 超管初始密码 | 仅影响种子创建，已建账号走平台内改密 | 一次性（部署后改掉即可） |

## 操作步骤 / Procedures

### 1. `SECRET_KEY`（JWT 签名密钥）

1. 生成新值：`openssl rand -base64 48`。
2. GitHub 仓库 Settings → Secrets and variables → Actions → 更新 `SECRET_KEY`。
3. 推送一次 master（或重跑最近一次 deploy workflow）触发重新部署，流水线重写 `.env` 并重启后端。
4. 验证：旧 token 调任意接口返回 401；超管重新登录成功。
5. 生效即全员登出，**选择教学低峰执行**，提前一天通知教师。

### 2. `POSTGRES_PASSWORD`

1. 在 db 容器内改角色密码：`docker exec <db> psql -U postgres -c "ALTER USER postgres PASSWORD '新值';"`。
2. 立即更新 GitHub Secret `POSTGRES_PASSWORD` 并触发部署（两步之间越短越好，期间后端可能报连接失败）。
3. 验证：`docker exec <backend> python -c "from app.core.db import engine; from sqlalchemy import text; print(engine.connect().execute(text('select 1')).scalar())"`。
4. 回滚：把角色密码改回旧值即可（`.env` 未变时）。

### 3. 火山方舟 / vei 网关密钥

1. 在火山控制台新建 API Key（旧 key 先保留，切换验证后再禁用）。
2. 更新对应 Secret（`ARK_API_KEY` / `ARK_TTS_API_KEY`）并触发部署。
3. 验证：大盘「性能与稳定」区 ASR/LLM/TTS 失败率为 0 且有新调用量；或发起一次跟读作答。
4. 验证通过后在控制台**禁用旧 key**。

### 4. `SMTP_PASSWORD`

1. 邮箱服务商侧改密码（或新建授权码）。
2. 更新 Secret `SMTP_PASSWORD` 并触发部署。
3. 按告警 runbook（`docs/runtime-observability.md`）在容器内发一封测试邮件验证。

### 5. 部署 SSH 密钥

1. 本地生成新对：`ssh-keygen -t ed25519 -f deploy_key_$(date +%Y%m)`。
2. 服务器 `~/.ssh/authorized_keys` 先**追加**新公钥（保留旧行），更新 GitHub Secret 后重跑部署验证成功。
3. 确认新 key 可用后，从 `authorized_keys` 删除旧行。

## 通用检查 / General checklist

- 轮换完成的标准 = 生产验证通过 + 旧值已禁用/失效，两件事都做才算闭环。
- 每次轮换在本文档追加一行记录（日期 + 密钥名 + 执行人），不记值本身。
- 怀疑任何密钥泄露时：优先级为「立即轮换 → 排查访问日志 → 评估影响面」，不要先排查再轮换。
