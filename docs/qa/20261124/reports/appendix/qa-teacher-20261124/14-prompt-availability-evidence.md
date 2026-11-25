# 14 · 素材预判 UI 复验证据（D3）

- 复验时间：2026-11-24；分支 `fix/qa-vocab-regression-20261124`（commit `4e2a6e4`）
- 浏览器：独立 Playwright 无头上下文；教师 `[本地测试账号]`；学生取证账号 `s10003`（学生1-3）独立无头上下文
- 可用性口径（前端 `src/lib/vocab-prompt-availability.ts`，与后端 `services/vocabulary_prompt_types.py` 对齐）：roots 可用 = 拆解 ≥2 段且按序拼回原词（忽略大小写）；四选一 ≥4 词；cloze = 例句含原词。

## 结论：部分通过

| 子项 | 预期 | 实测 | 判定 |
|---|---|---|---|
| 3a 无 morphology 小书：roots 禁用 + 提示 | 禁用，提示「所选词没有可用的词法拆解，补词法后再选。」 | 2/2 选中，roots 复选框 **disabled**、未勾选，提示文案**完全一致** | **通过** |
| 3b 18 词 CSV 书：roots 可用（14 词可拆） | 选 ≥4 词后 roots 可勾选 | 选中 5 个 DB 内可拆词（teacher/helpful/sunflower/bookmark/notebook），roots **仍 disabled**，提示同上「没有可用的词法拆解」 | **失败（未修复到 UI 链路）** |
| 后端 roots 出题能力 | 含 roots 任务可生成 roots 题面 | 辅助 HTTP 发布 5 词任务，快照 3 道 roots（各 4 个词块选项）；学生会话 5 题中 **3 道 roots**，题面正常渲染 | **通过（后端侧）** |

## 3a · 无 morphology 小书（通过）

- 新书标题：`QA-FIX-nomorph-small-20261124`
- book_id：`[id]`（2 词：apple、banana，源 CSV 行无 morphology）
- 操作：UI 真实上传 `scratch/nomorph-small.csv` → 建库 → 词单勾选 2/2
- 实测：
  - roots（词根拼装）`disabled=true`，`checked=false`
  - 提示文案：**「所选词没有可用的词法拆解，补词法后再选。」**
- 截图：`14-nomorph-roots-disabled.png`

## 3b · 18 词 CSV 书 roots 预判（失败）

- 目标书：`[id]`（`QA-FIX-CSV-morph-20261124`，18 词；DB 内 14 词可拼回，见 12 号证据）
- 操作：UI 选中 teacher / helpful / sunflower / bookmark / notebook（5/18，均为 DB 内可拆词）
- 实测：roots 复选框 **disabled=true**，提示「所选词没有可用的词法拆解，补词法后再选。」
- 截图：`14-roots-still-disabled.png`

### 根因（后端读路径剥除 morphology，修复 commit 未覆盖）

- 教师端词单来自 `GET /api/v1/vocabulary/books/{book_id}`（AssignPanel `readBook`）。
- 实测该接口对 18 词返回的 `morphology` **全部为 null（0/18 非空）**，尽管 DB 中 15 行存有拆解。响应落盘：`scratch/readbook-response.json`。
- 代码定位：`backend/app/services/vocab_levels.py` `attach_word_levels()` 构造 `VocabularyWordPublic` 时逐字段赋值，**未传 `morphology=`**，字段回落默认 `None`：
  ```python
  VocabularyWordPublic(
      id=word.id, headword=word.headword, ...,
      audio_url=word.audio_url, status=word.status,
      level=..., all_levels=...,
      # 缺 morphology=word.morphology
  )
  ```
- 前端 `countEligibleByPromptType` 拿到的词法全为 null → roots 可出题数 = 0 → 复选框禁用。该缺口在 master 源码同样存在，不属于本次 4e2a6e4 改动范围（本 commit 后端仅含 RLS 只读迁移 + 测试；前端为映射透传与预判库）。
- 对照：导入预览接口、建库响应、发布快照、学生 today 接口均能读到 DB 中的 morphology；**仅词库详情读路径**剥除。

## 后端 roots 出题能力（辅助 HTTP 验证）

> 因 UI roots 复选框被上述读路径缺口禁用、无法真实点击发布；按复验规则，不可达环节用真实 token + HTTP 辅助，后端生成结果如下。

### 正式复验任务（5 词，纠正版）

- assignment_id：`[id]`（version_no 3，status `published`，mode `practice`）
- 标题：`QA-FIX-roots-20261124`
- prompt_types：`["meaning", "roots"]`；派发全班（20 名目标学生）
- 词单（显式 word_ids，5 词）：bookmark / helpful / notebook / sunflower / teacher
- 快照（DB `snapshot_items`）：

| headword | 题型 | 词法段 | roots 选项块 |
|---|---|---|---|
| bookmark | roots | book + mark | re / tion / mark / book（4 块，含 2 干扰块） |
| helpful | meaning | help + ful | — |
| notebook | roots | note + book | book / tion / note / re（4 块） |
| sunflower | meaning | sun + flower | — |
| teacher | roots | teach + er | re / er / teach / tion（4 块） |

- roots 题数：**3 / 5**（bookmark、notebook、teacher）；其余 2 词回落看义。

### 学生可答侧证据（s10003，独立无头上下文）

- 会话：`vocabulary_session` id `[id]`，assignment `69a51bbb…`，status `in_progress`，round 1（未提交任何作答）
- `GET /classes/SD100X/vocabulary/today?assignment_id=69a51bbb…`：5 题，**roots 3 题**（item 0 bookmark、item 2 notebook、item 4 teacher），meaning 2 题；roots 题均带 `morph_segments` 4 块。响应落盘：`scratch/student-today.json`
- 题面截图：`14-student-practice-first.png`（第 1 题 roots：bookmark，词块 re / tion / mark / book，输入框 + 提交）

## 遗留测试任务（待清理，详见 16 号汇总）

- `[id]`（version_no 2）：首次辅助发布时请求体同时带了 `book_id`，后端 `resolve_publish_words` 在 `book_id` 非空时按整本词库解析、忽略 `word_ids`，导致快照为全库 18 词（其中 9 道 roots）。该任务为调试副产物，建议归档/删除。

## 第二轮更新（commit `496c346`，2026-11-24）

- 上述 3b 根因已由补丁 `496c346` 修复：`attach_word_levels()` 补传 `morphology=word.morphology`，并加回归测试 `test_book_words_expose_morphology_to_teacher_panel`。
- 补丁后复验：readBook 15/18 morphology 非 null；18 词书选 teacher/helpful/sunflower/bookmark/notebook 5 词，roots 复选框**启用**并真实发布 v4 任务 `[id]`（快照 5 词，roots 3/5）。
- **D3 教师端 UI 预判链路最终判定：通过。** 完整实录见 `17-root-ui-retest.md`。
