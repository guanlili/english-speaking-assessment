# AI Development Guidelines & Coding Standards

This project is a Full Stack application using **FastAPI** (Backend) and **React + Vite** (Frontend).
Follow these guidelines to ensure code stability, consistency, and maintainability.

## 1. Technology Stack

### Backend (`/backend`)
- **Framework**: FastAPI (Python 3.14，见 `pyproject.toml` 的 `requires-python`；代码可使用 3.14 语法特性)
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **Database**: PostgreSQL (via Docker)
- **Package Manager**: uv
- **Linting**: Ruff (strict adherence required)
- **Type Checking**: ty (Astral, error-on-warning)

### Frontend (`/frontend`)
- **Framework**: React 19
- **Build Tool**: Vite
- **Language**: TypeScript
- **Styling**: TailwindCSS v4
- **State/Data**: TanStack Query (React Query)
- **Routing**: TanStack Router
- **UI Components**: Radix UI + Lucide React (Icons)
- **Linting/Formatting**: Biome

## 2. Coding Conventions

### 三端自适应（必须）

桌面/手机/平板（iPad 为主力学生设备）三端可用（CLAUDE.md「三端自适应准则」为权威说明）：

- 原生表单控件字号全断点 `text-base`（≥16px，防 iOS 聚焦放大）
- 触控目标高频 ≥44px / 低频 ≥40px；操作不得仅 hover 可达
- 表格走 `ui/table.tsx` + 宽表加滑动提示；高度用 svh/dvh
- 新页面在 390/820/1180 三档宽度自查无横向溢出

### 双语（Bilingual UI，必须）

平台有外教使用，所有用户可见文案必须中英双语（CLAUDE.md「双语准则」为权威说明）：

- 新代码一律 `useI18n().t({ zh, en })`（`src/lib/i18n.tsx`），禁止新增单语言硬编码文案
- 后端错误 `detail` 文案是稳定标识（前端按文案分流），改措辞前先全局搜索引用；用户提示在前端做双语映射
- 存量页面按页面渐进迁移：PR 触碰到的页面必须顺手完成该页双语

### General
- **Naming**:
  - Python: `snake_case` for variables/functions, `PascalCase` for classes.
  - TypeScript: `camelCase` for variables/functions, `PascalCase` for components/interfaces.
  - Files:
    - Python: `snake_case.py`
    - TypeScript: `kebab-case.ts` (utils/hooks) or `PascalCase.tsx` (components).
- **Comments**: Write clear, concise comments for complex logic. Avoid stating the obvious.

### Backend (Python)
- **Type Hints**: Always use Python type hints.
  - `def get_user(id: uuid.UUID) -> User:`
- **Pydantic**: Use Pydantic models for all API Request/Response schemas.
- **Sync by default**: Route handlers and database operations use plain `def` with the sync SQLModel `Session`. FastAPI runs them in a threadpool. Do NOT mix in async DB sessions — stay consistent with the existing code. The readiness probe is a narrow exception: a dedicated async psycopg connection allows cancellation of the complete network operation.
- **Error Handling**: Use `HTTPException` for API errors. Do not return raw dictionaries for errors.
- **401 vs 403**: 401 仅用于 token 无效/过期（前端收到 401 会自动登出）；403 用于"已登录但权限不足"。不要混用——权限不足返回 401 会把正常用户踢下线。

### Frontend (TypeScript/React)
- **Components**: Use Functional Components with Hooks.
- **Strict Mode**: Do not use `any`. Define proper Interfaces or Types.
- **Styles**: Use Tailwind utility classes. Avoid inline `style={{}}` unless dynamic.
- **Fetching**: Use custom hooks wrapping `useQuery` / `useMutation` for API interactions.
- **Imports**: Use absolute imports (e.g., `@/components/...`) where possible.

## 3. Deployment & Infrastructure

- **Compose**: `compose.yml` is production. `compose.override.yml` is local dev (auto-applied).
- **API Routing**: nginx proxies `/api`, `/docs`, `/redoc` to the `backend` container. `VITE_API_URL` is empty in production (relative URLs).
- **Local Dev**: `VITE_API_URL` is empty; Vite proxies `/api` to `API_PROXY_TARGET` (defaults to `http://127.0.0.1:8000`; Docker uses `http://backend:8000`). If another local service occupies IPv4 port 8000, start Vite with `API_PROXY_TARGET=http://[::1]:8000` to reach the Docker backend over IPv6.
- **Credentials**: NEVER commit `.env` or any secret to git（`.gitignore` 已忽略）. Production `.env` is regenerated from GitHub Secrets on every deploy — GitHub Secrets is the single source of truth.
- **Deploy**: Production deployment requires repository variable `ENABLE_PRODUCTION_DEPLOY=true`; until then only CI runs. Push to `master` → CI (lint + tests + 前端客户端一致性) → server-side checkout 到该次 CI 验证过的 commit + `docker compose up -d --build`. See `.github/workflows/deploy.yml`.
- **HTTP vs HTTPS**: Internal tools and demos run on plain `http://IP:port` (the template default) — do NOT add TLS/reverse-proxy machinery to individual projects. Demos using microphone/camera or other secure-context APIs also require HTTPS when accessed remotely (localhost is exempt). Projects going live for real users MUST use HTTPS via the server-level Caddy path documented in README（域名 + ICP 备案，备案需提前 1~3 周启动）. If a project is about to go live and still runs on HTTP, remind the user.

## 4. Workflow & Best Practices

- **Modularity**: Keep components small and focused. One component per file is preferred.
- **Validation**: Validate all inputs at the API boundary (Pydantic).
- **Testing**: Write unit tests for critical utility functions in `backend/tests/`.

## 5. 前后端联动规范

- 后端改了模型或接口后，必须重新生成前端客户端：`cd frontend && npm run generate-client`（需要 backend 容器在运行，脚本会自动导出最新 OpenAPI 规范）。CI 会重新生成并 diff `src/client/`，忘记生成会在部署前被拦下
- 前端不允许手写 API 请求 URL 字符串，统一用 `client/` 目录下的生成代码
- 数据库模型变更后必须生成 Alembic 迁移文件，不允许直接改数据库

## 6. Forbidden Patterns

- No `print()` in production code — use `logging`.
- No circular imports — structure modules to avoid dependency cycles.
- No direct DOM manipulation in React — use refs if absolutely necessary.
- No magic numbers — use named constants.
- No `any` in TypeScript.
