# 异地备份（阿里云 OSS）接线报告 — volc-belp

- 执行时间：2026-11-27 CST
- 主机：`volc-belp` 115.190.122.24，目录 `/srv/english-speaking-assessment`，compose 项目 `esa`
- 范围：备份脚本 / cron 注册 / 环境键透传 / 文档；**未动数据库、未动应用容器、未重启服务、未改生产网络**；凭证不写仓库
- 基线提交：`4011db1a61e6c22d58c7e3a74a9ab3527709bdc4`
- 厂商口径：按既定偏好使用**阿里云 OSS**（S3 兼容协议，rclone），不新增腾讯云 COS

## 结论速览

| # | 项 | 现状 | 说明 |
|---|----|------|------|
| 1 | 服务器 OSS 工具/凭证 | ❌ 均无 | 无 rclone / ossutil / aws 二进制；无 `~/.ossutilconfig`、rclone.conf、`~/.aws/credentials`；`.env` 无 OSS/ALIYUN 键 |
| 2 | 脚本 / cron / 配置透传 | ✅ 已就绪 | `scripts/backup-offsite.sh`（OSS/rclone）；deploy-prod.yml 注册 04:00 cron；5 个 OSS 键进白名单 / 默认值 / `.env.example` / workflow Secret 映射 |
| 3 | 无凭证演练 | ✅ 跳过退出 0 | 服务器临时副本 dry-run：缺凭证逐项提示后退出 0，未写远端、未产生 failure 日志 |
| 4 | 真实上传 / 远端校验 | ⬜ 待凭证 | 未做真实上传；对象路径、大小、SHA256 对账待 RAM 凭证 / bucket / endpoint 到位后按第 6 节清单执行 |
| 5 | 远端保留策略 | ✅ 代码就绪 | 按包名时间戳清理超期 bundle，窗口 14 天（与本地一致）；dry-run 只列不删 |

## 1. 只读盘点（volc-belp，2026-11-27）

### 1.1 工具与凭证排查

```
=== binaries ===
rclone: absent
ossutil: absent
ossutil64: absent
aws: absent
=== config files ===
(root / deploy 家目录) ~/.ossutilconfig、~/.config/rclone/rclone.conf、~/.aws/credentials：均无
=== .env OSS keys ===
(.env: no OSS/ALIYUN keys)
```

- 旧 `scripts/backup-offsite.sh` 为火山 TOS / tosutil 死代码：服务器未装 tosutil、无凭证、无 cron 引用；本次在仓库内改写为阿里云 OSS 实现，未在服务器侧残留旧配置。
- 生产 `.env` 中现有第三方密钥为火山 ASR/TTS、ARK 等，与 OSS 无关，本次未改动。

### 1.2 当前最新本地包（上传对象的候选源）

| 包名 | 大小 | database.sql.gz | audio.tar.gz | 备注 |
|------|------|-----------------|--------------|------|
| `bundle-20261126T234202Z-JC0q5nyp` | 1.6G | 2,902,905 B（sha256 `4a54e8ee…c0d81`） | 1,639,488,351 B（sha256 `95bc8473…109025`） | metadata：attempt_rows=4621，commit `4011db1`，在线快照 |

> 该包为 A 块补跑生成，属主 `deploy:deploy`、本地权限 700/600；A 块新脚本上线后新包为 750/640。offsite 脚本以 `deploy` 身份运行，读该包无问题。

## 2. 代码侧改动（独立分支，随最终统一部署上线）

| 文件 | 改动 |
|------|------|
| `scripts/backup-offsite.sh`（重写） | 目标由火山 TOS 改为阿里云 OSS（rclone，`type=s3`、`provider=Alibaba`）；远端名 `esaoss`，配置全部走 `RCLONE_CONFIG_ESAOSS_*` 环境变量注入，**不在磁盘落 rclone 配置文件**；选最新完整 bundle（包名排序、排除 `.BROKEN`），先 `verify-backup.sh` 核验可恢复性再上传；默认含音频，`OSS_WITH_AUDIO=0` 仅传 db/config/metadata/manifest；远端按包名时间戳清理 14 天前 bundle；失败写 `backups/offsite-failure.log` |
| `scripts/generate-deploy-env.sh` | 白名单与默认值补 5 个键：`OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`、`OSS_ENDPOINT`、`OSS_BUCKET`、`OSS_PREFIX`；留空即空值，不阻断部署 |
| `.env.example` | 补 OSS 配置块与注释（endpoint 示例、RAM 最小权限提示、凭证不入库） |
| `.github/workflows/deploy-prod.yml` | 5 个 Secret 映射进部署环境；幂等注册 offsite cron `0 4 * * *`（本地备份 03:30 之后），清理旧版同名 cron；脚本自行从 `.env` 读 OSS_*，失败追加 `offsite-failure.log` |
| `docs/backup-restore.md` | 双语同步：异地副本路径、启用条件与当前本地单副本风险说明 |

### 2.1 环境键口径

| 键 | 必填 | 默认 | 说明 |
|----|------|------|------|
| `OSS_ACCESS_KEY_ID` | 是 | — | RAM 子账号 AccessKey ID |
| `OSS_ACCESS_KEY_SECRET` | 是 | — | RAM 子账号 AccessKey Secret |
| `OSS_ENDPOINT` | 是 | — | 例 `https://oss-cn-beijing.aliyuncs.com`；同地域 ECS 可用内网 endpoint 省流量 |
| `OSS_BUCKET` | 是 | — | 备份桶名（ACL private） |
| `OSS_PREFIX` | 否 | `esa/<hostname>` | 桶内前缀 |
| `OSS_RETENTION_DAYS` | 否 | `14` | 远端保留窗口，按包名时间戳 |
| `OSS_WITH_AUDIO` | 否 | `1` | `0` = 仅传 db/config/metadata/manifest |
| `DRY_RUN` | 否 | `0` | `1` = rclone `--dry-run`，不写远端 |

### 2.2 透传链路与一致性

Secrets → `deploy-prod.yml` env 映射 → `generate-deploy-env.sh` 落生产 `.env` → offsite 脚本读取。`scripts/test_deploy.py` 的两条一致性断言覆盖：`.env.example` 键集合 == 生成键集合；非派生键必须在 workflow env 映射出现。本地 6 个部署回归用例全部通过。

## 3. 演练结果（无凭证路径，服务器 dry-run）

把新脚本临时拷到 volc-belp `/tmp`，以生产目录为 `PROJECT_DIR` 执行（未改生产文件、未上传）：

```
$ PROJECT_DIR=/srv/english-speaking-assessment DRY_RUN=1 bash /tmp/backup-offsite-oss-dryrun.sh
⏭ 未配置 OSS_ACCESS_KEY_ID，异地备份跳过
⏭ 未配置 OSS_ACCESS_KEY_SECRET，异地备份跳过
⏭ 未配置 OSS_ENDPOINT，异地备份跳过
⏭ 未配置 OSS_BUCKET，异地备份跳过
提示：配齐 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_ENDPOINT / OSS_BUCKET 后自动启用。
rc=0
(no failure log, expected)
```

- 缺任一凭证即安全跳过、退出 0，cron / 巡检不会因此变红；不写 failure 日志。
- 本地另做兜底解析验证：在临时目录 `.env` 写入示例 OSS 变量，脚本能从 `.env` 只补 `OSS_*`（不全量 source，避免 compose 序列化的 `$$` 被二次展开），过凭证检查后停在「rclone 未安装」前置检查——符合预期（服务器尚未装 rclone）。
- 临时脚本已从服务器删除。

## 4. 未覆盖 / 现状边界

- **未真实上传**：无凭证、无桶、无 endpoint；未产生远端对象，未做远端 SHA256 对账。
- **rclone 未安装**：凭证到位后需在服务器安装一次（见第 6 节）；脚本对缺 rclone 给出明确报错退出 1。
- **远端告警**：当前上传/清理失败只追加本地 `backups/offsite-failure.log`；邮件 / Webhook 告警复用 B 块 GlitchTip / SMTP 通道，本次未单独接线。
- **生命周期兜底**：远端 14 天清理由脚本按包名执行；bucket 侧生命周期规则（到期自动删除 / 转冷归档）可作后端兜底，本次未配置。
- `docs/cutover-to-volc-2026-11.md` 中 TOS / tosutil 表述为 11 月迁移历史记录，本次不回溯改写；现行口径以本报告与 `docs/backup-restore.md` 为准。

## 5. 需要用户提供 / 决策的点

| # | 项 | 需要的内容 |
|---|----|-----------|
| 1 | RAM 凭证 | 子账号 AccessKey ID / Secret，仅授目标 bucket 的 `oss:GetObject` / `oss:PutObject` / `oss:DeleteObject` / `oss:ListBucket`（不要主账号 AK） |
| 2 | Bucket | 桶名、所在地域；建议独立备份桶、ACL private、关闭公共读 |
| 3 | Endpoint | 公网 endpoint 或同地域内网 endpoint（ECS 到 OSS 同地域走内网免流量费） |
| 4 | 上传范围 | 是否含音频卷（默认含，1.6G/包；`OSS_WITH_AUDIO=0` 仅传 db/config/metadata/manifest） |
| 5 | 远端窗口 / 归档 | 14 天窗口是否沿用；是否需要生命周期转冷归档或更长期版本保留 |

## 6. 凭证到位后执行清单（可执行）

1. 服务器安装 rclone（二选一，按 macOS/服务器包管理偏好）：
   ```bash
   # Ubuntu 22.04+：
   apt-get update && apt-get install -y rclone
   # 或官方静态包到 /usr/local/bin（版本以 rclone 官方为准）
   ```
2. 写入 GitHub production Secrets（本地 Mac，gh CLI）：
   ```bash
   printf '<AK>'     | gh secret set OSS_ACCESS_KEY_ID --repo guanlili/english-speaking-assessment --env production
   printf '<SECRET>' | gh secret set OSS_ACCESS_KEY_SECRET --repo guanlili/english-speaking-assessment --env production
   printf '<ENDPOINT>' | gh secret set OSS_ENDPOINT --repo guanlili/english-speaking-assessment --env production
   printf '<BUCKET>'  | gh secret set OSS_BUCKET --repo guanlili/english-speaking-assessment --env production
   # OSS_PREFIX 可选
   ```
3. 触发最终统一部署（`Deploy Production` workflow_dispatch）：Secrets 经 `generate-deploy-env.sh` 落生产 `.env`，并注册 04:00 offsite cron。
4. 手工首跑（先 dry-run 确认选择与路径，再真实上传）：
   ```bash
   cd /srv/english-speaking-assessment
   DRY_RUN=1 bash scripts/backup-offsite.sh   # 只列动作，不写远端
   bash scripts/backup-offsite.sh             # 真实上传 + 远端清理
   ```
5. 远端校验（对象路径 / 大小 / SHA256）：
   ```bash
   rclone lsf "esaoss:<bucket>/<prefix>/" --dirs-only
   # 下载回传后与本地 manifest.sha256 对账：
   rclone copy "esaoss:<bucket>/<prefix>/<stamp>/database.sql.gz" /tmp/oss-verify/
   sha256sum /tmp/oss-verify/database.sql.gz   # 与本地 manifest 对应行比对
   ```
6. 次日巡检：`crontab -l | grep backup-offsite`；`tail backups/offsite-failure.log`（无新条目即成功）；确认远端出现当日新 bundle 且 14 天前旧包被清理。

## 7. 安全与边界

- 凭证只走受限 `.env`（`deploy:deploy` 0640 级）/ GitHub Secret；不出现在命令行历史、仓库、日志；rclone 配置不落盘，由环境变量注入。
- bucket ACL private；RAM 子账号最小权限。
- 未改动生产 `.env` 无关配置；未读导出学生个人信息入库；不上传腾讯云 COS。
