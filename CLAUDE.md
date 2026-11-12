# CLAUDE.md — 项目规范

> 本项目为「BRS English Learning Platform」（简称 **BELP**）英语口语学习平台（视觉与交互参照 prototypes/speakup 原型），基于 lili-full-stack 模板创建。品牌沿革：SpeakUp → Charcoal（暂定）→ BRS English Learning Platform（2026-10-29 正式定名）；全名与简称统一定义在 `frontend/src/config.ts`（APP_NAME / APP_NAME_SHORT），改名只需动文案层，视觉素材（Logo 图形/插画）暂不重做。
>
> 本文件只放规则、不变量与流程。各模块的实现细节、关键路径和迁移号见 **[docs/module-notes.md](docs/module-notes.md)**——改动某模块前先读对应章节。

## 业务上下文

- 需求来源：甲方 PRD《独立英语口语评测平台 v0.1》（2026-09-25，王府学校）。
- **产品定位（2026-09-26 与甲方对齐）：课堂教学工具**——老师在前面授课、全班电脑登录学生端同步练习；不是多邻国式自学产品。内容节奏由老师主导：老师发布练习，全班 /today 即时同步；学生个人关卡路径仅作为课后自主练习的兜底。
- 当前阶段：PRD 功能全部就绪，并已上线激励层、AI 出题、背单词、模考与自动考试、教师备课/点评/补练。课堂难度由教师选择的内容决定，A2/B1/B2 仅作内部评分/词表元数据（兼容规则在 `app/scoring/bands.py`），不出现在课堂教学流程，也不向学生展示。演示重置：`bash scripts/reset-demo.sh`。
- 评分架构（PRD 不可协商）：引擎藏在可替换接口后（`app/scoring/`），`SCORING_PROVIDER` 配置切换：`mock`（默认，离线演示/测试）｜`ark`（火山方舟，需 `ARK_API_KEY`）。上传与评分分离：POST `/attempts` 立即返回 queued，线程池异步出分，前端轮询。跟读类（passage/repeat）出三维分，问答出总评+建议，ark 下另有 rubric 模拟分。音频回放走 `GET /attempts/{id}/audio`（attempt id 随机 UUID，不可猜）。
- 方舟适配要点：浏览器 webm/opus 需服务端 ffmpeg 转 16kHz wav（`app/scoring/audio_convert.py`）；空转写不出 0 分模拟分；标准音 TTS 走 vei AI 网关（`ARK_TTS_*`，与方舟 Key 是两套），未配置时 TTS 503、上传现成音频不受影响，前端 speechSynthesis 兜底。
- 界面文案铁律（PRD §3.2）：分数一律标「参考/模拟」，写明不是官方成绩；三种分（跟读引擎/模型/词表）来源要在界面上分开标注。
- EIP 教材原文因版权**不进仓库**，只建内容槽（Passage/RepeatSentence/Scenario/ScenarioQuestion 表）；演示种子用自写 Pets 内容（slug: demo-pets，课堂码 DEMO01）。五级词库原始教材同样不入仓库。
- 学生账号默认密码统一 `brs123456`，**不强制改密**（2026-09-29 产品决策）。
- 待办：EIP 教材文本录入；词级发音评分二期（选型结论：火山打底、腾讯 SOE-N 候选）；题库个人/校内共享分层 P2 复制 / P3 共享（P1 编辑保护已实现：教师只能改自己创建的题，管理员与存量内容公共可改；见 `docs/question-bank-ownership-design.md`）。
- 生产部署已启用：push `master` → CI（lint + 测试 + 客户端一致性 + E2E 汇总）→ 自动部署（`ENABLE_PRODUCTION_DEPLOY` 仓库变量控制）。回滚常规走 revert；紧急秒级用 `scripts/rollback.sh`（部署链自动保留上一版镜像为 `:rollback` 标签；见 README「回滚」）。

## 跨模块不变量（改代码时必须守住）

- **发布快照不可变**：老师发布生成 `ClassroomExercise.snapshot_items`（深拷贝题目内容），学生会话按快照出题，作答再存 `attempt.item_snapshot`，worker 只读快照。题库编辑只影响下一次发布；已发布练习、补练、历史结果一律按当时快照解释。背单词发布同理。
- **历史不漂移**：词库/题型等数据迁移只新增，不回填、不重算已有 attempt.vocab 与快照；新增可空列为 NULL 时旧流程含义完全不变。
- **服务器时间是考试的唯一权威**：开考、整场截止、逐题计时、自动考试阶段都由服务器时间恢复，刷新/退出不重置也不暂停；前端计时只做展示。考试会话内每题一次作答，未结束时不向学生泄露分数（含星级/XP 等派生信息）。
- **幂等键绑定会话+题目**：跨题/跨会话复用一律 422，断网重传原键安全。
- **题目说明（instruction）不算题**：不计入题量、进度、完成分母和最终反馈，只保留已读确认与考试计时窗口。
- **事务里不做慢操作**：ASR/LLM 网络调用、ffprobe、落盘不得持有打开事务或行锁；先短事务判定 → 释放 → 慢操作 → 新短事务复查并写入。
- **权限**：课堂类接口以课堂教师归属判定；重置密码只作用于学生角色账号；401 只用于 token 无效/过期，403 用于权限不足（详见 `AI_RULES.md`）。
- **列表端点分页（2026-11 起）**：返回 `list[...]` 的列表端点不得裸 `.all()` 返回全量，统一用 `app/api/pagination.py` 的 `paged(statement, offset, limit)`，签名 `offset: int = Query(default=0, ge=0)` + `limit: int | None = Query(default=None, ge=1, le=N)`（不传 limit = 不封顶，对既有调用零行为变化）；确需全量的端点（按天聚合、缺考补全、注释声明量级小）要在 docstring 写明理由。
- **多租户隔离（2026-11 起，RLS 已在生产强制）**：① 新业务表一律用 `models._tenant_id_field()` 工厂加租户列（写入自动继承请求上下文所属学校，勿手写 default）；② 学校业务查询默认信任 RLS 过滤，平台/跨校口径的端点用 `PlatformSessionDep`、后台任务用 `core.db.platform_engine`（语义=无租户边界，学校端点禁用）；③ 角色只有 school_admin/teacher/student（前端判定双兼容旧值 admin 到过渡期结束），无 is_superuser；④ 跨校对象访问按 404 处理不泄露存在性；⑤ 新唯一约束默认 (tenant_id, X) 复合。详见 `docs/multi-tenant-design.md` 与 A 期清单 §7。
- **运维巡检（2026-11 起）**：`.github/workflows/ops-watch.yml` 每小时跑一次只读巡检——公网探 `/api/v1/utils/health-check/`（连续 3 次非 200 才红灯，避免抖动误报）+ 服务器 `/` 与 `/opt` 磁盘两档（70% 预警、85% 告警，红灯）。阈值只在该 workflow 的 `env` 改；新增生产依赖（外部存储、第三方 API）时把探针加到同一个 workflow，不要新建分散的定时任务。

### 术语表（2026-09 统一，前端单一事实源 `frontend/src/lib/terms.ts`）

同一概念全端只用一个词，新文案必须遵守（历史盘点：Unit 曾有 7 种叫法、问答 8 种、指派相关 9 种）：

| 概念 | 统一词 | 备注 |
|---|---|---|
| Unit | 单元 | 课堂指派与自主练习的基本单位；页面叫「单元管理」 |
| Unit.topic | 主题 | 与单元名区分（单元叫「宠物朋友」，主题叫「宠物」） |
| Passage | 篇目 | 教师/管理端；朗读与复述共用的英文材料 |
| 题型 reading | 文章朗读 | 学生端旧称「整篇朗读」已废 |
| 题型 repeat | 听句复述 | 学生端旧称「听后复述」已废 |
| 题型 qa | 情景问答 | 旧称「模拟问答/问答/开放问题/问法」已废；单条题叫「题目」 |
| 题型 instruction | 题目说明 | 无作答的纯文字引导页；学生点「继续」进入下一题（2026-10-08 起） |
| 学生每日练习入口 | 今日练习 | 学生端页面 title、通知、首页 CTA 一致；教师端发布动作用「发布」 |
| 非指派模式 | 自主练习 | 旧称「自由练习/个人关卡」已废 |
| overall 分 | 参考分 | 可带前缀「跟读参考分/情景问答参考分」；rubric 0-9 叫「模拟分」 |
| CEFR band | 内部词表/评分元数据 | 不作为课堂安排或学生能力标签展示 |
| 学生成长页 | 我的成长 | 教师端对应页面叫「进步轨迹」 |
| 学生进班动作 | 进入课堂 | 旧称「加入课堂」已废（「邀请学生加入」作动词短语保留） |

- 课堂练习路由注意：TanStack 文件约定下 `p.$code.tsx`、`t.$code.tsx`、`_layout/admin.tsx` 都是父 layout（只渲染 Outlet），实际页面在 `*.index.tsx` 与兄弟路由文件。新增带参数子路由时必须检查父 layout 是否有 Outlet。

## 模块索引

实现细节见 [docs/module-notes.md](docs/module-notes.md) 对应章节；有独立设计文档的另列。

| 模块 | 关键代码 | 文档 |
|---|---|---|
| 发布快照 / 题型 / 朗读题库树 / 激励层 / 学习路径 / AI 出题 / 模拟分 | `services/exercise.py`、`services/reading.py`、`scoring/` | module-notes「课堂练习主链路」 |
| 五级词库 | `services/vocab_levels.py`、`/admin/vocablevels` | module-notes「五级词库」、`docs/five-level-vocab-quality-report.md` |
| 分级题型训练（TOEFL/IELTS） | `exam_kind`/`exam_level` 列 | module-notes「分级题型训练」 |
| 背单词 | `services/vocabulary.py`、`routes/vocabulary.py` | `docs/vocabulary-module-design.md` |
| 练习/考试入口与回看（G01–G05） | `/p/{code}`、`/exam/{code}` | module-notes「通用功能」 |
| 模考与课堂删除 | `services/exam.py`、`routes/attempts.py` | module-notes「模考模式」 |
| 自动考试（E01–E10） | `services/exam_flow.py`、`AutomatedExamSession` | module-notes「自动考试流程」 |
| 教师备课、诊断、点评、补练 | `class_composer.py`、`class_diagnostics.py`、`class_followups.py`、`class_followup_outcomes.py`、`class_reviews.py`、`class_messages.py` | `docs/teacher-platform-design.md` |
| 平台更新日志（教师/管理员可见） | `routes/changelog.py`、`frontend/src/routes/_layout/changelog.tsx`、`hooks/useChangelog.ts` | module-notes「平台更新日志」 |
| 口语原音频 ZIP / 学生学情 PDF | `routes/exports.py`、`services/audio_export.py`、`services/student_report_pdf.py`、`exporting/worker.py` | module-notes「口语原音频 ZIP」「学生个人学情报告 PDF」 |
| 实时课堂 / 自检 / 诊断补练 / 复核 / 讲评 / 对比 / 阶段报告 | `class_teaching_tools.py`、`admin_content_copy.py`、`attempts.py` | `docs/teacher-platform-design.md`「课堂教学闭环增强」 |
| 运行时与可观测 | `X-Request-ID`、metrics | `docs/runtime-observability.md` |
| 备份与恢复 | `scripts/backup-local.sh` | `docs/backup-restore.md` |
| 紧急回滚（秒级切上一版镜像） | `scripts/rollback.sh` | README「回滚」 |
| 部署链稳定性（lock 镜像改写/cron 注册/超时） | `backend/Dockerfile`、`.github/workflows/deploy.yml` | module-notes「部署链稳定化」 |
| 公开站点（落地页 / 关于 / 帮助 / 隐私） | `frontend/src/routes/index.tsx`、`routes/{about,help,privacy}.tsx`、`components/Site/SiteShell.tsx` | module-notes「公开站点」 |

## 项目结构

```
backend/app/
├── api/routes/     # FastAPI 路由（每个业务模块一个文件，只做权限与编排）
├── services/       # 域逻辑（快照、考试、词汇等边界规则）
├── scoring/        # 评分引擎接口与实现（ASR/rubric/TTS/worker）
├── core/           # 配置、安全、数据库连接
├── models/         # SQLModel 数据模型（按域拆分，__init__ 统一再导出）
│   ├── base.py       # 租户列工厂与公共常量
│   ├── core.py       # 租户/用户/令牌
│   ├── content.py    # 篇目/单元/复述/情境/说明/题库
│   ├── classroom.py  # 课堂/学生/作答
│   ├── learning.py   # 学习路径/今日计划/看板/诊断
│   ├── vocabulary.py # 词库与五级分级
│   └── admin.py      # 运营指标/成本/变更日志/导出
├── crud.py         # 数据库增删改查操作
└── main.py         # 应用入口

frontend/src/
├── routes/         # TanStack Router 页面（_layout/ 下是需要登录的页面）
├── components/     # 可复用组件
├── hooks/          # 自定义 hooks（封装 useQuery/useMutation）
└── client/         # 自动生成的 API 客户端（不要手动修改）
```

## 本地开发

```bash
docker compose up --build   # 首次启动
docker compose watch        # 启用热更新（后端 --reload，前端 vite HMR）
docker compose down         # 停止
```

| 服务 | 地址 |
|------|------|
| 前端（vite dev server） | http://localhost:5173 |
| API 文档 | http://localhost:8000/docs |
| 邮件测试 | http://localhost:1080 |

查看数据库：`docker compose exec db psql -U postgres -d app`

运行后端测试（需要数据库在运行；测试自动创建并使用**独立测试库** `app_test`，不碰开发库 `app`）：

```bash
cd backend
# 本机宿主机 5432 被其他项目占用，db 映射到 5433（见 compose.override.yml）
POSTGRES_SERVER=localhost POSTGRES_PORT=5433 uv run bash scripts/tests-start.sh
```

提交前的统一入口（格式 → Lint → 全量测试 + 覆盖率门禁 → openapi 契约，四道闸门一次跑完）：

```bash
cd backend
uv run bash scripts/verify.sh --openapi     # 全量，约 2.5 分钟，退出码 0 才算过
uv run bash scripts/verify.sh -k 某个用例名  # 只改了单模块时先定向跑，几秒出结果
```

`scripts/verify.sh` 会自动探测本地数据库（5433 通了就自己 export，不通会直接告诉你先 `docker compose up -d db`）。
openapi 契约变更属有意改动时，用 `--openapi-update` 更新 `backend/openapi-baseline.json` 并随 PR 提交。

更快的本地闸门：装一次 pre-commit（`brew install pre-commit && pre-commit install`），之后每次 `git commit` 自动跑后端的 `ruff` + `ty` 和前端的 `biome check`，秒级、与 CI 同口径。它**不跑测试与覆盖率**，这两项仍走上面的 `verify.sh`；想手动全量跑改用 `pre-commit run --all-files`。hook 定义在仓库根的 `.pre-commit-config.yaml`，入口脚本是 `scripts/precommit.sh`（后端会自己探 `.venv/bin`，前端缺 `node_modules` 会直接报错提示先 `npm ci`）。

测试库指向应用库时（`POSTGRES_DB_TEST` 与 `POSTGRES_DB` 相同）会在任何建表/删数据操作之前直接拒绝运行。

E2E：新测试文件默认进入真实后端的 `chromium` 项目；确认所有 API 都被模拟且无共享状态后，才加入 `frontend/playwright.config.ts` 的 `mockedFiles`（分层与本地分片命令见 module-notes「Actions E2E 分层与并行」）。

## 开发新功能的标准流程

> 本节是流程的唯一权威版本（README 只留概览指向这里）。

1. **后端**：在 `models/<对应域>.py` 加数据模型（按域放置，不要新建顶层模型文件；对外仍以 `from app.models import X` 引用） → 在 `crud.py` 加增删改查 → 在 `api/routes/` 加新路由文件 → 在 `api/main.py` 注册路由
2. **数据库迁移**：`docker compose exec backend alembic revision --autogenerate -m "add xxx"` → `alembic upgrade head`
3. **前端 API 客户端**：后端改完后重新生成 → `cd frontend && npm run generate-client`（脚本会从运行中的 backend 容器导出最新 OpenAPI 规范再生成）
4. **前端页面**：在 `routes/_layout/` 加新页面，在 `frontend/src/components/Sidebar/AppSidebar.tsx` 的 `baseItems` 里加导航链接（平台区块按运营身份 `esa:role=operator` 展示，校级业务按 `role` 判定——多租户 B3 起无 `is_superuser`）
5. **文档**：模块实现细节写进 `docs/module-notes.md`（或模块自己的设计文档），并在本文件「模块索引」加一行；只有新增跨模块规则时才改本文件正文。

## 双语准则（平台级，2026-09-30 起）

平台有外教使用，**所有用户可见文案必须中英双语**。这是硬性开发准则，不是可选项。

- **机制**：`frontend/src/lib/i18n.tsx` 的 `useI18n()` → `t({ zh: "…", en: "…" })`；语言切换组件 `components/Common/LanguageToggle`（中/EN，localStorage 按浏览器记忆，默认中文）。
- **参考实现**：`frontend/src/routes/login.tsx` 与 `components/Common/LoginLayout.tsx`（含 zod 校验消息随语言重建的写法）。
- **新增界面/文案**：一律 `t({ zh, en })`，不允许再落单语言硬编码。共享术语的中英文对齐本文件「术语表」。
- **存量迁移**：按页面渐进迁移（改哪页双语哪页），不要求一次性完成；新 PR 触碰某页时顺手完成该页双语。
- **后端 API 错误文案**：`detail` 是稳定标识（前端 `main.tsx` 有按文案分流的 401 处理逻辑，**不得随意改措辞**）；面向用户的错误提示一律在前端映射成双语展示，不直接透出 detail。后端返回值的枚举/状态值（如 `status: "done"`）永不做翻译。
- **不做**：URL 按语言分路由（`/en/...`）；服务端语言协商。一个前端包、客户端切换即可。

## 三端自适应准则（平台级，2026-10-01 起）

平台必须支持电脑 / 手机 / 平板三端，**iPad 是学生上课主力设备**。新页面与改动都要在 390 / 820 / 1180 三档宽度下检查无横向溢出（`tests/e2e/responsive.spec.ts` 已入 CI）。

- **表单控件字号 ≥16px（全断点）**：原生 input/select/textarea 必须 `text-base`——iOS Safari 聚焦小于 16px 的控件会整页自动放大且失焦不还原。禁止用 `maximum-scale=1` 禁缩放来绕过（无障碍红线）。
- **触控目标**：高频操作 ≥44px，低频至少 40px；相邻的破坏性操作拉开间距。`icon-sm` 已调整为 size-10。
- **表格**：统一走 `ui/table.tsx`（自带 overflow-x-auto，不会撑破手机屏）；列多的宽表在 `<sm` 屏加「横向滑动」提示（`t.$code.index.tsx` 有范例）。
- **视口高度**用 `svh/dvh`，不用 `vh`（iOS 工具栏收放导致跳动）。
- **交互不得仅 hover 可达**（触屏无 hover）；hover 只用于装饰性反馈。
- **Dialog 滚动**依赖 `ui/dialog.tsx` 模板（dvh 口径 + overflow-y-auto + 小屏按钮纵向堆叠），业务弹窗不要再套自己的 `max-h-[xxvh]`。
- 学生端壳（StudentShell）<768 走底部 tab + 安全区，≥768 走侧栏；教师端侧栏 <768 走抽屉——断点行为已定型，新页面挂在对应壳下自动获得。

## 技术规范

详见 `AI_RULES.md`。

## 项目管理（devledger，记账硬性规范）

本仓库由人类 + 多个 AI 协作开发，项目管理主账本是 GitHub Project `#3`（devledger skill，工具与方法论在本机 ~/.agents/skills/devledger）。

**硬性纪律：任何 AI 会话完成了一个可交付单元（需求/缺陷/修复/交付线/文档），结束会话前必须完成记账三步。不可跳过、不可"下次一起补"——没记账的工作等于没做。**

记账三步：

1. 当轮 commits 聚类成可交付单元（甲方可感知的主题，一次 commit 不等于一条）；commit 末尾尽量带 issue 号 `(#N)` 自动关联
2. 按模板建 issue（`.github/ISSUE_TEMPLATE/需求.md`：来源[含原话]/描述[为什么·否决方案·做了什么]/交付物/验证/工时，label=类型；决策上下文记录时写全，事后不可补）。保存 issue URL，已有 issue 直接复用。
3. 用 `python3 ~/.agents/skills/devledger/scripts/bookkeep.py --project 3 --issue <issue URL> --type <类型> --source <来源> --hours <人类等价工时> --start <YYYY-MM-DD> --end <YYYY-MM-DD>` 入板、补字段并读回，确认后关闭 issue。甲方需求加 `--requester <需求人>`。中断后使用相同 URL 和参数续跑。

**issue 是唯一工作真相源**：字段与任何汇总均为派生视图。已知坑与扩展工具见 ~/.agents/skills/devledger/SKILL.md。

