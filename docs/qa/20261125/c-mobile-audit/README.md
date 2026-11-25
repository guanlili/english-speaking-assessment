# #517 C 块 · 移动端真机级审计（第一阶段，2026-11-25）

本目录归档 issue #517「移动端真机级审计」C 块第一阶段成果：本地 CDP 设备模拟矩阵、阻断级缺陷修复、截图与指标证据。分支 `fix/mobile-audit-20261125`，基点 master `c1a1a8c`（已含 B #557）。

## 1. 环境与证据边界

- 全部页面来自本 worktree 本地 dev：前端 **5181** → 后端 **8034** → 本机 Docker Postgres **5433**（库 `app`，本地 demo 合成数据）。**未连接生产/预发，未部署。**
- 驱动方式：Playwright + 系统 Chrome，CDP 设备模拟（`isMobile` + `hasTouch`，deviceScaleFactor 2，headless）。
- **重要口径：本阶段所有「通过」结论均为 CDP 模拟（simulated），不是真机结论。** 凡需真实设备 / 桌面缩放才能判定的项，见第 7 节「未覆盖与第二阶段待办」，不得在对外材料中写成「真机通过」。
- 审计脚本：`scripts/audit.mjs`（`smoke | matrix | interactive`）；单页调试：`scripts/debug.mjs`。
- 指标落盘：`audit.json`（矩阵 186 条）、`audit-interactive.json`（交互式 12 条）；截图：`screenshots/`，命名 `<route>-<lang>-<width>[-land].png`。

## 2. 矩阵规模与覆盖口径

| 维度 | 覆盖 |
|---|---|
| 路由 | 23 条：登录；学生 首页 / 作答 / 词汇首页 / 测分 / 自主复习 / 班内榜 / 词库浏览 / 记录；教师 课堂面板 / 词汇发布及 results / trend / placement / pk / farm / review / leaderboard 七子页 / 学生详情；管理端 dashboard / 词库 / 用户 / 学校 |
| 竖屏视口 | 320×568、360×640、390×844、430×932 |
| 横屏 | 844×390（iPad/手机横屏，≥sm 断点，桌面密度） |
| 语言 | `zh` / `en` 双语 |
| 矩阵记录 | 186 条（关键页 4 宽 × 中英 + 横屏；其余页 320/390/430 × 中英冒烟） |
| 交互式记录 | 12 条：添加用户弹窗、新建班级词库内联面板、学生词库卡片展开（390/320 × 中英） |
| 截图 | 198 个 png（186 矩阵 + 12 交互式；debug 调试截图未入库） |
| 最终状态 | 矩阵 **186 PASS / 0 FAIL**；交互式 **12 PASS / 0 FAIL** |

状态口径：`PASS` = 采集指标全部达标；`FAIL` = 溢出 / 字号 / 目标尺寸越线；`SKIP` = 触发条件未满足（本阶段无 SKIP）。第 5 节「修复清单」中的缺陷在修复后复测均为 PASS；`audit.json` 记录的是修复后的最终状态。

### 采集指标（`collectMetrics`）

- **横向溢出**：`documentElement.scrollWidth - clientWidth`；被祖先 `overflow-x: auto/scroll/clip/hidden` 裁剪的元素不计入溢出（表格内部横向滑动属预期）。
- **触控目标**：`a/button/input/select/textarea/[role=button|tab|link]`，可见且非 sr-only；宽或高 <44px 记入 `targets`。
- **表单字号**：`input/select/textarea`（排除 checkbox/radio/hidden），计算字号 <16px 记入 `smallFonts`。
- **固定底栏**：`position: fixed; bottom: 0` 元素及其 `padding-bottom`（安全区）。
- **视口 meta**：记录 `viewport` content；确认未锁缩放（`zoomLocked=false`，允许 pinch 缩放）。

## 3. 验收红线核对结果（模拟口径）

| 红线 | 结果 | 证据 |
|---|---|---|
| 320 宽无横向溢出 | ✅ 52 条 320 记录最大溢出 1px（容差内），无 >1px 溢出 | `audit.json` → `metrics.overflow` / `offenders` |
| 触控目标 ≥44px（高频主操作） | ✅ 头部、主 CTA、主选择 chips、视图 tab、弹窗主按钮、Select 触发条均 ≥44；残留 36px 次级控件见第 6 节 P2 | `audit.json` → `metrics.targets` |
| 表单字号 ≥16px | ✅ 全部可见 input/select/textarea 字号 16px；`smallFonts` 为空 | `audit.json` → `metrics.smallFonts` |
| 安全区 / 软键盘不遮提交按钮 | ⚠️ 静态核对：学生底栏 `pb-[max(0.5rem,env(safe-area-inset-bottom))]`，内容区 `pb-20` 避让；**软键盘顶起未真机验证**（第 7 节） | `StudentShell.tsx` 底栏类名；`metrics.fixedBottom` |
| 长列表可滚动、底部操作可达 | ✅ 首屏无溢出；表格内部横向滑动由 `overflow-x` 容器承担；逐屏滚动态未遍历（第 7 节） | DataTable `min-w-0` + 内部滚动容器 |
| 中英双语 | ✅ 每条路由 zh/en 双份截图与指标 | 截图文件名 lang 段 |
| 缩放不被锁 | ✅ `viewport` meta 未禁止缩放 | `metrics.zoomLocked=false` |

## 4. 本阶段未触碰的范围

- A #556 新增 `/admin/vocabulary-licenses` 授权页、`routes/_layout/admin.tsx`、`components/AppSidebar.tsx`、`lib/vocabGovernance.ts`、`src/client/`：**第一阶段未审、未改**，第二阶段 A 合入 master 后补。
- 全局 `AppSidebar.tsx` 抽屉 / 底部入口：本阶段按要求未动。
- D #555（nginx / `config.py` / `db.py` / 探针）：不影响本块 UI，第二阶段合并回归。

## 5. 修复清单（页面 / 视口 / 现象 / 根因 / 修复 / 证据）

### 5.1 横向溢出

| # | 页面 | 视口 | 现象 | 根因 | 修复 | 证据 |
|---|---|---|---|---|---|---|
| 1 | 登录页 | 320–390 英文 | 头部横向溢出约 25px | Logo 副标题 `whitespace-nowrap`，英文长串不可收缩；头部右组 `gap-6` 过宽 | 副标题移动端 `max-sm:hidden`；头部右组 `gap-3 sm:gap-6` | `login-en-320/360/390/430.png` |
| 2 | 学生首页 / 作答 / 词汇各页 | 320 | 头部横向溢出约 16px | 头部控件（语言钮、账户菜单箭头、间距）合计超宽 | 语言钮移动端去掉装饰图标、宽度 36→44；账户菜单箭头移动端隐藏、`padding/gap` 收紧 | `student-home-*`、`student-practice-*`、`vocab-*-*` 320 截图 |
| 3 | 教师词汇 · 扩展区（AdvancedWordPanel） | 320–390 | 目标词库选择框 / 搜索框 / 名称输入撑破 393px | 控件固定 `max-w-*`，窄屏不收缩 | 选择框 / 搜索 / 名称输入 `w-full sm:w-auto`；转入按钮 `w-full sm:w-auto` | `teacher-vocab-*-320/390.png` |
| 4 | 教师词汇 · 新建班级词库内联面板 | 320–390 | 长说明 token（CSV 表头）不换行顶破容器 | 说明 `span` 无 `min-w-0/flex-1/break-words`；导入 select 非全宽 | 说明段 `min-w-0 flex-1 break-words`；导入 select `w-full max-w-full` | `inline-new-book-*-320/390.png` |
| 5 | 教师词汇 · 趋势面板 | 320–390 | 4 个筛选项（粒度/周期/词库/题型）窄屏不收缩 | `label` 不可收缩，`select` 无全宽；长说明 Badge 不换行 | `label min-w-0`、`select w-full`；Badge 移动端 `w-full break-words sm:w-auto` | `teacher-trend-*-320/390/430.png` |
| 6 | 教师词汇 · PK 面板 | 320–390 | 3 个筛选项 label/select 溢出 | 同 5 | 3 个 `label min-w-0`、2 个 `select w-full` | `teacher-pk-*-320/390/430.png` |
| 7 | 学生词库浏览 | 320–390 | 长词库名卡片撑破 grid | grid 项 `li` 缺 `min-w-0` | `li` 加 `min-w-0` | `vocab-books-*-320/390.png`、`book-detail-*` |
| 8 | 表格与管理端卡片 | 320–390 | 外层 flex 容器不收缩，长内容顶破页面 | DataTable 外层/内层 flex、admin 根容器、ExportCard 卡片/文本块缺 `min-w-0` | 上述容器补 `min-w-0`（ExportCard 文本块 `min-w-0`）；表格内部仍由滚动容器横向滑动 | `admin-index/admin-dashboard/admin-vocabbooks/admin-schools-*` |

### 5.2 触控目标（高频主操作 ≥44px）

| # | 控件 | 视口 | 现象 | 根因 | 修复 | 证据 |
|---|---|---|---|---|---|---|
| 9 | 语言切换 LanguageToggle | 320–430 | 移动端按钮 36×28 | 档位 `h-7 min-w-9` 为桌面密度 | 移动端 `h-11 min-w-11`、图标移动端隐藏；桌面 `sm:h-7 sm:min-w-9` 还原 | 各页 `*-zh/en-390.png` 头部 |
| 10 | 外观切换 Appearance | 320–430 | 移动端 36×36 | 原类名写反：`size-9 sm:size-11`（移动小、桌面大） | 改为 `size-11 sm:size-9` | `student-home-*`、`vocab-*-*` 头部 |
| 11 | 教师壳层 SidebarTrigger | 320–430 | 36×36 | `size-9` 无响应式档位 | `size-11 sm:size-9` | `teacher-board/teacher-vocab-*` 头部 |
| 12 | InfoHint 问号 | 320–430 | 命中区约 20px | 图标按钮无显式尺寸 | `size-10 -m-1.5`（命中区 40px，视觉不变） | 各面板说明问号 |
| 13 | 教师词汇 8 枚视图 tab | 320–430 | 36px | `size="sm"` 固定 h-9 | 8 枚 tab `h-11 sm:h-9` | `teacher-vocab-*-320/390/430.png` |
| 14 | LoadingButton（主提交按钮） | 320–430 | 默认档位 36px | 档位表与 Button 基线不一致（default h-9 / sm h-8 / lg h-10 / icon size-9） | 对齐 Button：default `h-11`、sm `h-9`、lg `h-12`、icon `size-11` | 弹窗保存、面板主按钮；`audit-interactive.json` |
| 15 | 弹窗关闭按钮 | 320–390 | 36×36 | Dialog close `size-9` | `size-11 sm:size-9` | `dialog-add-user-*` |
| 16 | Radix Select 触发条 | 320–430 | 36px | SelectTrigger 默认 `h-9`，与 16px/44px 输入框基线不一致 | 默认档位 `h-11`，sm `h-9`；桌面筛选条同步抬高与输入框对齐 | `admin-users/admin-schools/dialog-add-user/inline-new-book-*` |
| 17 | 发布面板 · 模式 / 范围 chips | 320–390 | 36px | `size="sm"` 固定 | 练习/测验、全班/指定学生四枚主选择 `max-sm:h-11` | `teacher-vocab-*`、`inline-new-book-*` |
| 18 | 口语 / 词汇模块切换 | 320–390 | 36px | `size="sm"` 固定 | 两枚切换钮 `max-sm:h-11` | `teacher-vocab-*` 头部 |

### 5.3 字号

- 全站可见 `input/select/textarea` 计算字号均为 **16px**（`smallFonts` 为空），未触发 iOS 聚焦放大条件。
- 残留 14px 仅为：原生 checkbox/radio（不计入缩放判定）、Radix Select 弹层文本（非原生控件，不触发聚焦缩放）、展示性文字。

## 6. P2 遗留观察项（本阶段未修，建议第二阶段统一评估）

以下项在竖屏模拟下未阻断主流程，按「不做无关视觉重设计」原则未抬高；均已在 `audit.json` 的 `targets` 留尺寸明细。

1. **原生 checkbox / radio 16×16**：登录记住、词汇勾选、弹窗启用、词卡开关等；标签行整体可点，未单独放大命中区。
2. **行内文字链接高 16–36px**：登录页「注册账号 / 平台运营入口」、面包屑「← 我的课堂 / 返回词汇首页」、「结果页 / 去词库开一轮 / 去词库挑词 / 到题目库补充内容」等；属行内次级导航。
3. **h-9（36px）次级按钮**：刷新、整体学习建议 / 本次学情分析、结束任务、周翻页 42×36、新建班级词库 ghost 钮、CSV 选择 / 创建空词库、全选 / 清空、去审核等行内或次级操作。是否把 Button `sm` 档位在移动端统一抬高到 44，需结合桌面密度与视觉批量评估，不在本块单点改动。
4. **Radix Select 触发条 14px 文本**：非原生弹层，不触发 iOS 聚焦放大；字号沿用桌面密度。
5. **开发态 TanStack Router devtools 浮层**：采集时已按 label 排除，生产不出现。

## 7. 未覆盖与第二阶段待办

### 7.1 本阶段未覆盖（不可作为真机结论）

- **真机验证**：未在 iPhone / Android 实机跑触摸、滚动、手势；全部为 CDP 模拟。
- **桌面 / 系统缩放**：未跑 macOS Safari / Chrome 的 pinch 缩放、字体大小缩放与动态字体。
- **软键盘顶起**：CDP 无法真实唤起软键盘；输入聚焦后 visual viewport 上移、提交按钮是否被键盘遮挡，未验证。
- **刘海 / 灵动岛 / Home Indicator 安全区**：仅静态核对 `env(safe-area-inset-*)` 类名与底栏 padding；真机异形屏表现未验证。
- **长列表逐屏滚动**：采集首屏指标；下拉加载、滚到底部操作可达性未逐屏遍历。

### 7.2 第二阶段（等 A #556 合入 master 后）

1. `git fetch origin && git merge origin/master`，合入 A #556（及 D #555）；冲突时保留 A 的授权页 / 侧栏入口与 C 的移动端修复。
2. 补审 `/admin/vocabulary-licenses` 页与侧栏入口，重跑全矩阵并补截图 / README。
3. 审计全局 `AppSidebar.tsx` 移动端抽屉 / 底部入口。
4. 真机 / 桌面缩放补证；P2（第 6 节）sm 档位统一评估。
5. 最终 push、开 PR 到 master；PR 正文写明模拟 / 真机边界、页面×视口矩阵、修复清单、测试、`Refs #517`。**不 merge、不部署、不跑 devledger。**

## 8. 复现命令（本地 dev，非生产）

```bash
# 后端 8034 → 本机 Postgres 5433（工作树 backend 目录；复用主仓 .venv）
cd backend
ENVIRONMENT=local POSTGRES_SERVER=localhost POSTGRES_PORT=5433 POSTGRES_DB=app \
  POSTGRES_USER=postgres POSTGRES_PASSWORD=changethis \
  APP_POSTGRES_USER=esa_app APP_POSTGRES_PASSWORD=<...> \
  PLATFORM_POSTGRES_USER=esa_platform PLATFORM_POSTGRES_PASSWORD=<...> \
  /Users/lili/Projects/english-speaking-assessment/backend/.venv/bin/python \
  -m uvicorn app.main:app --host 127.0.0.1 --port 8034

# 前端 5181（工作树 frontend 目录）
cd frontend
API_PROXY_TARGET=http://127.0.0.1:8034 npx vite --host 127.0.0.1 --port 5181 --strictPort

# 审计矩阵 / 交互式（在 frontend 目录下执行）
node ../docs/qa/20261125/c-mobile-audit/scripts/audit.mjs matrix
node ../docs/qa/20261125/c-mobile-audit/scripts/audit.mjs interactive

# 单页调试：<path> [role] [lang] [width] [height]
node ../docs/qa/20261125/c-mobile-audit/scripts/debug.mjs /t/DEMO01/vocab teacher zh 390
```

## 9. 回归测试

- `frontend/tests/e2e/responsive.spec.ts`：新增 320 / 430 两档窄宽锚点（登录、教师词汇任务、学生词库浏览无横向溢出 + 关键入口可达），与既有 390 / 820 / 1180 用例同口径。
- 本块改动为样式 / 类名调整，未改业务逻辑；既有单元 233 项、组件 131 项全绿（见第 10 节闸门）。

## 10. 本地闸门结果

- 前端 `npm run typecheck`：✅ 通过
- 前端 `npm run lint`：✅ 无错误（仅 biome schema 版本提示 2.6.4→2.6.7 信息级）
- 前端 `npm test`（node --test 233 + vitest 131）：✅ 全绿
- 前端 `npm run build`：✅ 构建成功
- 后端 `bash scripts/verify.sh --openapi`：格式 / ruff / ty / **1225 passed, 2 skipped** 全绿；openapi 步骤报 3 处差异，均为 A #556 授权契约（`VocabularyLicenseStatusItem/List`、`/admin/vocabulary/license/status`、导出 CSV 描述）。原因：复用主仓 editable venv（`.pth` 指向主仓 backend），spec 从已合入 #556 的主仓 master 生成，而本工作树基线仍是基点 c1a1a8c；**本块零后端改动**。主仓 master 上 `openapi_diff.py` 实测零漂移（234 路径 / 335 schemas）。第二阶段合入 master 后基线自动对齐，无需 `--openapi-update`。
