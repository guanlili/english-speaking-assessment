"""管理端内容·篇目域：篇目 CRUD、拆句/复述句、题目说明、整篇切分。

从 admin_content 拆分（第二刀）；路由前缀/路径/权限零变化。
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import field_validator
from sqlalchemy import JSON, func
from sqlmodel import Field, SQLModel, col, select

from app import crud
from app.api.deps import SessionDep, TeacherUserDep
from app.api.routes._content_common import (
    VALID_BANDS,
    _reject_delete_items_queued,
    _reject_delete_with_queued_attempts,
    _reject_null_non_nullable,
    _strip_blank,
    _strip_nonempty,
)
from app.models import (
    AttemptItemType,
    Instruction,
    InstructionPublic,
    Passage,
    PassageCreate,
    PassagePublic,
    ReadingSentenceSeconds,
    RepeatSentence,
    Unit,
    get_datetime_utc,
    validate_exam_fields,
)
from app.services import content_access, reading

router = APIRouter(prefix="/admin", tags=["admin"])


# ── 内容请求模型（不复用 table=True 模型作请求体）────────────────────
# 语义约定：
# - 创建：必填字段缺失/空 → 422；范围越界（秒数/序号/档位）→ 422；非法外键 → 404/422
# - 更新：缺省字段不修改（exclude_unset）；可空字段（translation/audio_url/
#   passage_id/unit_id）传 null 清空；非空字段传 null → 422


class SentenceCreate(SQLModel):
    """新建复述句请求（独立创建或挂篇目）。"""

    passage_id: uuid.UUID | None = None
    order_index: int = Field(default=0, ge=0)
    text: str = Field(min_length=1, max_length=1024)
    translation: str | None = Field(default=None, max_length=1024)
    audio_url: str | None = Field(default=None, max_length=1024)
    suggested_seconds: int = Field(default=8, ge=3, le=60)
    replay_limit: int = Field(default=3, ge=0, le=9)
    # 分级题型训练（可空=普通课堂内容）：题型与级别分别建模
    exam_kind: str | None = None
    exam_level: str | None = None

    _text_nonempty = field_validator("text")(_strip_nonempty)
    _translation_blank = field_validator("translation")(_strip_blank)
    _audio_blank = field_validator("audio_url")(_strip_blank)


class SentenceUpdate(SQLModel):
    """更新复述句请求：缺省不修改；passage_id/translation/audio_url 可 null 清空。"""

    passage_id: uuid.UUID | None = None
    order_index: int | None = Field(default=None, ge=0)
    text: str | None = Field(default=None, min_length=1, max_length=1024)
    translation: str | None = Field(default=None, max_length=1024)
    audio_url: str | None = Field(default=None, max_length=1024)
    suggested_seconds: int | None = Field(default=None, ge=3, le=60)
    replay_limit: int | None = Field(default=None, ge=0, le=9)
    exam_kind: str | None = None
    exam_level: str | None = None

    _text_nonempty = field_validator("text")(_strip_nonempty)
    _translation_blank = field_validator("translation")(_strip_blank)
    _audio_blank = field_validator("audio_url")(_strip_blank)


class InstructionCreate(SQLModel):
    """新建题目说明请求：说明文字必填，停留秒数默认 20。"""

    title: str | None = Field(default=None, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    suggested_seconds: int = Field(default=20, ge=5, le=300)

    _title_blank = field_validator("title")(_strip_blank)
    _text_nonempty = field_validator("text")(_strip_nonempty)


class InstructionUpdate(SQLModel):
    """更新题目说明请求：缺省不修改；title 可 null 清空，text 不允许 null。"""

    title: str | None = Field(default=None, max_length=100)
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    suggested_seconds: int | None = Field(default=None, ge=5, le=300)

    _title_blank = field_validator("title")(_strip_blank)
    _text_nonempty = field_validator("text")(_strip_nonempty)


class PassageUpdate(SQLModel):
    """更新篇目请求：缺省不修改；translation/audio_url/unit_id 可 null 清空。"""

    reading_sentence_seconds: list[ReadingSentenceSeconds | None] | None = None
    reading_sentence_texts: list[str] | None = None
    # 拆句配音：键=句子原文，值=标准音地址；null 清空
    reading_sentence_audio: dict[str, str] | None = None

    title: str | None = Field(default=None, min_length=1, max_length=255)
    topic: str | None = Field(default=None, max_length=100)
    cefr_band: str | None = None
    text: str | None = Field(default=None, min_length=1)
    translation: str | None = Field(default=None, max_length=1024)
    audio_url: str | None = Field(default=None, max_length=1024)
    suggested_seconds: int | None = Field(default=None, ge=10, le=180)
    is_active: bool | None = None
    unit_id: uuid.UUID | None = None

    _title_nonempty = field_validator("title")(_strip_nonempty)
    _text_nonempty = field_validator("text")(_strip_nonempty)
    _topic_blank = field_validator("topic")(_strip_blank)
    _translation_blank = field_validator("translation")(_strip_blank)
    _audio_blank = field_validator("audio_url")(_strip_blank)


# ── 篇目与复述句 ─────────────────────────────────────────────────────


class PassageWithSentences(PassagePublic):
    sentences: list[RepeatSentence] = []
    reading_segments: list[str] = []
    reading_child_ids: list[uuid.UUID] = []


def _require_valid_band(band: str) -> None:
    if band not in VALID_BANDS:
        raise HTTPException(
            status_code=422,
            detail=f"CEFR 档位无效，可选：{'/'.join(sorted(VALID_BANDS))}",
        )


class PassagesListOut(SQLModel):
    """管理端篇目分页信封：count 为根篇目总数；limit=None 时全量（组卷/句库兼容）"""

    data: list[PassageWithSentences]
    count: int


@router.get("/passages", response_model=PassagesListOut)
def list_passages(
    session: SessionDep,
    _admin: TeacherUserDep,
    q: str | None = Query(default=None, description="标题/主题关键词过滤"),
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=500),
    ids: list[uuid.UUID] | None = Query(default=None),
) -> Any:
    """管理端篇目列表：按「根篇目」分页（拆句子篇不单占一行）+ 关键词过滤。

    limit=None 走全量——教师组卷/句库要跨全部篇目搜索，不能被默认页宽截断。
    句子与子篇只查本页根篇的，不再全表预取。
    """
    conditions = [col(Passage.parent_passage_id).is_(None)]
    if ids is not None:
        parent_ids = session.exec(
            select(Passage.parent_passage_id).where(col(Passage.id).in_(ids))
        ).all()
        conditions.append(
            col(Passage.id).in_({*ids, *(p for p in parent_ids if p is not None)})
        )
    if q and q.strip():
        needle = q.strip()
        conditions.append(
            col(Passage.title).icontains(needle) | col(Passage.topic).icontains(needle)  # type: ignore[operator]
        )
    count = session.exec(
        select(func.count()).select_from(Passage).where(*conditions)
    ).one()
    stmt = (
        select(Passage)
        .where(*conditions)
        .order_by(col(Passage.created_at), col(Passage.id))
        .offset(skip)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    passages = session.exec(stmt).all()
    passage_ids = [p.id for p in passages]
    sentences_by_passage: dict[uuid.UUID, list[RepeatSentence]] = {}
    if passage_ids:
        all_sentences = session.exec(
            select(RepeatSentence)
            .where(col(RepeatSentence.passage_id).in_(passage_ids))
            .order_by(col(RepeatSentence.order_index))
        ).all()
        for s in all_sentences:
            if s.passage_id is not None:
                sentences_by_passage.setdefault(s.passage_id, []).append(s)
    children_by_passage: dict[uuid.UUID, list[uuid.UUID]] = {}
    if passage_ids:
        child_rows = session.exec(
            select(Passage.id, Passage.parent_passage_id).where(
                col(Passage.parent_passage_id).in_(passage_ids)
            )
        ).all()
        for child_id, parent_id in child_rows:
            children_by_passage.setdefault(parent_id, []).append(child_id)
    result = []
    for passage in passages:
        item = PassageWithSentences.model_validate(passage)
        item.sentences = sentences_by_passage.get(passage.id, [])
        item.reading_segments = (
            _split_reading_sentences(passage.text) if passage.reading_split else []
        )
        item.reading_child_ids = children_by_passage.get(passage.id, [])
        result.append(item)
    return PassagesListOut(data=result, count=count)


@router.post("/passages", response_model=PassagePublic)
def create_passage(
    session: SessionDep, current_user: TeacherUserDep, passage_in: PassageCreate
) -> Any:
    _require_valid_band(passage_in.cefr_band)
    if passage_in.unit_id is not None and session.get(Unit, passage_in.unit_id) is None:
        raise HTTPException(status_code=422, detail="Unit not found")
    if passage_in.slug:
        duplicate = session.exec(
            select(Passage).where(Passage.slug == passage_in.slug)
        ).first()
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="slug 已存在")
    return crud.create_passage(
        session=session,
        passage_in=passage_in,
        owner_id=content_access.owner_for(current_user),
    )


@router.put("/passages/{passage_id}", response_model=PassagePublic)
def update_passage(
    session: SessionDep,
    current_user: TeacherUserDep,
    passage_id: uuid.UUID,
    passage_in: PassageUpdate,
) -> Any:
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    content_access.require_passage(session, current_user, passage)
    update = passage_in.model_dump(exclude={"slug"}, exclude_unset=True)
    # 非空字段不允许显式清空（slug 由创建决定，不在此更新）
    _reject_null_non_nullable(
        update, {"title", "text", "cefr_band", "suggested_seconds", "is_active"}
    )
    if "cefr_band" in update:
        _require_valid_band(str(update["cefr_band"]))
    if "unit_id" in update and update["unit_id"] is not None:
        if session.get(Unit, update["unit_id"]) is None:
            raise HTTPException(status_code=422, detail="Unit not found")
    if "topic" in update and update["topic"] is None:
        # topic 非空列：显式清空/空串归一为空串（挂单元时反正会被派生值覆盖）
        update["topic"] = ""
    segments = reading.split_reading_sentences(str(update.get("text", passage.text)))
    expected_segments = update.pop("reading_sentence_texts", None)
    if expected_segments is not None and expected_segments != segments:
        raise HTTPException(422, detail="Reading sentences changed")
    if "reading_sentence_seconds" in update:
        durations = update["reading_sentence_seconds"]
        if durations is not None and len(durations) != len(segments):
            raise HTTPException(422, detail="Reading sentence durations count mismatch")
    elif segments != reading.split_reading_sentences(passage.text):
        update["reading_sentence_seconds"] = None
    if "reading_sentence_audio" in update:
        audio_map = update["reading_sentence_audio"]
        if audio_map is not None:
            if any(len(url) > 1024 for url in audio_map.values()):
                raise HTTPException(422, detail="Reading sentence audio url too long")
            # 键按当前分句修剪：正文编辑后失配的旧键自然淘汰，字典不随时间膨胀
            update["reading_sentence_audio"] = {
                key: url for key, url in audio_map.items() if key in segments
            }
        # 正文变更但未传配音字典时不重置：文本键自适应，未命中句子等同未配音
    passage.sqlmodel_update(update)
    # 主题单一事实源：挂单元的篇目 topic 一律跟随单元，显式传入值不生效
    if passage.unit_id is not None:
        passage.topic = crud.derive_passage_topic(
            session, passage.unit_id, passage.topic
        )
    session.add(passage)
    session.commit()
    session.refresh(passage)
    return passage


@router.delete("/passages/{passage_id}")
def delete_passage(
    session: SessionDep, current_user: TeacherUserDep, passage_id: uuid.UUID
) -> dict[str, str]:
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    content_access.require_passage(session, current_user, passage)
    sentence_ids = session.exec(
        select(RepeatSentence.id).where(RepeatSentence.passage_id == passage_id)
    ).all()
    child_ids = list(
        session.exec(
            select(Passage.id).where(Passage.parent_passage_id == passage_id)
        ).all()
    )
    if child_ids:
        sentence_ids = [
            *sentence_ids,
            *session.exec(
                select(RepeatSentence.id).where(
                    col(RepeatSentence.passage_id).in_(child_ids)
                )
            ).all(),
        ]
    _reject_delete_items_queued(
        session,
        [(passage_id, AttemptItemType.PASSAGE)]
        + [(pid, AttemptItemType.PASSAGE) for pid in child_ids]
        + [(sid, AttemptItemType.REPEAT) for sid in sentence_ids],
    )
    session.delete(passage)  # 复述句/作答按外键级联
    session.commit()
    return {"message": "deleted"}


def next_sentence_order(session: Any, passage_id: uuid.UUID | None) -> int:
    """复述句下一题排序号：挂篇目取同篇目 max+1，独立句取全局 max+1。"""
    stmt = select(func.max(RepeatSentence.order_index))  # type: ignore[call-overload]
    if passage_id is not None:
        stmt = stmt.where(RepeatSentence.passage_id == passage_id)  # type: ignore[arg-type]
    max_order = session.exec(stmt).one()
    return (max_order or 0) + 1


@router.post("/passages/{passage_id}/sentences", response_model=RepeatSentence)
def create_sentence(
    session: SessionDep,
    current_user: TeacherUserDep,
    passage_id: uuid.UUID,
    sentence_in: SentenceCreate,
) -> Any:
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    content_access.require_passage(session, current_user, passage)
    sentence = RepeatSentence.model_validate(sentence_in.model_dump())
    sentence.passage_id = passage_id
    sentence.owner_id = content_access.sentence_owner_for(
        session, current_user, passage
    )
    sentence.order_index = next_sentence_order(session, passage_id)
    session.add(sentence)
    session.commit()
    session.refresh(sentence)
    return sentence


class SentenceWithPassage(RepeatSentence):
    """平铺复述句库视图：带所属篇目标题（独立句为 null）。"""

    exam_settings: dict[str, object] | None = Field(default=None, sa_type=JSON)
    passage_title: str | None = None  # 考试字段自 RepeatSentence 继承


class SentencesListOut(SQLModel):
    data: list[SentenceWithPassage]
    count: int


@router.get("/sentences-page", response_model=SentencesListOut)
def list_sentences_page(
    session: SessionDep,
    _admin: TeacherUserDep,
    q: str | None = Query(default=None, max_length=200),
    standalone_only: bool = False,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> SentencesListOut:
    """题库管理分页：过滤与计数同口径，只读取当前页的挂靠篇目标题。"""
    conditions = []
    if q and q.strip():
        conditions.append(
            col(RepeatSentence.text).icontains(q.strip(), autoescape=True)
        )
    if standalone_only:
        conditions.append(col(RepeatSentence.passage_id).is_(None))
    count = session.exec(
        select(func.count()).select_from(RepeatSentence).where(*conditions)
    ).one()
    rows = session.exec(
        select(RepeatSentence, Passage.title)
        .outerjoin(Passage, col(RepeatSentence.passage_id) == col(Passage.id))
        .where(*conditions)
        .order_by(col(RepeatSentence.created_at), col(RepeatSentence.id))
        .offset(skip)
        .limit(limit)
    ).all()
    return SentencesListOut(
        data=[
            SentenceWithPassage(**s.model_dump(), passage_title=title)
            for s, title in rows
        ],
        count=count,
    )


@router.get("/sentences", response_model=list[SentenceWithPassage])
def list_sentences_flat(
    session: SessionDep,
    _admin: TeacherUserDep,
    exam_kind: str | None = Query(default=None, description="考试题型过滤"),
    exam_level: str | None = Query(default=None, description="考试级别过滤"),
    ids: list[uuid.UUID] | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> Any:
    """复述句独立题库：全部复述句平铺（含挂篇目的），按创建顺序。"""
    stmt = select(RepeatSentence).order_by(col(RepeatSentence.created_at))
    if ids is not None:
        stmt = stmt.where(col(RepeatSentence.id).in_(ids))
    if exam_kind is not None:
        stmt = stmt.where(RepeatSentence.exam_kind == exam_kind)  # type: ignore[arg-type]
    if exam_level is not None:
        stmt = stmt.where(RepeatSentence.exam_level == exam_level)  # type: ignore[arg-type]
    if q and q.strip():
        stmt = stmt.where(
            col(RepeatSentence.text).icontains(q.strip(), autoescape=True)
        )
    stmt = stmt.order_by(col(RepeatSentence.id)).offset(skip)
    if limit is not None:
        stmt = stmt.limit(limit)
    sentences = session.exec(stmt).all()
    passage_titles = dict(
        session.exec(
            select(Passage.id, Passage.title).where(
                col(Passage.id).in_(
                    {s.passage_id for s in sentences if s.passage_id is not None}
                )
            )
        ).all()
    )
    return [
        SentenceWithPassage(
            **s.model_dump(),
            passage_title=passage_titles.get(s.passage_id) if s.passage_id else None,
        )
        for s in sentences
    ]


@router.post("/sentences", response_model=RepeatSentence)
def create_sentence_standalone(
    session: SessionDep,
    current_user: TeacherUserDep,
    sentence_in: SentenceCreate,
) -> Any:
    """独立创建复述句（不挂篇目）：题目库三题型互相独立后的复述题入口。

    传 passage_id 仍可挂到篇目（自主练习轮会随篇目出现）。
    """
    passage = None
    if sentence_in.passage_id is not None:
        passage = session.get(Passage, sentence_in.passage_id)
        if passage is None:
            raise HTTPException(status_code=404, detail="Passage not found")
        content_access.require_passage(session, current_user, passage)
    validate_exam_fields("repeat", sentence_in.exam_kind, sentence_in.exam_level)
    sentence = RepeatSentence.model_validate(sentence_in.model_dump())
    sentence.owner_id = content_access.sentence_owner_for(
        session, current_user, passage
    )
    sentence.order_index = next_sentence_order(session, sentence.passage_id)
    session.add(sentence)
    session.commit()
    session.refresh(sentence)
    return sentence


@router.put("/sentences/{sentence_id}", response_model=RepeatSentence)
def update_sentence(
    session: SessionDep,
    current_user: TeacherUserDep,
    sentence_id: uuid.UUID,
    sentence_in: SentenceUpdate,
) -> Any:
    sentence = session.get(RepeatSentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    content_access.require_sentence(session, current_user, sentence)
    update = sentence_in.model_dump(exclude={"id"}, exclude_unset=True)
    # 非空字段不允许显式清空（text/order_index/suggested_seconds/replay_limit）
    _reject_null_non_nullable(
        update, {"text", "order_index", "suggested_seconds", "replay_limit"}
    )
    if "passage_id" in update and update["passage_id"] is not None:
        target = session.get(Passage, update["passage_id"])
        if target is None:
            raise HTTPException(status_code=422, detail="Passage not found")
        content_access.require_passage(session, current_user, target)
        update["owner_id"] = content_access.passage_owner(session, target)
    # 部分更新：与原记录合并出完整状态再校验；显式清题型级联清级别
    merged_kind = update.get("exam_kind", sentence.exam_kind)
    merged_level = update.get("exam_level", sentence.exam_level)
    if "exam_kind" in update and update["exam_kind"] is None:
        merged_level = None
    validate_exam_fields("repeat", merged_kind, merged_level)
    if "exam_kind" in update and update["exam_kind"] is None:
        update["exam_level"] = None
    sentence.sqlmodel_update(update)
    session.add(sentence)
    session.commit()
    session.refresh(sentence)
    return sentence


@router.delete("/sentences/{sentence_id}")
def delete_sentence(
    session: SessionDep, current_user: TeacherUserDep, sentence_id: uuid.UUID
) -> dict[str, str]:
    sentence = session.get(RepeatSentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    content_access.require_sentence(session, current_user, sentence)
    _reject_delete_with_queued_attempts(session, sentence_id, AttemptItemType.REPEAT)
    session.delete(sentence)
    session.commit()
    return {"message": "deleted"}


# ── 题目说明（第四种题型：无作答的纯文字引导页） ────────────────────


@router.get("/instructions", response_model=list[InstructionPublic])
def list_instructions(
    session: SessionDep,
    _admin: TeacherUserDep,
    q: str | None = Query(default=None, max_length=200),
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> Any:
    """题目说明库：组卷时可勾选复用的全部说明，按创建顺序。"""
    stmt = select(Instruction)
    if q and q.strip():
        stmt = stmt.where(
            col(Instruction.text).icontains(q.strip(), autoescape=True)
            | col(Instruction.title).icontains(q.strip(), autoescape=True)
        )
    stmt = stmt.order_by(col(Instruction.created_at), col(Instruction.id)).offset(skip)
    if limit is not None:
        stmt = stmt.limit(limit)
    return session.exec(stmt).all()


@router.post("/instructions", response_model=InstructionPublic)
def create_instruction(
    session: SessionDep,
    current_user: TeacherUserDep,
    instruction_in: InstructionCreate,
) -> Any:
    instruction = Instruction.model_validate(instruction_in.model_dump())
    instruction.owner_id = content_access.owner_for(current_user)
    session.add(instruction)
    session.commit()
    session.refresh(instruction)
    return instruction


@router.put("/instructions/{instruction_id}", response_model=InstructionPublic)
def update_instruction(
    session: SessionDep,
    current_user: TeacherUserDep,
    instruction_id: uuid.UUID,
    instruction_in: InstructionUpdate,
) -> Any:
    instruction = session.get(Instruction, instruction_id)
    if instruction is None:
        raise HTTPException(status_code=404, detail="Instruction not found")
    content_access.require_instruction(current_user, instruction)
    update = instruction_in.model_dump(exclude_unset=True)
    _reject_null_non_nullable(update, {"text", "suggested_seconds"})
    instruction.sqlmodel_update(update)
    instruction.updated_at = get_datetime_utc()
    session.add(instruction)
    session.commit()
    session.refresh(instruction)
    return instruction


@router.delete("/instructions/{instruction_id}")
def delete_instruction(
    session: SessionDep, current_user: TeacherUserDep, instruction_id: uuid.UUID
) -> dict[str, str]:
    """删除安全：发布快照深拷贝文字，历史练习不受影响。"""
    instruction = session.get(Instruction, instruction_id)
    if instruction is None:
        raise HTTPException(status_code=404, detail="Instruction not found")
    content_access.require_instruction(current_user, instruction)
    session.delete(instruction)
    session.commit()
    return {"message": "deleted"}


class PassageSplitResult(SQLModel):
    created: int
    passage_ids: list[uuid.UUID] = []
    original_deactivated: bool = False


@router.post("/passages/{passage_id}/split", response_model=PassageSplitResult)
def split_passage_into_readings(
    session: SessionDep,
    current_user: TeacherUserDep,
    passage_id: uuid.UUID,
    mode: Literal["paragraph", "sentence"] = "sentence",
) -> Any:
    """启用逐句拆分：发布/练习时该文章按句展开成多道朗读题（见 services/reading.py）。"""
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    content_access.require_passage(session, current_user, passage)

    if passage.parent_passage_id is not None:
        raise HTTPException(status_code=422, detail="请在原文章下拆分句子")
    segments = _split_reading_sentences(passage.text)
    if len(segments) < 2:
        raise HTTPException(
            status_code=422,
            detail=(
                "正文不足两句，无法按句拆分"
                if mode == "sentence"
                else "正文只有一个段落，无需拆分；请先用换行分段"
            ),
        )

    passage.reading_split = True
    session.add(passage)
    session.commit()
    return PassageSplitResult(created=len(segments))


@router.delete("/passages/{passage_id}/split", response_model=PassagePublic)
def unsplit_passage_readings(
    session: SessionDep, current_user: TeacherUserDep, passage_id: uuid.UUID
) -> Any:
    """取消拆分：此后发布/练习回到整篇一道题；已发布快照不可变不受影响。"""
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    content_access.require_passage(session, current_user, passage)
    if passage.parent_passage_id is not None:
        raise HTTPException(status_code=422, detail="请在原文章下取消拆分")
    if passage.reading_split:
        passage.reading_split = False
        session.add(passage)
        session.commit()
    session.refresh(passage)
    return passage


def _split_reading_sentences(text: str) -> list[str]:
    """按正文顺序拆句，保留句末标点（算法真源在 services/reading.py）。"""
    return reading.split_reading_sentences(text)
