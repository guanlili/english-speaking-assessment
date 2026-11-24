# 学校模块授权生命周期（租期 / 试用状态机）

> 面向：平台运营 / 后端 / 前端对接。依据代码：`backend/app/models/core.py`、
> `backend/app/services/entitlement.py`、`backend/app/api/routes/modules.py`、
> `backend/app/api/routes/admin_tenants.py`、`backend/app/api/deps.py`。
> 基础授权模型（整校 × 模块、缺行=未购、底座豁免）见
> [`module-entitlement-ops.md`](module-entitlement-ops.md)，本文只补充 **租期、
> 试用、到期** 相关的状态机与边界。

## 1. 数据模型

`tenant_module` 每校每模块唯一一行（`uq_tenant_module_tenant_key`）。

| 字段 | 含义 | 约束 |
|---|---|---|
| `enabled` | 开关 | 非空 bool |
| `effective_at` | **开始时间**（同一事实，不另设 `starts_at` 列） | 可空；空=立即生效；未来时间=待生效 |
| `expires_at` | 到期时间 | 可空；空=长期；`now >= expires_at` 即到期 |
| `grant_type` | 授权类型 | `trial` / `paid` / `manual`，非空，默认 `manual` |
| `granted_by` | 本次授权 / 续期 / 改类型的操作人 | FK `platformoperator.id`，`ON DELETE SET NULL`，可空 |
| `updated_by` | 最后改动者 | 与 `granted_by` 语义不同：单纯关闭也会刷新 `updated_by` |

> API 响应里的 `starts_at` 是 `effective_at` 的**只读镜像**，二者是同一事实；
> 请求体只认 `effective_at`，不要传 `starts_at`。

## 2. 状态机

状态由 `entitlement.compute_state(row, now)` 纯函数计算，门禁、
`/modules/me`、运营列表筛选共用同一口径，不存在两套判断。

| 状态 | 判定条件 | 门禁结果 |
|---|---|---|
| `not_granted` | 授权行缺失（未开通） | 403 `module_not_enabled:<key>` |
| `disabled` | `enabled=false`（**优先级最高**：即使同时已过期也报 disabled） | 403 `module_not_enabled:<key>` |
| `scheduled` | `enabled=true` 且 `now < effective_at`（待生效） | 403 `module_not_enabled:<key>` |
| `expired` | `enabled=true`、已到开始时间，且 `expires_at` 非空且 `now >= expires_at` | 403 `module_expired:<key>` |
| `active` | 其余情形（含长期 `expires_at=null`） | 放行 |

### 2.1 判定顺序（固定，不可调换）

1. 非法 `module_key` → **500**（配置错误，不是业务拒绝）；
2. `not_granted` / `disabled` / `scheduled` → 403 `module_not_enabled:<key>`；
3. `expired` → 403 `module_expired:<key>`；
4. `active` → 放行。

### 2.2 关键优先级口径

- **`enabled=false` 优先于过期**：一行同时 `enabled=false` 且 `expires_at` 已过，
  状态判 `disabled`，detail 是 `module_not_enabled:<key>`，不是 `module_expired`。
- **到点即过期**：`now >= expires_at` 即 `expired`，代码内**不留宽限期**；
  是否给宽限属于商务策略，待确认后再在代码/配置中落地（见 §7）。
- **401 不用于模块口径**：401 只留给 token 无效/过期；模块未购、到期都返回 403，
  前端不触发登出。
- **404 先于 403**：课堂/成员不存在先抛 404；成员与身份确定之后才判模块闸门。

### 2.3 `days_left`

- 长期（`expires_at=null`）或缺行 → `null`；
- 已到期 → `0`（不返回负数）；
- 未到期 → 剩余 24 小时块**向上取整**的整天数（剩 1 天 2 小时记 2 天，
  剩 2 小时记 1 天）。口径实现见 `entitlement.compute_days_left`。

### 2.4 授权类型与状态的关系

`grant_type` 不单独决定状态，只在 `active` 时区分来源：

- `trial` 试用：**必须**带 `expires_at`（否则 422 `trial_requires_expires_at`），
  到期自然转 `expired`；
- `paid` 正式付费：可带 `expires_at`（合同到期日），也可 `null`（长期）；
- `manual` 手工开通：默认值，长期或按运营填写的到期日。

## 3. 运营 API

### 3.1 响应字段（`TenantModulePublic`）

`tenant_id`、`module_key`、`enabled`、`effective_at`、`starts_at`（镜像）、
`expires_at`、`grant_type`、`granted_by`、`state`、`days_left`、
`updated_at`、`updated_by`。

### 3.2 写入（`PUT /admin/tenants/{tenant_id}/modules/{module_key}`）

请求体 `TenantModuleUpdate`：`enabled`、`effective_at`、`expires_at`、`grant_type`。

- **PUT 整行语义，省略的元数据保留旧值**：服务端用 `model_fields_set` 区分
  「字段省略」与「显式传 null」；`expires_at` 显式传 `null` 才是清除到期日
  （转长期）。
- 校验（失败均 422）：
  - `grant_type` 不在 `trial|paid|manual` → `grant_type_invalid`；
  - `grant_type=trial` 未给 `expires_at` → `trial_requires_expires_at`；
  - `expires_at` 必须晚于开始时间：开始时间取 `effective_at`，为空则取 `now`
    → `expires_at_must_be_after_effective_at`；
  - 过去时间的 `expires_at` 允许写入，但状态直接判 `expired`。
- **`granted_by` 归属规则**：
  - 首次开通、从关闭变开启、续期（改到期日）或改类型 → 记当前操作人；
  - 单纯关闭、或未变更授权归属 → 保留旧值。
- **审计**：每次写入（含状态未变的幂等提交）落一条 `tenant_module_audit`，
  前后值覆盖 `enabled` / `effective_at` / `expires_at` / `grant_type` /
  `granted_by`，另记 `actor_operator_id` 与 `created_at`。

### 3.3 学校列表筛选

`GET /admin/tenants?expiring_within_days=<1..365>`：只返回存在满足以下条件
模块行的学校——`enabled=true`、`expires_at` 非空、`now <= expires_at <= now+N 天`。

- 已过期（`expires_at < now`）不计入本筛选；长期（`null`）不计入；
- 命中学校仍返回其**全部模块行**（含关闭、长期、已过期行），筛选只影响学校名单。

## 4. 学校侧状态（`GET /modules/me`）

- 响应保留原有 `modules: list[str]`（仅 `active` 键，与闸门同口径）；
- 新增 `statuses: list[...]`，对 `speaking` / `vocabulary` 两键都给一行：
  `module_key`、`state`、`enabled`、`effective_at`、`starts_at`、`expires_at`、
  `grant_type`、`days_left`、`granted_by`；
- **缺行也返回 `not_granted` 行，不 404**；
- 本端点只读，不新增任何学校侧写接口；`statuses` 仅供前端做到期提醒展示。

## 5. 到期 / 续期 / 重新开通的语义

| 场景 | 数据变化 | 状态与门禁 |
|---|---|---|
| 长期有效 | `expires_at=null` | 持续 `active`，`days_left=null` |
| 试用转正式（续期/改类型） | 运营改 `expires_at` 和/或 `grant_type=paid`；`granted_by` 记当前操作人 | 保持 `active`，历史作答与任务不重算、不迁移 |
| 到期 | 不改任何业务数据；到点后状态自动转 `expired` | 闸门 403 `module_expired:<key>`；`modules` 清单移除该键 |
| 到期后重新开通 | 运营再次开启 / 续期（可改开始时间、到期日、类型） | 恢复 `active`；之前留存的数据继续可查（边界见 §6） |
| 手工关闭 | `enabled=false` | `disabled`，优先级高于过期；`granted_by` 保留旧值 |

**到期只关门禁，绝不物理删除业务数据**：不删作答、任务、名册、消息、农场/复习
状态等任何业务表；`tenant_module` 与审计行同样留存。

## 6. 闸门覆盖边界（哪些路由受控、哪些不受控）

> 以下清单以代码内实际调用点为准；新增端点时必须显式选择是否挂闸门。

### 6.1 挂有模块闸门的端点

闸门三种挂载方式：路由级依赖 `require_module("<key>")`、课堂依赖
`require_speaking_classroom`、handler / 共享助手内联 `ensure_module_enabled`。

**speaking（口语）**

- 课堂链路：`require_speaking_classroom` 依赖挂在 `/classes/*` 课堂路由
  （`app/api/deps.py`、`app/api/routes/class_shared.py`）；课堂底座路径
  （建校/名册/教师团队/加入/通讯/帮助/在场等）在依赖内豁免放行。
- 作答链路（`app/api/routes/attempts.py`，内联闸门）：
  - `POST /attempts`（提交上传）
  - `POST /attempts/batch-read`（批量读，教师授权判定之后）
  - `GET /attempts/{attempt_id}/comparison`（前后对比）
  - `PUT /attempts/{attempt_id}/teacher-feedback`（教师反馈）
- 课堂管理助手：`class_shared` 中删除课堂、班级设置等 owner 操作在身份判定后
  附加 speaking 闸门。

**vocabulary（单词）**

- 路由级依赖 `require_module("vocabulary")`：
  - 教师词库导入 / 词库路由（`app/api/routes/vocabulary.py` 聚合的 import、books 子路由）
  - `GET /vocabulary/words`、`POST /vocabulary/words/from-levels`（`vocab_levels.py`）
  - `GET /vocabulary/reviews`、`POST /vocabulary/reviews`、
    `GET /vocabulary/reviews/audit`（`vocabulary_reviews.py`）
  - `POST /vocabulary/ai/word-drafts`、`POST /vocabulary/ai/word-drafts/import`（`vocab_ai.py`）
- 内联闸门（`app/api/routes/vocabulary_assignments.py`）：
  - 会话归属解析助手 `_get_owned_vocab_session` 覆盖的会话链路
  - `POST /vocabulary/sessions/{session_id}/submit`（提交）
  - `POST /vocabulary/sessions/{session_id}/tab-switch`（切屏上报）
- `app/api/routes/vocabulary_pk.py`：PK 大厅查看助手 `_viewer` 覆盖的 PK 端点。

### 6.2 不受模块闸门影响的路由（准确边界）

到期 / 关闭**不会**把下列内容「全部关掉」；未挂模块闸门的端点仍按既有的
登录、成员、角色口径放行：

- **作答轮询**：`GET /attempts/{attempt_id}`（`attempts.py` 的 `read_attempt`）
  不挂模块闸门，本人学生或授权教师可继续轮询既有作答状态；
- **课堂底座与历史协作数据**：名册、课堂列表、教师团队、课堂消息/通讯、
  句型收藏、帮助请求、跟进留言、成长进度底座等共享路由，其助手调用未传
  `module_key`，不做模块判定；
- **历史作答 / 任务数据物理留存**：到期后既有作答记录、分数、录音引用、
  词汇作业与会话记录、农场/复习状态均不删除；是否能在前端再次看到，取决于
  对应只读端点是否挂闸门（见上两条），未挂闸门的历史只读端点不受影响；
- **平台运营端点**：五级字典、运营统计、大盘、目录、更新日志等走平台通道，
  不走学校模块口径；
- **被闸门挡住的写操作**不会部分落库：闸门在 handler 解析成员/归属之后、
  业务写入之前抛出 403/403 对应标识。

> 边界维护原则：新增业务端点时，写操作与模块主链路读操作应挂闸门；纯历史
> 只读、导出、报表类端点是否受控需显式决策，不要默认「到期后全部不可见」。

## 7. 待商务确认的默认值（代码未硬编码）

以下产品口径当前**未在代码里写死默认值**，需商务 / 产品确认后再落地：

- **试用天数**：`trial` 开通时 `expires_at` 默认多少天（当前由运营逐单填写）；
- **到期宽限**：到期后是否给宽限期、多长（当前到点即 `expired`，无宽限）；
- **提醒时点**：学校管理员前端 30 / 7 / 1 天到期提醒的阈值与触达方式；
- **试用转正式的价格 / 配额**：属于业务规则，不在授权表结构内。

## 8. 迁移与回滚

- 新迁移 `b2c3d4e5f6a7`（父版本 `a1b2c3d4e5f6`）：加 `expires_at` /
  `grant_type` / `granted_by` 三列与 `expires_at` 索引；审计表加三组前后值列；
  存量行 `grant_type` 回填 `manual`。先加可空列 → 回填 → 再收紧 NOT NULL。
- downgrade 可逆：摘除新列、索引与外键；**不删除任何业务表或业务数据**。
- 回滚运营口径只需改开关 / 续期 / 重新开通，不需要 downgrade 迁移。
