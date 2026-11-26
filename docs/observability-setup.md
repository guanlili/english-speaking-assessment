# 可观测性开通手册（Sentry 错误上报 / SMTP 告警邮件）

> 两条链路的**代码与部署管线均已就绪**，只差在 GitHub Secrets 填值。
> 本手册是唯一操作步骤——不需要改任何代码，填完手动运行一次 `Deploy Production` 部署即生效（push master 只跑 CI，不自动部署）。

## 一、错误监控（自建 GlitchTip，Sentry 协议）

**现状**：后端 `app/core/observability.py` 与前端 `main.tsx` 均已按需初始化——未配 DSN 时 SDK 不加载/不打包，零成本；
部署链 `Secrets → generate-deploy-env.sh → 生产 .env / compose build args → vite` 全通。
监控端为遗留机 `49.232.156.221` 上的自建 GlitchTip；ESA 组织与 `esa-backend` / `esa-frontend` 两个项目已建好。
盘点、密钥、网络诊断与待决策端点方案见 `docs/qa/20261128/glitchtip/REPORT.md`。

**待办（端点方案定稿后）**：

1. 确定 ingest 入口：后端可走 volc-belp 到监控机的 SSH 隧道（`127.0.0.1:8090`）；前端必须是学生浏览器可达的公网 HTTPS 子域反代。
2. 填入 GitHub Secrets（DSN 形如 `https://<公钥>@<可达主机>/<项目id>`）：
   ```bash
   printf '<后端 DSN>' | gh secret set SENTRY_DSN --repo guanlili/english-speaking-assessment --env production
   printf '<前端 DSN>' | gh secret set VITE_SENTRY_DSN --repo guanlili/english-speaking-assessment --env production
   ```
3. 手动运行 `Deploy Production` workflow（`deploy-prod.yml`）触发部署。

**验证**：部署后后端容器内 `sentry_sdk.capture_message(...)`、前端控制台抛错，分别在 GlitchTip 两个项目看到事件；详见 QA 报告 5.2。

**注意**：DSN 公钥是公开标识（前端 DSN 会打进 bundle），不是密钥；SDK 默认 `send_default_pii=False`，不传用户/IP/Cookie/请求体。当前生产到 49.232:8090 网络不通，端点未打通前 Secrets 保持空值，SDK 不上报。

## 二、SMTP 告警邮件（队列堆积/成本告警）

**现状**：告警触发逻辑已上线（管理面板红黄标恒生效；邮件通道仅在 SMTP 配置后才发）。
触发条件：评分队列堆积（ oldest_queued_age_s 超阈值）→ 发 `COST_ALERT_EMAIL`。

**开通步骤**：

1. 准备一个发件邮箱（推荐企业邮箱或 QQ/163 的 SMTP 授权码，不要用个人密码）
2. 填四个 Secrets（示例为 QQ 邮箱）：
   ```bash
   printf 'smtp.qq.com'      | gh secret set SMTP_HOST
   printf '你的QQ号@qq.com'   | gh secret set SMTP_USER
   printf 'SMTP授权码'        | gh secret set SMTP_PASSWORD
   printf '你的QQ号@qq.com'   | gh secret set EMAILS_FROM_EMAIL
   ```
   163 邮箱把 HOST 换成 `smtp.163.com`；企业邮箱按服务商文档。
3. 收件人（告警发到哪）：
   ```bash
   printf '收件邮箱' | gh secret set COST_ALERT_EMAIL
   ```
4. 触发一次部署

**验证**：管理面板 → 平台大盘 → 若当前队列无堆积，红黄标为绿色即链路自检通过；
邮件通道真实触发需要队列真实堆积（或临时把 SCORING_WORKERS 设 0 制造一次堆积验证后再改回）。

**注意**：`SMTP_USER/EMAILS_FROM_EMAIL` 同时服务「新建账号通知邮件」——开通后平台建号会自动给学生/教师发通知，确认这是期望行为（免费额度内）。

## 附：当前 Secrets 待填清单速查

| Secret | 用途 | 状态 |
|---|---|---|
| SENTRY_DSN | 后端错误上报（GlitchTip） | ⬜ 待端点方案定稿后填（本手册一） |
| VITE_SENTRY_DSN | 前端错误上报（GlitchTip） | ⬜ 待公网 HTTPS 入口就绪后填（本手册一） |
| SMTP_HOST/USER/PASSWORD | 发件通道 | ⬜ 待填（本手册二） |
| EMAILS_FROM_EMAIL | 发件人地址 | ⬜ 待填（同上） |
| COST_ALERT_EMAIL | 告警收件人 | ⬜ 待填（同上） |
| FIRST_OPERATOR_EMAIL/PASSWORD | 平台运营独立凭据 | ⬜ 建议商用前拆（当前沿用首超管，见 B3 说明） |
