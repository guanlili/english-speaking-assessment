# 新建功能模块

按标准模式创建一个完整的功能模块（后端 + 前端）。

## 参数

$ARGUMENTS — 功能名称，例如 `order`（订单）、`product`（产品）

## 执行步骤

1. **后端 Model**：在 `backend/app/models.py` 中添加 SQLModel 数据模型（参考现有 Item 模型的写法）

2. **后端 CRUD**：在 `backend/app/crud.py` 中添加对应的增删改查函数

3. **后端路由**：新建 `backend/app/api/routes/$ARGUMENTS.py`，参考 `items.py` 的结构，实现标准 REST 接口（GET list、GET by id、POST、PUT、DELETE）

4. **注册路由**：在 `backend/app/api/main.py` 中 include 新路由

5. **数据库迁移**：
   ```bash
   docker compose exec backend alembic revision --autogenerate -m "add $ARGUMENTS table"
   docker compose exec backend alembic upgrade head
   ```

6. **后端测试**：新建 `backend/tests/api/routes/test_$ARGUMENTS.py`，参考 `test_items.py` 的结构，覆盖增删改查和权限（普通用户不能操作他人数据）。本地运行验证（backend 镜像不含 pytest，测试在宿主机跑，连 compose 暴露的 5432 数据库）：
   ```bash
   cd backend && POSTGRES_SERVER=localhost uv run pytest tests/api/routes/test_$ARGUMENTS.py -v
   ```

7. **重新生成前端客户端**（需要 backend 容器在运行）：
   ```bash
   cd frontend && npm run generate-client
   ```

8. **前端页面**：新建 `frontend/src/routes/_layout/$ARGUMENTS.tsx`，参考 `items.tsx` 的结构，实现列表页 + 新增/编辑弹窗

9. **导航链接**：在 `frontend/src/components/Sidebar/Main.tsx` 的导航项中添加新页面的入口

完成后告知用户，并列出所有新建/修改的文件，确认测试全部通过。
