# 五级词库 · 资料清洗与数据质量报告

> 生成：`backend/scripts/vocab_level_import/extract_vocab_sources.py`（本地运行）。
> 版权约束：原始教材与提取出的完整词表均不入仓库、未经授权不导入生产库；本报告只含统计与格式样例。

## 五级定义（固定顺序，实际难度取最早一级）

| 序 | 级别代码 | 名称 |
|---|---|---|
| 1 | `KET` | KET 词汇 |
| 2 | `PET` | PET 词汇 |
| 3 | `ACADEMIC` | 学术词汇 |
| 4 | `CET4` | 四级词汇 |
| 5 | `IELTS_TOEFL` | 雅思&托福词汇 |

## 各级提取统计

| 级别 | 去重后词条 | 词组 | 待人工核对 | 来源文件 |
|---|---|---|---|---|
| KET 词汇 | 546 | 0 | 0 | 1.KET单词表14天-整理版 副本.xlsx（总表 623 词条口径，跨天重复词已合并） |
| PET 词汇 | 2672 | 0 | 2672 | 2. PET高频词汇表-新.pdf（42 页扫描件，OCR；xlsx 为空文件） |
| 学术词汇 | 568 | 0 | 0 | 3.基础学术词汇-整理版.xlsx + 3.academic_vocabulary_list.xlsx（同一份表的重复来源，已合并） |
| 四级词汇 | 2213 | 0 | 0 | 4.新东方四级词汇乱序版.doc（textutil 提取） |
| 雅思&托福词汇 | 1842 | 1193 | 0 | 5.雅思阅读词汇.xlsx + 5.托福真词汇_Chapter1-2.xlsx + 5.猴哥托福词组1200.xls（三来源分别识别） |

## 同级重复与来源保留

同 (级别, 单词, 释义) 的重复行已合并，来源标签保留在 `sources` 列表（如 KET 跨天重复：apartment 同时出现在 DAY9/DAY10 → sources 含两天标签）。同词同级不同释义 = 同形异义，各留一行（sense 区分）。

## 跨级冲突（实际难度取最早一级）

共 **1630** 个词出现在多个级别。前 30 个：

| 单词 | 出现级别 | 实际难度 |
|---|---|---|
| barbecue | KET、PET | **KET** |
| chips | KET、PET | **KET** |
| biscuit | KET、PET | **KET** |
| bottle | KET、PET | **KET** |
| chocolate | KET、PET | **KET** |
| coffee | KET、PET | **KET** |
| cook | KET、PET | **KET** |
| cooker | KET、PET | **KET** |
| cream | KET、PET | **KET** |
| dinner | KET、PET | **KET** |
| ice cream | KET、PET | **KET** |
| jam | KET、PET | **KET** |
| juice | KET、PET | **KET** |
| kitchen | KET、PET | **KET** |
| knife | KET、PET | **KET** |
| lemon | KET、PET、CET4 | **KET** |
| pizza | KET、PET | **KET** |
| plate | KET、KET、PET | **KET** |
| potato | KET、PET | **KET** |
| salad | KET、PET、CET4 | **KET** |
| salt | KET、PET | **KET** |
| bowl | KET、PET | **KET** |
| breakfast | KET、PET | **KET** |
| burger | KET、PET | **KET** |
| butter | KET、PET | **KET** |
| carrot | KET、PET、CET4 | **KET** |
| cheese | KET、PET | **KET** |
| chicken | KET、PET | **KET** |
| dish | KET、PET | **KET** |
| drink | KET、PET | **KET** |
| … | 共 1630 个，完整清单见 output/cross-level-conflicts.json（本地） | |

## 待人工核对（needs_review）

- **PET 全部 2672 条来自扫描件 OCR**：英文词头与词性可靠，中文释义 OCR 不可靠已留空，需人工补录核对后方可启用。
- OCR 中识别出的拼法变体（如 all right/alright）已写入备注，不作为可接受拼写自动生效（同义词/变体不自动放宽是平台判分红线）。

## 格式样例（每来源 ≤5 条，仅示意字段结构）

### KET 词汇

| headword | 词性 | 释义 | is_phrase | needs_review | sources |
|---|---|---|---|---|---|
| barbecue | n. v. | 烤肉 | False | False | KET整理版·DAY1 |
| chips | n. | 炸土豆条/片 | False | False | KET整理版·DAY1 |
| biscuit | n. | 饼干 | False | False | KET整理版·DAY1 |
| bottle | n. | 瓶子 | False | False | KET整理版·DAY1 |
| chocolate | n. | 巧克力 | False | False | KET整理版·DAY1 |

### PET 词汇

| headword | 词性 | 释义 | is_phrase | needs_review | sources |
|---|---|---|---|---|---|
| address | n | – | False | True | PET扫描件OCR |
| a admire | v | – | False | True | PET扫描件OCR |
| ability | n | – | False | True | PET扫描件OCR |
| able | adj | – | False | True | PET扫描件OCR |
| about | adv & prep | – | False | True | PET扫描件OCR |

### 学术词汇

| headword | 词性 | 释义 | is_phrase | needs_review | sources |
|---|---|---|---|---|---|
| abandon | v. | 放弃 | False | False | 基础学术词汇·整理版; academic_vocabulary_list |
| abstract | adj. | 抽象的 | False | False | 基础学术词汇·整理版; academic_vocabulary_list |
| academy | n. | 学院 | False | False | 基础学术词汇·整理版; academic_vocabulary_list |
| access | n. | 进入 | False | False | 基础学术词汇·整理版; academic_vocabulary_list |
| accommodate | v. | 容纳 | False | False | 基础学术词汇·整理版; academic_vocabulary_list |

### 四级词汇

| headword | 词性 | 释义 | is_phrase | needs_review | sources |
|---|---|---|---|---|---|
| sincere | – | 真诚的 | False | False | 四级乱序版·List1 |
| mood | – | 情绪 | False | False | 四级乱序版·List1 |
| static | – | 稳定的 | False | False | 四级乱序版·List1 |
| senator | – | 议员 | False | False | 四级乱序版·List1 |
| hobby | – | 兴趣 | False | False | 四级乱序版·List1 |

### 雅思&托福词汇

| headword | 词性 | 释义 | is_phrase | needs_review | sources |
|---|---|---|---|---|---|
| burrow | v. | 挖洞穴 | False | False | 雅思阅读词汇·建筑类Architecture |
| construction | n. | 建筑 | False | False | 雅思阅读词汇·建筑类Architecture |
| skyscraper | n. | 摩天大楼 | False | False | 雅思阅读词汇·建筑类Architecture |
| design | v. | 设计 | False | False | 雅思阅读词汇·建筑类Architecture |
| structure | n. | 建筑物 | False | False | 雅思阅读词汇·建筑类Architecture |

## 尚需人工核对的行（汇总）

1. PET 2672 条 OCR 行：释义留空待补，全部 `needs_review=true`；导入后可在管理端「五级词库」按该标记过滤逐条核对。
2. 猴哥托福词组中混入的单词行已跳过；如发现词组解析缺行，对照原 xls 复核。
3. 四级 .doc 为出版物全文提取（新东方《四级词汇词根+联想记忆法（乱序版）》），**未确认授权前不得导入生产库**。
4. 学术词汇两份 xlsx 内容重叠度高（同一份表），合并后如数量异常请对照说明页。

## 导入方式

- 确认授权后：管理端「五级词库」逐级上传导入（预览→确认，事务性），或用本工具 output/ 的规范化 JSON 走 `apply_import.py`。
- 导入只新增 `vocab_level_entry` 行；已发布任务快照与历史 A2/B1/B2 词汇分析结果不受影响。
