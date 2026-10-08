import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import sentry_sdk
from fastapi import FastAPI, Request, Response
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
    # 启动时恢复僵尸 scoring 作答（进程崩溃后遗留）。
    # 同步全表扫描放线程池：直接在事件循环上跑会拖慢启动，数据量大时
    # 健康检查窗口内服务不可响应
    from anyio import to_thread

    from app.scoring.worker import start_sweeper, startup_recovery

    # ASR 走 LLM responses API 按音频 token 计费，比 volc_flash 专线贵数倍；
    # 生产漏配 ASR_PROVIDER=volc_flash 时在此显式告警（默认值保持 ark 以兼容本地仅有方舟密钥的环境）
    if (
        settings.ENVIRONMENT == "production"
        and settings.SCORING_PROVIDER == "ark"
        and settings.ASR_PROVIDER == "ark"
    ):
        logging.getLogger(__name__).warning(
            "ASR_PROVIDER=ark 走 LLM 转写（贵路径），生产建议 ASR_PROVIDER=volc_flash"
        )

    await to_thread.run_sync(startup_recovery)
    start_sweeper()
    yield
    # 关闭评分线程池与清扫线程，避免 docker stop 时挂起
    from app.scoring.worker import shutdown_executor, stop_sweeper

    stop_sweeper()
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


# 安全响应头（2026-10-08 审计）：后端直出的 JSON/音频响应也带基础防线；
# HSTS 只在 TLS 后面有意义，由 nginx 的 443 server 块下发（见 nginx-tls.conf）
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


app.include_router(api_router, prefix=settings.API_V1_STR)
