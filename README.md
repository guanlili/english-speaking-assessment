# Charcoal 开口说 · 英语口语学习平台

> 品牌更名：SpeakUp → **Charcoal**（暂定名，2026-10；规避与市面雅思口语平台重名）。纯展示层改名，域名、账号、登录均不受影响；正式名待结合「全题型英语模考学习平台」新定位定稿。

基于 [guanlili/lili-full-stack](https://github.com/guanlili/lili-full-stack) 创建的独立项目仓库。

## 当前状态

平台已上线生产。PRD 三阶段功能全部就绪并有后续增强：学生端全流程（学号账号登录、课堂码进入、文章朗读/听句复述/情景问答/题目说明四题型、发布快照、模考逐题限时计时）、词汇学习模块（词库、发布、看义/听音拼词、多任务多轮练习、限时测验、错词本、AI 学情）、五级词库分级数据源、教师面板与题库三层结构（主题 → 篇目 → 句子）、管理端内容管理、激励层（星级/XP/连胜/徽章）与进步轨迹。评分引擎可选 `mock`（离线）或 `ark`（火山方舟真实转写 + LLM rubric 模拟分）。

### 演示入口（本地 `docker compose up -d` 后）

| 入口 | 地址 | 说明 |
|------|------|------|
| 学生进入课堂 | http://localhost:5173/j/DEMO01 | 学号账号登录后进入（本地演示账号 `student` / `demo1234`）|
| 学生首页 | http://localhost:5173/home/DEMO01 | 今日练习与词汇任务入口 |
| 学生结果页 | http://localhost:5173/p/DEMO01/result | 每题转写与参考反馈 |
| 学生成长 | http://localhost:5173/me/DEMO01 | 参考分与进步轨迹 |
| 词汇学习 | http://localhost:5173/vocab/DEMO01 | 词库浏览、自主练习与错词本 |
| 教师面板 | http://localhost:5173/t/DEMO01 | 名单、发布、结果、录音回放 |
| 内容管理 | http://localhost:5173/admin（管理员登录） | 篇目/情景问答/单元/五级词库/公共词库/课堂 |

> ⚠️ `scripts/reset-demo.sh` 会**清空全部学生、作答、会话与音频**（仅保留内容与 DEMO01 课堂码）。只在交付前的一次性演示环境使用，不要在任何有真实数据的库上运行。

默认评分引擎为离线 mock（`SCORING_PROVIDER=mock`）。接入真实转写：方舟控制台开通模型后，在 `.env` 设置 `ARK_API_KEY` 并把 `SCORING_PROVIDER` 改为 `ark`。

- 本地配置：`.env`（已忽略，不提交）；首次克隆可运行 `bash scripts/init-project.sh "英语口语评测平台"`，然后将 `COMPOSE_PROJECT_NAME` 设为 `english-speaking-assessment`。
- 开发规范：[AGENTS.md](AGENTS.md)、[CLAUDE.md](CLAUDE.md)、[AI_RULES.md](AI_RULES.md)。
- 生产部署已启用：push 到 `master` → CI（lint + 测试 + 客户端一致性）→ 自动部署，回滚走 revert，细节见下文「生产部署」。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + SQLModel + PostgreSQL |
| 包管理 | uv（后端）/ npm（前端）|
| 认证 | JWT + 邮件找回密码 |
| 数据库迁移 | Alembic |
| 前端框架 | React 19 + TypeScript + Vite |
| 样式 | TailwindCSS v4 + Radix UI + Lucide React |
| 数据请求 | TanStack Query + TanStack Router |
| 代码规范 | Ruff + ty（后端）/ Biome（前端）|
| 容器 | Docker Compose（nginx 内置 /api 代理，无 Traefik）|
| CI/CD | GitHub Actions：lint + 测试通过后 → server-side git pull + docker compose up |

---

## 本地开发

```bash
# 启动所有服务（自动加载 compose.override.yml）
docker compose up --build

# 启用热更新（后端 --reload + 前端 vite HMR，推荐日常开发用这个）
docker compose watch

# 停止
docker compose down
```

本地开发时前端跑的是 vite dev server（5173 端口，支持热更新），生产镜像才是 nginx 静态托管。

---

## 新功能开发流程

**权威版本在 [CLAUDE.md](CLAUDE.md)**（Claude Code 每次会话自动加载，人和 AI 都照它执行），此处只留概览，避免两份文档漂移：

> 后端加模型/CRUD/路由 → Alembic 迁移 → `cd frontend && npm run generate-client` 同步客户端 → 前端加页面。

编码规范（命名、类型、禁止模式）见 [AI_RULES.md](AI_RULES.md)。

---

## Claude Code 自定义指令

项目内置了 4 个自定义斜杠命令，在 Claude Code 中可直接使用：

| 指令 | 用途 |
|------|------|
| `/new-feature <名称>` | 自动创建完整功能模块（后端 model + crud + route + 前端页面） |
| `/migration <描述>` | 生成并应用 Alembic 数据库迁移 |
| `/generate-client` | 重新生成前端 API 客户端 |
| `/upgrade-deps` | 升级所有依赖包（uv + npm）|

示例：

```
/new-feature order
```

Claude Code 会按标准流程自动创建订单模块的全部后端和前端代码。

仓库还内置了团队共享的权限白名单（`.claude/settings.json`）：日常开发的高频命令
（docker compose、npm run、uv run、git 只读、gh 查看 CI 等）已预授权，克隆即用，
少弹大部分权限框；破坏性操作（`down -v`、push、commit 等）仍会请求确认。
注意边界：`uv run *` 和 `docker compose exec backend *` 实质上允许 AI 免确认执行任意代码——
这是"减少弹框"的有意取舍，团队成员应知情；要求更严格的项目可自行收窄白名单。
个人偏好写在 `.claude/settings.local.json`（已被 gitignore，不入库）。

---

## 生产部署

### 首次部署

**1. 配置 GitHub Secrets**

在仓库 **Settings → Secrets and variables → Actions** 添加以下 12 个必填 Secret：

| Secret | 必改 | 说明 | 示例 |
|--------|:----:|------|------|
| `SERVER_HOST` | | 服务器 IP | `你的服务器IP` |
| `SERVER_USER` | | SSH 用户名 | `root` |
| `SERVER_SSH_KEY` | | SSH 私钥（完整内容）| `-----BEGIN...` |
| `DEPLOY_PATH` | ✅ | 服务器部署路径，每个项目不同 | `/mnt/datadisk0/项目名` |
| `COMPOSE_PROJECT_NAME` | ✅ | Docker Compose 项目名（容器前缀），同服务器各项目不能重复 | `order-mgmt` |
| `APP_PORT` | ✅ | 前端暴露端口，同服务器上各项目不能重复 | `8083` |
| `FRONTEND_HOST` | ✅ | 前端完整地址，与 `APP_PORT` 对应 | `http://你的服务器IP:8083` |
| `SECRET_KEY` | ✅ | JWT 签名密钥，每个项目必须唯一 | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `PROJECT_NAME` | ✅ | 项目名称（显示在邮件等处）| `我的项目` |
| `POSTGRES_PASSWORD` | | 数据库密码，建议各项目不同 | 自定义强密码 |
| `FIRST_SUPERUSER` | | 初始管理员邮箱 | `admin@example.com` |
| `FIRST_SUPERUSER_PASSWORD` | | 初始管理员密码 | 自定义 |

> `BACKEND_CORS_ORIGINS` 自动与 `FRONTEND_HOST` 保持一致，无需单独配置。

另有以下**可选** Secret（不设置则用默认值）：

| Secret | 默认 | 说明 |
|--------|------|------|
| `USERS_OPEN_REGISTRATION` | `false` | 是否开放自助注册。生产默认关闭（管理员在后台建账号）；产品需要用户自行注册时设为 `true` |
| `WORKERS` | `1` | 后端 worker 进程数，大流量项目可调至 CPU 核数×2+1 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_TLS` / `SMTP_SSL` | 空 / `587` / `True` / `False` | SMTP 服务器配置。**`SMTP_HOST` 为空 = 邮件功能整体关闭** |
| `SMTP_USER` / `SMTP_PASSWORD` | 空 | SMTP 认证（无认证的内部中继可留空） |
| `EMAILS_FROM_EMAIL` | `info@example.com` | 发件人地址（邮件功能开启时建议设置真实地址） |

**未配置邮件（`SMTP_HOST` 为空）时的实际行为**：

- 创建用户：成功，不发欢迎邮件（管理员建账号时密码线下告知）
- 找回密码：接口仍返回成功文案（防账号枚举），但**不会发出任何邮件**，服务端日志会记 warning 提醒；用户实际无法自助重置密码，需要管理员在后台改密
- 测试邮件接口（`/utils/test-email/`）：返回明确错误

所以**产品需要"忘记密码"自助找回时，SMTP 相关 Secret 必须配齐**。

**2. 服务器上 clone 一次**

```bash
git clone git@github.com:guanlili/<项目名>.git $DEPLOY_PATH
```

只需做一次。之后 push 到 `master` 即自动触发：**CI（后端 lint + 测试、前端 lint + 构建、前后端客户端一致性）→ 全部通过才部署** → checkout 到该次 CI 验证过的 commit → 从 Secrets 生成 `.env`（base64 中转 + 校验通过后原子替换，特殊字符安全、日志不落值）→ 构建镜像 → 跑 Alembic 迁移 → 重启容器 → 就绪检查（含数据库）验证 → 清理旧镜像。

**部署入口与并发**：

- 自动部署只来自 `master` 的 push；手动触发（workflow_dispatch）也仅限 `master` 分支，PR 只跑检查不部署。
- 所有指向生产的部署共用一把并发锁，不自动取消正在进行的部署。不要依赖任务排队顺序：每次部署在服务器 fetch 后比较本次通过 CI 的提交与 `origin/master`，过期任务（包括旧任务重跑）直接跳过。最新提交必须通过自己的 CI 才能部署；若检查失败，保留当前线上版本。回滚使用 revert 生成新的 master 提交。

部署配置生成脚本：`scripts/generate-deploy-env.sh`。候选文件 `.env.new` 同时用于 Compose 插值与容器环境校验，首次部署不依赖旧 `.env`；校验通过后才原子替换。配置文件权限为 600，失败时清理候选文件。

本地可运行 `python3 scripts/test_deploy.py` 验证首次部署、旧配置隔离、特殊字符和必填校验（需要 Docker Compose CLI，无需启动容器）。就绪检查使用独立连接，对连接和查询设置合计 3 秒的超时；数据库不可用返回 503，恢复后探测恢复。Docker 的 unhealthy 状态本身不会触发自动重启。

> `.env` 每次部署都由 workflow 从 Secrets 重新生成，GitHub Secrets 是唯一配置源。**`.env` 永远不要提交到 git**（已被 `.gitignore` 忽略）。

### HTTP / HTTPS 策略

按项目性质二选一，**立项时就确定**：

| 项目性质 | 方案 |
|---------|------|
| 内网工具、临时演示（不用麦克风/摄像头等 API） | `http://IP:端口`（模板默认），够用，不折腾 |
| 需要麦克风、摄像头、剪贴板、地理定位、通知等**安全上下文 API** 的项目 | **必须 HTTPS，哪怕是临时远程演示**（见下） |
| 正式上线、面向真实用户 | **必须 HTTPS**，按下面三步走 |

HTTP 明文意味着 JWT token 和登录密码裸奔公网、浏览器标"不安全"。另外**普通 HTTP 的 IP 地址（非 localhost）不是"安全上下文"**——`getUserMedia`（麦克风/摄像头）、剪贴板写入、Notification 等浏览器 API 在 `http://IP:端口` 下会被浏览器直接禁用，页面写 `navigator.mediaDevices` 拿到的是 `undefined`。这类功能的项目给客户做远程演示时也必须走 HTTPS（本机 `http://localhost` 例外，它算安全上下文）。

**正式上线三步（前置条件：已备案域名）：**

1. **域名解析**：加一条 A 记录 `项目名.你的域名.com → 服务器 IP`。国内服务器要求域名已 ICP 备案——**备案需 1~3 周，立项时就启动**；子域名跟随主域名备案，不用重复办。优先用客户自己已备案的域名（备案主体在客户侧，域名归属也更合理）。
2. **服务器级 Caddy**（整台服务器装一次，所有项目共享；TLS 必须在服务器层做，因为 443 端口只有一个）：
   ```
   # apt install caddy 后编辑 /etc/caddy/Caddyfile，每个项目加 3 行：
   项目名.你的域名.com {
       reverse_proxy localhost:8083   # 对应该项目的 APP_PORT
   }
   ```
   `systemctl reload caddy` 生效，证书自动申请续期。安全组需放行 80/443。
3. **改 Secret**：`FRONTEND_HOST` 改为 `https://项目名.你的域名.com`，push 触发重新部署即可（CORS 自动跟随，代码零改动）。

### 数据库备份

生产数据只存在 Docker volume 里，服务器磁盘损坏即全部丢失。**部署流水线会自动注册每日备份 cron**（每天 3:30，保留 14 天，`backups/` 目录），**不要手动再注册备份 crontab**（会双跑双清理）。备份内容：

- `app-*.sql.gz`：pg_dump 全量数据库；
- `env-*.env`：当次 `.env` 快照（SECRET_KEY、数据库密码、方舟密钥——灾后重建必需）。

失败排查：备份失败会追加一行时间戳到 `backups/backup-failure.log`。

> ⚠️ 备份仍只落在服务器本地盘：服务器整体报废时数据与备份同归于尽。异地容灾（对象存储/另一台机器）需要提供云凭证后另行配置。

恢复（用户名/库名以服务器 `.env` 中的 `POSTGRES_USER`/`POSTGRES_DB` 为准）：

```bash
gunzip -c 备份文件.sql.gz | docker compose exec -T db psql -U $POSTGRES_USER $POSTGRES_DB
```

### 回滚

CI 挡得住挂掉的构建，挡不住"测试全绿但业务逻辑错了"的版本。上线后发现坏版本：

**常规回滚（推荐）**——revert 后走正常流水线，有 CI 门槛兜底：

```bash
git revert <坏提交>   # 或 git revert <坏起点>..<坏终点> 批量撤销
git push              # 自动触发 CI → 部署 → 健康检查
```

**紧急回滚（生产事故，等不了 CI 的几分钟）**——直接在服务器上退：

```bash
ssh 服务器 "cd 部署路径 && git reset --hard <上一个好提交> && docker compose -f compose.yml up -d --build"
```

> 紧急回滚只是止血：master 上坏提交还在，下次 push 会把它重新部署上去。
> 止血后必须回到常规流程 revert + push，让远端历史与线上一致。

**数据库迁移注意**：回滚代码不会回滚 Alembic 迁移。坏版本若只是**加**了表/列，旧代码通常兼容，直接回滚代码即可；若做了破坏性变更（删列、改类型），优先前向修复（fix + push）而不是 `alembic downgrade`——降级操作有数据丢失风险，动手前先做一次备份。

---

## 项目结构

```
english-speaking-assessment/
├── .claude/
│   └── commands/          # Claude Code 自定义斜杠命令
├── scripts/
│   └── init-project.sh    # 新项目一键初始化（改名 + 密钥随机化）
├── .env.example           # 环境变量模板（复制为 .env 使用）
├── .env                   # 实际配置（gitignore 忽略，永不提交；生产由 Secrets 生成）
├── AI_RULES.md            # AI 开发规范（技术约定）
├── CLAUDE.md              # 项目上下文（Claude Code 启动时自动读取）
├── compose.yml            # 生产 Docker Compose
├── compose.override.yml   # 本地开发覆盖配置
├── backend/
│   └── app/
│       ├── api/routes/    # FastAPI 路由
│       ├── core/          # 配置、认证、数据库
│       ├── alembic/       # 数据库迁移文件
│       ├── models.py      # SQLModel 数据模型
│       └── crud.py        # 数据库操作
└── frontend/
    ├── scripts/           # generate-client.sh / regen-lockfile.sh
    └── src/
        ├── routes/        # 页面（_layout/ 下需要登录）
        ├── components/    # 组件
        ├── hooks/         # 自定义 hooks
        └── client/        # 自动生成的 API 客户端（勿手动修改）
```

---

## 设计取舍（有意不做的东西）

> 本节记录沿用自模板、本仓库**刻意省略**的实践及原因。补齐它们之前请先读这里——多数"缺失"是权衡后的决定，不是疏漏。

| 不做什么 | 为什么 |
|---------|--------|
| 前端组件测试（vitest） | 纯逻辑（lib/）用 node --test 覆盖；组件层暂不做，前端质量门槛 = tsc + biome + E2E 冒烟 + 后端 API 测试兜底 |
| dependabot / renovate | 小团队没精力处理持续的升级 PR 噪音。用季度 `/upgrade-deps` 集中升级 + 验证代替；每周 audit.yml 定时跑 pip-audit / npm audit 作发现渠道 |
| pre-commit 钩子 | CI 是唯一质量门槛。本地钩子对 AI 驱动的开发是摩擦（AI 每次提交都会被格式化钩子打断），且和 CI 重复 |
| staging 环境 | 单服务器多项目、快速交付定位。staging 的维护成本大于收益；重要变更靠 CI 门槛 + 部署后健康检查兜底 |
| JWT refresh token | 8 天 access token + localStorage 是简单性取舍，适合工具型产品。对安全有更高要求的项目再升级会话机制 |
| 登录接口限流 | 不在代码层加依赖。`rate_limit` **不是 Caddy 内置模块**——官方发行版不带，需要用 `xcaddy` 自行构建含 `caddy-ratelimit` 插件的二进制（或换用云防火墙/WAF 做限流）；本仓库不提供也不默认包含，正式上线且暴露公网时再评估 |
| 重置密码 token 一次性失效 | token 48 小时内可重复使用（改完密码不作废）。工具型项目风险低；高安全要求的项目可把 token 绑定当前密码 hash（密码一改即失效） |
| 生产环境隐藏 `/docs`、`/redoc` | API 文档公开对内网工具是便利。正式上线面向公网的项目建议关闭（`ENVIRONMENT=production` 时设 `docs_url=None`）或在 Caddy 层加 basic auth |
| Kubernetes / 多机编排 | 单服务器 docker compose 覆盖当前所有项目规模。规模到了再迁移，不预支复杂度 |
