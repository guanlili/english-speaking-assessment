# 词汇模块增量优化计划——任务与多轮练习改造

> 2026-10-05。状态：**阶段 1+2 已实现（PR #73）**；阶段 3 为可选项未做。上游：`docs/vocabulary-module-design.md`。
> 目标：解决「新任务覆盖旧任务」与「再练一次不是独立记录」两个结构限制，服务当前学校课堂场景。

## 0. 代码现状核实（2026-10-05，基于 master `5e36752`）

| 事实 | 出处 |
|---|---|
| 发布时归档同课堂全部其他 published——同班同时至多一个进行中任务 | `app/services/vocabulary.py` `publish_assignment` 归档循环 |
| 一个学生对一个任务只有一份会话（部分唯一索引 `ix_vocab_session_assignment_student`） | `app/models.py` `VocabularySession` |
| 单题尝试 = `VocabularyAnswer` 唯一 `(session_id, item_index, attempt_no)`，attempt_no 递增，**不覆盖** | `app/models.py` `VocabularyAnswer` |
| 判分与教师统计默认看首答（attempt_no=1） | `app/services/vocabulary.py` `first_answers_by_session` |
| 任务内容经发布快照固化，题序固定 | `publish_assignment` / `build_word_snapshot` |
| `due_at` 仅发布时校验晚于当前；练习/统计均无逾期状态 | `publish_assignment` 及学生/教师面板 |
| quiz 模式入口 422 预留 | `publish_assignment` |

结论：与已知基础一致，无滞后项。以下规划在此基础上做增量。

## 1. 三者关系定义（本次改造的概念基础）

| 概念 | 载体 | 关键规则 |
|---|---|---|
| **任务**（Task） | `VocabularyAssignment` | 教师发布单位：快照+名单+规则（due_at 等）。**改造后同班可多个并存**，互不关闭。 |
| **轮次**（Round） | `VocabularySession`（改造后） | 学生对某任务的一次完整练习。默认每任务一轮；「重新练一轮」开新轮次。**任务成绩锁定首轮**（最早完成提交的轮次），后续轮次为复习，独立记录、不改写。 |
| **单题尝试**（Attempt） | `VocabularyAnswer` | 轮次内每题的每次提交（attempt_no 递增）。本题重试 = 同轮次内新 attempt 行，**不覆盖本轮首答**；跨轮次的提交互不影响。 |

判分与统计口径不变：首答（attempt_no=1）判分；教师统计看任务首轮的首答；错词本按词聚合不变。

## 2. 功能清单

### 已有（保留，不重复开发）
- 发布快照、固定名单、due_at 校验、全班发布
- 看义/听音拼词、首答判分、本题重试、错词本
- 教师结果面板、历史期数查看、CSV 导出
- 学生会话幂等、刷新续做、多端进入（同档案）
- quiz 模式 422 预留、五级词库/句型推荐（并行线）

### 需优化（本计划）
1. 任务可见性：归档任务从学生端消失 → 学生任务列表常驻（有会话或名单内 published 均可见）
2. 任务状态机：增加**逾期**时间维度，与进度维度分离
3. 教师结果面板：完成口径明确为**首轮**，并区分逾期完成

### 需新增（本计划）
1. 「重新练一轮」：同任务开新轮次（新 VocabularySession），成绩独立
2. 学生任务列表状态机（未开始/进行中/已完成 × 逾期标记）
3. 教师任务列表与按轮次的结果汇总（轮次数、最佳轮）

### 暂不做（明确排除）
- 词汇 quiz 限时模式（仍 422 预留）
- 多学校 / 课程组 / 自定义名单分组
- 跨任务错词聚合改造（现有错词本已按词聚合）
- 复习调度算法（间隔重复）、教师逐生补派名单外的学生
- 句型/收藏改造（PR B 刚上线，保持）

## 3. 分阶段范围与验收标准

### 阶段 1：多任务并存 + 状态机（结构改造，先行）

**范围**
- `publish_assignment` 移除归档循环；`archive_assignment` 保留（教师手动「结束任务」）
- `read_vocab_today` 改造：返回**任务列表**（每任务：状态、进度、due、轮次数），兼容返回当前聚焦任务的练习数据
- 学生词汇首页：任务列表卡片（状态徽标、逾期标记、点入练习带 assignment_id）
- 教师面板：任务列表（进行中/已结束分组）、结果面板按所选任务（已有期数选择器，改为不限归档）
- 逾期判定：`now > due_at` 且学生未完成 → 任务状态标记 `overdue`（进度维度仍独立：未开始/进行中/已完成）

**API 调整**
| 端点 | 变化 |
|---|---|
| `GET /classes/{code}/vocabulary/today` | 响应加 `assignments: [任务摘要+状态]`；原单任务字段保留为「聚焦任务」（默认=最早 due 的未完成任务）兼容旧客户端 |
| `GET /classes/{code}/vocabulary/assignments`（教师） | 响应每任务加进度统计（名单/完成/进行中/未开始/逾期） |

**验收标准**
1. 同班连续发布 2 个任务：两个任务都在师生两端可见，互不影响
2. 学生完成任一任务 → 教师面板该任务 completed=1；另一任务不受影响
3. `due_at` 过期 → 学生列表该任务显示逾期徽标；未完成的进度状态不变
4. 旧数据（改造前发布的单任务）→ 列表正常显示、可续做，成绩口径不变

### 阶段 2：多轮练习（依赖阶段 1 的 round_no 结构）

**范围**
- `VocabularySession` 加 `round_no`；唯一约束改为 `(assignment_id, student_id, round_no)`
- 「重新练一轮」API：复制任务快照开新轮次（round_no = max+1）；仅在**上一轮已完成**后可用
- 学生练习页：已完成任务的「再练一轮」入口 + 轮次切换；教师结果面板加轮次维度（首轮成绩锁定 + 最佳轮/轮次数）
- 判分与错词本：口径不变（首答=各轮 attempt_no=1；错词本仍按词聚合全部轮次）

**关键数据变更**
| 表 | 变更 |
|---|---|
| `vocabulary_session` | 加 `round_no int not null default 1`；唯一索引重建为 `(assignment_id, student_id, round_no)` |
| `vocabulary_assignment` / `vocabulary_answer` | 无结构变更 |

**API 调整**
| 端点 | 变化 |
|---|---|
| `POST /classes/{code}/vocabulary/sessions` | 请求加 `round: "continue" \| "new"`（默认 continue=续做未完成轮，无则新开） |
| `GET /classes/{code}/vocabulary/results` | 响应加 per-round 汇总（round_no、首答正确率、提交时间） |

**验收标准**
1. 首轮完成后「再练一轮」→ 新会话独立记录，首答重新判分；**任务成绩仍为首轮**
2. 本题重试（同轮）→ attempt_no 递增，首答统计不变（既有行为回归）
3. 轮次进行中重复点击开练/刷新 → 幂等续做，不产生重复轮次
4. 并发提交同题 → `uq_vocab_answer_slot` 兜底，无重复行
5. 多端进入同任务 → 同一档案同一轮次续做
6. 教师结果面板：任务完成判定不受后续轮次影响；可按轮次查看
7. 存量数据（改造前会话）→ round_no=1，行为不变

### 阶段 3（可选，视反馈）
- 收藏/句型在重练轮的沿用确认（当前实现天然沿用，无需改动，仅补 e2e）
- 学生「我的收藏」独立页（成长页已有块，按反馈决定）
- 教师发布时的句型预览

## 4. 涉及的主要文件

| 层 | 文件 | 变更 |
|---|---|---|
| 服务 | `app/services/vocabulary.py` | 移除归档循环；`get_or_create_session` 支持 round_no；任务列表状态机；教师统计首轮口径 |
| 模型 | `app/models.py` | `VocabularySession.round_no`；`VocabularySessionCreate`/响应模型扩展 |
| 路由 | `app/api/routes/vocab_levels.py` | today 列表化、sessions round 参数、results 轮次汇总 |
| 路由 | `app/api/routes/admin_content.py` | （无变更——任务端点已在 vocab_levels.py） |
| 前端 | `src/routes/vocab.$code.index.tsx` | 任务列表状态机 |
| 前端 | `src/routes/vocab.$code.practice.tsx` | 「再练一轮」入口、轮次提示 |
| 前端 | `src/routes/t.$code.vocab.tsx` | 任务列表、结果轮次维度 |
| 数据 | `app/alembic/versions/*` | round_no 列 + 唯一索引重建（阶段 2） |

## 5. 历史数据处理与回归风险

**历史数据（无损）**
- 存量 `vocabulary_session` 全部 `round_no=1`（default 填充），与旧唯一约束等价
- 存量任务保持各自 status；改造后「多任务并存」对旧任务无感（published 保持 published）
- 存量答案 attempt_no 不变，首答口径不变

**回归风险（需全量回归的假设点）**
1. 「唯一 published」假设散布在学生 today、教师面板、`current_published_assignment` —— 需逐一改为「聚焦任务选择策略」（默认最早 due 的未完成任务，无则最近发布）
2. 错词本聚合跨轮次——口径保持「全部轮次首答错词」，无回归
4. CSV 导出、期数选择器——需回归验证归档任务不因多任务并存丢失

## 6. 必须由产品方决定的问题（附推荐默认值）

| # | 问题 | 推荐默认值 |
|---|---|---|
| 1 | 同时进行的任务数量是否设上限 | 不设上限；列表按 due 升序、无 due 按发布倒序 |
| 2 | 「再练一轮」次数是否限制 | 不限（课堂场景练习性质）；教师可看轮次数 |
| 3 | 逾期后能否继续作答 | **已定案：截止后禁止新作答**（沿用口语模块口径，不加补交配置）；历史记录可回看，未完成轮标记 `due_passed` |
| 4 | 任务完成判定 | 首轮全部题首答完成即「已完成」；逾期以独立时间维度展示（列表 overdue 徽标），不改写进度状态 |
| 5 | 重练是否需要教师开启 | 默认学生自主可重练；如需控制后续加班级开关 |
| 6 | 学生是否可见每轮成绩对比 | 学生可在练习页回看自己各轮记录（只读）；轮次对比趋势报告留给后续批次 |

## 7. 边界覆盖承诺（阶段验收必须包含）

刷新续做、重复点击开练、并发提交（slot 唯一约束 + round 分配幂等）、多端进入、
旧数据迁移（round_no 回填）、发布新任务不影响旧任务与旧成绩、重试不刷高成绩
（统计锁定首轮首答）——每条对应阶段验收标准中的显式用例。
