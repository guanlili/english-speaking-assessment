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
6. 全站用户可见文案必须中英双语（外教使用）：前端用 `useI18n().t({ zh, en })`，参考实现见登录页；后端 `detail` 文案是稳定标识不得随意改措辞。详见 CLAUDE.md「双语准则」。
7. 三端自适应（桌面/手机/iPad）：表单控件字号 ≥16px 防 iOS 聚焦放大、触控目标 ≥44px、新页面过 390/820/1180 三档宽度。详见 CLAUDE.md「三端自适应准则」。

## 项目管理试点

执行前及收尾时阅读 [docs/project-management.md](docs/project-management.md)，按其中约定关联 Issue、PR、验证与交付证据。实际人工工时未经本人确认保持未记录；客户归属与工时可按用户确认范围公开记录，凭据与学生个人信息不得入库。既有 #222 双轨试运行约定仍有效，需求版本冲突先记录并澄清。

项目身份、客户归属和试点基线见 [docs/project-profile.md](docs/project-profile.md)。
