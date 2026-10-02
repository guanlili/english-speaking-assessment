# 五级词库导入工具（本地运行，产出不入仓库）

把学校提供的原始词表资料（KET / PET / 学术 / 四级 / 雅思&托福）提取、规范化、
去重并生成数据质量报告。**工具与报告入仓库；原始教材文件与提取出的完整词表
一律不入仓库**（`output/` 已被 `.gitignore` 忽略）。

## 版权与授权约束（必读）

- 这些资料为出版物词表（剑桥 KET/PET 词表、新东方四级乱序版、3+1 雅思阅读词汇、
  托福真词汇、猴哥托福词组），**未确认线上使用授权前不得导入生产库**。
- 授权确认前，只允许：本地运行本工具生成统计报告 → 人工核对质量 → 报告审查。
- 授权确认后：通过管理端「五级词库」逐级上传导入（预览 → 确认，单事务），
  或用 `output/*.json` 走 `apply_import.py`（待授权后按需补充的脚本）。

## 用法

在 `backend/` 目录：

```bash
# 全量提取 + 生成质量报告（docs/five-level-vocab-quality-report.md）
uv run --with openpyxl --with xlrd python scripts/vocab_level_import/extract_vocab_sources.py \
    --source-dir "/Users/guanhongli/Downloads/2026Vocabulary(1)" --report
```

依赖：macOS 自带 `textutil`（.doc）、poppler 的 `pdftoppm`、`tesseract`
（需 `chi_sim` 语言包，仅 PET OCR 使用）。

## 五级定义（固定顺序，实际难度取最早、最易一级）

| 序 | 代码 | 名称 |
|---|---|---|
| 1 | `KET` | KET 词汇 |
| 2 | `PET` | PET 词汇 |
| 3 | `ACADEMIC` | 学术词汇 |
| 4 | `CET4` | 四级词汇 |
| 5 | `IELTS_TOEFL` | 雅思&托福词汇（雅思词表、托福真词汇、托福词组三个来源分别识别） |

## 清洗规则

- 规范化：NFKC + 首尾空白 + casefold（与平台拼写判分同口径）；
- 同级重复：同 (级别, 单词, 释义) 合并为一行，来源标签全部保留在 `sources`；
- 同形异义：同 (级别, 单词) 不同释义各占一行（入库后按 `sense_no` 区分）；
- 同义词/拼法变体不自动并入任何「可接受拼写」（判分红线，人工处理）；
- PET 扫描件 OCR：英文词头与词性直接采用，中文释义 OCR 不可靠一律留空，
  全部行 `needs_review=true`，人工核对后（管理端标记）才参与两模块的分级统计。

## 产出

- `output/<level>.json`：规范化词条（不入仓库）
- `output/cross-level-conflicts.json`：跨级重复完整清单（不入仓库）
- `docs/five-level-vocab-quality-report.md`：质量报告（统计 + 每来源 ≤5 行格式
  样例，入仓库可审查）
