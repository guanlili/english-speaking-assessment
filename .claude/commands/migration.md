# 创建数据库迁移

当 `backend/app/models.py` 有改动后，生成并应用 Alembic 迁移文件。

## 参数

$ARGUMENTS — 迁移描述，例如 `add user avatar field`

## 执行步骤

1. 确认 docker compose 正在运行（`docker compose ps` 查看 backend 状态）

2. 生成迁移文件：
   ```bash
   docker compose exec backend alembic revision --autogenerate -m "$ARGUMENTS"
   ```

3. 检查生成的迁移文件（在 `backend/app/alembic/versions/` 下），确认 upgrade/downgrade 函数内容正确

4. 应用迁移：
   ```bash
   docker compose exec backend alembic upgrade head
   ```

5. 验证表结构已更新：
   ```bash
   docker compose exec db psql -U postgres -d app -c "\d 表名"
   ```
