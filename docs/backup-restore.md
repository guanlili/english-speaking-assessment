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

**一条命令版**（脚本化上面四步，自动建包、建独立项目、比对全库行数、登录核对、清理）：

```bash
bash scripts/recovery-drill.sh              # 现场生成备份包并演练，结束后清理独立项目
bash scripts/recovery-drill.sh --bundle backups/bundle-...   # 用已校验的包
bash scripts/recovery-drill.sh --keep       # 失败或需保留现场时不清理
```

脚本固定使用独立 Compose 项目 `esa-drill` 与库名 `recovery_drill_<YYYYMMDD>`，只启动 `db/prestart/backend`，不发布端口、不启前端与 acme，因此不会与运行中的栈抢端口或串库。任一项不过（行数差异、登录失败）会保留现场并以非零退出。

下面是等价的手工步骤，供没有脚本或需要逐步排查时使用。只恢复到**全新的隔离主机或 Compose 项目**，不用现有生产/开发/测试库。先检验备份，不要将校验失败的数据用于恢复。下列命令在隔离项目目录执行，`/safe/backup` 为已通过校验的完整包。

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

### 2026-11-14 整栈演练（Mac Mini 开发栈，脚本化）

| 项 | 结果 |
|---|---|
| 执行方式 | `bash scripts/recovery-drill.sh`（一条命令：建包→校验→独立项目→导入→音频→拉起→核对→清理） |
| 备份包 | `bundle-drill-20261114T140340Z-afb4ec`（现场从本机栈生成，`verify-backup.sh` 四件套 OK） |
| 独立环境 | Compose 项目 `esa-drill` + 库 `recovery_drill_20261114`，未发布端口、未启前端/acme |
| 数据库恢复 | dump 导入约 2s，`ON_ERROR_STOP=on` 无错；`prestart`（alembic + 角色 + 种子）退出 0 |
| 行数比对 | **39 张 public 表逐表精确计数，0 处差异**（user 15、student 1、classroom 10、scenario_question 27、sentence_frame 12 等） |
| 就绪与登录 | `ready-check` 返回 200；`FIRST_SUPERUSER` 走 `/api/v1/login/access-token` 登录成功 |
| 音频 | 源栈音频卷为空（0 个文件），恢复链路执行成功但**未验证回放** |
| 清理 | 独立项目与三个卷已 `down -v` 清理，未触碰运行中栈 |
| 未覆盖 | 生产数据规模、真实录音回放、成绩历史核对、单校恢复路径 |

本轮验证的是**机制**（脚本与恢复链路能在独立环境跑通并自动判据），不是业务恢复结论：本机栈只有 15 个用户、1 名学生、0 次作答，音频卷为空，数据量与生产不可比。生产主机上的一次真实演练仍待执行，届时用同一命令并保留 `--bundle` 指向生产已校验包。

**已知限制**：本机（macOS）没有 `flock`，`scripts/backup-local.sh` 无法直接运行（它是给 Linux 生产主机和 cron 用的）；演练脚本因此自带建包步骤，不复用该脚本。镜像仓库不可达时脚本会复用本机已有 `esa-backend` 镜像，不再拉取构建依赖。
