# #517 C 块 · 移动端真机级审计（第二阶段，2026-11-25）

本目录归档 issue #517「移动端真机级审计」C 块成果。分支 `fix/mobile-audit-20261125`；第一阶段提交 `cbb66bf`（基点 master `c1a1a8c`），第二阶段已 `git fetch origin && git merge origin/master`（merge commit `f3ba17d`，合入 A #556 授权页/侧栏、D #555 nginx/DB、B #557 CEFR/vocab），无冲突。

## 1. 环境与证据边界

- 全部页面来自本 worktree 本地 dev：前端 **5181** → 后端 **8034** → 本机 Docker Postgres **5433**（库 `app`，本地 demo 合成数据）。**未连接生产/预发，未部署。**
- 驱动方式分四类，**禁止混标**：

| 证据标签 | 引擎 / 手段 | 口径边界 |
|---|---|---|
| CDP 移动模拟（`audit.json` / `audit-interactive.json`） | Playwright + 系统 Chrome，`isMobile` + `hasTouch`，DSR 2，headless | 视口/触控模拟，**非真机触摸与手势** |
| `real-chrome-zoom`（`zoom.json`） | 系统 Chrome 桌面引擎，200% 缩放按「CSS 视口折半（640 宽）+ DSR 2」模拟 | 非真机 pinch 缩放 / 系统字体大小缩放 |
| `real-webkit`（`webkit.json`） | Playwright WebKit 27.2（v2388，Safari 同内核）headless | **不是 Safari.app 真机**；渲染内核等价，控件行为/字体回退以真机为准 |
| `sim-keyboard`（`keyboard.json`） | CDP 输入聚焦 + visualViewport 读取 | CDP 无法真实唤起软键盘；**键盘遮挡未真机验证** |
| `sim-longlist`（`longlist.json`） | CDP 模拟滚动到末行 | 仅两组样本顶部/底部可达；无限滚动未遍历 |

- **真实 Safari.app 自动化：BLOCKED。** `safaridriver` 27.0 在线（`/status` ready），但建会话被拒：`You must enable 'Allow remote automation' in the Developer section of Safari Settings to control Safari via WebDriver.` 该开关只能在 Safari GUI 内手动打开，无法脚本开启。手动复核步骤见第 8.2 节。
- 审计脚本：`scripts/audit.mjs`（`smoke | matrix | interactive`）；补充取证 `scripts/extra-evidence.mjs`（`zoom | webkit | keyboard | longlist`）；单页调试 `scripts/debug.mjs`。

## 2. 矩阵规模与覆盖口径

| 维度 | 覆盖 |
|---|---|
| 路由 | 24 条：登录；学生 首页 / 作答 / 词汇首页 / 测分 / 自主复习 / 班内榜 / 词库浏览 / 记录；教师 课堂面板 / 词汇发布及 results / trend / placement / pk / farm / review / leaderboard 七子页 / 学生详情；管理端 dashboard / 词库 / **授权台账（A #556）** / 用户 / 学校 |
| 竖屏视口 | 320×568、360×640、390×844、430×932 |
| 横屏 | 844×390（iPad/手机横屏） |
| 语言 | `zh` / `en` 双语 |
| CDP 矩阵记录 | **196 条**：13 关键页 ×10（4 竖宽 + 横屏 × 中英），11 非关键页 ×6（320/390/430 × 中英） |
| 交互式记录 | **16 条**：添加用户弹窗、新建班级词库内联面板、学生词库卡片展开、侧栏抽屉导航（390/320 × 中英） |
| 桌面缩放记录 | **14 条**（`real-chrome-zoom`：7 关键页 × 中英，CSS 640 宽） |
| WebKit 记录 | **14 条**（`real-webkit`：7 关键页 × 中英，390 宽） |
| 软键盘记录 | **4 条**（`sim-keyboard`：登录密码框、授权页筛选框，中英） |
| 长列表记录 | **4 条 / 8 张截图**（`sim-longlist`：学生词库浏览、授权台账，中英各 top/bottom） |
| 截图 | **262 个 png**：矩阵 196 + 授权页表格 reveal 10 + 交互 16 + 缩放 14 + WebKit 14 + 软键盘 4 + 长列表 8；debug 调试截图未入库 |
| 最终状态 | CDP 矩阵 **196 PASS / 0 FAIL**；交互 **16 PASS / 0 FAIL**；缩放 **14 PASS**；WebKit **14 PASS**；软键盘 **4 PASS**；长列表 **4 PASS** |

状态口径：`PASS` = 采集指标全部达标；`FAIL` = 溢出 / 字号 / 目标尺寸越线；`SKIP` = 触发条件未满足。各 JSON 记录的是修复后的最终状态。

### 采集指标（`collectMetrics`）

- **横向溢出**：`documentElement.scrollWidth - clientWidth`；被祖先 `overflow-x: auto/scroll/clip/hidden` 裁剪的元素不计入溢出（表格内部横向滑动属预期）。
- **触控目标**：`a/button/input/select/textarea/[role=button|tab|link]`，可见且非 sr-only；宽或高 <44px 记入 `targets`。
- **表单字号**：`input/select/textarea`（排除 checkbox/radio/hidden），计算字号 <16px 记入 `smallFonts`。
- **固定底栏**：`position: fixed; bottom: 0` 元素及其 `padding-bottom`（安全区）。
- **视口 meta**：记录 `viewport` content；确认未锁缩放（`zoomLocked=false`，允许 pinch 缩放）。

## 3. 验收红线核对结果（模拟口径）

| 红线 | 结果 | 证据 |
|---|---|---|
| 320 宽无横向溢出 | ✅ 196 条矩阵记录最大溢出 0px，无 >1px 溢出 | `audit.json` → `metrics.overflow` / `offenders` |
| 触控目标 ≥44px（高频主操作） | ✅ 头部、主 CTA、主选择 chips、视图 tab、弹窗主按钮、Select 触发条均 ≥44；残留 36px 次级控件见第 6 节 P2 | `audit.json` → `metrics.targets` |
| 表单字号 ≥16px | ✅ 全部可见 input/select/textarea 字号 16px；`smallFonts` 为空（CDP / WebKit 双引擎复核） | `audit.json`、`webkit.json` → `metrics.smallFonts` |
| 安全区 / 软键盘不遮提交按钮 | ⚠️ 静态核对底栏安全区 padding；软键盘顶起仅 CDP 聚焦模拟（`sim-keyboard` 主按钮均在 visual viewport 内），**真实键盘遮挡未验证** | `keyboard.json`；`metrics.fixedBottom` |
| 长列表可滚动、底部可达 | ✅ 两组样本（词库 5 条、台账 8 条）末行滚动后可见；其余长列表逐屏遍历未做 | `longlist.json` → `metrics.lastRow` |
| 中英双语 | ✅ 每条路由 zh/en 双份截图与指标 | 截图文件名 lang 段 |
| 缩放不被锁 | ✅ `viewport` meta 未禁止缩放，`zoomLocked=false` | `metrics.zoomLocked` |

## 4. A #556 授权台账页与侧栏入口覆盖

新增路由 `/admin/vocabulary-licenses`（operator，`src/routes/_layout/admin.vocabulary-licenses.tsx`），第二阶段补审，结论 **10 条矩阵记录全 PASS、0 溢出、无 <16 字号、无 <44 高频目标**。

- **统计卡**：有效 / 临期 / 已过期 / 缺失 4 张，窄屏 `grid-cols-2`，≥md 四列；演示数据有效 8、其余 0。
- **筛选**：学校（输入）、词库（输入）、授权状态（原生 select）三项；输入框 h-11 / 16px / 全宽，select h-11 / 16px。
- **表格**：8 列（学校 / 词库 / 来源类型 / 授权状态 / 授权方 / 到期日 / 凭证 / 备注登记时间），置于 `.overflow-x-auto` 内横向滑动；窄屏有「横向滑动表格」提示文案；10 张 `-table.png` 为滚到表格后的证据。
- **导出 CSV**：`AdminService.adminExportLicenseCsv()` 返回文本 → Blob 下载 `vocabulary-license-all-<date>.csv`；按钮 h-11；headless 未触发真实下载，链路为代码级核对。
- **凭证链接**：`isSafeHttpUrl` 仅放行 `http/https`；链接 `target="_blank" rel="noopener noreferrer"`；其余（含 `javascript:` 等）按纯文本展示。演示数据无 http/https 凭证，UI 中凭证列呈纯文本。
- **侧栏入口**：`AppSidebar.tsx` 平台设置分组下「授权台账 / License Ledger」（ShieldCheck 图标，路径 `/admin/vocabulary-licenses`）；经 SidebarTrigger 打开抽屉后可见且当前态高亮，证据 `sidebar-nav-*.png`（4 条交互记录）。
- **窄屏**：320 / 390 头部、卡片、筛选、表格横滚均无页面级横向溢出。

## 5. 修复清单

### 5.1 第一阶段（提交 `cbb66bf`，18 项，基线已复测全绿）

窄屏溢出 8 项：登录页英文头部 nowrap、学生/作答/词汇头部控件超宽、教师词汇扩展区控件不收缩、新建词库内联长 token、趋势 / PK 面板筛选项、学生词库卡片 grid 项、表格与管理端卡片 `min-w-0`。

触控目标 10 项：LanguageToggle、Appearance、SidebarTrigger、InfoHint、教师词汇 8 枚视图 tab、LoadingButton、弹窗关闭钮、Radix Select 触发条、发布面板 chips、口语/词汇模块切换，移动端统一抬到 ≥44px（桌面 `sm:` 档位还原）。

字号：全站可见表单控件 16px，未触发 iOS 聚焦放大。

### 5.2 第二阶段新修复（本分支工作树）

| # | 页面 / 控件 | 视口 / 引擎 | 现象 | 根因 | 修复 | 证据 |
|---|---|---|---|---|---|---|
| 19 | 登录页（英文） | 320 / 360 / 390，CDP | 主 CTA「Sign in to workspace」在折线下：320 底部 929（超 85px）、360 877（33px）、390 853（9px）；中文各宽均在屏内 | 移动端营销区（ eyebrow / 标题 / 描述）与登录卡片纵向间距偏大，英文标题/描述换行后把卡片下推 | `LoginLayout` 移动端收紧：main `gap-4 pt-2 pb-6`（sm 还原 `gap-7 pt-4 pb-10`）；标题 `text-2xl leading-snug`；描述 `mt-2 leading-5`（sm 还原）；卡片 `p-4`（sm `p-8`）。桌面 lg 布局不动 | 复测：en 360 底部 837、390 817、430 829 均在屏内；`login-*-*.png`、`keyboard-login-en-390.png` |
| 20 | 原生 `<select>`（7 文件 9 处） | WebKit 27，390 | WebKit 下原生 select 不被 `min-height` 拉伸，控件高仅 27–28px；Chrome 下 `min-h-11` 生效故第一阶段未暴露 | WebKit 对原生替换元素的 `min-height` 不参与控件盒高计算；需显式 `height` | 9 处原生 select 的 `min-h-11` 改为 `h-11`（显式 44px）：`StudentClassroomInbox`（求助类型）、`Admin/Dashboard/CostCard`（对账月份）、`ClassroomContactPanel`（求助记录 / 提醒状态）、`LeaderboardTeacherPanel`（可见范围）、`LessonReview`（示例选择）、`FollowupManager`（筛选条件 / 来源练习）、`LearningReportCard`（时间范围 / 教学练习）。Button / summary / TabsTrigger 等非 select 未改动 | `webkit.json` 复测：上述 select 不再进入 `<44` 清单；0 溢出、无小字号 |

## 6. P2 遗留观察项（本阶段未修）

以下项在竖屏模拟下未阻断主流程，按「不做无关视觉重设计」原则未抬高；均在对应 JSON 的 `targets` 留尺寸明细。

1. **原生 checkbox / radio 16×16**：登录记住、词汇勾选、弹窗启用、词卡开关等；标签行整体可点，未单独放大命中区。
2. **行内文字链接高 16–36px**：登录「注册账号 / 平台运营入口」、面包屑「← 我的课堂 / 返回词汇首页」、「结果页 / 去词库开一轮 / 去词库挑词 / 到题目库补充内容」等行内次级导航。
3. **h-9（36px）次级按钮**：刷新、整体学习建议 / 本次学情分析、结束任务、周翻页 42×36、新建班级词库 ghost 钮、CSV 选择 / 创建空词库等行内或次级操作。Button `sm` 档位是否在移动端统一抬高到 44，需结合桌面密度批量评估。
4. **Radix Select 触发条 14px 文本**：非原生弹层，不触发 iOS 聚焦放大；字号沿用桌面密度。
5. **InfoHint 问号命中区约 16–20px**：CDP 与 WebKit 下均偏小；图标视觉不变，是否放大命中区留待统一评估。
6. **侧栏抽屉底部外观切换钮**：抽屉内次级，高 32px；抽屉展开态才可见，不影响主流程。
7. **320 宽英文登录页 CTA**：修复后 320 底部仍约 889（折线下约 45px），页面可一次滚动到达；360 及以上已在屏内。320 宽设备为 legacy 机型，记为 P2。
8. **开发态 TanStack Router devtools 浮层**：采集时已按 label 排除，生产不出现。

## 7. 未覆盖与边界（不可作为真机结论）

- **真机验证**：未在 iPhone / Android 实机跑触摸、滚动、手势；全部为 CDP / 无头引擎模拟。
- **真实 Safari.app**：BLOCKED（第 1 节）；`real-webkit` 仅为同内核无头代理。
- **桌面 / 系统缩放**：`real-chrome-zoom` 为 CSS 视口折半 + DSR2 模拟；未跑系统字体大小缩放、动态字体（Dynamic Type）与真机 pinch。
- **软键盘顶起**：CDP 无法真实唤起软键盘；`sim-keyboard` 仅聚焦输入框并读取 visualViewport，提交按钮在模拟视口内；真实键盘弹起后的遮挡 / 回弹未验证。
- **刘海 / 灵动岛 / Home Indicator 安全区**：仅静态核对 `env(safe-area-inset-*)` 类名与底栏 padding；真机异形屏表现未验证。
- **长列表逐屏滚动**：仅词库浏览（5 条）、授权台账（8 条）两组顶部/底部可达取证；分页加载、虚拟列表与超长列表未遍历。

## 8. 复现命令（本地 dev，非生产）

### 8.1 起服务

```bash
# 后端 8034 → 本机 Postgres 5433（工作树 backend 目录；复用主仓 .venv）
# 注意：必须带 PYTHONPATH=.，避免 editable .pth 把 app 解析到主仓 backend
cd backend
PYTHONPATH=. ENVIRONMENT=local POSTGRES_SERVER=localhost POSTGRES_PORT=5433 POSTGRES_DB=app \
  POSTGRES_USER=postgres POSTGRES_PASSWORD=changethis \
  APP_POSTGRES_USER=esa_app APP_POSTGRES_PASSWORD=<...> \
  PLATFORM_POSTGRES_USER=esa_platform PLATFORM_POSTGRES_PASSWORD=<...> \
  /Users/lili/Projects/english-speaking-assessment/backend/.venv/bin/python \
  -m uvicorn app.main:app --host 127.0.0.1 --port 8034

# 前端 5181（工作树 frontend 目录）
cd frontend
API_PROXY_TARGET=http://127.0.0.1:8034 npx vite --host 127.0.0.1 --port 5181 --strictPort
```

### 8.2 审计与补充取证（在 frontend 目录下执行）

```bash
# CDP 矩阵 / 交互式
node ../docs/qa/20261125/c-mobile-audit/scripts/audit.mjs matrix
node ../docs/qa/20261125/c-mobile-audit/scripts/audit.mjs interactive

# 补充取证：桌面缩放 / WebKit 内核 / 软键盘模拟 / 长列表可达
node ../docs/qa/20261125/c-mobile-audit/scripts/extra-evidence.mjs zoom
node ../docs/qa/20261125/c-mobile-audit/scripts/extra-evidence.mjs webkit
node ../docs/qa/20261125/c-mobile-audit/scripts/extra-evidence.mjs keyboard
node ../docs/qa/20261125/c-mobile-audit/scripts/extra-evidence.mjs longlist

# 单页调试：<path> [role] [lang] [width] [height]
node ../docs/qa/20261125/c-mobile-audit/scripts/debug.mjs /t/DEMO01/vocab teacher zh 390
```

### 8.3 真实 Safari 手动复核步骤（自动化 BLOCKED 时）

1. 打开 Safari → 菜单栏 `Safari` → `Settings…` → `Developer` 标签 → 勾选 **Allow remote automation**（允许远程自动化）。
2. 复核页面：登录页 320/390 中英、学生首页、词汇首页、教师课堂面板、教师词汇、管理端 dashboard、授权台账 `/admin/vocabulary-licenses`。
3. 重点看：320/390 头部是否溢出、表格横滚是否顺滑、固定底栏是否遮内容、弹窗主按钮是否可达、聚焦输入框时页面是否自动滚动避让。
4. 复核后可 `safaridriver -p <port>` 建会话回归；未开开关前 `POST /session` 必然返回权限错误。

## 9. 回归测试

- `frontend/tests/e2e/responsive.spec.ts`：320 / 430 窄宽锚点（登录、教师词汇、学生词库无横向溢出 + 关键入口可达），与既有 390 / 820 / 1180 用例同口径。
- 本块改动为样式 / 类名调整，未改业务逻辑；未改 lockfile、未手改 `src/client/` 生成码、后端零改动。

## 10. 本地闸门结果（第二阶段，合并 master 后）

- 前端 `npm run typecheck`（tsc --noEmit）：✅ 通过
- 前端 `npm run lint`（biome）：✅ 无错误（仅 schema 版本 2.6.4→2.6.7 信息级提示）
- 前端 `npm test`：✅ node --test **234 passed / 0 fail**，vitest **131 passed**（23 文件）
- 前端 `npm run build`：✅ 构建成功
- 后端 `bash scripts/verify.sh --openapi`（`PYTHONPATH=.` 指向工作树 backend）：格式 / ruff / ty / 测试全绿，**1231 passed, 2 skipped**；**openapi 零漂移（234 路径 / 335 schemas）**。第一阶段记录的 3 处差异系 editable venv `.pth` 指向主仓 backend 所致；本阶段在工作树 `PYTHONPATH=.` 下复跑，基线已含 A+B+D 全部端点，零漂移。
