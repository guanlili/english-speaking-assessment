# 粗分档自适应测与班级掌握度证据（2026-11-24）

范围：本地开发环境真机走查，验证 #517 下一批两项功能：

1. 学生「粗分档自适应小测」placement：独立会话、approved 五级词四选一、自适应收敛、只给建议起点 + 推荐词库、可重测留历史、教师只读。
2. 教师「班级掌握度」：首答正确率分段（`<60%` / `60–85%` / `>85%`）+ FSRS `new/learning/review` + 到期未复习条目数，默认 30 天、按任务切换、逐词下钻、CSV 导出。

**未访问、未部署生产**；全部数据为本地开发库合成数据。截图不使用真实学生姓名或真实学校数据。

## 环境

- 代码：集成分支 `feat/vocab-placement-mastery-20261124`，worktree `.../agents/o_000VxxkxFsS/integration`；基线 master `8fe2a71`。
- 本地开发库：Docker Postgres `english-speaking-assessment-db-1` / DB `app`，已升级到 placement 迁移 `a1b2c3d4e5f6`。
- 后端：集成分支代码 `127.0.0.1:8006`，`POSTGRES_SERVER=localhost POSTGRES_PORT=5433`。
- 前端：集成分支 vite `127.0.0.1:5176`，`API_PROXY_TARGET=http://127.0.0.1:8006`。
- 浏览器：系统 Chrome（Playwright），全新上下文；未复用生产会话。
- 账号：本地种子校级管理员 `admin@example.com`（口令不记录），课堂 `AY6S7T`。

## 合成验收数据

均为本地开发库临时数据，仅用于走查，不代表真实学校记录，也不作为生产种子。

| 数据 | 用途 | 说明 |
| --- | --- | --- |
| 公共词库「粗分档演示词库 · Demo」 | placement 题源 / 推荐词库 | 40 词，KET/PET/CET4/ADVANCED 四档各 10 词，`approved`、`source=demo`；已写 40 条 `vocab_level_entry` 五级映射 |
| 学生档案「演示学生测」 | 学生端 + 教师端 | 绑定本地 admin 账号，课堂 `AY6S7T`；仅用于用同一账号走通学生与教师两侧 |
| 学生 B 任务首答 | mastery 逐词分段 | 复制任务会话并写入 18 条首答，构造低/高两段 |
| 学生 C 任务首答 | mastery 中段 | 仅对 `apple/banana/careless/teacher` 四词各写 1 条正确首答；加上 A、B 后为 `2/3 = 67%`，落中段 |
| placement 作答历史 | 重测留历史 | 学生端连续完成多次 12 题小测，结果均为 KET；历史逐条保留 |

> 同一任务上方「完成情况」卡片的 `100%` 只统计该任务正式完成名单里的学生 A（4/4）；下方「班级掌握度」按课堂内全部本轮首答聚合，含合成 B/C，得到 `54%`。两处口径不同，不是同一分母。

## 截图与导出

1. `01-placement-intro-1180-zh.png`
   - 桌面 1180：入口说明卡、口径提示（粗分档建议，不是定级/考试分数/认证，可重测）、开始按钮。
2. `02-placement-intro-390-zh.png`
   - 手机 390：说明卡与按钮完整，`scrollWidth == innerWidth == 390`。
3. `03-placement-question-390-zh.png`
   - 手机 390 作答态：第 1/12 题、PET 档位、单词与四个中文释义选项；触控按钮为整行。
4. `04-placement-question-1180-zh.png`
   - 桌面 1180 作答态；进度条与题号一致。
5. `05-placement-result-1180-zh.png`
   - 结果态：建议档位 `KET（基础）`、推荐词库「粗分档演示词库 · Demo」、作答 12/12、答对 3；明确提示不写等级档案、不影响任务难度；含「再测一次 / 历史记录」。
6. `06-placement-result-820-zh.png`
   - iPad 820 结果态；两列信息卡折为单列，按钮完整。
7. `07-placement-result-390-zh.png`
   - 手机 390 结果态（视口截图）；建议档位、推荐词库与重测/历史按钮完整；历史列表位于下方可滚动区，旧记录不被覆盖。
8. `08-teacher-mastery-1180-zh.png`
   - 教师「完成情况」tab 内的「班级掌握度」：教师任务口径、时间窗近 30 天、导出按钮、到期黄色提示（按人×词×能力条目计数）、五张分段卡、复习状态分布、逐词表（0% 正确显示为“偏弱”而不是 0 分/未答）。
9. `09-teacher-mastery-820-en.png`
   - iPad 820 英文：`Class mastery`、`Window: Last 30 days`、`Export mastery`、`Class first-try accuracy 54%`、`Below 60% 8 / 60–85% 4 / Above 85% 6`、FSRS `0 · 20 · 2`、`5 review entries are due` 全部英文。
10. `10-teacher-mastery-390-zh.png`
    - 手机 390 中文：分段卡两列、时间窗与导出可点；逐词表在卡片内横向滑动，页面本身无横向溢出（`scrollWidth == innerWidth == 390`）。
11. `11-teacher-placement-1180-zh.png`
    - 教师「测分结果」tab：只读、每生最近一次，展示「演示学生测 KET（基础）· 12 题 · 答对 2 · 时间」。
12. `mastery-export-20261124.csv`
    - 从页面「导出掌握度」实际下载的 CSV：10 列、17 个词行；无数据正确率写 `-`，不伪装成 0%。表头为：`单词,释义,首答正确,已答,首答正确率,分段,新词,学习中,待复习,到期未复习`。

## 真机断言

- 三档宽度 `390 / 820 / 1180` 下页面均无整页横向溢出（`documentElement.scrollWidth == innerWidth`）；390 的逐词表按设计在组件内部横滑。
- placement 第 1 题从 PET 起步；12 题后收敛返回 `recommended_band=KET`，结果页同时给出推荐词库与限制说明；历史保留每次结果，可重测。
- 教师端 placement 只读列表展示每生最近一次，学生端不出现教师操作。
- mastery 接口与页面一致：`answered_count=26`、`correct_first_count=14`、`accuracy_rate=54`、`low_count=8`、`mid_count=4`、`high_count=6`、`no_data_count=0`、`fsrs_new=0`、`fsrs_learning=20`、`fsrs_review=2`、`due_count=5`。
- 中段词为 `apple / banana / careless / teacher`，各 `2/3 = 67%`；证明 `60–85%` 含 60 与 85 边界内的 67%，不是把 50% 误判为中段。
- CSV 导出 10 列 17 行，与页面逐词表一致。

## 相关校验（代码侧）

- placement 分支：后端全量 `1093 passed / 2 skipped`（含边界修复回归）、placement 专项 20 例；前端 typecheck、107 components、182 unit；OpenAPI 210 paths / 297 schemas。
- mastery 分支：后端全量 `1090 passed / 2 skipped`、mastery 专项 17 例；前端 182 unit / 110 components；OpenAPI 207 paths / 292 schemas。
- 集成分支：后端全量 `verify.sh --openapi` **1110 passed / 2 skipped**（242.75s，退出码 0），覆盖率全局 93% / services 93% / scoring 93% / api 92% / core 92%；placement + mastery 定向 37 passed；前端 typecheck / biome（仅既有 schema 版本 info）/ 182 unit / 110 components 全过；OpenAPI 基线 211 paths / 299 schemas 零漂移，生成客户端含 `readVocabMastery`、`startPlacement`、`answerPlacement`、`placementHistory`。

## 边界与待确认口径

- **未部署生产、未跑 devledger、未合并 master**；本证据只覆盖本地集成分支。
- mastery 的 `all_tasks` 会展示本班全部教师任务快照并集，窗口内无首答的旧任务词仍列出并标 `no_data`；`round_no=1` 且 `attempt_no=1` 的首答才计入，`self/review/review_fsrs/placement` 不混入；`due_count` 是 `user×word×capability` 状态条目数，不是去重词数；分段在取整后的展示正确率上判定。以上均待老师确认。
- placement 推荐词库规则（最多建议档的可见 active 词库，兜底最多 approved 池词）、题池是否与自主练习共用、`ADVANCED` 对外用 `ACADEMIC` 展示是否合适，待老师/产品确认。
- 本地 `POSTGRES_SERVER=db` 只适用容器内；宿主机跑后端/测试必须覆盖为 `localhost:5433`。本地手工 grant 新表不能当作迁移内容，生产由 `prestart.sh` / `ensure_db_roles.py` 统一授权。
- 集成分支的 `frontend/src/client/*` 已由合并后的后端统一重生成；若后续再改契约，必须重跑 `openapi_diff.py --update` 与 `npm run generate-client -- --local`，禁止手改生成文件。
