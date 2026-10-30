"""管理端内容路由的共享小工具（拆分自 admin_content，避免模块间循环导入）。"""

import uuid
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import Attempt, AttemptStatus

VALID_BANDS = {"A2", "B1", "B2"}


def _strip_blank(value: str | None) -> str | None:
    """可空字符串字段：空白串归 None（前端空输入直接清空语义）。"""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _strip_nonempty(value: str | None) -> str | None:
    """非空字符串字段：去空白后仍为空 → 校验失败（更新模型里传 null 走 422）。"""
    if value is None:
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("内容不能为空")
    return stripped


def _reject_null_non_nullable(
    update: dict[str, Any], non_nullable_fields: set[str]
) -> None:
    """更新语义：非空字段不允许显式传 null（传 null 返回 422）。

    允许为空的字段（translation/audio_url/passage_id/unit_id）传 null = 清空，
    不受此限制。
    """
    for field in non_nullable_fields:
        if field in update and update[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"{field} 不能为 null，如需清空请传空字符串或省略",
            )


def _reject_delete_with_queued_attempts(
    session: Session, item_id: uuid.UUID, item_type: str
) -> None:
    """有排队评分中的作答时拒绝删除内容（否则 worker 领取时找不到题目会失败）。"""
    has_queued = (
        session.exec(
            select(Attempt.id)
            .where(
                Attempt.item_id == item_id,
                Attempt.item_type == item_type,
                col(Attempt.status).in_([AttemptStatus.QUEUED, AttemptStatus.SCORING]),
            )
            .limit(1)
        ).first()
        is not None
    )
    if has_queued:
        raise HTTPException(
            status_code=409,
            detail="有正在评分中的作答，请稍后再删除",
        )


def _reject_delete_items_queued(
    session: Session, items: list[tuple[uuid.UUID, str]]
) -> None:
    """批量检查多个 item 是否有待评作答，任一有则拒绝删除。"""
    if not items:
        return
    item_ids_by_type: dict[str, list[uuid.UUID]] = {}
    for item_id, item_type in items:
        item_ids_by_type.setdefault(item_type, []).append(item_id)
    has_queued = False
    for item_type, ids in item_ids_by_type.items():
        found = session.exec(
            select(Attempt.id)
            .where(
                col(Attempt.item_id).in_(ids),
                Attempt.item_type == item_type,
                col(Attempt.status).in_([AttemptStatus.QUEUED, AttemptStatus.SCORING]),
            )
            .limit(1)
        ).first()
        if found is not None:
            has_queued = True
            break
    if has_queued:
        raise HTTPException(
            status_code=409,
            detail="有正在评分中的作答，请稍后再删除",
        )
