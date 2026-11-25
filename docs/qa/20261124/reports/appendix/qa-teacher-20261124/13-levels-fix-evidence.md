# 13 · 五级词库 KET 转入复验证据（D2）

- 复验时间：2026-11-24；分支 `fix/qa-vocab-regression-20261124`（commit `4e2a6e4`）
- 账号：教师 `[本地测试账号]`；课堂 `SD100X`；独立 Playwright 无头上下文
- 基线对照：D2 复现时 from-levels 转入 **0 词**（平台租户五级词条被学校租户 RLS 过滤）；基线空书 `[id]` 保持 0 词未动。

## 结论：通过

| 检查项 | 预期 | 实测 | 判定 |
|---|---|---|---|
| `created_count` | 5 | **5**（`skipped_existing=0`，`remaining_count=0`，单轮完成） | 通过 |
| 落库词 | apple / book / teacher / helpful / sunflower | 5 词全部落库，`status=active` | 通过 |
| UI 词单 | 5 词可见 | 选择器显示「QA-FIX-KET-levels-20261124（5 词·班级）」；词单列出 5 词，均带 KET 徽章 | 通过 |
| 基线空书未被污染 | 仍 0 词 | `[id]` 仍 0 词 | 通过 |

## 转入结果

- 新书标题：`QA-FIX-KET-levels-20261124`
- book_id：`[id]`
- 接口：`POST /api/v1/vocabulary/words/from-levels`，level=`KET`，200
- 响应快照：`scratch/levels-payload.json`

## DB 核对（book `[id]`）

| headword | status | meaning_zh | level（API） |
|---|---|---|---|
| apple | active | 苹果 | KET |
| book | active | 书 | KET |
| helpful | active | 有帮助的 | KET |
| sunflower | active | 向日葵 | KET |
| teacher | active | 老师 | KET |

> 说明：转入的是平台目录已核对词条副本，`morphology` 为 null（目录词条本身不带 CSV 词法）；`level=KET`，`all_levels=["KET"]`。

## 截图

- `13-ket-import-fix.png`：转入后词库选择器「5 词·班级」、5 词词单、toast「已从五级词库转入 5 个已核对词条（跳过 0 个已有词）」

## 备注

- 基线空书 `[id]`（「QA基线-KET五级转入-20261124」）本轮未使用、未改动，仍为 0 词。
- RLS 修复：迁移版本 `e9a7c3f1d5b2`，新策略 `vocab_level_catalog_read`（平台目录只读放开）；学校租户上下文可读到平台 KET 词条。
