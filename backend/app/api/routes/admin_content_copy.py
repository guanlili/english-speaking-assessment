"""Copy school question-bank material into an independently editable teacher version."""

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from sqlmodel import SQLModel

from app.api.deps import SessionDep, TeacherUserDep
from app.models import Instruction, Passage, RepeatSentence, ScenarioQuestion
from app.services import content_access, content_copy

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
    # 多租户：session.get 按主键直取不带租户过滤，跨校源按不存在处理（404），
    # 副本一律落当前用户所在校（deepcopy 会继承源校 tenant_id）
    content_access.require_same_tenant(current_user, source)
    owner_id = content_access.owner_for(current_user)
    tenant_id = current_user.tenant_id
    if isinstance(source, Passage):
        copied = content_copy.copy_passage(
            session, source, owner_id, target_tenant_id=tenant_id
        )
    elif isinstance(source, RepeatSentence):
        copied = content_copy.copy_sentence(
            session, source, owner_id, target_tenant_id=tenant_id
        )
    elif isinstance(source, ScenarioQuestion):
        copied = content_copy.copy_question(
            session, source, owner_id, target_tenant_id=tenant_id
        )
    else:
        copied = content_copy.copy_instruction(
            session, source, owner_id, target_tenant_id=tenant_id
        )
    content_copy.commit_copy(session)
    assert copied.copied_from_id is not None
    return ContentCopied(id=copied.id, copied_from_id=copied.copied_from_id)


class SharedContentPreview(SQLModel):
    id: uuid.UUID
    title: str | None = None
    text: str
    author_name: str | None = None


@router.get("/content/{kind}/{item_id}", response_model=SharedContentPreview)
def read_shared_content_source(
    session: SessionDep,
    current_user: TeacherUserDep,
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
    # 多租户：与 copy 端点同口径——session.get 按主键直取不带租户过滤，
    # 跨校源按不存在处理（404），不泄露他校私有内容标题/正文/作者
    content_access.require_same_tenant(current_user, source)
    owner = session.get(User, source.owner_id) if source.owner_id else None
    return SharedContentPreview(
        id=source.id,
        title=getattr(source, "title", None),
        text=source.text,
        author_name=owner.full_name if owner else None,
    )
