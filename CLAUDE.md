# CLAUDE.md — 项目规范

> 本项目为「英语口语评测平台」，基于 lili-full-stack 模板创建。

## 业务上下文

- 当前阶段：项目初始化，尚未实现口语评测业务。
- 已确定目标：建设英语口语评测平台。
- 待确认：目标用户、朗读或自由回答题型、评分维度、教师端需求、并发及预算、评测服务。
- 模板现有 User / Item 不代表最终业务模型；Items 暂留作开发参考。
- 开发顺序：需求与验收标准 → 真实录音评测验证 → 数据与接口设计 → 录音到报告的最小闭环。
- 远程录音演示需要 HTTPS；第三方评测密钥只放后端环境配置，不进入前端。
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
uv run bash scripts/tests-start.sh   # conftest 自动创建 app_test 并在其中建表、清库
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
