# 本地演示词表与 mock 种子数据（demo-only）

本目录只存放一套**本地演示词汇数据**，供后续 A/B/C mock 取证使用；**不接入后端模型/API、不生成迁移、不写生产库、不用于生产**。

> 声明：本目录全部数据均为本地 mock。释义与例句原创撰写，未复制任何受版权保护的词典释义或例句；不含政治、隐私内容。后续清理脚本按固定 demo 命名空间整体删除，禁止把本目录数据导入生产库。

## 文件

| 文件 | 说明 |
| --- | --- |
| `words.json` | 220 条演示词条（UTF-8，无 BOM），五级各 44 |
| `validate_words.py` | 纯标准库本地校验脚本，可重复运行 |
| `seed_demo.py` | 幂等种子脚本：先清理旧 demo 命名空间，再写入一套可演示的 mock 数据 |
| `cleanup_demo.py` | 一键清理脚本：只删除固定 demo 命名空间内的对象，删除前做外部引用护栏 |
| `README.md` | 本说明 |

## words.json 数据结构

顶层：

```json
{
  "demo": true,
  "license_owner": "Demo Content Team",
  "license_ref": "DEMO-ONLY",
  "note": "Local demo data only; not for production",
  "words": [ ... ]
}
```

每条词条字段：

| 字段 | 说明 |
| --- | --- |
| `headword` | 唯一、真实英文单词（单个词，非短语） |
| `level` | 五级之一：`KET` / `PET` / `ACADEMIC` / `CET4` / `IELTS_TOEFL` |
| `part_of_speech` | 词性缩写（`n.` / `v.` / `adj.` / `adv.`） |
| `meaning_zh` | 简洁中文释义 |
| `meaning_en` | 简短英文释义 |
| `example_en` | 原创例句，必须包含 `headword` 原形（供 cloze 挖空） |
| `morphology` | 词法拆解数组：`[{text, gloss, kind}]`，`kind ∈ prefix / root / suffix` |
| `source_type` | 固定 `"demo"` |
| `review_status` | 固定 `"approved"` |

## 分级与规模

| 级别 | 词条数 |
| --- | --- |
| KET | 44 |
| PET | 44 |
| ACADEMIC | 44 |
| CET4 | 44 |
| IELTS_TOEFL | 44 |
| **合计** | **220** |

其中 99 个词条含两段及以上真实词法拆解（校验门禁要求 ≥ 80）。

## 词法拆解约定（roots 题依赖）

- `morphology` 各段按顺序拼接，**必须严格等于 `headword`**（大小写敏感、不做音变还原）；
- 常见派生词按前缀 / 词根 / 后缀真实拆分，简单词用单个 `root` 段；
- 出现音变（如 `happy → happiness / happily`、`drive → driver`）时，词根段按拼写实际形式书写，保证拼接一致。

## 词表本地校验

在仓库根目录运行（纯本地，无第三方依赖）：

```bash
python3 backend/scripts/demo_vocab/validate_words.py
```

校验项：顶层 `demo / license_owner / license_ref / note` 标记齐全；总数 220、五级各 44；`headword` 唯一且为单个英文单词；例句含 `headword` 原形（大小写不敏感，按词边界匹配）；`morphology` 拼接等于 `headword`、`kind` 合法；每条 `source_type == "demo"`、`review_status == "approved"`；两段及以上拆解词条数 ≥ 80。退出码 `0` 通过，`1` 存在错误。

---

## 种子与一键清理（本地 mock）

### 运行前提

- 仅连接**本地开发库**（`localhost:5433`，库名 `app`）。脚本启动时解析实际 SQLAlchemy URL 做守卫：`ENVIRONMENT=production`、远程 host、非 `app` 库名直接退出非 0；**没有任何 `--allow-remote` 绕过开关**。
- 在 `backend/` 目录下运行，使用后端 venv 解释器。

### 命令

```bash
# 写入一套演示数据（默认先清理旧 demo 命名空间，幂等可重跑）
POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \
    .venv/bin/python scripts/demo_vocab/seed_demo.py

# 只清理 demo 命名空间，不动其他数据
POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \
    .venv/bin/python scripts/demo_vocab/cleanup_demo.py
```

### 环境变量

| 变量 | 说明 |
| --- | --- |
| `VOCAB_DEMO_PASSWORD` | 演示账号口令。未设置时使用固定本地演示口令 `Demo2026!`，**仅本地 mock，绝不用于生产**；回报与日志中不写明文口令。 |
| `DEMO_ANCHOR_DATE` | 任务发布时间锚点日期（`YYYY-MM-DD`），默认 `2026-11-25`。 |
| `POSTGRES_SERVER` / `POSTGRES_PORT` | 本地库连接覆盖，默认 `localhost` / `5433`。 |

### 固定 demo 命名空间

所有种子对象都落在以下固定标识内，清理脚本只按这些标识删除：

| 维度 | 固定标识 |
| --- | --- |
| 租户 slug | `vocabdemo` |
| 账号邮箱 | `vocabdemo.admin@example.com`（school_admin）、`vocabdemo.teacher@example.com`、`vocabdemo.s01..@example.com`（`@example.com`） |
| 课堂码 | `VOCDEMO1`（12 名学生）、`VOCDEMO2`（6 名学生，跨班 404 隔离演示） |
| 词库 / 任务标题 | 前缀 `[DEMO]` |
| 词条授权 | `license_owner = Demo Content Team`、`license_ref = DEMO-ONLY`、`source_type = demo` |

### 种子数据构成

- **五级演示词库**：KET / PET / ACADEMIC / CET4 / IELTS_TOEFL 各 44 词，共 220，全部来自 `words.json`；`source_type=demo`、`review_status=approved`。
  - KET 词库走三个真实版本快照：v1 36 词 → v2 40 词（修订首条释义与例句 + 补 4 词）→ v3 44 词（最终版）；版本行由治理服务 `capture_version` 采集，含确定性 `content_hash`。
- **授权演示词库**：
  - `[DEMO] 授权教材词库`：`source_type=textbook`，有效期未来，20 词，2 个版本；
  - `[DEMO] 过期授权词库`：`source_type=licensed`，有效期已过，10 词；
  - 3 条真实授权审计行（教材库续期备注、教材词条引用号变更、过期库授权落账），`changes` 带 `from / to` 前后值，可查可追溯。
- **课堂与师生**：教师 `vocabdemo.teacher@example.com`（role=teacher，绑定两间课堂）；VOCDEMO1 12 名学生、VOCDEMO2 6 名学生，显示名为“演示学生01…”假名。
- **演示校级管理员**：`vocabdemo.admin@example.com`（username `vocabdemo.admin`，role=`school_admin`，`tenant_id` 归属 `vocabdemo` 租户，显示名“演示管理员”），供 `/admin/vocabbooks` 词库授权 / 版本管理取证；口令来源与教师/学生相同（`VOCAB_DEMO_PASSWORD`，未设置走 README 本地 fallback）。幂等：重复 seed 不重复建；cleanup 按 demo 租户命名空间一并清掉。
- **任务与作答**：VOCDEMO1 5 个教师任务，发布时间覆盖最近 5 个自然周（锚点 `2026-11-25`），题型覆盖 `meaning / cloze / roots`；12 名学生形成“完成 / 部分完成 / 未开始”三种状态，首答正确率 low / mid / high 分段；每任务有首轮 session 与 `attempt_no=1` 答案，部分错题带 `attempt_no=2` 重试（重试证据不进首答统计）。
- **FSRS**：8 名学生 × 3 词共 24 条 `VocabularyReviewState`，选词跨 KET / CET4 / IELTS_TOEFL 三个任务词库，`due_at` 分布在过去（到期未复习）/ 本周 / 未来，保证近期周期趋势报告的 `due_unreviewed` 可回算出非零值。
- **D/E 备用**：2 场已结束 PK（含大厅、对局、玩家、作答，不改任务统计）；5 个农场地块与 4 枚农场徽章。

### 管理员账号与端点角色口径

端点角色门禁以 `backend/app/api/deps.py` 为准（B3 身份拆分后无全局超管）：

| 门禁 | 放行角色 | 覆盖的词库端点 |
| --- | --- | --- |
| `TeacherUserDep` | `teacher` / `school_admin` | 词库列表与 CRUD、词条授权台账、版本历史、授权审计、`GET /vocabulary/license/alerts` 提醒 |
| `SchoolAdminDep` | 仅 `school_admin` | 校级授权清单 CSV：`GET /vocabulary/license/export.csv` |
| `PlatformOperatorDep` | 平台运营（独立 `PlatformOperator` 身份 / operator token） | 跨校授权清单 CSV：`GET /admin/vocabulary/license/export.csv`；**校级账号不可访问**，本种子不造运营账号 |

- 模块授权闸门 `require_module("vocabulary")`：种子已为 `vocabdemo` 租户写入 `TenantModule(module_key="vocabulary", enabled=True)`，管理员账号自动满足模块条件，无需额外授权行。
- 前端可访问页面：`school_admin` 可进入 `/admin/vocabbooks`（词库管理、授权面板、版本历史、提醒面板、内容审核、校级 CSV 导出）、`/admin/units`、`/admin/sentenceframes`，以及教师三页；页面内写授权 / 回滚按钮按 `school_admin` 身份放开。

### 管理员登录与访问实测（本地 `app` 库，TestClient 直连本地后端）

以 `school=vocabdemo` 调用 `POST /api/v1/login/access-token`（表单 `username=vocabdemo.admin@example.com`，口令由 `VOCAB_DEMO_PASSWORD` 提供）：

| 检查项 | 实测结果 |
| --- | --- |
| 登录 `POST /login/access-token?school=vocabdemo` | `200`；token `role=school_admin`，`tid` 为 vocabdemo 租户 UUID（与两间课堂同租户） |
| `GET /vocabulary/license/alerts` | `200`，返回 11 条临期 / 已过期提醒 |
| `GET /vocabulary/license/export.csv`（校级 CSV，SchoolAdminDep） | `200` |
| `GET /admin/vocabulary/license/export.csv`（平台运营专属） | `401`，按预期拒绝校级 token |

### 清理规则与护栏

- `seed_demo.py` 默认先调用 `cleanup_demo.py` 的清理逻辑再写入，保证幂等；重复重跑不会产生重复对象。
- 清理**只删上述命名空间**内的对象；**不按 `source_type=demo` 泛删**，避免误删其他人的演示数据。
- 删除前先做外部引用护栏：若已有非 demo 数据引用将删对象（其他词库收录 demo 词条、其他任务名单挂 demo 学生、非 demo 账号复习状态引用 demo 词条等），停止并报错，不做级联误删。
- 删除按外键安全顺序执行：PK 作答/玩家/对局/大厅 → 作答/会话/任务名单/任务 → 复习状态/徽章/地块 → 词条条目/审计/版本/词条/词库 → 学生/教师成员/课堂/租户模块/账号/租户。

### 租户上下文与归属一致性

RLS 下所有写入必须落在 `vocabdemo` 租户，脚本与应用主引擎同口径处理：

- 种子最外层用 `tenant_scope(tenant_id)` 包住全部写入；引擎装上租户绑定事件，每次事务开始自动 `set_config('app.tenant_id', ...)`，与 `app.core.db` 主引擎一致。
- 每个模型构造时**显式带 `tenant_id`**（Student / VocabularySession / VocabularyAnswer / VocabularyReviewState / VocabularyAssignment / VocabularyBook / VocabularyBookItem / VocabularyWord / 版本快照 / 授权审计 / PK 四表 / 农场地块 / 徽章 / 账号 / 课堂 / 教师成员），不依赖 ORM 默认租户兜底，避免漏写时落到默认租户 `00000000-...0001`。
- 清理脚本在同一 `tenant_scope` 上下文内执行；父表按 `tenant_id` 显式收敛，子表按父级 FK（课堂 / 大厅）归属命名空间，兼容旧版种子误落默认租户的残留行；不会因 RLS 看不见而漏删，也不跨命名空间误删。
- 版本快照 / 授权审计行由治理服务 `capture_version` / `apply_license_update` 落库，`tenant_id` 继承自目标词库 / 词条。

### 趋势报告复核实测（`build_trend_report`，VOCDEMO1，近 5 周）

以 `tenant_scope(vocabdemo)` 打开 `Session` 调用 `build_trend_report(classroom=VOCDEMO1, granularity='week', periods=5, anchor=None, book_id=None, prompt_type=None)`，实测：

| 周期 | assigned_targets | completion_rate | first_answered | due_unreviewed |
| --- | --- | --- | --- | --- |
| 2026-10-26 ~ 11-01 | 12 | 75 | 80 | 0 |
| 2026-11-02 ~ 11-08 | 12 | 75 | 80 | 0 |
| 2026-11-09 ~ 11-15 | 12 | 75 | 72 | 0 |
| 2026-11-16 ~ 11-22 | 12 | 42 | 56 | 1 |
| 2026-11-23 ~ 11-29 | 12 | 42 | 70 | 6 |
| **汇总** | **60** | **5 个周期非空** | **358** | **7** |

- 5 个教师任务 `source_book_ids` 均非空；按 `book_id` 筛选对应词库时，`assigned_targets=12`、`first_answered=80`，筛选有数据。
- 教师账号 `vocabdemo.teacher@example.com` 的 `tenant_id` 与两间课堂一致；VOCDEMO1 12 名学生、VOCDEMO2 6 名学生 `tenant_id` 全部等于 `vocabdemo`，无错配。

### 实测最终计数（种子后，本地 `app` 库）

| 对象 | 计数 |
| --- | --- |
| 五级演示词库 / 词条 | 5 个 / 220 词 |
| 授权演示词库 / 词条 | 2 个 / 30 词（教材 20、过期 10） |
| 词库版本快照 | 10 行（KET 3、教材 2、其余 5 库各 1） |
| 授权审计行 | 3 条 |
| 课堂 / 学生 | 2 间（VOCDEMO1 12、VOCDEMO2 6）/ 18 名学生 |
| 演示账号（school_admin / teacher / 可登录学生） | 1 / 1 / 12 |
| 教师任务 | 5 个 |
| 会话（submitted / in_progress） | 49（37 / 12） |
| 首答答案 / 重试答案 | 358 / 31 |
| FSRS 复习状态（overdue / 本周 / 未来） | 24（8 / 9 / 7） |
| PK（大厅 / 对局 / 玩家 / 作答） | 2 / 2 / 4 / 24 |
| 农场（地块 / 徽章） | 5 / 4 |

### 清理验证结果

跑 `cleanup_demo.py` 后，demo 命名空间计数全部为 0（含管理员 `vocabdemo.admin@example.com` 在内共 14 行 demo 账号：12 名可登录学生 + 教师 + 管理员）；既有非 demo 数据总量与种子前基线逐项一致，未被改动：

| 表 | 种子前基线 | 清理后 |
| --- | --- | --- |
| tenant | 16 | 16 |
| user | 157 | 157 |
| classroom | 21 | 21 |
| student | 129 | 129 |
| vocabulary_word | 94 | 94 |
| vocabulary_book | 8 | 8 |
| vocabulary_book_item | 94 | 94 |
| vocabulary_assignment | 5 | 5 |
| vocabulary_session | 18 | 18 |
| vocabulary_answer | 110 | 110 |
| vocabulary_book_version | 0 | 0 |
| vocabulary_license_audit | 0 | 0 |
| vocabulary_review_state | 26 | 26 |
| vocab_pk_lobby / match / player / answer | 4 / 4 / 8 / 48 | 4 / 4 / 8 / 48 |
| vocab_farm_plot / student_badge | 5 / 2 | 5 / 2 |

## 已知未覆盖项

- 不造音频文件，`audio_url` 为空，练习端走浏览器朗读兜底；
- `quiz` 限时测验不在演示范围，种子任务 `mode` 全部为 `practice`；
- 跨班 404 仅由 VOCDEMO2 名单隔离体现，不构造跨班访问用例；
- FSRS 调度参数为演示取值，不追求真实 FSRS 算法曲线；
- `vocabulary_assignment.source_book_ids` 脚本做了双路径兼容：列存在时 INSERT 写入来源词库 id 数组；列缺失时退化为不带该字段（本地库当前已落地该列，5 个任务均写入非空 `source_book_ids`）；
- 学生演示口令与教师共用 `VOCAB_DEMO_PASSWORD`（未单独设置），仅本地 mock；
- 平台运营（`PlatformOperator` 身份 / operator token）及其专属跨校端点（`/admin/vocabulary/license/export.csv` 等）不在演示范围，种子不造运营账号；
- VOCDEMO2 的 6 名学生只建 `Student` 名单行用于跨班 404 隔离演示，不建可登录 `User` 账号。
