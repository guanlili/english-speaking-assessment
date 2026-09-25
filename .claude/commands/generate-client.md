# 重新生成前端 API 客户端

后端接口有新增或修改后，同步更新前端的自动生成客户端代码。

## 何时需要执行

- 新增了 API 路由
- 修改了接口的请求/响应数据结构
- 修改了 Pydantic 模型

## 执行步骤

1. 确认后端正在运行（脚本需要从 backend 容器导出 OpenAPI 规范）：
   ```bash
   docker compose ps backend
   ```
   没在运行则先 `docker compose up -d`。

2. 生成客户端（脚本会依次：导出 openapi.json → openapi-ts 生成代码 → biome 格式化）：
   ```bash
   cd frontend && npm run generate-client
   ```

3. 检查 `frontend/src/client/` 目录下的变更，确认新接口已生成

注意：
- `frontend/src/client/` 目录是自动生成的，不要手动修改里面的文件
- `frontend/openapi.json` 是中间产物，已被 gitignore，不需要提交
