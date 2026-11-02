# 可观测性开通手册（Sentry 错误上报 / SMTP 告警邮件）

> 两条链路的**代码与部署管线均已就绪**，只差在 GitHub Secrets 填值。
> 本手册是唯一操作步骤——不需要改任何代码，填完跑一次部署（或等下次自动部署）即生效。

## 一、Sentry 前端错误上报

**现状**：`frontend/src/main.tsx` 已按需初始化（未配 DSN 时 Sentry 不打包进首屏，零成本）；
部署链 `Secrets → generate-deploy-env.sh → compose build args → vite` 全通（PR#221 接线，CI 校验键一致）。

**开通步骤**：

1. 注册 [sentry.io](https://sentry.io)（免费档 5K errors/月够用）或自托管实例
2. 创建项目，平台选 **React**，拿到 DSN（形如 `https://xxx@oXXX.ingest.sentry.io/YYY`）
3. 填入 GitHub Secret：
   ```bash
   # 本地终端执行（或仓库 Settings → Secrets → Actions 页面添加）
   printf 'https://你的DSN' | gh secret set VITE_SENTRY_DSN --repo guanlili/english-speaking-assessment
   ```
4. 触发一次部署（push 任意 commit 或手动 rerun 最新 deploy run）

**验证**：部署完成后打开网站 → 浏览器控制台执行 `setTimeout(() => { throw new Error('sentry-test') }, 100)`
→ Sentry 后台几秒内出现该事件。

**注意**：DSN 是公开标识不是密钥（会打进前端 bundle），泄露无风险；但想换项目时改 Secret 重新部署即可。
国内访问 sentry.io 的 ingest 端点偶有抖动——若上报不稳定，考虑自托管或选用国内同类（如 FrontJS），代码侧只需换 DSN。

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
| VITE_SENTRY_DSN | 前端错误上报 | ⬜ 待填（本手册一） |
| SMTP_HOST/USER/PASSWORD | 发件通道 | ⬜ 待填（本手册二） |
| EMAILS_FROM_EMAIL | 发件人地址 | ⬜ 待填（同上） |
| COST_ALERT_EMAIL | 告警收件人 | ⬜ 待填（同上） |
| FIRST_OPERATOR_EMAIL/PASSWORD | 平台运营独立凭据 | ⬜ 建议商用前拆（当前沿用首超管，见 B3 说明） |
