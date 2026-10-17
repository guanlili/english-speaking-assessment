"""Copy school question-bank material into an independently editable teacher version."""

import uuid
from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, HTTPException
from sqlmodel import SQLModel, select

from app.api.deps import SessionDep, TeacherUserDep
from app.models import Instruction, Passage, RepeatSentence, ScenarioQuestion

router = APIRouter(prefix="/admin", tags=["admin"])


class ContentCopied(SQLModel):
    id: uuid.UUID
    copied_from_id: uuid.UUID


@router.post("/content/{kind}/{item_id}/copy", response_model=ContentCopied)
def copy_school_content(
    session: SessionDep,
    current_user: TeacherUserDep,
    kind: Literal["passage", "repeat", "question", "instruction"],
    item_id: uuid.UUID,
) -> ContentCopied:
    model = {
        "passage": Passage,
        "repeat": RepeatSentence,
        "question": ScenarioQuestion,
        "instruction": Instruction,
    }[kind]
    source = session.get(model, item_id)
    if source is None:
        raise HTTPException(404, detail="Content not found")
    values = deepcopy(source.model_dump(exclude={"id", "created_at", "updated_at"}))
    values.update(owner_id=current_user.id, copied_from_id=source.id)
    if kind == "passage":
        values.update(slug=f"copy-{uuid.uuid4().hex}", parent_passage_id=None)
    elif kind == "repeat":
        # A copied sentence must not inherit the source passage owner's rights.
        values.update(passage_id=None, order_index=0)
    copy = model.model_validate(values)
    session.add(copy)
    session.flush()
    if kind == "passage":
        children = session.exec(
            select(RepeatSentence).where(RepeatSentence.passage_id == source.id)
        ).all()
        for child in children:
            child_values = deepcopy(child.model_dump(exclude={"id", "created_at"}))
            child_values.update(
                passage_id=copy.id, owner_id=current_user.id, copied_from_id=child.id
            )
            session.add(RepeatSentence.model_validate(child_values))
    session.commit()
    return ContentCopied(id=copy.id, copied_from_id=source.id)


class SharedContentPreview(SQLModel):
    id: uuid.UUID
    title: str | None = None
    text: str
    author_name: str | None = None


@router.get("/content/{kind}/{item_id}", response_model=SharedContentPreview)
def read_shared_content_source(
    session: SessionDep,
    _current_user: TeacherUserDep,
    kind: Literal["passage", "repeat", "question", "instruction"],
    item_id: uuid.UUID,
) -> SharedContentPreview:
    from app.models import User

    model = {
        "passage": Passage,
        "repeat": RepeatSentence,
        "question": ScenarioQuestion,
        "instruction": Instruction,
    }[kind]
    source = session.get(model, item_id)
    if source is None:
        raise HTTPException(404, detail="Content not found")
    owner = session.get(User, source.owner_id) if source.owner_id else None
    return SharedContentPreview(
        id=source.id,
        title=getattr(source, "title", None),
        text=source.text,
        author_name=owner.full_name if owner else None,
    )
