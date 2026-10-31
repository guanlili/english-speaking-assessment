"""管理员内容管理接口（PRD：内容槽由校方录入，软件只留槽位）。

篇目、情景和问法允许教师/管理员维护；课堂平台配置仅超级管理员可操作。
EIP 文本只进数据库，不进 git。

    /admin/passages            篇目 CRUD（含复述句子路由）
    /admin/scenarios           情景 + 分档问法 CRUD
    /admin/classrooms          课堂码列表 / 停用
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import field_validator
from sqlmodel import Field, SQLModel, col, select

from app import crud
from app.api.deps import PlatformOperatorDep, SessionDep, TeacherUserDep
from app.api.routes._content_common import (
    _strip_blank,
    _strip_nonempty,
)
from app.api.routes.admin_passages import (  # noqa: F401 - copy 路由响应模型
    PassageWithSentences,
    SentenceWithPassage,
)
from app.api.routes.admin_scenarios import (  # noqa: F401 - 同上
    QuestionBankOut,
    ScenarioOut,
)
from app.core.config import settings
from app.core.storage import (
    content_audio_path,
    content_audio_url,
    save_content_audio,
    save_content_audio_named,
)
from app.models import (
    Classroom,
    ClassroomPublic,
    Instruction,
    InstructionPublic,
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    ScenarioQuestionPublic,
)
from app.services import content_access, content_copy, reading

router = APIRouter(prefix="/admin", tags=["admin"])

logger = logging.getLogger(__name__)


@router.post("/passages/{passage_id}/copy", response_model=PassageWithSentences)
def copy_passage(
    session: SessionDep, current_user: TeacherUserDep, passage_id: uuid.UUID
) -> PassageWithSentences:
    source = session.get(Passage, passage_id)
    if source is None:
        raise HTTPException(404, detail="Passage not found")
    copied = content_copy.copy_passage(
        session, source, content_access.owner_for(current_user)
    )
    content_copy.commit_copy(session)
    result = PassageWithSentences.model_validate(copied)
    result.sentences = list(
        session.exec(
            select(RepeatSentence)
            .where(RepeatSentence.passage_id == copied.id)
            .order_by(col(RepeatSentence.order_index), col(RepeatSentence.id))
        ).all()
    )
    result.reading_segments = (
        reading.split_reading_sentences(copied.text) if copied.reading_split else []
    )
    result.reading_child_ids = list(
        session.exec(
            select(Passage.id).where(Passage.parent_passage_id == copied.id)
        ).all()
    )
    return result


@router.post("/sentences/{sentence_id}/copy", response_model=SentenceWithPassage)
def copy_sentence(
    session: SessionDep, current_user: TeacherUserDep, sentence_id: uuid.UUID
) -> SentenceWithPassage:
    source = session.get(RepeatSentence, sentence_id)
    if source is None:
        raise HTTPException(404, detail="Sentence not found")
    copied = content_copy.copy_sentence(
        session, source, content_access.owner_for(current_user)
    )
    content_copy.commit_copy(session)
    return SentenceWithPassage.model_validate(copied)


@router.post("/scenarios/{scenario_id}/copy", response_model=ScenarioOut)
def copy_scenario(
    session: SessionDep, current_user: TeacherUserDep, scenario_id: uuid.UUID
) -> ScenarioOut:
    source = session.get(Scenario, scenario_id)
    if source is None:
        raise HTTPException(404, detail="Scenario not found")
    copied = content_copy.copy_scenario(
        session, source, content_access.owner_for(current_user)
    )
    content_copy.commit_copy(session)
    questions = session.exec(
        select(ScenarioQuestion)
        .where(ScenarioQuestion.scenario_id == copied.id)
        .order_by(col(ScenarioQuestion.order_index), col(ScenarioQuestion.id))
    ).all()
    return ScenarioOut(
        **copied.model_dump(),
        questions=[
            ScenarioQuestionPublic.model_validate(question) for question in questions
        ],
    )


@router.post("/questions/{question_id}/copy", response_model=QuestionBankOut)
def copy_question(
    session: SessionDep, current_user: TeacherUserDep, question_id: uuid.UUID
) -> QuestionBankOut:
    source = session.get(ScenarioQuestion, question_id)
    if source is None:
        raise HTTPException(404, detail="Question not found")
    copied = content_copy.copy_question(
        session, source, content_access.owner_for(current_user)
    )
    content_copy.commit_copy(session)
    scenario = session.get(Scenario, copied.scenario_id)
    assert scenario is not None
    return QuestionBankOut(**copied.model_dump(), topic=scenario.topic)


@router.post("/instructions/{instruction_id}/copy", response_model=InstructionPublic)
def copy_instruction(
    session: SessionDep, current_user: TeacherUserDep, instruction_id: uuid.UUID
) -> InstructionPublic:
    source = session.get(Instruction, instruction_id)
    if source is None:
        raise HTTPException(404, detail="Instruction not found")
    copied = content_copy.copy_instruction(
        session, source, content_access.owner_for(current_user)
    )
    content_copy.commit_copy(session)
    return InstructionPublic.model_validate(copied)


class ClassroomUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    grade: str | None = Field(default=None, max_length=64)
    teaching_goal: str | None = Field(default=None, max_length=255)
    unlock_all: bool | None = None
    show_report_percentile: bool | None = None
    owner_id: uuid.UUID | None = None
    is_active: bool | None = None
    class_size: int | None = Field(default=None, ge=1, le=100)


# ── 课堂码 ───────────────────────────────────────────────────────────


@router.get("/classrooms", response_model=list[ClassroomPublic])
def list_classrooms(session: SessionDep, _operator: PlatformOperatorDep) -> Any:
    return session.exec(select(Classroom).order_by(col(Classroom.created_at))).all()


@router.delete("/classrooms/{classroom_id}")
def deactivate_classroom(
    session: SessionDep, _operator: PlatformOperatorDep, classroom_id: uuid.UUID
) -> dict[str, str]:
    classroom = session.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="Classroom not found")
    classroom.is_active = False
    session.add(classroom)
    session.commit()
    return {"message": "deactivated"}


@router.put("/classrooms/{classroom_id}", response_model=ClassroomPublic)
def update_classroom(
    session: SessionDep,
    _operator: PlatformOperatorDep,
    classroom_id: uuid.UUID,
    classroom_in: ClassroomUpdate,
) -> Any:
    """更新课堂设置：unlock_all（一键解锁）、owner_id（绑定授权教师）、启停、班容。"""
    classroom = session.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(status_code=404, detail="Classroom not found")
    update = classroom_in.model_dump(exclude_unset=True)
    if "owner_id" in update and update["owner_id"] is not None:
        # 校验被绑定教师真实存在且确为教师角色（绑成学生等于授予全班教师权限）
        from app.models import User as _User

        owner = session.get(_User, update["owner_id"])
        if owner is None:
            raise HTTPException(status_code=422, detail="教师账号不存在")
        if owner.role not in ("admin", "teacher"):
            raise HTTPException(status_code=422, detail="被绑定账号不是教师角色")
    if update.get("class_size") is not None:
        crud.ensure_class_size_feasible(
            session=session, classroom=classroom, new_size=update["class_size"]
        )
    classroom.sqlmodel_update(update)
    session.add(classroom)
    session.commit()
    session.refresh(classroom)
    return classroom


# ── 内容标准音 ───────────────────────────────────────────────────────


class TtsRequest(SQLModel):
    # 限长：TTS 按音频时长计费，无上限文本 = 费用放大器（2000 字符远超任何题目文本）
    text: str = Field(max_length=2000)


class AudioUrlResult(SQLModel):
    audio_url: str


@router.post("/audio/tts", response_model=AudioUrlResult)
def generate_standard_audio(_admin: TeacherUserDep, body: TtsRequest) -> Any:
    """用语音合成生成标准音并落盘，返回可回放的相对 URL。

    内容寻址缓存：同 (模型, 音色, 文本) 命中已有文件直接返回，不重复合成扣费。
    """
    from app.scoring.tts import TtsError, build_tts_provider, cache_key

    provider = build_tts_provider()
    stem = cache_key(provider.model, provider.voice, body.text)
    cached = content_audio_path(f"{stem}.mp3")
    if cached is not None:
        return AudioUrlResult(audio_url=content_audio_url(cached.name))
    try:
        audio = provider.synthesize(body.text)
    except TtsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not audio:
        # 网关对不存在的音色返回 200 + 0 字节：不落缓存文件（否则空文件永久命中）
        raise HTTPException(status_code=502, detail="TTS 返回空音频，请检查音色配置")
    path = save_content_audio_named(audio, ".mp3", stem)
    return AudioUrlResult(audio_url=content_audio_url(path.name))


class QuestionUpdate(SQLModel):
    band: str | None = None
    text: str | None = Field(default=None, min_length=1, max_length=512)
    translation: str | None = None
    audio_url: str | None = None
    # 上限 300：考试题（IELTS Part 2 长回答）；普通题 ≤60 由校验函数按合并后状态把关
    suggested_seconds: int | None = Field(default=None, ge=10, le=300)
    order_index: int | None = Field(default=None, ge=0)
    exam_kind: str | None = None
    exam_level: str | None = None
    cue_card_bullets: list[str] | None = None
    prep_seconds: int | None = None

    _text_nonempty = field_validator("text")(_strip_nonempty)
    _translation_blank = field_validator("translation")(_strip_blank)
    _audio_blank = field_validator("audio_url")(_strip_blank)


@router.post("/audio/upload", response_model=AudioUrlResult)
async def upload_standard_audio(_admin: TeacherUserDep, file: UploadFile) -> Any:
    """上传现成音频（学校已有的录音/外教音频），作为标准音使用。"""
    from pathlib import PurePosixPath

    suffix = PurePosixPath(file.filename or "").suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a", ".ogg", ".webm"}:
        raise HTTPException(status_code=422, detail="仅支持 mp3/wav/m4a/ogg/webm")
    max_bytes = settings.MAX_AUDIO_MB * 1024 * 1024
    data = bytearray()
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"音频超过 {settings.MAX_AUDIO_MB}MB 上限"
            )
    if not data:
        raise HTTPException(status_code=422, detail="音频为空")
    # 同步写盘（上限 20MB）放线程池，避免阻塞事件循环
    path = await run_in_threadpool(save_content_audio, bytes(data), suffix)
    return AudioUrlResult(audio_url=content_audio_url(path.name))
