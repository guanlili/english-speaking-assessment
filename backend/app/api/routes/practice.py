"""学生练习接口（MVP：2 天演示形态，公开、无登录）。

MVP 演示页只取当前篇目；作答走通用 /attempts（见 attempts.py）。
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app.api.deps import SessionDep
from app.models import Passage, PassagePublic

router = APIRouter(prefix="/practice", tags=["practice"])


@router.get("/passage", response_model=PassagePublic)
def read_active_passage(session: SessionDep) -> Any:
    """
    获取当前激活的练习篇目（演示阶段全局一篇）。
    """
    statement = (
        select(Passage)
        .where(Passage.is_active)  # type: ignore[attr-defined]
        .order_by(col(Passage.created_at))
        .limit(1)
    )
    passage = session.exec(statement).first()
    if not passage:
        raise HTTPException(status_code=404, detail="No active passage")
    return passage
