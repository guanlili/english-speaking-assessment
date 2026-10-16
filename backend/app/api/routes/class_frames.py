"""句型收藏：学生按单条表达收藏，挂课堂档案跨设备可见。"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlmodel import SQLModel, col, select

from app.api.deps import (
    SessionDep,
    StudentUserDep,
)
from app.api.routes.class_shared import (
    _get_classroom,
    _student_profile_of,
    router,
)
from app.models import (
    ExpressionFavoriteCreate,
    ExpressionFavoritePublic,
    SentenceFrame,
    SentenceFramePublic,
    StudentExpressionFavorite,
    StudentFrameFavorite,
)

MAX_EXPRESSION_FAVORITES = 50

logger = logging.getLogger(__name__)


# ── 句型收藏（PR B）：学生按单条表达收藏，挂课堂档案跨设备可见 ───────


class FrameFavoriteRequest(SQLModel):
    frame_id: uuid.UUID


@router.get("/{code}/frame-favorites", response_model=list[SentenceFramePublic])
def list_my_frame_favorites(
    session: SessionDep, code: str, current_user: StudentUserDep
) -> Any:
    """我的句型收藏（跨设备：挂课堂档案，同账号任何设备可见）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    favorites = session.exec(
        select(SentenceFrame)
        .join(
            StudentFrameFavorite,
            StudentFrameFavorite.frame_id == SentenceFrame.id,  # ty: ignore[invalid-argument-type]
        )
        .where(StudentFrameFavorite.student_id == student.id)  # type: ignore[arg-type]
        .order_by(col(StudentFrameFavorite.created_at).desc())
    ).all()
    return [
        SentenceFramePublic(
            id=frame.id,
            level=frame.level,
            purpose=frame.purpose,
            exam_kind=frame.exam_kind,
            text_en=frame.text_en,
            text_zh=frame.text_zh,
            favorited=True,
        )
        for frame in favorites
    ]


@router.post("/{code}/frame-favorites", response_model=list[SentenceFramePublic])
def add_frame_favorite(
    session: SessionDep,
    code: str,
    body: FrameFavoriteRequest,
    current_user: StudentUserDep,
) -> Any:
    """收藏一条句型（幂等；重复收藏返回同一列表）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    frame = session.get(SentenceFrame, body.frame_id)
    if frame is None or frame.status != "active":
        raise HTTPException(status_code=404, detail="句型不存在")
    existing = session.exec(
        select(StudentFrameFavorite).where(
            StudentFrameFavorite.student_id == student.id,  # type: ignore[arg-type]
            StudentFrameFavorite.frame_id == frame.id,  # type: ignore[arg-type]
        )
    ).first()
    if existing is None:
        session.add(StudentFrameFavorite(student_id=student.id, frame_id=frame.id))
        session.commit()
    return list_my_frame_favorites(session, code, current_user)


@router.delete(
    "/{code}/frame-favorites/{frame_id}", response_model=list[SentenceFramePublic]
)
def remove_frame_favorite(
    session: SessionDep,
    code: str,
    frame_id: uuid.UUID,
    current_user: StudentUserDep,
) -> Any:
    """取消收藏（幂等）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    favorite = session.exec(
        select(StudentFrameFavorite).where(
            StudentFrameFavorite.student_id == student.id,  # type: ignore[arg-type]
            StudentFrameFavorite.frame_id == frame_id,  # type: ignore[arg-type]
        )
    ).first()
    if favorite is not None:
        session.delete(favorite)
        session.commit()
    return list_my_frame_favorites(session, code, current_user)


def _expression_favorites(
    session: SessionDep, student_id: uuid.UUID
) -> list[ExpressionFavoritePublic]:
    rows = session.exec(
        select(StudentExpressionFavorite)
        .where(StudentExpressionFavorite.student_id == student_id)  # type: ignore[arg-type]
        .order_by(col(StudentExpressionFavorite.created_at).desc())
    ).all()
    return [ExpressionFavoritePublic(id=row.id, text=row.text) for row in rows]


@router.get(
    "/{code}/expression-favorites", response_model=list[ExpressionFavoritePublic]
)
def list_my_expression_favorites(
    session: SessionDep, code: str, current_user: StudentUserDep
) -> list[ExpressionFavoritePublic]:
    """我的升级表达收藏（挂课堂档案，同账号任何设备可见）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    return _expression_favorites(session, student.id)


@router.post(
    "/{code}/expression-favorites", response_model=list[ExpressionFavoritePublic]
)
def add_expression_favorites(
    session: SessionDep,
    code: str,
    body: ExpressionFavoriteCreate,
    current_user: StudentUserDep,
) -> list[ExpressionFavoritePublic]:
    """收藏升级表达。重复文本忽略；每人最多 50 条，超出部分不再写入。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    existing = {
        row.text
        for row in session.exec(
            select(StudentExpressionFavorite).where(
                StudentExpressionFavorite.student_id == student.id  # type: ignore[arg-type]
            )
        ).all()
    }
    room = MAX_EXPRESSION_FAVORITES - len(existing)
    added = False
    for raw in body.texts:
        text = raw.strip()
        if not text or text in existing or len(text) > 500:
            continue
        if room <= 0:
            break
        session.add(StudentExpressionFavorite(student_id=student.id, text=text))
        existing.add(text)
        room -= 1
        added = True
    if added:
        session.commit()
    return _expression_favorites(session, student.id)


@router.delete(
    "/{code}/expression-favorites/{favorite_id}",
    response_model=list[ExpressionFavoritePublic],
)
def remove_expression_favorite(
    session: SessionDep,
    code: str,
    favorite_id: uuid.UUID,
    current_user: StudentUserDep,
) -> list[ExpressionFavoritePublic]:
    """取消一条升级表达收藏（幂等）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    favorite = session.get(StudentExpressionFavorite, favorite_id)
    if favorite is not None and favorite.student_id == student.id:
        session.delete(favorite)
        session.commit()
    return _expression_favorites(session, student.id)
