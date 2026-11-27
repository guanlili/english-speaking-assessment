# 17 · Roots 预判 UI 复验（第二轮 · 读路径补丁 commit `496c346`）

- 复验时间：2026-11-24（Asia/Shanghai）；分支 `fix/qa-vocab-regression-20261124`（PR #543），本轮补丁 commit `496c346`「fix(vocab): 教师读词库补回 morphology，roots 预判恢复」
- 浏览器：**独立 Playwright 无头上下文**（chromium headless shell 1148），未占用共享 Chrome / 5175；教师 `[本地测试账号]`
- 入口：`http://本地服务`，后端 `http://本地服务`，DB 5433 库 `app`

## 结论：通过（UI 链路 roots 复选框恢复可用，真实发布 5 词 roots 任务）

| 子项 | 预期 | 实测 | 判定 |
|---|---|---|---|
| 读路径 morphology 透传 | 18 词书 `GET /vocabulary/books/{id}` 返回 morphology，可拆词非 null | 18 词中 **15** 个 morphology 非 null；teacher / helpful / sunflower / bookmark / notebook **均非 null** | **通过** |
| 18 词书选 5 可拆词，roots 复选框启用 | 选中 ≥4 可拆词后「词根拼装」可勾选 | 选中 5/18（teacher / helpful / sunflower / bookmark / notebook），roots 复选框 **enabled 且可勾选**，提示恢复默认文案 | **通过** |
| UI 真实发布含 roots 任务 | 发布成功，快照含 roots 题，无全库副产物 | 标题 `QA-FIX-roots-v4-20261124`；快照 **5 词**，roots **3/5**；请求体仅显式 `word_ids`，未带 `book_id` | **通过** |

## 一、补丁与后端现状

- 补丁内容：`backend/app/services/vocab_levels.py` `attach_word_levels()` 构造 `VocabularyWordPublic` 时补传 `morphology=word.morphology`（单行）；同 commit 加回归测试 `test_book_words_expose_morphology_to_teacher_panel`（`backend/tests/api/routes/test_vocabulary_prompt_types.py:189`）。
- 容器装载说明：后端容器 `english-speaking-assessment-backend-1` 无源码 bind mount，compose develop watch 同步主检出 `./backend`（主检出仍在 master `50b1f2f`，未含补丁）；本轮补丁文件经 `docker cp` 拷入容器 `/app/backend/app/services/vocab_levels.py` 并触发 reload。容器内文件 md5 `8bb54e994f4ba40f649ab60429934188`，与 worktree 补丁文件一致；**容器重建或主检出文件事件触发 watch 回写后补丁可能丢失，需重新核对**。
- 复核（本轮复验前重新请求）：`GET /vocabulary/books/18f5d700-…` 18 词 morphology 非 null **15/18**；抽查 5 词全部非 null。响应落盘：`scratch/readbook-after-patch.json`。

## 二、UI 操作实录（5176，真实点击）

- 目标书：`[id]`（`QA-FIX-CSV-morph-20261124`，18 词）。
- 勾选 5 词：teacher / helpful / sunflower / bookmark / notebook（已选 5/18）。
- 出题方式：看义拼词（meaning）+ 词根拼装（roots）；roots 复选框为**启用态**并勾选；无「所选词没有可用的词法拆解」禁用提示。
- 任务名称：`QA-FIX-roots-v4-20261124`；模式「练习（可重试）」；派发范围全班。
- 点击「发布（5 词）」→ toast「词汇任务已发布，快照已固化。」；任务列表首条出现「第 4 期 · 5 词 · 0/20」。
- 截图：
  - `17-v4-roots-ready.png`：发布前 5/18 选中，roots 复选框启用勾选态，标题已填。
  - `17-v4-published.png`：发布后任务卡片 `QA-FIX-roots-v4-20261124 第4期·5词`，toast 快照固化。

## 三、发布结果（DB 核对）

- assignment_id：**`[id]`**
- version_no `4`；status `published`；mode `practice`；prompt_types `["meaning", "roots"]`；快照词数 **5**；目标学生 **20**；学生会话 **0**（学生尚未作答）。
- 快照明细（`snapshot_items`）：

| headword | 题型 | roots 选项块 |
|---|---|---|
| teacher | roots | re / er / teach / tion（4 块） |
| helpful | meaning | — |
| sunflower | roots | sun / flower / tion / re（4 块） |
| bookmark | meaning | — |
| notebook | roots | book / tion / note / re（4 块） |

- roots 题数：**3 / 5**（teacher、sunflower、notebook）；其余 2 词回落看义。
- 无全库副产物：快照仅 5 词（非整本 18 词），证明发布 body 只带显式 `word_ids`、未带 `book_id`（`book_id` 非空时后端 `resolve_publish_words` 会按整本解析并忽略 `word_ids`）。发布响应落盘：`scratch/v4-assignment-payload.json`。

## 四、与第一轮对照

- 第一轮（commit `4e2a6e4`，补丁前）：同一 18 词书选同样 5 词，roots 复选框仍 disabled（证据 `14-roots-still-disabled.png`，详见 14 号证据 3b）。
- 第二轮（commit `496c346`，补丁后）：roots 启用并真实发布，快照 roots 3/5。**D3 教师端 UI 预判链路本轮复验通过。**

## 五、遗留说明

- writer 一词的非法拆解（write+er=`writeer`≠writer）仍随 DB 入库（D1 残留，P2），本轮未在发布口径拦截；见 12 号证据。
- v4 学生端会话/roots 题面本轮未复测；快照 roots 3/5 已由 DB 核对。
