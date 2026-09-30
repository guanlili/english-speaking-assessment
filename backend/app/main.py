from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(
        dsn=str(settings.SENTRY_DSN),
        enable_tracing=True,
        # 按环境归因事件；全采样在 40 人课堂并发下会刷配额，0.1 起步
        environment=settings.ENVIRONMENT,
        traces_sample_rate=0.1,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # 启动时恢复僵尸 scoring 作答（进程崩溃后遗留）
    from app.scoring.worker import startup_recovery

    startup_recovery()
    yield
    # 关闭评分线程池，避免 docker stop 时挂起
    from app.scoring.worker import shutdown_executor

    shutdown_executor()


# 生产不对外暴露 /docs、/redoc、/openapi.json（完整 API 面可被匿名枚举）；
# 本地/CI 保留（客户端生成与调试依赖 app.openapi()，其不受 docs_url 影响）
_api_docs_enabled = settings.ENVIRONMENT == "local"
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if _api_docs_enabled else None,
    docs_url=f"{settings.API_V1_STR}/docs" if _api_docs_enabled else None,
    redoc_url=f"{settings.API_V1_STR}/redoc" if _api_docs_enabled else None,
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
