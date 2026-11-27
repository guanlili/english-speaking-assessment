# #567 模块授权遗留验收 — e2e/守护断言切片（2026-11-27）

本切片对应 issue #567 正文六条遗留取证项。边界沿用 #516：不含计费/账单（#480 暂缓）；
不冒充教学验收；取证用匿名合成租户（后端 TestClient + 独立测试库 `app_test`），不碰生产
既有学校数据；不部署、不写 default 租户。

## 本轮自动化覆盖（后端合成租户 TestClient）

测试文件：`backend/tests/api/routes/test_module_entitlement_e2e.py`（6 项）。

复现：

```bash
cd backend
POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \
  uv run pytest tests/api/routes/test_module_entitlement_e2e.py -q
# 与既有授权回归一起：
uv run pytest tests/api/routes/test_module_entitlement.py \
  tests/api/routes/test_tenant_module_lifecycle.py \
  tests/api/routes/test_module_entitlement_e2e.py -q
```

### 1. 纯词汇租户端到端闭环 —— 已自动化 ✅

`test_vocabulary_only_tenant_closed_loop`：合成租户只开通 `vocabulary`（无 speaking 行），
链路 建校 → 建班 → 学生入班 → 校管建公共词库 → 发布任务 → 学生今日题单 → 开轮作答
（2 词全对）→ 教师报告 `completed_count=1` 全 200；`/modules/me` 下发 `["vocabulary"]`；
同租户口语 `today` 仍 403 `module_not_enabled:speaking`，不被词汇闭环误伤放行。

### 4. 仅词汇租户不读口语业务表（行数级守护断言）—— 已自动化 ✅

`test_vocabulary_only_does_not_touch_speaking_tables`：词汇闭环跑通后，学生 `revision`
与教师 `today` 两条口语链路均 403 `module_not_enabled:speaking`；随后行数级断言：
- `attempt`（口语作答）本租户 0 行；
- `practice_session`（口语练习会话）本租户 0 行。

闸门在进口语服务层之前抛出，未产生任何口语作答/会话记录。日志级断言未加（服务端无跨模块
审计日志可锚定），以行数级为准。

### 5. 仅口语租户：词汇端点逐条 403 —— 后端清单已自动化 ✅

`test_speaking_only_vocab_routes_blocked_per_checklist`：合成租户只开通 `speaking`，
教师侧 9 条 + 学生侧 6 条词汇端点逐条断言 403 `module_not_enabled:vocabulary`：

- 教师：词库列表、任务列表、班级结果、趋势、趋势 CSV、教师农场汇总、排行榜设置、
  排行榜、PK 大厅；
- 学生：错词本、学生词库、历史、复习队列、复习统计、学生农场。

前端导航隐藏与入口守卫的纯函数断言由既有测试覆盖：
`frontend/tests/navigation-modules.test.ts`（只买口语 → 单词入口隐藏）、
`frontend/tests/module-guard.test.ts`（未购模块守卫 denied）、
`frontend/tests/components/TeacherModuleGuard.test.tsx`。

### 3. 关闭 / 到期：链路 403、业务行留存 —— 已自动化 ✅

`test_disabled_blocks_vocab_but_retains_rows`（`enabled=false`）与
`test_expired_blocks_retains_rows_reopen_restores_visibility`（`expires_at` 过去）：

- 闭环作答完成后快照业务行数；关闭/到期后：学生复习队列、教师结果报告、趋势 CSV 均
  403（关闭 `module_not_enabled:vocabulary` / 到期 `module_expired:vocabulary`）；
- 任务、目标行、会话、作答、名册、课堂物理留存，前后行数一致；
- 运营重开（paid + 30 天）后报告 200，`completed_count=1` 不被重置，学生队列恢复 200。

**当前实现口径（取证事实，非待修功能）**：关闭/到期后词汇的读与写链路一并关门禁，
仓库内**未提供**「历史只读 + 关闭后 CSV 导出」模式；词汇趋势 CSV（`trend.csv`）同样
受闸门拦截。口语报告/音频导出（`exports.py`）是基线能力，不走学校模块闸门。
「到期后历史只读可见、可导出」是否作为产品能力开放，属商务/产品决策，不在 #516 与
本切片范围；若后续要做，需单独评审只读端点豁免口径。

### 6. 真实到期长链路 —— 自动化补齐 ✅

`test_expired_blocks_retains_rows_reopen_restores_visibility` 覆盖：到期 403
`module_expired:vocabulary` → 作答/名册留存 → 重开后旧报告与队列恢复、成绩不丢。
生产测试校到期探针（三词汇端点 403、`/modules/me` state=expired、days_left=0）见
`docs/qa/20261126/567-entitlement-probe/` Phase B；到期零宽限由状态机
`entitlement.py` 的 `expires_at <= now` 与既有单测固定。

## 未自动化 / 保留缺口（不伪造）

### 2. 全开租户改造前后等价截图与统计对照 —— 缺口，需 QA 双时点取证 ❌

- **现状**：仓库内未留存 #516 改造前（旧构建）的学生 4 页 / 教师面板 / 管理端截图基线；
  生产已运行改造后代码，无法在同一环境回退旧包做 before/after 快照。CI 内也不具备旧
  构建产物。
- **需要的环境与步骤**（QA 在可切换版本的环境执行）：
  1. 同一全开测试校，旧 release tag 构建下截 390 / 820 / 1180 三档：学生今日任务、我的成长、
     主题探索、词汇学习 4 页 + 教师面板 + 管理端模块面板，记录各页统计数字（完成率、人数、
     掌握度分段等）；
  2. 升级到当前构建后同账号、同数据重截同页同口径数字；
  3. 逐项对照页面结构与统计数字无回归差异；差异项单列。
- **旁证**：既有 mocked e2e `frontend/tests/e2e/module-entitlement.spec.ts`（双开 /
  单开 `/modules/me` 下发与审计）与本轮 41 项后端闸门/生命周期测试守住口径；前端双开页面
  回归由 `frontend/tests/e2e/` 各 mocked 规格覆盖。

### 5（部分）. 仅口语租户空卡片 / 空报表章节浏览器目检 —— 人工缺口 ❌

后端 15 条词汇端点逐条 403 已自动化（见上）；前端导航条目隐藏与守卫拦截有纯函数/组件测试。
「词汇面板直达后是否出现空卡片、空报表章节」的浏览器目检需在仅口语测试校走一遍：
词汇学习入口不可达（守卫弹回我的班级），无残留空章节；截图归档到本目录 `screenshots/`。

### 既有未覆盖分支（沿用上一轮结论，本轮未补）

- 平台运营 token 自身 403 分支：aud 正确但 typ≠operator、停用 operator 未探针；
- 到期边界瞬间（`expires_at` 恰好等于 now）未掐点实测；零宽限由代码比较式与单测固定；
- 生产未持平台运营 token，`PUT` 开关与审计历史未在生产重放（以本地 e2e + 单测 + 只读 SQL
  快照佐证，见 567-entitlement-probe 缺口清单）。

## 证据与代码索引

- 后端新测试：`backend/tests/api/routes/test_module_entitlement_e2e.py`
- 既有授权测试：`backend/tests/api/routes/test_module_entitlement.py`、
  `test_tenant_module_lifecycle.py`
- 闸门/状态机：`backend/app/services/entitlement.py`；课堂成员与教师身份闸：
  `backend/app/api/routes/class_shared.py`
- 前端过滤：`frontend/src/lib/module-filter.ts`、`frontend/src/hooks/useModules.ts`
- 上一轮生产探针：`docs/qa/20261126/567-entitlement-probe/`
