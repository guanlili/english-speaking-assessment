"""课堂练习快照域逻辑：发布/归档/快照构建/按题解析。

从 routes/classes.py 抽出（2026-09-29 收敛）：路由层只做参数与权限，
快照的版本递增、题目内容深拷贝、并发发布锁都在这里。
"""

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, update
from sqlmodel import col, select

from app.models import (
    AssignmentItemIn,
    AttemptItemType,
    Classroom,
    ClassroomExercise,
    Passage,
    PracticeSession,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    get_datetime_utc,
)


def validate_assignment_items(session: Any, items: list[AssignmentItemIn]) -> None:
    """按题指派引用校验：题型合法且对象存在（朗读要求启用）。"""
    if len(items) > 100:
        raise HTTPException(status_code=422, detail="一次发布最多包含 100 道题")
    seen: set[tuple[str, uuid.UUID]] = set()
    for item in items:
        if item.type not in {"passage", "repeat", "question"}:
            raise HTTPException(status_code=422, detail=f"未知题型：{item.type}")
        if (item.type, item.id) in seen:
            raise HTTPException(status_code=422, detail="指派清单内有重复题目")
        seen.add((item.type, item.id))
        if item.type == "passage":
            obj = session.get(Passage, item.id)
            if obj is None or not obj.is_active:
                raise HTTPException(status_code=404, detail="朗读篇目不存在或已停用")
        elif item.type == "repeat":
            if session.get(RepeatSentence, item.id) is None:
                raise HTTPException(status_code=404, detail="复述句不存在")
        else:
            question = session.get(ScenarioQuestion, item.id)
            if question is None:
                raise HTTPException(status_code=404, detail="问答题不存在")
            scenario = session.get(Scenario, question.scenario_id)
            if scenario is None or not scenario.is_active:
                raise HTTPException(status_code=422, detail="问答题所属主题已停用")


def resolve_assigned_items(
    session: Any, classroom: Classroom
) -> tuple[list[Passage], list[RepeatSentence], list[ScenarioQuestion]] | None:
    """解析按题指派：返回（朗读篇目 / 复述句 / 问答题），对象缺失的自动跳过。

    无按题指派时返回 None（走单元指派路径）。
    """
    if not classroom.assigned_items:
        return None
    passages: list[Passage] = []
    sentences: list[RepeatSentence] = []
    questions: list[ScenarioQuestion] = []
    for spec in classroom.assigned_items:
        kind, item_id = spec.get("type"), spec.get("id")
        if kind == "passage":
            obj = session.get(Passage, uuid.UUID(item_id))
            if obj is not None and obj.is_active:
                passages.append(obj)
        elif kind == "repeat":
            obj = session.get(RepeatSentence, uuid.UUID(item_id))
            if obj is not None:
                sentences.append(obj)
        elif kind == "question":
            obj = session.get(ScenarioQuestion, uuid.UUID(item_id))
            if obj is not None:
                questions.append(obj)
    return passages, sentences, questions


def build_snapshot_item(
    session: Any, item_type: str, item_id: uuid.UUID
) -> dict[str, object]:
    """把题目当前内容复制进发布快照。题库后续编辑不影响已发布练习。"""
    if item_type == AttemptItemType.PASSAGE:
        item = session.get(Passage, item_id)
        if item is None or not item.is_active:
            raise HTTPException(status_code=404, detail="朗读篇目不存在或已停用")
        return {
            "type": item_type,
            "id": str(item.id),
            "text": item.text,
            "translation": item.translation,
            "audio_url": item.audio_url,
            "suggested_seconds": item.suggested_seconds,
            "title": item.title,
            "topic": item.topic,
        }
    if item_type == AttemptItemType.REPEAT:
        item = session.get(RepeatSentence, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="复述句不存在")
        return {
            "type": item_type,
            "id": str(item.id),
            "text": item.text,
            "translation": item.translation,
            "audio_url": item.audio_url,
            "suggested_seconds": item.suggested_seconds,
            "replay_limit": item.replay_limit,
        }
    item = session.get(ScenarioQuestion, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="问答题不存在")
    return {
        "type": item_type,
        "id": str(item.id),
        "text": item.text,
        "translation": item.translation,
        "audio_url": item.audio_url,
        "suggested_seconds": item.suggested_seconds,
        "band": item.band,
        "scenario_id": str(item.scenario_id),
    }


def next_exercise_version(session: Any, classroom_id: uuid.UUID) -> int:
    latest = session.exec(
        select(ClassroomExercise.version_no)
        .where(ClassroomExercise.classroom_id == classroom_id)
        .order_by(col(ClassroomExercise.version_no).desc())
    ).first()
    return (latest or 0) + 1


def publish_exercise(
    session: Any,
    classroom: Classroom,
    created_by: uuid.UUID | None,
    snapshots: list[dict[str, object]],
    title: str | None = None,
) -> ClassroomExercise:
    if not snapshots:
        raise HTTPException(status_code=422, detail="练习至少需要包含一道题目")
    exercise_title = (title or "课堂练习").strip()
    if len(exercise_title) > 255:
        raise HTTPException(status_code=422, detail="练习名称不能超过 255 个字符")
    # 同一课堂并发发布时锁住课堂行，避免版本号重复或互相覆盖当前版本。
    session.exec(
        select(Classroom).where(Classroom.id == classroom.id).with_for_update()
    ).first()
    exercise = ClassroomExercise(
        classroom_id=classroom.id,
        version_no=next_exercise_version(session, classroom.id),
        title=exercise_title or "课堂练习",
        status="published",
        snapshot_items=snapshots,
        created_by=created_by,
    )
    session.add(exercise)
    session.flush()
    archive_current_exercise(session, classroom)
    classroom.current_exercise_id = exercise.id
    classroom.assigned_items = [
        {"type": str(item["type"]), "id": str(item["id"])} for item in snapshots
    ]
    session.add(classroom)
    return exercise


def archive_current_exercise(session: Any, classroom: Classroom) -> None:
    # 懒加载避免与 routes.classes 的循环导入（该日历函数真源在路由模块）
    from app.api.routes.classes import _today_in_practice_tz

    previous_id = classroom.current_exercise_id
    if previous_id is None:
        return
    previous = session.get(ClassroomExercise, previous_id)
    if previous is not None and previous.status == "published":
        previous.status = "archived"
        previous.archived_at = get_datetime_utc()
        session.add(previous)
    classroom.current_exercise_id = None
    # 恢复自主练习时解绑当日已开始的会话：否则学生会一直读到旧快照，
    # "恢复自主"对当天开练的学生不生效。

    session.execute(
        update(PracticeSession)
        .where(
            and_(
                PracticeSession.classroom_id == classroom.id,  # ty: ignore[invalid-argument-type]
                PracticeSession.session_date == _today_in_practice_tz(),  # ty: ignore[invalid-argument-type]
                PracticeSession.mode == "daily",  # ty: ignore[invalid-argument-type]
                PracticeSession.assignment_id == previous_id,  # ty: ignore[invalid-argument-type]
            )
        )
        .values(assignment_id=None)
    )
