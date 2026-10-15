"""私有组卷草稿与历史题目引用复制；永不直接发布。"""

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, SQLModel, col, select

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.class_shared import (
    _get_classroom,
    _require_classroom_teacher,
    router,
)
from app.crud import get_composer_draft
from app.models import (
    ClassroomExercise,
    ComposerDraft,
    Passage,
    ScenarioQuestion,
    get_datetime_utc,
)


class DraftTypes(SQLModel):
    reading: bool
    repeat: bool
    qa: bool
    instruction: bool


class DraftSelection(SQLModel):
    passages: list[uuid.UUID] = Field(max_length=1000)
    sentences: list[uuid.UUID] = Field(max_length=1000)
    scenarioIds: list[uuid.UUID] = Field(max_length=1000)
    instructions: list[uuid.UUID] = Field(max_length=1000)
    questions: list[uuid.UUID] = Field(max_length=1000)


class ComposerState(SQLModel):
    title: str = Field(max_length=255)
    types: DraftTypes
    selection: DraftSelection
    ordered_keys: list[str] | None = Field(default=None, max_length=4000)
    is_exam: bool
    exam_minutes: int
    base_exercise_id: uuid.UUID | None = None


class DraftWrite(SQLModel):
    expected_revision: int = Field(ge=0)
    state: ComposerState


class DraftPublic(SQLModel):
    revision: int
    state: ComposerState
    updated_at: datetime


@router.get("/{code}/composer-draft", response_model=DraftPublic | None)
def read_composer_draft(
    session: SessionDep, code: str, current_user: CurrentUser
) -> DraftPublic | None:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    row = get_composer_draft(session, classroom.id, current_user.id)
    return DraftPublic.model_validate(row, from_attributes=True) if row else None


@router.put("/{code}/composer-draft", response_model=DraftPublic)
def save_composer_draft(
    session: SessionDep, code: str, body: DraftWrite, current_user: CurrentUser
) -> DraftPublic:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    row = get_composer_draft(session, classroom.id, current_user.id)
    if (row.revision if row else 0) != body.expected_revision:
        raise HTTPException(409, detail="Draft revision conflict")
    if row is None:
        row = ComposerDraft(
            classroom_id=classroom.id, owner_id=current_user.id, state={}
        )
    else:
        row.revision += 1
    row.state = body.state.model_dump(mode="json")
    row.updated_at = get_datetime_utc()
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, detail="Draft revision conflict") from None
    session.refresh(row)
    return DraftPublic.model_validate(row, from_attributes=True)


@router.get(
    "/{code}/exercises/{exercise_id}/composer-seed", response_model=ComposerState
)
def read_exercise_composer_seed(
    session: SessionDep, code: str, exercise_id: uuid.UUID, current_user: CurrentUser
) -> ComposerState:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    exercise = session.get(ClassroomExercise, exercise_id)
    if exercise is None or exercise.classroom_id != classroom.id:
        raise HTTPException(404, detail="Exercise not found")
    refs = list(
        dict.fromkeys(
            (str(i["type"]), str(i.get("parent_id") or i["id"]))
            for i in exercise.snapshot_items
        )
    )
    passage_ids = [uuid.UUID(key) for kind, key in refs if kind == "passage"]
    roots = (
        dict(
            session.exec(
                select(Passage.id, Passage.parent_passage_id).where(
                    col(Passage.id).in_(passage_ids)
                )
            ).all()
        )
        if passage_ids
        else {}
    )
    refs = list(
        dict.fromkeys(
            (kind, str(roots.get(uuid.UUID(key)) or key) if kind == "passage" else key)
            for kind, key in refs
        )
    )
    questions = [uuid.UUID(key) for kind, key in refs if kind == "question"]
    scenarios = (
        session.exec(
            select(ScenarioQuestion.scenario_id)
            .where(col(ScenarioQuestion.id).in_(questions))
            .distinct()
        ).all()
        if questions
        else []
    )
    return ComposerState(
        title=exercise.title,
        types=DraftTypes(
            reading=any(k == "passage" for k, _ in refs),
            repeat=any(k == "repeat" for k, _ in refs),
            qa=bool(questions),
            instruction=any(k == "instruction" for k, _ in refs),
        ),
        selection=DraftSelection(
            passages=[uuid.UUID(v) for k, v in refs if k == "passage"],
            sentences=[uuid.UUID(v) for k, v in refs if k == "repeat"],
            scenarioIds=list(scenarios),
            instructions=[uuid.UUID(v) for k, v in refs if k == "instruction"],
            questions=questions,
        ),
        ordered_keys=[f"{k}:{v}" for k, v in refs],
        is_exam=exercise.is_exam,
        exam_minutes=exercise.time_limit_minutes or 30,
    )
