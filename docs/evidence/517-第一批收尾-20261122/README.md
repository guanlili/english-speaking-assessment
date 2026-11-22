# 517 第一批收尾 · 浏览器闭环测试证据（2026-11-22）

> 测试对象：`english-speaking-assessment` 词汇第一批功能（四题型：英译中 `en_zh` / 中译英 `zh_en` / 语境填空 `cloze` / 词根拼装 `roots`）。
> 测试方式：真实浏览器（Aha Browser Use，CDP 视口覆盖）+ 直连 API / 数据库核验。所有演示数据均加 `E2E517` 前缀隔离。
> 本次测试**未 commit / push，未发 GitHub 评论，未改业务源码**；证据仅落本目录。演示语料为 AI 起草待审核，本报告不代表教师已验收。

## 1. 测试环境与服务状态

| 项 | 值 |
|---|---|
| 后端服务 | `uvicorn`，监听 `127.0.0.1:8001`，健康检查 `/api/v1/utils/health-check/` 返回 200 / true |
| 前端服务 | `vite`，监听 `127.0.0.1:5175`，首页 200 |
| 数据库 | 本地 docker `english-speaking-assessment-db-1`（5433，库名 `app`，用户 `postgres`）；未触碰 5173/8000 上的旧 docker 容器 |
| 服务进程（收尾探测） | 前端 PID 24213（LISTEN 5175）全程未重启；后端几经重启：初版 24125 → D1 复验 28689 → 第二批 FSRS 冒烟当前 PID 38312（LISTEN 8001，健康 200） |
| 测试课堂 | code `AY6S7T`，classroom_id `e21c4093-7ed6-440a-b8da-781ac8aed463` |
| 测试时间 | 2026-11-22（UTC+8）；D1 修复复验同日进行 |

### 隔离测试账号（不含口令；口令仅存于本机 scratch，未写入本目录）

| 角色 | 标识 | 说明 |
|---|---|---|
| 教师 | `e2e517-t@example.com`（显示名 E2E517教师） | 发布任务、查看结果 |
| 学生 A | `e2e517-a`（id `f198528c-49b2-46aa-a6d8-73b89653fce0`，显示名 学生A） | 任务目标名单内，完成四类各一题 |
| 学生 B | `e2e517-b`（id `b8f6d0a3-3ec4-4acd-98e6-7116d52de206`） | 不在目标名单，用于隔离可见性验证 |

### 隔离演示词库

| 词库 | id | 词数 | 素材情况 | 用途 |
|---|---|---|---|---|
| 本班主库 | `9c5e128a-fcce-441e-875e-c1cd4cd670ee` | 18 | 有例句、部分有词法拆解 | 闭环任务 + 自主练习主场景 |
| 素材不足演示库 | `fce04593-bf44-4cf9-acf3-9c505cbccc4f` | 2 | 无例句、无拆解 | 阻断 / 422 场景 |
| 公共书 Pets & School | `f96c19b6-56f8-43c1-bed7-c9ae8260f718` | 20 | 有例句、无拆解 | roots 阻断对照 |

任务：assignment id `9c90310b-9219-4796-a222-639252af7cc1`，标题「E2E517 第一批四题型任务」，`prompt_types = ["en_zh","zh_en","cloze","roots"]`，18 词，第 1 期。

## 2. 闭环四步测试结论

### 2.1 教师发布（四题型勾选 + 手动分组）

| 检查项 | 实测结果 | 结论 | 证据 |
|---|---|---|---|
| 发布面板四题型可选 | 四类题型复选框均出现，教师勾选全部四类 | 已验证 | `01-publish-prompt-types-zh.png` |
| 手动分组目标名单 | 分组仅选中学生 A（1/2），学生 B 不在名单 | 已验证；DB 核验 `target_count = 1` | `02-publish-group-zh.png` |

### 2.2 学生隔离可见性

| 检查项 | 实测结果 | 结论 | 证据 |
|---|---|---|---|
| 学生 B 不可见任务 | 学生 B 端 UI 无任务；API today / assignments 名单为空（`assignments: []`） | 已验证 | `03-student-b-no-task-zh.png` |
| 学生 A 可见任务 | 学生 A 端今日任务列表出现该任务，可进入作答 | 已验证 | `04-a-en-zh-prompt-zh.png` 起 |
| 他课堂旧书不可见 | 学生 A 端词库列表不含他课堂两本旧书（2 词 / 4 词，无例句无拆解）；学生端直连 `/vocabulary/books/{id}` 返回 403/404，必须走 `/classes/{code}/vocabulary/student/books/{book_id}` | 已验证 | （API 核验，无独立截图） |

### 2.3 作答与判分（四类各答对一题）

| 题型 | 作答词 | 题面 | 判分反馈 | 证据 |
|---|---|---|---|---|
| 英译中 en_zh | apple | 已验证 | 答对，首答正确 | `04-a-en-zh-prompt-zh.png` / `05-a-en-zh-feedback-zh.png` |
| 中译英 zh_en | banana | 已验证 | 答对，首答正确 | `06-b-zh-en-prompt-zh.png` / `07-b-zh-en-feedback-zh.png` |
| 语境填空 cloze | careless | 已验证（拼写输入） | 答对，首答正确 | `08-c-cloze-prompt-zh.png` / `09-c-cloze-feedback-zh.png` |
| 词根拼装 roots | teacher | 已验证（拼写输入） | 答对，首答正确 | `10-d-roots-prompt-zh.png` / `11-d-roots-feedback-zh.png` |

DB / API 核验：任务会话 18 题构成 `en_zh 5 / zh_en 5 / cloze 4 / roots 4`，四类题型在题单真实出现；学生 A 共答 4 题、首答正确 4 题。

### 2.4 教师结果统计

| 检查项 | 实测结果 | 结论 | 证据 |
|---|---|---|---|
| 题型维度统计 | `prompt_type_stats` 四类均出现：`en_zh 1答/1对`、`zh_en 1答/1对`、`cloze 1答/1对`、`roots 1答/1对`，首答正确率均 100% | 已验证 | `12-teacher-results-stats-zh.png` / `13-teacher-results-stats-rows-zh.png` / `43-teacher-results-prompt-stats-en.png` |
| 学生维度统计 | 学生 A：4/18，首答正确 4，正确率 100%，状态进行中 | 已验证 | `42-teacher-results-stats-en.png` |
| 英文统计区翻译 | 列标题 `PROMPT TYPE / ANSWERED ITEMS / FIRST-TRY CORRECT / FIRST-TRY ACCURACY` 及四类标签 `English → Chinese / Chinese → English / Fill the Gap / Word Parts` 均为英文；中文态对应完整 | 已验证 | `42` / `43` |

## 3. 自主练习题型入口与素材阻断

### 3.1 词库选择页题型选择器

| 检查项 | 实测结果 | 结论 | 证据 |
|---|---|---|---|
| 四题型分组与标签 | `/vocab/{code}/books` 选中词库后出现分组「出题方式（题型）/ Question types」，四项：英译中 / 中译英 / 语境填空 / 词根拼装，中英双语标签齐全 | 已验证 | `14-self-books-types-zh.png` |
| 可出词数徽标 | 每项带「N 词可出」/「N words」徽标；默认仅勾选前两项（英译中、中译英）；D1 修复后 roots 在 18 词主库显示「14 词可出」 | 已验证 | `14-self-books-types-zh.png` / `44-self-books-roots-badge-zh.png` |
| 素材不足项禁用 + 原因 | 不可出题型置灰禁用，并给出具体原因；勾选不可出项时「开始」按钮禁用，`role=alert` 双语告警 | 已验证 | `22-deficient-book-blocked-zh.png` / `23-deficient-book-blocked-en.png` |

### 3.2 自主轮出题（18 词主库）

#### 3.2.1 修复前基线轮（D1 阻断状态，2026-11-22 早些时候）

| 检查项 | 实测结果 | 结论 | 证据 |
|---|---|---|---|
| 自主轮题型构成 | 自主轮 18 题：`en_zh 6 / zh_en 6 / cloze 6 / roots 0` | 已验证（UI + API） | `15`–`20` |
| 前三类在 UI 真实出现并可作答 | 英译中、中译英选择题点选项；语境填空拼写输入；三类各答对一题（careless / teacher / kindness），每题头部有题型小标签 | 已验证 | `15-self-en-zh-prompt-zh.png` / `16-self-en-zh-feedback-zh.png` / `17-self-zh-en-prompt-zh.png` / `18-self-zh-en-feedback-zh.png` / `19-self-cloze-prompt-zh.png` / `20-self-cloze-feedback-zh.png` |
| 词根拼装 roots 自主轮 | 当时被 D1 阻断：前端预判恒判 0 词、不可勾选（后端接口可出，API 已验证）。该阻断状态已随 D1 修复消除，见 3.2.2 | 基线记录 | （API 核验，无 UI 截图） |

#### 3.2.2 D1 修复后复验轮（2026-11-22）

复验前已清理修复前遗留的进行中自主轮（会话 `db9c089c-3ba8-4956-9bbf-a9cdec805c38`，含 3 条作答，仅 E2E517 测试数据；教师任务会话未动），由新代码重新开轮。复验会话 `be098bbe-39ea-411f-bd8a-32f5f00bdabb`。

| 检查项 | 实测结果 | 结论 | 证据 |
|---|---|---|---|
| roots 可出词数徽标 | 18 词主库选中后，「词根拼装」徽标显示 **14 词可出**（API 复核：15 词带拆解，其中 14 词拆解可拼回原词），复选框可勾选、未禁用；英译中 / 中译英 / 语境填空均 18 词可出 | 已验证 | `44-self-books-roots-badge-zh.png` |
| 复验轮题型构成 | 新轮 18 题：`roots 4 / en_zh 5 / zh_en 5 / cloze 4`，四类题型在题单真实出现 | 已验证（API + UI 逐题核对） | 会话 `be098bbe…` |
| 四类 UI 渲染 | Q1 roots 拼装、Q2 英译中选择、Q3 中译英选择、Q5 语境填空输入，题面头部题型小标签均正常渲染 | 已验证 | `45` / `46` / `47`；`15`–`20` |
| roots 作答判分 | Q1 词根拼装 `preheat`（词块 tion / re / pre / heat，含两个干扰块），首答拼对，反馈「拼对了！preheat」；会话级首答正确 1 | 已验证 | `45-self-roots-prompt-zh.png` / `46-self-roots-feedback-zh.png` |
| roots 窄屏适配 | 390px 中文态 roots 反馈页：`innerWidth 390 / scrollWidth 390`，无横向溢出，词块自动换行 | 已验证 | `47-self-roots-zh-390.png` |

### 3.3 素材不足场景实测

| 场景 | 选择题（<4 词） | 语境填空（缺例句） | 词根拼装（缺拆解） | 证据 |
|---|---|---|---|---|
| 2 词不足演示库（无例句无拆解） | 禁用：词库不足 4 词，无法构造干扰项 | 禁用：无词条含自身的例句 | 禁用：无词条拆解可拼回原词 | `22-deficient-book-blocked-zh.png`（中文告警）/ `23-deficient-book-blocked-en.png`（英文标签与原因） |
| 公共书 Pets & School（20 词，有例句无拆解） | 可选 | 可选 | 禁用：无词法拆解 | `21-pets-roots-blocked-zh.png` |

英文态原因文案实测完整：
- 选择题：`Fewer than 4 words – choice distractors can't be built.`
- 填空：`No word has an example sentence containing it.`
- 词根：`No word's parts assemble back to the whole word.`
- 告警：`These types can't be offered…`（对应中文「以下题型当前词库无法出题，请先去掉…」）。

### 3.4 后端 422 文案分流（直连 API）

创建自主轮被后端二次校验拦截时，三类 422 `detail` 分流明确、互不混淆；前端 `describeSelfSession422` 映射为双语说明。

| 触发条件 | 后端 422 detail（中文原文） | 结论 |
|---|---|---|
| 选择题不足 4 词 | 「选择题至少需要 4 个词才能生成干扰项；请多选几个词，或去掉选择题」 | 已验证 |
| 缺例句（填空） | 「语境填空要求词条带例句且例句包含该词本身；所选词条都不满足，请先补例句，或去掉语境填空」 | 已验证 |
| 缺词法拆解（roots） | 「词根拼装要求词条带词法拆解（前缀/词根/后缀），且拆解能拼回原词；所选词条都不满足，请先补词法拆解，或去掉词根拼装」 | 已验证 |

## 4. 三档屏宽 × 双语量化扫描

扫描方法：CDP `Emulation.setDeviceMetricsOverride` 覆盖 390 / 820 / 1180 三档宽度；每格采集 `innerWidth`、`documentElement.scrollWidth`、高度 <44px 的可点元素清单、`font-size <16px` 的表单控件；TanStack devtools 调试浮层元素不计入产品判定。

判定口径：
- 无横向溢出：`scrollWidth <= innerWidth`；
- 主操作 / 选项卡片触控高 ≥44px；
- 表单控件字号 ≥16px（防 iOS 聚焦放大）；
- 词的中文释义、书目标题、学生姓名为演示语料数据，不计入 UI 未翻译。

### 4.1 词库选择页 `/vocab/{code}/books`

| 屏宽 | 语言 | innerWidth | scrollWidth | 横向溢出 | <44px 可点数 | 表单控件数 | <16px 字号控件 | 截图 |
|---|---|---|---|---|---|---|---|---|
| 390 | 中文 | 394 | 394 | 无 | 32 | 2 | 无 | `24-books-zh-390.png` |
| 820 | 中文 | 820 | 820 | 无 | 104 | 2 | 无 | `25-books-zh-820.png` |
| 1180 | 中文 | 1180 | 1180 | 无 | 104 | 2 | 无 | `26-books-zh-1180.png` |
| 390 | 英文 | 398 | 398 | 无 | 20 | 2 | 无 | `27-books-en-390.png` |
| 820 | 英文 | 820 | 820 | 无 | 92 | 2 | 无 | `28-books-en-820.png` |
| 1180 | 英文 | 1180 | 1180 | 无 | 92 | 2 | 无 | `29-books-en-1180.png` |

### 4.2 学生练习页 `/vocab/{code}/practice`

| 屏宽 | 语言 | innerWidth | scrollWidth | 横向溢出 | <44px 可点数 | 表单控件数 | <16px 字号控件 | 截图 |
|---|---|---|---|---|---|---|---|---|
| 390 | 英文 | 390 | 390 | 无 | 43 | 0 | 无 | `30-practice-en-390.png` |
| 820 | 英文 | 820 | 820 | 无 | 117 | 0 | 无 | `31-practice-en-820.png` |
| 1180 | 英文 | 1180 | 1180 | 无 | 117 | 0 | 无 | `32-practice-en-1180.png` |
| 390 | 中文 | 390 | 390 | 无 | 43 | 0 | 无 | `33-practice-zh-390.png` |
| 820 | 中文 | 820 | 820 | 无 | 117 | 0 | 无 | `34-practice-zh-820.png` |
| 1180 | 中文 | 1180 | 1180 | 无 | 117 | 0 | 无 | `35-practice-zh-1180.png` |

### 4.3 教师结果页 `/t/AY6S7T/vocab`（完成情况 tab）

| 屏宽 | 语言 | innerWidth | scrollWidth | 横向溢出 | <44px 可点数 | 表单控件数 | <16px 字号控件 | 截图 |
|---|---|---|---|---|---|---|---|---|
| 390 | 中文 | 390 | 390 | 无 | 11 | 1 | 无 | `36-teacher-results-zh-390.png` |
| 820 | 中文 | 820 | 820 | 无 | 142 | 1 | 无 | `37-teacher-results-zh-820.png` |
| 1180 | 中文 | 1180 | 1180 | 无 | 16 | 1 | 无 | `38-teacher-results-zh-1180.png` |
| 390 | 英文 | 390 | 390 | 无 | 11 | 1 | 无 | `39-teacher-results-en-390.png` |
| 820 | 英文 | 820 | 820 | 无 | 16 | 1 | 无 | `40-teacher-results-en-820.png` |
| 1180 | 英文 | 1180 | 1180 | 无 | 16 | 1 | 无 | `41-teacher-results-en-1180.png` |

补充统计区截图：`42-teacher-results-stats-en.png`（逐词错词表 + 学生完成度）、`43-teacher-results-prompt-stats-en.png`（四题型统计表）。

### 4.4 触控高度与字号观察

- **主操作与选项卡片**：选择题选项卡片实测满宽、高度 ≥44px；三档宽度下无横向溢出。
- **<44px 的产品元素（均为图标 / 次要控件，非主操作）**：侧边导航项 ~40px、语言切换钮 28px、外观切换钮 32–36px、返回链接 ~20px、顶部视图 tab / 刷新 / 导出 / 结束任务钮 36px、logo 区 43px、课堂徽章 ~30px。
- **结果表内逐词展开图标按钮**：820 中文格展开态下高度 16–25px（图标型小按钮，`Open match details`），建议后续评估是否加大点击热区。
- **跳过链接**（「跳至主要内容 / Skip to main content」）高度 1px，为无障碍隐藏链接，不计入触控判定。
- **表单字号**：books 页 2 个搜索输入、results 页 1 个期数 `select`，实测 `font-size ≥16px`；practice 页扫描题位为选择题，当前题位无文本输入控件。

### 4.5 双语与未翻译核查

- 三页（books / practice / teacher results）在中文、英文两态下，导航、按钮、tab、告警、统计列标题、题型标签均完整翻译，未见残留未翻译 UI 文案。
- 词头中文释义、书目标题 / 描述、学生姓名为演示语料数据（中文），按口径不计入 UI 未翻译。

## 5. 缺陷与修复记录

**D1（前端 roots 恒 0 阻断）— 已修复并复验通过（2026-11-22）**

- 原现象：学生端词库列表中，词根拼装在所有词库恒显「0 词可出」并禁用，即使 DB 中词条已带词法拆解。
- 原定位：后端学生词库序列化 `backend/app/api/routes/vocabulary_shared.py` 的 `_word_public()` 未把 `morphology` 传入公开模型（`backend/app/models/vocabulary/words.py:62` 的 `VocabularyWordPublic.morphology` 字段存在），导致学生端词条 `morphology` 恒为 `null`；前端预判 `frontend/src/lib/vocab-prompt-availability.ts`（`morphologyAssembles` / `countEligibleByPromptType`）据此判 roots 可出词数为 0。
- 修复：`_word_public()` 补传 `morphology=word.morphology`（响应模型本就有该字段，契约不变）；新增回归用例 `backend/tests/api/routes/test_vocabulary_student.py::test_student_book_exposes_morphology_for_prompt_availability`，本地运行 **1 passed**，ruff 干净。
- 复验（后端重启后，健康检查 200）：
  - API：学生 A 词库接口 18 词中 15 词回传非空 `morphology`，14 词拆解可拼回原词；
  - UI：18 词主库 roots 徽标显示「14 词可出」、可勾选；新自主轮 `be098bbe…` 构成 `roots 4 / en_zh 5 / zh_en 5 / cloze 4`，roots 题面渲染正常，`preheat` 首答拼对；
  - 证据：`44-self-books-roots-badge-zh.png` / `45-self-roots-prompt-zh.png` / `46-self-roots-feedback-zh.png` / `47-self-roots-zh-390.png`。
- 复验环境：后端 8001 已用修复后代码重启（复验时 PID 28689）；前端 5175 未重启。

## 6. 第二批 FSRS 复习引擎冒烟（2026-11-22）

> 范围：教师发布 → 学生可见 → 作答判分 → 教师统计闭环之外，追加验证第二批 FSRS 到期复习队列、统计接口、复习轮出题与调度重排。演示数据仍仅 E2E517 隔离；未 commit、未发评论、未改业务源码。

### 6.1 环境与前置

- 后端按当前源码重启：kill 旧 PID 28689 后，`POSTGRES_SERVER=127.0.0.1 POSTGRES_PORT=5433 ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001`，当前 PID 38312，健康检查 200；前端 5175 未动（PID 24213）。
- 迁移 `d9a1b2c3e4f5` 已 apply 到本地 dev 库 5433。**环境缺口记录**：新表 `vocabulary_review_state` 初始未授受限角色 DML 权限，接口首调 500（`permission denied for table vocabulary_review_state`）；按 prestart 既定流程补跑 `scripts/ensure_db_roles.py`（幂等授权 esa_app / esa_platform）后恢复。属本地部署授权步骤未重放，非业务代码缺陷。

### 6.2 接口基线（造数前，学生 A）

| 接口 | daily_limit | reviewed_today | due_today | remaining_today | tracked / due / learning / review / recognition / spelling |
|---|---|---|---|---|---|
| `GET .../review-queue` | 20 | 0 | 0 | 20 | — |
| `GET .../review-stats` | — | 0 | — | — | 0 / 0 / 0 / 0 / 0 / 0 |

### 6.3 到期造数（仅 E2E517 学生 A 已答词；未动教师任务会话与快照）

直接写 `vocabulary_review_state` 3 条（账号 `3b31ca01-7219-4ede-9c1d-b67645b40b11`，租户默认）：

| 词条 | 能力维度 | 状态 | 到期时间（UTC） | 逾期天数 | reps | lapses | 间隔(天) |
|---|---|---|---|---|---|---|---|
| apple | recognition 认读 | learning | 2026-11-19 07:03 | 3 | 2 | 1 | 1 |
| careless | spelling 拼写 | learning | 2026-11-21 07:03 | 1 | 1 | 0 | 1 |
| teacher | spelling 拼写 | learning | 2026-11-22 02:03 | 0（今日到期） | 1 | 0 | 1 |

### 6.4 队列与统计实测（造数后、作答前）

**review-queue 摘要**：`daily_limit=20`，`reviewed_today_count=1`，`due_today_count=3`，`remaining_today_count=19`，`items=3`。

| 词条 | capability | state | due_at | overdue_days | lapses | 建议题型 |
|---|---|---|---|---|---|---|
| apple | recognition | learning | 2026-11-19T07:03:05Z | 3 | 1 | `en_zh` |
| careless | spelling | learning | 2026-11-21T07:03:05Z | 1 | 0 | `meaning` |
| teacher | spelling | learning | 2026-11-22T02:03:05Z | 0 | 0 | `meaning` |

**review-stats 实测**：`tracked_count=3`，`due_count=3`，`reviewed_today_count=1`，`learning_count=3`，`review_count=0`，`recognition_count=1`，`spelling_count=2`。

### 6.5 复习轮（UI + API）

- 会话 `3ec353dc-cdab-46d5-bf24-12998c2e4c37`，`kind=review_fsrs`，3 题；题单构成 **`en_zh 1 / meaning 2`**（apple 认读英译中；careless、teacher 拼写看义拼词），与到期队列一致。
- Q1 `apple` 英译中选「苹果」，首答正确，反馈「拼对了！apple」。证据 `51` / `52`。
- **刷新稳定**：刷新后续到 Q2/3，首答正确 1，Q1 已答状态保留，题单与题序未变。证据 `53`。
- **FSRS 重排（作答后 API 复核）**：apple 由 `learning → review`，`reps 2→3`，`due_at` 推到 2026-11-24 11:39，`interval_days=2`，`last_rating=good`，`last_is_correct=true`；该词移出到期队列。队列摘要变为 `due_today=2`、`reviewed_today=2`、`remaining=18`；stats `due=2`、`reviewed_today=2`、`learning=2`、`review=1`。

### 6.6 三档 × 双语抽查（卡片 + 复习题面）

| 表面 | 390 中文 | 1180 中文 | 820 英文 | 实测口径 |
|---|---|---|---|---|
| 今日复习卡片 | `49-review-card-zh-390.png` | `48-review-card-zh-1180.png` | `50-review-card-en-820.png` | 三格 `scrollWidth=innerWidth` 无横向溢出；主按钮「开始复习 / Start Review」44px |
| 复习题面 | `54-review-fsrs-zh-390.png` | `55-review-fsrs-zh-1180.png` | `56-review-fsrs-en-820.png` | 三格无横向溢出；提交 / Submit 48px；拼写输入框 `font-size=16px` |

- 卡片英文标签完整：Today's Review / Spaced Repetition / Due today / Reviewed today / Left today / Daily limit；队列条目标签 Recognition / Spelling、N days overdue、Last correct、N-day interval、N reviews · N lapses。
- 题面英文标签完整：Scheduled Review、Spell from Meaning、Read the Chinese meaning and spell the word、Type the English word、Submit。
- 卡片规则说明（中）：「复习状态跟随你的账号，换班后继续保留；历史练习记录与快照不会被改写。这里只展示真实计数，不预测记忆留存率。」

### 6.7 标题 i18n 缺陷修复复验（2026-11-22 二次）

- **原缺陷**：英文态复习轮标题直出后端固定中文串「复习队列」（`self.tsx:429` 直出 `plan.title`，后端 `build_review_fsrs_session` 标题写死）。
- **修复**：新增纯函数 `practiceRoundTitle(kind, title)`（`frontend/src/lib/vocab-review.ts`）：`review_fsrs` → 记忆复习 / Scheduled Review；`review` → 错词复习 / Wrong-word Review；任务与词库标题原样保留。`/self` 题面标题与 `/records` 轮次标题均改用它。
- **复验结果（浏览器实测，820 英文）**：
  - 复习会话 `3ec353dc-cdab-46d5-bf24-12998c2e4c37` 题面标题与 chip 均为 `Scheduled Review`，DOM 全文不含「复习队列」，`scrollWidth=innerWidth=820` 无横向溢出。证据 `57-review-fsrs-title-en-820.png`。
  - `/vocab/AY6S7T/records` 英文页：该 FSRS 轮次标题显示 `Scheduled Review`（窄卡片标题省略为 `Scheduled R...`，完整串在 DOM 内）；其余轮次分别为 Self practice / Teacher task。证据 `58-records-titles-en-820.png`。
  - 纯函数单测 `node --test tests/vocab-review.test.ts` **5 passed**：`review_fsrs→Scheduled Review`、`review→Wrong-word Review`、`task/self` 标题兜底均断言通过。
- **受限说明**：学生 A 名下当前无 `kind=review`（错词专项）历史轮次，`Wrong-word Review` 标签未在真实数据上渲染过，仅由单测覆盖；若后续开出错词复习轮，records 页需再目检一次。

### 6.8 其余受限项

| 项 | 状态 | 说明 |
|---|---|---|
| 复习轮选择题选项数随池收缩 | 如实记录，非缺陷 | 本轮到期池仅 3 词，Q1 选择题为 3 个选项（非四选一满配）；按复习池口径出题 |
| Q2 / Q3 未作答 | 未测 | 仅要求作答至少一题；`again/good` 评分切换、错词回收入队、跨班状态延续未测 |
| 造数链路 | 受限 | 到期状态为直接写 `review_state`；真实「首答 → 建档」链路未走通，作答后 `record_first_answer` 触发的重排已在 apple 一词上验证 |

## 7. 未覆盖项补齐（2026-11-22，第三批前低成本收口）

> 范围：仅收口第一批 / 第二批遗留的低成本覆盖项；**未做 PK / 农场实现，未改业务源码**。演示数据仅 E2E517 隔离；未 commit、未 push、未发 issue 评论、未部署。演示语料 AI 起草待审核，本报告结论仅为工程实测，不代表教师已验收。

### 7.1 填空 / 词根拼装输入框字号量化

- 轮次：自主练习轮 `be098bbe-39ea-411f-bd8a-32f5f00bdabb`（18 词主库；题单 roots 4 / en_zh 5 / zh_en 5 / cloze 4），学生 A 账号。
- 方法：CDP `Emulation.setDeviceMetricsOverride` 覆盖 390 / 820 / 1180 三档宽度，中 / 英两态；脚本读取拼写输入控件 `#self-vocab-answer` 的计算样式 `font-size`，同时记录 `innerWidth` 与 `documentElement.scrollWidth`。
- 口径：表单控件字号目标 ≥16px（防 iOS 聚焦放大）；cloze 与 roots 共用同一拼写输入控件（`AnswerForm` / 复用 `Input`，类名 `text-base`）。

| 宽度 | 语言 | cloze 输入 font-size | roots 输入 font-size | 横向溢出 | 截图 |
|---|---|---|---|---|---|
| 390 | 中文 | 16px | 16px | 无（scrollWidth = innerWidth = 390） | `59` / `60` |
| 390 | 英文 | 16px | 16px | 无 | — |
| 820 | 中文 | 16px | 16px | 无（820 = 820） | — |
| 820 | 英文 | 16px | 16px | 无 | `61` |
| 1180 | 中文 | 16px | 16px | 无（1180 = 1180） | — |
| 1180 | 英文 | 16px | 16px | 无 | `62` |

- 结论：12 格实测全部 **16px（≥16px 达标）**；三档宽度均无横向溢出。390 档输入控件高 40px、宽 308px（随容器伸缩）。
- 受限：390 英文 cloze 格处于错题反馈态，点「Try again」重开输入后测量；390 英文未单独截图（重点覆盖 390 中文、820 英文）。

### 7.2 导出结果 CSV 与结束任务

对象：任务 `9c90310b-9219-4796-a222-639252af7cc1`「E2E517 第一批四题型任务」，`practice` 模式，目标名单 1 人（学生 A）。

权限口径：教师端点门禁 `_require_classroom_teacher`；本次以同租户 school_admin 账号 `admin@example.com` 调用（与课堂教师走同一授权闸门），未使用教师 demo 账号口令。

**(a) 导出 CSV**

- practice 任务**无服务端 CSV 导出端点**；前端 `ResultsPanel.exportCsv` 的 practice 分支由 `/results` 载荷在浏览器端经 `downloadCsv` 生成（RFC 4180 转义、公式注入防护、UTF-8 BOM，规则与后端 `_csv_text_cell` 同口径）。
- 服务端测验导出端点 `GET /classes/{code}/vocabulary/assignments/{assignment_id}/results-export` 对本 practice 任务实测返回 **422 `该任务不是测验`**（门禁拦截，非故障）。
- 按前端口径用 `/results` 载荷重构 CSV，落盘为证据产物 `64-classroom-AY6S7T-vocabulary-practice.csv`，内容：

```
Name,Suffix,Status,Answered/Total,First-try correct,First-try accuracy,First-try correct per round
学生A,,In progress,4/18,4,100%,R1 4/4
```

- 归档前 `/results` 基线：学生 A 状态 `in_progress`，已答 4/18，首答正确 4，正确率 100%，1 轮；逐词首答正确：apple / banana / careless / teacher 各 1 次。

**(b) 结束任务（归档）**

- 请求：`POST /classes/AY6S7T/vocabulary/assignments/9c90310b-9219-4796-a222-639252af7cc1/archive`（教师闸门）。
- 响应：**200** `{"message":"词汇任务已结束"}`。
- 归档后核验：
  - `/results?assignment_id=…` 仍 **200**；任务状态 `archived`，`archived_at=2026-11-22T07:51:01.268635Z`；学生行统计不变（4/18，首答正确 4，R1 4/4）；四个已答词的首答正确记录不变。
  - 任务列表仅 1 期，状态 `archived`，`version_no=1`。
  - DB 核验：作答行仍 **4 条**、会话仍 **1 个**、快照 `snapshot_items` 仍 **18 条**；历史数据未删、发布快照未改写。
  - 重复归档：**422 `该任务已结束`**（幂等门禁）。
- 受限：未在浏览器点击「导出 / Export」「结束任务 / End task」按钮走完整下载与弹窗链路；CSV 为按前端口径从结果载荷重构。教师结果页浏览器截图沿用第一批 §4.3 既有证据。**该任务当前保持已结束状态，数据未删除。**

### 7.3 旧错词复习（kind=review）标签

- 造数（仅 E2E517 学生 A）：自主轮 `be098bbe-…` 第 5 题（cloze，helpful / 有帮助的）首答提交错误拼写 `zzxx-wrong`；回执 `is_correct=false, attempt_no=1, answered_count=2, correct_first_count=1`。`/wrong-words` 列表随即出现 helpful（`wrong_count=1`，`last_first_is_correct=false`，`practiceable=true`）。
- 开轮：`POST /classes/AY6S7T/vocabulary/student/sessions`，body `{"kind":"review","word_count":5}` → **200**；会话 `c7e40e9a-566b-426b-9acb-6d1fc3a64053`，`kind=review`，标题「错词复习」，`total_count=1`，`wrong_word_count=1`。
- 历史列表 `/history` 首行：`review` / 错词复习 / 已答 0 / 首答正确 0。
- 浏览器 records 页（英文态）：该行标题渲染 **`Wrong-word Review`**（非中文直出）；下方类型徽章为 `Wrong-word review`（`KIND_LABELS` 小写口径，与行标题属两套文案）；页面 DOM 无「错词复习 / 记忆复习 / 自主练习 / 教师任务」中文残留。证据 `63-records-wrong-word-review-en.png`。
- 闭环说明：6.7 节遗留的「学生 A 名下无 `kind=review` 历史轮次、`Wrong-word Review` 标签仅由单测覆盖」受限项，本轮已在真实数据上渲染验证。
- 受限：该 review 轮未作答（0/1）；徽章 `Wrong-word review` 与行标题 `Wrong-word Review` 的大小写差异本轮未改动。

### 7.4 新增截图 / 产物清单（59–64）

| 编号 | 文件 | 内容 |
|---|---|---|
| 59 | `59-self-cloze-zh-390.png` | 自主轮 cloze 题面，390 中文，输入 16px |
| 60 | `60-self-roots-zh-390.png` | 自主轮 roots 题面，390 中文，输入 16px |
| 61 | `61-self-roots-en-820.png` | 自主轮 roots 题面，820 英文，输入 16px |
| 62 | `62-self-roots-en-1180.png` | 自主轮 roots 题面，1180 英文，输入 16px |
| 63 | `63-records-wrong-word-review-en.png` | records 英文态：错词复习行标题 Wrong-word Review |
| 64 | `64-classroom-AY6S7T-vocabulary-practice.csv` | practice 任务结果 CSV（按前端口径重构） |

## 8. 未验证 / 受限项清单

| 项 | 状态 | 说明 |
|---|---|---|
| 自主练习填空 / roots 文本输入框字号 | **已覆盖** | 见 §7.1：三档 × 双语 12 格实测均 16px |
| 学生端直接访问他课堂 / 私有书 | 已验证拒绝 | 403/404；未做越权写操作尝试 |
| 导出 / 结束任务等次要动作 | **已覆盖** | 见 §7.2：CSV 重构 + 归档状态流转 / 快照完整性核验；浏览器按钮下载链路未走 |
| 教师验收口径 | 不适用 | 演示语料待教师审核，本报告结论仅为工程实测 |

## 9. 证据截图清单（01–64）

| 编号 | 文件 | 内容 |
|---|---|---|
| 01 | `01-publish-prompt-types-zh.png` | 发布面板四题型勾选（中文） |
| 02 | `02-publish-group-zh.png` | 手动分组仅学生 A（1/2） |
| 03 | `03-student-b-no-task-zh.png` | 学生 B 无任务 |
| 04 | `04-a-en-zh-prompt-zh.png` | 英译中题面 |
| 05 | `05-a-en-zh-feedback-zh.png` | 英译中判分反馈 |
| 06 | `06-b-zh-en-prompt-zh.png` | 中译英题面 |
| 07 | `07-b-zh-en-feedback-zh.png` | 中译英判分反馈 |
| 08 | `08-c-cloze-prompt-zh.png` | 语境填空题面 |
| 09 | `09-c-cloze-feedback-zh.png` | 语境填空判分反馈 |
| 10 | `10-d-roots-prompt-zh.png` | 词根拼装题面 |
| 11 | `11-d-roots-feedback-zh.png` | 词根拼装判分反馈 |
| 12 | `12-teacher-results-stats-zh.png` | 教师结果题型统计表（中文） |
| 13 | `13-teacher-results-stats-rows-zh.png` | 题型统计行明细（中文） |
| 14 | `14-self-books-types-zh.png` | 自主练习题型组与可出词数徽标 |
| 15 | `15-self-en-zh-prompt-zh.png` | 自主英译中题面 |
| 16 | `16-self-en-zh-feedback-zh.png` | 自主英译中反馈 |
| 17 | `17-self-zh-en-prompt-zh.png` | 自主中译英题面 |
| 18 | `18-self-zh-en-feedback-zh.png` | 自主中译英反馈 |
| 19 | `19-self-cloze-prompt-zh.png` | 自主填空题面 |
| 20 | `20-self-cloze-feedback-zh.png` | 自主填空反馈 |
| 21 | `21-pets-roots-blocked-zh.png` | 公共书 roots 阻断 |
| 22 | `22-deficient-book-blocked-zh.png` | 2 词库三类阻断 + 中文告警 |
| 23 | `23-deficient-book-blocked-en.png` | 同场景英文告警与原因 |
| 24–26 | `24-books-zh-390.png` / `25-books-zh-820.png` / `26-books-zh-1180.png` | 词库页中文三档 |
| 27–29 | `27-books-en-390.png` / `28-books-en-820.png` / `29-books-en-1180.png` | 词库页英文三档 |
| 30–32 | `30-practice-en-390.png` / `31-practice-en-820.png` / `32-practice-en-1180.png` | 练习页英文三档 |
| 33–35 | `33-practice-zh-390.png` / `34-practice-zh-820.png` / `35-practice-zh-1180.png` | 练习页中文三档 |
| 36–38 | `36-teacher-results-zh-390.png` / `37-teacher-results-zh-820.png` / `38-teacher-results-zh-1180.png` | 教师结果页中文三档 |
| 39–41 | `39-teacher-results-en-390.png` / `40-teacher-results-en-820.png` / `41-teacher-results-en-1180.png` | 教师结果页英文三档 |
| 42 | `42-teacher-results-stats-en.png` | 英文逐词错词表 + 学生完成度 |
| 43 | `43-teacher-results-prompt-stats-en.png` | 英文四题型统计表 |
| 44 | `44-self-books-roots-badge-zh.png` | 修复后：18 词主库 roots「14 词可出」徽标，四类可勾选 |
| 45 | `45-self-roots-prompt-zh.png` | 修复后自主轮 roots 题面（preheat 词块） |
| 46 | `46-self-roots-feedback-zh.png` | roots 首答拼对反馈「拼对了！preheat」 |
| 47 | `47-self-roots-zh-390.png` | roots 反馈页 390px 中文窄屏（无横向溢出） |
| 48 | `48-review-card-zh-1180.png` | 今日复习卡片 1180 中文（到期 3 / 已复习 1 / 剩余 19 / 上限 20，三条队列） |
| 49 | `49-review-card-zh-390.png` | 今日复习卡片 390 中文窄屏 |
| 50 | `50-review-card-en-820.png` | 今日复习卡片 820 英文（Today's Review / Due today / Reviewed today / Left today / Daily limit） |
| 51 | `51-review-fsrs-prompt-zh.png` | 复习轮 Q1 apple 英译中题面（记忆复习 · 复习队列） |
| 52 | `52-review-fsrs-feedback-zh.png` | Q1 首答拼对反馈「拼对了！apple」 |
| 53 | `53-review-fsrs-reload-zh.png` | 刷新后续到 Q2/3，题单与已答进度稳定 |
| 54 | `54-review-fsrs-zh-390.png` | 复习题面 390 中文（看义拼词，输入 16px，提交 48px） |
| 55 | `55-review-fsrs-zh-1180.png` | 复习题面 1180 中文 |
| 56 | `56-review-fsrs-en-820.png` | 复习题面 820 英文（Spell from Meaning / Submit） |
| 57 | `57-review-fsrs-title-en-820.png` | 修复复验：复习轮 820 英文标题 Scheduled Review，无「复习队列」直出 |
| 58 | `58-records-titles-en-820.png` | 修复复验：records 页 FSRS 轮次标题 Scheduled Review（820 英文） |
| 59 | `59-self-cloze-zh-390.png` | §7.1：自主轮 cloze，390 中文，输入 16px |
| 60 | `60-self-roots-zh-390.png` | §7.1：自主轮 roots，390 中文，输入 16px |
| 61 | `61-self-roots-en-820.png` | §7.1：自主轮 roots，820 英文，输入 16px |
| 62 | `62-self-roots-en-1180.png` | §7.1：自主轮 roots，1180 英文，输入 16px |
| 63 | `63-records-wrong-word-review-en.png` | §7.3：records 英文态，错词复习行标题 Wrong-word Review |
| 64 | `64-classroom-AY6S7T-vocabulary-practice.csv` | §7.2：practice 任务结果 CSV（按前端口径重构，非截图） |
