# #526 上线后浏览器补验证据（2026-11-23）

- 验证日期：2026-11-23（Asia/Shanghai）
- 代码基线：master `fe4a6b4dbfde2804a57cebbbe010ddafe9390bb3`；2026-11-25 整理为独立证据 PR 归档，**不改产品代码、不部署**。
- 环境：仅本机本地 docker compose（db 5433 / backend 8000 / 前端 5173、5174）；浏览器取证统一走 `http://localhost:5174`。**未连接/写入生产库与生产服务器，未触发部署，未改产品代码。**
- 复用 A 校 `e2e-526-a`（仅 speaking，课堂码 `D5V8CH`）、B 校 `e2e-526-b`（仅 vocabulary，课堂码 `VJS6CD`）与既有 `.seed` 匿名账号；本轮新建的临时班级/词库/作答状态验完已清理（见 §3 清理记录）。截图与机读证据仅含匿名代号、课堂码与合成邮箱后缀，无真实姓名/手机号/token。
- 本目录是 `../README.md`（G1–G4 桌面阶段）的上线后补充：① G4 子路由面板补三档视口 × 中英；② 教师面板「导出 CSV」完整真实浏览器下载链路；③ 跨班 FSRS 复习连续性（浏览器级 + API 级）；④ G3b 验证 PR #537（清单 staleTime 45s + 聚焦重取）到点后零整页 reload 自动放行。

## 1. G4 补验 · 子路由面板三档视口 × 中英

### 被测场景

B 校教师（speaking off）直连教师进步轨迹子路由 `/t/VJS6CD/s/[student-id]`（B 学生档案 ID，取自本地测试库 `student` 表，非编造）。守卫 `t.$code.s.$studentId.tsx` 在 `denied` 分支返回 `ModuleDeniedPanel`，**不发 navigate**，面板停留。

### 截图矩阵（390×844 / 820×1180 / 1180×820 × zh/en）

| 视口 | zh | en |
|---|---|---|
| 390×844（手机） | `G4-390-zh.png` | `G4-390-en.png` |
| 820×1180（平板竖屏） | `G4-820-zh.png` | `G4-820-en.png` |
| 1180×820（桌面横屏） | `G4-1180-zh.png` | `G4-1180-en.png` |

### 实测观察

- 六张均为 CDP `Emulation.setDeviceMetricsOverride` 覆盖视口后截取；每张读取 `innerWidth / innerHeight / scrollWidth / scrollHeight` 与面板文案。
- **横向滚动**：六张 `document.documentElement.scrollWidth` 均等于 `innerWidth`，无横向滚动条；按钮未被视口边缘遮挡。
- **文案在屏**：
  - zh：「本校暂未开通口语模块。」+「回课堂列表」按钮。
  - en：「The speaking module is not enabled for this school.」+「Back to Classes」按钮。
  - 390 窄宽档 en 长句自然换行两行，未截断；按钮完整可见。
- 与桌面 1280 阶段（`../` G4 两张子路由面板截图）行为一致：面板停留，不自动跳转。

## 2. G5 · 教师面板「导出 CSV」完整下载链路

### 手段

A 校教师（speaking on）在浏览器打开 `/t/D5V8CH`，切到学生结果/今日名单标签页，点击名单卡片「导出」按钮；CDP `Page.setDownloadBehavior` 允许下载并指向本目录 `downloads/`，捕获浏览器真实下载事件落地的文件，再与页面名单（board 名册）逐项对照。

链路：`BoardRosterCard onExportCsv → boardRosterCsv(filteredStudents, classroom_code, t) → downloadCsv(rows, filename)`，浏览器 Blob URL + `<a download>` 触发，非接口直出。

### 机读证据：`export-download.json`

- 触发按钮：教师面板「导出 / Export」；页面 `/t/D5V8CH`。
- 下载文件：`downloads/课堂D5V8CH-练习名单-2026-11-23.csv`（原始文件仅本地留存、未入库，避免仓库 `text=auto` 把 CRLF 规范化为 LF 导致字节/哈希与取证快照不一致），124 字节，UTF-8 BOM（RFC 4180 CRLF），sha256 `9f9a39e8f155302935135a2fc23d9ec55abcb54cf656333a89773a2345361b9b`。
- 表头 8 列：姓名 / 区分码 / 完成题数 / 跟读均分 / 情景问答均分 / XP / 连胜天数 / 状态。
- 数据行 1 行；board API 名册人数 1，`match=true`。
- 面板截图：`G5-教师面板名单-zh.png`（1280×960，可见班级学生 1、今日名单 1/1 人、导出按钮）。

### 备注与失败尝试

- A 校本地课堂原本无在练篇目，board 404 `No active passage`，教师面板走空态分支、无名单与导出按钮。为解锁本地名单，以 A 校教师身份临时补了一条标题带 `[e2e-roster-probe]` 标记的匿名篇目；**验完已删除**，复核 board 回到 404，两校模块终态不变。
- CSV 空均分单元格按公式注入防护规则加 `'` 前缀（`'-`），属预期转义，非脏数据。
- 下载文件内仅含合成代号「A校学生」，无真实 PII；机读 JSON 未记录 token。

## 3. G6 · 跨班 FSRS 复习连续性（浏览器级 + API 级）

### 验证设计

同一 `.seed` 学生账号 `stu-b01`（B 校 vocabulary on）加入 B 校两个本地班级：既有班 `VJS6CD`（班1）+ 本轮临时新建班 `P56P78`（班2）。班1 自主开一轮、首答故意答错，留下 FSRS 状态；不做任何班2 作答，直接在班2 读取复习统计与到期队列，核对状态是否按账号延续、历史 session 是否仍归属原班。

机读证据：`cross-class.json`；浏览器截图：

| 文件 | 页面 | 观察 |
|---|---|---|
| `G6-跨班-班1-复习队列-zh.png` | `/vocab/VJS6CD` | 今日到期 1 / 已复习 1 / 剩余 19 / 上限 20；队列行 `probecat` · 拼写 · 今日到期 · 上次答错 · 间隔 1 天 · 复习 1 · 遗忘 1；错词本含该词错 1 次 |
| `G6-跨班-班2-复习队列-zh.png` | `/vocab/P56P78` | 同一队列行 `probecat` · 拼写 · 今日到期 · 上次答错 · 间隔 1 天 · 复习 1 · 遗忘 1；错词本为空、无练习记录（历史未迁移） |

### 浏览器级验证了什么

- 班2 词汇页「今日复习」统计与班1 一致：`tracked=1 / learning=1 / spelling=1`，到期队列命中同一词条，调度字段（state/reps/lapses/last_is_correct）一致。
- 班2 错词本为空、学习建议为「还没有练习记录」：首答历史与错词本未跨班带出，历史记录仍属原班。

### API / 数据库级佐证（本地测试库只读查询）

- `vocabulary_review_state` 唯一约束 `(user_id, word_id, capability)`：该行按账号 `7644eced-…` 汇总，`probecat` · `spelling` · `learning` · `reps=1` · `lapses=1` · `last_is_correct=false`；班1/班2 队列接口读到的是同一行。
- `vocabulary_session` / `vocabulary_answer`：本轮 session `79c5e95c-…` 与首答（attempt_no=1，未答对）仍绑定 `VJS6CD`；班2 `P56P78` 名下该账号 session/answer 行数为 0，未被迁移或改写快照。
- 能力维度分列：`spelling_count=1`、`recognition_count=0`。
- 队列可见性按当前班可练词库过滤（active public/本班库内 active 词条）；状态按账号汇总，可见性按课堂词库过滤。

### 测试侧调整说明

- 新卡 again 评分后稳定性 0.4072 天，首次到期时间在未来，此刻到期队列为空。为同时观察队列级连续性，在**本地测试库**把该卡 `due_at` 回拨到当前时间前 1 小时；未改动 `state/reps/lapses/stability/difficulty` 等调度字段，未改调度算法，生产库无此操作。
- 临时共享词库（标题 `[e2e-cross-class] 临时共享词库`，public，词条 `probecat/probecow`）由 B 校管理员经本地 API 创建，供两班可见。

### 清理记录（验完已还原）

- 临时班 `P56P78`：`DELETE /classes/P56P78?delete_history=true` → 200「课堂已删除」。
- 本地库直清本轮残留：`vocabulary_answer` / `vocabulary_session` / `vocabulary_review_state`（该 user+word）/ `vocabulary_book_item` / `vocabulary_word`（probecat、probecow）/ `vocabulary_book`（临时词库）。
- 复核：该账号 review_state 0、临时词库 0、临时词条 0、临时词条项 0、临时班级 0、该账号 session 0。
- 两校模块终态：A `["speaking"]`、B `["vocabulary"]`，与测试前一致。

### 失败尝试与备注

- 初始尝试复用种子公开词书 `f96c19b6-…`（Pets & School）：该词书归属 seed 默认租户，本地 RLS 下 B 校会话不可见，自主轮 `book_id` 报 404「词库不存在或已归档」；改为 B 校同租户自建 public 临时词库后通过。
- 农场 XP / 徽章跨班连续性本轮未单独截图验证（任务口径二选一或都做，FSRS 为主口径）；农场账本复用既有账号口径，不在本次回归范围。

## 4. G3b · PR #537 清单 staleTime 45s 聚焦重取（零整页 reload）

### 被测对象

- PR #537（分支 `fix/modules-refetch-45s`，head `8b1ece3`）：`useModules` 清单查询 `staleTime = 45s`、`refetchOnWindowFocus: true`，由 react-query 内置 focusManager 监听窗口聚焦/可见性变化，仅当缓存超过 45s 才重取；不另写全局 visibilitychange 轮询。
- 前端不从主 worktree 起：从 PR #537 代码所在 worktree `agents/s_000Vum426Xa/worktree-modules`（HEAD `8b1ece31bb82a4ffd0505a6cb158b644edb5e6e2`）独立起 Vite dev server `http://127.0.0.1:5176`，`/api` 代理本地 8000；已核对该服务源码含 `MODULES_STALE_TIME_MS = 45 * 1000` 与 `refetchOnWindowFocus: true`。

### 验证设计

A 校教师（`teacher-a@e2e526.seed`，课堂 `D5V8CH`）经本地平台接口把 speaking 置为 `enabled=true, effective_at = now + 90s`；到点前 `/modules/me = []`，侧边栏口语门禁入口（「题目库」`/create`、「录音导出」`/exports`）隐藏。不刷新页面，等到点后缓存超过 45s，经聚焦/可见性路径触发一次重取，核对清单回到 `["speaking"]`、入口自动出现，且期间无整页 reload、无轮询风暴。

### 机读证据：`module-refetch-45s.json`

- 文档生命周期内 `/modules/me` 共 **2** 次请求：#1 挂载（10:30:46.392Z，到点前，body `[]`）；#2 聚焦/可见性重取（10:32:49.424Z，到点后 52.9s，body `["speaking"]`，直连 API 快照佐证）。
- 两次间隔 **123.032s**，缓存年龄 123.032s > 45s staleTime；无 45s 内重复切 tab 触发的重复请求，无定时轮询。
- 零 reload：挂载后注入的 `g3b-marker` 重取后仍存活；`history.length` 前后均为 50；PerformanceResourceTiming 缓冲仍同时保留两条记录（reload 会清空缓冲）。
- 侧边栏：到点前 `[我的课堂, 平台更新]`；到点后 `[我的课堂, 录音导出, 题目库, 平台更新]`。

### 浏览器截图

| 文件 | 页面 | 观察 |
|---|---|---|
| `G3b-未到点-课堂列表-zh.png` | `/classrooms`（到点前） | 侧边栏仅「我的课堂」「平台更新」，无「题目库」「录音导出」；课堂 D5V8CH 卡片可见 |
| `G3b-到点后-入口自动出现.png` | `/classrooms`（到点后重取） | 侧边栏出现「录音导出」「题目库」；同一标签页、未整页刷新 |

### 环境限制与失败尝试（如实记录）

- 嵌入式自动化浏览器在真实切标签时不派发原生 `visibilitychange`/`focus`：页面探针监听两个事件，切走再切回日志为空，`document.hasFocus()=false`。本轮 #2 重取是在 `window` 上派发 `visibilitychange` 触发的，走的是 focusManager 注册在 window 的同一监听；真实浏览器原生 OS 聚焦/标签可见性路径未在本轮自动化中直接观察到。
- 页面内 fetch 包装器未截获 SDK 请求（生成客户端初始化时持有 `globalThis.fetch` 引用）；请求次数与时间取自 `PerformanceResourceTiming`，响应体由直连 API 快照佐证。
- 教师父路由 `t.$code.index.tsx` 在 `denied` 的 effect 内立即 SPA 跳转 `/classrooms`，拦截面板只渲染一帧；本轮未在该分支抓到稳定面板帧。双语面板首屏已由本目录 G1/G4 既有 committed 证据覆盖，本块不重复抓拍、不补造面板截图。

### 清理记录

- A 校 speaking 恢复 `enabled=true, effective_at=null`；复核 `/modules/me = ["speaking"]`，本地库 `tenant_module` 行 `e2e-526-a / speaking / t / effective_at=null`。
- B 校未触碰，终态 `["vocabulary"]`；两校模块终态与测试前一致。

## 5. 未覆盖项与限制

1. 三档视口仍为 CDP 设备模拟；未在真实手机/平板上实测触摸与安全区适配。
2. G6 仅验证 FSRS 复习状态与历史 session 归属；农场 XP 跨班连续性、徽章/连胜跨班口径未回归。
3. G6 词库为本轮自建临时 public 词库；种子演示词书在多租户 RLS 下的跨班可见性未在本轮验证。
4. 浏览器取证基于本地 5174 挂载前端；生产构建首屏表现未单独复测。
5. 本轮截图以 zh 为主；G6 两班队列未切 en 复核文案。

## 6. 隐私与数据边界

- 截图与机读证据仅含匿名测试代号（`e2e-526-a/b`、`D5V8CH`、`VJS6CD`、`P56P78`、`stu-a01/b01`、`probecat/probecow`、`*.e2e526.seed`）；无真实校名、真实师生姓名、手机号、访问 token。
- 既有真实学校数据全程只读；本轮造数/改写仅限两所匿名测试校与临时班/词库，验完已清理并还原模块状态。
