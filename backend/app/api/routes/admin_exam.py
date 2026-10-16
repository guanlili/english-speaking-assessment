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
    User,
)
from app.services import content_access

router = APIRouter(prefix="/admin", tags=["admin"])
ItemType = Literal["passage", "repeat", "question", "instruction"]


class ExamItemSettingsOut(ExamItemSettings):
    # 他人题目只能补缺失的考试音频，不能替换/清空已有的
    can_replace_audio: bool = True


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


def _out(
    session: SessionDep,
    user: User,
    item: Passage | RepeatSentence | ScenarioQuestion | Instruction,
    settings: ExamItemSettings,
) -> ExamItemSettingsOut:
    return ExamItemSettingsOut(
        **settings.model_dump(),
        can_replace_audio=content_access.can_edit(
            user, content_access.item_owner(session, item)
        ),
    )


@router.get(
    "/exam-items/{item_type}/{item_id}/settings", response_model=ExamItemSettingsOut
)
def read_exam_item_settings(
    session: SessionDep,
    current_user: TeacherUserDep,
    item_type: ItemType,
    item_id: uuid.UUID,
) -> ExamItemSettingsOut:
    item = _item(session, item_type, item_id)
    settings = ExamItemSettings.model_validate(item.exam_settings or {})
    return _out(session, current_user, item, settings)


@router.put(
    "/exam-items/{item_type}/{item_id}/settings", response_model=ExamItemSettingsOut
)
def update_exam_item_settings(
    session: SessionDep,
    current_user: TeacherUserDep,
    item_type: ItemType,
    item_id: uuid.UUID,
    body: ExamItemSettings,
) -> ExamItemSettingsOut:
    # 计时不做归属校验：组卷时选用他人题目也要能调；音频会替换考试里播放的
    # 内容，他人题目只允许在原本没有考试音频时补上
    item = _item(session, item_type, item_id)
    current = ExamItemSettings.model_validate(item.exam_settings or {})
    if (
        body.audio_url != current.audio_url
        and current.audio_url is not None
        and not content_access.can_edit(
            current_user, content_access.item_owner(session, item)
        )
    ):
        raise HTTPException(status_code=403, detail=content_access.EXAM_AUDIO_DETAIL)
    item.exam_settings = body.model_dump()
    session.add(item)
    session.commit()
    return _out(session, current_user, item, body)
