# AGENTS.md — AI 工具通用入口

本文件给所有 AI 编码工具（Claude Code、Codex、Cursor、ZCode 等）作为统一入口。
规范只维护一份，此处只做引用，避免多份拷贝漂移：

- **[CLAUDE.md](CLAUDE.md)** — 项目结构、本地开发、新功能标准流程（模型/迁移/生成客户端/页面）、测试运行方式。所有工具都应遵守。
- **[AI_RULES.md](AI_RULES.md)** — 编码规范（命名、类型、错误处理、401/403 语义、禁止模式）与部署约定。

两者冲突时以 `CLAUDE.md` 的流程章节为准。

## 最小必读约定（详细版见上述两文件）

1. 后端改动模型/接口后：生成 Alembic 迁移，并 `cd frontend && npm run generate-client` 同步客户端（CI 会校验漂移）。
2. 前端不手写 API URL，统一用 `src/client/` 生成代码。
3. 401 只用于 token 无效/过期（前端自动登出并清缓存）；403 用于权限不足，不触发登出。
4. 后端测试用独立测试库 `app_test`（`conftest` 自动创建），任何情况下不得把测试指向开发库。
5. 生产 `.env` 由部署流水线从 GitHub Secrets 生成，不手改、不提交。
