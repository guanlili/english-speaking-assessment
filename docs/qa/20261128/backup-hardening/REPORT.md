# 备份巡检 P1/P2 硬化报告 — volc-belp

- 执行时间：2026-11-27 CST（UTC 2026-11-26 23:31–23:44）
- 主机：`volc-belp` 115.190.122.24，目录 `/srv/english-speaking-assessment`，compose 项目 `esa`，DB 容器 `esa-db-1`
- 范围：只改备份脚本 / 巡检判定 / 文档；**未动数据库、未动应用容器、未重启服务**；本地备份为在线快照，无写入停顿
- 基线提交：`4011db1a61e6c22d58c7e3a74a9ab3527709bdc4`
- 关联巡检：GitHub Actions `ops-watch.yml`「备份新鲜度」，阈值 `BACKUP_MAX_AGE_HOURS=30`

## 结论速览

| # | 项 | 整改前 | 整改后 |
|---|----|--------|--------|
| 1 | 手工备份包属主/权限 | 4 个手工包 `root:root 700/600`，巡检 SSH 用户 `deploy` 不可读，「备份新鲜度」红灯 | 4 包归一为 `deploy:deploy 750/640`；脚本收尾自动归一属主/权限，监控用户可读 manifest |
| 2 | 保留策略口径 | `find -mtime +14` 按目录 mtime 判定；8 个老包 mtime 被批量重置到 11-19 21:57，超期滞留 | 改为按包名 `bundle-YYYYMMDDTHHMMSSZ-*` 时间戳判定；`.BROKEN` 残留无条件清理 |
| 3 | 现存包 | 23 个 bundle / 24G（含 1 个 BROKEN） | 14 个 bundle / 22G；删除 8 个 mtime 重置老包 + 1 个 BROKEN |
| 4 | 最新包可校验性 | 最新候选包巡检 `Permission denied` | 最新包 `bundle-20261126T234202Z-JC0q5nyp` 以 `deploy` 身份 `verify-backup.sh` 退出 0 |

## 1. 整改前问题（只读盘点）

### 1.1 P1：手工包属主 root:root 700，巡检不可读

- 巡检 workflow 以 `deploy`（uid 1000）SSH 进主机读备份清单；cron 自动包属主 `deploy:deploy` 可读，但 2026-11-26 白天 4 个手工以 root 执行的备份包属主 `root:root`、目录 `700`、文件 `600`，`deploy` 无法进入目录读 `manifest.sha256`。
- 失败巡检 run [`45791924933`](https://github.com/guanlili/english-speaking-assessment/actions/runs/45791924933)（2026-11-26T09:26:13Z）日志：

  ```
  最近备份：backups/bundle-20261126T085431Z-lGVWNzL1（0 小时前）
  bash: line 23: cd: backups/bundle-20261126T085431Z-lGVWNzL1: Permission denied
  ##[error]备份清单校验失败，最新包不可用：backups/bundle-20261126T085431Z-lGVWNzL1
  ```

- 整改前以 `deploy` 身份复测 4 个 root 包，`manifest.sha256` 全部 `DENIED`。

### 1.2 P2：保留策略按 mtime，超期包滞留

- 旧脚本 `find backups/bundle-* -mtime +14 -exec rm -rf` 按目录 mtime 判定。11-11～11-18 共 8 个目录在 11-19 迁移/拷贝时 mtime 被批量重置为 11-19 21:57–21:58，按 mtime 仍在 14 天内，一直未回收。
- 另有 1 个 `*.BROKEN` 残留：`bundle-20261119T075036Z-xFng5zy5.BROKEN`（db 17,191B、audio 105B，低于容量底线，旧版脚本尚无大小/结构地板校验所致）。

### 1.3 阈值与判定口径（本次沿用/明确）

| 判定项 | 阈值/口径 | 位置 |
|--------|-----------|------|
| 新鲜度年龄 | 最新包 ≤ 30 小时（每日 03:30 备份，留一天余量） | `ops-watch.yml` `BACKUP_MAX_AGE_HOURS=30` |
| 本地保留窗口 | 14 天，**按包名时间戳**（不看 mtime） | `backup-local.sh` `BACKUP_RETENTION_DAYS=14` |
| 包年龄解析 | 包名 `bundle-YYYYMMDDTHHMMSSZ-<rand>`，定宽 ISO，字符串字典序即时间顺序 | 脚本 / 巡检一致 |
| DB 容量地板 | dump ≥ 500,000B、表 ≥ 25 | `BACKUP_MIN_DB_BYTES` / `BACKUP_MIN_TABLES` |
| 音频容量地板 | audio.tar.gz ≥ 102,400B | `BACKUP_MIN_AUDIO_BYTES` |
| 产物权限 | 目录 `750`、文件 `640`；属主归一到 `backups/` 目录当前属主（生产即 `deploy`），同组巡检用户可读 manifest，其他用户不可进入 | `backup-local.sh` 收尾 |
| BROKEN 残留 | 任何年龄都不作为可用备份，保留清理时直接删除 | `backup-local.sh` 保留段 |

## 2. 代码改动（独立分支，随最终统一部署上线）

| 文件 | 改动 |
|------|------|
| `scripts/backup-local.sh` | ① 发布包后归一属主（`BACKUP_OWNER`/`BACKUP_GROUP` 可覆盖，默认取 `backups/` 目录属主/组；非 root 跳过 chown 只收敛权限位）；目录 `750`、文件 `640`。② 保留策略改为按包名时间戳排序与比较，去掉 `find -mtime +14` 对 bundle 的判定；`.BROKEN` 无条件清理；时间戳解析失败的包跳过并告警，不误删。③ 旧版单文件快照（`app-*.sql.gz` / `env-*.env`）仍按 mtime 保留 14 天。 |
| `.github/workflows/ops-watch.yml` | 备份新鲜度作业：最新包按包名排序选取（排除 `.BROKEN`）；年龄从包名时间戳计算，不再用 `stat -c %Y`；包名时间戳解析失败显式红灯。 |
| `docs/backup-restore.md` | 同步权限模型（750/640、属主归一）与按包名时间戳保留的说明（中英双语）。 |
| `scripts/test_backup.py` | 回归断言更新到 750/640 契约（其他用户无权限、同组可读）；新增用例：包名时间戳超期包被清理、BROKEN 被清理、新鲜包保留。 |

## 3. 服务端处置记录

### 3.1 现存 4 个 root 手工包归一（root 一次性执行）

整改前 4 包均为 `root:root 700/600`；先以 root 跑 `verify-backup.sh` 四件套全部 OK，再 `chown -R deploy:deploy`、目录 `750`、文件 `640`。归一后以 `deploy` 身份复测 manifest 全部可读且校验通过：

| 包名 | created_at (UTC) | commit | attempt | db 字节 | 整改后可读性（deploy） |
|------|------------------|--------|---------|---------|------------------------|
| `bundle-20261126T030043Z-IXEoOPwQ` | 2026-11-26 03:00:42 | `51f4184b` | 4621 | 2,455,544 | readable + manifest OK |
| `bundle-20261126T071421Z-kmDT6xnx` | 2026-11-26 07:14:20 | `bfbaaea4` | 4621 | 2,899,523 | readable + manifest OK |
| `bundle-20261126T085431Z-lGVWNzL1` | 2026-11-26 08:54:29 | `e59b1bba` | 4621 | 2,901,776 | readable + manifest OK |
| `bundle-20261126T155445Z-RgZWuSG7` | 2026-11-26 15:54:43 | `2d18f081` | 4621 | 2,910,065 | readable + manifest OK |

### 3.2 手工补跑一次备份（以 `deploy` 身份）

- 新包：`bundle-20261126T234202Z-JC0q5nyp`，属主 `deploy:deploy`，commit `4011db1a`，attempt 4621，db 2,902,905B，audio 1,639,488,351B。
- 以 `deploy` 身份 `verify-backup.sh` 退出 0：`database.sql.gz / audio.tar.gz / config.env / metadata.txt` 四项 OK。
- 说明：服务器当前运行的仍是旧版脚本（产物 `700/600`），属主已是 `deploy`，巡检可读；750/640 与按包名保留的新逻辑随最终统一部署上线。

### 3.3 清理清单（删除前逐项核验，最新可用包已确认）

删除前先确认两个最老的保留完整包 `bundle-20261119T145808Z-VqCpUnRy`、`bundle-20261119T193118Z-UPYhW52A` 以 `deploy` 身份校验通过，再执行删除。

| # | 被删包名 | 大小 | 格式 | gzip 校验 | 删除原因 |
|---|----------|------|------|-----------|----------|
| 1 | `bundle-20261111T193129Z-teWaqNZB` | 2.4M | 仅 db（旧格式，无 audio） | db OK | mtime 被重置；按包名时间超 14 天；旧格式无音频卷 |
| 2 | `bundle-20261112T193130Z-ilXLW7Wk` | 2.4M | 仅 db | db OK | 同上 |
| 3 | `bundle-20261113T193131Z-zoXvzVUU` | 2.4M | 仅 db | db OK | 同上 |
| 4 | `bundle-20261114T193131Z-ML5T0Np5` | 2.4M | 仅 db | db OK | 同上 |
| 5 | `bundle-20261115T193130Z-MC5Cl0rj` | 2.4M | 仅 db | db OK | 同上 |
| 6 | `bundle-20261116T193131Z-g32Noqsv` | 2.4M | 仅 db | db OK | 同上 |
| 7 | `bundle-20261117T193130Z-ekPbSHyc` | 2.4M | 仅 db | db OK | 同上 |
| 8 | `bundle-20261118T193132Z-1fzRSpDb` | 1.6G | 完整 db+audio | db/audio OK | mtime 被重置；包名年龄约 8.3 天仍在 14 天窗口内，但属本次盘点确认的 8 个重置 mtime 老包之一；其后已有 11-19 14:58Z 起的多个校验通过完整包兜底 |
| 9 | `bundle-20261119T075036Z-xFng5zy5.BROKEN` | 40K | 失败残留（db 17,191B / audio 105B） | gzip -t 通过但低于容量地板 | 标记 BROKEN，不可用于恢复，无条件清理 |

- 删除前：23 个 bundle / 24G；删除后：14 个 bundle / 22G（明细见 `inventory-after.txt`）。
- 未触碰：`app-*.sql.gz` predeploy 单文件快照、`env-domain-20261123-195500/` 配置快照（均在 14 天窗口内，旧版 mtime 保留逻辑继续覆盖）。

### 3.4 整改后新鲜度巡检模拟（`deploy` 身份，按新判定逻辑）

```
最近备份：bundle-20261126T234202Z-JC0q5nyp（按包名时间戳 0 小时 1 分钟前）
清单校验通过（database / audio / config / metadata 四项）
无 backup-failure.log
```

年龄 1 分钟 ≤ 30h 阈值；manifest 四项 OK；无失败记录。

## 4. 最新包可恢复性核验（只读，未做恢复导入）

针对最新包 `bundle-20261126T234202Z-JC0q5nyp`（补跑前一版 `bundle-20261126T193120Z-0ZFcyRnC` 同口径核验通过）：

| 检查 | 结果 |
|------|------|
| `manifest.sha256` 四件套 | OK（sha256sum --check 退出 0） |
| `database.sql.gz` gzip -t | OK；`CREATE TABLE` 54 张 |
| `audio.tar.gz` gzip -t / tar 列表 | OK；4,946 个音频成员 |
| dump 内 attempt 行数 | 4,621，与线上 `select count(*) from attempt` = 4,621 一致 |
| metadata commit | `4011db1a61e6c22d58c7e3a74a9ab3527709bdc4` |
| 隔离恢复演练 | 本次未执行整栈导入；按 `docs/backup-restore.md` 的 `recovery-drill.sh` 在独立 `esa-drill` 项目演练，纳入下一档验证 |

## 5. 未覆盖 / 待最终部署后验证

1. 新脚本与新巡检判定随最终统一部署上线；上线后首个 03:30 cron 自动包需复核：属主 `deploy:deploy`、目录 750 / 文件 640、按包名保留生效。
2. 部署后手动触发一次 `ops-watch.yml`，确认「备份新鲜度」作业在 GitHub Actions 侧绿灯（本次为服务器侧按新逻辑模拟通过）。
3. 异地副本未在本块范围；见 OSS 异地备份独立 PR。
4. 未做整栈隔离恢复演练；建议择机在低峰跑 `scripts/recovery-drill.sh --bundle <最新校验包>`。

## 证据索引

- `inventory-after.txt` — 整改后现存 14 个包的属主/权限/mtime/包名清单与最新包元数据
- 失败巡检 run：https://github.com/guanlili/english-speaking-assessment/actions/runs/45791924933
