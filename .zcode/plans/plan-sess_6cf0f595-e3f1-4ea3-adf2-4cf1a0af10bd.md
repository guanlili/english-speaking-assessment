# 多邻国式激励层 + 老师出题工作台 + AI 驱动定位

已确认的产品决策：**只和自己比**（学生端无班级排名）｜**关卡顺序解锁 + 老师可全开**｜**AI 生成问法 + 自动拆句**（篇目正文仍由学校提供，AI 不代写）。

## Phase 1：激励层基础（XP / 连胜 / 星级 / 徽章）

**后端**
- `Student` 加字段：`xp: int`、`streak_days: int`、`last_practice_date: date | None`
- `PracticeSession` 加 `stars: int | None`（0-3）
- 新表 `StudentBadge`（student_id / badge_key / awarded_at）；徽章定义为代码常量（first_round、streak_3、streak_7、ten_rounds、reached_b2）
- 幂等结算函数（在 `/today` 聚合时触发，复用 band_change 的模式）：本轮 5 题全部终态时——星级 = 平均总评 ≥85→3 星、≥70→2 星、完成即 1 星；XP = 每题 10 + 每星 5 + 连胜 ≥3 天奖励 10；连胜按「当日首次结算」推进（昨天练过 +1、断档重置 1）；结算时判定并写入新徽章
- `TodayPlan` 扩展 `gamification: {xp, streak_days, badges, session_stars}`（新徽章按 awarded_at=今天标出，结果页展示「本轮获得」）
- 教师面板 `BoardStudent` 加 xp/streak（老师可见全班，学生端不排名）
- 测试：结算幂等、星级分档、连胜连续/断档、徽章触发条件

**前端**
- 练习页头部 HUD：🔥 连胜天数 + ⭐ XP
- 结果页：星星逐个点亮（CSS 动画）+「+N XP」+ 新徽章横幅 + `canvas-confetti` 庆祝（3 星或获得新徽章时；新增该依赖，~6KB 无传递依赖）
- `/me` 我的进步：加徽章墙 + 连胜展示

## Phase 2：关卡地图（单元路径）

**后端**
- 新表 `Unit`（order_index / title / topic / is_active）；`Passage` 加 `unit_id`（nullable；迁移把现有 demo-pets 归入默认「Unit 1 · Pets」）；`Classroom` 加 `unlock_all: bool` 默认 false
- `GET /classes/{code}/path`：单元有序列表，每单元含该生最好星数、完成轮数、是否锁定；锁定规则 = 未开 unlock_all 且上一单元完成 0 轮
- 今日篇目逻辑改造：从「全局第一篇」改为「学生路径上第一个未完成单元的篇目」（无单元数据时回退现状，保持 `/practice` MVP 页与现有测试兼容）；全部完成 → 复练最后单元
- admin：Unit 的 CRUD + 篇目归属编辑（复用现有 passage PUT）
- 测试：路径顺序、解锁/全开、完成推进

**前端**
- `/map/:code` 纵向关卡列表（单元卡：标题/主题/星星/锁），点击进入练习；练习页头部加「关卡地图」入口

## Phase 3：AI 出题（老师侧工作台）

**后端**
- 抽公共 `ArkChatClient`（`app/scoring/ark_client.py`：chat/completions 封装 + JSON 容错解析公共化），`ArkRubricScorer` 改用之
- `POST /admin/scenarios/{id}/questions/generate`（count 1-10 / band / hint）→ **只起草不入库**，返回可编辑草稿；prompt 内置 PRD §6 三档难度描述（A2 二选一 15-20s / B1 情景偏好 30s / B2 连续追问 45s）；无密钥 503（同 TTS 口径）
- `POST /admin/passages/{id}/sentences/auto-split`：本地算法（句分割→按词数升序→取 3 句建复述句），幂等
- 补 `PUT /admin/scenarios/{id}`（改名/启停）
- 测试：生成解析与边界（MockTransport）、自动拆句幂等、503、Scenario PUT

**前端**
- admin 情景页：「AI 生成问法」→ 预览面板（每条可编辑文本/档位/秒数，采纳走已有 POST / 丢弃）
- admin 篇目页：「自动拆分复述句」按钮

**红线**：AI 只服务老师起草，学生端题库仍全部来自内容表（PRD「模型不当场出唯一题」）。

## Phase 4：AI 驱动定位包装与收尾

- README/界面文案标注五大 AI 能力（转写 / rubric 评分 / 词表 CEFR / TTS 标准音 / AI 出题）
- 教师面板头部加引擎状态徽章（演示模式 / 方舟）
- CLAUDE.md 更新；全量测试 + 浏览器验证；提交 PR

## 依赖与迁移

- 前端新增 `canvas-confetti`；后端零新依赖
- 一个 Alembic 迁移：student 3 字段、practice_session.stars、unit 表、passage.unit_id、classroom.unlock_all、student_badge 表 + 默认单元种子

## 执行顺序与验证

Phase 1→2→3→4 串行，每阶段：后端+迁移+测试全绿 → generate-client → 前端 → lint/build → 浏览器实测。关键回归点：`/today` 改造不破坏现有 141 个测试（无单元数据走回退路径）；档位降级依旧不向学生展示（星级与档位解耦，无负面反馈机制）。