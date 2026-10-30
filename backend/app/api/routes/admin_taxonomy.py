"""管理端内容 taxonomy：单元、主题词表、句型库（从 admin_content 拆分）。

权限口径与权限矩阵（docs/permissions-matrix-2026-10.md）一致：
单元与句型库的管理仅管理员；单元/主题列表教师可读（出题选择用）。
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Field, SQLModel, col, func, select

from app.api.deps import SessionDep, SuperUserDep, TeacherUserDep
from app.api.routes.admin_content import _reject_null_non_nullable
from app.models import (
    EXAM_KIND_QUESTION,
    Passage,
    Scenario,
    SentenceFrame,
    SentenceFramePublic,
    Unit,
    UnitCreate,
    UnitPublic,
    UnitUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/units", response_model=list[UnitPublic])
def list_units(session: SessionDep, _admin: TeacherUserDep) -> Any:
    units = session.exec(select(Unit).order_by(col(Unit.order_index))).all()
    counts = _active_passage_counts(session)
    return [
        UnitPublic(
            **u.model_dump(),
            passage_count=counts.get(u.id, 0),
        )
        for u in units
    ]


def _active_passage_counts(session: SessionDep) -> dict[uuid.UUID, int]:
    """每个单元的启用篇目数（指派前完整性检查用）。"""
    rows = session.exec(
        select(Passage.unit_id, func.count())
        .where(
            Passage.is_active,
            Passage.unit_id.is_not(None),  # type: ignore
        )
        .group_by(Passage.unit_id)  # type: ignore
    ).all()
    return {unit_id: count for unit_id, count in rows if unit_id is not None}


# 单元增删改仅管理员：教师页面只读单元（出题选择），与权限矩阵一致
@router.post("/units", response_model=UnitPublic)
def create_unit(session: SessionDep, _admin: SuperUserDep, unit_in: UnitCreate) -> Any:
    unit = Unit.model_validate(unit_in)
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit


@router.put("/units/{unit_id}", response_model=UnitPublic)
def update_unit(
    session: SessionDep,
    _admin: SuperUserDep,
    unit_id: uuid.UUID,
    unit_in: UnitUpdate,
) -> Any:
    unit = session.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")
    update = unit_in.model_dump(exclude_unset=True)
    # 非空字段不允许显式清空
    _reject_null_non_nullable(update, {"title", "topic", "order_index", "is_active"})
    unit.sqlmodel_update(update)
    session.add(unit)
    # 主题单一事实源：单元改主题后，属下篇目的 topic 级联跟随
    if "topic" in update:
        for passage in session.exec(
            select(Passage).where(Passage.unit_id == unit.id)
        ).all():
            passage.topic = update["topic"]
            session.add(passage)
    session.commit()
    session.refresh(unit)
    return unit


@router.delete("/units/{unit_id}")
def delete_unit(
    session: SessionDep, _admin: SuperUserDep, unit_id: uuid.UUID
) -> dict[str, str]:
    unit = session.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")
    session.delete(unit)  # 篇目 unit_id 置空（SET NULL）
    session.commit()
    return {"message": "deleted"}


@router.get("/topics", response_model=list[str])
def list_topics(session: SessionDep, _admin: TeacherUserDep) -> Any:
    """已有主题词表（篇目/单元/情景的 topic 并集）：录入时从列表选，不再自由输入。"""
    topics: set[str] = set()
    for column in (Passage.topic, Unit.topic, Scenario.topic):
        # DISTINCT 在库端去重，避免随内容量增长整列拉回
        topics.update(t for t in session.exec(select(column).distinct()).all() if t)
    return sorted(topics)


# ── 句型推荐（PR B）：按级别与表达用途分类的可替换句型 ───────────────


class SentenceFrameCreate(SQLModel):
    level: str = Field(max_length=16)
    purpose: str = Field(max_length=24)
    exam_kind: str | None = None
    text_en: str = Field(min_length=1, max_length=255)
    text_zh: str = Field(min_length=1, max_length=255)
    status: str = Field(default="active", max_length=16)


class SentenceFrameUpdate(SQLModel):
    level: str | None = None
    purpose: str | None = None
    exam_kind: str | None = None
    text_en: str | None = Field(default=None, min_length=1, max_length=255)
    text_zh: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = None


def _validate_frame_fields(
    level: str | None,
    purpose: str | None,
    exam_kind: str | None,
    status: str | None = None,
) -> None:
    from app.models import FRAME_PURPOSES, VOCAB_LEVEL_ORDER
    from app.services.exercise import AttemptItemType  # noqa: F401 占位

    del AttemptItemType
    if level is not None and level not in VOCAB_LEVEL_ORDER:
        raise HTTPException(
            status_code=422, detail="级别无效，可选：" + "/".join(VOCAB_LEVEL_ORDER)
        )
    if purpose is not None and purpose not in FRAME_PURPOSES:
        raise HTTPException(
            status_code=422, detail="表达用途无效，可选：" + "/".join(FRAME_PURPOSES)
        )
    if exam_kind is not None and exam_kind not in EXAM_KIND_QUESTION:
        raise HTTPException(
            status_code=422,
            detail="句型关联题型无效（可空=通用）：" + "/".join(EXAM_KIND_QUESTION),
        )
    # 句型同样遵循「有题型必配级别」（与题型训练一致，避免歧义记录）
    if exam_kind is not None and level is None:
        raise HTTPException(status_code=422, detail="选择考试题型时需同时标注级别")
    if status is not None and status not in {"active", "archived"}:
        raise HTTPException(status_code=422, detail="状态只能是 active/archived")


class SentenceFramesListOut(SQLModel):
    """句型库分页信封：count 反映过滤后的总数"""

    data: list[SentenceFramePublic]
    count: int


# 句型库管理整套端点仅管理员：前端唯一调用方是 /admin/sentenceframes 管理页
@router.get("/sentence-frames", response_model=SentenceFramesListOut)
def list_sentence_frames(
    session: SessionDep,
    _admin: SuperUserDep,
    level: str | None = Query(default=None, description="五级筛选"),
    purpose: str | None = Query(default=None, description="表达用途筛选"),
    exam_kind: str | None = Query(default=None, description="题型筛选"),
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=500),
) -> Any:
    conditions: list[Any] = []
    if level is not None:
        conditions.append(SentenceFrame.level == level)  # type: ignore[arg-type]
    if purpose is not None:
        conditions.append(SentenceFrame.purpose == purpose)  # type: ignore[arg-type]
    if exam_kind is not None:
        conditions.append(SentenceFrame.exam_kind == exam_kind)  # type: ignore[arg-type]
    count = session.exec(
        select(func.count()).select_from(SentenceFrame).where(*conditions)
    ).one()
    stmt = (
        select(SentenceFrame)
        .where(*conditions)
        .order_by(
            col(SentenceFrame.purpose),
            col(SentenceFrame.text_en),
            col(SentenceFrame.id),
        )
        .offset(skip)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return SentenceFramesListOut(
        data=[
            SentenceFramePublic.model_validate(frame)
            for frame in session.exec(stmt).all()
        ],
        count=count,
    )


@router.post("/sentence-frames", response_model=SentenceFramePublic)
def create_sentence_frame(
    session: SessionDep,
    _admin: SuperUserDep,
    frame_in: SentenceFrameCreate,
) -> Any:
    _validate_frame_fields(
        frame_in.level, frame_in.purpose, frame_in.exam_kind, frame_in.status
    )
    frame = SentenceFrame.model_validate(frame_in.model_dump())
    session.add(frame)
    session.commit()
    session.refresh(frame)
    return frame


@router.put("/sentence-frames/{frame_id}", response_model=SentenceFramePublic)
def update_sentence_frame(
    session: SessionDep,
    _admin: SuperUserDep,
    frame_id: uuid.UUID,
    frame_in: SentenceFrameUpdate,
) -> Any:
    frame = session.get(SentenceFrame, frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="Sentence frame not found")
    update = frame_in.model_dump(exclude_unset=True)
    _validate_frame_fields(
        update.get("level", frame.level),
        update.get("purpose", frame.purpose),
        update.get("exam_kind", frame.exam_kind),
        update.get("status", frame.status),
    )
    frame.sqlmodel_update(update)
    session.add(frame)
    session.commit()
    session.refresh(frame)
    return frame


class SentenceFrameBatchItem(SQLModel):
    """批量导入的单条：校验放处理器逐条做，避免一条非法整批 422。"""

    level: str = ""
    purpose: str = ""
    exam_kind: str | None = ""
    text_en: str = ""
    text_zh: str = ""


class SentenceFrameBatchIssue(SQLModel):
    index: int
    reason: str


class SentenceFrameBatchResult(SQLModel):
    created: int
    skipped_duplicates: int
    invalid: list[SentenceFrameBatchIssue]


@router.post("/sentence-frames/batch", response_model=SentenceFrameBatchResult)
def create_sentence_frames_batch(
    session: SessionDep,
    _admin: SuperUserDep,
    items: list[SentenceFrameBatchItem],
) -> Any:
    """批量创建句型：无效行跳过并报告；同 (级别, 用途, 英文) 重复跳过。"""
    created = 0
    skipped = 0
    invalid: list[SentenceFrameBatchIssue] = []
    # 跨请求去重：数据库已有的 (级别, 用途, 英文) 视为重复跳过
    seen: set[tuple[str, str, str]] = {
        (frame.level, frame.purpose, frame.text_en.casefold())
        for frame in session.exec(select(SentenceFrame)).all()
    }
    for index, item in enumerate(items):
        text_en = item.text_en.strip()
        text_zh = item.text_zh.strip()
        level = item.level.strip()
        purpose = item.purpose.strip()
        exam_kind = (item.exam_kind or "").strip() or None
        if not text_en or not text_zh or not level or not purpose:
            invalid.append(
                SentenceFrameBatchIssue(
                    index=index, reason="缺少必填字段（level/purpose/text_en/text_zh）"
                )
            )
            continue
        try:
            _validate_frame_fields(level, purpose, exam_kind)
        except HTTPException as exc:
            invalid.append(SentenceFrameBatchIssue(index=index, reason=str(exc.detail)))
            continue
        key = (level, purpose, text_en.casefold())
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        session.add(
            SentenceFrame(
                level=level,
                purpose=purpose,
                exam_kind=exam_kind,
                text_en=text_en,
                text_zh=text_zh,
            )
        )
        created += 1
    if created:
        session.commit()
    return SentenceFrameBatchResult(
        created=created, skipped_duplicates=skipped, invalid=invalid
    )


@router.delete("/sentence-frames/{frame_id}")
def delete_sentence_frame(
    session: SessionDep, _admin: SuperUserDep, frame_id: uuid.UUID
) -> dict[str, str]:
    frame = session.get(SentenceFrame, frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="Sentence frame not found")
    session.delete(frame)
    session.commit()
    return {"message": "deleted"}
