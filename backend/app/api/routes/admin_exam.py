"""Question-bank timing settings, copied into each published exam."""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep, TeacherUserDep
from app.models import (
    ExamItemSettings,
    Instruction,
    Passage,
    RepeatSentence,
    ScenarioQuestion,
)

router = APIRouter(prefix="/admin", tags=["admin"])
ItemType = Literal["passage", "repeat", "question", "instruction"]


def _item(
    session: SessionDep, item_type: ItemType, item_id: uuid.UUID
) -> Passage | RepeatSentence | ScenarioQuestion | Instruction:
    models = {
        "passage": Passage,
        "repeat": RepeatSentence,
        "question": ScenarioQuestion,
        "instruction": Instruction,
    }
    item = session.get(models[item_type], item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get(
    "/exam-items/{item_type}/{item_id}/settings", response_model=ExamItemSettings
)
def read_exam_item_settings(
    session: SessionDep,
    _current_user: TeacherUserDep,
    item_type: ItemType,
    item_id: uuid.UUID,
) -> ExamItemSettings:
    item = _item(session, item_type, item_id)
    return ExamItemSettings.model_validate(item.exam_settings or {})


@router.put(
    "/exam-items/{item_type}/{item_id}/settings", response_model=ExamItemSettings
)
def update_exam_item_settings(
    session: SessionDep,
    _current_user: TeacherUserDep,
    item_type: ItemType,
    item_id: uuid.UUID,
    body: ExamItemSettings,
) -> ExamItemSettings:
    # 不做归属校验：组卷排序行就地设置计时，选用他人题目组考试时也要能调
    item = _item(session, item_type, item_id)
    item.exam_settings = body.model_dump()
    session.add(item)
    session.commit()
    return body
