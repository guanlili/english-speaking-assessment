# 上线 smoke 清单（#517）

状态：**未对生产执行**。本文与 `scripts/go-live-smoke.sh` 只读、可重复；默认 dry-run。
目标：一次性上线 master `a6abbe8` 前/后各跑一遍，确认代码、迁移、权限、只读台账、口语主链路与移动端基线；**不写业务数据、不部署、不回滚**。

清单共 **32 项**：部署前 12 项、部署后 20 项。
脚本能自动判定的条目用 `A`，必须人工确认的用 `M`，服务器/数据库类在提供 SSH 参数后可自动、否则转人工的用 `A/M`。

## 1. 使用边界

- 脚本默认 dry-run：只跑本地静态检查（git、迁移文件、prestart 顺序、workflow 静态），不发网络/SSH 请求。
- `--execute` 才发 **GET**、只读 SQL、只读 `git` / `docker` / `nginx` / 日志；不含任何 POST/PUT/PATCH/DELETE。
- 不自动登录、不提交作答、不上传音频、不导出文件到磁盘；CSV 只在内存中检查首列。
- token 只从环境变量读取，不写文件、不回显；不要用 `bash -x` 跑本脚本。
- 生产执行只允许只读命令；`ensure_db_roles`、迁移、重启等写操作由部署流水线负责，不在本脚本。

## 2. 环境变量

| 变量 | 用途 | 必需 |
|---|---|---|
| `SMOKE_BASE_URL` | 站点根地址，例如 `https://<生产域名>`；脚本拼 `/api/v1` | 部署后 HTTP 检查必需 |
| `SMOKE_WEB_URL` | 前端根地址；默认同 `SMOKE_BASE_URL` | 页面检查可选 |
| `SMOKE_API_BASE` | 直接指定 API base；默认 `${SMOKE_BASE_URL}/api/v1` | 可选 |
| `SMOKE_PLATFORM_TOKEN` | 平台运营 Bearer token；兼容 `SMOKE_ADMIN_TOKEN` | 台账 API 自动检查必需 |
| `SMOKE_PLATFORM_COOKIE` | 平台运营 Cookie；兼容 `SMOKE_ADMIN_COOKIE` | token 的替代 |
| `SMOKE_SCHOOL_TOKEN` | 学校管理员/教师 Bearer token | 口语/词汇/403 检查必需 |
| `SMOKE_SCHOOL_COOKIE` | 学校账号 Cookie | token 的替代 |
| `SMOKE_EXPECTED_SHA` | 目标代码 SHA；默认当前 HEAD | 建议显式设置 |
| `SMOKE_DEPLOYED_SHA` | 已知的部署 SHA；不提供则尝试 SSH `git rev-parse` | 可选 |
| `SMOKE_SSH_TARGET` | 服务器 SSH 别名/地址，启用服务器只读检查 | 可选 |
| `SMOKE_DEPLOY_PATH` | 生产代码目录，默认 `/srv/english-speaking-assessment` | 配合 SSH |
| `SMOKE_BACKUP_FILE` | 本机可读的备份文件路径（直接 `gzip -t`） | 可选 |
| `SMOKE_AUDIO_URL` | 一条已知可回放的音频 GET URL | 可选；否则人工 |
| `SMOKE_EXPECT_VOCAB_STATUS` | 词汇端点期望码，生产默认 `403` | 生产保持 403 |
| `SMOKE_EXPECT_VOCAB_MODULE` | `off`（生产默认）/`on`（本地开通环境） | 本地测试可设 on |
| `SMOKE_DB_BASE` | 生产部署前 `alembic_version`，默认 `e5f6a7b8c9d0` | 变更基线时改 |
| `SMOKE_EXPECT_DB_HEAD` | 部署后 head，默认 `f3a4b5c6d7e8` | 变更迁移时改 |
| `SMOKE_EXPECT_CHAIN_LEN` | `e5 → head` 迁移支数，默认 `5` | 变更迁移时改 |
| `SMOKE_APP_DB_USER` | 受限应用角色，默认 `esa_app` | 通常不改 |
| `SMOKE_LOG_SINCE` | 日志回看窗口，默认 `30m` | 可选 |
| `SMOKE_GH_BIN` | gh 可执行路径；默认 PATH 或 Homebrew 路径 | 可选 |

Token 建议用不落 shell 历史的读入方式：

```bash
read -rsp 'Platform token: ' SMOKE_PLATFORM_TOKEN; echo
read -rsp 'School token:   ' SMOKE_SCHOOL_TOKEN; echo
export SMOKE_PLATFORM_TOKEN SMOKE_SCHOOL_TOKEN
```

不要把 token 写进 `.env`、命令历史、Issue、PR 或截图。

## 3. 执行顺序

```bash
# 1) 先 dry-run，确认参数与静态检查
bash scripts/go-live-smoke.sh

# 2) 部署前只读
SMOKE_EXPECTED_SHA=<目标 SHA> \
SMOKE_BASE_URL=https://<生产域名> \
bash scripts/go-live-smoke.sh --pre --execute

# 3) 部署（由 Deploy Production 手动 workflow，不在此脚本）

# 4) 部署后只读
SMOKE_EXPECTED_SHA=<目标 SHA> \
SMOKE_DEPLOYED_SHA=<目标 SHA> \
SMOKE_BASE_URL=https://<生产域名> \
bash scripts/go-live-smoke.sh --post --execute
```

建议把输出保存到本地工单附件；脚本不会打印 token，但输出可能含学校名/CSV 首列，按内部资料管理。

## 4. 部署前清单（12 项）

| ID | 检查 | 判定 | 方式 | 证据/命令 |
|---|---|---|---|---|
| P01 | 部署审批：时间窗、无并发部署、用户已确认上线 | 人工签字 | M | 本 Issue/工单确认 |
| P02 | 目标 SHA 与 CI：HEAD=目标，且该 SHA 的 CI success | SHA 相等 + CI run success | A | `git rev-parse HEAD`；`gh run list --workflow CI --commit <sha>` |
| P03 | 工作树：已跟踪文件无未提交改动 | `git status --porcelain -uno` 为空 | A | 脚本 |
| P04 | 备份文件存在：最新 `backups/app-*-predeploy.sql.gz` 或完整 bundle | 文件非空 | A/M | `SMOKE_BACKUP_FILE` 或 SSH |
| P05 | 备份可读：`gzip -t` 通过 | exit 0 | A/M | 脚本 |
| P06 | `:rollback` 镜像存在（backend/frontend） | `docker image inspect` 成功 | A/M | SSH 或服务器人工 |
| P07 | 迁移清单与 head：`e5 → f3` 共 5 支 | n=5，head=`f3a4b5c6d7e8` | A | 脚本解析 Alembic 文件 |
| P08 | 生产 DB 基线：`alembic_version=e5f6a7b8c9d0` | 只读查询相等 | M | `alembic current`（服务器） |
| P09 | `tenant_module`：speaking on、vocabulary off | 全校 speaking 启用、vocabulary 均关闭 | A/M | HTTP `/modules/me`（抽样校）或 SQL 聚合 |
| P10 | `ensure_db_roles` 在 prestart 中位于 Alembic 之后 | 行号 alembic < ensure | A | `backend/scripts/prestart.sh` |
| P11 | 部署流水线含 predeploy 快照、`:rollback` 标签、prestart 失败日志 | 3 项均存在 | A | `.github/workflows/deploy-prod.yml` |
| P12 | 备份可恢复演练 | 独立项目恢复 + prestart + smoke 通过 | M | **未执行**；等确认后按 `recovery-drill` 单独安排 |

迁移链预期：

```text
e5f6a7b8c9d0
  → f8a2b3c4d5e6  （2 张班内榜表）
  → b6c7d8e9f0a1  （授权审计/版本快照 + 存量回填 + 索引）
  → c7d8e9f0a2b3  （JSON 列）
  → d8e9f0a1b2c3  （索引 rename）
  → f3a4b5c6d7e8  （exam_tags / cefr_band）
```

## 5. 部署后清单（20 项）

| ID | 检查 | 通过标准 | 方式 | 证据/命令 |
|---|---|---|---|---|
| S01 | ready | HTTP 200 且含 `Ready` | A | `GET /api/v1/utils/ready-check/` |
| S02 | health | HTTP 200 且含 `true` | A | `GET /api/v1/utils/health-check/` |
| S03 | 版本 SHA | 部署 SHA=目标 SHA | A/M | SSH `git rev-parse` 或 `SMOKE_DEPLOYED_SHA` |
| S04 | 迁移 head | `alembic current` 含 `f3a4b5c6d7e8` | A/M | SSH `docker compose exec backend alembic current` |
| S05 | 4 张新表存在 | 4 行均存在 | A/M | 只读 SQL：班内榜 2 + 授权审计 + 版本快照 |
| S06 | `esa_app` 有 DML | 4 表 `SELECT/INSERT/UPDATE/DELETE` 均 true | A/M | `has_table_privilege` |
| S07 | 无租户上下文读 0 行 | 4 表均 0 | A/M | `SET ROLE esa_app` + `count(*)` |
| S08 | RLS 自检 | `prod-rls-selfcheck.sh` exit 0 | A/M | SSH 只读 |
| S09 | 口语登录 | `/modules/me` 200 且 speaking 启用 | A | 学校 token |
| S10 | 课堂 | `/classes` 200 且至少 1 个课堂 | A | 学校 token；0 条转人工 |
| S11 | 作答/评分 | 测试账号完成一次作答并看到评分 | M | **写链路，脚本不提交** |
| S12 | 音频回放 | HTTP 200/206，可播放 | A/M | `SMOKE_AUDIO_URL`；否则人工 |
| S13 | 词汇仍 403 | `/vocabulary/books` HTTP 403 | A | 生产 `SMOKE_EXPECT_VOCAB_STATUS=403` |
| S14 | 运营授权页只读 200 | 页面 HTML 200；页面无编辑/保存/删除入口 | A + M | 页面 GET + 人工目检 |
| S15 | 授权状态 API | 200，`items` 数组 | A | 平台 token |
| S16 | CSV 首列 | CSV 200，首列「学校」 | A | 平台 token；注意 BOM |
| S17 | 学校 token 拒绝 | 401/403，不能读平台台账 | A | 平台端点；见下方口径 |
| S18 | 390 宽无溢出 | `scrollWidth == clientWidth` | M | DevTools/Playwright：登录/学生首页/教师词汇/台账 |
| S19 | 日志无权限/500 | 最近 30m 无 `permission denied`/`500`/`Internal Server Error` | A/M | SSH `docker compose logs backend` |
| S20 | nginx PK SSE | `nginx -T` 含 `vocabulary/pk/matches` SSE location | A/M | SSH `nginx -T` |

### 必须人工确认的项

- **P01** 审批与时间窗、**P12** 备份恢复演练（按备注本轮不执行）。
- **S11** 口语作答/评分：写链路，只读 smoke 不提交。
- **S12** 音频回放：没有 `SMOKE_AUDIO_URL` 时人工播放。
- **S14** 只读视觉：页面无编辑/保存/删除入口。
- **S18** 390 宽关键页无横向溢出。
- 任何 `A/M` 项在未提供 SSH/DB 参数时都会降级为人工，输出 `MANUAL`，不算 PASS。

## 6. 口径纠偏：学校 token 是 401，不是 403

平台授权端点使用独立 audience；学校 token 没有平台 audience，后端返回 **401**（凭据 audience 不匹配），不是 403。前端学校管理员访问 `/admin/vocabulary-licenses` 会被路由守卫重定向，也不是 403。

因此脚本对 S17 的判定是 **401/403 均视为“被拒绝”**，并打印实际码；本地实测为 401。若上线验收必须严格 403，需要另开后端语义 PR（把 audience 错误映射为 403），不属于本文档范围。

词汇端点 S13 的 403 是模块关闭的独立门禁，和上面的平台 audience 不是同一件事。

## 7. 失败处理

- 任一 `FAIL`：停止上线流程；不要用重启/重试掩盖。
- 部署前 FAIL：不部署。
- 部署后 FAIL：按 `scripts/rollback.sh` 切 `:rollback` 镜像；DB 保持新 schema，**不要** `alembic downgrade`、不要把 stamp 回 `e5`。
- `MANUAL` 未确认：不得把上线标记为完成。
- `permission denied` / RLS 自检失败：先停写、查角色/策略，不要先回滚代码（代码回滚不一定修复权限问题）。

## 8. 本轮未做

- 生产部署、生产写操作、生产压测。
- 第 1 项「备份可恢复演练」：未执行；等用户确认后单独安排。
- C 块真机 Safari/真实软键盘：仍为 BLOCKED/模拟口径；本清单只做 Go-live smoke，不重复真机审计。

## 9. 本地验证记录（2026-11-26）

- 默认 dry-run：exit 0，`PASS=5 FAIL=0 MANUAL=6 SKIP=12`。
- `--pre --execute`（本地仓库 + 本地 API）：exit 0，`PASS=7 FAIL=0 MANUAL=5`；CI run `45654007673` 被识别为 success。
- `--post --execute`（本地 current backend `:8035` + 前端 `:5173`）：exit 0，`PASS=10 FAIL=0 MANUAL=11`；license status `items=8`、CSV 首列「学校」、学校 token 平台端点实测 **401**、词汇端点本地按开通环境返回 200。
- 4 张新表存在、`esa_app` 四表 DML、`SET ROLE esa_app` 后四表均 0 行：已在本机 PG18 只读 SQL 验证。
- 服务器/DB/nginx/日志类检查未在本机模拟；生产执行时需提供 `SMOKE_SSH_TARGET` 或按第 5 节人工。
- **未对生产执行任何命令。**
