# AC4 内容治理证据（2026-11-24）

范围：本地开发环境真机走查，验证词条审核链路、发布门禁、词条编辑与发布面板门禁。
**未访问、未部署生产**；生产 vocabulary 模块当前全关，教师侧流程无法在生产验证。

## 环境

- 代码：`feat/ac4-content-review-20261124` worktree（基线 master `efce2db`）
- 本地开发库：Docker Postgres `english-speaking-assessment-db-1` / DB `app`，已执行 `alembic upgrade head`（`e9a7c3f1d5b2 -> ac4d5e6f7a80`）
- 后端：worktree 代码 `127.0.0.1:8002`
- 前端：worktree vite `127.0.0.1:5175`，`API_PROXY_TARGET=http://127.0.0.1:8002`
- 浏览器：系统 Chrome（Playwright），全新上下文，未复用生产会话
- 账号：本地种子校级管理员 `admin@example.com`（口令不记录）；课堂 `AY6S7T`

## 合成验收数据

在本地课堂 `AY6S7T` 新建班级词库 `AC4 审核演示 · AI 草稿`，`source=ai`，6 个词：

| 词条 | 状态 | 说明 |
| --- | --- | --- |
| curious | approved | 审核通过，备注“释义与例句已核对，可发布” |
| playground | approved | 审核通过，同上 |
| notebook | rejected | 审核拒绝，备注“例句过于简单，请补一个校园场景例句后再审” |
| whisper | pending | 待审 |
| library | pending | 待审 |
| carefully | pending | 待审 |

该数据仅存在本地开发库，用于截图；不代表真实学校老师审核记录，也不作为生产种子。

## 截图

1. `01-管理员-审核队列-待审-1180-zh.png`
   - 管理员词库页顶部审核面板：待审徽章 3、状态/来源/关键词筛选、批量条、逐行通过/拒绝/编辑。
2. `02-管理员-审核队列-全部三态-1180-zh.png`
   - `状态=全部` + `来源=AI`：同一屏展示 approved / rejected / pending 三态；非待审行只有编辑，无勾选框与通过/拒绝按钮。
3. `03-管理员-词条编辑弹窗-1180-zh.png`
   - 词条编辑：中文释义、词性、英文释义、例句、音频 URL、可接受拼写、词法拆解；提交携带当前 `expected_version`。
4. `04-教师-审核tab-1180-zh.png`
   - 教师词汇页新增「词库审核」tab，tab 徽章显示待审 3；面板按当前课堂收口。
5. `05-教师-发布门禁-未审不可发布-1180-zh.png`
   - 发布面板：已选 0/2（仅 approved 可勾）；未 approved 的 3 pending + 1 rejected 灰显并标状态；黄色提示“还有 4 个词条未通过审核，不能发布”，附「去审核」。
6. `06-教师-审核tab-390-zh.png`
   - 手机 390 宽：4 个 tab 换行完整可见；审核队列使用卡片布局；`scrollWidth == innerWidth == 390`，无横向滚动。
7. `07-管理员-审核卡片-820-en.png`
   - iPad 820 宽英文：审核队列卡片布局，操作按钮完整可点；`scrollWidth == innerWidth == 820`。
8. `08-管理员-审核队列-1180-en.png`
   - 桌面 1180 英文表格视图。

## 真机断言

- 待审队列默认 3 条；`status=all` 后同一词库 6 条三态齐全。
- approved 词在发布面板可勾选；pending/rejected 不可勾选。
- `/api/v1/vocabulary/books/{id}` 返回的审核字段与 DB 一致：
  `curious approved`、`playground approved`、`notebook rejected`、`whisper/library/carefully pending`，`source=ai`。
- 390/820 页面无横向溢出；1180 表格操作列完整。
- 浏览器 console / pageerror 无报错。

## 相关校验（代码侧）

- 后端全量：1073 passed / 2 skipped / 0 failed，全局覆盖率 93%（services 92% / api 92% / scoring 93% / core 93%）。
- 前端：typecheck 0 错误；`test:unit` 177 passed；`test:components` 18 files / 107 passed。
- OpenAPI 基线零漂移（206 paths / 290 schemas）。
- pre-commit：后端 ruff/ty、前端 biome 通过。

## 边界

- 审核审计历史后端已留痕（`vocabulary_content_review_audit`），本轮未做前端审计列表。
- 教师 Review tab 徽章在进入过一次 Review tab 后由面板数据回填；未进入时显示 0。
- 审核操作、发布 422 的 409/403 等错误路径由后端测试与本地面板参数验证覆盖，未逐条截图。
