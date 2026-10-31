# 多租户改造 A 期交付：边界清单 + RLS 原型验证 + 双角色方案 + 迁移演练方案

日期：2026-10-31。对应需求：[Notion 多租户商用改造 V1.0](https://app.notion.com/p/4099aef5c21081c2bde7e1ad7170ab76)（GitHub 镜像 #223）与技术设计 [multi-tenant-design.md](multi-tenant-design.md)。A 期四件产出物（V1.0 §8）全部落位于本文与 [rls_prototype.py](../backend/scripts/rls_prototype.py)。

**结论先行**：
1. 边界盘点完成——35 张表、23 个 router 约 211 条路由、3 处原生 SQL + 8 处 Core update + 6 处聚合裸查询、8 类后台任务、2 块存储卷 + 1 条匿名音频入口、前后端全部缓存键；四个高风险耦合点已定位（见 §2）。
2. **RLS+连接池原型 12/12 通过**（PostgreSQL 18 真库）：TenantSession 事务级绑定、缺上下文默认拒绝、连接复用不串校、双角色分离全部成立——V1.0 §5 的技术路线可行。
3. 迁移与恢复演练方案成稿（§5），单校恢复与多校回滚边界明确。

---

## 1. 边界清单（逐条盘点）

### 1.1 数据库表（35 张，models.py）

分类口径：A=身份/租户入口；B=教学业务（外键链到身份，全部加 tenant_id）；C=平台级（不加）；D=需裁决。

**A 类（1 张）**
| 表 | 关键约束 | 说明 |
|---|---|---|
| user | email 全局唯一；username 全局唯一索引 | 租户入口核心：唯一性改 (tenant_id, X)，登录先定校（V1.0 FR-02） |

**B 类（20 张）**
classroom（code 全局唯一，owner_id FK；首期保留 code 全局唯一兼容旧入口）、student（三个部分唯一索引均以 classroom_id/user_id 打头，随课堂归租户自然隔离）、classroom_exercise（(classroom_id,version_no) 唯一）、composer_draft（(classroom_id,owner_id) 唯一）、practice_session（4 个部分唯一索引）、attempt（idempotency_key 全局唯一幂等键）、item_listen（唯一约束被原生 UPSERT 按约束名引用，见 §2-2）、instruction_ack、student_badge、student_expression_favorite、student_frame_favorite、classroom_review、followup_batch、classroom_message、vocabulary_assignment（(classroom_id,version_no) 唯一）、vocabulary_assignment_target、vocabulary_session（3 个部分唯一索引）、vocabulary_answer（幂等键全局唯一）、export_job、export_audit。

**C 类（6 张）**
changelog_entry（平台更新日志）、admin_metrics_daily（day 主键，全平台口径日快照）、admin_cost_reconcile（month 主键总账）、vocab_level_entry（五级词库授权目录，存量先归原校）、unit（全局单元目录）、sentence_frame（共享句型）。C 类中 vocab_level_entry/unit/sentence_frame 按 V1.0 FR-04 属「存量归原校、授权后入平台目录」——**B/C 归属在实施时按此口径落库**。

**D 类（8 张，需按 V1.0 裁决落位）**
passage（slug 全局唯一→改 (tenant_id,slug)）、repeat_sentence、scenario（topic 全局唯一→改 (tenant_id,topic)）、scenario_question、instruction（以上 owner_id 仅表校内编辑权，NULL≠全平台共享）、vocabulary_word（公共词条池，scope 语义待定）、vocabulary_book（scope=public/classroom 双态，public 重定义为校内公共）、vocabulary_ai_cache（cache_key 全局唯一，与 RLS 共存需裁决）。另：content_copy 的 copied_from_id 裸 uuid 列存在跨租户复制链路，随 FR-04 复制到本校一并裁决。

### 1.2 路由（23 个 router，约 211 条）

权限门分布（T=TeacherUserDep，admin 恒通过；S=SuperUserDep；St=StudentUserDep；C=任意登录；Opt=匿名或学生凭证；anon=匿名）：
- **学生链路**（St/Opt，租户校验从学生凭证推导）：classes 系列 13 文件约 70 条（today/next-question/exam/state/start/flow/listens/acks/trail/path/my-sessions/revision 等）、attempts 6 条（提交双限流桶）、vocabulary 学生侧约 15 条、vocab_ai 3 条（限流）。
- **教师链路**（T，需在课堂归属判定前加学校一致性校验）：classes 管理侧约 25 条、students 7 条（导入/重置含跨校静默合并漏洞）、vocabulary 教师侧约 14 条、admin 内容族约 60 条（passages/sentences/instructions/scenarios/questions/taxonomy/composer/exam-items/question-bank io/copy）。
- **平台运营链路**（S，is_superuser 替换为 PlatformOperator 时的改造面）：users 10 条、admin dashboard 6 条、admin export 3 条、metrics 1 条、changelog 写 3 条、classrooms 3 条、units/sentence-frames 写 6 条、vocab-levels 5 条。
- **匿名入口**（租户解析先行）：login 7 条、audio/content/{filename} 1 条（**无鉴权**，见 §2-4）、health/ready 2 条。

完整逐条路由清单见盘点底稿（2026-10-31 会话存档）；实施时以 `grep -rn "@router\." backend/app/api/routes/` 现场再生成，防止漂移。

### 1.3 裸 SQL / Core execute 路径（TenantSession 必须覆盖）

- **原生 text() 三处**：class_runtime.py:223/237（item_listen 原子 UPSERT，按约束名 `uq_item_listen_scope` 引用）；question_bank_io.py:2118（pg_advisory_xact_lock 导入锁）；utils.py:66（就绪探针 SELECT 1，不能被 RLS 拦死）。
- **Core update() 经 session.execute() 八处**：audio_retention.py:117（音频批量结算）、scoring/worker.py:877/927（评分清扫/启动恢复）、vocabulary.py:444 与 services/vocabulary.py:1894（词书版本自增）、vocab_quiz.py:315（切屏计数）、services/exam.py:569/590（考试切屏）。
- **connection().execute 聚合查询六处**：usage_export.py:197/298/313/322/329（全平台 CSV 导出）、admin_dashboard.py:329/341（课堂累计/活跃）、metrics_daily.py:164/199（日快照回算）、class_report_pdf.py:192、trail.py:51、class_trend.py:27。
- **行锁路径**（FOR UPDATE / SKIP LOCKED，RLS 下语义已由原型 P4d 验证）：scoring/worker.py:357/391/731/868/918、exporting/worker.py:132、services/exam.py:288/293、exam_flow.py:222。
- **部署侧**：backup_bundle.py:163 pg_dump 全库快照（不走应用 Session，多租户下保留为灾备口径）。

### 1.4 后台任务（8 类，全部脱离 HTTP 上下文自建 Session）

评分 worker（ThreadPoolExecutor SCORING_WORKERS + copy_context 提交，5 处 `with Session(engine)`，领取 FOR UPDATE SKIP LOCKED）、评分清扫线程（60s）、评分重试 Timer、启动恢复（lifespan 僵尸关闭+重投）、导出 worker（EXPORT_WORKERS=2，8 处 Session）、导出清扫线程（1h）、大盘日快照线程（60s 采样/跨日落行/启动回填 400 天）、音频保留清理线程（24h，含孤儿回收）。另进程外脚本 4 个（orphan_scan/perf_baseline/initial_data/pre_start）。
**要点**：request_context.py 的 contextvars 不覆盖上述任何路径——设计稿 §7.2 的「任务持久化 tenant_id + worker 显式接收 (tenant_id, task_id) 重绑」是必选改造，原型 P3 已验证重绑语义成立。

### 1.5 文件系统与对外 URL

学生录音（{AUDIO_STORAGE_DIR}/ uuid 扁平）、内容标准音（content/ 子目录，TTS 内容寻址缓存）、回放缓存（.playback.wav 旁路）、导出成品（{EXPORT_STORAGE_DIR}/，DB 存 artifact_relpath）；compose 三卷 app-audio-data/app-export-data/app-db-data。对外 URL：/api/v1/audio/content/{filename}（匿名）、/api/v1/attempts/{id}/audio（鉴权流式）、/api/v1/exports/{job_id}/download。目标结构 tenants/{tenant_id}/recordings|content|exports（V1.0 FR-05），Storage 接口封装。

### 1.6 缓存与内存态

后端：metrics 计数器（重启归零）、音频统计 60s 缓存、日峰值采样线程态、三组限流桶（登录/注册/作答）+ 词汇 AI 每用户桶、五级词评分缓存、重投簿记。前端：admin.tsx 5 分钟用户缓存（按 token 指纹——多租户需带租户维度）、React Query 键全清单（admin/*、users、my-classrooms 为跨租户键；classroom/vocab 键天然带 code/studentId）、localStorage 11 个 key（access_token、esa:role、esa:must-change-pw、esa:student:{CODE}、esa:saved-expressions:{owner}、exam-session:{studentId}:{CODE}、exam-note:*、esa:qbank:composer-preset、esa:changelog-seen、esa:lang、vite-ui-theme——**均无租户维度**）、sessionStorage 1 个、IndexedDB 录音草稿（复合主键含 owner/classroomCode）。

## 2. 高风险耦合点（盘点浮现，实施时先拆）

1. **全局唯一键直接挡复合化**：user.email、user.username、passage.slug、scenario.topic 四个列级唯一 + attempt.idempotency_key、vocabulary_answer.idempotency_key、vocabulary_ai_cache.cache_key 三个生成键。前四个按设计改 (tenant_id, X)；幂等键保留全局唯一，命中冲突按租户核验（设计稿 §4.3）。
2. **UPSERT 按约束名引用**：class_runtime.py 的 ON CONFLICT ON CONSTRAINT uq_item_listen_scope——该表加 tenant_id 时约束结构变化会破坏此 SQL，需同步改写。
3. **8 类后台 Session 与 contextvars 隔离**：见 §1.4 要点。
4. **匿名内容音频入口**：/audio/content/{filename} 完全无鉴权，租户过滤只能靠 FR-05 的资产映射鉴权（历史 URL 兼容）或路径分段，不能靠文件名不可猜延续。

## 3. RLS + 连接池原型验证（12/12 通过）

脚本：backend/scripts/rls_prototype.py（幂等，独立原型库 rls_proto，自建自清，不碰 app/app_test）。
复跑：`cd backend && POSTGRES_SERVER=localhost POSTGRES_PORT=5433 uv run python scripts/rls_prototype.py`

| # | 命题 | 结果 |
|---|---|---|
| P1a/b | 缺上下文默认拒绝：SELECT 空、INSERT 被策略拒 | ✅ |
| P2a/b | 事务级绑定双路径：ORM 文本查询与裸 connection().execute 同受 RLS 过滤 | ✅ |
| P2c | WITH CHECK 拒绝跨租户写入 | ✅ |
| P3a/b/c | 同一物理连接（backend_pid 相同）A→B 事务重绑无残留、各只见本租户行 | ✅ |
| P4a | 运行角色非 superuser、无 BYPASSRLS | ✅ |
| P4b | 运行角色无 DDL 权限（CREATE 被拒） | ✅ |
| P4c | DDL 角色可建表（Alembic/prestart 通道） | ✅ |
| P4d | FOR UPDATE SKIP LOCKED 在 RLS 下不重复领取（评分/导出领取语义保持） | ✅ |

实现要点（TenantSession 原型）：`ContextVar[str|None]` 持当前租户 + SQLAlchemy 引擎级 `begin` 事件执行 `SELECT set_config('app.tenant_id', :t, true)`（事务级）；策略 `USING/WITH CHECK (coalesce(current_setting('app.tenant_id', true), '') = tenant_id::text)`——coalesce 保证未设上下文（NULL/''）永不匹配即默认拒绝。该模式即为 B 期 TenantSession 工厂的验收基线。

## 4. 数据库双角色方案（原型已验证）

| 项 | esa_ddl（迁移角色） | esa_app（运行角色） |
|---|---|---|
| 登录 | 是 | 是 |
| 数据库 | rls_proto OWNER（生产=业务库 owner） | CONNECT only |
| schema/表 | CREATE/ALTER/DROP、owner | USAGE on schema；DML on 表（SELECT/INSERT/UPDATE/DELETE） |
| RLS | 表 owner（FORCE 下同样受限；迁移窗口可显式 DEFEAT） | 非 owner、无 BYPASSRLS、FORCE 生效 |
| TRUNCATE/DDL | 允许 | 拒绝（P4b 验证） |
| 使用方 | Alembic、部署 prestart、回填脚本 | 应用运行时全部业务连接 |

落地注意：① 生产 compose 的 POSTGRES_USER 需拆为两个（env 各一套凭据，走部署 Secrets）；② Alembic 迁移内如需 UPDATE 数据（回填），在迁移角色下天然可行（owner；FORCE 策略对 owner 生效时迁移内先 `ALTER TABLE ... DISABLE ROW LEVEL SECURITY` 或用 SECURITY DEFINER 辅助，B 期定稿）；③ 平台运营全局汇总走受控 BYPASSRLS 会话或 SECURITY DEFINER 聚合（V1.0 §5 评审补充），实现细节 B 期定稿。

## 5. 迁移与恢复演练方案（A 期稿，E 期执行）

**迁移主线**（设计稿 §9 的操作化）：
1. 准备：整库备份 + 隔离恢复演练（沿用 docs/backup-restore.md 演练规程）；用 §1 清单现场再生成表/路由/文件/任务核对表；建立原校 Tenant（标识由管理员核实）。
2. 扩展：可空 tenant_id + 新代码双写窗口（新代码显式写原校 ID），旧进程漏写由切换检查追补——本仓部署为单进程滚动，窗口=一次部署内。
3. 回填：user/题库/课堂直接归原校；student 从课堂推导；session/attempt/词汇/点评/导出沿父链逐层回填；孤儿与冲突进人工清单。回填脚本跑在 DDL 角色（§4）。
4. 凭证与资产：旧 JWT（无租户声明）统一失效重登；旧录音/标准音先建 FileAsset 归属映射，再分批搬迁至 tenants/{id}/ 并校验大小/摘要。
5. 收紧：无 NULL/无跨校关联/校内规范化无冲突三项检查通过后，加非空+唯一+复合 FK+RLS+换运行角色，删默认回落逻辑。
6. 验收：合成 B 校越权测试（AC-01~12）→ 真实试点。

**单校恢复**：恢复整库备份到隔离实例（同 §备份演练），按依赖图提取该校行（tenant_id 过滤导出）+ 该校资产文件，校验后导回生产；禁止用旧整库覆盖生产恢复单校。恢复后重放删除清单。
**多校回滚**：第二校写入后禁止回滚到不识别租户的镜像；rollback 标签镜像须先过「含 tenant_id 迁移链」兼容检查（scripts/rollback.sh 增加检查项，E 期落地）。
**演练排期**：全量恢复已具备规程（10-30 已实操一次）；单校恢复演练排在 E 期（需先有 tenant_id 才可按校提取）。

## 6. A 期结论与 B 期入口

- 技术路线全部验证可行，无阻断项；四个高风险耦合点已有明确解法方向。
- B 期（租户与身份，5-8 人日）建议首批 PR 切分：①Tenant/PlatformOperator 模型+迁移+双角色落地 ②(tenant_id, username/email) 复合唯一+登录租户解析+/s/{slug}/login ③TenantSession 工厂（原型转正）+HTTP 依赖注入 ④导入/加入跨校阻断 ⑤is_superuser 全量替换审计。每批走既有流程：PR → CI 全量 → 合并 → 双轨回填。
- 估时复核（V1.0 §8 要求）：C 期 10-15 人日维持「偏紧」判断——35 表中 8 张 D 类裁决 + 约束/索引复合化工作量集中在 C；建议 B 期结束后按实际 PR 体感再校一次。
