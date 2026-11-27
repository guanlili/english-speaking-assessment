# 16 · 修复分支复验汇总（fix/qa-vocab-regression-20261124 / PR #543）

- 复验时间：2026-11-24（Asia/Shanghai）；两轮：第一轮基线 commit `4e2a6e4`，第二轮读路径补丁 commit `496c346`
- 环境：前端 `http://本地服务`（修复 worktree Vite）；后端 `http://本地服务`；DB 5433 库 `app`
- 浏览器：**独立 Playwright 无头上下文**（chromium headless shell 1148），未占用共享 Chrome/5175；教师 `[本地测试账号]`，学生取证 `s10003`
- 约束遵守：未改代码、未合并；worktree `git status` 干净；基线任务保持 published、未归档。

## 一、复验结论总览

| # | 复验项 | 判定 | 关键数字 |
|---|---|---|---|
| 1 | CSV morphology 端到端落库（D1） | **基本通过** | 预览 18 行；DB JSON 非空 **15** / null **3**；可拼回 **14**；非法拆解残留 **1**（writer） |
| 2 | 五级词库 KET 转入（D2） | **通过** | `created_count=5`；apple / book / helpful / sunflower / teacher；DB 与 UI 一致 |
| 3 | 素材预判 UI（D3） | **通过（第二轮补丁后 UI 复验通过）** | 3a 无词法小书 roots 禁用+提示 **通过**；3b 补丁前 18 词书 roots 禁用（读路径剥除 morphology），补丁 `496c346` 透传 morphology 后 roots **启用并真实发布 v4**，快照 roots **3/5**；后端 roots 出题 **通过** |
| 4 | 结果页真实下载 CSV（D4） | **通过** | `waitForEvent('download')` 捕获成功；CSV **3 行 × 7 列**，与面板一致 |
| 5 | 基线任务保留 | **通过** | v1 `cb387b7d…` 仍 `published`，2 名目标学生未变 |
| 6 | 教师子路由 speaking 守卫（第二轮） | **通过** | seedpilot-01（speaking+vocabulary）档案页正常，board/trail 200；seedpilot-02（speaking on / vocabulary off）子路由仍可访问，board/trail 200；zh/en × 390/1180 截图齐备 |

## 二、DB 关键数字

### 词库（租户 seedpilot-01 `d79018a2-…`）

| book_id | 标题 | 词数 | 说明 |
|---|---|---|---|
| `[id]` | QA-FIX-CSV-morph-20261124 | 18 | 本轮新建；morph JSON 非空 15 / null 3；可拼回 14，writer 非法拆解仍入库 |
| `[id]` | QA-FIX-KET-levels-20261124 | 5 | 本轮 KET 转入；apple/book/helpful/sunflower/teacher |
| `[id]` | QA-FIX-nomorph-small-20261124 | 2 | 本轮新建；apple/banana，无 morphology |
| `[id]` | QA基线-CSV导入-20261124 | 18 | 基线遗留，未改动 |
| `[id]` | QA基线-KET五级转入-20261124 | 0 | 基线遗留空书，未改动 |

### 任务（vocabulary_assignment）

| version | assignment_id | 标题 | 状态 | 题型 | 快照词数 | 说明 |
|---|---|---|---|---|---|---|
| 1 | `[id]` | QA基线-词汇任务-20261124 | published | meaning/en_zh/zh_en/cloze | 18 | 基线任务，**保留不归档**，2 名目标学生 |
| 2 | `[id]` | QA-FIX-roots-20261124 | published | meaning/roots | 18 | **调试副产物**：辅助发布误带 `book_id`，整本入快照；9 道 roots；20 目标；无学生会话 |
| 3 | `[id]` | QA-FIX-roots-20261124 | published | meaning/roots | 5 | **第一轮辅助 HTTP 复验任务**；3 道 roots（bookmark/notebook/teacher），2 道 meaning；20 目标；1 个 in_progress 会话 |
| 4 | `[id]` | QA-FIX-roots-v4-20261124 | published | meaning/roots | 5 | **第二轮 UI 正式复验 roots 任务**；3 道 roots（teacher/sunflower/notebook），2 道 meaning（helpful/bookmark）；20 目标；0 会话 |

- 第二轮 UI 正式复验 roots 任务 assignment_id：**`[id]`**（v4，保留作 roots 样例）
- 第一轮辅助会话：`[id]`（s10003，v3，in_progress，round 1，**0 作答**）；today 接口 5 题中 3 道 roots。

## 三、导出文件（D4）

- 绝对路径：`[本地路径]`
- 3 行（表头 + 2 学生）× 7 列；177 字节；含 UTF-8 BOM；学生1-1 18/18 · 100%，学生1-2 2/18 · 100%。

## 四、证据目录与文件

目录：`[本地路径]`

| 文件 | 内容 |
|---|---|
| `12-morphology-fix-evidence.md` | CSV 预览/入库 morphology 核对（D1） |
| `13-levels-fix-evidence.md` | KET 转入 5 词 DB + UI 核对（D2） |
| `14-prompt-availability-evidence.md` | roots 禁用/可用预判、根因、后端 roots 出题与会话证据（D3 第一轮） |
| `15-export-download-evidence.md` | CSV 真实下载落盘与读回核对（D4） |
| `17-root-ui-retest.md` | 第二轮读路径补丁后 roots UI 启用 + v4 真实发布证据（D3 第二轮） |
| `18-teacher-child-route.md` | 教师子路由 speaking 守卫两租户落点证据 |
| `16-fix-retest-summary.md` | 本汇总 |
| `12-csv-preview-fix.png` / `12-csv-book-created.png` | CSV 预览、建库后词单 |
| `13-ket-import-fix.png` | KET 转入后词单与 toast |
| `14-nomorph-roots-disabled.png` | 无词法小书 roots 禁用 + 提示 |
| `14-roots-still-disabled.png` | 18 词书选 5 可拆词，roots 仍禁用（补丁前对照） |
| `14-student-practice-first.png` | 学生端 roots 题面（bookmark，4 词块） |
| `15-export-clicked.png` | 结果面板与导出按钮 |
| `17-v4-roots-ready.png` / `17-v4-published.png` | v4 发布前 roots 启用勾选态、发布后卡片与固化 toast |
| `18-guard-zh-1180.png` / `18-guard-zh-390.png` / `18-guard-en-1180.png` / `18-guard-en-390.png` | seedpilot-01 档案页 zh/en × 390/1180 |
| `18-seed02-child-route.png` | seedpilot-02（vocabulary off）档案页落点 |
| `exports/课堂SD100X-词汇任务-2026-11-23.csv` | 导出 CSV 原件 |
| `scratch/` | Playwright 脚本、接口响应 JSON（含 `modules-me-seed001/002.json`、`readbook-after-patch.json`、`v4-assignment-payload.json`）、学生会话/today 快照、中间 CSV |

## 五、遗留缺陷（建议跟进）

1. **D3 读路径缺口（已修复，第二轮 UI 复验通过）**：补丁 `496c346` 在 `attach_word_levels()` 补传 `morphology=word.morphology` 并加回归测试 `test_book_words_expose_morphology_to_teacher_panel`；复验 readBook 15/18 非 null，roots 复选框启用并真实发布 v4（详见 17 号证据）。**部署注意**：本轮后端容器内补丁系手动 `docker cp` 装载（容器 watch 同步主检出，主检出仍在 master）；容器重建/主检出文件事件触发 watch 回写后补丁可能丢失，合入 master 并重建容器后需回归一次。
2. **D1 残留（P2）**：非法词法拆解（writer：write+er=`writeer`≠writer）入库时未被校验拦截/置空，原样落库；建议按 `morphologyAssembles` 口径在入库侧校验，不可拼回则置空并计入 invalid。
3. **本轮范围外未复测**：D5（EN 态日期占位仍中文）、D7（归档无二次确认）；D6（共享 Chrome 串号）本轮已由独立无头上下文规避，未复测共享平面。

## 六、测试产物清理建议

| 产物 | ID | 建议 |
|---|---|---|
| 调试副产物任务（18 词 roots，误带 book_id） | `[id]` | 归档或删除；无学生作答，不影响基线成绩 |
| 第一轮辅助 HTTP 复验 roots 任务（5 词） | `[id]` | 归档或删除；回归收尾后清理 |
| 学生 in_progress 会话 | `[id]`（s10003，0 作答） | 随 v3 任务一并清理 |
| **第二轮 UI 正式复验 roots 任务（5 词）** | `[id]`（v4） | **本轮保留**；回归收尾后与小书一并清理 |
| 测试词库 CSV-morph | `[id]` | 回归收尾后归档/删除 |
| 测试词库 KET-levels | `[id]` | 同上 |
| 测试词库 nomorph-small | `[id]` | 同上 |
| 基线两书一任务 | `4d49c3dc…`、`55319027…`、`cb387b7d…` | **保留不动** |

> 备注：v2/v3/v4 三个测试 roots 任务均为全班派发（20 名目标学生）；清理时如需只撤派不删库，可按任务归档处理。v4 为第二轮 UI 复验正式样例，按本轮口径只保留这一个 5 词任务。
