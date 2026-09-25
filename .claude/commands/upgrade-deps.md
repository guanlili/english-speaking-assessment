# 升级依赖包

定期维护任务，将后端 Python 包和前端 npm 包升级到最新版本。

## 执行步骤

1. **升级后端依赖**（uv workspace，lock 文件在仓库根目录）：
   ```bash
   uv lock --upgrade
   ```
   检查 `uv.lock` 的变更，关注主要包（fastapi、sqlmodel、pydantic）的版本变化

2. **升级前端依赖**：
   ```bash
   cd frontend && npm update
   ```
   检查 `frontend/package.json` 和 `frontend/package-lock.json` 的版本变化。
   如需跨大版本升级，用 `npx npm-check-updates -u && npm install`，并逐个确认 breaking changes。

3. **验证后端正常启动**：
   ```bash
   docker compose up --build backend
   ```
   确认没有 import 错误或启动报错

4. **验证前端生产构建**：
   ```bash
   docker compose -f compose.yml build frontend
   ```
   （用 `-f compose.yml` 构建生产镜像，验证 tsc + vite build 全链路）

5. 如有报错，查看具体包的 changelog，按需调整代码。
   若 Docker 构建报 `Cannot find native binding`（npm 跨平台 lockfile bug），执行：
   ```bash
   bash frontend/scripts/regen-lockfile.sh
   ```

6. 一切正常后提交：
   ```bash
   git add uv.lock frontend/package.json frontend/package-lock.json
   git commit -m "chore: upgrade dependencies"
   ```
