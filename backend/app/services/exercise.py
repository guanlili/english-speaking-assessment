"""课堂练习快照域逻辑：发布/归档/快照构建/按题解析。

从 routes/classes.py 抽出（2026-09-29 收敛）：路由层只做参数与权限，
快照的版本递增、题目内容深拷贝、并发发布锁都在这里。
"""

import uuid
from typing import Any

from fastapi import HTTPException
from sqlmodel import col, select

from app.models import (
    AssignmentItemIn,
    AttemptItemType,
    Classroom,
    ClassroomExercise,
    Instruction,
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    get_datetime_utc,
)


def validate_assignment_items(
    session: Any, items: list[AssignmentItemIn], tenant_id: uuid.UUID
) -> None:
    """按题指派引用校验：题型合法且对象存在（朗读要求启用）。

    多租户：批量查询一律限定本校（tenant_id 过滤）——跨校题目按不存在
    处理（404），他校内容不得被指派进本校作业（C5 应用层防线，无 RLS
    环境同等生效）。

    按题型分组的 in_() 批量查询替代逐题 session.get（指派上限 100 题，
    该函数在发布热路径上）。校验过的行进 session 身份映射，调用方随后
    的 session.get 不再发查询。
    """
    _check_item_shapes(items)
    passages_by_id = _load_passages(session, items, tenant_id)
    sentences_by_id = _load_repeat_sentences(session, items, tenant_id)
    questions_by_id, scenarios_by_id = _load_questions(session, items, tenant_id)
    instructions_by_id = _load_instructions(session, items, tenant_id)
    _assert_items_resolvable(
        items,
        passages_by_id,
        sentences_by_id,
        questions_by_id,
        scenarios_by_id,
        instructions_by_id,
    )


def _check_item_shapes(items: list[AssignmentItemIn]) -> None:
    """数量上限、至少一道可作答题、题型合法、清单内无重复。"""
    if len(items) > 100:
        raise HTTPException(status_code=422, detail="一次发布最多包含 100 道题")
    if items and all(item.type == AttemptItemType.INSTRUCTION for item in items):
        raise HTTPException(status_code=422, detail="练习至少需要一道可作答的题目")
    seen: set[tuple[str, uuid.UUID]] = set()
    for item in items:
        if item.type not in {"passage", "repeat", "question", "instruction"}:
            raise HTTPException(status_code=422, detail=f"未知题型：{item.type}")
        if (item.type, item.id) in seen:
            raise HTTPException(status_code=422, detail="指派清单内有重复题目")
        seen.add((item.type, item.id))


def _load_passages(
    session: Any, items: list[AssignmentItemIn], tenant_id: uuid.UUID
) -> dict[uuid.UUID, Passage]:
    ids = [i.id for i in items if i.type == "passage"]
    if not ids:
        return {}
    return {
        obj.id: obj
        for obj in session.exec(
            select(Passage).where(
                col(Passage.id).in_(ids),
                col(Passage.tenant_id) == tenant_id,
            )
        ).all()
    }


def _load_repeat_sentences(
    session: Any, items: list[AssignmentItemIn], tenant_id: uuid.UUID
) -> dict[uuid.UUID, RepeatSentence]:
    ids = [i.id for i in items if i.type == "repeat"]
    if not ids:
        return {}
    return {
        obj.id: obj
        for obj in session.exec(
            select(RepeatSentence).where(
                col(RepeatSentence.id).in_(ids),
                col(RepeatSentence.tenant_id) == tenant_id,
            )
        ).all()
    }


def _load_questions(
    session: Any, items: list[AssignmentItemIn], tenant_id: uuid.UUID
) -> tuple[dict[uuid.UUID, ScenarioQuestion], dict[uuid.UUID, Scenario]]:
    ids = [i.id for i in items if i.type == "question"]
    questions_by_id: dict[uuid.UUID, ScenarioQuestion] = {}
    if ids:
        for obj in session.exec(
            select(ScenarioQuestion).where(
                col(ScenarioQuestion.id).in_(ids),
                col(ScenarioQuestion.tenant_id) == tenant_id,
            )
        ).all():
            questions_by_id[obj.id] = obj
    scenarios_by_id: dict[uuid.UUID, Scenario] = {}
    scenario_ids = {q.scenario_id for q in questions_by_id.values()}
    if scenario_ids:
        for obj2 in session.exec(
            select(Scenario).where(
                col(Scenario.id).in_(scenario_ids),
                col(Scenario.tenant_id) == tenant_id,
            )
        ).all():
            scenarios_by_id[obj2.id] = obj2
    return questions_by_id, scenarios_by_id


def _load_instructions(
    session: Any, items: list[AssignmentItemIn], tenant_id: uuid.UUID
) -> dict[uuid.UUID, Instruction]:
    ids = [i.id for i in items if i.type == AttemptItemType.INSTRUCTION]
    if not ids:
        return {}
    return {
        obj.id: obj
        for obj in session.exec(
            select(Instruction).where(
                col(Instruction.id).in_(ids),
                col(Instruction.tenant_id) == tenant_id,
            )
        ).all()
    }


def _assert_items_resolvable(
    items: list[AssignmentItemIn],
    passages_by_id: dict[uuid.UUID, Passage],
    sentences_by_id: dict[uuid.UUID, RepeatSentence],
    questions_by_id: dict[uuid.UUID, ScenarioQuestion],
    scenarios_by_id: dict[uuid.UUID, Scenario],
    instructions_by_id: dict[uuid.UUID, Instruction],
) -> None:
    """逐项检查引用对象存在且可用，缺失按题型给出 404/422。"""
    for item in items:
        if item.type == "passage":
            obj = passages_by_id.get(item.id)
            if obj is None or not obj.is_active:
                raise HTTPException(status_code=404, detail="朗读篇目不存在或已停用")
            if obj.parent_passage_id is not None:
                raise HTTPException(status_code=404, detail="朗读篇目不存在或已停用")
        elif item.type == "repeat":
            if sentences_by_id.get(item.id) is None:
                raise HTTPException(status_code=404, detail="复述句不存在")
        elif item.type == AttemptItemType.INSTRUCTION:
            if instructions_by_id.get(item.id) is None:
                raise HTTPException(status_code=404, detail="题目说明不存在")
        else:
            question = questions_by_id.get(item.id)
            if question is None:
                raise HTTPException(status_code=404, detail="问答题不存在")
            scenario = scenarios_by_id.get(question.scenario_id)
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
    # 按题型分组的 id 集合：三次 in_() 批量查询替代逐题 session.get
    # （该函数在 /today、/board、/next-question 学生端热路径上，指派上限 100 题）
    ids_by_type = _group_assigned_ids(classroom)
    passages_by_id = _assigned_passages(
        session, ids_by_type["passage"], classroom.tenant_id
    )
    sentences_by_id = _assigned_sentences(
        session, ids_by_type["repeat"], classroom.tenant_id
    )
    questions_by_id = _assigned_questions(
        session, ids_by_type["question"], classroom.tenant_id
    )
    return _collect_assigned(
        classroom, passages_by_id, sentences_by_id, questions_by_id
    )


def _group_assigned_ids(classroom: Classroom) -> dict[str, set[str]]:
    ids_by_type: dict[str, set[str]] = {
        "passage": set(),
        "repeat": set(),
        "question": set(),
    }
    for spec in classroom.assigned_items or []:
        kind = spec.get("type")
        item_id = spec.get("id")
        if kind in ids_by_type and item_id:
            ids_by_type[kind].add(str(item_id))
    return ids_by_type


def _assigned_passages(
    session: Any, ids: set[str], tenant_id: uuid.UUID
) -> dict[str, Passage]:
    if not ids:
        return {}
    return {
        str(obj.id): obj
        for obj in session.exec(
            select(Passage).where(
                col(Passage.id).in_(list(ids)),
                col(Passage.tenant_id) == tenant_id,
            )
        ).all()
    }


def _assigned_sentences(
    session: Any, ids: set[str], tenant_id: uuid.UUID
) -> dict[str, RepeatSentence]:
    if not ids:
        return {}
    return {
        str(obj.id): obj
        for obj in session.exec(
            select(RepeatSentence).where(
                col(RepeatSentence.id).in_(list(ids)),
                col(RepeatSentence.tenant_id) == tenant_id,
            )
        ).all()
    }


def _assigned_questions(
    session: Any, ids: set[str], tenant_id: uuid.UUID
) -> dict[str, ScenarioQuestion]:
    if not ids:
        return {}
    return {
        str(obj.id): obj
        for obj in session.exec(
            select(ScenarioQuestion).where(
                col(ScenarioQuestion.id).in_(list(ids)),
                col(ScenarioQuestion.tenant_id) == tenant_id,
            )
        ).all()
    }


def _collect_assigned(
    classroom: Classroom,
    passages_by_id: dict[str, Passage],
    sentences_by_id: dict[str, RepeatSentence],
    questions_by_id: dict[str, ScenarioQuestion],
) -> tuple[list[Passage], list[RepeatSentence], list[ScenarioQuestion]]:
    passages: list[Passage] = []
    sentences: list[RepeatSentence] = []
    questions: list[ScenarioQuestion] = []
    for spec in classroom.assigned_items or []:
        kind, item_id = spec.get("type"), spec.get("id")
        if item_id is None:
            continue
        key = str(item_id)
        if kind == "passage":
            obj = passages_by_id.get(key)
            if obj is not None and obj.is_active:
                passages.append(obj)
        elif kind == "repeat":
            obj2 = sentences_by_id.get(key)
            if obj2 is not None:
                sentences.append(obj2)
        elif kind == "question":
            obj3 = questions_by_id.get(key)
            if obj3 is not None:
                questions.append(obj3)
    return passages, sentences, questions


def build_snapshot_item(
    session: Any, item_type: str, item_id: uuid.UUID, tenant_id: uuid.UUID
) -> dict[str, object]:
    """把题目当前内容复制进发布快照。题库后续编辑不影响已发布练习。

    多租户：快照来源必须是本校对象——跨校题目按不存在处理（404），
    防止他校内容经快照进入本校发布（C5 应用层防线）。
    """
    if item_type == AttemptItemType.PASSAGE:
        return _passage_snapshot(session, item_id, tenant_id)
    if item_type == AttemptItemType.REPEAT:
        return _repeat_snapshot(session, item_id, tenant_id)
    if item_type == AttemptItemType.INSTRUCTION:
        return _instruction_snapshot(session, item_id, tenant_id)
    return _question_snapshot(session, item_id, tenant_id)


def _passage_snapshot(
    session: Any, item_id: uuid.UUID, tenant_id: uuid.UUID
) -> dict[str, object]:
    item = session.get(Passage, item_id)
    if (
        item is None
        or not item.is_active
        or item.parent_passage_id is not None
        or item.tenant_id != tenant_id
    ):
        raise HTTPException(status_code=404, detail="朗读篇目不存在或已停用")
    return {
        "type": AttemptItemType.PASSAGE,
        "id": str(item.id),
        "text": item.text,
        "translation": item.translation,
        "audio_url": item.audio_url,
        "suggested_seconds": item.suggested_seconds,
        "title": item.title,
        "topic": item.topic,
    }


def _repeat_snapshot(
    session: Any, item_id: uuid.UUID, tenant_id: uuid.UUID
) -> dict[str, object]:
    item = session.get(RepeatSentence, item_id)
    if item is None or item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="复述句不存在")
    return {
        "type": AttemptItemType.REPEAT,
        "id": str(item.id),
        "text": item.text,
        "translation": item.translation,
        "audio_url": item.audio_url,
        "suggested_seconds": item.suggested_seconds,
        "replay_limit": item.replay_limit,
        # 分级题型训练（可空=普通课堂内容；快照不可变，透传题库行）
        "exam_kind": item.exam_kind,
        "exam_level": item.exam_level,
    }


def _instruction_snapshot(
    session: Any, item_id: uuid.UUID, tenant_id: uuid.UUID
) -> dict[str, object]:
    item = session.get(Instruction, item_id)
    if item is None or item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="题目说明不存在")
    return {
        "type": AttemptItemType.INSTRUCTION,
        "id": str(item.id),
        "text": item.text,
        "title": item.title,
        "suggested_seconds": item.suggested_seconds,
    }


def _question_snapshot(
    session: Any, item_id: uuid.UUID, tenant_id: uuid.UUID
) -> dict[str, object]:
    item = session.get(ScenarioQuestion, item_id)
    if item is None or item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="问答题不存在")
    return {
        "type": AttemptItemType.QUESTION,
        "id": str(item.id),
        "text": item.text,
        "translation": item.translation,
        "audio_url": item.audio_url,
        "suggested_seconds": item.suggested_seconds,
        "band": item.band,
        "scenario_id": str(item.scenario_id),
        # 分级题型训练（可空=普通情景问法；Part 2 话题卡要点/准备时间）
        "exam_kind": item.exam_kind,
        "exam_level": item.exam_level,
        "cue_card_bullets": item.cue_card_bullets,
        "prep_seconds": item.prep_seconds,
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
    automated_exam: bool = False,
    is_exam: bool = False,
    time_limit_minutes: int | None = None,
    assignment_items: list[dict[str, object]] | None = None,
    slot: str = "class",
) -> ClassroomExercise:
    exercise_title = _validate_publish_params(
        snapshots=snapshots,
        title=title,
        is_exam=is_exam,
        time_limit_minutes=time_limit_minutes,
        slot=slot,
    )
    if automated_exam and is_exam:
        snapshots = _apply_automated_exam_settings(session, snapshots)
    # 同一课堂并发发布时锁住课堂行，避免版本号重复或互相覆盖当前版本。
    session.exec(
        select(Classroom).where(Classroom.id == classroom.id).with_for_update()
    ).first()
    exercise = _create_exercise(
        session=session,
        classroom=classroom,
        created_by=created_by,
        snapshots=snapshots,
        exercise_title=exercise_title,
        is_exam=is_exam,
        time_limit_minutes=time_limit_minutes,
        slot=slot,
    )
    session.add(exercise)
    session.flush()
    if slot == "homework":
        archive_homework_exercise(session, classroom)
        classroom.homework_exercise_id = exercise.id
        session.add(classroom)
        return exercise
    archive_current_exercise(session, classroom)
    classroom.current_exercise_id = exercise.id
    # 指派镜像只存真实题目 ID：拆句展开只进快照（assigned_items 上的合成 ID
    # 会被旧兼容路径静默丢弃、指派页回显也无法解析）
    mirror_source = assignment_items if assignment_items is not None else snapshots
    classroom.assigned_items = [
        {"type": str(item["type"]), "id": str(item["id"])} for item in mirror_source
    ]
    session.add(classroom)
    return exercise


def _validate_publish_params(
    snapshots: list[dict[str, object]],
    title: str | None,
    is_exam: bool,
    time_limit_minutes: int | None,
    slot: str,
) -> str:
    """发布前置校验，返回归一化后的练习标题。"""
    if not snapshots:
        raise HTTPException(status_code=422, detail="练习至少需要包含一道题目")
    if len(snapshots) > 100:
        # 拆句展开在快照层发生，上限按展开后的题数把关
        raise HTTPException(
            status_code=422,
            detail=f"拆句展开后共 {len(snapshots)} 道题，超过单次发布上限 100 道；请减少篇目或缩短文章",
        )
    exercise_title = (title or "课堂练习").strip()
    if len(exercise_title) > 255:
        raise HTTPException(status_code=422, detail="练习名称不能超过 255 个字符")
    if is_exam:
        if time_limit_minutes is None:
            raise HTTPException(status_code=422, detail="模考必须设置整场限时（分钟）")
        if not (5 <= time_limit_minutes <= 240):
            raise HTTPException(status_code=422, detail="模考限时须在 5–240 分钟之间")
    if slot == "homework" and is_exam:
        raise HTTPException(status_code=422, detail="课后作业不能开启模考")
    return exercise_title


def _apply_automated_exam_settings(
    session: Any, snapshots: list[dict[str, object]]
) -> list[dict[str, object]]:
    """把题库行的 exam_settings 合进快照，并校验音频齐备。"""
    from app.models import ExamItemSettings

    models = {
        "passage": Passage,
        "repeat": RepeatSentence,
        "question": ScenarioQuestion,
        "instruction": Instruction,
    }
    snapshots = [dict(item) for item in snapshots]
    for item in snapshots:
        kind = str(item["type"])
        source_id = uuid.UUID(str(item.get("parent_id") or item["id"]))
        source = session.get(models[kind], source_id)
        settings = (
            ExamItemSettings.model_validate(source.exam_settings or {})
            if source is not None
            else ExamItemSettings()
        )
        if settings.prep_seconds is None:
            settings.prep_seconds = (
                int(str(item.get("prep_seconds") or 60))
                if item.get("exam_kind") == "ielts_p2"
                else 0
            )
        item["exam_flow"] = settings.model_dump()
        if settings.audio_url:
            item["audio_url"] = settings.audio_url
    missing_audio = [
        str(index + 1)
        for index, item in enumerate(snapshots)
        if item["type"] != "passage" and not str(item.get("audio_url") or "").strip()
    ]
    if missing_audio:
        raise HTTPException(
            status_code=422,
            detail="Automated exam audio missing: " + ", ".join(missing_audio),
        )
    return snapshots


def _create_exercise(
    session: Any,
    classroom: Classroom,
    created_by: uuid.UUID | None,
    snapshots: list[dict[str, object]],
    exercise_title: str,
    is_exam: bool,
    time_limit_minutes: int | None,
    slot: str,
) -> ClassroomExercise:
    """构造待插入的练习行（版本号在课堂行已锁定后取）。"""
    return ClassroomExercise(
        classroom_id=classroom.id,
        version_no=next_exercise_version(session, classroom.id),
        title=exercise_title or ("课后作业" if slot == "homework" else "课堂练习"),
        status="published",
        snapshot_items=snapshots,
        created_by=created_by,
        is_exam=is_exam,
        time_limit_minutes=time_limit_minutes if is_exam else None,
    )


def archive_homework_exercise(session: Any, classroom: Classroom) -> None:
    previous_id = classroom.homework_exercise_id
    if previous_id is None:
        return
    previous = session.get(ClassroomExercise, previous_id)
    if previous is not None and previous.status == "published":
        previous.status = "archived"
        previous.archived_at = get_datetime_utc()
        session.add(previous)
    classroom.homework_exercise_id = None


def archive_current_exercise(session: Any, classroom: Classroom) -> None:
    # 懒加载避免与 routes.classes 的循环导入（该日历函数真源在路由模块）

    previous_id = classroom.current_exercise_id
    if previous_id is None:
        return
    previous = session.get(ClassroomExercise, previous_id)
    if previous is not None and previous.status == "published":
        previous.status = "archived"
        previous.archived_at = get_datetime_utc()
        session.add(previous)
    classroom.current_exercise_id = None
    # 不清空任何历史会话的 assignment_id（不可变锚）：
    # - 旧会话始终绑发布时快照，发布历史回查靠它
    # - current_exercise_id = None 即入口切换信号，today/board 定位器会走
    #   assignment_id IS NULL 的自主练习会话（同日新开一轮）
    # - 并发唯一性由 ix_practice_session_by_assignment /
    #   自主轮 (student, date, mode) 部分唯一索引保证
