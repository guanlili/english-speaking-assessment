# 课堂同步、考试轮询与故障定位 / Runtime synchronization and diagnostics

- 学生首页每 5 秒检查 `/classes/{code}/revision`。接口只校验本班身份并返回版本摘要，不创建练习会话；版本变化时刷新题单和学习路径。浏览器后台暂停定时请求，回到页面或重连时由 Query 刷新。正在作答的页面仍使用原发布快照，不被首页同步替换。

  The student home checks the class revision every five seconds and reloads the plan/path only on change. Revision checks do not create sessions. Background polling pauses; focus/reconnect refreshes the query. In-progress answers remain tied to their original publication snapshot.

- 自动考试首次加载完整题单，后续 `/classes/{code}/exam/state?session_id=…` 只返回阶段、服务器剩余时间和已提交题 ID。服务端继续执行原考试截止与逐题规则，不接受客户端延长计时。刷新或新设备进入仍需读取完整题单。

  Automated exams load the full plan once, then poll the compact state endpoint for phase, server time, and submitted IDs. Server deadlines and per-item rules remain authoritative. Refreshing or switching devices loads the snapshot again.

- 每个 API 响应含 `X-Request-ID`；支持人员可从浏览器网络面板复制该值，再在后端日志定位请求。只接受 8–64 位字母、数字、短横线和下划线组成的客户端关联值，其余请求自动生成。日志记录路由模板、HTTP 状态和耗时，不记录请求正文、密码、Authorization 或录音。

  Every API response includes `X-Request-ID`. Copy it from the browser network panel and search backend logs. Valid client correlation IDs contain 8–64 letters, digits, hyphens, or underscores; other values are replaced. Logs contain route templates, status, and duration, not request bodies, credentials, or recordings.

  ```bash
  docker compose -f compose.yml logs backend | rg 'request_id=SUPPORT_ID'
  docker compose -f compose.yml logs backend | rg 'provider_call'
  ```

- 评分主线程和详情线程继承请求上下文；外部 ASR/LLM/TTS 调用记 `provider_call`、成功与耗时。重启恢复的后台任务没有原 HTTP 上下文，标为 `background`。`/admin/metrics` 的计数仍为当前进程快照，新增实例 ID、PID 和启动时间，用于识别重启或多 worker，不能跨实例直接计算增量。历史排查使用日志；长期趋势另由 `admin_metrics_daily` 日快照表承接（2026-10 大盘 P1：业务量回算 + 运行时峰值采样，跨重启保留），无需外接指标库。

  Scoring and detail workers inherit request context; provider logs record outcome and latency. Restart recovery tasks use `background`. Metrics remain per-process counters and now include instance ID, PID, and start time to identify resets or multiple workers. Use logs for historical diagnosis; long-term trends require log collection.

- Playwright 失败时保留 trace、截图及视频，CI 将 `frontend/test-results/` 上传为失败现场。下载对应 runner 分片的产物，用下列命令打开 trace。现场可能包含测试账号和测试内容，按内部调试材料处理。

  Playwright retains traces, screenshots, and video on failure. CI uploads the failing shard's `frontend/test-results/`. Open the downloaded trace with the command below. Treat artifacts as internal debugging material because they may include test accounts/content.

  ```bash
  cd frontend
  npx playwright show-trace /path/to/trace.zip
  ```

- 导入查重只对本批涉及的题型分批读取规范化匹配键，再加载命中的候选详情；沿用 Python NFKC、casefold 与 Unicode 空白规则。匹配键扫描仍随相关表增长，不宣称已变成常数时间索引查找；如后续需要进一步提速，应引入可迁移、全写入路径一致维护的规范化索引列。

  Import planning streams matching keys only for relevant question types and materializes matching candidates. Python normalization semantics are unchanged. Key scans still scale with the relevant tables; indexed normalized columns are a separate migration if larger datasets justify them.

- 队列告警邮件默认关闭（`COST_ALERT_EMAIL` 留空即关闭，大盘红黄标不受影响）。启用只需配置，零代码改动：评分队列最老排队超过 25 分钟（`ALERT_QUEUE_AGE_S`）时向收件人发双语告警，当日限一封。部署流水线已映射所需 Secrets，步骤：

  1. 仓库 Settings → Secrets and variables → Actions → New repository secret，逐个添加 `SMTP_HOST`、`SMTP_USER`、`SMTP_PASSWORD`、`EMAILS_FROM_EMAIL`（如平台已有可用邮件配置可跳过）与 `COST_ALERT_EMAIL`（收件邮箱）。`SMTP_TLS`/`SMTP_SSL`/`SMTP_PORT` 未配置时默认 `True`/`False`/`587`。
  2. Secret 名必须与 deploy.yml 的映射逐字一致——拼错不会报错，只会静默不生效。
  3. 部署后在 backend 容器内验证配置已生效，并发一封测试邮件确认链路（凭据从 settings 读取，不落命令行）：

  ```bash
  docker compose -f compose.yml exec backend python -c "from app.core.config import settings; print(settings.emails_enabled, bool(settings.COST_ALERT_EMAIL))"
  # 期望输出：True True
  docker compose -f compose.yml exec backend python -c "from app.core.config import settings; from app.utils import send_email; send_email(email_to=settings.COST_ALERT_EMAIL, subject='[BELP] queue alert test', html_content='<p>队列告警链路测试</p>'); print('sent')"
  ```

  4. 关闭方式：删除 `COST_ALERT_EMAIL` secret 并重新部署。

  The queue alert email ships disabled (`COST_ALERT_EMAIL` empty); dashboard badges are unaffected. Enabling is configuration-only: when the oldest queued attempt exceeds 25 minutes, a bilingual alert is sent at most once per day. Add `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAILS_FROM_EMAIL`, and `COST_ALERT_EMAIL` as repository secrets (names must match deploy.yml exactly — typos fail silently), redeploy, then verify inside the backend container that `emails_enabled` and `COST_ALERT_EMAIL` are both set and send a probe email via `app.utils.send_email`. Remove the secret and redeploy to disable.
