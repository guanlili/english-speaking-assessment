# #517 租期 / 试用 / 用量 本地真机取证证据

> 取证日期：2026-11-24（Asia/Shanghai）。本次仅在**本地开发环境**操作，未部署生产、未访问任何生产地址、未跑 devledger。截图与 CSV 内不含真实学生/真实学校信息；可见的课堂/教师名为本地 e2e 演示数据。

## 1. 环境

| 项 | 值 |
|---|---|
| Worktree | `…/agents/o_000VxxkxFsS/tenant-ops` |
| 分支 | `feat/tenant-license-usage-20261124` |
| 取证时 HEAD | `eef628dd1b656317ab6d542dd7ee82ae0a40b591`（操作人不再展示内部 UUID，统一归为“平台运营 / Platform operator”） |
| 任务基线 HEAD | `e39e4e7`；其上依次为 `4b0b9cd`（后端到期日校验）、`48afbe6`（首轮证据提交）、`2020e73`（单复数修复）、`826aa5b`（二轮证据提交）、`eef628d`（操作人去 UUID） |
| 工作区状态 | 除本证据目录外无改动，未修改任何业务代码 |
| 后端 | `127.0.0.1:8006`（uvicorn，代码即本 worktree） |
| 前端 | `127.0.0.1:5176`（Vite，`API_PROXY_TARGET=http://127.0.0.1:8006`） |
| 数据库 | Docker `english-speaking-assessment-db-1`，`localhost:5433` / 库 `app`，迁移 head `e5f6a7b8c9d0`（`d6372fd6a828` 之后仅重命名既有索引，不改数据） |
| 浏览器 | 附加 Chrome，经 `browser_use`（plane=`bu`）+ CDP `Emulation.setDeviceMetricsOverride`；常规视口 `deviceScaleFactor=1`、`mobile=false`；二轮另试 `mobile=true / deviceScaleFactor=2 / TouchEmulation`（见 §7） |
| 视口三档 | 390×844 / 820×1000 / 1180×1000 |
| 主仓 8000/5173 | 未触碰（仍由 Docker 容器占用） |

登录：平台运营走 `/platform/login`，学校管理员走 `/login`；账号 `admin@example.com`，密码仅从本地 `.env` 的 `FIRST_SUPERUSER_PASSWORD` 读取，未写入本 README、日志或回报。

## 2. 合成演示数据（全部本地库，仅用于截图）

6 所示范学校 slug 固定，名称中英双语且以“演示 / Demo”开头；`speaking` 模块均未授权，避免干扰。

| slug | 名称（zh / en） | 单词模块状态 | 授权类型 | 到期 / 生效 | 截图徽标 |
|---|---|---|---|---|---|
| `demo-lic-trial` | 演示·试用中校 / Demo Trial School | active（试用中） | trial | 到期 now+5d（剩 5 天） | 试用中 · 剩 5 天 / Trial · 5 days left |
| `demo-lic-expired` | 演示·已到期校 / Demo Expired School | expired（已到期） | trial | 生效 now-10d，到期 now-1d | 已到期 / Expired |
| `demo-lic-closed` | 演示·已关闭校 / Demo Closed School | disabled（已关闭） | trial | 生效 now-10d，到期 now-1d；`enabled=false` | **已关闭 / Closed**（不显示“已到期”） |
| `demo-lic-notgranted` | 演示·未开通校 / Demo Not Granted School | not_granted（无模块行） | — | — | 未开通 / Not granted |
| `demo-lic-scheduled` | 演示·待生效校 / Demo Scheduled School | scheduled（待生效） | paid | 生效 now+2d，长期 | 待生效 / Scheduled |
| `demo-lic-active` | 演示·使用中校 / Demo Active School | active（使用中） | paid | 长期（无到期） | 使用中 / Active |

默认学校 `default`（id `00000000-0000-0000-0000-000000000001`）：取证期间依次置为 trial +5d（模块弹窗/审计/用量）→ +30d → +7d → +1d（横幅三档），**取证结束已恢复 `grant_type=manual`、`expires_at=null`（长期）**。 speaking 模块为 manual 长期 active。

## 3. 截图清单（15 张 PNG）

文件名两位序号；宽表在窄屏允许组件内部横滑，整页不得横向溢出。

### 运营端（平台运营登录 `/admin/schools`）

| 文件 | 视口 / 语言 | 看到了什么 | 断言 |
|---|---|---|---|
| `01-list-1180-zh.png` | 1180 / 中文 | 六态徽标齐全：试用中·剩 5 天、已到期、已关闭、未开通、待生效、使用中；近 7 天 / 近 30 天用量列 | 六态可在列表找到；`demo-lic-closed` 显示“已关闭”而非“已到期” |
| `02-list-820-zh.png` | 820 / 中文 | 学校码/名称/状态列可见，宽列在容器内横滑 | 整页无横向溢出 |
| `03-list-390-zh.png` | 390 / 中文 | 侧边栏收为顶栏；表格仅露出学校码/名称，其余列内部横滑 | 整页 `scrollWidth == innerWidth`，无整页横溢 |
| `04-list-1180-en.png` | 1180 / 英文 | Vocabulary: Trial · 5 days left / Expired / Closed / Not granted / Scheduled / Active | 英文徽标齐全；Closed ≠ Expired；界面文案无中文残留（校名除外） |
| `05-list-390-en.png` | 390 / 英文 | Schools / New school / All schools / CODE / NAME 全英文 | 390 无整页横溢；无中文 UI 残留 |
| `06-filter-expiring7-1180-zh.png` | 1180 / 中文 | 筛选下拉选中“7 天内到期”；结果仅 `default`（剩 5 天）与 `demo-lic-trial`（剩 5 天） | 7 天到期筛选不出现 expired / closed / not_granted / scheduled / active |
| `07-module-dialog-1180-zh.png` | 1180 / 中文 | 默认校单词试用卡：状态“试用中·剩 5 天”、授权类型“试用”、到期 `2026/11/29 06:30`、剩余 5 天；“上次更新：…· **平台运营**”；变更历史行可见 | 字段完整；审计前后值可见（非只显示当前值）；操作人显示“平台运营”，画面无 UUID |
| `08-module-dialog-820-en.png` | 820 / 英文（390 兜底，见 §7） | Module access · default；Speaking Active Manual；Vocabulary Trial · 5 days left，Grant Trial，Expiry `2026/11/29 06:30`；`Last updated: … · **Platform operator**`；Change history `Manual → Trial` | 字段完整、弹窗内可读；操作人显示 `Platform operator`，画面无 UUID；390 布局经 JS 实测见 §5 |
| `09-audit-table-1180-zh.png` | 1180 / 中文 | 变更历史行：开关 `开 → 开`、类型 `人工 → 试用`、开始 `立即 → 立即`、到期 `长期 → 2026/11/29 06:30:50`；操作人列 DOM 显示 `平台运营`（画面因表内横滑未整列露出） | `grant_type_before → after`、`expires_at_before → after` 清楚可读；操作人无 UUID；审计表容器可横滑 |
| `10-usage-dialog-1180-zh.png` | 1180 / 中文 | 学校用量 · default，区间 `2026/10/26 – 2026/11/24`；9 项总量卡；口径说明 2 条；每日明细表头与前若干行 | 9 项 totals、每日表、两条 limitations 均在；无学生标识 |
| `11-usage-dialog-820-en.png` | 820 / 英文（390 兜底，见 §7） | School usage · default；From/To 同区间；Download CSV；Notes 2 条；9 张英文指标卡；每日表 DATE/TEACHERS/… | totals 与弹窗一致；390 布局经 JS 实测见 §5；无中文 UI 残留 |

### 学校管理员（学校登录 `/classrooms`，角色 `school_admin`）

| 文件 | 视口 / 语言 | 看到了什么 | 断言 |
|---|---|---|---|
| `12-banner-trial-30d-1180-zh.png` | 1180 / 中文 | 横幅 level `trial`（中性 primary 色，Clock 图标）：“单词模块试用还剩 30 天”；副文案“到期后师生入口关闭，数据保留，请联系平台续期。” | 30 天档 trial 色；校管可见横幅；副文案含入口关闭/数据保留/联系平台 |
| `13-banner-warning-7d-390-zh.png` | 390 / 中文 | level `warning`（amber 琥珀色，TriangleAlert 图标）：“单词模块试用还剩 7 天” + 同一副文案 | 7 天档 warning 色；390 无整页横溢 |
| `14-banner-critical-1d-390-en.png` | 390 / 英文 | level `critical`（destructive 红色，ShieldAlert 图标）：“Vocabulary trial: **1 day left**”；“After expiry, teacher and student entry closes; data is retained. Contact the platform to renew.” | 1 天档 critical/destructive 色；英文单复数正确（`1 day left`）；无中文残留；副文案含 entry closes / data retained / contact platform |
| `15-banner-critical-1d-1180-en.png` | 1180 / 英文 | 同上 critical 横幅（`1 day left`），宽屏侧边栏全英文 | 宽屏 critical 档复核；无中文 UI 残留 |

## 4. CSV 产物核对

文件：`tenant-default-usage-20261124.csv`（默认校近 30 天，`2026-10-26 ~ 2026-11-24`）

- 编码：UTF-8 **BOM**（首三字节 `EF BB BF`），Excel 可直开。
- 行数：**31 行** = 1 表头 + 30 个自然日。
- 列数：**10 列**，表头顺序：

  ```
  日期, 活跃教师数, 活跃学生数, 词汇作答数, 发布任务数, 完成任务人数, PK 对局数, 农场收获数（下限）, placement 测试数, 导出次数
  ```

- 末行 `2026-11-24, 1, 3, 54, 1, 1, 0, 0, 4, 0`；首日 `2026-10-26, 0, 0, 0, 0, 0, 0, 0, 0, 0`。
- 无学生 id / 姓名 / 邮箱：正则扫描 0 个 UUID；CSV 仅日期 + 聚合数。
- `farm_harvests`（农场收获数（下限））列存在。
- CSV 逐日求和与弹窗/API totals **逐项一致**：

  | 指标 | totals |
  |---|---|
  | active_teachers 活跃教师数 | 4 |
  | active_students 活跃学生数 | 14 |
  | vocab_answers 词汇作答数 | 110 |
  | published_tasks 发布任务数 | 5 |
  | completed_students 完成任务人数 | 4 |
  | pk_matches PK 对局数 | 4 |
  | farm_harvests 农场收获数（下限） | 1 |
  | placement_tests placement 测试数 | 4 |
  | exports 导出次数 | 0 |

- 对照来源：`GET /api/v1/admin/tenants/00000000-…/usage?from=2026-10-26&to=2026-11-24` 返回相同 totals、30 行、2 条 limitations、时区 `Asia/Shanghai`。
- 下载方式说明：弹窗「下载 CSV」按钮触发的请求经代理返回 200（`…/usage.csv?from=2026-10-26&to=2026-11-24`）；本次附加浏览器会话未把 blob 落盘（无头下载通道未捕获），证据 CSV 取自**同一产品端点**并与弹窗逐项核对一致。

## 5. 真机断言数字（`document.documentElement.scrollWidth` vs `window.innerWidth`）

整页无横向溢出（组件内部横滑除外）；读数来自 `bu.js` 实测。

| 页面 / 视口 | scrollWidth | innerWidth | 结论 |
|---|---|---|---|
| 学校列表 1180 | 1180 | 1180 | 相等 |
| 学校列表 820 | 820 | 820 | 相等 |
| 学校列表 390 | 390 | 390 | 相等 |
| 模块弹窗 390（页面层） | 390 | 390 | 相等 |
| 模块弹窗 390（弹窗卡片） | client 388 / scroll 388 | — | 卡片自身无横溢；审计表容器 client 336 / scroll 1097，**内部横滑** |
| 用量弹窗 390（页面层） | 390 | 390 | 相等 |
| 用量弹窗 390（弹窗卡片） | client 388 / scroll 388 | — | 卡片自身无横溢；明细表容器 client 338 / scroll 338，列宽自适应不溢出 |
| 校管横幅页 1180 | 1180 | 1180 | 相等 |
| 校管横幅页 390 | 390 | 390 | 相等 |

## 6. 状态机 / 校验 / 审计 / 横幅核对

- **六态**：`not_granted`（无模块行）→ `disabled`（`enabled=false`，优先级最高）→ `scheduled`（生效时间在未来）→ `expired`（已过到期）→ `active`。API 复核与上表一致。
- **closed 优先**：`demo-lic-closed` 虽也已过期，但 `enabled=false` 判 `disabled`，徽标为“已关闭 / Closed”，不是“已到期 / Expired”（见 01、04）。
- **7 天筛选**：`expiring_within_days=7` 仅返回临近到期的 active trial；取证后默认校已恢复长期，当前接口结果只剩 `demo-lic-trial`（剩 5 天），不含 expired / closed。截图 06 拍摄时默认校仍为 +5d，故结果为 default + trial 两条。
- **trial 必填到期**：
  - 前端 `validateModuleForm`：trial 未填到期 → 双语错误“试用必须设置到期时间 / A trial requires an expiry date”。
  - 后端实测探针：`PUT …/modules/vocabulary` 带 `grant_type=trial, expires_at=null` → **HTTP 422**，`detail=trial_requires_expires_at`，数据未被改写；填到期后保存成功（模块弹窗 07/08 即为填到期后的成功态）。
- **审计前后值**：默认校单词模块共 **10 条** grant 记录（三轮取证写入；自下而上）：
  1. `manual → trial`，到期 `长期 → 2026-11-29 13:30:53Z`
  2. `trial → trial`，到期 `2026-11-29 → 2026-12-24`（+30d 档）
  3. `trial → trial`，到期 `2026-12-24 → 2026-12-01`（+7d 档）
  4. `trial → trial`，到期 `2026-12-01 → 2026-11-25`（+1d 档）
  5. `trial → manual`，到期 `2026-11-25 → 长期`（首轮恢复长期）
  6. `manual → trial`，到期 `长期 → 2026-11-25 14:09:19Z`（二轮 +1d 档）
  7. `trial → trial`，到期 `2026-11-25 → 2026-11-29 14:10:14Z`（二轮 +5d 档）
  8. `trial → manual`，到期 `2026-11-29 → 长期`（二轮恢复长期）
  9. `manual → trial`，到期 `长期 → 2026-11-29 14:30:50Z`（三轮 +5d 档）
  10. `trial → manual`，到期 `2026-11-29 14:30:50Z → 长期`（三轮恢复长期）
  - 审计表同时保存 before / after，截图 09 可见 `人工 → 试用`、`长期 → 2026/11/29 06:30:50`。
  - **操作人**：界面“上次更新”与审计“操作人”列统一显示 `平台运营 / Platform operator`，不再直出内部 `actor_operator_id` UUID（eef628d 修复）；本轮 DOM 与截图正则扫描 0 个 UUID。
- **用量口径**：9 项指标按本地自然日聚合，区间总量为每日行求和、去重项单日去重；界面只出聚合数，无学生/教师标识。两条 limitations：
  1. 活跃口径不含仅登录用户：当前没有登录日志或 `last_login_at`；活跃教师=当天有教学操作的去重教师，活跃学生=当天有词汇作答的去重学生。
  2. `farm_harvests` 为下限口径：农场只保存累计 `harvest_count` 与最近一次 `last_harvested_at`，无逐日收获事件；本数是“最近一次收获落在当日”的地块数，非当日真实收获次数。
- **横幅可见性**：仅 `school_admin`（兼容旧值 `admin`）角色渲染；平台运营 / 教师 / 学生不显示（组件测试已覆盖；真机至少确认校管角色 `school_admin` 显示三档横幅）。三档阈值：active + trial 且 `days_left ≤ 30` trial、`≤ 7` warning、`≤ 1` critical；expired 单独入口关闭提醒；disabled / not_granted / scheduled 不提示。

## 7. 已知限制与环境缺陷

- **390 弹窗栅格缺陷（环境问题，非产品 UI bug）**：本次附加无头 Chrome 在 390 视口下，Radix Dialog 的 body 直挂 fixed portal 层未被栅格化（弹窗标题条可见，卡片正文与遮罩透出底层列表；注入的裸 fixed 测试元素同样被裁剪成窄边）。820 / 1180 同一弹窗绘制完全正常。已排除：禁用动画/过渡、重置 transform/translate、`overflow:visible`、`captureBeyondViewport` 全页截图、元素裁剪截图、portal 改 absolute 定位；DOM 堆叠、`opacity/visibility` 计算样式均正确。
  - 二轮重试：按 `mobile=true, deviceScaleFactor=2, width=390, height=844` 并启用 `TouchEmulation` 重开模块弹窗与用量弹窗；另对照 `dpr=2/非移动`、`移动/dpr=1` 两组变体，正文层**仍未栅格化**（仅标题条绘制，卡片透出列表），DOM 内 9 张指标卡/表单字段均在。结论：该缺陷与 DPR、移动模拟、触摸模拟无关，属本地无头浏览器窄视口合成层问题。
  - 因此 08（模块弹窗）与 11（用量弹窗）的英文画面在 **820** 兜底拍摄；390 的布局无溢出与表格内部横滑结论以 §5 的 JS 实测宽度为准。建议后续在真机或常规浏览器窗口复拍 390 弹窗。
- **登录活跃缺失**：见 §6 limitations 第 1 条，活跃教师/学生并非全量在线口径。
- **农场逐日收获为下限**：见 §6 limitations 第 2 条，不作为当日精确收获数。
- 次要文案观察（未改代码，待产品确认）：
  - 英文界面下日期输入框占位仍为中文原生本地化文案“年/月/日 --:--”（浏览器原生日期控件 locale，非应用 i18n 词条）。
  - 列表名称列固定渲染 `name_zh`，不随界面语言切换 `name_en`，属数据专有名词口径，未当作 bug 改动。

## 8. 待商务确认的默认值

- 试用默认天数（当前演示按 5/30/7/1 天构造，产品默认值未定）。
- 到期宽限：当前**无宽限**，到点即判 expired。
- 提醒时点：当前阈值 `≤30` 提示、`≤7` 警示、`≤1` 紧急。

## 9. 取证边界声明

- 仅本地开发库 `app`（Docker `english-speaking-assessment-db-1`）；未连接、未访问任何生产服务器（含 49.232.156.221 / 42.193.108.162 等）。
- 未部署生产环境；未执行 devledger 记账。取证阶段尚未创建 PR / 合并 master；交付状态以 PR 与 #517 为准。
- 截图中的课堂名/教师名为本地 e2e 演示数据，无真实学生姓名、账号或联系方式。
- 取证结束后已停掉本次启动的 8006 / 5176（见提交前收尾）；主仓 8000 / 5173 容器未动。
