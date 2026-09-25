import asyncio
import logging
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic.networks import EmailStr

from app.api.deps import get_current_active_superuser
from app.core.config import settings
from app.models import Message
from app.utils import generate_test_email, send_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    """
    Test emails.
    """
    if not settings.emails_enabled:
        # superuser 专用接口，直接说明原因，优于让 send_email 抛 500
        raise HTTPException(
            status_code=400,
            detail="Email is not configured (SMTP_HOST / EMAILS_FROM_EMAIL missing)",
        )
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/health-check/")
async def health_check() -> bool:
    """
    轻量存活检查（liveness）：进程能响应即返回 True，不触碰数据库。
    容器重启判定、负载均衡存活探针用它。
    """
    return True


READINESS_TIMEOUT_SECONDS = 3


def get_readiness_dsn() -> str:
    return str(settings.SQLALCHEMY_DATABASE_URI).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )


async def probe_database(dsn: str) -> None:
    # Dedicated short-lived connection: no waiting on the application's pool.
    # The caller bounds the entire connect + query operation, including a silent peer.
    conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    query = asyncio.create_task(conn.execute("SELECT 1"))
    try:
        # psycopg normally cancels queries via a second network connection. Shield
        # that path so a timeout can close this disposable socket immediately.
        await asyncio.shield(query)
    finally:
        await conn.close()
        if not query.done():
            query.cancel()
        await asyncio.gather(query, return_exceptions=True)


@router.get("/ready-check/")
async def ready_check(dsn: Annotated[str, Depends(get_readiness_dsn)]) -> Message:
    """Bound the full database probe; expose no connection details on failure."""
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            await probe_database(dsn)
    except Exception:
        logger.warning("Readiness check failed: database not reachable")
        raise HTTPException(status_code=503, detail="Service not ready") from None
    return Message(message="Ready")
