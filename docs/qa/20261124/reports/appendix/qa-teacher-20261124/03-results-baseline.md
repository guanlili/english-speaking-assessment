# 证据 3：结果页基线（学生未作答，首载成功态）

- 时间：2026-11-24 本地；任务 assignment_id `[id]`
- 接口：`GET /api/v1/classes/SD100X/vocabulary/results?assignment_id=[id]`（首载 200）
- 截图：`10-results-baseline.png`

## 顶部汇总卡片（页面原文）

| 卡片 | 值 |
|---|---|
| 名单学生 | 2 |
| 已完成 | 0 |
| 进行中 | 0 |
| 未开始 | 2 |
| 完成率 | 0%（分母 = 发布时的名单，后加入的学生不计入） |

说明原文：成绩按每题第一次作答统计；练习重试不冲高正确率。

## 按出题方式看表现（首答口径）

| 出题方式 | 已答题数 | 首答正确 | 首答正确率 |
|---|---|---|---|
| 看义拼词 meaning | 未出题 | 0 | – |
| 英译中（四选一）en_zh | 未出题 | 0 | – |
| 中译英（四选一）zh_en | 未出题 | 0 | – |
| 语境填空 cloze | 未出题 | 0 | – |

说明原文：勾了但全班零作答的题型显示「未出题」，不折算成 0% 正确率。

## 逐词错误分布

还没有错词——学生都还没开始，或首答全对。18 词逐词表均为 `0 / 2`、首答正确 0、常见误拼 –：
apple/banana/careless/teacher/preheat/unhappy/rethink/helpful/kindness/bookmark/notebook/sunlight/rainbow/popcorn/teapot/sunflower/writer/disable。

## 学生完成情况

| 姓名 | 状态 | 已答 | 首答正确 | 首答正确率 | 交卷时间 |
|---|---|---|---|---|---|
| 学生1-1（s10001） | 未开始 | 0 / 18 | 0 | – | – |
| 学生1-2（s10002） | 未开始 | 0 / 18 | 0 | – | – |

说明原文：零作答显示「未开始」，不折算成 0% 正确率；统计只看每题第一次作答。

## DB 旁证

- `vocabulary_session`（本任务）= 0；`vocabulary_answer` 经 session 关联 = 0。
- 目标名单 2 人：s10001 `[id]`、s10002 `[id]`。

## 二次进入异常（D6，待干净会话复测）

重登后同接口返回 403，页面回退「该期数没有结果数据 / No result data for this round」；首次首载为上述正常态。DB 中任务与名单未变。
