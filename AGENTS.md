# AGENTS.md — AI 工具通用入口

本文件给所有 AI 编码工具（Claude Code、Codex、Cursor、ZCode 等）作为统一入口。
规范只维护一份，此处只做引用，避免多份拷贝漂移：

- **[CLAUDE.md](CLAUDE.md)** — 项目结构、本地开发、新功能标准流程（模型/迁移/生成客户端/页面）、测试运行方式。所有工具都应遵守。
- **[AI_RULES.md](AI_RULES.md)** — 编码规范（命名、类型、错误处理、401/403 语义、禁止模式）与部署约定。

两者冲突时以 `CLAUDE.md` 的流程章节为准。

## 最小必读约定（详细版见上述两文件）

0. **提交前跑 `cd backend && bash scripts/verify.sh --openapi`**：一条命令过完格式 / Lint / 全量测试 + 覆盖率门禁 / openapi 契约。退出码 0 才算可交付；只改单个模块时用 `-k <用例名>` 先定向跑（几秒）。
1. 后端改动模型/接口后：生成 Alembic 迁移，并 `cd frontend && npm run generate-client` 同步客户端（CI 会校验漂移）。
2. 前端不手写 API URL，统一用 `src/client/` 生成代码。
3. 401 只用于 token 无效/过期（前端自动登出并清缓存）；403 用于权限不足，不触发登出。
4. 后端测试用独立测试库 `app_test`（`conftest` 自动创建），任何情况下不得把测试指向开发库。
5. 生产 `.env` 由部署流水线从 GitHub Secrets 生成，不手改、不提交。
6. 全站用户可见文案必须中英双语（外教使用）：前端用 `useI18n().t({ zh, en })`，参考实现见登录页；后端 `detail` 文案是稳定标识不得随意改措辞。详见 CLAUDE.md「双语准则」。
7. 三端自适应（桌面/手机/iPad）：表单控件字号 ≥16px 防 iOS 聚焦放大、触控目标 ≥44px、新页面过 390/820/1180 三档宽度。详见 CLAUDE.md「三端自适应准则」。
8. 多租户：新业务表用 `_tenant_id_field()` 工厂加租户列；跨校/平台口径用 `PlatformSessionDep`（学校端点禁用）；角色值 school_admin/teacher/student。RLS 已在生产强制，详见 CLAUDE.md「跨模块不变量」多租户条。
9. **先装 pre-commit**：`brew install pre-commit && pre-commit install`。之后每次 `git commit` 自动跑后端的 ruff + ty 和前端的 biome（秒级，与 CI 同口径）。想手动全量跑一遍用 `pre-commit run --all-files`。它不跑测试与覆盖率——那部分仍走第 0 条的 `verify.sh`。
10. **安全漏洞不要建公开 Issue**：私下联系维护者，报告要求与防护现状见 [SECURITY.md](SECURITY.md)。

## 项目管理试点

执行前及收尾时阅读 [docs/project-management.md](docs/project-management.md)，按其中约定关联 Issue、PR、验证与交付证据。实际人工工时未经本人确认保持未记录；客户归属与工时可按用户确认范围公开记录，凭据与学生个人信息不得入库。既有 #222 双轨试运行约定仍有效，需求版本冲突先记录并澄清。

项目身份、客户归属和试点基线见 [docs/project-profile.md](docs/project-profile.md)。

## 项目管理记账（devledger，硬性纪律）

任何 AI 会话（Codex / Claude Code / Cursor 等）完成一个可交付单元后、结束会话前**必须记账**——不可跳过、不可「下次一起补」，没记账的工作等于没做。主账本：GitHub Project `#3`（工具与方法论：本机 `~/.agents/skills/devledger`）。

记账三步：

1. 当轮 commits 聚类成可交付单元（甲方可感知的主题，一次 commit ≠ 一条）；commit message 末尾带 issue 号 `(#N)` 自动关联
2. 按模板建 issue（`.github/ISSUE_TEMPLATE/需求.md`：来源[含甲方原话]/描述[为什么现在做·否决方案·做了什么]/交付物/验证/工时，label=类型；决策上下文记录时写全，事后不可补）。保存 issue URL，已有 issue 直接复用。
3. 用 `python3 ~/.agents/skills/devledger/scripts/bookkeep.py --project 3 --issue <issue URL> --type <类型> --source <来源> --hours <人类等价工时> --start <YYYY-MM-DD> --end <YYYY-MM-DD>` 入板、补字段并读回，确认后关闭 issue。甲方需求加 `--requester <需求人>`。中断后使用相同 URL 和参数续跑。

**issue 是唯一工作真相源**：字段与任何汇总均为派生视图。已知坑与扩展工具见 `~/.agents/skills/devledger/SKILL.md`。

