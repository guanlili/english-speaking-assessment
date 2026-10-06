# CLAUDE.md — 项目规范

> 本项目为「Charcoal 开口说」英语口语学习平台（视觉与交互参照 prototypes/speakup 原型），基于 lili-full-stack 模板创建。品牌 2026-10 由 SpeakUp 更名而来（Charcoal 为暂定名，规避与市面雅思口语平台重名）；品牌名统一定义在 `frontend/src/config.ts` 的 APP_NAME，改名只需动文案层，视觉素材（Logo 图形/插画）暂不重做。

## 业务上下文

- 需求来源：甲方 PRD《独立英语口语评测平台 v0.1》（2026-09-25，王府学校）。三阶段累计工期：2 天演示（周一 2026-09-28）→ 2 周（课堂码+问答）→ 3 周（词汇/CEFR/教师面板）。
- **产品定位（2026-09-26 与甲方对齐）：课堂教学工具**——老师在前面授课、全班电脑登录学生端同步练习；不是多邻国式自学产品。内容节奏由老师主导：老师面板「今日课堂指派」设定当前单元，全班 /today 即时同步；学生个人关卡路径仅作为课后自主练习的兜底。
- 当前阶段：**PRD 功能全部就绪 + 增强版（多邻国式激励层 + AI 出题）**——学生端全流程（US-04/05/06）+ 词汇分析（US-07）+ 模拟分骨架（US-08，ark 引擎下 LLM rubric 四维 + 0-9 映射 + 升级表达；mock 不出假分）+ 学生进步轨迹（US-09）+ 教师面板（US-10）+ 管理端内容管理（`/admin/passages|scenarios|wordlist|classrooms`：篇目与复述句、情景问法、词表 CSV 导入、课堂码生成/停用）。课堂支持教师自定义名称、年级/班型和教学目标；课堂难度由教师选择的内容决定，A2/B1/B2 仅作内部评分/词表元数据，不出现在课堂教学流程。内容标准音：TTS 生成（`app/scoring/tts.py`，需方舟密钥）或上传现成音频，回放走 `GET /audio/content/{name}`；无密钥时前端 speechSynthesis 兜底。模板 Items 已删除。演示重置：`bash scripts/reset-demo.sh`。
- 激励层（P1，`app/scoring/gamification.py`）：星级（均分 ≥85→3/≥70→2/完成 1）、XP（题×10+星×5+连胜≥3 奖 10）、连胜、5 枚徽章；结算幂等挂在 /today；只和自己比（学生端无排名，老师面板可看 XP/连胜）。
- 学习路径（P2）：Unit 表 + Passage.unit_id + Classroom.unlock_all（顺序解锁默认开，老师可全开）；/classes/{code}/path；今日篇目=路径上第一个未完成单元（无单元数据回退全局第一篇）。原 /map/:code 关卡地图页与 MVP 演示页 /practice 已删除（2026-09 精简）。
- AI 出题（P3，`app/scoring/ark_client.py` + `question_gen.py`）：chat/completions 公共客户端；/admin/scenarios/{id}/questions/generate 只出草稿不入库（老师审改后采纳）；自动拆句 /admin/passages/{id}/sentences/auto-split（本地算法幂等）；无密钥 503。
- 模拟分（`app/scoring/rubric.py`）：rubric 四维 0-4 映射 0-9（`RUBRIC_TO_SCORE` 表）；LLM 失败降级不出假分，界面显示「建议暂缺」；仅 `SCORING_PROVIDER=ark` 时启用（`ARK_RUBRIC_MODEL` 配置模型）。
- 词汇分析（`app/scoring/lexicon.py`）：问答作答评分后写入 `attempt.vocab`（命中分档词/覆盖率/CEFR 参考）；只统计问答转写（跟读参考文本不算）；词元匹配支持规则屈折；标签规则：最高稳定档（≥5 命中）即该档，否则降一档。2026-10-06 起老词表（A2/B1/B2）退役：新作答只产出五级 level_stats（未导入五级数据时 vocab 为 null）；历史 attempt 中的旧口径 JSON 原样保留展示（不回填不重算）；/admin/wordlist 导入已下线（410），仅只读历史统计；内置演示词表 ~600 词（A2/B1/B2）仍保留供历史统计展示。
- 40 人并发已验证（BDD B）：测试 `test_board.py::test_classroom_40_concurrent_submissions` 用真实线程池跑 40 并发上传 → 全部出分 → board 到齐。
- **发布快照体系（2026-09-29，`app/services/exercise.py`）**：老师发布（按题选题）生成不可变 `ClassroomExercise`（snapshot_items 深拷贝题目内容、version_no 递增、可命名标题），学生 daily 会话绑 `assignment_id` 后始终按快照出题；作答提交时再存 `attempt.item_snapshot`，worker 评分只读快照——题库编辑不影响已发布练习与历史解释。恢复自主练习会归档练习并解绑当日会话。旧指派路径（单元指派/按题引用）仅作兼容读取，重新发布即转快照；学生历史结果按「发布历史」Tab（`/classes/{code}/exercises/{id}/results`）按当时题单解释。
- **三题型互相独立（2026-09-29）**：文章朗读（可多篇拆段/自动拆分）/ 听句复述（独立句库 `SentenceLibrary`，可不挂篇目）/ 情景问答（按主题整组，**不分级**——band 字段仅存量兼容，抽题与发布不看档位）。课堂发布 = 三类各选内容写快照，操作条三端统一（编辑→标准音→删除）。
- **学生账号密码（2026-09-29 决策）**：默认密码统一 `brs123456`，导入/重置/批量重置均用它且**不强制改密**（学生侧边栏有自愿修改入口）；随机初始密码与 CSV 导出已下线。

### 术语表（2026-09 统一，前端单一事实源 `frontend/src/lib/terms.ts`）

同一概念全端只用一个词，新文案必须遵守（历史盘点：Unit 曾有 7 种叫法、问答 8 种、指派相关 9 种）：

| 概念 | 统一词 | 备注 |
|---|---|---|
| Unit | 单元 | 课堂指派与自主练习的基本单位；页面叫「单元管理」 |
| Unit.topic | 主题 | 与单元名区分（单元叫「宠物朋友」，主题叫「宠物」） |
| Passage | 篇目 | 教师/管理端；朗读与复述共用的英文材料 |
| 题型 reading | 文章朗读 | 学生端旧称「整篇朗读」已废 |
| 题型 repeat | 听句复述 | 学生端旧称「听后复述」已废 |
| 题型 qa | 情景问答 | 旧称「模拟问答/问答/开放问题/问法」已废；单条题叫「题目」 |
| 学生每日练习入口 | 今日练习 | 学生端页面 title、通知、首页 CTA 一致；教师端发布动作用「发布」 |
| 非指派模式 | 自主练习 | 旧称「自由练习/个人关卡」已废 |
| overall 分 | 参考分 | 可带前缀「跟读参考分/情景问答参考分」；rubric 0-9 叫「模拟分」 |
| CEFR band | 内部词表/评分元数据 | 不作为课堂安排或学生能力标签展示 |
| 学生成长页 | 我的成长 | 教师端对应页面叫「进步轨迹」 |
| 学生进班动作 | 进入课堂 | 旧称「加入课堂」已废（「邀请学生加入」作动词短语保留） |
- 课堂练习路由注意：TanStack 文件约定下 `p.$code.tsx`、`t.$code.tsx`、`_layout/admin.tsx` 都是父 layout（只渲染 Outlet），实际页面在 `*.index.tsx` 与兄弟路由文件。新增带参数子路由时必须检查父 layout 是否有 Outlet。
- 评分架构（PRD 不可协商）：引擎藏在可替换接口后（`app/scoring/`），`SCORING_PROVIDER` 配置切换：`mock`（默认，离线演示/测试）｜`ark`（火山方舟 Responses API 转写，需控制台开通模型 + `ARK_API_KEY`）。上传与评分分离：POST `/attempts` 立即返回 queued，线程池异步出分，前端轮询。跟读类（passage/repeat）出三维分，问答（question）只出总评+一句建议（rubric 四维是第 3 周）。音频回放走 `GET /attempts/{id}/audio`（attempt id 随机 UUID，不可猜）。
- 兼容评分规则（`app/scoring/bands.py`）：A2/B1/B2 仍保留在内部数据中，供历史数据、词表分析和评分兼容使用；不参与教师课堂编排，也不向学生展示。
- 界面文案铁律（PRD §3.2）：分数一律标「参考/模拟」，写明不是官方成绩；三种分（跟读引擎/模型/词表）来源要在界面上分开标注。
- EIP 教材原文因版权**不进仓库**，只建内容槽（Passage/RepeatSentence/Scenario/ScenarioQuestion 表）；演示种子用自写 Pets 内容（slug: demo-pets，课堂码 DEMO01）。
- **方舟已开通（2026-09-26 实测）**：`SCORING_PROVIDER=ark` 真实转写/rubric 模拟分已全链路验证。关键适配：浏览器 webm/opus 需服务端 ffmpeg 转 16kHz wav（`app/scoring/audio_convert.py`，容器已装 ffmpeg）；空转写不出 0 分模拟分。TTS `/audio/speech` 报 401（模型未开通），标准音暂用上传通道。
- 待办（上线前）：讯飞评测账号（跟读分升级可选）、学校分级词表 CSV（经 /admin/wordlist 导入）、EIP 文本（经 /admin/passages 录入，配音可上传现成音频）、域名 + ICP 备案（进教室要 HTTPS，备案 1~3 周需立即启动）。
- 生产部署尚未启用。配置部署 Secrets 后，将 GitHub Actions 仓库变量 `ENABLE_PRODUCTION_DEPLOY` 设置为 `true` 才允许自动部署。

## 项目结构

```
backend/app/
├── api/routes/     # FastAPI 路由（每个业务模块一个文件）
├── core/           # 配置、安全、数据库连接
├── models.py       # SQLModel 数据模型（数据库表结构）
├── crud.py         # 数据库增删改查操作
└── main.py         # 应用入口

frontend/src/
├── routes/         # TanStack Router 页面（_layout/ 下是需要登录的页面）
├── components/     # 可复用组件
├── hooks/          # 自定义 hooks（封装 useQuery/useMutation）
└── client/         # 自动生成的 API 客户端（不要手动修改）
```

## 本地开发

```bash
docker compose up --build   # 首次启动
docker compose watch        # 启用热更新（后端 --reload，前端 vite HMR）
docker compose down         # 停止
```

| 服务 | 地址 |
|------|------|
| 前端（vite dev server） | http://localhost:5173 |
| API 文档 | http://localhost:8000/docs |
| 邮件测试 | http://localhost:1080 |

查看数据库：`docker compose exec db psql -U postgres -d app`

运行后端测试（需要数据库在运行；测试自动创建并使用**独立测试库** `app_test`，不碰开发库 `app`）：

```bash
cd backend
# 本机宿主机 5432 被其他项目占用，db 映射到 5433（见 compose.override.yml）
POSTGRES_SERVER=localhost POSTGRES_PORT=5433 uv run bash scripts/tests-start.sh
```

测试库指向应用库时（`POSTGRES_DB_TEST` 与 `POSTGRES_DB` 相同）会在任何建表/删数据操作之前直接拒绝运行。

## 开发新功能的标准流程

> 本节是流程的唯一权威版本（README 只留概览指向这里）。

1. **后端**：在 `models.py` 加数据模型 → 在 `crud.py` 加增删改查 → 在 `api/routes/` 加新路由文件 → 在 `api/main.py` 注册路由
2. **数据库迁移**：`docker compose exec backend alembic revision --autogenerate -m "add xxx"` → `alembic upgrade head`
3. **前端 API 客户端**：后端改完后重新生成 → `cd frontend && npm run generate-client`（脚本会从运行中的 backend 容器导出最新 OpenAPI 规范再生成）
4. **前端页面**：在 `routes/_layout/` 加新页面，在 `frontend/src/components/Sidebar/AppSidebar.tsx` 的 `baseItems` 里加导航链接（Admin 入口已按 `is_superuser` 条件展示，可参考）

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
- **PR B（待做）**：句型推荐（按级别与表达用途分类的可替换句型）+ 学生单条收藏（跨设备）。

## 背单词模块（2026-10-01 起，P0 已上线）

独立「词汇学习」模块（设计文档 `docs/vocabulary-module-design.md`），与口语分析用的 `WordlistEntry` 完全分离，沿用现有账号/课堂/学生档案：

- **数据模型**：`VocabularyWord`（词条：拼写/词性/中英释义/可接受拼写）→ `VocabularyBook`（public=管理员维护 / classroom=本班教师自建）→ `VocabularyBookItem`；发布走 `VocabularyAssignment`（snapshot_items 深拷贝 + version_no）+ `VocabularyAssignmentTarget`（发布时固定名单，完成率分母不漂移）；作答 `VocabularySession`/`VocabularyAnswer`（幂等键唯一，练习重试 attempt_no 递增）。
- **判分**（`app/services/vocabulary.py`）：NFKC + 首尾空白 + casefold 规范化；只认快照拼写与显式 `accepted_spellings` 变体（**只收英美拼写变体，不收同义词**），不自动放宽复数/连字符。统计与错词本一律看**首答**；未答题不向学生端泄露拼写。
- **边界规则**：发布词单受可见性约束（公共库或本人班级库，word_ids 逐词核验归属，管理员不限）；`due_at` 以服务器时间强制（过期开会话/作答均 422）；幂等键绑定会话+题号（跨题复用 422）；纯听音任务要求全部词有标准音（发布 422），无标准音且未作答的词自动回落看义拼词。
- **API**：`app/api/routes/vocabulary.py`（`/vocabulary/books…` 词库 CRUD + CSV 导入预览；`/classes/{code}/vocabulary/…` 发布/结果/学生任务/错词本；`/vocabulary/sessions/{id}/answers` 作答）。域逻辑在 services，路由只做权限。
- **前端**：学生端 `/vocab/$code`（任务首页 + `/practice` 拼写练习 + 错词本），手机底部导航为「首页/口语/词汇/成长」；教师端 `/t/$code/vocab`（选词发布 + 完成情况），课堂面板可切换口语/词汇；管理端 `/admin/vocabbooks`（公共词库 CSV 导入预览）。无标准音的词练习用浏览器朗读兜底并标注「设备合成语音」。
- 测试 `tests/api/routes/test_vocabulary.py`（权限/快照/判分/幂等/名单/统计）；响应式 e2e 覆盖词汇两页三档宽度。

## 模考模式（2026-10-01 起）

发布练习时可开启「模考」（`is_exam` + `time_limit_minutes` 5–240）：

- **限时以服务器时间为准**：学生首次打开今日计划即落 `exam_started_at`，倒计时只是展示；到时任何读写触碰会话都会惰性落 `exam_ended_at`（= 自动交卷），此后提交一律 422。
- **每题一次作答**：考试会话内同题第二个作答 422（幂等键重传不受影响，断网重试安全）。
- **防切屏**：前端 `visibilitychange` 上报 `POST /classes/{code}/exam/violation`，计数入 `practice_session.tab_switch_count`（封顶 999），教师面板与发布历史可见。
- 考试中禁换题（next-question 422）、不展示逐题反馈（分数在结果页统一看）、题面 `select-none`。
- 实现在 `app/services/exam.py`（域逻辑）+ `attempts.py`（作答门禁）+ 练习页考试态 UI。测试 `tests/api/routes/test_exam.py`。

## 双语准则（平台级，2026-09-30 起）

平台有外教使用，**所有用户可见文案必须中英双语**。这是硬性开发准则，不是可选项。

- **机制**：`frontend/src/lib/i18n.tsx` 的 `useI18n()` → `t({ zh: "…", en: "…" })`；语言切换组件 `components/Common/LanguageToggle`（中/EN，localStorage 按浏览器记忆，默认中文）。
- **参考实现**：`frontend/src/routes/login.tsx` 与 `components/Common/LoginLayout.tsx`（含 zod 校验消息随语言重建的写法）。
- **新增界面/文案**：一律 `t({ zh, en })`，不允许再落单语言硬编码。共享术语的中英文对齐本文件「术语表」。
- **存量迁移**：按页面渐进迁移（改哪页双语哪页），不要求一次性完成；新 PR 触碰某页时顺手完成该页双语。
- **后端 API 错误文案**：`detail` 是稳定标识（前端 `main.tsx` 有按文案分流的 401 处理逻辑，**不得随意改措辞**）；面向用户的错误提示一律在前端映射成双语展示，不直接透出 detail。后端返回值的枚举/状态值（如 `status: "done"`）永不做翻译。
- **不做**：URL 按语言分路由（`/en/...`）；服务端语言协商。一个前端包、客户端切换即可。

## 三端自适应准则（平台级，2026-10-01 起）

平台必须支持电脑 / 手机 / 平板三端，**iPad 是学生上课主力设备**。新页面与改动都要在 390 / 820 / 1180 三档宽度下检查无横向溢出（`tests/e2e/responsive.spec.ts` 已入 CI）。

- **表单控件字号 ≥16px（全断点）**：原生 input/select/textarea 必须 `text-base`——iOS Safari 聚焦小于 16px 的控件会整页自动放大且失焦不还原。禁止用 `maximum-scale=1` 禁缩放来绕过（无障碍红线）。
- **触控目标**：高频操作 ≥44px，低频至少 40px；相邻的破坏性操作拉开间距。`icon-sm` 已调整为 size-10。
- **表格**：统一走 `ui/table.tsx`（自带 overflow-x-auto，不会撑破手机屏）；列多的宽表在 `<sm` 屏加「横向滑动」提示（`t.$code.index.tsx` 有范例）。
- **视口高度**用 `svh/dvh`，不用 `vh`（iOS 工具栏收放导致跳动）。
- **交互不得仅 hover 可达**（触屏无 hover）；hover 只用于装饰性反馈。
- **Dialog 滚动**依赖 `ui/dialog.tsx` 模板（dvh 口径 + overflow-y-auto + 小屏按钮纵向堆叠），业务弹窗不要再套自己的 `max-h-[xxvh]`。
- 学生端壳（StudentShell）<768 走底部 tab + 安全区，≥768 走侧栏；教师端侧栏 <768 走抽屉——断点行为已定型，新页面挂在对应壳下自动获得。

## 技术规范

详见 `AI_RULES.md`。
