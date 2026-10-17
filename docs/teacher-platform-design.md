# Charcoal 教师平台设计

## 产品定位

服务一堂口语课的完整流程：老师准备内容、组织学生练习、查看录音和反馈、安排下一次教学。教师端不展示激励运营、词表维护、账号权限等无关入口。

老师只需理解三个对象：课堂、练习、题目。课堂用于组织学生；一份练习容纳有序的题目；可作答的题目有文章朗读、听句复述、情景问答三种，另有「题目说明」引导页（无作答，学生点「继续」进入下一题，模考中按秒数计时）。

## 导航与页面职责

- 我的课堂（登录默认页）：创建课堂、进入教学空间；导入学生与名单放在次级操作。
- 题目库：按题型出题、预览、搜索和复用；题目说明在组卷时内联新建或勾选复用。
- 平台设置：仅管理员可见、默认折叠，容纳账号权限、词表及兼容旧数据的维护功能。

不再增加一个重复罗列功能的“教学工作台”。学习单元、情景、问法是内容组织细节，不作为教师的一级菜单。

课堂教学空间的目标结构：

1. 课堂练习：练习列表、当前发布、创建下一次练习、历史归档。
2. 学生结果：按练习查完成情况、录音、转写与参考反馈。
3. 学生管理：导入、加入、移出、账号恢复。

当前版本将练习安排与结果放在课堂内，学生名单保留在课堂卡片的次级区域。

## 三种出题体验

| 题型 | 老师准备 | 老师配置 | 学生过程 |
| --- | --- | --- | --- |
| 文章朗读 | 英文文章或段落；可选中文提示与参考音 | 作答时长、难度 | 阅读题目 → 录音 → 提交 → 参考反馈 |
| 听句复述 | 一句英语与标准音 | 作答时长、可听次数，0 表示不限 | 听音 → 按剩余次数重听 → 复述录音 |
| 模拟问答 | 英文问题、可选提示和音频 | 难度、答题时长、顺序 | 听题 → 自由作答 → 下一问 |

AI 出题是问答编辑器内的辅助能力，生成结果为待审核草稿，明确采纳才写入；保存失败保留草稿。AI 功能不可用时仍可手动出题。

三种题型均可独立创建，复述和纯问答不要求老师先建一篇文章。所有已发布题目采用快照，修改题库只影响未来发布。

## 课堂备课与发布

目标流程：进入课堂 → 新建练习 → 添加或复用题目 → 调整顺序与参数 → 预览 → 发布给本课堂 → 查看结果 → 归档。

编辑与发布必须分开。选择内容、勾选题型不立即改变全班练习。发布前校验空题单、题干、播放次数、时长和音频准备情况；问答只需该主题有题即可（2026-09-29 起不分级，全班同题，老师自由编排）。

发布摘要必须展示目标课堂、内容、题型和题量。发布失败保留选择，成功后明确显示当前发布内容。不把“清除指派”称为“结束考试”：清除目前意味着恢复自主练习。

## 数据结构（已落地，名称以 models.py 为准）

- Classroom：课堂名称、年级/班型、教学目标、教师归属、成员、启用状态。课堂码只是加入方式，不替代课堂名称。
- Question：类型与题干，附难度、时长、参考音、复述播放次数；不通过主题字符串隐式关联。
- ClassroomExercise：所属课堂、标题、递增版本号；发布时把题目与参数深拷贝进 `snapshot_items`（发布与快照写入同一事务）。
- Attempt：关联学生、练习版本与具体题目，提交时再存 `item_snapshot`；录音、评分、反馈独立存储。

权限验证以课堂教师归属为准。未排期需求：题目库区分个人和校内共享、复用他人内容默认复制——当前为全校教师共享题库（已确认决策），改题库不影响已发布快照，但会影响他人后续组卷。

结果页需分开显示提交人数、完成全部题目人数、评分中人数、待关注人数；分数标注参考并注明来源。历史结果始终按当时题单解释，不能随题库编辑变化。

## 当前实现

- 一级导航收敛为我的课堂与题目库，首页直接进入课堂，平台设置默认折叠；操作使用真实生成客户端与数据，无模拟发布或假统计。
- 题目库按「主题 → 篇目 → 句子」三层组织；听句复述支持编辑句子、时长、可听次数，问答保留手动、AI 草稿和批量入口；题目说明在组卷时内联新建或勾选复用。
- 课堂内练习安排与结果分开。结果页提供教学动作：复制未完成学生的提醒文案、复制单个学生的反馈提示、直接进入下一次练习安排。
- 发布流程：选择内容、选择题型、完整性检查、内容预览、确认发布；未选题型、无材料、缺复述句、主题无问答题时阻止发布（多档问答齐备要求已随「问答不分级」决策移除）。补题入口带课堂上下文，可直接返回原课堂继续安排。
- 课堂支持自定义名称、年级/班型和教学目标，课堂码只作为学生进入课堂的凭证；课堂难度由教师选题和发布内容决定，A2/B1/B2 仅保留为词表和评分的内部元数据，不出现在课堂流程。
- 课堂删除（2026-10-08）：确认永久删除后可清理课堂的完整历史，包括已移出成员的口语与词汇记录；学生账号及其他课堂保留。停用课堂同样可删除，评分中记录需等待评分结束。
- 模考逐题规则（2026-10-08）：服务器按发布快照顺序计时；到时自动停止并提交录音、进入下一题；刷新不能重置时间或回到旧题；结果页仅可回放，移除重练与换题入口（细节见 docs/module-notes.md「模考模式」）。

## 底层边界（快照与发布校验）

- 课堂发布会生成不可变练习版本（`ClassroomExercise` 快照）：题目文本、音频地址、建议时长和复述次数随版本保存；学生当日会话、作答提交、评分 worker 与教师面板均按该版本。题库后续修改只影响下一次发布，旧版本仍可通过课堂练习历史接口回看。旧课堂若尚未重新发布，仍按兼容路径读取原有指派。
- 发布校验在后端收口（`app/services/exercise.py` `publish_exercise`，快照与课堂镜像同一事务写入）：空题单、重复题、拆句展开后超 100 题、主题停用返回 422；题目缺失或内容停用（篇目/复述句/题目说明/问答题）返回 404。页面上的校验只是提前反馈，绕过前端直接调接口同样被拦截。注意语义区分：`PUT /classes/{code}/assignment` 传 `items=[]` **不是被拒绝的无效请求**——它归档当前练习并清除指派（恢复自主练习），想保留当前发布就不要发空列表。
- 朗读直接选择整篇文章，分句没有单独的组卷复选框；拆分过的文章（`reading_split`）发布/练习时按句展开成逐句朗读题：每句单独录音评分，作答限时按句长推算 4–30 秒，句子条目用 uuid5(passage_id, 句序) 的确定性合成 ID，只在快照/题单层存在、不建篇目行，指派镜像仍存整篇 ID；`DELETE /admin/passages/{id}/split` 可取消拆分。历史拆段版本曾拆成多篇、#88 统一为整篇一道题、2026-10-08 起拆句真正下发——旧发布仍按原快照解释，历史拆段篇目在归属完整且唯一时迁回原文章。听句复述的自动拆分是另一项操作，从正文选 3 句生成听音后复述题。
- 听句复述选择独立句库（不挂篇目可直接创建/指派），情景问答按主题整组、不分级选题；历史拆分题重选时归回原文章。
- 听数规则边界：复述句的可听次数由服务器在**播放前**登记（`item_listen` 计数），加载/播放中重复点击被前端禁用、播放失败有提示，但**失败不自动退回次数**（2026-10-09 交互审计后维持的现状口径）。
- 题库三层重构（主题 → 篇目 → 句子）的有意决策：未挂篇目的独立句**有意保留**（不强制迁移归属）；指派页保持平铺不按主题分组（出题要快）；Scenario 与 Unit 实体不合并，仍按 topic 字符串配对，情景配不到时降级为问答缺席而非 404。

## 验收路径

1. 登录后只看见我的课堂和题目库；管理员设置折叠。
2. 从课堂进入题目库，三种题型各有清晰说明，可返回同一课堂。
3. 设置复述可听次数后再打开，值保持一致；仅更新音频不重置播放限制。
4. 勾选、选择内容不会发布；至少一种题型且内容齐备才能预览。
5. 发布成功刷新当前课堂；失败保留输入。
6. 学生结果独立于备课表单，录音和参考反馈可回看。
7. 朗读文章可折叠查看分句，选择一次即选整篇；未拆分文章计为一道题，拆分文章按句展开（预览与题单标注逐句题数）。
8. 冗余/停用课堂在确认后可删除，清空成员后仍能清理归档历史；评分未结束时保留确认框并提示稍后重试。
9. 模考每题倒计时到时自动推进，刷新不会回到上一题；最后一题完成/到时进入结果页，结果页可回放但不提供重答入口。普通练习仍可重练。

## 私有备课草稿、历史复制与异常提示（2026-10-16）

- 草稿按教师账号与课堂隔离，编辑标题、选题、题序和考试模式后约 800ms 自动保存到服务器；切换设备可继续。未保存时有状态提示，关闭/刷新有浏览器离开保护。断网时保留页面编辑，恢复后可重试；浏览器崩溃或强制关闭前尚未完成的保存不能保证恢复。
- 草稿通过版本比较阻止多设备互相覆盖。发生冲突后保留当前页面编辑并提示重新加载，不静默覆盖服务器。登录身份变化后不再提交旧页面的排队保存，也不把迟到响应写入新账号缓存。
- 发布前等待草稿保存完成，再在同一发布事务中检查版本并清理本人的草稿。发布失败保留草稿；其他教师的草稿不清理。当前发布变化时，旧草稿仍保留并提示核对。可确认放弃编辑、恢复当前发布选题。
- 发布历史可复制选题、顺序、标题及考试模式到本人有权限的课堂草稿；替换目标已有草稿需明确勾选确认。**新练习使用题库当前的题文、音频和逐题设置**，不是逐字克隆旧快照；旧成绩、作答、计时状态不复制。已删除的材料会在组卷校验中提示，必须处理后才能发布。
- 学生结果页每 5 秒检查课堂异常。麦克风/播放/提交问题来自学生设备的枚举上报，不包含原始错误、正文或录音；持续问题每分钟刷新，超过 5 分钟失效。无网络的设备不能上报，未作答也不能据此推断离线或设备异常。
- 服务端仅检查今日、当前发布、当前在班学生的最新课堂轮次。评分失败和排队/处理超过 2 分钟单独提示；每题只看最新作答，后续成功不再展示旧失败。定位学生会展开对应结果，不自动重传、重评或重置考试。

### English

Private drafts are scoped to the teacher and classroom. Edits save to the server after about 800ms and can resume on another device. Failed saves keep the form open for retry; unsaved edits warn on browser exit. A crash or forced close before a save completes can still lose changes. Revision conflicts prevent overwriting another device. Successful publishing checks the draft revision and removes only that teacher's draft in the publication transaction; failure keeps it.

History reuse copies selections, order, title and exam mode into an authorized target classroom's private draft. Replacing an existing draft requires explicit confirmation. New publication uses **current question-bank text, audio and item settings**; it does not clone historical content or copy results. Missing items must be resolved before publishing.

The student-results panel checks issues every five seconds. Device and submission hints are self-reported enums, refreshed every minute while present and expire after five minutes. Offline devices cannot report, and missing answers are not treated as device faults. Server-side scoring alerts use the latest attempt per item in today's current publication only. Finding a student expands their results without retrying uploads or changing exam clocks.

## 教师点评与指定学生补练（2026-10-16）

- 教师在作答详情编辑点评并标记重点；文字、作者、时间及版本独立于 AI 建议/参考分。重点标记在当前最新作答的名单行可见，属于该条作答，不是给学生永久贴标签。保存失败保留编辑；并发冲突需确认重新加载，不能静默覆盖。
- 学生在练习结果与历史回看中看到教师点评。考试进行中，作答接口与题单接口都不返回点评、作者、时间或重点标记；考试结束后恢复。点评不修改转写、参考分、rubric 或考试成绩。
- 教师在学生结果页选择来源发布、原题和接收学生，创建独立补练。补练**复制原发布快照**（包括拆句的原题 ID 和题面），与“历史复制到备课草稿使用当前题库”不同。题库编辑/删除不重解释补练题目；补练不复制原作答、不重开考试、不改变全班 current_exercise_id。
- 接收名单及显示名发布时固定；教师只能选择当前课堂成员。学生只看到自己的任务和自己的进度，不能通过任务 ID 打开他人的任务。原课堂活动仍按 daily 统计，补练使用 followup 模式，跨天继续同一会话，不允许换出任务外的题。
- 当前活动考试不能布置为补练。使用归档考试时，接收学生若仍在该考试作答，也拒绝发布，避免借普通练习绕过考试反馈边界。补练自身为普通练习，可重练；进度按每题最新作答，评分失败与评分中单独显示，不伪造完成。
- 教师可撤销补练，已有记录保留；学生不能再开会话或提交新作答。上传开始及音频校验后均复查状态，撤销与提交串行化；如果校验期间撤销，本次文件补偿删除。已接受作答的幂等重传仍返回原回执。
- 任务列表最多返回最近 50 项（接口上限 100），学生先按本人筛选再限制条数。学生首页每 20 秒更新，教师进度每 10 秒更新。移出课堂的学生不能继续进入原课堂任务。

### English

Teachers can save feedback and a focus mark on an individual recording, independently of AI advice and scores. Students review it with their results; both attempt and plan responses hide teacher feedback while an exam is active. Version checks prevent overwriting another page's edits. Failed saves keep the text for retry.

Targeted practice copies selected items from the **original publication snapshot** into a separate, fixed-recipient task. This differs from history reuse in the composer, which uses current question-bank content. Original scores, exam clocks and the classroom's current publication stay unchanged. Each recipient continues one follow-up session across days; task items cannot be exchanged for unrelated questions. Progress uses the latest attempt per item.

A current exam cannot be used for follow-up practice. Recipients must also finish any still-running earlier exam before receiving its items. Withdrawing a task keeps existing records but blocks new starts and submissions, including cancellation during audio validation. Students see only their own tasks and progress; filtering happens before the list limit.

## 课堂教学闭环增强（2026-10-17）

- 实时状态：学生首页及口语作答页每 30 秒上报进入/练习/录音/上传状态，切换状态立即上报，后台页停止心跳。教师结果页每 5 秒读取；90 秒后标为「暂无近期状态」，不推断离线。设备自检有效期为 2 小时；既有异常面板继续展示上传、播放及评分问题。
- 课前自检：学生首页试录 5 秒，录音只在本页内存中回放，不上传、不开考。回放结束后由学生确认听清，并读取课堂版本接口验证连接，再向本课堂老师上报通过/失败。页面离开释放麦克风与对象 URL。
- 诊断补练：在现有补练对话框按低于 70 的参考分、少于 15 词的问答、指定内容词漏读或教师重点筛选。只看今日当前发布的每人每题最近一次作答；评分中/失败不匹配，当前考试禁止筛选。筛选只预填学生与原题，核对后点击发布才创建任务。少词/漏词均是转写层面的教学提示，不是发音或能力判定；诊断按每位学生匹配原题，预览中可逐人调整；关闭逐人模式时才使用共同题目。
- 题库复用：沿用现有全校可读、原作者可改的共享规则，新增篇目、独立复述句、问答与说明的复制。副本归当前教师，保存 `copied_from_id`；篇目同时深拷贝复述句与考试设置，独立复制复述句解除原篇目绑定。原题、历史快照和作答不变。标准音文件沿用引用，不复制实体文件；未来增加内容音频清理前必须处理共享引用。
- 教师复核：在现有乐观锁点评中增加已复核、转写有误、建议不适用标记。学生结果与回看中和教师点评一起显示，考试反馈遮罩同时隐藏复核标记；原始模型转写、建议与参考分不修改。
- 匿名讲评：教师结果页选择匿名编号的已出分作答，投屏回放、查看题面和转写并记录亮点/建议。考试只允许选择已交卷学生的作答。姓名不显示，但声音或回答内容仍可能暴露身份；讲评笔记按发布练习和作答持久保存，仅课堂授权教师可见，可从学生结果或发布历史重新打开；不写入教师点评或学生档案。
- 重练对比：普通练习结果页打开录音详情后，可对比同会话同题的首次与最近一次已出分作答，含录音、转写、参考分及建议。不足两次时提示再练。服务端拒绝所有考试的对比请求，不能跨学生、跨会话或跨题读取。
- 阶段报告：学生「我的成长」与教师「进步轨迹」新增最近 7/30/90 天报告；教师可按发布练习筛选。按课堂时区的练习日筛选会话，再统计期间作答；每题按最近提交状态计完成，评分中/失败不算完成，开口时长包含期间全部提交。跟读和问答均分分别计算，最多展示 6 条近期代表性已出分录音（优先有教师点评/复核的作答）。未结束考试全部排除，支持浏览器打印/保存 PDF；没有数据不生成分数或伪造个性化结论。

### English

Teachers can inspect short-lived classroom activity and device-check results, select follow-up recipients from current-practice diagnostics, copy shared question-bank content into their own editable versions, review AI feedback, and discuss anonymous answer examples. Diagnostic selection always requires a final review and explicit assignment. Device tests retain recordings in browser memory only and never start exams. Classroom activity is self-reported, not proof of attendance or connectivity.

Students can compare their first and latest scored answers to the same regular-practice item within one session. Students and authorized teachers can open a 7/30/90-day learning report, with separate reading/repeat and Q&A averages and selected recordings/teacher feedback. Teachers can filter by publication. Unfinished exams are excluded; original scores and published snapshots remain unchanged. Discussion notes last only for the current page. Browser printing targets the report.


## P1 讲评、逐人补练与课堂消息（2026-10-17）

- 讲评共用版本号，保存冲突返回 409，保留本地输入后由老师重新加载；关闭、切换示例及教师页面离开时保护未保存编辑。课堂小结先存私有草稿，再明确发布；继续改草稿不覆盖已发布版本，教师可撤回。学生只看到已发布的班级小结，不接收私有讲评笔记；考试未结束的反馈继续遮罩。
- 逐人补练预览每个学生的原题组合，相同组合合成一份固定名单任务。一次发布在单事务完成，任何组校验失败均回滚；客户端请求 ID 绑定来源、标题和逐人题单，重试返回原任务，换载荷返回 409。保留共同题目模式。
- 学生从首页或学习消息举手求助，选择操作、设备、题意等类型并可补充说明；每人同时一条待处理请求，可主动撤回。教师在学生结果面板查看、标记已查看或已处理；学生能看到处理状态。
- 教师明确选人发送站内提醒，可快捷选择有未提交题目的学生。学生主动点“我已阅读”才记已读；教师不能代为确认。提醒不是练习完成标记，求助和提醒不改变考试计时。消息只在当前课堂成员及所属教师之间可见，发送重试不重复写入。
