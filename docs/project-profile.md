# 项目档案：英语口语评测平台

| 项目 | 已确认信息 |
| --- | --- |
| 项目编号 | CHARCOAL-001（本次试点采用的内部管理编号） |
| 客户 | 查理公司（charcoal，用户于 2026-11-01 确认；非核验后的工商全称） |
| 客户项目序号 | 第一个项目 |
| 代码仓库 | https://github.com/guanlili/english-speaking-assessment |
| 产品名称 | BRS English Learning Platform / BELP（依据 CLAUDE.md 与 #229；README 中旧品牌描述待统一） |
| 管理试点开始 | 2026-11-01（Asia/Shanghai） |
| 管理看板 | https://github.com/users/guanlili/projects/3 （当前私有） |
| 记录可见范围 | 用户已确认客户归属、实际工时与商务记录可以放在当前公开仓库；仅填写已确认信息 |
| 当前阶段 | 已有生产使用记录，持续迭代；非本次重新核验生产 |
| 合同范围、金额、结算方式 | 待用户确认；本档案不构成报价或新交付承诺 |
| 人工负责人、客户验收人、交期 | 待用户确认，不从 GitHub 作者或学校名称推定 |
| 维护/质保期限、权属及复用边界 | 待用户确认 |
| 当前关注 | 多租户 #223 的阶段实施与后续验收；已有 Notion 双轨试运行 #222 |

客户 charcoal 与使用学校/产品品牌分别记录，不把学校名称推定为签约客户。
项目编号不要求重命名代码仓库或改变产品展示名。

## 日常入口

- [项目管理约定](project-management.md)
- [需求与改动](https://github.com/guanlili/english-speaking-assessment/issues)
- [代码评审与实现](https://github.com/guanlili/english-speaking-assessment/pulls)
- [多租户需求](https://github.com/guanlili/english-speaking-assessment/issues/223)
- [历史双轨试运行](https://github.com/guanlili/english-speaking-assessment/issues/222)
- [试点配置草稿 PR](https://github.com/guanlili/english-speaking-assessment/pull/240)

## 2026-11-01 试点基线快照

这是一次带日期的盘点，不是另一个实时任务台账。后续状态直接读 Issue、PR 和 Projects。
已关联需求 #222–#232；其中 #223 为父需求，阶段 PR 不能作为新增需求重复计量。

| #223 阶段 | 代码证据 | 本次核验到的事实 | 实际人工投入 |
| --- | --- | --- | --- |
| A 盘点验证 | [#233](https://github.com/guanlili/english-speaking-assessment/pull/233) | 已合并 | 未记录 |
| B1 租户地基 | [#234](https://github.com/guanlili/english-speaking-assessment/pull/234) | 已合并 | 未记录 |
| B2 学校入口 | [#235](https://github.com/guanlili/english-speaking-assessment/pull/235) | 已合并 | 未记录 |
| B3 运营身份 | [#236](https://github.com/guanlili/english-speaking-assessment/pull/236) | 已合并 | 未记录 |
| C1 业务表租户字段 | [#237](https://github.com/guanlili/english-speaking-assessment/pull/237) | 已合并 | 未记录 |
| C2 校内唯一性 | [#238](https://github.com/guanlili/english-speaking-assessment/pull/238) | 已合并 | 未记录 |
| C3 请求与任务上下文 | [#239](https://github.com/guanlili/english-speaking-assessment/pull/239) | 已合并 | 未记录 |

#223 评论已有阶段部署报告，但本次未访问生产环境，不将其写为本次部署验证或客户验收。
父需求正文的初始“未派工”描述已与实施记录产生差异；读最新评论与 PR，不据此重新派工或覆盖原始需求。
C4/C5、D/E 等剩余工作以最新设计与后续记录为准，本试点不新增功能实施授权。
历史 26–40 人日是原需求估算，不是已经发生的投入，未确定人日小时口径前不转换为小时。

## 首次试验的工作记录

2026-11-01：盘点项目现有记录，关联 11 条历史需求，建立工时/工作类型/交付状态字段；
准备 Issue、PR 模板与 AI 收尾约定。实现证据见 PR #240。
（后续变更：2026-11-13 接入 devledger 后字段统一为 类型/来源/需求人/工时(h)/开始/结束，早期字段已清理，见 `project-management.md` 最小字段表与 #435。）
实际人工投入：未记录。AI 执行时长不折算成人时。
试验是否继续：通过下一批 3–5 次真实工作，检查追溯完整性、回填负担与工时归因。

## 历史档案已补齐（2026-11-01）

已核对 Notion 完整导出：61 条需求、3 条执行记录；10 条复用、51 条补建历史归档 Issue。详见 [迁移与工时核对报告](history-migration-2026-11-01.md)。

用户确认历史小时数为实际投入，1 人日=8小时。51 条有实际投入记录，数值加总710小时，另10条未记录。该数值尚未核对范围重叠，不是净投入或结算工时；上文多租户 A–C3 阶段未知工时仍保持未知。

看板新增“进行中与待办”“历史需求与交付”视图；本仓库 Issue 新增或更新后自动进入项目。Notion 历史需求详细正文保留在原来源，公开归档以管理元数据和来源索引为主。
