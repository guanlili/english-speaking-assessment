# DB 证据 1：CSV 导入班级词库（只读查询，本地 app DB @5433）

- 执行时间：2026-11-24（本地隔离环境，未连生产）
- DB 容器：`本地 DB 容器`，库 `app`，用户 `postgres`
- 词库：`QA基线-CSV导入-20261124`，book_id = `[id]`
- 租户：`seedpilot-01`（id `[id]`），课堂 SD100X（id `[id]`）
- 源 CSV：`backend/scripts/demo/vocab-demo-words.csv`（18 数据行；其中 15 行带 morphology JSON，apple/banana/careless 三行 morphology 为空）

## 查询 1：词库元数据

```sql
SELECT b.title, b.scope, b.status, count(i.word_id) AS items
FROM vocabulary_book b
LEFT JOIN vocabulary_book_item i ON i.book_id=b.id
WHERE b.id='[id]'
GROUP BY b.id;
```

结果：

| title | scope | status | items |
|---|---|---|---|
| QA基线-CSV导入-20261124 | classroom | active | 18 |

## 查询 2：词条 morphology / 例句落库情况

```sql
SELECT w.headword, w.part_of_speech, w.morphology::text AS morph_raw,
       LEFT(COALESCE(w.example_en,'NULL'),30) AS example
FROM vocabulary_word w
JOIN vocabulary_book_item i ON i.word_id=w.id
WHERE i.book_id='[id]'
ORDER BY w.headword;
```

结果（18 行）：

| headword | POS | morph_raw | example_en |
|---|---|---|---|
| apple | n. | null | I ate an apple after lunch. |
| banana | n. | null | The banana is still green. |
| bookmark | n. | null | He put a bookmark in the page. |
| careless | adj. | null | His careless mistake cost the |
| disable | v. | null | You can disable the alarm in s |
| helpful | adj. | null | Your advice was very helpful. |
| kindness | n. | null | She showed great kindness to t |
| notebook | n. | null | Write it down in your notebook |
| popcorn | n. | null | We shared a bag of popcorn. |
| preheat | v. | null | Preheat the oven before baking |
| rainbow | n. | null | A rainbow appeared after the r |
| rethink | v. | null | Let us rethink the plan togeth |
| sunflower | n. | null | The sunflower turns toward the |
| sunlight | n. | null | Sunlight filled the classroom. |
| teacher | n. | null | Our teacher explained the rule |
| teapot | n. | null | The teapot is on the table. |
| unhappy | adj. | null | She looked unhappy about the r |
| writer | n. | null | The writer signed her new book |

## 查询 3：聚合口径（注意：morphology 列为 json，空值存为 JSON `null` 字面量，不是 SQL NULL）

```sql
SELECT count(*) FILTER (WHERE morphology::text <> 'null') AS morph_present,
       count(*) FILTER (WHERE morphology::text = 'null') AS morph_null_literal,
       count(*) FILTER (WHERE example_en IS NOT NULL) AS has_example,
       count(*) AS total
FROM vocabulary_word w
JOIN vocabulary_book_item i ON i.word_id=w.id
WHERE i.book_id='[id]';
```

结果：

| morph_present | morph_null_literal | has_example | total |
|---|---|---|---|
| 0 | 18 | 18 | 18 |

## 结论（基线事实）

- 18 行全部入库，`part_of_speech` / `meaning_zh` / `meaning_en` / `example_en` 均保留；
- **morphology 全部丢失**：源 CSV 中带词法拆解的 15 词（teacher/preheat/unhappy/rethink/helpful/kindness/bookmark/notebook/sunlight/rainbow/popcorn/teapot/sunflower/writer/disable）DB 中均为 JSON `null`；
- 例句（cloze 素材）18/18 保留；
- 代码旁证（非 UI 事实，供修复定位）：后端 `vocabulary_import.py` 预览解析了 morphology 列并放入 `VocabularyImportRow.word`；但前端 `CreateClassroomBook.tsx` / `AddWordsToBook.tsx` 预览→提交映射未带 `morphology` 字段，`VocabularyWordIn` schema 本身支持该字段。
