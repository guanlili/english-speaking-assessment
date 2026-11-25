# 本地演示词表数据（demo-only）

本目录只存放一套**本地演示词表**，供后续 A/B/C mock 种子使用；**不接入后端模型/API、不写数据库、不用于生产**。后续会有单独的种子脚本把这些词条映射进 `vocabulary_book / word` 表。

## 文件

| 文件 | 说明 |
| --- | --- |
| `words.json` | 220 条演示词条（UTF-8，无 BOM） |
| `validate_words.py` | 纯标准库本地校验脚本，可重复运行 |
| `README.md` | 本说明 |

## 数据结构

`words.json` 顶层：

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

## 校验

在仓库根目录运行（纯本地，无第三方依赖）：

```bash
python3 backend/scripts/demo_vocab/validate_words.py
```

校验项：

- 顶层 `demo / license_owner / license_ref / note` 标记齐全；
- 总数 220，五级各 44；
- `headword` 唯一且为单个英文单词；
- 例句含 `headword` 原形（大小写不敏感，按词边界匹配）；
- `morphology` 拼接等于 `headword`，`kind` 合法；
- 每条 `source_type == "demo"`、`review_status == "approved"`；
- 两段及以上拆解词条数 ≥ 80。

退出码：`0` 全部通过；`1` 存在校验错误（明细打印到标准输出）。

## 版权与清理标记

- 释义与例句均为本演示数据原创撰写，未复制任何受版权保护的词典释义或例句；不含政治、隐私内容。
- 本目录所有条目均带显式 demo 标记：顶层 `demo: true`、`license_ref: "DEMO-ONLY"`，条目级 `source_type: "demo"`。后续清理脚本按这些标记整体删除，禁止把本目录数据导入生产库。
