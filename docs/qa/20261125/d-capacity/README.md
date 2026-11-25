# D-capacity：多实例与实时容量验证（#517，2026-11-25）

> 范围：课堂 PK（Vocabulary PK）在 **单副本基线 / 双副本** 两种形态下的作答延迟、
> 跨副本状态传播延迟与并发通道实测；nginx SSE 入口配置；应用连接空闲事务超时；
> Redis 边界结论与目标环境复测状态。
>
> **数字口径警示**：以下全部为**本机参考环境**实测值，不构成生产容量承诺。
> 生产/同规格非生产环境复测状态见文末「目标环境复测」，当前为 **BLOCKED**。

## 1. 环境与方法

### 1.1 本机环境（两类本机数字的共同前提）

| 项 | 值 |
| --- | --- |
| 主机 | Apple M6 / 24 GB 内存 / macOS 27.0（arm64） |
| 数据库 | 本地 Docker `postgres:18`，端口 5433（独立开发实例） |
| 探针库 | 合成库 `app_pk_probe`，每次运行前 drop/create，跑完自动清理（`--keep-db` 保留） |
| 评分 | `SCORING_PROVIDER=mock`，不触真实 ASR/LLM/TTS |
| 副本形态 | 单副本：探针进程内临时 uvicorn（随机端口）；双副本：**两个独立 OS 子进程**（`backend/scripts/pk_probe_server.py`），共库、独立端口，非同一进程双线程 |
| 既有进程 | 8000 后端 / 5173 前端 / 5433 DB 的开发容器未被探针复用；探针走临时端口与合成库 |
| 安全闸 | 探针仅允许 `ENVIRONMENT=local` + 本机 host；口令取自 `PK_PROBE_PASSWORD` 环境变量，无内置默认弱口令 |

### 1.2 场景规模（与设计稿 §1.3 一致）

- 20 名学生 / 10 场 1v1；20 条对局 SSE + 20 条轮询快照通道，合计 **40 通道保持 60s**。
- 作答：每名学生提交第 1 题正确答案，记录端到端 `/answers` 延迟；双副本下作答与通道尽量跨副本轮询分布。
- 传播：抽样 5 场，观察者 SSE 连接所在副本与提交方副本分离（双副本即跨副本样本），记录服务端提交 → 观察者 SSE 收到新版本快照的耗时；SSE 服务端轮询周期 1.0s，传播延迟存在该周期下限。
- 目标：作答 P95 ≤ 300 ms；传播 P95 ≤ 1.5 s；40 通道 / 60s 达标。

### 1.3 复现命令

```bash
cd backend
# 单副本基线
PK_PROBE_PASSWORD=<本机临时口令> POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \
  SCORING_PROVIDER=mock .venv/bin/python scripts/pk_capacity_probe.py \
  --replicas 1 --hold-seconds 60 --label local-single
# 双副本（两独立子进程共库）
PK_PROBE_PASSWORD=<本机临时口令> POSTGRES_SERVER=localhost POSTGRES_PORT=5433 \
  SCORING_PROVIDER=mock .venv/bin/python scripts/pk_capacity_probe.py \
  --replicas 2 --hold-seconds 60 --label local-dual
```

原始输出：`raw/local-single-60s.log`、`raw/local-dual-60s.log`（含 httpx 访问日志与完整报告表）。

## 2. 实测指标表（三类环境分列）

| 环境类别 | 副本 | 作答 P50 | 作答 P95 | 传播 P50 | 传播 P95 | 跨副本传播 P95 | 通道（保持 60s） | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 本机单副本基线 | 1 进程 | 112.6 ms | 161.7 ms | 0.95 s | 0.96 s | —（同进程） | SSE 20 + 轮询 20 = 40 | 达标 |
| 本机双副本 | 2 独立进程共库 | 78.3 ms | 92.8 ms | 0.96 s | 0.99 s | n=5，P95 0.99 s | SSE 20 + 轮询 20 = 40 | 达标 |
| 目标环境（预发/测试或同规格非生产） | — | — | — | — | — | — | — | **BLOCKED**（见 §6） |

- 作答样本：每组 n=20；双副本作答分布 副本0 10 笔 / 副本1 10 笔。
- 传播样本：每组 n=5；双副本 5 场均为跨副本（提交方与观察者分处不同进程）。
- 双副本相对单副本**未见明显劣化**：作答 P95 反而更低（本机噪声 + 两进程独立调度），跨副本传播 P95 0.99s 与单副本 0.96s 在同一量级，差值落在 1s SSE 轮询周期的测量噪声内。

### 2.1 图表

- 作答延迟 P50/P95：[`charts/answer-latency.svg`](charts/answer-latency.svg)
- 状态传播延迟 P50/P95：[`charts/propagation-latency.svg`](charts/propagation-latency.svg)
- 并发通道构成：[`charts/channels.svg`](charts/channels.svg)

## 3. 代码改动清单

| 文件 | 改动 |
| --- | --- |
| `backend/scripts/pk_capacity_probe.py` | 扩展为 `--replicas 1\|2`：单副本线程内基线 / 双副本独立子进程共库；作答与通道跨副本轮询；记录作答副本分布、跨副本传播样本；报告区分环境 `--label`；播种时显式双开 speaking/vocabulary 模块授权、词库 `confirm_reviewed` |
| `backend/scripts/pk_probe_server.py` | 新增：探针副本子进程入口，连接探针库、覆盖全局 engine、单 worker uvicorn；复用 local + 本机安全闸 |
| `frontend/nginx.conf` | PK SSE 路径专用 location：关缓冲/缓存、HTTP/1.1、Connection 清空、读写超时 300s、`X-Accel-Buffering: no` / `Cache-Control: no-cache`、按 IP 连接上限 |
| `frontend/nginx-tls.conf` | 同上（443 server），重复 HSTS 头；80 server 仅健康探测，不挂 SSE location |
| `backend/app/core/config.py` | 新增 `DB_IDLE_IN_TXN_TIMEOUT_S`（默认 30s，0=关闭） |
| `backend/app/core/db.py` | 应用业务引擎与平台通道引擎连接参数下发 `idle_in_transaction_session_timeout`；Alembic/admin 管理连接不经此路径 |
| `backend/tests/test_db_idle_txn_timeout.py` | 新增：参数下发可见、空闲事务超时后可恢复、并发提交不丢作答、并发会话不串租户 |

后端 SSE 路由（`vocabulary_pk.py`）原有 `X-Accel-Buffering: no` / `Cache-Control: no-cache` / `Connection: keep-alive` 响应头保留，与 nginx 入口侧配置形成双保险，本次未改动其语义。

## 4. nginx SSE 配置口径

专用 location 匹配 `^/api/v1/classes/{code}/vocabulary/pk/matches/{id}/events$`：

- `proxy_buffering off`、`proxy_cache off`：禁止入口把事件攒批下发；
- `proxy_http_version 1.1` + `proxy_set_header Connection ""`：长连接复用；
- `proxy_read_timeout 300s` / `proxy_send_timeout 300s`：对齐单连接 5 分钟上限以内的空闲容忍；
- `add_header X-Accel-Buffering "no" always`、`Cache-Control "no-cache" always`：与后端头双保险；
- **连接上限口径**：`limit_conn pk_sse_per_ip 64`，按客户端 IP 计数。刻意不设低值——整班学生常走同一校园 NAT 出口共享一个公网 IP，64 留足单班 40 人 + 断线重连余量；不同班级 / 不同 NAT 出口互不影响。超限返回 503，前端既有降级路径切 1.5s 轮询，比赛不暂停。zone 为每 IP 计数（非整站总连接数），未采用会误伤整班 NAT 的单 IP 低上限。

两份 conf 互斥启用（`entrypoint.sh` 按证书存在性二选一），zone 名在各自文件顶部 http 上下文声明。

## 5. 空闲事务超时（idle_in_transaction_session_timeout）

- 默认 **30s**，可经 `DB_IDLE_IN_TXN_TIMEOUT_S` 配置（0 关闭）；走 libpq `options` 下发 GUC，单位毫秒。
- 作用范围：应用业务引擎 + 平台通道引擎。兜底 PK 结算/异常路径偶发占着连接不释放、把连接池耗尽的问题。
- **不影响**：Alembic 迁移（`env.py` 用 admin URI 自建 NullPool 引擎，不经此函数）；admin/owner 管理连接；评分 worker 在长 LLM 调用前已提交事务，不存在跨调用的开环事务。
- 测试覆盖：超时参数在新连接上生效（`pg_settings` 毫秒值）；空闲事务超时被 PG 终止后，新连接可正常工作（pre-ping 不残留死连接）；两线程并发各提交 5 条作答全部落库；并发会话租户上下文互不串扰。

## 6. 目标环境复测：BLOCKED

### 6.1 状态：未复测（BLOCKED）

本次**未部署任何环境、未连接测试/生产库**。仓库内存在测试环境流水线 `.github/workflows/deploy-test.yml`（GitHub Environment `test`），但：

1. 测试环境最近一次部署为 **2026-11-19，SHA `05ffe42`**，早于本分支基线 `06ca873`；本分支尚未部署到测试环境。
2. 测试机 host / 域名 / SSH 凭据位于 GitHub Environment Secrets，本会话不可读；仓库文档中也未记录测试环境可直连入口（`outman.website` 对应生产，不在复测范围）。
3. 探针安全闸只允许本机 host；对远端运行需要单独评审放开白名单，本次未做。

### 6.2 复测 runbook（解除 BLOCKED 所需条件齐备后执行）

1. **部署授权**：本分支 PR 合并（或指定 SHA）经 CI 全绿后，手动触发 `Deploy Test`（`deploy-test.yml` 的 `workflow_dispatch`）部署到 `test` 环境；不得触发 `Deploy Production`。
2. **环境确认**：记录测试机规格（CPU/内存/磁盘）、`WORKERS` 副本/进程数、DB 是否独立、是否与生产同规格；确认测试库为非生产库。
3. **探针准备**：在可访问测试环境的机器（测试机本机或授权跳板机）上，以合成数据创建探针库与探针账号；`SCORING_PROVIDER=mock`；探针 target 模式放开 host 白名单需经评审并留痕。
4. **复测执行**：按 §1.3 命令分别跑 `--replicas 1` / `--replicas 2`，`--label target-test`；记录环境规格、同时段背景负载、P50/P95、通道数与跨副本样本数。
5. **判定**：达标线同上（作答 P95 ≤ 300ms、传播 P95 ≤ 1.5s、40 通道/60s）；数字必须标注为「目标环境」，与本机数字分列。
6. **清理**：复测后删除探针库/账号；原始输出归档到本目录 `raw/`。

### 6.3 所需条件（缺口）

- 测试环境部署授权与目标 SHA；测试环境入口地址；探针合成库/账号创建权限；到测试环境 DB/HTTP 的网络可达；环境规格与 WORKERS 配置信息。

## 7. Redis 边界结论（本轮不引入 Redis）

### 7.1 结论

双副本共库实测**未明显劣化**，跨副本传播 P95 0.99s 达标。**本轮不引入 Redis**，`compose.yml` 不新增 Redis 服务。当前可确认的可行边界：

- 单班 20 玩家（10 场 1v1）、40 通道量级；2 个后端副本共享同一 Postgres；
- 状态事实源始终是 DB；SSE 仅作通知/版本推送优化，轮询快照为一致降级路径；
- 跨副本可见性依赖 DB 提交（read committed），不依赖进程内广播或粘性会话。

### 7.2 不适用 / 需重新评估的场景

- 多班同时开课、并发显著超出 20 玩家 / 40 通道（需按压测结果上调）；
- 对跨副本通知延迟有硬要求（明显低于当前 ~1s 的 SSE 服务端轮询周期）；
- `WORKERS` 上调后进程内通知失效（当前已自动回退轮询，SSE 退化为单副本优化）；
- DB 连接池 / 行锁 / 快照查询成为瓶颈，或单库无法承载多副本写入。

### 7.3 Redis pub/sub 备选方案（未实施，仅预案与成本估算）

若复测出现跨副本传播不达标或 DB 轮询压力超限：

- **方案**：每副本订阅 `pk:match:{match_id}` 频道；作答/推进/结算提交 DB 后向频道 publish 版本号；本副本持有该对局 SSE 连接的进程收到通知即向客户端推快照。**Redis 只做通知扇出，不存分、不做事实源**；DB 仍为状态唯一来源，通知丢失时由 1.5s 轮询兜底。
- **成本估算（2026-11 公开价位量级，以实际报价为准）**：
  - 同机旁挂自建 Redis（小内存实例，通知 payload 仅 match_id + 版本号）：无新增云账单，占用少量本机内存；
  - 托管 Redis（阿里云 Tair/Redis 社区版 1GB 主备）：约 ¥100–200/月量级，不含带宽与应用改造工时；
  - 改造项：pub/sub 订阅/发布封装、断线重订阅、消息积压与重复通知去重、连接池与哨兵/集群选型；不涉及计分口径改动。

## 8. 限制与口径

- 本机为开发机 + 本地 Docker PG，无生产网络抖动、无跨可用区延迟；P95 数字不能外推为生产承诺。
- 传播延迟受 SSE 服务端 1.0s 轮询周期下限约束，单副本与双副本差值在测量噪声内；样本量 n=5，仅作容量方向参考。
- 探针评分走 mock，未覆盖真实 ASR/LLM 链路耗时；作答延迟不含音频上传与语音识别。
- 探针合成数据不写 `VocabularyAnswer`、不触教师任务统计与发布快照。
- 原始日志仅含本机 `127.0.0.1` 临时端口与合成账号（`pkstu00` 等）；探针口令经环境变量注入，未写入日志或仓库。
