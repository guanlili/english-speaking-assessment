# DB 证据 2：五级词库 KET 转入（只读，本地 app DB @5433）

## 操作记录（UI）

- 入口：`/t/SD100X/vocab` → 「New classroom book」→ 「Import from leveled source」选 `KET (reviewed only)` → 「Create & import」
- 接口：`POST /api/v1/vocabulary/words/from-levels`（HTTP 200，duration ~40ms）
- 新建词库：`QA基线-KET五级转入-20261124`，book_id = `[id]`，scope=classroom，status=active
- UI 下拉显示：`QA基线-KET五级转入-20261124（0 words·class）`；词单为空

## DB 查询

```sql
-- 新书词条数
SELECT count(*) FROM vocabulary_book_item
WHERE book_id='[id]';
-- 结果：0

-- 五级分级词条（平台租户 [id]）
SELECT headword, level, status, needs_review, meaning_zh, tenant_id
FROM vocab_level_entry WHERE level='KET';
-- 5 行：apple / book / teacher / helpful / sunflower，均 active、needs_review=false、有释义
```

## RLS 复现（应用角色 应用角色，非超级用户）

策略 `vocab_level_entry.tenant_isolation`：
`COALESCE(current_setting('app.tenant_id', true), '') = tenant_id::text`

```sql
-- 学校租户上下文
SET app.tenant_id='[id]';  -- seedpilot-01
SELECT count(*) FROM vocab_level_entry;  -- 0

-- 平台租户上下文
SET app.tenant_id='[id]';
SELECT count(*) FROM vocab_level_entry;  -- 5
```

后端只读复现（容器内脚本，未 commit）：`_entry_headword_map(session,'KET')` → `entries: []`；`_effective_headwords(...)` → `effective: []`；目标书已有词 → `[]`。

## 结论（基线事实）

- 书可以创建（端点 200），但**转入 0 词**：5 个 KET 词条在学校租户会话下被 RLS 隐藏，候选为空；
- 平台种子分级词条（tenant_id=00000000…）对学校租户不可见，教师侧「从五级词库转入」拿不到任何候选；
- 注：`vocabulary_word` 中 `book` 词头在本租户不存在（其余 4 个已由 CSV 书带入），排除「同租户去重导致跳过」的解释；
- 缺陷候选：五级词库平台数据未走平台通道/未做跨租户只读放开，学校教师 from-levels 入口空转。
