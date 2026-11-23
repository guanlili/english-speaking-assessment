# 整校模块授权运维手册（speaking / vocabulary）

> 面向：平台超管 / 运维。依据代码：`backend/app/models/core.py`、`backend/app/services/entitlement.py`、`backend/app/api/deps.py`、`backend/app/api/routes/modules.py`、`backend/app/api/routes/admin_tenants.py`、`backend/scripts/backfill_tenant_modules.py`、`frontend/src/hooks/useModules.ts`、`frontend/src/routes/_layout/admin.schools.tsx`。
>
> 配套生产切换步骤见 [`production-switch-checklist-526.md`](production-switch-checklist-526.md)。

## 1. 概念与默认值

### 1.1 授权模型

- 授权粒度 = **整校 × module_key**，`tenant_module` 表每校每模块唯一一行（`uq_tenant_module_tenant_key`）。**无班级 override、无白名单、无按班灰度**。
- 可售模块只有两个 SKU：

  | module_key | 中文名 | 说明 |
  |---|---|---|
  | `speaking` | 口语 | 课堂、作答、录音导出、单元/句型库等口语链路 |
  | `vocabulary` | 单词 | 词库、五级选词、AI 备课、词汇作业、PK、农场、FSRS 复习 |

- **PK / 农场 / FSRS 是 `vocabulary` 的子能力，不单独开关**；词汇模块一关，这些入口与接口一并关闭。
- **缺行 = 未购买（默认关闭）**。`enabled=false` 与「没有授权行」对闸门效果一致，都按未购处理。

### 1.2 生效时间（effective_at）

- `effective_at` 为**空 = 立即生效**。
- `effective_at` 为**未来时间点 = 尚未生效**：即使 `enabled=true`，闸门仍按未购买处理（403），前端 badge 显示「待生效 / Scheduled」。
- 判定口径（`entitlement._row_active`）：行不存在 → 关；`enabled=false` → 关；`effective_at` 非空且晚于当前 UTC 时间 → 关；其余 → 开。

### 1.3 存量 / 新校口径

| 场景 | speaking | vocabulary | 来源 |
|---|---|---|---|
| 存量学校（迁移回填） | 开（on） | 关（off） | 迁移 `c7e2a9f4b1d8`，`ON CONFLICT DO NOTHING` 幂等重放安全 |
| 新建学校 | 关（无行） | 关（无行） | 建校端点不自动插行，缺行即双关 |
| 默认锚点校 `default`（本地 / 测试 / CI 种子） | 开 | 开 | `backend/app/core/db.py` 种子 upsert，**仅演示用途，不扩散到业务校** |

> 生产基线口径：所有业务校 `vocabulary=off`（含试点校），存量 `speaking=on`；新开通学校默认双关，按合同显式开模块。

## 2. 超管后台操作

### 2.1 入口

1. 以**平台运营**身份登录（独立运营账号，`typ=operator` + `aud=platform`，与学校用户身份分离）。
2. 进入 **学校管理** 页面，前端路由 `/admin/schools`（侧边栏「学校管理 / Schools」）。
3. 目标学校行点击 **模块 / Modules** 按钮，打开「模块授权 / Module access」对话框。

校级管理员、教师、学生**看不到也改不了**本接口；模块改写只走平台运营通道（`PlatformSessionDep` + `PlatformOperatorDep`）。

### 2.2 开关与生效时间怎么填

对话框内每个模块一张卡片（口语 speaking / 单词 vocabulary）：

- **勾选框**：勾选 = 开，不勾 = 关。
- **生效时间（选填，留空立即生效）**：`datetime-local` 输入框；留空提交后 `effective_at=null`（立即生效）；填写未来时间则到点生效。关闭模块时该输入框禁用（关闭即立即生效，不排期）。
- 每张卡片有独立 **保存 / Save** 按钮；两个模块互不绑定，可分别保存。
- 保存请求：`PUT /admin/tenants/{tenant_id}/modules/{module_key}`，body `{ "enabled": bool, "effective_at": ISO8601 或 null }`。

列表 badge 三种状态：**开（On）**、**关（Off）**、**待生效（Scheduled）**——勾选了开但生效时间在未来，显示待生效。

### 2.3 保存后多久生效

- **服务端：立即生效。** 模块闸门每个请求实时查 `tenant_module` 行，服务端无跨请求缓存；保存提交（`commit`）之后，新请求即按新口径裁决。
- **前端：存在本地缓存窗口。** 校端导航经 `useModules()` 调 `GET /api/v1/modules/me`，react-query `staleTime` 为 **5 分钟**。已打开的旧页面最长 5 分钟后刷新清单；**重新登录、刷新页面或重进路由**会立刻拿到新清单。
- 后台保存成功后只刷新运营后台的学校列表与本校审计历史，**不推送、不踢校端会话**；已登录的校端用户按上述缓存窗口收敛。

### 2.4 两个模块的导航表现

导航按 `/modules/me` 清单显隐；标注模块的入口仅在已购时出现，共享底座（无模块标注）始终保留。**前端隐藏只是减少无效直达，服务端闸门仍是最终裁决**——绕过导航直达旧链接仍会被 403 挡住。

| 组合 | 学生端 | 教师/管理员端 |
|---|---|---|
| 双开 | 全部入口（今日任务、单词学习、成长页、考试、主题探索、我的课堂、帮助） | 全部入口 |
| 只开 speaking | 单词学习入口隐藏；口语任务/成长/考试/探索可见；课堂底座（我的课堂、帮助、名册、通讯、在场）保留 | 词库管理隐藏；单元管理、句型库、录音导出可见；课堂底座保留 |
| 只开 vocabulary | 今日任务、成长页、考试、主题探索隐藏；单词学习可见；课堂底座保留 | 单元管理、句型库、录音导出隐藏；词库管理可见；课堂底座保留 |
| 双关 | 仅剩课堂底座与帮助类入口 | 仅剩共享底座管理入口 |

> 课堂底座路径（建校/名册/教师团队/加入/课堂通讯/帮助请求/提醒/在场/活动等）在 `require_speaking_classroom` 内放行进闸门，`vocabulary-only` 学校同样可用：账号、班级、名册是共享底座。

## 3. 回填脚本

脚本：`backend/scripts/backfill_tenant_modules.py`（在 backend 容器或本地 uv 环境执行）。连接走 `SQLALCHEMY_ADMIN_DATABASE_URI`（admin/owner 连接，迁移/种子/回填专用窗口）。

### 3.1 参数

| 参数 | 说明 |
|---|---|
| `--dry-run` | 只打印目标学校清单与变更计划，**不写库** |
| `--tenant-slug <slug>` | 目标学校码，可重复传入；不传 = 全部学校（仅用于默认回填口径） |
| `--enable <key>` | 开启指定模块（upsert `enabled=true`），`key ∈ speaking/vocabulary` |
| `--disable <key>` | 关闭指定模块（upsert `enabled=false`） |
| `--revert` | 删除目标校的全部模块授权行（回滚用） |
| `--allow-production` | 显式允许在 production 环境执行；**默认拒绝连生产库** |

互斥约束（脚本启动即校验）：`--revert` 不能与 `--enable/--disable` 同用；`--enable` 与 `--disable` 不能同用。slug 不存在时脚本退出并打印库内现有 slug 清单。

### 3.2 `--dry-run` 输出怎么读

输出头部一行：`目标学校 N 所；dry-run=True；revert=...`；随后表格逐校列出 `slug`、`status`、计划（如 `speaking=on, vocabulary=off` 或 `vocabulary=on`）。dry-run 下逐行只打印不落库，结尾标注 `dry-run：未写库。`

**生产执行前必须先跑 dry-run，逐校核对清单，并把输出留档（截图或日志文件）**；清单与合同口径不一致时不得执行写库命令。

### 3.3 常用命令（本地/演练环境先跑）

下列命令均在 `backend/` 目录下执行（脚本依赖 `app` 包导入）。

```bash
# 演练：只打清单与计划，不写库
python scripts/backfill_tenant_modules.py --dry-run

# 全量回填默认口径：speaking=on、vocabulary=off
python scripts/backfill_tenant_modules.py

# 给指定学校整校开启 vocabulary（--tenant-slug 可重复）
python scripts/backfill_tenant_modules.py --tenant-slug school-a --enable vocabulary

# 关闭某校 vocabulary
python scripts/backfill_tenant_modules.py --tenant-slug school-a --disable vocabulary

# 回滚：删除目标校模块授权行
python scripts/backfill_tenant_modules.py --tenant-slug school-a --revert
```

### 3.4 幂等与回滚语义

- **幂等**：目标状态与现行一致则不重复写；需要改时 upsert 该行，`effective_at` 置空（立即）、`updated_by` 置 `NULL`（脚本通道不留操作人）、`updated_at` 刷新。
- **`--revert`**：删除目标校在 `tenant_module` 中的全部授权行；删行后该校回到「缺行 = 未购」状态。注意 revert 不清理 `tenant_module_audit` 历史行（审计按设计留存）。
- **护栏**：`ENVIRONMENT=production` 时不带 `--allow-production` 直接退出，报错提示先在演练环境 dry-run 核对清单；确需对生产执行才显式加该旗标。
- **脚本回填不写业务审计**：`tenant_module_audit` 只记录平台运营后台改写；回填口径由迁移与脚本清单留痕。

## 4. 审计

### 4.1 后台历史列表

模块授权对话框底部「变更历史 / Change history」，按学校查、最新在前（`created_at desc, id desc`）。列字段：

| 列 | 字段（`tenant_module_audit`） | 说明 |
|---|---|---|
| 模块 | `module_key` | `speaking` / `vocabulary` |
| 变更 | `enabled_before → enabled_after` | 前后开关值；无前值显示「无记录 / none」 |
| 生效时间 | `effective_at_before → effective_at_after` | 前后生效时间；空显示「立即 / now」 |
| 操作人 | `actor_operator_id` | 平台运营 id；脚本回填或历史行可为空，显示 `–` |
| 时间 | `created_at` | 变更落库时间 |

`action` 取值 `grant`（开）/ `revoke`（关）。

### 4.2 审计写入时机

- **只在平台运营通过后台端点改写授权时落行**：`PUT /admin/tenants/{tenant_id}/modules/{module_key}` → `entitlement.upsert_module`，先写授权行再写一条审计，同一事务提交。
- **状态未变也留痕**：重复提交同一开关同样落一条审计（幂等 upsert 也记录）。
- 迁移回填、脚本 `backfill_tenant_modules.py`、`--revert` **均不写业务审计**。

### 4.3 只读 SQL 查询示例

> 需用 admin/owner 连接在只读窗口执行；生产查询走运维授权通道，不在业务受限角色连接里绕过 RLS。下列语句仅示例字段与关联口径。

```sql
-- 按学校 slug 查某校全部模块变更历史（最新在前）
SELECT  a.module_key,
        a.action,
        a.enabled_before,
        a.enabled_after,
        a.effective_at_before,
        a.effective_at_after,
        a.actor_operator_id,
        a.created_at
FROM    tenant_module_audit a
JOIN    tenant t ON t.id = a.tenant_id
WHERE   t.slug = '<school-slug>'
ORDER BY a.created_at DESC, a.id DESC;

-- 只看 vocabulary 模块
SELECT  a.*
FROM    tenant_module_audit a
JOIN    tenant t ON t.id = a.tenant_id
WHERE   t.slug = '<school-slug>'
  AND   a.module_key = 'vocabulary'
ORDER BY a.created_at DESC, a.id DESC;

-- 对照当前授权行（缺行即未购）
SELECT  m.module_key, m.enabled, m.effective_at, m.updated_by, m.updated_at
FROM    tenant_module m
JOIN    tenant t ON t.id = m.tenant_id
WHERE   t.slug = '<school-slug>'
ORDER BY m.module_key;
```

## 5. 403 排查

### 5.1 错误口径与优先级

- 模块闸门未购/未生效 → **403**，detail 稳定标识 `module_not_enabled:<key>`（如 `module_not_enabled:vocabulary`）。前端按标识映射双语，不按措辞匹配。
- **404 优先于 403**：
  - 课堂不存在 → 404 `Classroom not found`；学生未入班 → 404 `Student not found`；
  - 非本班教师 → 成员门 403（`没有权限：您不是该课堂的授权教师…`）；
  - **成员/身份确定之后**才判整校模块授权，未购再抛模块 403。
- 无课堂成员解析的校内端点（教师词库、AI 备课、五级选词等）走 `require_module(<key>)` 依赖工厂，直接判模块。

### 5.2 三步定位

1. **看模块清单**：校端用户带 token 调 `GET /api/v1/modules/me`，返回 `{ "modules": [...] }`；目标 key 不在清单里即为未购/未生效（缺行、关闭、未到生效时间三种之一）。
2. **核对 token 所属 tenant**：JWT 的 `tid` 须与用户行 `tenant_id` 一致；不一致 → 401（凭证失效），不是模块问题。注意 `/modules/me` 只服务学校用户，平台运营 token 调本端点会被 401 拒收。
3. **查 `tenant_module` 行**：按 `tenant_id + module_key` 看是否有行、`enabled`、`effective_at`；缺行=未购，`enabled=false`=关，`effective_at` 在未来=待生效。

### 5.3 平台运营端点豁免

- 平台运营路由用 `PlatformSessionDep`（平台通道会话）+ `PlatformOperatorDep`（运营身份门），**不走校端模块闸门**；运营没有「本校模块」概念。
- 学校业务端点不得使用平台会话依赖；跨校/平台口径操作必须走运营通道端点。

### 5.4 401 与 403 的区别（不要混用）

| | 触发条件 | 前端行为 |
|---|---|---|
| **401** | token 无效/过期、用户不存在、密码指纹不符、token 租户声明不符、运营 token 误用学校端点 | 自动登出并清缓存 |
| **403** | 已登录但权限不足：模块未购（`module_not_enabled:*`）、角色不符、非本班成员、用户/租户/运营停用 | **不登出**，留在当前会话 |

模块未购只返回 403，不触发登出；若用户被登出（401），先查凭证而非模块授权。

## 6. 新学校开通流程

1. **建校**：后台「开新学校」或 `POST /admin/tenants`，填学校码 slug（小写字母/数字/连字符）、中文名、英文名（选填）。建校成功即生成登录链接 `/s/{slug}/login`。
2. **默认双关**：新校不自动插模块行，speaking / vocabulary 均按未购处理。
3. **按合同开模块**：进入该校「模块授权」对话框，勾选对应模块；立即生效则生效时间留空，排期则填未来时间点；逐模块保存。也可用脚本按 slug 批量开启（见 §3），但脚本不留操作人审计。
4. **验证**：
   - 用该校教师/学生账号调 `GET /api/v1/modules/me`，清单与合同一致；
   - 登录前端核对导航：应出现的入口可见，未购模块入口隐藏；
   - 直达未购模块旧链接返回 403 `module_not_enabled:<key>`。
5. **留痕**：后台改写自动落审计行；核对「变更历史」前后值、生效时间、操作人、时间完整。

## 7. 变更 / 回滚注意

- **迁移只加表与回填，不改业务表结构**：迁移 `c7e2a9f4b1d8` 新建 `tenant_module`、`tenant_module_audit` 两张表及索引、RLS 策略，并回填存量 speaking=on / vocabulary=off；不改动任何作答、课堂、用户等业务表。
- **回滚模块授权只需改开关，不删表**：把模块开关改回 off，或用 `--revert` 删授权行即可；`tenant_module` / `tenant_module_audit` 表保留在库中对旧版本与未开通学校无害。
- **PK / 农场 / FSRS 不单独开关**：随 vocabulary 整体受控，不要尝试为子能力单独加授权行。
- **迁移 downgrade 边界**：若执行 Alembic downgrade，两张表连同回填数据一并摘除；审计行与授权行随表丢弃，**不影响任何业务作答数据**。正常运营回滚不建议 downgrade，走开关/revert 即可。
- **RLS 口径**：两张新表与既有业务表同口径（`FORCE ROW LEVEL SECURITY`，策略按 `app.tenant_id` 上下文隔离）；平台通道 BYPASSRLS 读写，学校侧只读本校行。生产 RLS 自检由部署流水线 `scripts/prod-rls-selfcheck.sh` 每次部署自动跑。
