# CLAUDE.md — 项目规范

> 本项目为「英语口语评测平台」，基于 lili-full-stack 模板创建。

## 业务上下文

- 需求来源：甲方 PRD《独立英语口语评测平台 v0.1》（2026-09-25，王府学校）。三阶段累计工期：2 天演示（周一 2026-09-28）→ 2 周（课堂码+问答）→ 3 周（词汇/CEFR/教师面板）。
- 当前阶段：**PRD 功能全部就绪（含内容标准音与建议档）**——学生端全流程（US-04/05/06）+ 词汇量与 CEFR（US-07）+ 模拟分骨架（US-08，ark 引擎下 LLM rubric 四维 + 0-9 映射 + 升级表达；mock 不出假分）+ 学生进步轨迹（US-09）+ 教师面板（US-10）+ 管理端内容管理（`/admin/passages|scenarios|wordlist|classrooms`：篇目与复述句、情景问法、词表 CSV 导入、课堂码生成/停用）。内容标准音：TTS 生成（`app/scoring/tts.py`，需方舟密钥）或上传现成音频，回放走 `GET /audio/content/{name}`；无密钥时前端 speechSynthesis 兜底。学生轨迹含 band_change（维持/升/降，PRD US-10）。模板 Items 已删除。演示重置：`bash scripts/reset-demo.sh`。
- 模拟分（`app/scoring/rubric.py`）：rubric 四维 0-4 映射 0-9（`RUBRIC_TO_SCORE` 表）；LLM 失败降级不出假分，界面显示「建议暂缺」；仅 `SCORING_PROVIDER=ark` 时启用（`ARK_RUBRIC_MODEL` 配置模型）。
- 词汇分析（`app/scoring/lexicon.py`）：问答作答评分后写入 `attempt.vocab`（命中分档词/覆盖率/CEFR 参考）；只统计问答转写（跟读参考文本不算）；词元匹配支持规则屈折；标签规则：最高稳定档（≥5 命中）即该档，否则降一档。词表未配置时 vocab 为 null，界面显示「未配置词表」（BDD D）。内置演示词表 ~600 词（A2/B1/B2），待学校 CSV 替换。
- 40 人并发已验证（BDD B）：测试 `test_board.py::test_classroom_40_concurrent_submissions` 用真实线程池跑 40 并发上传 → 全部出分 → board 到齐。
- 课堂练习路由注意：TanStack 文件约定下 `p.$code.tsx`、`t.$code.tsx`、`_layout/admin.tsx` 都是父 layout（只渲染 Outlet），实际页面在 `*.index.tsx` 与兄弟路由文件。新增带参数子路由时必须检查父 layout 是否有 Outlet。
- 评分架构（PRD 不可协商）：引擎藏在可替换接口后（`app/scoring/`），`SCORING_PROVIDER` 配置切换：`mock`（默认，离线演示/测试）｜`ark`（火山方舟 Responses API 转写，需控制台开通模型 + `ARK_API_KEY`）。上传与评分分离：POST `/attempts` 立即返回 queued，线程池异步出分，前端轮询。跟读类（passage/repeat）出三维分，问答（question）只出总评+一句建议（rubric 四维是第 3 周）。音频回放走 `GET /attempts/{id}/audio`（attempt id 随机 UUID，不可猜）。
- 档位规则（`app/scoring/bands.py`）：A2/B1/B2 三档，首轮默认 B1；复述平均完整度 ≥80 且流利度 ≥60 升档，<50 降档；调整写入 student.current_band（下一轮沿用）与 session.question_band（本轮问答用）。
- 界面文案铁律（PRD §3.2）：分数一律标「参考/模拟」，写明不是官方成绩；三种分（跟读引擎/模型/词表）来源要在界面上分开标注。
- EIP 教材原文因版权**不进仓库**，只建内容槽（Passage/RepeatSentence/Scenario/ScenarioQuestion 表）；演示种子用自写 Pets 内容（slug: demo-pets，课堂码 DEMO01）。
- 待办（上线前）：火山方舟控制台开通模型推理（当前账号所有模型 NotFound；开通后填 `ARK_API_KEY` 并设 `SCORING_PROVIDER=ark`，转写与模拟分同时激活）、讯飞评测账号（跟读分升级可选）、学校分级词表 CSV（经 /admin/wordlist 导入）、EIP 文本（经 /admin/passages 录入，配音可上传现成音频）、域名 + ICP 备案（进教室要 HTTPS，备案 1~3 周需立即启动）。
- 生产部署尚未启用。配置部署 Secrets 后，将 GitHub Actions 仓库变量 `ENABLE_PRODUCTION_DEPLOY` 设置为 `true` 才允许自动部署。

## 项目结构

```
backend/app/
├── api/routes/     # FastAPI 路由（每个业务模块一个文件）
├── core/           # 配置、安全、数据库连接
├── models.py       # SQLModel 数据模型（数据库表结构）
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

测试库指向应用库时（`POSTGRES_DB_TEST` 与 `POSTGRES_DB` 相同）会在任何建表/删数据操作之前直接拒绝运行。

## 开发新功能的标准流程

> 本节是流程的唯一权威版本（README 只留概览指向这里）。

1. **后端**：在 `models.py` 加数据模型 → 在 `crud.py` 加增删改查 → 在 `api/routes/` 加新路由文件 → 在 `api/main.py` 注册路由
2. **数据库迁移**：`docker compose exec backend alembic revision --autogenerate -m "add xxx"` → `alembic upgrade head`
3. **前端 API 客户端**：后端改完后重新生成 → `cd frontend && npm run generate-client`（脚本会从运行中的 backend 容器导出最新 OpenAPI 规范再生成）
4. **前端页面**：在 `routes/_layout/` 加新页面，在 `frontend/src/components/Sidebar/AppSidebar.tsx` 的 `baseItems` 里加导航链接（Admin 入口已按 `is_superuser` 条件展示，可参考）

## 示例代码说明

`backend/app/api/routes/items.py` 和 `frontend/src/routes/_layout/items.tsx` 是 CRUD 功能的完整示例，展示了标准的开发模式。开始新功能时可以参考，最终交付前删除。

## 技术规范

详见 `AI_RULES.md`。
