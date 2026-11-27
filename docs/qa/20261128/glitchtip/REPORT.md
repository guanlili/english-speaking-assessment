# GlitchTip 错误监控接线报告 — ESA

- 执行时间：2026-11-27 CST（UTC 2026-11-26 23:31–23:55）
- 监控端（GlitchTip 自建）：遗留机 `49.232.156.221`（`esa-prod`，ubuntu），compose 目录 `~/glitchtip`；**不是**生产 app 机
- 生产 app 机：`volc-belp` 115.190.122.24，目录 `/srv/english-speaking-assessment`
- 范围：代码侧最小接入 + 项目/密钥准备 + 网络与待办清单；**未重启生产容器、未改生产网络、未改生产 `.env` 无关配置**
- 基线提交：`4011db1a61e6c22d58c7e3a74a9ab3527709bdc4`

## 结论速览

| 项 | 状态 | 说明 |
|----|------|------|
| GlitchTip compose 容器 | ✅ 在跑 | `glitchtip-web` / `glitchtip-postgres-1` / `glitchtip-valkey-1`，Up 2 days |
| 监听地址 | ⚠️ 仅 `127.0.0.1:8090` | web 容器端口映射 `127.0.0.1:8090->8000`，本机 `curl 127.0.0.1:8090/` 返回 200 |
| ESA 项目 | ✅ 已建 | 组织 `esa`(id 3)；`esa-backend`(id 6, python)、`esa-frontend`(id 7, javascript-react) |
| 项目密钥 | ✅ 已取 | 见下方 DSN 表；密钥为 ingest 公钥，不写仓库，只进 Secrets |
| ingest 自测 | ✅ 本机通过 | 两项目各收到 1 条自测事件并落库（见 3.3） |
| volc-belp → 8090 网络 | ❌ 不可达 | TCP 8090 连接超时（curl rc=28，5002ms；TCP rc=124）；22 通、ICMP 5.8ms |
| 后端 SDK 代码 | ✅ 已就绪 | DSN 为空时不初始化；显式 `send_default_pii=False` |
| 前端 SDK 代码 | ✅ 已就绪 | DSN 为空时不打包；@sentry/react v11 默认不采集 PII（该版本无显式 PII 开关） |
| 生产 `.env` / Secrets | ⬜ 待端点决策 | `SENTRY_DSN=""` / `VITE_SENTRY_DSN=""` 保持空；端点方案未定前不写入不可达地址 |
| 告警出口 | ⚠️ 未配置 | GlitchTip 侧无 SMTP、无告警规则；事件先落库，邮件/Webhook 告警待后续配置 |

## 1. 监控端盘点（只读 + 建项目）

### 1.1 容器与监听

```
glitchtip-web          Up 2 days   127.0.0.1:8090->8000/tcp
glitchtip-postgres-1   Up 2 days   5432/tcp（内网）
glitchtip-valkey-1     Up 2 days   6379/tcp（内网）
```

- 本机健康检查：`curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/` → `200`。
- `~/glitchtip/.env` 仅含 `SECRET_KEY`、`DB_PASSWORD`；无 SMTP 配置。
- 环境变量：`ENABLE_ADMIN=False`、`ENABLE_USER_REGISTRATION=False`、`GLITCHTIP_DOMAIN=http://glitchtip:8000`（容器内别名，仅内部使用，不能作为对外 ingest 地址）。

### 1.2 已建项目与密钥

| 项目 | GlitchTip id | 平台 | 公钥（hex，无连字符） |
|------|--------------|------|------------------------|
| `esa-backend` | 6 | python | `79cac76c63fb4d37ac2a0d4473c3ef4f` |
| `esa-frontend` | 7 | javascript-react | `db6f0c3dca15479198fae4860e2b4dff` |

组织 `esa`(id 3)，现有超管 `ops@outman.press` 已加为 Owner。

DSN 格式：`<scheme>://<公钥hex>@<可达主机[:端口]>/<项目id>`。主机段取决于最终端点方案（见第 4 节），当前**未定**，因此不把半成品 DSN 写进生产配置。

### 1.3 ingest 自测（本机回环，不经过生产网络）

在 `esa-prod` 本机向 `127.0.0.1:8090` 直接 POST store 接口：

| 项目 | HTTP | 落库标题 | first_seen (UTC) |
|------|------|----------|-------------------|
| esa-backend (6) | 200 | `esa-backend wiring self-test 2026-11-27` | 2026-11-26 23:50:08 |
| esa-frontend (7) | 200 | `esa-frontend wiring self-test 2026-11-27` | 2026-11-26 23:50:13 |

结论：GlitchTip 项目、密钥、入库链路在监控端本机是通的；未从生产 app 机回传过事件。

## 2. 代码侧改动（独立分支，随最终统一部署上线）

| 文件 | 改动 |
|------|------|
| `backend/app/core/observability.py`（新增） | 集中 `init_sentry()`：DSN 为空或 `ENVIRONMENT=local` 不初始化；`environment` 按环境标签；`traces_sample_rate=0.1`；显式 `send_default_pii=False`（不传用户/IP/Cookie/Authorization）。 |
| `backend/app/main.py` | 去掉模块内联 `sentry_sdk.init`，改为调用 `init_sentry()`。评分 worker 是后端进程内线程池，复用同一初始化，无需单独接入。 |
| `frontend/src/main.tsx` | `Sentry.init` 配置 `environment` / `tracesSampleRate=0.1`；@sentry/react v11 默认不采集 PII（`sendDefaultPii` 选项在 v11 已移除，不可传）；未配 DSN 仍动态 import、不进首屏。 |
| `.env.example` | DSN 注释更新为自建 GlitchTip 口径；注明前端 DSN 必须是学生浏览器可达的公网 HTTPS 地址。 |

PII 边界：SDK 侧不传用户标识、IP、Cookie、认证头；GlitchTip 项目侧 `scrub_ip_addresses=True`（服务端再匿名化 IP）。当前 sentry-sdk 版本（2.x）初始化参数不含请求体开关，请求体不主动附加；如需更严的 body 剥离，后续在 ingest 侧 PII scrubber 配置。

## 3. 网络诊断（volc-belp → 49.232.156.221）

2026-11-26 23:3x 从生产机实测：

```
ping 49.232.156.221            2 packets received, 0% loss, rtt 5.834ms
TCP 49.232.156.221:22          open
TCP 49.232.156.221:8090        closed/filtered（timeout，rc=124）
curl http://49.232.156.221:8090/  curl: (28) Connection timed out after 5002ms，http_code=000
```

- 根因双重：① web 只绑定 `127.0.0.1:8090`，公网网卡上本就没有监听；② 云安全组未放行 8090。
- 本次**未改**生产网络、未动安全组、未在 49.232 新增公网监听。
- 既有项目佐证：`yujee-web` 的历史事件是 Next.js 服务端报错（`node:_http_server`、`.next/server`），由同机后端进程走回环上报；目前不存在浏览器可达的公网 ingest 入口。

## 4. 待用户决策的端点方案

### 方案 A：后端走 SSH 隧道（快，只覆盖后端）

- 在 volc-belp 以 systemd/ autossh 维持一条到 `esa-prod` 的本地转发：`127.0.0.1:8090 → 127.0.0.1:8090`。
- 后端 DSN：`http://79cac76c63fb4d37ac2a0d4473c3ef4f@127.0.0.1:8090/6`
- 局限：前端 SDK 在学生浏览器里运行，`127.0.0.1` 指向学生自己设备，**前端事件无法上报**。

### 方案 B：公网子域反代（推荐，前后端都覆盖）

- 在 49.232 现有 `speakup-frontend-1` nginx 上加一个子域（如 `glitchtip.outman.press`）反代到 `127.0.0.1:8090`；DNS 解析 + TLS 证书（主机已有 acme 容器）；安全组放行 443。
- 后端 DSN：`https://79cac76c63fb4d37ac2a0d4473c3ef4f@glitchtip.outman.press/6`
- 前端 DSN：`https://db6f0c3dca15479198fae4860e2b4dff@glitchtip.outman.press/7`
- 注意：前端 DSN 会打进学生浏览器 bundle，公钥本就是公开标识；但 ingest 入口必须 HTTPS，避免事件明文走公网。

### 方案 C：8090 直接公网裸露（不推荐）

- 安全组放行 8090 + 监听改 `0.0.0.0:8090`；HTTP 明文、无域名证书。仅作兜底记录，不建议采用。

## 5. 端点确定后的配置与验证清单（可执行）

### 5.1 写入 Secrets（端点方案定稿后执行）

```bash
# 后端（方案 A 用 127.0.0.1:8090；方案 B 用 glitchtip.outman.press）
printf '<后端 DSN>' | gh secret set SENTRY_DSN --repo guanlili/english-speaking-assessment --env production
# 前端（只能用方案 B 的公网 HTTPS 地址）
printf '<前端 DSN>' | gh secret set VITE_SENTRY_DSN --repo guanlili/english-speaking-assessment --env production
```

管线：Secrets → `generate-deploy-env.sh` → 生产 `.env`；`VITE_SENTRY_DSN` 同时经 compose build arg 进前端镜像。生产 `.env` 当前两值均为空，SDK 不初始化。

### 5.2 部署后验证

1. 最终统一部署完成后，后端容器内触发一条测试事件（不重启容器）：
   ```bash
   ssh volc-belp
   cd /srv/english-speaking-assessment
   docker compose exec -T backend python -c "import sentry_sdk; sentry_sdk.capture_message('esa deploy verify backend')"
   ```
   预期：GlitchTip `esa-backend`(6) 几秒内出现该事件；SDK 未初始化时 `import sentry_sdk` 仍可用，但无 DSN 不会发出。
2. 前端：浏览器打开生产站点，控制台执行
   ```js
   setTimeout(() => { throw new Error('esa deploy verify frontend') }, 100)
   ```
   预期：`esa-frontend`(7) 出现事件；DevTools Network 可见请求发往配置的公网 HTTPS ingest 地址。
3. PII 抽检：事件载荷不含学生邮箱、姓名、IP（服务端匿名化后）、Cookie、Authorization、请求体。
4. 回环自测残留：项目 6/7 各有 1 条本次 wiring 自测事件，确认通路后可在 GlitchTip UI 删除或忽略。

### 5.3 告警出口现状与待办

- 当前 GlitchTip 实例**未配 SMTP**，`alerts_projectalert` 全库 0 条规则；事件只落库、不主动推送。
- 后续在 GlitchTip UI 为两个项目配告警规则（如 N 分钟内 M 条新错误），并在 `~/glitchtip/.env` 补 SMTP 或接 Webhook（如飞书/钉钉机器人）；该步属监控端配置，不在本次代码 PR 内。
- 业务侧队列堆积/成本告警走平台自有 SMTP 邮件链路（见 `docs/observability-setup.md` 第二节），与 GlitchTip 相互独立。

## 6. 未覆盖 / 待办

1. 端点方案（A/B）与子域归属需要用户决策；决策前 Secrets 保持空值，SDK 不上报，不存在「已接通」谎报。
2. 公网反代的 nginx 配置、DNS、证书、安全组放行属监控端部署改动，待方案定稿后单独执行，不在本 PR。
3. GlitchTip 侧 SMTP / 告警规则 / Webhook 未配置。
4. 未在生产后端容器实际触发过 SDK 上报（DSN 空且网络不通）；5.2 清单为部署后首验步骤。
