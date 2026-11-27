# 按租户按天用量聚合（#517 B 部分）

平台运营侧的单校用量日报：按租户（学校）按本地自然日聚合 9 类指标，供运营列表与单校趋势查看。后端实现见 `backend/app/services/tenant_usage.py` 与 `backend/app/api/routes/admin_tenant_usage.py`。

## 1. 九项指标定义

| 字段 | 中文名 | 定义 | 来源表 | 时间字段 | 去重口径 |
|---|---|---|---|---|---|
| `active_teachers` | 活跃教师数 | 当天有教学操作的去重教师数：发布词汇任务、发布课堂练习、词条内容审核三类操作的操作人并集去重 | `vocabulary_assignment.created_by`、`classroom_exercise.created_by`、`vocabulary_content_review_audit.actor_id` | `published_at` / `published_at` / `created_at` | 操作人 ID 去重 |
| `active_students` | 活跃学生数 | 当天有词汇作答的去重学生数（作答经 `vocabulary_session` 反查 `student_id`） | `vocabulary_answer` JOIN `vocabulary_session` | `vocabulary_answer.answered_at` | `student_id` 去重 |
| `vocab_answers` | 词汇作答数 | 词汇作答条数，每行一次作答（含同题多次尝试） | `vocabulary_answer` | `answered_at` | 计数 |
| `published_tasks` | 发布任务数 | 当天发布的词汇任务数 | `vocabulary_assignment` | `published_at` | 计数 |
| `completed_students` | 完成任务人数 | 当天完成教师任务的去重学生数：`kind='task'` 且 `status='submitted'` 的会话 | `vocabulary_session` | `submitted_at` | `student_id` 去重 |
| `pk_matches` | PK 对局数 | 当天开始的 PK 对局数 | `vocab_pk_match` | `started_at` | 计数 |
| `farm_harvests` | 农场收获数（下限） | 最近一次收获落在当日的地块数（**下限口径**，见 §3） | `vocab_farm_plot` | `last_harvested_at` | 计数（地块） |
| `placement_tests` | placement 测试数 | 当天完成的 placement 粗分档测试数 | `vocab_placement_result` | `submitted_at` | 计数 |
| `exports` | 导出次数 | 当天创建的导出任务数（`export_audit.action='create'`；`start/success/fail/download/retry/expire/reject` 不计） | `export_audit` | `created_at` | 计数 |

汇总口径：区间总量 = 每日行求和；去重项（教师、学生、完成人数）在**单日内去重**，跨日不重复去重（同一教师/学生连续两天活跃，两天各计一次）。运营列表的 7/30 天汇总在**整窗内去重**（窗口内活跃教师/学生各计一次），其余为条数求和。

## 2. 日界与时区

- 日界按租户 `Tenant.timezone`（缺省 `Asia/Shanghai`）的自然日切分；非法时区回退 `Asia/Shanghai`。
- 范围查询把本地自然日转成 UTC 半开区间 `[start_utc, end_utc)` 裁剪明细；分组时用 PostgreSQL `timezone(租户时区, 时间列)` 再截本地日期。
- 返回的 `date` 字段是该租户**本地日期**（`YYYY-MM-DD`），不是 UTC 日期。
- 例：`Asia/Shanghai`（UTC+8）下，UTC 前一日 16:30 对应本地当日 00:30，计入本地当日。

## 3. 两个必须诚实披露的数据缺口

### 3.1 没有登录事件，活跃口径不含「仅登录」用户

当前系统**没有登录日志，也没有 `last_login_at` 字段**；本需求不新增登录埋点、不改 User 表。因此：

- 活跃教师 = 当天有教学操作（发布词汇任务 / 课堂练习 / 内容审核）的去重教师；
- 活跃学生 = 当天有词汇作答的去重学生；
- **仅登录、未产生上述操作的账号不计入活跃数。**

该限制在接口 `limitations` 中返回，前端展示需如实标注。

### 3.2 农场没有逐日收获事件，`farm_harvests` 是下限

`vocab_farm_plot` 只保存累计 `harvest_count` 与最近一次 `last_harvested_at`，**没有逐日收获事件表**，无法回算某一天的真实收获次数。`farm_harvests` 的定义是「最近一次收获落在当日的地块数」，是当日收获账号数的**下限**：

- 某账号当天多次收获，地块只算 1；
- 某账号最近一次收获不在当天、但当天有过收获（被后续收获覆盖时间），不会被记到当天。

不得把该字段解读为真实收获次数；也不为本指标新建收获事件表。

## 4. 隐私口径

- 接口只返回聚合数，**不返回任何学生 / 教师标识**（学生 id、姓名、学号、教师 id 均不进响应与 CSV）。
- CSV 同样只含日期与 9 项聚合数；表头：日期 / 活跃教师数 / 活跃学生数 / 词汇作答数 / 发布任务数 / 完成任务人数 / PK 对局数 / 农场收获数（下限）/ placement 测试数 / 导出次数。
- 跨租户隔离：平台运营通道查询，条件带 `tenant_id`；不读取他校明细。

## 5. 为什么不用 `admin_metrics_daily`

`admin_metrics_daily` 是大盘**全局**日快照（按 UTC 自然日、无 `tenant_id` 维度），口径是口语作答大盘，不能按学校拆分，也不含词汇任务 / PK / 农场 / placement / 导出等指标。本需求**不改、不硬塞租户列**到该表；当前阶段全部走明细表按需 SQL 聚合。

## 6. 索引清单（迁移 `c3d4e5f6a7b8`）

所有查询形态为 `tenant_id = :t AND 时间列 >= :start AND 时间列 < :end`，补 `(tenant_id, 时间列)` 复合索引；既有单列 `tenant_id` 索引保留不动：

| 表 | 索引 | 列 |
|---|---|---|
| `vocabulary_answer` | `ix_vocabulary_answer_tenant_answered_at` | `tenant_id, answered_at` |
| `vocabulary_assignment` | `ix_vocabulary_assignment_tenant_published_at` | `tenant_id, published_at` |
| `vocabulary_session` | `ix_vocabulary_session_tenant_submitted_at` | `tenant_id, submitted_at` |
| `vocab_pk_match` | `ix_vocab_pk_match_tenant_started_at` | `tenant_id, started_at` |
| `vocab_placement_result` | `ix_vocab_placement_result_tenant_submitted_at` | `tenant_id, submitted_at` |
| `export_audit` | `ix_export_audit_tenant_created_at` | `tenant_id, created_at` |
| `vocabulary_content_review_audit` | `ix_vocab_review_audit_tenant_created_at` | `tenant_id, created_at` |
| `classroom_exercise` | `ix_classroom_exercise_tenant_published_at` | `tenant_id, published_at` |
| `vocab_farm_plot` | `ix_vocab_farm_plot_tenant_last_harvested_at` | `tenant_id, last_harvested_at` |

索引同时声明在对应模型 `__table_args__`，避免模型 / 迁移漂移。downgrade 按名可逆删除。合并 head 为 `d6372fd6a828`；后续 `e5f6a7b8c9d0` 仅把 master 上既有 `vocab_placement_result` / `vocabulary_content_review_audit` 的 5 个索引名对齐模型自动名，不改列与数据。

## 7. 物化升级条件

当前为按需查询（明细表 + 复合索引）。出现以下任一信号再考虑按租户按日物化快照表（或回写 `admin_metrics_daily` 的租户维度扩展）：

- 单校明细行数进入百万级，区间聚合响应明显变慢（慢查询日志 / 运营端 P95 超标）；
- 运营列表需要跨校批量展示 7/30 天趋势，每次实时聚合扫描成本过高；
- 需要长期留存历史日快照（明细被清理 / 归档后仍要回看趋势）。

物化前先补事件源缺口：登录活跃需要登录日志（或 `last_login_at`），农场真实日收获次数需要逐日收获事件记录。
