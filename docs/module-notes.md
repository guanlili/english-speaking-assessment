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

## 课堂教学闭环（2026-10-17）

- `class_teaching_tools.py`：学生自报状态与教师实时名单、诊断补练接收者筛选、权限隔离的阶段报告；`admin_content_copy.py`：四类题目复制；`attempts.py`：普通练习首末次对比与教师复核标签。
- 数据迁移 `b3d01b77c78a`：学生近期课堂状态 JSON、作答复核标签 JSON、四类题库内容的来源 UUID，全部可空，不回填历史。
- 前端：`ClassroomLiveStatus`、`DevicePreflight`、`LessonReview`、`LearningReportCard`、`AttemptComparison`；补练对话框与点评编辑器复用既有发布/版本控制。
- 功能口径、隐私边界与使用入口见 `docs/teacher-platform-design.md`「课堂教学闭环增强」。

- 补练列表支持 `status=active|history|all`、`offset`、`limit`（1–100）。先按固定接收者及最新作答筛选，再按创建时间与 ID 倒序分页；学生待完成只看本人，教师待完成看任一接收者，评分失败仍属待完成。两端默认待完成，每页 10 条，历史独立分页。
- 汇总反馈走 `POST /attempts/batch-read`（1–100 个 ID，去重保序），整批通过课堂归属检查后返回；越权或缺失不返回部分结果。前端处理中每 3 秒批量刷新，并同步逐题详情缓存；学生单条接口的考试遮罩不变。

## 题库复制与录音草稿保护（2026-10-16）

- P2 提供篇目、复述句、情景主题、单题和说明的 `POST /admin/{kind}/{id}/copy`；域逻辑在 `services/content_copy.py`。篇目连同旧子篇和复述句复制，主题连同全部问法复制；单句成为独立句，单题留在共享主题。JSON 设置深拷贝，标准音与考试音频引用保留，不改原题、发布快照或成绩。
- 复制归属沿用 P1：教师副本归本人，管理员副本为公共内容。仍全校可见，不引入私有库或共享开关；篇目 slug 和主题名称自动去重。前端复制后直接进入副本编辑，说明副本追加到当前草稿、不替换原有选择。
- 录音上传成功只清理同账号、课堂、会话、题型、题目下的草稿；同目标保存与清理串行，避免慢保存重新留下已上传草稿。补练撤销后，落盘完成可返回首页；存储失败则明确确认丢失后才能离开，普通断网重传保护不变。


## P1 教学闭环（2026-10-17）

- 新表 `ClassroomReview`（发布级私有笔记/小结草稿/公开副本/版本）、`FollowupBatch`（逐人补练原子幂等回执）、`ClassroomMessage`（求助、提醒、已读与处理时间）。迁移 `d7d796c9ed2a`，删除课堂级联清理。
- `class_reviews.py` / `services/classroom_review.py`：教师私有 GET/PUT、显式发布/撤回；学生 `/review-summaries` 先过滤活动考试及个人仍锁定的考试，再分页。笔记校验作答属于同一发布，考试期间禁止讲评该学生未交卷作答。
- `teaching_actions.py`：逐人题单按集合分组，调用 `create_followup(commit=False)`，全部校验通过后一次提交；课堂锁保护版本与重试，原发布快照不变。诊断接口额外返回逐人 `targets`，保留旧并集字段。
- `class_messages.py` / `services/classroom_messages.py`：学生求助序列化，提醒按发送请求 ID 去重；教师仅能查看/处理求助，学生仅能撤回本人求助、确认本人提醒。待处理求助与未读提醒在学生查询中优先，教师列表先筛当前成员再分页。
- 前端 `ClassReviewEditor` / `LessonReview` / `ExerciseHistory` 支持持续讲评；`FollowupManager` 支持逐人预览。`ClassroomContactPanel` 为教师收发入口，`StudentClassroomInbox` 在首页及学习消息可用，`PublishedClassSummaries` 在首页显示公开小结。全部通过生成客户端调用。

## 补练效果与消息处理闭环（2026-10-18）

- `class_followup_outcomes.py` / `services/followup_outcomes.py` 提供教师专用补练效果，来源与补练会话按课堂/发布/学生/题目隔离，SQL 窗口函数选最新作答，原作答额外限定提交时间不晚于补练发布。来源为活动考试时拒绝，个人考试反馈仍锁定时隐藏原作答。仅同引擎完成记录计算参考分差。
- `ClassroomMessage` 新增可空 `reply_text/replied_at/due_at/reminder_of` 和默认 0 的 `reply_revision`，迁移 `dbc789e98708`；旧消息语义不变。`class_messages.py` 新增 PUT 求助答复和 POST `/reminders/{id}/repeat`；保留旧标记已处理接口。
- 再次提醒按课堂→消息的锁顺序串行，绑定原始提醒链，重复请求返回原记录；同链 60 秒冷却。已读确认也按课堂→消息顺序锁定并同步同链已读，不伪造任务完成。截止时间创建时必须含时区且晚于服务端当前时间；重试与重复提醒保留原截止时间。
- 前端 `FollowupOutcomesDialog` 使用生成客户端按 10 人分页查看证据，可进入 `AttemptFeedbackDialog` 点评，关闭详情后刷新效果。`HelpReplyEditor` 提供带版本答复；`ClassroomContactPanel` 增加历史/未读筛选、截止时间和重复提醒。教师课堂页集中待办，其他工具默认折叠但保留发布操作入口。

## 学生任务入口精简与逐题补练（2026-10-18）

- 学生首页改为「今日任务」，一张卡片集中展示当前练习/考试、题型摘要、完成进度和开始/继续入口；课后作业、指定补练、求助与提醒、公开课堂小结仍可直接使用。移除首页周目标、XP/连续天数、表达累计、每日金句及主题推荐，首页不再请求学习路径和成长轨迹。成长数据仍可在「我的成长」查看。
- 学生手机主导航为「今日任务 / 词汇学习 / 我的成长」；删除重复的「今日练习」导航，口语与考试作答页高亮今日任务。考试从当前任务卡进入，原考试路由与服务器计时不变。自主练习的首页快捷入口在无题单或普通练习完成后出现；考试需已结束。主题探索仍可从次级导航进入。
- 首页和学习消息按每题最近一次作答的 `done` 状态统计完成，题目说明不计数，评分失败不显示为已完成。设备自检通过后在当前页面收为简短提示，仍可重新检查；同步失败保留完整操作区。
- 教师展开当前普通练习的学生逐题结果，可直接「查看与点评」或「补练这题」。补练复用原有创建对话框，预选该学生与该题，等待核对与明确发布；更换来源练习后沿用原有选题逻辑。当前考试不提供逐题补练快捷按钮，后端考试边界保持不变。

## 首页空态与近期设备自检（2026-10-18）

- 学生补练待完成第一页成功加载且无任务时，仅显示一行状态与历史入口；历史、加载错误及重试仍可访问。补练只有存在前后页时才显示分页；后台更新发现新补练后恢复完整任务列表。公开课堂小结在第一页成功加载且无数据时隐藏，加载中或失败仍显示状态/重试。
- 学生求助表单默认折叠，展开后才显示类型、说明和发送按钮；折叠不清空编辑。当前求助、教师答复和提醒保持直接展示，不自动标已读或处理完成。
- `lib/device-preflight.ts` 在当前标签页的 sessionStorage 中按账号 ID、学生 ID、课堂码隔离存储通过时间，不存 token、录音或正文；缺少身份、存储不可用时不缓存，仍可正常自检。试录、回放确认、连接检查和向老师上报全部成功后才写入通过时间。
- 通过结果最多保留两小时，与服务端设备自检 TTL 一致；读取不续期，也不重新上报 passed，避免延长老师端有效期。页面内到期、返回可见时过期、设备变化或主动重查会失效。重新检查立即清除旧通过记录；上报失败保留试录及重试入口。账号变化/组件卸载后的迟到响应不更新状态或写入缓存。
- 窄屏顶部保留 Logo 与工具按钮，页面标题对读屏保留、视觉上从 sm 起展示；重复课堂标识从 lg 起显示，避免手机与 iPad 竖屏上标题和工具区重叠。

## 题库查重预计算与补练查询量级验证（2026-10-20）

- 导入查重匹配键预计算：Passage（title/text）、Unit（title）、Scenario（topic）、ScenarioQuestion/RepeatSentence/Instruction（text）六表七列加 `dedup_*_hash`（归一键 sha256，可空+索引）。归一化函数单一事实源在 `services/content_dedup.py`（NFKC + strip + casefold + 空白折叠），`before_flush` 会话级钩子维护所有 ORM 写入路径（CRUD/复制/导入/AI 出题/种子），`question_bank_io._matching_ids` 优先哈希索引、NULL 行回退流式归一（迁移前残留兜底）。casefold/Unicode 空白无法在 SQL 精确复刻，故不用数据库生成列；迁移 `a3f8c1d90e42` 内冻结归一函数回填存量。基准（3000 篇 3KB 正文）：全表流式 634ms → 哈希索引 2.4ms。
- 补练列表未完成判定（PR#167 改写的量级验证，合成数据 1 课堂）：600 任务 × 40 学生 × 6 题全部完成（history 视图最坏情况，144k 作答）时，旧实现（每 (target,item) 对一次相关 LIMIT-1）墙钟 8.8s / 1.30M buffer 命中 / 144,000 次子计划执行；新实现（全班一次 DISTINCT ON + 逐对小 EXISTS）4.4s / 0.24M。小规模（150 任务）两者墙钟接近但 buffers 差 5.3 倍——全内存命中时 jsonb 展开是共同主成本，buffer 差异在真实缓存压力下才是决定项。结论：随任务×学生×题规模扩大，新实现优势线性放大，PR#167 改写方向正确。

## 平台更新日志（2026-10-26）

管理员在界面上发布平台更新，教师与管理员可见（学生端不设入口）。

- **后端** `models.ChangelogEntry`（`day` 面向读者的发布日期 + `kind: feature/improvement/fix/null` + 标题正文各中英）；路由 `api/routes/changelog.py`：`GET /changelog`（TeacherUserDep，按 day/created_at 倒序）、POST/PUT/DELETE 均为 SuperUserDep。PUT 是全量更新（kind 传 null 清标签）。
- **前端** `_layout/changelog.tsx` 时间线页（管理员多出发布/编辑/删除）；侧栏「平台更新」入口带未读红点——`hooks/useChangelog.ts` 用 localStorage 水位 `esa:changelog-seen`（存最近看过的最新条目日期）对比列表首条 `day`；进入页面即视为已读，红点在侧栏下次渲染时消失。queryKey `["changelog"]` 侧栏与页面共享。
- **注意**：字段名用 `day` 不用 `date`（与类型注解同名会让 pydantic 报 unevaluable-type）。

## 口语原音频 ZIP（2026-10-27）

学生导出自己的原始录音、教师导出本班录音。同一迭代，只出 ZIP + 根目录 `manifest.csv`（UTF-8 BOM）。不转码、不进 COS/S3、不用 Redis/Celery。与管理员用量 CSV（`admin_export.py`）无关，那条行为不要改。

- **迁移** `e8a1c4b90d27`（revises `1f4592d70e43`）：表 `export_job`、`export_audit`。任务创建时把筛选条件冻进 `filter_json`，worker 只读这份快照。
- **接口** `api/routes/exports.py`：`POST /exports` 一律异步返回 `job_id`（H2，不走同步小包）；`GET /exports` 只列请求人自己的任务（含 `unseen_ready`）；`GET /exports/{id}` 请求人或超管可读；`GET /exports/{id}/download` 成功且未过期时流式下载，过期 410 并删文件；`POST /exports/{id}/retry` 只重试 `failed`。教师 `scope=classroom` 必须 `confirm_contains_student_audio=true`，且 `crud.classroom_teacher_allowed`（课堂 `owner_id` 或超管）；跨班 403。学生只能 `scope=self`。进行中任务每人上限 `EXPORT_MAX_IN_PROGRESS`（默认 2）→ 429 `export_too_many_in_progress`。
- **范围**：排除 `queued`/`scoring`；`done`/`failed` 且磁盘上有原文件才打进包。`audio_purged_at`、缺文件、或 `*.playback.wav` 记 `missing=1` 并继续；全部缺失或零条匹配 → 任务 `failed`（`export_all_missing` / `export_empty`），不写空 ZIP。预估体积 > `EXPORT_MAX_BYTES`（默认 2GiB）在入队前 422 `export_too_large`。教师未传起止日期时默认最近 `EXPORT_RECENT_DAYS_DEFAULT`（7）天。显式范围只填一端，或长于 90 天再加当天结束时刻（`23:59:59`），返回 422 `export_range_too_wide`。日期控件选满 90 天（结束日含当天）可以提交。学生自己的导出不套 90 天窗。
- **包结构**：前缀 `SpeakUp_`。学生 `SpeakUp_我的录音_{stamp}/` 下按练习或日期分目录；教师默认 `group_by_item` 按题目分目录，文件名用学生姓名或学号。根目录必有 `manifest.csv`。`zip_path` 相对根目录，与包内条目一致。原字节、原后缀，`ZIP_STORED`。文件名清洗；重名追加 attempt id 前 8 位。
- **Worker** `app/exporting/worker.py`：独立 `ThreadPoolExecutor`，`EXPORT_WORKERS` 钳在 1–2，**不读** `SCORING_WORKERS`。领取用 `FOR UPDATE SKIP LOCKED`。进程重启时把 `running` 打回 `queued` 再提交。每小时清扫已过 `expires_at` 的成功包（`EXPORT_TTL_DAYS`，默认 7）。审计动作 create/start/success/fail/download/retry/expire/reject，另有 `app.export` 结构化日志。意外异常记 `export_failed: …` 并 `logger.exception`，不吞掉。
- **存储**：`EXPORT_STORAGE_DIR`（容器内 `/app/export`），compose 卷 `app-export-data`，与 `app-audio-data` 分开。磁盘文件名是 `{job_id}.zip`，下载名是 `download_name`。API 不返回绝对路径。
- **前端**：教师/管理员 `/exports`（侧栏「录音导出」，未下载成功包显示角标）；学生不进 `_layout`，入口是 `/my-exports`（班级页与学生壳账号菜单）。教师提交前二次确认勾选。文案走 `useI18n`；`detail` 稳定码在 `utils.ts` 的 `DETAIL_MESSAGES` 与 `lib/export-copy.ts` 映射。下载用带 Authorization 的 fetch（生成客户端的 download 返回 unknown）。完成/失败用列表刷新 + toast，无新推送或邮件。
- **配置**：`EXPORT_STORAGE_DIR`、`EXPORT_TTL_DAYS`、`EXPORT_WORKERS`、`EXPORT_MAX_IN_PROGRESS`、`EXPORT_RECENT_DAYS_DEFAULT`、`EXPORT_RECENT_DAYS_MAX`、`EXPORT_MAX_BYTES`、`EXPORT_ASYNC_MIN_FILES`、`EXPORT_ASYNC_MIN_BYTES`。后两个阈值保留为配置，当前没有同步路径。`.env.example` 与 `scripts/generate-deploy-env.sh` 写出 `EXPORT_STORAGE_DIR` / `EXPORT_TTL_DAYS`。
