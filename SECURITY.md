# 安全策略

## 报告漏洞

**不要**为安全漏洞建公开 Issue。请私下联系仓库维护者，提供：

- 影响范围（哪个端点 / 哪个流程 / 哪份数据）
- 复现步骤与环境
- 如果有，建议的修复方向

收到后会确认收到，并告知是否受理与大致处理计划。
## 范围

**属于本仓库**：`backend/`、`frontend/` 的代码、`.github/workflows/` 的 CI 配置、`scripts/` 的部署与回滚脚本、`docker-compose*.yml`。

**不属于本仓库**：第三方依赖自身的漏洞。请向上游报告；本仓库通过 `依赖审计` workflow 每周扫描 pip 与 npm 生产依赖（`high` 及以上），发现问题会另行处置。

## 已实施的防护（供评估时参考）

- 生产 `.env` 由部署流水线从 GitHub Secrets 生成，不手改、不提交
- 多租户 RLS 在生产强制；跨校访问按 404 处理，不泄露存在性
- 测试库与开发库隔离：`POSTGRES_DB_TEST` 与 `POSTGRES_DB` 相同时，`conftest` 会在任何建表/删数据操作前直接拒绝运行
- 合并闸门：`master` 要求 CI 全绿 + 分支与最新 master 同步（`strict`），管理员也不能绕过
- 凭据与学生个人信息不入库（见 `docs/project-management.md`）
