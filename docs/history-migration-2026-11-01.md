# Notion 历史迁移与工作量核对

项目：CHARCOAL-001 / english-speaking-assessment。迁移日期：2026-11-01（Asia/Shanghai）。

## 来源与覆盖范围

- [原项目历史档案](https://app.notion.com/p/SpeakUp-english-speaking-assessment-4069aef5c210814e8d04e28e378183c0)
- [产品需求池](https://app.notion.com/p/c6cdf916df6a4dd0bd7d9216f0219fbe)
- [研发工作台](https://app.notion.com/p/fd387147313a4013b4d537b0352ce0ba)
- 本次完整项目导出含 61 条需求、3 条研发执行记录。原页“45 条”是 2026-10-27 的 Excel 回填批次，不能作为今天的总数。
- 61 个 Notion 来源 ID 逐条去重：10 条复用已有 Issue，51 条补建历史归档 Issue。#222 是管理试运行说明，不计作这 61 条产品需求；PR #240 是本次管理配置，也不计入需求数。
- Notion 原页未修改。公开记录仅保存标题、分类、日期、工时原值与换算、来源链接及已有代码引用；详细需求正文、授权约束与运维安全细节保留在原来源。演示登录信息未迁入公开档案。
- GitHub 创建/关闭日期是导入日期；历史提出、认领、完成日期另存，不能用导入日期统计历史交付趋势。

## 工作量口径

用户已于 2026-11-01 确认：备注中“工时 xx h”为实际投入；1 人日=8小时。
43 条历史小时记录共 **634 小时**；8 条“实耗人日”记录共 **9.5 人日=76 小时**。
合计 **51 条有实际投入记录，数值相加为 710 小时**；另 10 条未记录实际投入，保持空值。

**710 小时是原记录数值加总，不是去重后的项目净工时，也不是报价或结算依据。**
“初版需求”“功能增强”等打包记录与后续细项可能重叠。确认范围不重叠后才计算净投入。
不以提交数或 AI 时长补造工时；估时与实耗分开；父项与子项不同时纳入净工时。
[机器可读迁移快照](history/notion-migration-2026-11-01.json)用于审计和后续统计，不另设一套实时需求台账。当前状态仍读 Issue/PR/Projects。

## 状态与来源差异

| 差异 | 本次处理 |
| --- | --- |
| 旧项目页写“自有产品”，用户现在确认客户为 charcoal | 客户归属按本次用户确认；代码/知识产权归属仍以合同为准，未据旧描述推定 |
| 旧页保留 SpeakUp / Charcoal 暂定品牌 | 保留历史名称；当前名称 BELP 按 #229 和现有代码约定 |
| 旧页把 #197 列为待合入 | 已读取 PR 核实 #197 已合并，不据旧待办重复派工 |
| 多租户原需求仍写待评审、未派工 | 保留原始需求；#223 最新实施评论及 #233–#239 证明已分期实施，看板为 In Progress |
| #231 历史源完成日期为 10-06，现有 GitHub 摘要写 10-07 | 两种来源并存，标为待核对，不覆盖已有摘要 |
| 部署/客户验收 | 历史报告与本次代码合并核验分开；未访问生产或代客户验收 |
| #222 既有双轨约定 | 保留，本次是一次性回填；不宣称自动双向同步或正式切换需求权威 |

已重新读取并确认合并的历史 PR：#197、#198、#199、#202、#203、#204、#205、#206、#207、#208。
其余引用只标“历史引用”，不将未核验内容写为本次验证通过。

## 研发执行记录的归并

三个工作台记录分别归到对应需求，不新建三份产品需求，也不重复计算投入。

| 历史执行记录 | 角色（原记录） | 关联需求 | 代码证据 |
| --- | --- | --- | --- |
| 反代配置入库 | PM | #230 | #197 |
| 学生个人学情报告 PDF | DevOps | #287 | #199 |
| 拆句单句配音 P0 | SE | #289 | #202 |

角色为历史记录标签，不推定为当前负责人或独立的人力投入。

## 逐条迁移索引

源状态：60 条“已完成”、1 条“待研发评审”。这是源快照分布，不代表今天的研发状态。

| 历史需求 | GitHub | 提出日期 | 源状态 | 原小时 | 原实耗人日 | 实际小时 |
| --- | --- | --- | --- | --- | --- | --- |
| [outman.press 反代配置入库（避免 redeploy 冲掉）](https://app.notion.com/p/4069aef5c21081168995cb5e54e8d8b3) | [#230](https://github.com/guanlili/english-speaking-assessment/issues/230) | 2026年10月27日 | 已完成 | — | 0.75 | 6 |
| [单次反馈只反馈个分，和学生读完的转文字,这个速度要快,最后的总反馈反馈的细节一些，整评分,这个要细要全面](https://app.notion.com/p/4069aef5c210811d89eaff4feab5c1c0) | [#241](https://github.com/guanlili/english-speaking-assessment/issues/241) | 2026年9月27日 | 已完成 | 4 | — | 4 |
| [情景问答 · 题目管理](https://app.notion.com/p/4069aef5c2108199b674ce4e284e98f6) | [#242](https://github.com/guanlili/english-speaking-assessment/issues/242) | 2026年9月29日 | 已完成 | 6 | — | 6 |
| [教师后台增加题库录入的功能](https://app.notion.com/p/4069aef5c21081a09087ed62bc74da02) | [#243](https://github.com/guanlili/english-speaking-assessment/issues/243) | 2026年9月27日 | 已完成 | 6 | — | 6 |
| [初版需求](https://app.notion.com/p/4069aef5c21081ebb13bee4f6da7e3dd) | [#244](https://github.com/guanlili/english-speaking-assessment/issues/244) | 2026年9月25日 | 已完成 | 96 | — | 96 |
| [整体的用户体系，有超级管理员，教师，学生，学生需要有账号（学号）密码登录，之后才能加入课堂。](https://app.notion.com/p/4069aef5c21081ef812bef32c5186828) | [#245](https://github.com/guanlili/english-speaking-assessment/issues/245) | 2026年9月28日 | 已完成 | 4 | — | 4 |
| [文章朗读有倍速，为什么听句复述没有倍速](https://app.notion.com/p/4069aef5c210811aaedac7d8cca2f689) | [#246](https://github.com/guanlili/english-speaking-assessment/issues/246) | 2026年9月29日 | 已完成 | 4 | — | 4 |
| [凌晨修改](https://app.notion.com/p/4069aef5c2108139876edc99b3f116b0) | [#247](https://github.com/guanlili/english-speaking-assessment/issues/247) | 2026年9月29日 | 已完成 | 8 | — | 8 |
| [模考功能防作弊防切屏整个考试限时](https://app.notion.com/p/4069aef5c2108159b7fff08ced38f070) | [#248](https://github.com/guanlili/english-speaking-assessment/issues/248) | 2026年9月30日 | 已完成 | 18 | — | 18 |
| [教师端在课程里看，学生名单展示有问题，帮我优化下](https://app.notion.com/p/4069aef5c21081aa8902de12f6534283) | [#249](https://github.com/guanlili/english-speaking-assessment/issues/249) | 2026年9月29日 | 已完成 | 16 | — | 16 |
| [双语界面给外教使用](https://app.notion.com/p/4069aef5c21081bc857bf7204a366a0a) | [#250](https://github.com/guanlili/english-speaking-assessment/issues/250) | 2026年9月30日 | 已完成 | 8 | — | 8 |
| [增加背单词的模块](https://app.notion.com/p/4069aef5c2108109b75dc27577baa6e3) | [#251](https://github.com/guanlili/english-speaking-assessment/issues/251) | 2026年9月30日 | 已完成 | 60 | — | 60 |
| [五级词库统一——全系统分级标准切换](https://app.notion.com/p/4069aef5c2108109b9d6e8b9caac1bb3) | [#252](https://github.com/guanlili/english-speaking-assessment/issues/252) | 2026年10月6日 | 已完成 | 12 | — | 12 |
| [ipad端适配](https://app.notion.com/p/4069aef5c210811c96ccd31f504bac7d) | [#253](https://github.com/guanlili/english-speaking-assessment/issues/253) | 2026年9月30日 | 已完成 | 6 | — | 6 |
| [词汇分级](https://app.notion.com/p/4069aef5c2108154b34bea56d1e90689) | [#254](https://github.com/guanlili/english-speaking-assessment/issues/254) | 2026年10月3日 | 已完成 | 34 | — | 34 |
| [口语题目分级](https://app.notion.com/p/4069aef5c21081d9a375ee32235b8124) | [#255](https://github.com/guanlili/english-speaking-assessment/issues/255) | 2026年10月3日 | 已完成 | 28 | — | 28 |
| [平台更名：SpeakUp → Charcoal（暂定名）](https://app.notion.com/p/4069aef5c210813fa75bfdbd70f6f0ed) | [#256](https://github.com/guanlili/english-speaking-assessment/issues/256) | 2026年10月6日 | 已完成 | 2 | — | 2 |
| [功能增强](https://app.notion.com/p/4069aef5c2108151821ee57c1f87017d) | [#257](https://github.com/guanlili/english-speaking-assessment/issues/257) | 2026年10月6日 | 已完成 | 16 | — | 16 |
| [题库：主题-篇目-句子结构](https://app.notion.com/p/4069aef5c2108155a070c711a81310f8) | [#258](https://github.com/guanlili/english-speaking-assessment/issues/258) | 2026年10月7日 | 已完成 | 12 | — | 12 |
| [选择练习题目时可以改不同题型题目的顺序，希望顺序：读句，问答，读句，问答](https://app.notion.com/p/4069aef5c210815a9caaca4eefa956be) | [#259](https://github.com/guanlili/english-speaking-assessment/issues/259) | 2026年10月7日 | 已完成 | 15 | — | 15 |
| [学生多班归属——一个账号可加入多个班级](https://app.notion.com/p/4069aef5c2108172a680ff8578f86ee3) | [#231](https://github.com/guanlili/english-speaking-assessment/issues/231) | 2026年10月6日 | 已完成 | 14 | — | 14 |
| [单个练习只能选择一个口语主题题目，希望能多选](https://app.notion.com/p/4069aef5c210814da51ef49f2fcce1da) | [#232](https://github.com/guanlili/english-speaking-assessment/issues/232) | 2026年10月7日 | 已完成 | 8 | — | 8 |
| [题目限时设置之后练习中还是默认一分钟](https://app.notion.com/p/4069aef5c2108175ac49d5627d10acae) | [#260](https://github.com/guanlili/english-speaking-assessment/issues/260) | 2026年10月7日 | 已完成 | 9 | — | 9 |
| [题目切换按下一题按钮不能直接切换下一题，需要在摁麦克风才能切换，且按麦克风切换后的第一次录音评分不准，需要重练](https://app.notion.com/p/4069aef5c210817f95a3f754ce43a39d) | [#261](https://github.com/guanlili/english-speaking-assessment/issues/261) | 2026年10月7日 | 已完成 | 6 | — | 6 |
| [组题逻辑统一调整：所有题型统一采用「主题-篇目-句子」三级结构，当前仅听句复述模块已实现折叠逻辑，其余题型需全部对齐该标准，以篇目为单位选题、调序，无需逐…](https://app.notion.com/p/4069aef5c21081e5aa49c4a25af3b206) | [#262](https://github.com/guanlili/english-speaking-assessment/issues/262) | 2026年10月7日 | 已完成 | 4 | — | 4 |
| [课堂删除功能异常：测试阶段创建的大量冗余班级，即便清空成员仍提示异常，无法正常删除，需作为最高优先级修复。](https://app.notion.com/p/4069aef5c21081fe844cda608769ccdc) | [#263](https://github.com/guanlili/english-speaking-assessment/issues/263) | 2026年10月7日 | 已完成 | 10 | — | 10 |
| [题库层级结构混乱：当前文章拆分句子后平铺展示，配置试题时需逐一点选翻找，操作效率极低，需统一调整层级逻辑。](https://app.notion.com/p/4069aef5c210810287fdd22d5ddb4d73) | [#264](https://github.com/guanlili/english-speaking-assessment/issues/264) | 2026年10月7日 | 已完成 | 5 | — | 5 |
| [我还需要新增一个功能，就是现在出题的时候不是有三种类型吗？我想增加一种类型叫提干就是这个题目吧，题目说明题目说明的目的呢，就是在其实不同的题之间可能老师的…](https://app.notion.com/p/4069aef5c210814c885bd45394a6a2dd) | [#265](https://github.com/guanlili/english-speaking-assessment/issues/265) | 2026年10月8日 | 已完成 | 12 | — | 12 |
| [在题目配置设置中，生成ai朗读之后，点击小喇叭按钮，并不能听ai生成的朗读，按钮无效](https://app.notion.com/p/4069aef5c2108169bf7fced2255067db) | [#266](https://github.com/guanlili/english-speaking-assessment/issues/266) | 2026年10月8日 | 已完成 | 12 | — | 12 |
| [模考模式专属规则：模考场景下移除「再练一次」选项，避免学生反复重答导致进度差异过大，单题倒计时结束后自动跳转下一题，匹配真实考试规则。](https://app.notion.com/p/4069aef5c210816cbff9d76f5dd98a3a) | [#267](https://github.com/guanlili/english-speaking-assessment/issues/267) | 2026年10月7日 | 已完成 | 2 | — | 2 |
| [增加题目缓冲功能，题干说明，这个单独的题型](https://app.notion.com/p/4069aef5c2108183bae8e9254914abde) | [#268](https://github.com/guanlili/english-speaking-assessment/issues/268) | 2026年10月8日 | 已完成 | 8 | — | 8 |
| [学生和老师都能查看一个任务做完之后的那个详细反馈。目前学生是到了第二天就看不了前一天的详细反馈了，老师那个班级面板里也只能看见学生的百分制评分和听录音，但…](https://app.notion.com/p/4069aef5c2108133af42e86ded9300e4) | [#269](https://github.com/guanlili/english-speaking-assessment/issues/269) | 2026年10月10日 | 已完成 | 30 | — | 30 |
| [四、教师端反馈与听评](https://app.notion.com/p/4069aef5c21081399ae1fc93b0cf01e6) | [#270](https://github.com/guanlili/english-speaking-assessment/issues/270) | 2026年10月11日 | 已完成 | 19 | — | 19 |
| [二、考试模式](https://app.notion.com/p/4069aef5c21081628e3afe0c45cd4c43) | [#271](https://github.com/guanlili/english-speaking-assessment/issues/271) | 2026年10月11日 | 已完成 | 24 | — | 24 |
| [三、练习模式](https://app.notion.com/p/4069aef5c210817d938de6d19cd318fa) | [#272](https://github.com/guanlili/english-speaking-assessment/issues/272) | 2026年10月11日 | 已完成 | 16 | — | 16 |
| [一、通用功能](https://app.notion.com/p/4069aef5c210819ca9cee8436b351599) | [#273](https://github.com/guanlili/english-speaking-assessment/issues/273) | 2026年10月11日 | 已完成 | 18 | — | 18 |
| [考试模式学生题目说明可以跳过（这个等他读完太久了），录音学生说完可以直接点击下一题（这个非常重要，因为有的学生说的快时间没到但是倒计时还在走，会把其他学生…](https://app.notion.com/p/4069aef5c21081488569c0c46eb45a74) | [#274](https://github.com/guanlili/english-speaking-assessment/issues/274) | 2026年10月12日 | 已完成 | 4 | — | 4 |
| [这俩按钮在考试模式中去掉](https://app.notion.com/p/4069aef5c210816081e8f49b183e62c4) | [#275](https://github.com/guanlili/english-speaking-assessment/issues/275) | 2026年10月11日 | 已完成 | 2 | — | 2 |
| [五、缺陷修复与界面优化](https://app.notion.com/p/4069aef5c2108177a37aed9fae78626a) | [#276](https://github.com/guanlili/english-speaking-assessment/issues/276) | 2026年10月11日 | 已完成 | 8 | — | 8 |
| [这个朗读拆句功能没问题，但是每一个句子无法独立配置时间，还是自动设定的时间。看下方的听句复述就可以单独每个句子去配置时长，希望可以每一句都单独配置](https://app.notion.com/p/4069aef5c2108196bab2f8da999f1a30) | [#277](https://github.com/guanlili/english-speaking-assessment/issues/277) | 2026年10月12日 | 已完成 | 14 | — | 14 |
| [课堂面板设计的好看点](https://app.notion.com/p/4069aef5c21081acb17ad3d8b02eed78) | [#278](https://github.com/guanlili/english-speaking-assessment/issues/278) | 2026年10月11日 | 已完成 | 6 | — | 6 |
| [导出与学情报告（音频 ZIP / 学生报告 / 班级报告）](https://app.notion.com/p/4069aef5c2108134a5b5c1903c60b5f3) | [#226](https://github.com/guanlili/english-speaking-assessment/issues/226) | 2026年10月27日 | 已完成 | — | — | — |
| [在现有口语平台的题库中，优先增加批量导入、导出功能，方便学校集中录入和维护托福、雅思口语题目。支持 Excel/CSV 模板，保留题干、题型、主题、作答时…](https://app.notion.com/p/4069aef5c210815da65bd528dda5b683) | [#279](https://github.com/guanlili/english-speaking-assessment/issues/279) | 2026年10月14日 | 已完成 | 28 | — | 28 |
| [提高班级上限人数，可配置。](https://app.notion.com/p/4069aef5c210816cb925c6e77fc5325d) | [#280](https://github.com/guanlili/english-speaking-assessment/issues/280) | 2026年10月13日 | 已完成 | 2 | — | 2 |
| [模考模式播放录音会卡，还有一个是显示录音开始的时候，其实会过一秒钟大概才开始录音](https://app.notion.com/p/4069aef5c210816d8ab6fdbf6262f17c) | [#281](https://github.com/guanlili/english-speaking-assessment/issues/281) | 2026年10月13日 | 已完成 | 18 | — | 18 |
| [管理面板优化](https://app.notion.com/p/4069aef5c21081ad932cc72f79196339) | [#225](https://github.com/guanlili/english-speaking-assessment/issues/225) | 2026年10月23日 | 已完成 | — | — | — |
| [分数口径解释触点——参考分/模拟分差异可解释](https://app.notion.com/p/4069aef5c210811bab91c6e8d697d856) | [#282](https://github.com/guanlili/english-speaking-assessment/issues/282) | 2026年10月11日 | 已完成 | — | — | — |
| [学情诊断与趋势——逐词标注、弱项诊断、四维趋势与班级趋势](https://app.notion.com/p/4069aef5c2108172a9bbc52057724b0f) | [#283](https://github.com/guanlili/english-speaking-assessment/issues/283) | 2026年10月19日 | 已完成 | — | — | — |
| [课堂教学闭环——讲评持久化、指定补练、课堂消息与阶段报告](https://app.notion.com/p/4069aef5c2108185a23fe5fc7a699687) | [#284](https://github.com/guanlili/english-speaking-assessment/issues/284) | 2026年10月15日 | 已完成 | — | — | — |
| [数据备份与可验证恢复（含音频卷）](https://app.notion.com/p/4069aef5c2108198be77d5f0f5c0d10d) | [#285](https://github.com/guanlili/english-speaking-assessment/issues/285) | 2026年9月29日 | 已完成 | — | — | — |
| [平台更新日志——管理员发布、教师可见、侧栏未读红点](https://app.notion.com/p/4069aef5c210819ca960e3248f6aeb13) | [#286](https://github.com/guanlili/english-speaking-assessment/issues/286) | 2026年10月26日 | 已完成 | — | — | — |
| [导出：教师全班可视化分析报告](https://app.notion.com/p/4069aef5c2108158b7bde2b3e03f244f) | [#227](https://github.com/guanlili/english-speaking-assessment/issues/227) | 2026年10月27日 | 已完成 | — | 1 | 8 |
| [导出：学生个人学情报告（PDF）](https://app.notion.com/p/4069aef5c2108188a4b4d148ab205a74) | [#287](https://github.com/guanlili/english-speaking-assessment/issues/287) | 2026年10月27日 | 已完成 | — | — | — |
| [导出：口语原音频 ZIP（学生自助 + 教师按班/按题）](https://app.notion.com/p/4069aef5c21081f79ca3f5dc5fe2aa89) | [#288](https://github.com/guanlili/english-speaking-assessment/issues/288) | 2026年10月27日 | 已完成 | — | 5 | 40 |
| [拆句朗读：每句可单独生成 AI 配音（P0 单句按钮；P1 批量一键）](https://app.notion.com/p/4079aef5c21081cdb6d4d056f8581cf3) | [#289](https://github.com/guanlili/english-speaking-assessment/issues/289) | 2026年10月28日 | 已完成 | — | 1 | 8 |
| [部署链稳定化：依赖下载固化国内镜像 + 超时上调（不引入新服务）](https://app.notion.com/p/4079aef5c210816eb8d1f7d63126fb53) | [#290](https://github.com/guanlili/english-speaking-assessment/issues/290) | 2026年10月29日 | 已完成 | — | 0.25 | 2 |
| [拆句配音 P1：批量一键配音 + 配音覆盖率可视化 + 发布前未配音提醒](https://app.notion.com/p/4089aef5c2108119815cf5f1c10cb7ba) | [#291](https://github.com/guanlili/english-speaking-assessment/issues/291) | 2026年10月29日 | 已完成 | — | 0.5 | 4 |
| [导出无界防护：学生自助 ZIP 套时间窗 + 行数硬上限](https://app.notion.com/p/4089aef5c21081c7b5f4f32332ade52a) | [#228](https://github.com/guanlili/english-speaking-assessment/issues/228) | 2026年10月29日 | 已完成 | — | 0.5 | 4 |
| [平台更名：BRS English Learning Platform（简称 BELP）](https://app.notion.com/p/4089aef5c21081789ed3d0c723da194f) | [#229](https://github.com/guanlili/english-speaking-assessment/issues/229) | 2026年10月29日 | 已完成 | — | 0.5 | 4 |
| [部署提速：服务器拉取预检前置，bundle 仅在拉取失败时兜底传输](https://app.notion.com/p/4089aef5c21081fe8a28ec568fce87ae) | [#224](https://github.com/guanlili/english-speaking-assessment/issues/224) | 2026年10月29日 | 已完成 | — | — | — |
| [多租户商用改造——一套部署服务多客户（分期落地）](https://app.notion.com/p/4099aef5c21081c2bde7e1ad7170ab76) | [#223](https://github.com/guanlili/english-speaking-assessment/issues/223) | 2026年10月31日 | 待研发评审 | — | — | — |
