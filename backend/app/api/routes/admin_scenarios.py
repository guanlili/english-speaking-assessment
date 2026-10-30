"""管理端内容·情景域：情景/问法 CRUD、题库全局视图、批量录入、AI 出题。

从 admin_content 拆分（第二刀）；路由前缀/路径/权限零变化。
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import field_validator
from sqlalchemy import func
from sqlmodel import Field, SQLModel, col, select

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
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    ScenarioQuestionPublic,
    validate_exam_fields,
    validate_question_suggested_seconds,
)
from app.services import content_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


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


def next_question_order(session: Any, scenario_id: uuid.UUID) -> int:
    """同主题下一道题的排序号：现存最大 +1（删除中间题不影响单调性）。"""
    max_order = session.exec(
        select(func.max(ScenarioQuestion.order_index)).where(  # type: ignore[call-overload]
            ScenarioQuestion.scenario_id == scenario_id,
        )
    ).one()
    return (max_order or 0) + 1


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
    owner_id: uuid.UUID | None = None
    questions: list[ScenarioQuestionPublic]


@router.get("/scenarios", response_model=ScenariosListOut)
def list_scenarios(
    session: SessionDep,
    _admin: TeacherUserDep,
    q: str | None = Query(default=None, description="主题关键词过滤"),
    skip: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=500),
    ids: list[uuid.UUID] | None = Query(default=None),
) -> Any:
    """问答题库主题列表：分页 + 主题关键词（limit=None 全量，组卷选择器兼容）。"""
    conditions: list[Any] = []
    if ids is not None:
        conditions.append(col(Scenario.id).in_(ids))
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
        # ty 对 in_(列表推导) 的重载推断失真（同代码在 master 无此报错，
        # 疑与上文 stmt 分支赋值联动），行内标注压制
        for q in all_questions:  # ty: ignore[invalid-assignment]
            questions_by_scenario.setdefault(q.scenario_id, []).append(q)  # ty: ignore[unresolved-attribute, invalid-argument-type]
    result = []
    for scenario in scenarios:
        questions = questions_by_scenario.get(scenario.id, [])
        result.append(
            ScenarioOut(
                id=scenario.id,
                topic=scenario.topic,
                is_active=scenario.is_active,
                owner_id=scenario.owner_id,
                questions=[ScenarioQuestionPublic.model_validate(q) for q in questions],
            )
        )
    return ScenariosListOut(data=result, count=count)


@router.post("/scenarios")
def create_scenario(
    session: SessionDep, current_user: TeacherUserDep, scenario_in: ScenarioCreate
) -> Any:
    duplicate = session.exec(
        select(Scenario).where(Scenario.topic == scenario_in.topic)
    ).first()
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="主题已存在")
    scenario = Scenario.model_validate(scenario_in.model_dump())
    scenario.owner_id = content_access.owner_for(current_user)
    session.add(scenario)
    session.commit()
    session.refresh(scenario)
    return scenario


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(
    session: SessionDep, current_user: TeacherUserDep, scenario_id: uuid.UUID
) -> dict[str, str]:
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    content_access.require_scenario_delete(session, current_user, scenario)
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
    current_user: TeacherUserDep,
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
            "owner_id": content_access.owner_for(current_user),
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
    session: SessionDep, current_user: TeacherUserDep, question_id: uuid.UUID
) -> dict[str, str]:
    question = session.get(ScenarioQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    content_access.require_question(current_user, question)
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

    copied_from_id: uuid.UUID | None = None

    id: uuid.UUID
    scenario_id: uuid.UUID
    topic: str
    band: str
    order_index: int
    text: str
    translation: str | None = None
    audio_url: str | None = None
    suggested_seconds: int
    # 分级题型训练（可空=普通情景问法）
    exam_kind: str | None = None
    exam_level: str | None = None
    cue_card_bullets: list[str] | None = None
    prep_seconds: int | None = None
    owner_id: uuid.UUID | None = None


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
    conditions: list[Any] = []
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
                audio_url=question.audio_url,
                suggested_seconds=question.suggested_seconds,
                exam_kind=question.exam_kind,
                exam_level=question.exam_level,
                cue_card_bullets=question.cue_card_bullets,
                prep_seconds=question.prep_seconds,
                owner_id=question.owner_id,
                copied_from_id=question.copied_from_id,
            )
            for question, topic_name in rows
        ],
        count=count,
    )


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


class BatchQuestionItem(SQLModel):
    """批量录入的单条：空文本/秒数越界等校验放处理器里逐条做，
    不在模型层拦——否则一条非法会把整批 422 掉。"""

    text: str = ""
    translation: str | None = None
    suggested_seconds: int = 20


class BatchQuestionResult(SQLModel):
    created: int
    failed: list[BatchFailItem]


@router.post(
    "/scenarios/{scenario_id}/questions/batch",
    response_model=BatchQuestionResult,
)
def create_questions_batch(
    session: SessionDep,
    current_user: TeacherUserDep,
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
                owner_id=content_access.owner_for(current_user),
            )
        )
        created += 1
    if created:
        session.commit()
    return BatchQuestionResult(created=created, failed=failed)


class ClassroomUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    grade: str | None = Field(default=None, max_length=64)
    teaching_goal: str | None = Field(default=None, max_length=255)
    unlock_all: bool | None = None
    show_report_percentile: bool | None = None
    owner_id: uuid.UUID | None = None
    is_active: bool | None = None
    class_size: int | None = Field(default=None, ge=1, le=100)


# ── 情景编辑与 AI 出题 ────────────────────────────────────────────────


class ScenarioUpdate(SQLModel):
    topic: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None

    _topic_nonempty = field_validator("topic")(_strip_nonempty)


@router.put("/scenarios/{scenario_id}")
def update_scenario(
    session: SessionDep,
    current_user: TeacherUserDep,
    scenario_id: uuid.UUID,
    scenario_in: ScenarioUpdate,
) -> Any:
    """编辑情景（改名/启停）。"""
    scenario = session.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    content_access.require_scenario(session, current_user, scenario)
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
    except Exception:  # noqa: BLE001 - 无密钥/调用失败 → 503
        # 异常原文（上游响应片段/内部路径）只进日志；前端把 detail 映射成
        # 双语稳定文案（vocab_ai 路由同款范式，2026-10-12 评审）
        logger.warning(
            "AI question draft failed scenario=%s band=%s",
            scenario_id,
            body.band,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503, detail="AI 生成暂不可用，请稍后再试"
        ) from None
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
    current_user: TeacherUserDep,
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
    content_access.require_passage(session, current_user, passage)
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
            owner_id=content_access.passage_owner(session, passage),
        )
        session.add(sentence)
        created.append(sentence)
    session.commit()
    for sentence_ in created:
        session.refresh(sentence_)
    return AutoSplitResult(created=len(created))


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
    current_user: TeacherUserDep,
    question_id: uuid.UUID,
    question_in: QuestionUpdate,
) -> Any:
    question = session.get(ScenarioQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    content_access.require_question(current_user, question)
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
