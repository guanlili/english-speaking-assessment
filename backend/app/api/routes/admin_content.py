"""管理员内容管理接口（PRD：内容槽由校方录入，软件只留槽位）。

全部需要超级管理员权限。EIP 文本只进数据库，不进 git。

    /admin/passages            篇目 CRUD（含复述句子路由）
    /admin/scenarios           情景 + 分档问法 CRUD
    /admin/wordlist            词表统计 / CSV 导入（学校分级词表）
    /admin/classrooms          课堂码列表 / 停用
"""

import csv
import io
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlmodel import Field, Session, SQLModel, col, select

from app import crud
from app.api.deps import SessionDep, SuperUserDep, TeacherUserDep
from app.core.config import settings
from app.core.storage import content_audio_url, save_content_audio
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Classroom,
    ClassroomPublic,
    Passage,
    PassageCreate,
    PassagePublic,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    ScenarioQuestionPublic,
    Unit,
    UnitCreate,
    UnitPublic,
    UnitUpdate,
    WordlistEntry,
)

router = APIRouter(prefix="/admin", tags=["admin"])

VALID_BANDS = {"A2", "B1", "B2"}


# ── 篇目与复述句 ─────────────────────────────────────────────────────


class PassageWithSentences(PassagePublic):
    sentences: list[RepeatSentence] = []


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


@router.get("/passages", response_model=list[PassageWithSentences])
def list_passages(session: SessionDep, _admin: TeacherUserDep) -> Any:
    passages = session.exec(select(Passage).order_by(col(Passage.created_at))).all()
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
    result = []
    for passage in passages:
        item = PassageWithSentences.model_validate(passage)
        item.sentences = sentences_by_passage.get(passage.id, [])
        result.append(item)
    return result


@router.post("/passages", response_model=PassagePublic)
def create_passage(
    session: SessionDep, _admin: TeacherUserDep, passage_in: PassageCreate
) -> Any:
    _require_valid_band(passage_in.cefr_band)
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
    passage_in: PassageCreate,
) -> Any:
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    _require_valid_band(passage_in.cefr_band)
    update = passage_in.model_dump(exclude={"slug"}, exclude_unset=True)
    passage.sqlmodel_update(update)
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
    _reject_delete_items_queued(
        session,
        [(passage_id, AttemptItemType.PASSAGE)]
        + [(sid, AttemptItemType.REPEAT) for sid in sentence_ids],
    )
    session.delete(passage)  # 复述句/作答按外键级联
    session.commit()
    return {"message": "deleted"}


@router.post("/passages/{passage_id}/sentences", response_model=RepeatSentence)
def create_sentence(
    session: SessionDep,
    _admin: TeacherUserDep,
    passage_id: uuid.UUID,
    sentence: RepeatSentence,
) -> Any:
    if session.get(Passage, passage_id) is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    # 表模型不走字段校验，可重听次数在此显式把关（0=不限，1–9）
    if not 0 <= sentence.replay_limit <= 9:
        raise HTTPException(status_code=422, detail="可重听次数需在 0–9 之间（0=不限）")
    sentence.passage_id = passage_id
    session.add(sentence)
    session.commit()
    session.refresh(sentence)
    return sentence


class SentenceWithPassage(RepeatSentence):
    """平铺复述句库视图：带所属篇目标题（独立句为 null）。"""

    passage_title: str | None = None


@router.get("/sentences", response_model=list[SentenceWithPassage])
def list_sentences_flat(session: SessionDep, _admin: TeacherUserDep) -> Any:
    """复述句独立题库：全部复述句平铺（含挂篇目的），按创建顺序。"""
    sentences = session.exec(
        select(RepeatSentence).order_by(col(RepeatSentence.created_at))
    ).all()
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
    sentence: RepeatSentence,
) -> Any:
    """独立创建复述句（不挂篇目）：题目库三题型互相独立后的复述题入口。

    传 passage_id 仍可挂到篇目（自主练习轮会随篇目出现）。
    """
    if not 0 <= sentence.replay_limit <= 9:
        raise HTTPException(status_code=422, detail="可重听次数需在 0–9 之间（0=不限）")
    if (
        sentence.passage_id is not None
        and session.get(Passage, sentence.passage_id) is None
    ):
        raise HTTPException(status_code=404, detail="Passage not found")
    session.add(sentence)
    session.commit()
    session.refresh(sentence)
    return sentence


@router.put("/sentences/{sentence_id}", response_model=RepeatSentence)
def update_sentence(
    session: SessionDep,
    _admin: TeacherUserDep,
    sentence_id: uuid.UUID,
    sentence_in: RepeatSentence,
) -> Any:
    sentence = session.get(RepeatSentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    update = sentence_in.model_dump(exclude={"id", "passage_id"}, exclude_unset=True)
    if "replay_limit" in update and not 0 <= update["replay_limit"] <= 9:
        raise HTTPException(status_code=422, detail="可重听次数需在 0–9 之间（0=不限）")
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


# ── 情景与问法 ───────────────────────────────────────────────────────


class ScenarioOut(SQLModel):
    """list_scenarios 的响应形状：情景 + 其问法列表。"""

    id: uuid.UUID
    topic: str
    is_active: bool
    questions: list[ScenarioQuestionPublic]


@router.get("/scenarios", response_model=list[ScenarioOut])
def list_scenarios(session: SessionDep, _admin: TeacherUserDep) -> Any:
    scenarios = session.exec(select(Scenario)).all()
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
    return result


@router.post("/scenarios")
def create_scenario(
    session: SessionDep, _admin: TeacherUserDep, scenario: Scenario
) -> Any:
    duplicate = session.exec(
        select(Scenario).where(Scenario.topic == scenario.topic)
    ).first()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="主题已存在")
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
    question_in: ScenarioQuestion,
) -> Any:
    if session.get(Scenario, scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if question_in.band not in VALID_BANDS:
        raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
    question_in.scenario_id = scenario_id
    session.add(question_in)
    session.commit()
    session.refresh(question_in)
    return question_in


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


@router.get("/questions", response_model=list[QuestionBankOut])
def list_question_bank(
    session: SessionDep,
    _admin: TeacherUserDep,
    topic: str | None = Query(default=None, description="按主题精确过滤"),
    band: str | None = Query(default=None, description="A2/B1/B2"),
    q: str | None = Query(default=None, description="题目/中文提示关键词"),
) -> Any:
    stmt = (
        select(ScenarioQuestion, Scenario.topic)
        .join(Scenario, ScenarioQuestion.scenario_id == Scenario.id)  # ty: ignore[invalid-argument-type]
        .order_by(
            col(Scenario.topic),
            col(ScenarioQuestion.band),
            col(ScenarioQuestion.order_index),
        )
    )
    if topic is not None:
        stmt = stmt.where(Scenario.topic == topic)
    if band is not None:
        if band not in VALID_BANDS:
            raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
        stmt = stmt.where(ScenarioQuestion.band == band)
    if q and q.strip():
        needle = q.strip()
        stmt = stmt.where(
            col(ScenarioQuestion.text).icontains(needle)
            | col(ScenarioQuestion.translation).icontains(needle)  # type: ignore[operator]
        )
    rows = session.exec(stmt).all()
    return [
        QuestionBankOut(
            id=question.id,
            scenario_id=question.scenario_id,
            topic=topic_name,
            band=question.band,
            order_index=question.order_index,
            text=question.text,
            translation=question.translation,
            suggested_seconds=question.suggested_seconds,
        )
        for question, topic_name in rows
    ]


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
                ScenarioQuestion.band == body.band,
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


# ── 词表 ─────────────────────────────────────────────────────────────


class WordlistStats(SQLModel):
    total: int
    by_band: dict[str, int]
    name: str | None = None


@router.get("/wordlist", response_model=WordlistStats)
def wordlist_stats(session: SessionDep, _admin: TeacherUserDep) -> Any:
    entries = session.exec(select(WordlistEntry)).all()
    by_band: dict[str, int] = dict.fromkeys(sorted(VALID_BANDS), 0)
    for entry in entries:
        by_band[entry.band] = by_band.get(entry.band, 0) + 1
    return {
        "total": len(entries),
        "by_band": by_band,
        "name": "内置演示词表（待学校分级词表 CSV 替换）" if entries else None,
    }


class WordlistImportResult(SQLModel):
    imported: int
    invalid_rows: list[int] = []


@router.post("/wordlist/import", response_model=WordlistImportResult)
async def import_wordlist_csv(
    session: SessionDep,
    _admin: TeacherUserDep,
    file: UploadFile,
) -> Any:
    """导入学校分级词表 CSV（表头 lemma,band；整体替换内置词表）。"""
    max_bytes = settings.MAX_WORDLIST_CSV_MB * 1024 * 1024
    raw = b""
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        raw += chunk
        if len(raw) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"CSV 超过 {settings.MAX_WORDLIST_CSV_MB}MB 上限",
            )
    try:
        text = raw.decode("utf-8-sig")  # 兼容 Excel 导出的 BOM
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV 必须是 UTF-8 编码") from exc

    reader = csv.DictReader(io.StringIO(text))
    if (
        not reader.fieldnames
        or "lemma" not in reader.fieldnames
        or "band" not in reader.fieldnames
    ):
        raise HTTPException(
            status_code=422, detail="CSV 需要表头：lemma,band（第一行）"
        )

    seen: set[str] = set()
    staged: list[WordlistEntry] = []
    invalid_rows: list[int] = []
    for lineno, row in enumerate(reader, start=2):
        lemma = (row.get("lemma") or "").strip().lower()
        band = (row.get("band") or "").strip().upper()
        if not lemma or band not in VALID_BANDS:
            invalid_rows.append(lineno)
            continue
        if lemma in seen:
            continue
        seen.add(lemma)
        staged.append(WordlistEntry(lemma=lemma, band=band))

    if not staged:
        raise HTTPException(
            status_code=422,
            detail=f"没有有效行（示例：friendly,B1）。无效行号：{invalid_rows[:10]}",
        )

    # 整体替换（学校词表是权威来源）。单事务内先删后插：
    # flush 让 DELETE 先执行（避开 lemma 唯一索引），中途失败整体回滚，不会清空词表
    for entry in session.exec(select(WordlistEntry)).all():
        session.delete(entry)
    session.flush()
    for entry in staged:
        session.add(entry)
    session.commit()

    return WordlistImportResult(imported=len(staged), invalid_rows=invalid_rows[:20])


# ── 学习单元（关卡）─────────────────────────────────────────────────


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
    unit.sqlmodel_update(unit_in.model_dump(exclude_unset=True))
    session.add(unit)
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
        # 校验被绑定教师真实存在
        from app.models import User as _User

        if session.get(_User, update["owner_id"]) is None:
            raise HTTPException(status_code=422, detail="教师账号不存在")
    classroom.sqlmodel_update(update)
    session.add(classroom)
    session.commit()
    session.refresh(classroom)
    return classroom


# ── 情景编辑与 AI 出题 ────────────────────────────────────────────────


class ScenarioUpdate(SQLModel):
    topic: str | None = None
    is_active: bool | None = None


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
    hint: str | None = None


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


_CN_NUMS = "一二三四五六七八九十"


def _reading_seconds(words: int) -> int:
    """朗读建议秒数：学生慢速朗读约 0.9 秒/词，5 秒取整，夹在 15–180。"""
    import math

    return max(15, min(180, math.ceil(words * 0.9 / 5) * 5))


def _split_reading_segments(text: str, max_words: int = 90) -> list[str]:
    """长文拆段：优先按段落切；超长段再按句聚合成不超过 max_words 词的段。"""
    import re as _re

    paragraphs = [p.strip() for p in _re.split(r"\n+", text) if p.strip()]
    segments: list[str] = []
    for para in paragraphs:
        if len(para.split()) <= max_words:
            segments.append(para)
            continue
        sentences = _re.split(r"(?<=[.!?])\s+", para)
        buf: list[str] = []
        buf_words = 0
        for s in sentences:
            w = len(s.split())
            if buf and buf_words + w > max_words:
                segments.append(" ".join(buf))
                buf, buf_words = [], 0
            buf.append(s)
            buf_words += w
        if buf:
            segments.append(" ".join(buf))
    return segments


class PassageSplitResult(SQLModel):
    created: int
    passage_ids: list[uuid.UUID] = []
    original_deactivated: bool = True


@router.post("/passages/{passage_id}/split", response_model=PassageSplitResult)
def split_passage_into_readings(
    session: SessionDep,
    _admin: TeacherUserDep,
    passage_id: uuid.UUID,
) -> Any:
    """把长文一键拆成多篇朗读材料（参考复述句自动拆分；本地算法非 AI）。

    按段落切分，超长段再按句聚合；新篇目沿用原标题/主题/难度/分组，
    标题追加（一）（二）…；原长文自动停用（历史与挂靠复述句保留，可再启用）。
    """
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")

    segments = _split_reading_segments(passage.text or "")
    if len(segments) < 2:
        raise HTTPException(
            status_code=422, detail="正文只有一个段落，无需拆分；请先用换行分段"
        )

    base_title = _re_split_title(passage.title or "Reading")
    created: list[Passage] = []
    for index, segment in enumerate(segments):
        num = _CN_NUMS[index] if index < 10 else str(index + 1)
        words = len(segment.split())
        new_passage = crud.create_passage(
            session=session,
            passage_in=PassageCreate(
                title=f"{base_title}（{num}）",
                topic=passage.topic,
                cefr_band=passage.cefr_band,
                text=segment,
                suggested_seconds=_reading_seconds(words),
                is_active=True,
                unit_id=passage.unit_id,
            ),
        )
        created.append(new_passage)

    passage.is_active = False
    session.add(passage)
    session.commit()
    for p in created:
        session.refresh(p)
    return PassageSplitResult(
        created=len(created),
        passage_ids=[p.id for p in created],
    )


def _re_split_title(title: str) -> str:
    """去掉标题上已有的（一）（二）类后缀，避免重复拆分时叠加。"""
    import re as _re

    return _re.sub(r"（[一二三四五六七八九十\d]+）$", "", title).strip() or title


# ── 内容标准音 ───────────────────────────────────────────────────────


class TtsRequest(SQLModel):
    text: str
    voice: str | None = None


class AudioUrlResult(SQLModel):
    audio_url: str


@router.post("/audio/tts", response_model=AudioUrlResult)
def generate_standard_audio(_admin: TeacherUserDep, body: TtsRequest) -> Any:
    """用语音合成生成标准音并落盘，返回可回放的相对 URL。"""
    from app.scoring.tts import TtsError, build_tts_provider

    try:
        audio = build_tts_provider().synthesize(body.text)
    except TtsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    path = save_content_audio(audio, ".mp3")
    return AudioUrlResult(audio_url=content_audio_url(path.name))


class QuestionUpdate(SQLModel):
    band: str | None = None
    text: str | None = None
    translation: str | None = None
    audio_url: str | None = None
    suggested_seconds: int | None = None
    order_index: int | None = None


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
    if "band" in update and update["band"] not in VALID_BANDS:
        raise HTTPException(status_code=422, detail="band 必须是 A2/B1/B2")
    if "suggested_seconds" in update and not 10 <= update["suggested_seconds"] <= 60:
        raise HTTPException(status_code=422, detail="建议秒数需在 10–60 之间")
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
    data = b""
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        data += chunk
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"音频超过 {settings.MAX_AUDIO_MB}MB 上限"
            )
    if not data:
        raise HTTPException(status_code=422, detail="音频为空")
    path = save_content_audio(data, suffix)
    return AudioUrlResult(audio_url=content_audio_url(path.name))
