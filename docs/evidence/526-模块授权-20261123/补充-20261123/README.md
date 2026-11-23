# #526 模块授权 — B 阶段补充验证证据（2026-11-23）

- 验证日期：2026-11-23（Asia/Shanghai）
- 代码基线：初始 B 阶段基于 master `ff4a1ea4927212d143c85c83c129320a83ad1500`；G4 补验 rebase 到 master `d1fb6685d5510a078df6538226541dce8acf539a`（含 PR #532 教师进步轨迹子路由 speaking 守卫）。补充分支 `docs/526-evidence-supplement`，PR base `master`，**不合并**。
- 环境：仅本机本地 docker compose（db 5433 / backend 8000 / 前端 5173、5174）；浏览器取证统一走 `http://localhost:5174`。**未连接/写入生产库与生产服务器，未触发部署，未改产品代码。**
- 复用 A 校 `e2e-526-a`（仅 speaking，课堂码 `D5V8CH`）、B 校 `e2e-526-b`（仅 vocabulary，课堂码 `VJS6CD`）与既有 `.seed` 测试账号；未新建真实信息。截图仅含匿名代号、课堂码与合成邮箱后缀。
- 本目录是 A 阶段证据（`../README.md`）的补充：G1 补齐 A 阶段未抓到的拦截面板首屏；G2 补三档视口 × 中英文；G3 验证未来 `effective_at` 到点自动放行；G4 补验 PR #532 合入后的教师轨迹子路由守卫。

## 1. G1 · ModuleDeniedPanel 双语首屏（补齐 A 阶段缺口）

### 手段（测试侧冻结，未改产品代码）

教师口语守卫 `t.$code.index.tsx` 在 `guard === "denied"` 的 effect 内立即 `navigate({ to: "/classrooms" })`，面板一帧即被卸载，普通轮询抓拍不到。本次用 CDP 条件断点在守卫跳转前持有页面：

- `Debugger.setBreakpointByUrl` 定位 `t.$code.index.tsx?tsr-split=component` 守卫行，条件 `guard === "denied"`；
- 断点命中、组件分支已提交到 DOM 后，`Page.captureScreenshot` 取证；取证后 `Debugger.resume` 放行，页面按原守卫逻辑跳转 `/classrooms`（正常跳转已回归验证）。
- 历史 API（`history.pushState/replaceState`）no-op 冻结方案已试：TanStack Router 路由状态由 history `notify` 独立驱动，冻 history 不能阻止内存路由切换，面板仍被卸载，故未采用。

### 结果

| 文件 | 语言 | 可见文案 | 按钮 |
|---|---|---|---|
| `G1-面板-zh.png` | 中文 | 本校暂未开通口语模块。 | 回课堂列表 |
| `G1-面板-en.png` | English | The speaking module is not enabled for this school. | Back to Classes |

- 「双语」= zh / en 两个语言模式分别验证对应文案；面板 `useI18n().t` 只渲染当前语言，不同屏双行显示。
- 场景：B 校教师（speaking 未购）直连 `/t/VJS6CD`；面板挂载在教师工作台布局内，侧栏为 B 校教师底座导航。
- 服务端闸门佐证：`GET /classes/VJS6CD/today` 403 `module_not_enabled:speaking`（见 A 阶段 `api-probe.json`）。

## 2. G2 · 三档视口 × 中英文矩阵

三档视口：390×844（手机）、820×1180（平板竖屏）、1180×820（桌面横屏）；每档 zh / en。场景：教师导航（B 教师 `/classrooms`，speaking 入口隐藏）、学生导航（B 学生 `/vocab/VJS6CD`，vocabulary 入口可见、口语入口隐藏）、未购模块拦截面板（B 教师 `/t/VJS6CD`，同 G1 断点持有）。

### 截图矩阵

| 视口 | 教师 zh | 教师 en | 学生 zh | 学生 en | 面板 zh | 面板 en |
|---|---|---|---|---|---|---|
| 390×844 | `G2-390-zh-教师导航.png` | `G2-390-en-教师导航.png` | `G2-390-zh-学生导航.png` | `G2-390-en-学生导航.png` | `G2-390-zh-面板.png` | `G2-390-en-面板.png` |
| 820×1180 | `G2-820-zh-教师导航.png` | `G2-820-en-教师导航.png` | `G2-820-zh-学生导航.png` | `G2-820-en-学生导航.png` | `G2-820-zh-面板.png` | `G2-820-en-面板.png` |
| 1180×820 | `G2-1180-zh-教师导航.png` | `G2-1180-en-教师导航.png` | `G2-1180-zh-学生导航.png` | `G2-1180-en-学生导航.png` | `G2-1180-zh-面板.png` | `G2-1180-en-面板.png` |

### 布局观察（实测记录）

- **横向滚动**：三档 × 两语言共 18 张，`document.documentElement.scrollWidth` 均等于 `innerWidth`，未出现横向滚动条；按钮未被视口边缘遮挡。
- **390 手机档**：侧栏折叠为顶部工具条，导航条目进入顶部/卡片流；面板英文提示在窄宽下自然换行两行（`The speaking module is not enabled for this school.`），文案未截断，按钮完整可见。
- **820 平板档**：侧栏展开；教师课堂卡片内的副文案（`Limit 30`、`Lead teacher: B 校教师`）在窄卡片内换行排列，属正常折行，无裁切或重叠。
- **1180 桌面档**：侧栏 + 主区双栏布局，条目与按钮排布正常。
- 导航过滤在三档两语言下均生效：B 教师侧栏无口语教学项；B 学生侧栏仅词汇学习组 + 我的班级，无口语组条目。

## 3. G3 · 未来 `effective_at` 到点自动放行

### 流程

1. t0：A 校 vocabulary 关闭。学生 A `/modules/me` 仅 `speaking`；词汇主页侧栏无「词汇学习」分组；`farm`、`pk/lobby` 均 403 `module_not_enabled:vocabulary`（截图 `G3-t0-学生导航隐藏.png`）。
2. 超管后台口径调接口：A 校 vocabulary 置为开启，`effective_at = now + 120s`（`2026-11-23T06:46:12.286235Z`）。
3. 未到点：`/modules/me` 仍仅 `speaking`，词汇端点仍 403（后端 `_row_active` 判定 `effective_at > now` 不计入）。
4. 到点后（同一浏览器上下文，未登出/未重登）：
   - **SPA 未刷新前**：`useModules` 查询 `staleTime = 5 分钟`，侧栏仍按旧缓存隐藏词汇入口（未观察到无刷新自动出现）。
   - **整页 reload 后**：`/modules/me` 返回 `["speaking", "vocabulary"]`；侧栏出现「词汇学习」分组（`G3-到点-词汇入口出现.png`）；词汇主页 PK / 农场入口可见（`G3-到点-词汇主页PK农场.png`）；`farm`、`pk/lobby` 均 200。
5. 验完收回：A 校 vocabulary 改回关闭（`effective_at = null`）；恢复后 `/modules/me` 回到仅 `speaking`，词汇端点恢复 403；审计留下 grant（未来生效）与 revoke 两条记录，含操作人 UUID、前后开关值、生效时间前后、时间戳。

### 机读证据：`api-probe-future.json`

- `planned_effective_at`：计划生效时间（UTC ISO）。
- `steps`：`t0_before_grant` / `t0_after_grant_future_not_due` / `t_due_after_effective_at` / `after_restore_off`，每步含时间戳、`modules_me` 返回、各词汇端点 HTTP 状态码与 `detail`。
- `grant_response` / `restore_response`：两次超管改写的状态码与响应体。
- `audit_after_restore`：收回后拉取的 A 校模块授权审计原始记录（10 行，含本次 grant/revoke）。

### 关键结论

- 后端按请求时刻评估 `effective_at`：未到点按未购 403，到点后自动纳入已购清单，无需后端人工干预。
- **前端不保证无刷新放行**：模块清单查询缓存 5 分钟，到点后同一会话内需整页 reload（或等缓存失效后重新拉取）才刷新导航显隐；本次如实记录为「同一会话内 reload 后生效」，未写成无刷新自动出现。

## 4. G4 · 教师进步轨迹子路由守卫（PR #532 合并后补验）

### 被测范围

- 路由 `/t/$code/s/$studentId`（`frontend/src/routes/t.$code.s.$studentId.tsx`，PR #532 `cfd2783` 合入 master `d1fb668`）：按 `moduleGuardState(..., "speaking")` 判定；`denied` 分支返回 `ModuleDeniedPanel`，**不发 navigate**——与父级 `/t/$code` 守卫不同（父级在 effect 内跳 `/classrooms`，子路由按设计停留面板，便于核对/截图）。
- 学生 ID 来源：本地测试库只读查询 `student` 表按课堂关联取得。`/classes/{code}/board` 名册接口在 A 校因无在练篇目 404（`No active passage`）、B 校被 speaking 闸门 403，不能作为名册来源。**路由参数是学生档案 ID（`student.id`），不是登录用户 ID**：
  - A 校：`1df80d3a-d571-4314-8da7-73752e906a32`（`stu-a01`，档案名「A校学生」）
  - B 校：`bea9fe6d-a905-4a79-8f13-14466c3aad65`（`stu-b01`，档案名「B校学生」）

### 浏览器结果

| 文件 | 场景 | 观察 |
|---|---|---|
| `G4-子路由面板-zh.png` | B 校教师直连 `/t/VJS6CD/s/bea9fe6d-a905-4a79-8f13-14466c3aad65` | 面板「本校暂未开通口语模块。/ 回课堂列表」；停留 2.5s 后 URL 仍在子路由，**无自动跳转** |
| `G4-子路由面板-en.png` | 同上，en 模式 | 「The speaking module is not enabled for this school. / Back to Classes」；停留不跳 |
| `G4-A校对照-轨迹页-zh.png` | A 校教师直连 `/t/D5V8CH/s/1df80d3a-d571-4314-8da7-73752e906a32` | 正常进入轨迹页：学生学习档案「A校学生」、课堂 `D5V8CH`、阶段报告与历史记录空态（无已完成作答） |
| `G4-B校词汇工作台-zh.png` | B 校教师 `/t/VJS6CD/vocab`（回归） | 词汇任务工作台正常渲染（发布任务 / 完成情况 / PK 对战），无回归 |

### 服务端探针佐证

- B 校教师 `GET /classes/VJS6CD/trail?student_id=bea9fe6d-…` → `403` `module_not_enabled:speaking`（闸门先于名册/轨迹数据返回）。
- A 校教师 `GET /classes/D5V8CH/trail?student_id=1df80d3a-…` → `200`，`sessions` 为空（测试班无已出分作答）。

### 既有行为回归

- 父级 `/t/VJS6CD`（B 校教师，speaking off）：直连后仍按父守卫 effect 跳回 `/classrooms`（本次实测落地 URL 为 `/classrooms`，课堂列表正常），行为未变；面板可视文案复用 G1 `G1-面板-zh.png`（G4 回归时点复核，未重新断点抓拍）。
- `/t/VJS6CD/vocab`：vocabulary on，工作台可进，截图见上表。

### 失败尝试与备注

- 子路由面板原生停留，本次**未使用** G1 的 CDP 条件断点 / history 冻结手段。
- 排查中曾误把登录用户 ID 当作路由参数：A 侧 trail 返回 404 `Student not found`；核对测试库后确认路由参数应为档案 ID，已更正后复测通过。

## 5. 未覆盖项与限制

1. G3 未验证「到点瞬间轮询/后台自动刷新」链路：本次以 reload 后生效为准；前端是否需要在清单过期后主动 invalidate，属后续优化项。
2. G2 视口以 CDP 设备模拟覆盖验证；未在真实手机/平板设备上实测触摸与安全区（刘海/home 指示条）适配。
3. 面板抓拍依赖调试器断点持有，属测试侧手段；生产构建下的首屏表现未单独复测。
4. 双语核对以本次 zh/en 两模式截图为准；其余空态、审计文案未逐条切 EN 比对。
5. 测试班未 seeded 已发布篇目/词库，部分主页空态（「学习计划暂时没有加载成功」等）属业务数据为空，非模块拦截。
6. G4 仅在桌面 1280×960 视口取证；子路由面板未在 390/820/1180 三档视口下复测（G2 矩阵覆盖的是父级面板）；A 校轨迹对照页仅验 zh，未切 en。

## 6. 隐私与数据边界

- 截图与机读证据仅含匿名测试代号（`e2e-526-a/b`、`D5V8CH`、`VJS6CD`、`stu-a01/b01`、`*.e2e526.seed`）；无真实校名、真实师生姓名、手机号、访问 token。
- 既有真实学校数据全程只读；本次造数/改写仅限两所匿名测试校，验完已还原模块状态。
