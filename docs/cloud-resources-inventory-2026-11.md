# 云资源清单（SpeakUp 现状盘点）

> 盘点时间：2026-11-18 ｜ 方式：在生产机只读核查 + 仓库配置比对
> 用途：云资源迁移的输入清单。配套方案见 [cloud-migration-plan-2026-10.md](cloud-migration-plan-2026-10.md)
> 口径：只记「实际在用」的资源；文档里计划要买但还没用的单列在第六节

## 一、先说一条最要紧的边界

**这台腾讯云 CVM 不是 SpeakUp 独占，是同机多项目共用。** 实际在跑的 Compose 项目：

| Compose 项目 | 服务数 | 目录 | 体积 |
| --- | --- | --- | --- |
| `speakup`（本项目） | 4 | `/opt/speakup` | 13G（含 13G 备份） |
| `yujee`（遇己，另一项目） | 5 | `~/yujee-ops`、卷 `yujee_pgdata` | 67M 库 + 1.4G 素材目录 |
| `salesbot-landing` | 1 | `~/salesbot-landing` | 5.8M |
| 其他代码目录（未跑容器） | — | `~/hypit` 7.9G、`/opt/langbot` 2.1M | — |

**所以不能按「整机交接给公司」做迁移。** 迁移只能搬 SpeakUp 自己的容器、卷和备份；同一台机上的 Yujee、salesbot、hypit 要么另买一台留给自己，要么一并规划。这一步开工前必须先拍板，否则新公司机买回来也搬不干净。

## 二、计算资源

| 项目 | 现状（已核实） |
| --- | --- |
| 厂商 / 实例 | 腾讯云 CVM，实例 ID `ins-9fqh03nr` |
| 地域 / 可用区 | `ap-beijing` / `ap-beijing-7`（北京七区） |
| 规格 | 4 vCPU（AMD EPYC 7K62）、15G 内存 |
| 系统盘 | 118G，已用 70G（62%），剩 44G |
| 公网 IP | `49.232.156.221` |
| 计费 | 包月，方案文档记 ¥185/月（腾讯 SA2.LARGE16），**带宽计费方式未核实** |
| 部署形态 | 单机 Docker Compose，6 个服务：`acme`、`db`、`prestart`、`backend`、`frontend`、`mailcatcher` |
| 操作系统 | Ubuntu（主机名 `VM-24-7-ubuntu`），uptime 69 天 |

## 三、数据与存储（迁移的实际工作量在这里）

| 卷 / 目录 | 内容 | 体积 |
| --- | --- | --- |
| 卷 `app-audio-data` | 学生录音（保留 `AUDIO_TTL_DAYS=180`） | 1.688G |
| 卷 `app-db-data` | PostgreSQL 数据目录 | 86.8M |
| 卷 `app-export-data` | 导出文件（保留 `EXPORT_TTL_DAYS=7`） | 4.3M |
| 卷 `acme-sh-data` | 证书状态 | 35.6K |
| `backups/`（主机目录） | 每日备份包，14 天保留 | 13G |
| 镜像 | 18 个 Docker 镜像 | 9.8G |

**业务数据合计约 1.8G**，加上备份 13G、镜像 9.8G，单机迁移的数据搬运量约 25G 量级。数据库 dump 仅 2.4M，音频是主要部分。

**当前没有任何对象存储。** 录音、导出、备份全部落在本机磁盘，异地副本尚未落地（这正是迁移方案里要补的短板）。

## 四、网络、域名、证书

| 项目 | 现状（已核实） |
| --- | --- |
| 生产域名 | `outman.website`（`TLS_DOMAIN` / `FRONTEND_HOST`） |
| 解析 | A 记录指向 `49.232.156.221`；NS 为 `drone.dnspod.net` / `same.dnspod.net` → **DNSPod（腾讯云解析）** |
| 域名注册商 | **未核实**（DNSPod 解析 ≠ 注册商，过户前要查 whois 或登录原注册商） |
| HTTPS 证书 | Let's Encrypt，容器内 `acme.sh` 自动续期；域名 `langbot.outman.press` 的证书也曾签发于此（历史遗留） |
| 证书校验方式 | **DNS-01**，凭 `DP_Id` / `DP_Key`（DNSPod API 密钥）自动签发 |
| 反向代理 | `frontend` 容器内 Nginx，`/api` 反代到 `backend:8000`，TLS 证书挂载自 `ssl/` |
| 线上可用性 | `https://outman.website/` 200、`/api/v1/utils/health-check/` 200 |

> 迁移要点：acme.sh 换成火山 DNS 时，校验插件要从 DNSPod 改成火山，否则证书续期会静默失败。这一条方案文档已列，属**必须改**项。

## 五、外部服务与第三方依赖

| 类别 | 服务 | 配置项 | 状态 |
| --- | --- | --- | --- |
| 语音识别 | 火山引擎（`ASR_PROVIDER=volc_flash`） | `VOLC_ASR_API_KEY` | 已填、在用 |
| 开放题评分 / 大模型 | 火山方舟（`SCORING_PROVIDER=ark`） | `ARK_API_KEY`，模型 `doubao-seed-2-0-lite-260428` | 已填、在用 |
| 语音合成 | 火山方舟 TTS | `ARK_TTS_API_KEY`，`doubao-tts` | 已填、在用 |
| 邮件（SMTP） | 无 | `SMTP_HOST/USER/PASSWORD` 全空 | **未配置**：密码找回、队列告警邮件实际发不出 |
| 错误监控 | 无 | `SENTRY_DSN`、`VITE_SENTRY_DSN` 空 | 未接入（已决暂缓） |
| 对象存储 | 无 | — | 未使用任何 OSS / COS / TOS |
| 短信 / 推送 | 无 | — | 未使用 |

## 六、CI/CD 与凭据台账

| 项目 | 现状 |
| --- | --- |
| 代码托管 | GitHub `guanlili/english-speaking-assessment`（公开仓库） |
| 流水线 | GitHub Actions：`deploy.yml`（推送 master 自动部署）、`audit.yml`、`ops-watch.yml` |
| 部署方式 | SSH 到 `SERVER_HOST`（`ubuntu@49.232.156.221`，密钥 `~/.ssh/esa_ops`），`DEPLOY_PATH=/opt/speakup` 下拉代码 + `docker compose up` |
| Actions Secrets | 27 个：`SERVER_HOST` `SERVER_USER` `SERVER_SSH_KEY` `DEPLOY_PATH` `TLS_DOMAIN` `FRONTEND_HOST` `SECRET_KEY` `POSTGRES_*` `APP_POSTGRES_*` `PLATFORM_POSTGRES_*` `FIRST_SUPERUSER*` `FIRST_OPERATOR_EMAIL` `ARK_API_KEY` `ARK_TTS_API_KEY` `VOLC_ASR_API_KEY` `ASR_PROVIDER` `SCORING_PROVIDER` `AUDIO_TTL_DAYS` `COST_ALERT_EMAIL` `PROJECT_NAME` `COMPOSE_PROJECT_NAME` `APP_PORT` `DP_ID` `DP_KEY` |
| 主机定时任务 | 每日 03:30 `scripts/backup-local.sh`（DB dump + 音频打包 + manifest），失败写 `backups/backup-failure.log` |

## 七、迁移时必须处理的耦合点（按优先级）

1. **机器不是独占的** —— 先决定 Yujee / salesbot / hypit 的去向，再买公司机；否则新机只装 SpeakUp，老机还得为别的项目续费。
2. **DNS + 证书链路成对迁移** —— 域名解析迁火山 + acme.sh 换火山 DNS 插件，两者必须一起改；只改一个会导致证书续期静默失败。
3. **27 个 Actions Secret 全部要换** —— 除 `SERVER_HOST` 外，`DP_ID/DP_Key`（DNS 校验）、两套火山密钥（新企业账号重新生成）、`TLS_DOMAIN/FRONTEND_HOST` 随域名走。
4. **数据搬运顺序** —— 先备份包（13G，或按需只取最新一个 bundle）→ 新机恢复 DB → 恢复音频卷 → 起服务 → 按恢复清单验证，最后切 DNS（TTL 提前降 60s）。
5. **备案衔接** —— 主体和接入商都变，属新备案；旧个人备案必须保持有效直到新备案通过。

## 八、待确认项（我核不到，需要你确认）

- [ ] 这台机上的 Yujee、salesbot-landing、hypit：跟着迁、留老机、还是下线？
- [ ] 域名 `outman.website` 的注册商是谁、到期时间、是否已在个人名下（过户对象确定）
- [ ] CVM 带宽计费方式（按流量 / 按带宽），影响新机规格选型
- [ ] 是否顺带把备份异地副本一起做（迁移方案已列，成本约几元/月）

> 计划要买但还没用、因此不计入「在用资源」的：TOS 桶 ×2、企业邮箱 SMTP、Sentry、火山新账号的两套密钥。
