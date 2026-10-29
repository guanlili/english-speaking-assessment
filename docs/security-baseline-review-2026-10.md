# 安全基线复核留档（2026-10-30）/ Security baseline review

> 对应《平台安全保障方案》短期计划第 6 项「安全基线复核」。只读复核，未改动任何服务器配置；带 ⚠ 的项需要拍板后处置。

### 端口与暴露面（腾讯 CVM bjfu-training，49.232.156.221）

| 端口 | 归属 | 对外 | 结论 |
|---|---|---|---|
| 443 / 80 | speakup-frontend（BELP 生产站） | 是 | ✅ 预期（HTTPS + 301 跳转） |
| 22 | sshd | 是 | ✅ 预期；PasswordAuthentication **no**（仅密钥） |
| 8080 | **yujee-web-1**（另一项目） | 是 | ⚠ 非 BELP 服务，共享服务器上对外暴露；建议加安全组白名单或收敛为本地反代，由 Yujee 侧决定 |
| 5432 (db) | speakup-db / yujee-postgres | 否（仅容器网络） | ✅ 未发布宿主端口 |
| 8001 / 8002 / 8787 | yujee 内部容器 | 仅本地/容器 | ✅ |
| backend | speakup-backend | 否（经 frontend 反代） | ✅ |

### SSH 与账号

| 项 | 现状 | 结论 |
|---|---|---|
| 密码认证 | 关闭 | ✅ |
| root 登录 | `PermitRootLogin yes` | ⚠ 建议 `prohibit-password`（当前仅密钥可登录，实际风险有限，但按最小权限应收紧；改动需先确认无 root 密钥登录依赖，改完保持会话验证） |
| 有 shell 的系统账号 | ubuntu、lighthouse（腾讯云组件） | ✅ 符合预期 |
| 失败登录（10-23 起） | 0 次 | ✅ |

### 备份与恢复（同日完成演练，详见 docs/backup-restore.md 演练记录）

- 03:30 cron 正常产出完整包（四件套校验 OK）；隔离库恢复演练通过，行数与快照口径一致，音频抽验完整。
- 结构性短板不变：无异地副本（安全方案短期计划第 1 项，待云侧拍板）。

### 处置清单

1. ⚠ yujee 8080 对外：转 Yujee 侧决策（白名单/收敛/维持）。
2. ⚠ PermitRootLogin yes → prohibit-password：一行 sshd 配置，需李梨确认执行窗口。
3. 异地备份 / 告警 SMTP 凭据 / 用户协议页：分别依赖云侧决策、凭据提供、法务文案，见安全方案短期计划。
