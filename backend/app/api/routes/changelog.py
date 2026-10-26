"""平台更新日志：教师与管理员查看，管理员发布维护（学生端不开放）。"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app.api.deps import SessionDep, SuperUserDep, TeacherUserDep
from app.models import (
    ChangelogCreate,
    ChangelogEntry,
    ChangelogPublic,
    ChangelogUpdate,
    get_datetime_utc,
)

router = APIRouter(prefix="/changelog", tags=["changelog"])

ALLOWED_KINDS = ("feature", "improvement", "fix")


def _validate_kind(kind: str | None) -> None:
    if kind is not None and kind not in ALLOWED_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"类型仅支持：{'/'.join(ALLOWED_KINDS)}",
        )


@router.get("", response_model=list[ChangelogPublic])
def read_changelog(session: SessionDep, _user: TeacherUserDep) -> Any:
    """按发布日期倒序返回全部更新日志（量级小，不分页）。"""
    return session.exec(
        select(ChangelogEntry).order_by(
            col(ChangelogEntry.day).desc(), col(ChangelogEntry.created_at).desc()
        )
    ).all()


@router.post("", response_model=ChangelogPublic)
def create_changelog_entry(
    session: SessionDep,
    _admin: SuperUserDep,
    entry_in: ChangelogCreate,
) -> Any:
    _validate_kind(entry_in.kind)
    entry = ChangelogEntry.model_validate(entry_in.model_dump())
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.put("/{entry_id}", response_model=ChangelogPublic)
def update_changelog_entry(
    session: SessionDep,
    _admin: SuperUserDep,
    entry_id: uuid.UUID,
    entry_in: ChangelogUpdate,
) -> Any:
    """全量更新（前端提交完整对象）：kind 传 null 表示清掉类型标签。

    防御部分提交：DTO 全字段可空，但 day/标题是 NOT NULL 列，缺失时
    与其等数据库约束炸 500，不如此处 422。
    """
    entry = session.get(ChangelogEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="更新日志不存在")
    _validate_kind(entry_in.kind)
    missing = [
        field
        for field in ("day", "title_zh", "title_en")
        if getattr(entry_in, field) is None
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"全量更新缺少必填字段：{'/'.join(missing)}",
        )
    entry.sqlmodel_update({**entry_in.model_dump(), "updated_at": get_datetime_utc()})
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_changelog_entry(
    session: SessionDep, _admin: SuperUserDep, entry_id: uuid.UUID
) -> dict[str, str]:
    entry = session.get(ChangelogEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="更新日志不存在")
    session.delete(entry)
    session.commit()
    return {"message": "deleted"}
