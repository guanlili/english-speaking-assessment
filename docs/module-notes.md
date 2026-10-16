# 模块实现备忘

> 2026-10-16 从 CLAUDE.md 迁出：各功能模块的实现细节、关键路径与迁移号。CLAUDE.md 只保留跨模块的规则与不变量；改动某个模块前先读本文对应章节。新模块上线时在这里追加一节，并在 CLAUDE.md「模块索引」加一行。

## 课堂练习主链路

- 激励层（P1，`app/scoring/gamification.py`）：星级（均分 ≥85→3/≥70→2/完成 1）、XP（题×10+星×5+连胜≥3 奖 10）、连胜、5 枚徽章；结算幂等挂在 /today；只和自己比（学生端无排名，老师面板可看 XP/连胜）。
- 学习路径（P2）：Unit 表 + Passage.unit_id + Classroom.unlock_all（顺序解锁默认开，老师可全开）；/classes/{code}/path；今日篇目=路径上第一个未完成单元（无单元数据回退全局第一篇）。原 /map/:code 关卡地图页与 MVP 演示页 /practice 已删除（2026-09 精简）。
- AI 出题（P3，`app/scoring/ark_client.py` + `question_gen.py`）：chat/completions 公共客户端；/admin/scenarios/{id}/questions/generate 只出草稿不入库（老师审改后采纳）；自动拆句 /admin/passages/{id}/sentences/auto-split（本地算法幂等）；无密钥 503。
- 模拟分（`app/scoring/rubric.py`）：rubric 四维 0-4 映射 0-9（`RUBRIC_TO_SCORE` 表）；LLM 失败降级不出假分，界面显示「建议暂缺」；仅 `SCORING_PROVIDER=ark` 时启用（`ARK_RUBRIC_MODEL` 配置模型）。
- 词汇分析（worker 内 `_analyze_vocab`）：问答作答评分后写入 `attempt.vocab`；只统计问答转写（跟读参考文本不算）；词元匹配支持规则屈折。2026-10-06 起老词表（A2/B1/B2）退役，2026-10-07 整表删除（wordlist_entry 已 drop）：新作答只产出五级 level_stats（未导入五级数据时 vocab 为 null）；历史 attempt 中的旧口径 JSON 原样保留展示（不回填不重算）。
- 40 人并发已验证（BDD B）：测试 `test_board.py::test_classroom_40_concurrent_submissions` 用真实线程池跑 40 并发上传 → 全部出分 → board 到齐。
- **发布快照体系（2026-09-29，`app/services/exercise.py`）**：老师发布（按题选题）生成不可变 `ClassroomExercise`（snapshot_items 深拷贝题目内容、version_no 递增、可命名标题），学生 daily 会话绑 `assignment_id` 后始终按快照出题；作答提交时再存 `attempt.item_snapshot`，worker 评分只读快照——题库编辑不影响已发布练习与历史解释。恢复自主练习会归档练习并解绑当日会话。旧指派路径（单元指派/按题引用）仅作兼容读取，重新发布即转快照；学生历史结果按「发布历史」Tab（`/classes/{code}/exercises/{id}/results`）按当时题单解释。
- **题型互相独立（说明为第四题型，2026-10-08）**：题目说明（`instruction`）是纯文字引导页，组卷时穿插题与题之间（默认排最前），学生点「继续」进入下一题；无作答、不进结算分母，模考中占计时窗口（秒数=suggested_seconds，可提前继续，到时自动翻页），教师面板显示已读状态；说明存 `instruction` 表可复用，确认记录在 `instruction_ack`（`POST /classes/{code}/acks`）。
- **三题型互相独立（2026-09-29）**：文章朗读（未拆分整篇一道题；拆分文章按句出题，见「朗读题库树」）/ 听句复述（独立句库 `SentenceLibrary`，可不挂篇目；从篇目自动生成时只取 3 句）/ 情景问答（按主题整组，**不分级**——band 字段仅存量兼容，抽题与发布不看档位）。课堂发布 = 三类各选内容写快照，操作条三端统一（编辑→标准音→删除）。
- 朗读拆句时长：`Passage.reading_sentence_seconds` 按正文拆句顺序保存逐句秒数（1–180，null 自动估算）。题库逐句保存，组卷预览显示自定义时长；统一展开算法供发布/今日题单/作答兜底使用，发布后快照冻结。正文拆句结果变化时清空配置，避免错句；仅调整标题等信息保留配置。迁移 `c100e2d8ff20`。
- **朗读题库树（2026-10-08）**：`Passage.reading_split` 启用逐句拆分，`/admin/passages/{id}/split` 不创建独立篇目、不停用原文章，`DELETE` 同路径取消拆分。组卷勾选整篇文章；拆分文章在发布快照/学生题单层按句展开成逐句朗读题（`app/services/reading.py`：uuid5(passage_id, 句序) 确定性合成 ID，快照携带 parent_id/句序，不建篇目行；作答限时优先使用逐句配置（1–180 秒），未配置则按句长自动估算 4–30 秒；指派镜像与 practice_session 锚点仍存真实篇目 ID；展开后超 100 题拒发）。旧版按段/按句拆出的篇目经完整且唯一的标题/正文/主题/单元匹配归入 `parent_passage_id`，保留原 ID 和发布快照，重新组卷时归回原文章。
- **学生账号密码（2026-09-29 决策）**：默认密码统一 `brs123456`，导入/重置/批量重置均用它且**不强制改密**（学生侧边栏有自愿修改入口）；随机初始密码与 CSV 导出已下线。

## 五级词库（2026-10-03 起，口语与背单词共用分级数据源）

KET → PET → 学术词汇 → 四级词汇 → 雅思&托福词汇，固定顺序（`VOCAB_LEVEL_ORDER`），同词多级时**实际难度取最早（最易）一级**。表 `vocab_level_entry`：同形异义按 (headword, level, sense_no) 各占一行；来源标签存 `sources` JSON（KET 跨天/学术双文件/雅思场景分别保留）；`is_phrase` 标记词组（口语逐词命中暂不计入）；`needs_review` 标记 OCR 待核对行（核对后才计入分级）。

- **导入**：管理端 `/admin/vocablevels`（预览→确认，单事务回滚；无效/批内重复/跨级冲突提示）+ 本地提取工具 `backend/scripts/vocab_level_import/`（学校资料清洗，**原始教材与完整提取词表不入仓库**，质量报告见 `docs/five-level-vocab-quality-report.md`；未确认线上使用授权前不得导入生产库）。
- **两模块同源**：背单词教师选词按 `level` 过滤（`/vocabulary/words?level=`、词库详情 `?level=`，词条带 `level`/`all_levels`）；口语问答评分在 attempt.vocab 新增独立 `level_stats`（用词来源级别），与旧 A2/B1/B2 命中口径并存、互不改写。
- **历史不漂移**：五级导入只新增分级行；已发布任务快照与历史 attempt.vocab 一律不回填、不重算；needs_review 行不参与两模块统计。

## 分级题型训练（2026-10-03 起，PR A：题库与练习流程）

考试式题型 × 共享五级，**两维分别建模**（`exam_kind` 与 `exam_level` 两个独立可空列），复用既有两表：`RepeatSentence`（`toefl_lnr`＝TOEFL Listen and Repeat）与 `ScenarioQuestion`（`interview`＝Take an Interview、`ielts_p1/p2/p3`）。KET/PET 为课堂版本：语言难度与作答要求靠内容本身承担（更短秒数、更简文本），无需单独题型值。

- **IELTS Part 2**：`cue_card_bullets`（话题卡要点 JSON）+ `prep_seconds`（准备时间 10–180s）；`suggested_seconds` 考试题上限 300（普通问法仍 ≤60，由 `validate_question_suggested_seconds` 按题型把关）。
- **旧数据不漂移**：两列为 NULL 的题目含义与流程完全不变；发布快照深拷贝考试字段（`exercise.build_snapshot_item`），已发布任务与历史作答不随题库改动重解释。
- **发布**：走既有 `PUT /classes/{code}/assignment`（items 选 id → 快照），学生 today 经 `PlanItem.exam_kind/exam_level/cue_card_bullets/prep_seconds` 透传。
- **前端**：练习页题型徽标（`EXAM_KIND_LABELS`）+ Part 2 话题卡与准备倒计时（录音门禁，可跳过）+ 免责声明「课堂练习反馈，非官方考试成绩」；题目库编辑表单加题型/级别/话题卡字段；发布面板条目带题型/级别徽标。
- **PR B（已上线，`f8f9372`）**：句型推荐（`SentenceFrame`：按级别与表达用途分类的可替换句型，管理端 `/admin/sentenceframes`）+ 学生单条收藏（`StudentFrameFavorite` 挂课堂档案，跨设备；`/classes/{code}/frame-favorites`）；练习页组件 `Practice/SentenceFrames.tsx`。

## 背单词模块（2026-10-01 起，P0 已上线）

独立「词汇学习」模块（设计文档 `docs/vocabulary-module-design.md`），与口语分析用的 `WordlistEntry` 完全分离，沿用现有账号/课堂/学生档案：

- **数据模型**：`VocabularyWord`（词条：拼写/词性/中英释义/可接受拼写）→ `VocabularyBook`（public=管理员维护 / classroom=本班教师自建）→ `VocabularyBookItem`；发布走 `VocabularyAssignment`（snapshot_items 深拷贝 + version_no）+ `VocabularyAssignmentTarget`（发布时固定名单，完成率分母不漂移）；作答 `VocabularySession`/`VocabularyAnswer`（幂等键唯一，练习重试 attempt_no 递增）。
- **判分**（`app/services/vocabulary.py`）：NFKC + 首尾空白 + casefold 规范化；只认快照拼写与显式 `accepted_spellings` 变体（**只收英美拼写变体，不收同义词**），不自动放宽复数/连字符。统计与错词本一律看**首答**；未答题不向学生端泄露拼写。
- **边界规则**：发布词单受可见性约束（公共库或本人班级库，word_ids 逐词核验归属，管理员不限）；`due_at` 以服务器时间强制（过期开会话/作答均 422）；幂等键绑定会话+题号（跨题复用 422）；纯听音任务要求全部词有标准音（发布 422），无标准音且未作答的词自动回落看义拼词。
- **API**：`app/api/routes/vocabulary.py`（`/vocabulary/books…` 词库 CRUD + CSV 导入预览；`/classes/{code}/vocabulary/…` 发布/结果/学生任务/错词本；`/vocabulary/sessions/{id}/answers` 作答）。域逻辑在 services，路由只做权限。
- **前端**：学生端 `/vocab/$code`（任务首页 + `/practice` 拼写练习 + 错词本），手机底部导航为「首页/口语/词汇/成长」；教师端 `/t/$code/vocab`（选词发布 + 完成情况），课堂面板可切换口语/词汇；管理端 `/admin/vocabbooks`（公共词库 CSV 导入预览）。无标准音的词练习用浏览器朗读兜底并标注「设备合成语音」。
- 测试 `tests/api/routes/test_vocabulary.py`（权限/快照/判分/幂等/名单/统计）；响应式 e2e 覆盖词汇两页三档宽度。

## 通用功能 G01–G05（2026-10-11）

- 学生练习 `/p/{code}`、考试 `/exam/{code}` 各有独立入口与结果路由；共享录音/反馈组件，旧练习链接遇考试自动转考试模块。当前课堂发布仍沿用单一活动快照。
- 学生「我的成长」按会话回看练习/考试；教师学生详情页通过 `/classes/{code}/students/{student_id}/sessions` 回看所有轮次（包含自主练习），逐题详情走提交时快照，考试反馈遮罩保持不变。
- 题目说明保留阅读确认及考试计时窗口，不计入题量、进度条、完成分母，也不进入学生最终反馈和教师发布历史结果；实时教师面板仍显示说明已读状态。

## 模考模式（2026-10-01 起）

发布练习时可开启「模考」（`is_exam` + `time_limit_minutes` 5–240）：

- **限时以服务器时间为准**：学生在确认页点击开始考试才落 `exam_started_at`；到时任何读写触碰会话都会惰性落 `exam_ended_at`（= 自动交卷），此后提交一律 422。
- **逐题顺序计时（2026-10-08）**：题目出现后开始计时（IELTS Part 2 先计准备时间，模考不能跳过准备）。服务器从开考时间、发布快照和首次提交时间恢复题序；到时未答题自动跳过，刷新不重置。录音上传成功即推进，不等待评分；到时录音自动结束并提交，上一题仅留 15 秒音频传输窗口，不重置下一题时间。最后一题结束即进入结果页。
- **每题一次作答**：考试会话内同题第二个作答 422（幂等键重传不受影响，断网重试安全）。
- **防切屏**：前端 `visibilitychange` 上报 `POST /classes/{code}/exam/violation`，计数入 `practice_session.tab_switch_count`（封顶 999），教师面板与发布历史可见。
- 考试中禁换题（next-question 422）、不展示逐题反馈（分数在结果页统一看）、题面 `select-none`。
- 模考结果页保留录音回放，移除重练、换题和返回该考试重答的入口；考试进行中不能提前查看结果。普通练习保留原有重练入口。
- 实现在 `app/services/exam.py`（域逻辑）+ `attempts.py`（作答门禁）+ 练习页考试态 UI。测试 `tests/api/routes/test_exam.py`。

### 课堂删除（2026-10-08）

教师/管理员确认删除后，客户端以 `DELETE /classes/{code}?delete_history=true` 清理该课堂、归档成员、口语/词汇会话及发布历史，保留学生账号与其他课堂。未确认清理历史的 API 调用仍保留有作答的课堂（409）。移出名单只解除账号绑定，历史仍归本课堂；停用课堂也可删除。先删会话再删发布，避免外键 SET NULL 引起日常会话唯一键冲突；queued/scoring 作答未结束时暂不允许删除。

## 自动考试流程 E01–E10（2026-10-11）

- 教师题库及组卷排序行的「考试流程设置」按题保存等待、准备、录音前缓冲时间；说明、复述和问答支持上传考试播放音频。发布页面的新考试传 `automated_exam=true`，将配置和音频地址冻结到 `snapshot_items.exam_flow`。旧发布没有该字段，继续使用原计时流程。
- 新发布的自动考试要求说明、复述、问答具备音频（考试配置覆盖音频优先，否则使用题库标准音频）。首次开考前加载检查全部题干音频；旧快照缺音频时先测试浏览器朗读，失败不启动新考试。已开考退出后服务器计时继续。同步重试始终携带最初的会话、题目和事件。
- 自动考试使用独立 `AutomatedExamSession`。说明等待后播放；朗读等待后提示音、录音；复述播放后缓冲再录音；问答播放后准备、缓冲再录音。说明播完、真实题作答时间结束后才显示「下一题」。上传完成不自动切题。进度按三种真实题型分组；问答笔记按账号、会话、题目保存在本机。
- 录音就绪以 `MediaRecorder.onstart` 为准；自动考试设备检查保留麦克风流，进入作答时复用，启动事件后才提示作答和播放提示音，离开页面释放。回放对浏览器流式容器缓存 WAV 副本，原录音保留，副本随原录音过期清理。
- 学生首次开始/返回时点击一次设备检查，允许声音和麦克风；后续题目自动推进阶段。媒体元素复用，设备检查点击中解锁音频，播放失败提供恢复入口，不把失败视作播放完成。
- `POST /classes/{code}/exam/flow` 保存实际音频结束及下一题事件；阶段时间由 `exam_flow_state` 的服务器时间恢复。退出/刷新不暂停整场、等待、准备或作答计时；返回音频阶段会重播当前题干。重复开考/事件不重置时钟。
- 本机按账号和课堂保存当前考试会话，返回仍读取原发布快照。录音中每秒暂存已产生的音频块，正常退出先结束录音并保存/上传；断网录音保留原幂等键供重传。突然关闭时只能恢复已经成功落盘的音频块，浏览器拒绝存储会明确提示。IndexedDB 使用 ArrayBuffer 存储并兼容旧 Blob 草稿。
- 当前题的保留录音可在整场截止前重传；点下一题后仅留 15 秒传输窗口。整场到时始终拒绝新提交，历史只读结束判定也检查整场截止。
- 数据迁移 `dc44acace33b` 为四类题库增加 `exam_settings`，为会话增加 `exam_flow_state`。服务端测试 `test_exam_flow.py`，浏览器回归 `exam-automated.spec.ts`。

## Actions E2E 分层与并行（2026-10-13）

- `chromium` 项目运行真实后端用例，单 worker，CI 单独启动完整 Docker 栈及独立数据库。新测试文件默认进入该项目，确认所有 API 都被模拟且没有共享状态后，才加入 `frontend/playwright.config.ts` 的 `mockedFiles`。
- `chromium-mock` 运行已审核的模拟接口文件；`webkit` 保留所有 `@webkit` 标记用例（含不访问后端的登录页冒烟）。两个项目在 CI 拆成 2 个独立 runner 分片，每片 2 workers，不启动后端或数据库。
- 模拟接口任务先 `npm run build`，再设置 `E2E_MOCK_ONLY=true`；Playwright 自动启动生产构建预览（5177）和组件宿主（5176）。本地可运行 `E2E_MOCK_ONLY=true npx playwright test --project=chromium-mock --project=webkit --shard=1/2`（第二片用 `2/2`）。
- 模拟用例按测试粒度并行；真实音频回放文件保持文件内顺序，避免共用系统音频设备造成不稳定。新增模拟用例需保持每个测试独立，不共享可变状态。
- `E2E 冒烟（主干道）` 汇总检查只有在全部分片成功时通过，任一失败、取消或跳过均阻断部署。生产部署仍等待前端、后端和 E2E 汇总通过，不复用其他提交的检查结果。

## 运行时与题库加载优化（2026-10-15）

- 学生首页经 `useClassroomRevision` 每 5 秒检查 `/classes/{code}/revision`，仅发布版本变化时刷新 today/path；不替换正在作答的会话快照。
- 自动考试首次读取完整题单，后续 `/classes/{code}/exam/state` 只返回考试态和已提交题 ID。设备检查、阶段推进、草稿恢复、状态请求分别在 `useExamAudioDevice` / `useExamPhase` / `useExamDraftRecovery` / `useAutomatedExamState`；服务端仍是计时与作答门禁的唯一权威。
- 组卷四类题库以 20 条分页浏览，`POST /admin/composer-selection` 按引用恢复已发布、跨页选中和导入预选的详情；包含旧朗读子篇归根、问答主题反查与缺失 ID。搜索/翻页不清空选择；新接口只读，无表结构变更。
- 导入查重只流式扫描相关题型的匹配键，再加载命中候选；保留 Python 的 NFKC/casefold/Unicode 空白规范化，不用 SQL lower 近似替代。
- API 响应携带 `X-Request-ID`，评分线程继承请求上下文。metrics 仍是进程快照，实例/启动信息识别计数重置，历史查外部调用日志；见 `docs/runtime-observability.md`。E2E 失败保留 trace/截图/视频，组件宿主使用独立 Vite 缓存。

## 教师备课与异常闭环（2026-10-16）

- `ComposerDraft` 保存教师+课堂私有草稿；`class_composer.py` 负责读写与历史引用恢复，版本比较避免并发覆盖。发布携带 `draft_revision`，同一事务清理自己的草稿，失败回滚。迁移 `08033814b327` 同时新增会话设备异常枚举/上报时间。
- 历史复制先到草稿，不直接发布；保留选题与题序，逐题内容/音频/设置使用当前题库，预览确认后才生效。旧快照和成绩不变。
- `class_diagnostics.py` 只聚合今日当前发布的最新轮次/作答，设备自报 5 分钟失效，评分超过 120 秒单独提示；不推断未上报设备的在线状态。详见 `docs/teacher-platform-design.md`。

## 教师点评与指定补练（2026-10-16）

- 点评保存在 `Attempt.teacher_feedback/teacher_focus/teacher_feedback_author/teacher_feedback_at/teacher_feedback_revision`，写入口仅授权教师/管理员，版本冲突 409；不改 AI 评分。`AttemptPublic` 和 `PlanAttempt` 均透传，考试未结束时两条出口都遮罩。重点标记透传教师 `BoardItem`。
- 指定补练复用不可变 `ClassroomExercise`，状态 followup/followup_closed、固定 target_students、source_exercise_id；不写 classroom.current_exercise_id。学生会话 mode=followup，以 student+assignment 唯一，跨天幂等继续。题目来自原发布快照，不读当前题库，禁止换题。
- 仅课堂教师可选本班成员发布/撤销；学生只见本人目标。当前考试及接收者仍在进行的历史考试不能作为补练来源。撤销在上传预检、落盘后事务内复查，失败清理新文件。
- `class_followups.py` 负责入口，`services/followups.py` 负责边界；迁移 `b22ce1e19087`。详情与英文说明见 `docs/teacher-platform-design.md`。
- 补练列表支持 `status=active|history|all`、`offset`、`limit`（1–100）。先按固定接收者及最新作答筛选，再按创建时间与 ID 倒序分页；学生待完成只看本人，教师待完成看任一接收者，评分失败仍属待完成。两端默认待完成，每页 10 条，历史独立分页。
- 汇总反馈走 `POST /attempts/batch-read`（1–100 个 ID，去重保序），整批通过课堂归属检查后返回；越权或缺失不返回部分结果。前端处理中每 3 秒批量刷新，并同步逐题详情缓存；学生单条接口的考试遮罩不变。

## 题库复制与录音草稿保护（2026-10-16）

- P2 提供篇目、复述句、情景主题、单题和说明的 `POST /admin/{kind}/{id}/copy`；域逻辑在 `services/content_copy.py`。篇目连同旧子篇和复述句复制，主题连同全部问法复制；单句成为独立句，单题留在共享主题。JSON 设置深拷贝，标准音与考试音频引用保留，不改原题、发布快照或成绩。
- 复制归属沿用 P1：教师副本归本人，管理员副本为公共内容。仍全校可见，不引入私有库或共享开关；篇目 slug 和主题名称自动去重。前端复制后直接进入副本编辑，说明副本追加到当前草稿、不替换原有选择。
- 录音上传成功只清理同账号、课堂、会话、题型、题目下的草稿；同目标保存与清理串行，避免慢保存重新留下已上传草稿。补练撤销后，落盘完成可返回首页；存储失败则明确确认丢失后才能离开，普通断网重传保护不变。
