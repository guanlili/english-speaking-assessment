# #517 词汇治理（授权台账 / 版本回滚）与教师趋势、PK、农场 — 本地浏览器 + API 独立取证

- 验证日期：2026-11-25（Asia/Shanghai）
- 验证环境：**仅本机本地开发环境**，未连接、未写入任何生产库或生产服务器，未触发部署、未推送代码。
- 服务地址：前端 `http://127.0.0.1:5175`（vite dev，`/api` 同源代理到本批后端）、后端 `http://127.0.0.1:8001/api/v1`（宿主 uvicorn）、本地库 `localhost:5433/app`（compose postgres）。
- 功能代码基线：分支 `feat/vocab-governance-trends-20261125`，浏览器取证时 HEAD `c7ac7dd`（含 390 看板卡排版修复 `9f28567`、版本对比表换行修复 `c7ac7dd`）；证据目录另行提交，不改功能代码。
- 被测功能：A 版权/授权台账、B 词库版本历史/对比/回滚、C 教师跨任务/时间趋势、D 教师 PK 历史、E 农场教师只读概览与课堂看板摘要卡。
- 取证方式：真实浏览器（本机 Chrome + Playwright，视口 390 / 820 / 1180，中 / 英双语，`timezoneId=Asia/Shanghai`）走查 + 后端 API 探针双向核对；不以组件测试代替浏览器走查。
- 配套机读证据：
  - `admin-evidence-manifest.json`：9 张管理端截图的视口、实际尺寸、落地 URL、横向溢出量、`pageerror` / 控制台错误计数、主内容文本、demo 标记可见性。
  - `teacher-evidence-manifest.json`：12 张教师端截图同上字段，另含趋势表行数、图表系列数、农场只读徽标可见性、时区。
  - `admin-api-verification.json` / `teacher-api-verification.json`：A–E 端点的状态码与关键原始字段（不含 token、口令、完整 UUID、邮箱）。

## 1. 演示数据与命名空间

全部演示数据落在本地租户 `vocabdemo`（`school=vocabdemo`），标题统一 `[DEMO]` 前缀，**仅本地 mock，不用于生产**。种子/清理脚本见 `backend/scripts/demo_vocab/`（`seed_demo.py` / `cleanup_demo.py` / `README.md`）。

| 对象 | 计数 / 口径 |
| --- | --- |
| 五级演示词库 / 词条 | 5 / 220（KET、PET、ACADEMIC、CET4、IELTS_TOEFL 各 44） |
| 授权演示词库 / 词条 | 2 / 30（教材 20 条、过期 10 条） |
| 版本快照 / 授权审计 | 7 个库合计 10 版 / 3 条 |
| 课堂 / 学生 | `VOCDEMO1` 12 名、`VOCDEMO2` 6 名（仅名单，无可登录账号） |
| 演示账号 | 1 `school_admin`（`vocabdemo.admin@example.com`）+ 1 `teacher` + 12 名可登录学生；口令由 `VOCAB_DEMO_PASSWORD` 提供，证据不写明文 |
| 教师任务 / 会话 | 5 个任务；49 个会话（37 submitted / 12 in_progress） |
| 首答 / 重试答案 | 358 / 31 |
| FSRS 状态 | 24（overdue 8 / 本周 9 / 未来 7） |
| PK | 2 大厅 / 2 终态对局 / 4 玩家 / 24 作答 |
| 农场 | 5 地块 / 4 徽章 |
| 课堂看板底座 | `vocabulary` + `speaking` 两个模块已开通；1 篇最小原创演示朗读篇目，使 `/classes/{code}/board` 可 200 |

- 演示词库 `source_type` 覆盖 `demo`（五级库）、`textbook`（教材库）、`licensed`（过期库）；数据与 UI 均带 `[DEMO]` / `演示 Mock` 标记。
- `vocabdemo` 租户每次重跑 seed 会重建，租户 UUID 会变；取证按邮箱 + `school=vocabdemo` 登录，不依赖旧 UUID。

## 2. 三档双语截图清单（21 张）

> 指标口径：横向溢出 = `document.documentElement.scrollWidth - clientWidth`，21 张均为 **0**；`pageerror=0`、控制台错误=0。截图前已隐藏侧栏、`sidebar-gap` 占位、粘性页头/页脚与 TanStack devtools 浮标；画面不含真实邮箱、token、`open_id` 或生产地址。

### A. 授权台账（管理端，`school_admin`）

| 文件 | 尺寸 | 语言 | 画面内容 | 溢出 | pageerror |
|---|---|---|---|---|---|
| `A-1180-zh-book-license.png` | 1180×3243 | 中文 | `[DEMO] 过期授权词库`：source_type=授权引进（licensed）、授权方、凭证、到期日、备注、授权变更记录、版本历史 | 0 | 0 |
| `A-390-zh-book-license.png` | 390×844 | 中文 | 同上授权面板窄屏单列，字段完整 | 0 | 0 |
| `A-820-en-book-license.png` | 820×1493 | 英文 | 30 天提醒摘要（Expiring 0 / Expired 11）+ License 卡：Licensed、owner、ref、expiry、change history、Export license list | 0 | 0 |
| `A-1180-zh-demo-badge.png` | 1180×3569 | 中文 | `source_type=demo` 的 `[DEMO] KET 演示词库`：标题旁「演示 Mock」徽标 +「演示 / Mock 内容：仅本地演示，不用于生产。」+ 44 行词条 | 0 | 0 |
| `A-1180-zh-license-alerts.png` | 1180×900 | 中文 | 30 天提醒列表 11 条：全部 `已过期`，含词库级与词条级 | 0 | 0 |

### B. 版本历史 / 对比 / 回滚（管理端）

| 文件 | 尺寸 | 语言 | 画面内容 | 溢出 | pageerror |
|---|---|---|---|---|---|
| `B-1180-zh-version-history.png` | 1180×900 | 中文 | KET 库 v1 初始创建 / v2 编辑词条 / v3 加词；版本号、操作人、时间、词数、摘要、哈希、回滚入口 | 0 | 0 |
| `B-820-en-version-compare.png` | 820×900 | 英文 | v1→v2：Added 4；Changed 1（apple，Meaning / Example 两维），Before / After 在单元格内换行、无串列 | 0 | 0 |
| `B-390-zh-rollback-confirm.png` | 390×844 | 中文 | 回滚二次确认：v3；「生成新版本、不删除历史：原有版本记录全部保留。」「已发布任务快照不受影响：学生仍按发布当时的快照练习与判分。」 | 0 | 0 |
| `B-1180-en-audit-csv.png` | 1180×900 | 英文 | 教材库授权面板 + 按库审计 2 条（词条引用号变更、续期审计）+ Export license list CSV 入口 | 0 | 0 |

### C. 教师跨任务 / 时间趋势

| 文件 | 尺寸 | 语言 | 画面内容 | 溢出 | pageerror |
|---|---|---|---|---|---|
| `C-1180-zh-trend.png` | 1180×2453 | 中文 | 趋势 Tab：周粒度 / 12 周期 / 全部词库 / 全部题型；4 张指标卡；双系列折线（完成率/首答正确率）+ 低/中/高/无数据分段堆叠；12 行周期明细 | 0 | 0 |
| `C-390-zh-trend.png` | 390×2995 | 中文 | 窄屏：筛选单列、指标 2 列、图表/表格容器内横滚，整页无横向溢出 | 0 | 0 |
| `C-820-en-trend.png` | 820×2743 | 英文 | `Teaching reference only — not a test score or ability certification` 声明可见；英文筛选/指标/图表/表头 | 0 | 0 |

### D. 教师 PK 历史

| 文件 | 尺寸 | 语言 | 画面内容 | 溢出 | pageerror |
|---|---|---|---|---|---|
| `D-1180-zh-pk-history.png` | 1180×1410 | 中文 | PK 对战 Tab：现有开厅/等待/进行中区 + 历史对局 2 场，最近一场 2026/11/19 18:10（演示学生03 500 胜 / 演示学生04 300），展开玩家明细 | 0 | 0 |
| `D-820-en-pk-history.png` | 820×1692 | 英文 | 英文历史表头 / 状态 / 胜者 / 玩家明细，时间 `11/19/2026, 6:10:00 PM` | 0 | 0 |
| `D-390-zh-pk-history.png` | 390×1843 | 中文 | 窄屏历史表，容器内横向滚动，整页不撑破 | 0 | 0 |

### E. 农场教师只读概览 + 课堂看板摘要

| 文件 | 尺寸 | 语言 | 画面内容 | 溢出 | pageerror |
|---|---|---|---|---|---|
| `E-1180-zh-farm.png` | 1180×1023 | 中文 | 农场 Tab：`只读概览` 徽标；参与地块 5 / 成熟 2 / 累计收获 6 / 徽章总数 4；徽章分布与收获榜 Top3 | 0 | 0 |
| `E-820-en-farm.png` | 820×1431 | 英文 | `Read-only overview`；英文指标 / 徽章 / 收获榜 | 0 | 0 |
| `E-390-zh-farm.png` | 390×1743 | 中文 | 窄屏单列指标卡，不撑破 | 0 | 0 |
| `E-1180-zh-board-cards.png` | 1100×284 | 中文 | 课堂看板「学生结果」内 PK 卡 + 农场卡；最近一场 2026/11/19 18:10、胜者 演示学生03 | 0 | 0 |
| `E-820-en-board-cards.png` | 772×316 | 英文 | 英文 PK / 农场摘要卡，最近一场 `11/19/2026, 6:10:00 PM` | 0 | 0 |
| `E-390-zh-board-cards.png` | 358×781 | 中文 | 390 宽两卡单列；卡内指标窄屏 2 列，「参与地块 / 累计收获 / 进行中对局」标签单行不折字 | 0 | 0 |

### 关键 UI 口径核对

- **Demo 标记分层**：`source_type=demo` 的五级库/词条显示红「演示 Mock」+「仅本地演示，不用于生产」；`licensed` 的过期库只带 `[DEMO]` 前缀与备注里的 demo 说明，不显示 Mock 徽标（`A-1180-zh-demo-badge.png` 专门补拍 demo 来源库取证）。
- **回滚不改历史**：确认弹窗明确「生成新版本、不删除历史」「已发布任务快照不受影响」。
- **趋势不是成绩**：筛选区常驻「教学参考，不是考试分数 / 能力认证」；表格脚注说明 `到期未复习` 按当前 FSRS 状态回算、历史周期仅供参考。
- **农场只读**：页头 `只读概览`，无种植/收获/改分按钮；数据只来自 `teacher/farm-summary`。
- **看板只读**：PK/农场摘要卡仅有「进入词汇页」深链；看板原有数值口径与卡片顺序未改。

## 3. API 口径验证结果（2026-11-25 实时复核）

### A/B 管理端（`school_admin`）

| # | 口径 | 实际结果 | 结论 |
|---|---|---|---|
| A1 | 管理员登录与租户 | `POST /login/access-token?school=vocabdemo` 200，role=`school_admin`，租户匹配 | 通过 |
| A2 | 30 天提醒 | `GET /vocabulary/license/alerts?days=30` 200，**11 条**，`statuses=["expired"]`，临期 0 / 过期 11 | 通过 |
| A3 | 词库与来源 | `GET /vocabulary/books` 200，**7 个**，全部 `[DEMO]` 前缀；`source_type={demo,textbook,licensed}` | 通过 |
| A4 | 过期库授权字段 | 按标题解析 `[DEMO] 过期授权词库`：200，`source_type=licensed`、`license_owner=演示授权方（DEMO）`、`license_ref=DEMO-LICENSED-EXPIRED`、`license_expires_at=2026-10-26T00:00:00Z` | 通过 |
| A5 | CSV 导出 | `GET /vocabulary/license/export.csv` 200，`text/csv; charset=utf-8`，UTF-8 BOM=true，表头 6 列：`词库/词条,source_type,授权方,凭证,到期日,状态` | 通过 |
| B1 | 版本列表 | `[DEMO] KET 演示词库` 200，**3 版**，`version_no=[1,2,3]` | 通过 |
| B2 | 版本对比 | `compare?from_version=1&to_version=2` 200，**added 4 / removed 0 / changed 1**；变更维度 `meaning、example` | 通过 |
| B3 | 授权审计 | `GET /vocabulary/license/audit` 200，**3 条**；字段含 target、actor、changes、created_at、tenant_slug 等 | 通过 |
| B4 | 回滚 | 打开二次确认后点取消，**本轮未执行 rollback / 未保存授权**；不改历史与快照语义由后端测试覆盖 | 只读取证，未实操写 |

### C/D/E 教师端（`teacher`）

| # | 口径 | 实际结果 | 结论 |
|---|---|---|---|
| C1 | 趋势 5 周期 | `trend?granularity=week&periods=5` 200，`teaching_reference=true`；targets 全 12；完成率 **75/75/75/42/42**；首答数 **80/80/72/56/70**；首答正确率 75/68/69/77/77；到期未复习 **0/0/0/1/6** | 通过 |
| C2 | 趋势 CSV | 200，`text/csv; charset=utf-8`，UTF-8 BOM=true，14 列表头（周期、起止、目标/完成/完成率、首答/正确/正确率、低/中/高/无数据、到期未复习），5 行 | 通过 |
| D1 | PK 历史 | `pk/history?limit=10` 200，**2 场**终态 `finished`，按时间倒序；最近一场 演示学生03 500 胜 / 演示学生04 300 负；次场 演示学生01 500 / 演示学生02 300；每场 players=2 | 通过 |
| D2 | 历史时间 | 原始 UTC `2026-11-19T10:10:00Z`；Asia/Shanghai 显示 `2026/11/19 18:10:00` | 通过 |
| E1 | 农场摘要 | `teacher/farm-summary` 200，`participants=5`、`mature_plots=2`、`harvested_total=6`；徽章 首次收获×3 / 七次收获×1；收获榜 演示学生01(3)、05(2)、02(1) | 通过 |
| E2 | 课堂看板 | `classes/VOCDEMO1/board` 200，`vocabulary_pk` 与 `vocabulary_farm` **均非 null**；PK 未开厅、排队 0、进行中 0、本周对局 0（最近一场 11/19 属上一周）；farm 5/2/6 | 通过 |
| P1 | 学生越权 | 学生 token：`farm-summary` 403、`trend` 403（需 teacher）、`pk/history` 403（仅本班教师） | 通过 |

## 4. 本地环境说明（非业务代码缺陷）

- 迁移 `b6c7d8e9f0a1` / `c7d8e9f0a2b3` apply 后，新表 `vocabulary_book_version`、`vocabulary_license_audit` 对受限应用角色缺 SELECT/GRANT，首次调用版本/审计端点 500。按项目既有 prestart 流程幂等运行 `backend/scripts/ensure_db_roles.py`（仅 GRANT/角色属性同步，未增删改任何业务行）后恢复 200。生产由 `backend/scripts/prestart.sh` 统一执行，属本地迁移后未重放授权步骤。
- 课堂看板底座需要 `speaking` 模块；`vocabdemo` 只开 `vocabulary` 时 `/board` 返回 403 `module_not_enabled:speaking`；补开 speaking + 1 篇最小演示篇目后 200。均为本地演示数据配置，不进生产。

## 5. 隐私与 Mock 声明

- 截图均裁到主内容区，侧栏/页头邮箱/devtools 已隐藏；画面与全部 JSON 经扫描，无真实邮箱、token、`open_id`、完整 UUID、生产地址。
- API JSON 不保存 access token；登录仅记录 role 与“租户匹配”结论。
- 本批所有词库、词条、账号、课堂、任务、作答、PK、农场记录均为本地 `vocabdemo` 演示数据，标题/描述带 `[DEMO]` 或 Demo 标记，**不用于生产、不得导入生产库**。

## 6. 观察与未验证项

- **未执行写操作**：未实际回滚版本、未保存授权、未开厅/收获；A/B/E 的写路径与权限由后端测试覆盖，浏览器只验证只读展示与确认弹窗文案。
- **审计 UI 按库过滤**：管理端审计列表只显示当前展开词库的记录（教材库 2 条）；API 全量 3 条已记入 `admin-api-verification.json`。
- **licensed demo 库无 Mock 徽标**：Mock 徽标仅在 `source_type=demo` 渲染；licensed 的过期库以 `[DEMO]` 前缀 + 备注标记，见 `A-1180-zh-demo-badge.png` 对照。
- **平台运营只读端**：`/admin/vocabulary/license/audit`、`/admin/vocabulary/license/export.csv` 后端已实现，管理端 UI 未接线，本轮未取证。
- **趋势历史口径**：`due_unreviewed` 按当前 FSRS 状态回算，历史周期不是精确还原；跨校/非本班教师沿用既有 helper 返回 403（不是 404）。
- **窄屏内部横滚**：C 趋势表、D PK 历史表在 390 宽使用容器内横向滚动，整页无横向溢出；部分右侧列需滑动查看。
- **时区**：本机系统时区为 PST，浏览器 context 已显式 `Asia/Shanghai`；所有时间展示按上海时区核对。
- **未覆盖视角**：学生端本轮未截图；VOCDEMO2 仅名单、无登录账号；平台运营身份未造。
