"""管理员内容管理接口（PRD：内容槽由校方录入，软件只留槽位）。

篇目、情景和问法允许教师/管理员维护；课堂平台配置仅超级管理员可操作。
EIP 文本只进数据库，不进 git。

    /admin/passages            篇目 CRUD（含复述句子路由）
    /admin/scenarios           情景 + 分档问法 CRUD
    /admin/classrooms          课堂码列表 / 停用
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import field_validator
from sqlalchemy import func
from sqlmodel import Field, Session, SQLModel, col, select

from app import crud
from app.api.deps import SessionDep, SuperUserDep, TeacherUserDep
from app.core.config import settings
from app.core.storage import (
    content_audio_path,
    content_audio_url,
    save_content_audio,
    save_content_audio_named,
)
from app.models import (
    EXAM_KIND_QUESTION,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Classroom,
    ClassroomPublic,
    Instruction,
    InstructionPublic,
    Passage,
    PassageCreate,
    PassagePublic,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    ScenarioQuestionPublic,
    SentenceFrame,
    SentenceFramePublic,
    Unit,
    UnitCreate,
    UnitPublic,
    UnitUpdate,
    get_datetime_utc,
    validate_exam_fields,
    validate_question_suggested_seconds,
)
from app.services import reading

router = APIRouter(prefix="/admin", tags=["admin"])

VALID_BANDS = {"A2", "B1", "B2"}


def _strip_blank(value: str | None) -> str | None:
    """可空字符串字段：空白串归 None（前端空输入直接清空语义）。"""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _strip_nonempty(value: str | None) -> str | None:
    """非空字符串字段：去空白后仍为空 → 校验失败（更新模型里传 null 走 422）。"""
    if value is None:
        return value
    stripped = value.strip()
    if not stripped:
        raise ValueError("内容不能为空")
    return stripped


def _reject_null_non_nullable(
    update: dict[str, Any], non_nullable_fields: set[str]
) -> None:
    """更新语义：非空字段不允许显式传 null（传 null 返回 422）。

    允许为空的字段（translation/audio_url/passage_id/unit_id）传 null = 清空，
    不受此限制。
    """
    for field in non_nullable_fields:
        if field in update and update[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"{field} 不能为 null，如需清空请传空字符串或省略",
            )


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


class ScenarioCreate(SQLModel):
    """新建情景请求：主题必填且非空。"""

    topic: str = Field(min_length=1, max_length=100)
    is_active: bool = True

    _topic_nonempty = field_validator("topic")(_strip_nonempty)


class QuestionCreate(SQLModel):
    """新建问法请求：scenario_id 兼容旧客户端，以路径参数为准。"""

    scenario_id: uuid.UUID | None = None
    band: str = Field(default="B1", max_length=10)
    order_index: int = Field(default=0, ge=0)
    text: str = Field(min_length=1, max_length=512)
    translation: str | None = Field(default=None, max_length=1024)
    audio_url: str | None = Field(default=None, max_length=1024)
    # 上限 300：考试题（IELTS Part 2 长回答）；普通题 ≤60 由校验函数把关
    suggested_seconds: int = Field(default=20, ge=10, le=300)
    # 分级题型训练（可空=普通情景问法）：话题卡仅 IELTS Part 2
    exam_kind: str | None = None
    exam_level: str | None = None
    cue_card_bullets: list[str] | None = None
    prep_seconds: int | None = None

    _text_nonempty = field_validator("text")(_strip_nonempty)
    _translation_blank = field_validator("translation")(_strip_blank)
    _audio_blank = field_validator("audio_url")(_strip_blank)


class PassageUpdate(SQLModel):
    """更新篇目请求：缺省不修改；translation/audio_url/unit_id 可 null 清空。"""

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


def _reject_delete_with_queued_attempts(
    session: Session, item_id: uuid.UUID, item_type: str
) -> None:
    """有排队评分中的作答时拒绝删除内容（否则 worker 领取时找不到题目会失败）。"""
    has_queued = (
        session.exec(
            select(Attempt.id)
            .where(
                Attempt.item_id == item_id,
                Attempt.item_type == item_type,
                col(Attempt.status).in_([AttemptStatus.QUEUED, AttemptStatus.SCORING]),
            )
            .limit(1)
        ).first()
        is not None
    )
    if has_queued:
        raise HTTPException(
            status_code=409,
            detail="有正在评分中的作答，请稍后再删除",
        )


def _reject_delete_items_queued(
    session: Session, items: list[tuple[uuid.UUID, str]]
) -> None:
    """批量检查多个 item 是否有待评作答，任一有则拒绝删除。"""
    if not items:
        return
    item_ids_by_type: dict[str, list[uuid.UUID]] = {}
    for item_id, item_type in items:
        item_ids_by_type.setdefault(item_type, []).append(item_id)
    has_queued = False
    for item_type, ids in item_ids_by_type.items():
        found = session.exec(
            select(Attempt.id)
            .where(
                col(Attempt.item_id).in_(ids),
                Attempt.item_type == item_type,
                col(Attempt.status).in_([AttemptStatus.QUEUED, AttemptStatus.SCORING]),
            )
            .limit(1)
        ).first()
        if found is not None:
            has_queued = True
            break
    if has_queued:
        raise HTTPException(
            status_code=409,
            detail="有正在评分中的作答，请稍后再删除",
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
) -> Any:
    """管理端篇目列表：按「根篇目」分页（拆句子篇不单占一行）+ 关键词过滤。

    limit=None 走全量——教师组卷/句库要跨全部篇目搜索，不能被默认页宽截断。
    句子与子篇只查本页根篇的，不再全表预取。
    """
    conditions = [col(Passage.parent_passage_id).is_(None)]
    if q and q.strip():
        needle = q.strip()
        conditions.append(
            col(Passage.title).icontains(needle)
            | col(Passage.topic).icontains(needle)  # type: ignore[operator]
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
    session: SessionDep, _admin: TeacherUserDep, passage_in: PassageCreate
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
    return crud.create_passage(session=session, passage_in=passage_in)


@router.put("/passages/{passage_id}", response_model=PassagePublic)
def update_passage(
    session: SessionDep,
    _admin: TeacherUserDep,
    passage_id: uuid.UUID,
    passage_in: PassageUpdate,
) -> Any:
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
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
    session: SessionDep, _admin: TeacherUserDep, passage_id: uuid.UUID
) -> dict[str, str]:
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
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


def next_question_order(session: Any, scenario_id: uuid.UUID) -> int:
    """同主题下一道题的排序号：现存最大 +1（删除中间题不影响单调性）。"""
    max_order = session.exec(
        select(func.max(ScenarioQuestion.order_index)).where(  # type: ignore[call-overload]
            ScenarioQuestion.scenario_id == scenario_id,
        )
    ).one()
    return (max_order or 0) + 1


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
    _admin: TeacherUserDep,
    passage_id: uuid.UUID,
    sentence_in: SentenceCreate,
) -> Any:
    if session.get(Passage, passage_id) is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    sentence = RepeatSentence.model_validate(sentence_in.model_dump())
    sentence.passage_id = passage_id
    sentence.order_index = next_sentence_order(session, passage_id)
    session.add(sentence)
    session.commit()
    session.refresh(sentence)
    return sentence


class SentenceWithPassage(RepeatSentence):
    """平铺复述句库视图：带所属篇目标题（独立句为 null）。"""

    passage_title: str | None = None  # 考试字段自 RepeatSentence 继承


@router.get("/sentences", response_model=list[SentenceWithPassage])
def list_sentences_flat(
    session: SessionDep,
    _admin: TeacherUserDep,
    exam_kind: str | None = Query(default=None, description="考试题型过滤"),
    exam_level: str | None = Query(default=None, description="考试级别过滤"),
) -> Any:
    """复述句独立题库：全部复述句平铺（含挂篇目的），按创建顺序。"""
    stmt = select(RepeatSentence).order_by(col(RepeatSentence.created_at))
    if exam_kind is not None:
        stmt = stmt.where(RepeatSentence.exam_kind == exam_kind)  # type: ignore[arg-type]
    if exam_level is not None:
        stmt = stmt.where(RepeatSentence.exam_level == exam_level)  # type: ignore[arg-type]
    sentences = session.exec(stmt).all()
    passage_titles = dict(session.exec(select(Passage.id, Passage.title)).all())
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
    _admin: TeacherUserDep,
    sentence_in: SentenceCreate,
) -> Any:
    """独立创建复述句（不挂篇目）：题目库三题型互相独立后的复述题入口。

    传 passage_id 仍可挂到篇目（自主练习轮会随篇目出现）。
    """
    if (
        sentence_in.passage_id is not None
        and session.get(Passage, sentence_in.passage_id) is None
    ):
        raise HTTPException(status_code=404, detail="Passage not found")
    validate_exam_fields("repeat", sentence_in.exam_kind, sentence_in.exam_level)
    sentence = RepeatSentence.model_validate(sentence_in.model_dump())
    sentence.order_index = next_sentence_order(session, sentence.passage_id)
    session.add(sentence)
    session.commit()
    session.refresh(sentence)
    return sentence


@router.put("/sentences/{sentence_id}", response_model=RepeatSentence)
def update_sentence(
    session: SessionDep,
    _admin: TeacherUserDep,
    sentence_id: uuid.UUID,
    sentence_in: SentenceUpdate,
) -> Any:
    sentence = session.get(RepeatSentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    update = sentence_in.model_dump(exclude={"id"}, exclude_unset=True)
    # 非空字段不允许显式清空（text/order_index/suggested_seconds/replay_limit）
    _reject_null_non_nullable(
        update, {"text", "order_index", "suggested_seconds", "replay_limit"}
    )
    if "passage_id" in update and update["passage_id"] is not None:
        if session.get(Passage, update["passage_id"]) is None:
            raise HTTPException(status_code=422, detail="Passage not found")
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
    session: SessionDep, _admin: TeacherUserDep, sentence_id: uuid.UUID
) -> dict[str, str]:
    sentence = session.get(RepeatSentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    _reject_delete_with_queued_attempts(session, sentence_id, AttemptItemType.REPEAT)
    session.delete(sentence)
    session.commit()
    return {"message": "deleted"}


# ── 题目说明（第四种题型：无作答的纯文字引导页） ────────────────────


@router.get("/instructions", response_model=list[InstructionPublic])
def list_instructions(
    session: SessionDep,
    _admin: TeacherUserDep,
) -> Any:
    """题目说明库：组卷时可勾选复用的全部说明，按创建顺序。"""
    return session.exec(select(Instruction).order_by(col(Instruction.created_at))).all()


@router.post("/instructions", response_model=InstructionPublic)
def create_instruction(
    session: SessionDep,
    _admin: TeacherUserDep,
    instruction_in: InstructionCreate,
) -> Any:
    instruction = Instruction.model_validate(instruction_in.model_dump())
    session.add(instruction)
    session.commit()
    session.refresh(instruction)
    return instruction


@router.put("/instructions/{instruction_id}", response_model=InstructionPublic)
def update_instruction(
    session: SessionDep,
    _admin: TeacherUserDep,
    instruction_id: uuid.UUID,
    instruction_in: InstructionUpdate,
) -> Any:
    instruction = session.get(Instruction, instruction_id)
    if instruction is None:
        raise HTTPException(status_code=404, detail="Instruction not found")
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
    session: SessionDep, _admin: TeacherUserDep, instruction_id: uuid.UUID
) -> dict[str, str]:
    """删除安全：发布快照深拷贝文字，历史练习不受影响。"""
    instruction = session.get(Instruction, instruction_id)
    if instruction is None:
        raise HTTPException(status_code=404, detail="Instruction not found")
    session.delete(instruction)
    session.commit()
    return {"message": "deleted"}


# ── 情景与问法 ───────────────────────────────────────────────────────


class ScenariosListOut(SQLModel):
    """问答题库主题分页信封：count 为主题总数；limit=None 时全量"""

    data: list[ScenarioOut]
    count: int


class ScenarioOut(SQLModel):
    """list_scenarios 的响应形状：情景 + 其问法列表。"""

    id: uuid.UUID
    topic: str
    is_active: bool
    questions: list[ScenarioQuestionPublic]


@router.get("/scenarios", response_model=ScenariosListOut)
def list_scenarios(
    session: SessionDep,
    _admin: TeacherUserDep,
    q: str | None = Query(default=None, description="主题关键词过滤"),
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=500),
) -> Any:
    """问答题库主题列表：分页 + 主题关键词（limit=None 全量，组卷选择器兼容）。"""
    conditions = []
    if q and q.strip():
        conditions.append(col(Scenario.topic).icontains(q.strip()))
    count = session.exec(
        select(func.count()).select_from(Scenario).where(*conditions)
    ).one()
    # Scenario 无 created_at 列；topic 唯一 + id 兜底，分页序稳定
    stmt = (
        select(Scenario)
        .where(*conditions)
        .order_by(col(Scenario.topic), col(Scenario.id))
    )
    if limit is not None:
        stmt = stmt.offset(skip).limit(limit)
    else:
        stmt = stmt.offset(skip)
    scenarios = session.exec(stmt).all()
    scenario_ids = [s.id for s in scenarios]
    questions_by_scenario: dict[uuid.UUID, list[ScenarioQuestion]] = {}
    if scenario_ids:
        all_questions = session.exec(
            select(ScenarioQuestion)
            .where(col(ScenarioQuestion.scenario_id).in_(scenario_ids))
            .order_by(col(ScenarioQuestion.order_index))
        ).all()
        for q in all_questions:
            questions_by_scenario.setdefault(q.scenario_id, []).append(q)
    result = []
    for scenario in scenarios:
        questions = questions_by_scenario.get(scenario.id, [])
        result.append(
            ScenarioOut(
                id=scenario.id,
                topic=scenario.topic,
                is_active=scenario.is_active,
                questions=[ScenarioQuestionPublic.model_validate(q) for q in questions],
            )
        )
    return ScenariosListOut(data=result, count=count)


@router.post("/scenarios")
def create_scenario(
    session: SessionDep, _admin: TeacherUserDep, scenario_in: ScenarioCreate
) -> Any:
    duplicate = session.exec(
        select(Scenario).where(Scenario.topic == scenario_in.topic)
    ).first()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="主题已存在")
    scenario = Scenario.model_validate(scenario_in.model_dump())
    session.add(scenario)
    session.commit()
    session.refresh(scenario)
    return scenario


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(
    session: SessionDep, _admin: TeacherUserDep, scenario_id: uuid.UUID
) -> dict[str, str]:
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    question_ids = session.exec(
        select(ScenarioQuestion.id).where(ScenarioQuestion.scenario_id == scenario_id)
    ).all()
    _reject_delete_items_queued(
        session,
        [(qid, AttemptItemType.QUESTION) for qid in question_ids],
    )
    session.delete(scenario)
    session.commit()
    return {"message": "deleted"}


@router.post(
    "/scenarios/{scenario_id}/questions", response_model=ScenarioQuestionPublic
)
def create_question(
    session: SessionDep,
    _admin: TeacherUserDep,
    scenario_id: uuid.UUID,
    question_in: QuestionCreate,
) -> Any:
    if session.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if question_in.band not in VALID_BANDS:
        raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
    validate_exam_fields(
        "question",
        question_in.exam_kind,
        question_in.exam_level,
        question_in.cue_card_bullets,
        question_in.prep_seconds,
    )
    validate_question_suggested_seconds(
        question_in.suggested_seconds, question_in.exam_kind
    )
    question = ScenarioQuestion.model_validate(
        {
            **question_in.model_dump(exclude={"scenario_id", "order_index"}),
            "scenario_id": scenario_id,
        }
    )
    # 排序号服务端生成：删过中间题后仍单调递增，不信任前端数组长度
    question.order_index = next_question_order(session, scenario_id)
    session.add(question)
    session.commit()
    session.refresh(question)
    return question


@router.delete("/questions/{question_id}")
def delete_question(
    session: SessionDep, _admin: TeacherUserDep, question_id: uuid.UUID
) -> dict[str, str]:
    question = session.get(ScenarioQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    _reject_delete_with_queued_attempts(session, question_id, AttemptItemType.QUESTION)
    session.delete(question)
    session.commit()
    return {"message": "deleted"}


# ── 题库（全局视图 + 批量录入）──────────────────────────────────────


class QuestionBankListOut(SQLModel):
    """问答题库分页信封：count 反映过滤后的总数"""

    data: list[QuestionBankOut]
    count: int


class QuestionBankOut(SQLModel):
    """题库全局视图：带上主题，供管理端筛选/搜索。"""

    id: uuid.UUID
    scenario_id: uuid.UUID
    topic: str
    band: str
    order_index: int
    text: str
    translation: str | None = None
    suggested_seconds: int
    # 分级题型训练（可空=普通情景问法）
    exam_kind: str | None = None
    exam_level: str | None = None
    cue_card_bullets: list[str] | None = None
    prep_seconds: int | None = None


@router.get("/questions", response_model=QuestionBankListOut)
def list_question_bank(
    session: SessionDep,
    _admin: TeacherUserDep,
    topic: str | None = Query(default=None, description="按主题精确过滤"),
    band: str | None = Query(default=None, description="A2/B1/B2"),
    q: str | None = Query(default=None, description="题目/中文提示关键词"),
    exam_kind: str | None = Query(default=None, description="考试题型过滤"),
    exam_level: str | None = Query(default=None, description="考试级别过滤"),
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=500),
) -> Any:
    conditions = []
    if topic is not None:
        conditions.append(Scenario.topic == topic)
    if band is not None:
        if band not in VALID_BANDS:
            raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
        conditions.append(ScenarioQuestion.band == band)
    if q and q.strip():
        needle = q.strip()
        conditions.append(
            col(ScenarioQuestion.text).icontains(needle)
            | col(ScenarioQuestion.translation).icontains(needle)  # type: ignore[operator]
        )
    if exam_kind is not None:
        conditions.append(ScenarioQuestion.exam_kind == exam_kind)  # type: ignore[arg-type]
    if exam_level is not None:
        conditions.append(ScenarioQuestion.exam_level == exam_level)  # type: ignore[arg-type]
    # count 与数据同条件：分页总数必须反映过滤后的集合
    count = session.exec(
        select(func.count())
        .select_from(ScenarioQuestion)
        .join(Scenario, ScenarioQuestion.scenario_id == Scenario.id)  # ty: ignore[invalid-argument-type]
        .where(*conditions)
    ).one()
    stmt = (
        select(ScenarioQuestion, Scenario.topic)
        .join(Scenario, ScenarioQuestion.scenario_id == Scenario.id)  # ty: ignore[invalid-argument-type]
        .where(*conditions)
        .order_by(
            col(Scenario.topic),
            col(ScenarioQuestion.band),
            col(ScenarioQuestion.order_index),
            col(ScenarioQuestion.id),
        )
        .offset(skip)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = session.exec(stmt).all()
    return QuestionBankListOut(
        data=[
            QuestionBankOut(
                id=question.id,
                scenario_id=question.scenario_id,
                topic=topic_name,
                band=question.band,
                order_index=question.order_index,
                text=question.text,
                translation=question.translation,
                suggested_seconds=question.suggested_seconds,
                exam_kind=question.exam_kind,
                exam_level=question.exam_level,
                cue_card_bullets=question.cue_card_bullets,
                prep_seconds=question.prep_seconds,
            )
            for question, topic_name in rows
        ],
        count=count,
    )


class BatchQuestionItem(SQLModel):
    """批量录入的单条：空文本/秒数越界等校验放处理器里逐条做，
    不在模型层拦——否则一条非法会把整批 422 掉。"""

    text: str = ""
    translation: str | None = None
    suggested_seconds: int = 20


class BatchQuestionCreate(SQLModel):
    # 档位已不参与抽题与展示（2026-09-29 产品决策：问答不分级，老师自由编排）；
    # 字段保留兼容旧客户端，缺省落 B1
    band: str = "B1"
    items: list[BatchQuestionItem]

    @field_validator("items")
    @classmethod
    def _cap_items(cls, v: list[BatchQuestionItem]) -> list[BatchQuestionItem]:
        # 单事务批量插入上限，防超大粘贴把一个事务撑爆
        if len(v) > 1000:
            raise ValueError("单次批量录入最多 1000 条，请分批提交")
        return v


class BatchFailItem(SQLModel):
    index: int
    reason: str


class BatchQuestionResult(SQLModel):
    created: int
    failed: list[BatchFailItem]


@router.post(
    "/scenarios/{scenario_id}/questions/batch",
    response_model=BatchQuestionResult,
)
def create_questions_batch(
    session: SessionDep,
    _admin: TeacherUserDep,
    scenario_id: uuid.UUID,
    body: BatchQuestionCreate,
) -> Any:
    """批量录入问法：逐条校验，合法的入库，非法的带原因返回（部分成功）。"""
    if session.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if body.band not in VALID_BANDS:
        raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
    if not body.items:
        raise HTTPException(status_code=422, detail="没有可录入的题目")

    next_order = 1 + (
        session.exec(
            select(func.max(ScenarioQuestion.order_index)).where(  # type: ignore[call-overload]
                ScenarioQuestion.scenario_id == scenario_id,
            )
        ).one()
        or 0
    )

    created = 0
    failed: list[BatchFailItem] = []
    for i, item in enumerate(body.items):
        text = item.text.strip()
        if not text:
            failed.append(BatchFailItem(index=i, reason="题目内容为空"))
            continue
        if len(text) > 512:
            failed.append(BatchFailItem(index=i, reason="题目过长（>512 字符）"))
            continue
        if not 10 <= item.suggested_seconds <= 60:
            failed.append(
                BatchFailItem(
                    index=i,
                    reason=f"建议秒数需在 10–60 之间（当前 {item.suggested_seconds}）",
                )
            )
            continue
        session.add(
            ScenarioQuestion(
                scenario_id=scenario_id,
                band=body.band,
                order_index=next_order + created,
                text=text,
                translation=(item.translation or "").strip() or None,
                suggested_seconds=item.suggested_seconds,
            )
        )
        created += 1
    if created:
        session.commit()
    return BatchQuestionResult(created=created, failed=failed)


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


@router.post("/units", response_model=UnitPublic)
def create_unit(
    session: SessionDep, _admin: TeacherUserDep, unit_in: UnitCreate
) -> Any:
    unit = Unit.model_validate(unit_in)
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit


@router.put("/units/{unit_id}", response_model=UnitPublic)
def update_unit(
    session: SessionDep,
    _admin: TeacherUserDep,
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
    session: SessionDep, _admin: TeacherUserDep, unit_id: uuid.UUID
) -> dict[str, str]:
    unit = session.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")
    session.delete(unit)  # 篇目 unit_id 置空（SET NULL）
    session.commit()
    return {"message": "deleted"}


class ClassroomUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    grade: str | None = Field(default=None, max_length=64)
    teaching_goal: str | None = Field(default=None, max_length=255)
    unlock_all: bool | None = None
    owner_id: uuid.UUID | None = None
    is_active: bool | None = None


@router.get("/topics", response_model=list[str])
def list_topics(session: SessionDep, _admin: TeacherUserDep) -> Any:
    """已有主题词表（篇目/单元/情景的 topic 并集）：录入时从列表选，不再自由输入。"""
    topics: set[str] = set()
    for column in (Passage.topic, Unit.topic, Scenario.topic):
        topics.update(t for t in session.exec(select(column)).all() if t)
    return sorted(topics)


# ── 课堂码 ───────────────────────────────────────────────────────────


@router.get("/classrooms", response_model=list[ClassroomPublic])
def list_classrooms(session: SessionDep, _admin: SuperUserDep) -> Any:
    return session.exec(select(Classroom).order_by(col(Classroom.created_at))).all()


@router.delete("/classrooms/{classroom_id}")
def deactivate_classroom(
    session: SessionDep, _admin: SuperUserDep, classroom_id: uuid.UUID
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
    _admin: SuperUserDep,
    classroom_id: uuid.UUID,
    classroom_in: ClassroomUpdate,
) -> Any:
    """更新课堂设置：unlock_all（一键解锁）、owner_id（绑定授权教师）、启停。"""
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
        if not owner.is_superuser and owner.role != "teacher":
            raise HTTPException(status_code=422, detail="被绑定账号不是教师角色")
    classroom.sqlmodel_update(update)
    session.add(classroom)
    session.commit()
    session.refresh(classroom)
    return classroom


# ── 情景编辑与 AI 出题 ────────────────────────────────────────────────


class ScenarioUpdate(SQLModel):
    topic: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None

    _topic_nonempty = field_validator("topic")(_strip_nonempty)


@router.put("/scenarios/{scenario_id}")
def update_scenario(
    session: SessionDep,
    _admin: TeacherUserDep,
    scenario_id: uuid.UUID,
    scenario_in: ScenarioUpdate,
) -> Any:
    """编辑情景（改名/启停）。"""
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    update = scenario_in.model_dump(exclude_unset=True)
    # 主题非空且不允许显式清空
    _reject_null_non_nullable(update, {"topic"})
    if "topic" in update:
        duplicate = session.exec(
            select(Scenario).where(Scenario.topic == update["topic"])
        ).first()
        if duplicate is not None and duplicate.id != scenario_id:
            raise HTTPException(status_code=409, detail="主题已存在")
    scenario.sqlmodel_update(update)
    session.add(scenario)
    session.commit()
    session.refresh(scenario)
    return scenario


class GenerateRequest(SQLModel):
    band: str = "B1"
    count: int = Field(default=3, ge=1, le=10)
    # AI 出题提示限长：数 MB 文本会放大 LLM 费用并长时间占用线程
    hint: str | None = Field(default=None, max_length=500)


class DraftQuestionOut(SQLModel):
    text: str
    suggested_seconds: int


@router.post(
    "/scenarios/{scenario_id}/questions/generate", response_model=list[DraftQuestionOut]
)
def generate_questions(
    session: SessionDep,
    _admin: TeacherUserDep,
    scenario_id: uuid.UUID,
    body: GenerateRequest,
) -> Any:
    """AI 按主题/档位起草问法（不入库，老师审改后走创建接口）。

    PRD 红线：模型只起草，不直接服务学生。
    """
    from app.scoring.question_gen import generate_draft_questions

    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if body.band not in VALID_BANDS:
        raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
    try:
        drafts = generate_draft_questions(
            topic=scenario.topic, band=body.band, count=body.count, hint=body.hint
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 无密钥/调用失败 → 503
        raise HTTPException(status_code=503, detail=f"AI 生成暂不可用：{exc}") from exc
    return [
        DraftQuestionOut(text=d.text, suggested_seconds=d.suggested_seconds)
        for d in drafts
    ]


class AutoSplitResult(SQLModel):
    created: int


@router.post(
    "/passages/{passage_id}/sentences/auto-split", response_model=AutoSplitResult
)
def auto_split_sentences(
    session: SessionDep,
    _admin: TeacherUserDep,
    passage_id: uuid.UUID,
    target_count: int = 3,
) -> Any:
    """从篇目正文自动拆分复述句（本地算法非 AI）：按句切、由短到长取 3 句。

    幂等：已有人工维护的句子时拒绝（避免覆盖老师内容）。
    """
    import re as _re

    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    existing = session.exec(
        select(RepeatSentence).where(RepeatSentence.passage_id == passage_id)
    ).all()
    if existing:
        raise HTTPException(status_code=409, detail="已有复述句，请先清空再自动拆分")

    sentences = [s.strip() for s in _re.split(r"[.!?]+\s*", passage.text) if s.strip()]
    if len(sentences) < target_count:
        raise HTTPException(
            status_code=422, detail=f"正文句子不足 {target_count} 句，无法拆分"
        )
    # 由短到长取 target_count 句，再按原文顺序输出（保持叙述顺序）
    picked = sorted(range(len(sentences)), key=lambda i: len(sentences[i].split()))[
        :target_count
    ]
    picked.sort()

    created = []
    for order, idx in enumerate(picked):
        text = sentences[idx]
        words = len(text.split())
        seconds = max(4, min(30, round(words / 2.5) + 2))
        sentence = RepeatSentence(
            passage_id=passage_id,
            order_index=order,
            text=text,
            suggested_seconds=seconds,
        )
        session.add(sentence)
        created.append(sentence)
    session.commit()
    for sentence_ in created:
        session.refresh(sentence_)
    return AutoSplitResult(created=len(created))


def _split_reading_sentences(text: str) -> list[str]:
    """按正文顺序拆句，保留句末标点（算法真源在 services/reading.py）。"""
    return reading.split_reading_sentences(text)


class PassageSplitResult(SQLModel):
    created: int
    passage_ids: list[uuid.UUID] = []
    original_deactivated: bool = False


@router.post("/passages/{passage_id}/split", response_model=PassageSplitResult)
def split_passage_into_readings(
    session: SessionDep,
    _admin: TeacherUserDep,
    passage_id: uuid.UUID,
    mode: Literal["paragraph", "sentence"] = "sentence",
) -> Any:
    """启用逐句拆分：发布/练习时该文章按句展开成多道朗读题（见 services/reading.py）。"""
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")

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
    session: SessionDep, _admin: TeacherUserDep, passage_id: uuid.UUID
) -> Any:
    """取消拆分：此后发布/练习回到整篇一道题；已发布快照不可变不受影响。"""
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    if passage.parent_passage_id is not None:
        raise HTTPException(status_code=422, detail="请在原文章下取消拆分")
    if passage.reading_split:
        passage.reading_split = False
        session.add(passage)
        session.commit()
    session.refresh(passage)
    return passage


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


@router.put("/questions/{question_id}", response_model=ScenarioQuestionPublic)
def update_question(
    session: SessionDep,
    _admin: TeacherUserDep,
    question_id: uuid.UUID,
    question_in: QuestionUpdate,
) -> Any:
    question = session.get(ScenarioQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    update = question_in.model_dump(exclude_unset=True)
    # 非空字段不允许显式清空（band/text/order_index/suggested_seconds 传 null → 422）
    _reject_null_non_nullable(
        update, {"band", "text", "order_index", "suggested_seconds"}
    )
    if "band" in update and update["band"] not in VALID_BANDS:
        raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
    # 部分更新：先与原记录合并出完整状态，再校验（仅改话题卡/仅清题型等
    # 单字段请求不能因「另一个字段缺失」被误拒，也不能留下不一致数据）
    merged_kind = update.get("exam_kind", question.exam_kind)
    merged_level = update.get("exam_level", question.exam_level)
    merged_bullets = update.get("cue_card_bullets", question.cue_card_bullets)
    merged_prep = update.get("prep_seconds", question.prep_seconds)
    if "exam_kind" in update and update["exam_kind"] is None:
        # 显式清空题型 → 级联清空关联字段；作答秒数超出普通口径则收敛到 60
        merged_level = None
        merged_bullets = None
        merged_prep = None
        merged_seconds = update.get("suggested_seconds", question.suggested_seconds)
        if merged_seconds is not None and merged_seconds > 60:
            update["suggested_seconds"] = 60
    validate_exam_fields(
        "question", merged_kind, merged_level, merged_bullets, merged_prep
    )
    merged_seconds = update.get("suggested_seconds", question.suggested_seconds)
    validate_question_suggested_seconds(
        merged_seconds if merged_seconds is not None else 20, merged_kind
    )
    if "exam_kind" in update and update["exam_kind"] is None:
        update["exam_level"] = None
        update["cue_card_bullets"] = None
        update["prep_seconds"] = None
    question.sqlmodel_update(update)
    session.add(question)
    session.commit()
    session.refresh(question)
    return question


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


@router.get("/sentence-frames", response_model=SentenceFramesListOut)
def list_sentence_frames(
    session: SessionDep,
    _admin: TeacherUserDep,
    level: str | None = Query(default=None, description="五级筛选"),
    purpose: str | None = Query(default=None, description="表达用途筛选"),
    exam_kind: str | None = Query(default=None, description="题型筛选"),
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=500),
) -> Any:
    conditions = []
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
        .order_by(col(SentenceFrame.purpose), col(SentenceFrame.text_en), col(SentenceFrame.id))
        .offset(skip)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return SentenceFramesListOut(
        data=session.exec(stmt).all(),
        count=count,
    )


@router.post("/sentence-frames", response_model=SentenceFramePublic)
def create_sentence_frame(
    session: SessionDep,
    _admin: TeacherUserDep,
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
    _admin: TeacherUserDep,
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
    _admin: TeacherUserDep,
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
    session: SessionDep, _admin: TeacherUserDep, frame_id: uuid.UUID
) -> dict[str, str]:
    frame = session.get(SentenceFrame, frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="Sentence frame not found")
    session.delete(frame)
    session.commit()
    return {"message": "deleted"}
