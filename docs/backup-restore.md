# 本地完整备份与恢复 / Local backup and recovery

## 备份 / Backup

生产 Linux 主机需要 Docker Compose、bash、flock、gzip、tar 和 sha256sum。部署后由流水线维护每天 03:30 的唯一 cron；不要重复注册。手动备份：

The Linux host requires Docker Compose, bash, flock, gzip, tar, and sha256sum. Deployment registers one daily job at 03:30 in the server's timezone. Run manually from the repository:

```bash
bash scripts/backup-local.sh
bash scripts/verify-backup.sh /absolute/path/to/backups/bundle-TIMESTAMP-ID
```

每个完整目录含 `database.sql.gz`（SQL）、`audio.tar.gz`（`/app/audio` 全卷，包括录音与标准音）、`config.env`（配置与密钥）、`metadata.txt`（提交与时间）和 `manifest.sha256`。只有所有步骤成功才发布目录；保留 14 天。执行失败退出非零，cron 记入 `backups/backup-failure.log`。目录和文件仅属主可读，**不得提交、共享或放进可公开下载的目录**。旧版 SQL/配置备份同样保留 14 天，完整新包成功后才清理到期文件。

A bundle contains the SQL dump, the entire audio volume, deployment configuration (including secrets), commit/time metadata, and checksums. It is published only after every step succeeds. Retention is 14 days; failures return nonzero and cron records their timestamps. Keep bundles private and outside Git/public download directories. Legacy SQL/config backups also retain 14 days and expire only after a complete new bundle succeeds.

在线备份跨数据库与音频卷不是原子快照。需要严格一致时，先在入口暂停作答/内容写入，等待评分结束再备份；不要在评分中停止服务。记录实际备份和恢复耗时。当前**没有异地副本**，整机磁盘故障仍可能丢失所有本地备份。

Online database/filesystem backups are not atomic. For strict consistency, pause new writes at ingress and let scoring finish before backing up. Record actual backup and restore times. Off-site upload is disabled; local backups do not survive loss of the host disk.

## 隔离恢复演练 / Isolated recovery drill

只恢复到**全新的隔离主机或 Compose 项目**，不用现有生产/开发/测试库。先检验备份，不要将校验失败的数据用于恢复。下列命令在隔离项目目录执行，`/safe/backup` 为已通过校验的完整包。

Restore only into a new isolated host or Compose project, never an existing production/development/test database. Verify before restoring. Run the following in the isolated project directory; `/safe/backup` is the verified bundle:

1. 检出 `metadata.txt` 中的提交。通过部署 Secrets 配好新的 `.env`，使用不同的 `COMPOSE_PROJECT_NAME`、端口及 `POSTGRES_DB`（如 `recovery_drill_20261015`）。参考 `config.env` 恢复必要的 `SECRET_KEY` 等，但不要覆盖生产 Secrets，也不要启动邮件或付费评分。

   Check out the recorded commit. Prepare a separate `.env` using a distinct Compose project name, ports, and database (for example `recovery_drill_20261015`). Recover required keys from the private config snapshot without overwriting production Secrets. Disable outgoing email and paid scoring during the drill.

2. 只启动新数据库；**先导入 dump，再启动后端和迁移**，避免种子数据与 dump 冲突。

   Start only the new database; import the dump before starting the application or migration/seed jobs.

   ```bash
   docker compose -f compose.yml up -d db
   # Wait until the new database is healthy before continuing.
   gzip -dc /safe/backup/database.sql.gz | docker compose -f compose.yml exec -T db sh -c 'psql --set ON_ERROR_STOP=on -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
   ```

   在 bash 中先执行 `set -o pipefail`，确保解压或 SQL 错误都使恢复失败。任一步失败就弃用该隔离库重新演练，不能将半恢复结果视为成功。

   Enable `set -o pipefail` in bash so decompression and SQL failures both abort. Discard a partially restored isolated database and start again after any error.

3. 构建后端镜像，将音频导入**空的新卷**；还没有启动后端。恢复包须为自己生成且已校验的可信包。命令在目标卷非空时拒绝写入。

   Build the backend image and restore trusted, verified audio into a new empty volume before starting the backend. This command refuses a nonempty volume:

   ```bash
   docker compose -f compose.yml build backend
   docker compose -f compose.yml run --rm --no-deps -T --entrypoint sh backend -c 'test -z "$(ls -A /app/audio)" && tar -C /app/audio -xzf -' < /safe/backup/audio.tar.gz
   docker compose -f compose.yml up -d --build
   ```

4. 验证 `/api/v1/utils/ready-check/`，登录教师与学生账号，核对课堂、发布快照和历史成绩，实际回放一条录音和一条标准音。仅校验和通过不等于业务恢复完成。记录结果及耗时，演练成功后再按实际事故制定生产切换方案。

   Check readiness, teacher/student login, classrooms, published snapshots, historical results, and actual playback of one recording and one content audio file. Checksums alone do not prove successful recovery. Record the outcome and duration before planning any production cutover.

## 演练记录 / Drill log

### 2026-10-30 隔离库演练（zocode 执行）

| 项 | 结果 |
|---|---|
| 备份包 | `bundle-20261028T193117Z-VJ0QnxZE`（2026-10-29 03:30 本机时间，commit `5c4ae79`；当月 cron 修复后的首个完整包） |
| 校验 | `scripts/verify-backup.sh` 四件套全部 OK |
| 数据库恢复 | 在生产 db 容器内**新建隔离库** `recovery_drill_20261030` 导入 dump，`ON_ERROR_STOP=on` 全程无错；建库 + 导入共约 1 秒（dump 1.3 MB） |
| 行数比对 | user 262=262、student 364=364、classroom 20=20、scenario_question/passage/repeat_sentence/sentence_frame 全一致；attempt 2763（生产 4533）、practice_session 323（396）、changelog 23（28）——差异全部为备份时点之后的当日使用（10-29 单日 +1770 作答）与当日新增条目；vocab_level_entry 备份为 0 属实（五级词库 10-29 白天生产首导） |
| 音频包 | 3,032 个文件；抽验 `04f1334b-….m4a` 19,067 B 完整解出；生产当前 5,011 个文件（备份后当日新增，属预期增长） |
| 清理 | 演练库已 `DROP`，临时文件已清，未触碰生产库 |
| 未覆盖 | 未做整栈拉起、登录与录音回放——下一档演练按上文「隔离恢复演练」在独立 Compose 项目执行 |

Drill against `bundle-20261028T193117Z-VJ0QnxZE`: checksums OK; the dump restored into an isolated database inside the production DB container in ~1s with `ON_ERROR_STOP=on`; per-table counts match snapshot semantics (all deltas are post-backup activity, including the same-day five-level vocab import); one audio member extracted intact; the drill database was dropped afterwards. Full isolated-host bring-up with login/playback remains the next-level drill.
