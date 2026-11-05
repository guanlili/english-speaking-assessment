"""课堂练习快照域：按题指派校验、指派解析、快照构建、发布前置校验。

这些分支的错误码是老师端"点发布却没反应"的直接原因（422/404 文案），
且跨校对象必须按不存在处理，所以逐条锁住。
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from fastapi import HTTPException
from sqlmodel import Session, col, delete

from app.core.tenant_context import tenant_scope
from app.models import (
    DEFAULT_TENANT_ID,
    AssignmentItemIn,
    AttemptItemType,
    Classroom,
    Instruction,
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    Tenant,
)
from app.services import exercise as exercise_service


@pytest.fixture
def other_tenant(db: Session) -> Any:
    """真实别校：passage/repeat 的 tenant_id 有外键，不能用凭空 uuid。"""
    row = Tenant(slug=f"ex-{_uid()}", name_zh="别校")
    db.add(row)
    db.commit()
    db.refresh(row)
    tid = row.id
    yield tid
    with Session(db.get_bind()) as cleanup:
        cleanup.exec(delete(Passage).where(col(Passage.tenant_id) == tid))
        cleanup.exec(delete(RepeatSentence).where(col(RepeatSentence.tenant_id) == tid))
        cleanup.exec(delete(Tenant).where(col(Tenant.id) == tid))
        cleanup.commit()


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
def passage(db: Session) -> Passage:
    row = Passage(title="朗读篇", text="hello world", slug=f"p-{_uid()}")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def sentence(db: Session) -> RepeatSentence:
    row = RepeatSentence(order_index=1, text="a short sentence")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def scenario(db: Session) -> Scenario:
    row = Scenario(topic=f"话题-{_uid()}")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def question(db: Session, scenario: Scenario) -> ScenarioQuestion:
    row = ScenarioQuestion(scenario_id=scenario.id, text="What do you think?")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def instruction(db: Session) -> Instruction:
    row = Instruction(text="请先听题再作答")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _item(kind: str, obj_id: uuid.UUID) -> AssignmentItemIn:
    return AssignmentItemIn(type=kind, id=obj_id)


def test_validate_rejects_more_than_100_items(db: Session) -> None:
    items = [_item(AttemptItemType.PASSAGE, uuid.uuid4()) for _ in range(101)]
    with pytest.raises(HTTPException) as exc:
        exercise_service.validate_assignment_items(db, items, DEFAULT_TENANT_ID)
    assert exc.value.status_code == 422
    assert "100" in str(exc.value.detail)


def test_validate_rejects_duplicate_items(db: Session, passage: Passage) -> None:
    items = [
        _item(AttemptItemType.PASSAGE, passage.id),
        _item(AttemptItemType.PASSAGE, passage.id),
    ]
    with pytest.raises(HTTPException) as exc:
        exercise_service.validate_assignment_items(db, items, DEFAULT_TENANT_ID)
    assert exc.value.status_code == 422
    assert "重复" in str(exc.value.detail)


def test_validate_rejects_child_passage(db: Session) -> None:
    # 拆句生成的子篇目不能直接指派（只能指派父篇目再展开）
    parent = Passage(title="父篇", text="parent", slug=f"pp-{_uid()}")
    db.add(parent)
    db.commit()
    db.refresh(parent)
    child = Passage(
        title="子篇",
        text="child",
        slug=f"cp-{_uid()}",
        parent_passage_id=parent.id,
    )
    db.add(child)
    db.commit()
    db.refresh(child)

    with pytest.raises(HTTPException) as exc:
        exercise_service.validate_assignment_items(
            db, [_item(AttemptItemType.PASSAGE, child.id)], DEFAULT_TENANT_ID
        )
    assert exc.value.status_code == 404


def test_validate_rejects_unknown_question(db: Session) -> None:
    with pytest.raises(HTTPException) as exc:
        exercise_service.validate_assignment_items(
            db, [_item(AttemptItemType.QUESTION, uuid.uuid4())], DEFAULT_TENANT_ID
        )
    assert exc.value.status_code == 404
    assert "问答题" in str(exc.value.detail)


def test_validate_rejects_question_of_inactive_scenario(
    db: Session, scenario: Scenario, question: ScenarioQuestion
) -> None:
    scenario.is_active = False
    db.add(scenario)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        exercise_service.validate_assignment_items(
            db, [_item(AttemptItemType.QUESTION, question.id)], DEFAULT_TENANT_ID
        )
    assert exc.value.status_code == 422
    assert "主题" in str(exc.value.detail)


def test_validate_accepts_mixed_valid_items(
    db: Session,
    passage: Passage,
    sentence: RepeatSentence,
    question: ScenarioQuestion,
    instruction: Instruction,
) -> None:
    exercise_service.validate_assignment_items(
        db,
        [
            _item(AttemptItemType.PASSAGE, passage.id),
            _item(AttemptItemType.REPEAT, sentence.id),
            _item(AttemptItemType.QUESTION, question.id),
            _item(AttemptItemType.INSTRUCTION, instruction.id),
        ],
        DEFAULT_TENANT_ID,
    )


def test_validate_treats_foreign_items_as_missing(
    db: Session, other_tenant: uuid.UUID
) -> None:
    # 跨校内容按 404 处理：他校篇目不得被指派进本校作业（C5 应用层防线）
    with tenant_scope(other_tenant):
        foreign = Passage(title="别校篇", text="foreign", slug=f"f-{_uid()}")
        db.add(foreign)
        db.commit()
        db.refresh(foreign)

    with pytest.raises(HTTPException) as exc:
        exercise_service.validate_assignment_items(
            db, [_item(AttemptItemType.PASSAGE, foreign.id)], DEFAULT_TENANT_ID
        )
    assert exc.value.status_code == 404


def test_resolve_returns_none_without_assignment(db: Session) -> None:
    classroom = Classroom(code=f"NONE{_uid()[:4].upper()}", class_size=5)
    db.add(classroom)
    db.commit()
    assert exercise_service.resolve_assigned_items(db, classroom) is None


def test_resolve_skips_missing_inactive_and_malformed(
    db: Session,
    passage: Passage,
    sentence: RepeatSentence,
    question: ScenarioQuestion,
) -> None:
    inactive = Passage(
        title="已停用", text="off", slug=f"off-{_uid()}", is_active=False
    )
    db.add(inactive)
    db.commit()
    db.refresh(inactive)

    classroom = Classroom(code=f"RES{_uid()[:4].upper()}", class_size=5)
    classroom.assigned_items = [
        {"type": "passage", "id": str(passage.id)},
        {"type": "repeat", "id": str(sentence.id)},
        {"type": "question", "id": str(question.id)},
        {"type": "passage", "id": str(inactive.id)},  # 停用 → 跳过
        {"type": "passage", "id": str(uuid.uuid4())},  # 已删 → 跳过
        {"type": "unknown", "id": str(uuid.uuid4())},  # 未知题型 → 忽略
        {"type": "passage", "id": ""},  # 无 id → 跳过
    ]
    db.add(classroom)
    db.commit()
    db.refresh(classroom)

    result = exercise_service.resolve_assigned_items(db, classroom)
    assert result is not None
    passages, sentences, questions = result
    assert [p.id for p in passages] == [passage.id]
    assert [s.id for s in sentences] == [sentence.id]
    assert [q.id for q in questions] == [question.id]


def test_resolve_empty_assignment_list_returns_empty_triplet(db: Session) -> None:
    # assigned_items 存在但全是被删对象：返回三个空列表而不是 None（走按题路径）
    classroom = Classroom(code=f"EMP{_uid()[:4].upper()}", class_size=5)
    classroom.assigned_items = [{"type": "passage", "id": str(uuid.uuid4())}]
    db.add(classroom)
    db.commit()

    result = exercise_service.resolve_assigned_items(db, classroom)
    assert result == ([], [], [])


def test_snapshot_passage_copies_content(db: Session, passage: Passage) -> None:
    snapshot = exercise_service.build_snapshot_item(
        db, AttemptItemType.PASSAGE, passage.id, DEFAULT_TENANT_ID
    )
    assert snapshot["type"] == AttemptItemType.PASSAGE
    assert snapshot["id"] == str(passage.id)
    assert snapshot["text"] == passage.text


def test_snapshot_rejects_child_passage(db: Session) -> None:
    parent = Passage(title="父", text="p", slug=f"sp-{_uid()}")
    db.add(parent)
    db.commit()
    db.refresh(parent)
    child = Passage(
        title="子", text="c", slug=f"sc-{_uid()}", parent_passage_id=parent.id
    )
    db.add(child)
    db.commit()
    db.refresh(child)

    with pytest.raises(HTTPException) as exc:
        exercise_service.build_snapshot_item(
            db, AttemptItemType.PASSAGE, child.id, DEFAULT_TENANT_ID
        )
    assert exc.value.status_code == 404


def test_snapshot_rejects_foreign_item(db: Session, other_tenant: uuid.UUID) -> None:
    with tenant_scope(other_tenant):
        foreign = RepeatSentence(order_index=1, text="foreign sentence")
        db.add(foreign)
        db.commit()
        db.refresh(foreign)

    with pytest.raises(HTTPException) as exc:
        exercise_service.build_snapshot_item(
            db, AttemptItemType.REPEAT, foreign.id, DEFAULT_TENANT_ID
        )
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    ("kind", "fixture_name"),
    [
        (AttemptItemType.REPEAT, "sentence"),
        (AttemptItemType.QUESTION, "question"),
        (AttemptItemType.INSTRUCTION, "instruction"),
    ],
)
def test_snapshot_other_kinds(
    db: Session, request: pytest.FixtureRequest, kind: str, fixture_name: str
) -> None:
    obj = request.getfixturevalue(fixture_name)
    snapshot = exercise_service.build_snapshot_item(db, kind, obj.id, DEFAULT_TENANT_ID)
    assert snapshot["type"] == kind
    assert snapshot["id"] == str(obj.id)
    assert snapshot["text"] == obj.text


@pytest.mark.parametrize(
    "kind",
    [AttemptItemType.REPEAT, AttemptItemType.INSTRUCTION, AttemptItemType.QUESTION],
)
def test_snapshot_missing_item_raises_404(db: Session, kind: str) -> None:
    with pytest.raises(HTTPException) as exc:
        exercise_service.build_snapshot_item(db, kind, uuid.uuid4(), DEFAULT_TENANT_ID)
    assert exc.value.status_code == 404


def test_publish_rejects_empty_snapshots(db: Session) -> None:
    classroom = Classroom(code=f"PUB{_uid()[:4].upper()}", class_size=5)
    with pytest.raises(HTTPException) as exc:
        exercise_service.publish_exercise(db, classroom, None, [])
    assert exc.value.status_code == 422
    assert "至少需要包含一道题目" in str(exc.value.detail)


def test_publish_rejects_over_long_title(db: Session, passage: Passage) -> None:
    classroom = Classroom(code=f"LON{_uid()[:4].upper()}", class_size=5)
    snapshots = [
        exercise_service.build_snapshot_item(
            db, AttemptItemType.PASSAGE, passage.id, DEFAULT_TENANT_ID
        )
    ]
    with pytest.raises(HTTPException) as exc:
        exercise_service.publish_exercise(
            db, classroom, None, snapshots, title="名" * 300
        )
    assert exc.value.status_code == 422
    assert "255" in str(exc.value.detail)


def test_publish_rejects_exam_in_homework_slot(db: Session, passage: Passage) -> None:
    classroom = Classroom(code=f"HMW{_uid()[:4].upper()}", class_size=5)
    snapshots = [
        exercise_service.build_snapshot_item(
            db, AttemptItemType.PASSAGE, passage.id, DEFAULT_TENANT_ID
        )
    ]
    with pytest.raises(HTTPException) as exc:
        exercise_service.publish_exercise(
            db,
            classroom,
            None,
            snapshots,
            is_exam=True,
            time_limit_minutes=30,
            slot="homework",
        )
    assert exc.value.status_code == 422
    assert "课后作业" in str(exc.value.detail)


def test_validate_rejects_all_instruction_items(
    db: Session, instruction: Instruction
) -> None:
    # 只有说明页没有可作答题目：发布出去学生无事可做
    with pytest.raises(HTTPException) as exc:
        exercise_service.validate_assignment_items(
            db,
            [_item(AttemptItemType.INSTRUCTION, instruction.id)],
            DEFAULT_TENANT_ID,
        )
    assert exc.value.status_code == 422
    assert "至少" in str(exc.value.detail)


def test_validate_rejects_unknown_item_type(db: Session) -> None:
    with pytest.raises(HTTPException) as exc:
        exercise_service.validate_assignment_items(
            db, [_item("video", uuid.uuid4())], DEFAULT_TENANT_ID
        )
    assert exc.value.status_code == 422
    assert "未知题型" in str(exc.value.detail)


@pytest.mark.parametrize(
    ("kind", "word"),
    [(AttemptItemType.REPEAT, "复述"), (AttemptItemType.INSTRUCTION, "说明")],
)
def test_validate_rejects_missing_item(
    db: Session, passage: Passage, kind: str, word: str
) -> None:
    # 搭配一道有效篇目，先越过"至少一道可作答题目"检查，才落到缺失 404
    with pytest.raises(HTTPException) as exc:
        exercise_service.validate_assignment_items(
            db,
            [_item(AttemptItemType.PASSAGE, passage.id), _item(kind, uuid.uuid4())],
            DEFAULT_TENANT_ID,
        )
    assert exc.value.status_code == 404
    assert word in str(exc.value.detail)


def _snap(kind: str, obj_id: uuid.UUID, **extra: object) -> dict[str, object]:
    """构造发布用快照条目（与 publish_exercise 的入参类型一致）。"""
    return {"type": kind, "id": str(obj_id), **extra}


def _classroom(db: Session) -> Classroom:
    row = Classroom(code=f"CLS{_uid()[:4].upper()}", class_size=5)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_publish_rejects_more_than_100_snapshots(db: Session, passage: Passage) -> None:
    classroom = _classroom(db)
    snapshots = [_snap(AttemptItemType.PASSAGE, passage.id)] * 101
    with pytest.raises(HTTPException) as exc:
        exercise_service.publish_exercise(db, classroom, None, snapshots)
    assert exc.value.status_code == 422
    assert "100" in str(exc.value.detail)


def test_publish_requires_time_limit_for_exam(db: Session, passage: Passage) -> None:
    classroom = _classroom(db)
    snapshots = [_snap(AttemptItemType.PASSAGE, passage.id)]
    with pytest.raises(HTTPException) as exc:
        exercise_service.publish_exercise(db, classroom, None, snapshots, is_exam=True)
    assert exc.value.status_code == 422
    assert "限时" in str(exc.value.detail)


def test_publish_rejects_out_of_range_time_limit(db: Session, passage: Passage) -> None:
    classroom = _classroom(db)
    snapshots = [_snap(AttemptItemType.PASSAGE, passage.id)]
    with pytest.raises(HTTPException) as exc:
        exercise_service.publish_exercise(
            db, classroom, None, snapshots, is_exam=True, time_limit_minutes=3
        )
    assert exc.value.status_code == 422
    assert "5" in str(exc.value.detail)


def test_publish_class_slot_versions_and_archives(
    db: Session, passage: Passage
) -> None:
    classroom = _classroom(db)
    first = exercise_service.publish_exercise(
        db,
        classroom,
        None,
        [_snap(AttemptItemType.PASSAGE, passage.id)],
        title="第一课",
    )
    db.commit()
    assert first.version_no == 1
    assert classroom.current_exercise_id == first.id
    # 指派镜像只存真实题目 ID
    assert classroom.assigned_items == [{"type": "passage", "id": str(passage.id)}]

    second = exercise_service.publish_exercise(
        db,
        classroom,
        None,
        [_snap(AttemptItemType.PASSAGE, passage.id)],
        title="第二课",
    )
    db.commit()
    assert second.version_no == 2
    assert classroom.current_exercise_id == second.id
    # 旧版本自动归档，历史会话仍绑旧快照
    db.refresh(first)
    assert first.status == "archived"
    assert first.archived_at is not None


def test_publish_homework_slot_replaces_previous(db: Session, passage: Passage) -> None:
    classroom = _classroom(db)
    first = exercise_service.publish_exercise(
        db,
        classroom,
        None,
        [{"type": "passage", "id": str(passage.id)}],
        slot="homework",
    )
    db.commit()
    assert classroom.homework_exercise_id == first.id
    # 作业槽不改课堂当前练习
    assert classroom.current_exercise_id is None

    second = exercise_service.publish_exercise(
        db,
        classroom,
        None,
        [{"type": "passage", "id": str(passage.id)}],
        slot="homework",
    )
    db.commit()
    assert classroom.homework_exercise_id == second.id
    db.refresh(first)
    assert first.status == "archived"


def test_publish_automated_exam_requires_audio(
    db: Session, sentence: RepeatSentence
) -> None:
    classroom = _classroom(db)
    snapshots = [_snap(AttemptItemType.REPEAT, sentence.id, audio_url="")]
    with pytest.raises(HTTPException) as exc:
        exercise_service.publish_exercise(
            db,
            classroom,
            None,
            snapshots,
            is_exam=True,
            time_limit_minutes=30,
            automated_exam=True,
        )
    assert exc.value.status_code == 422
    assert "audio missing" in str(exc.value.detail)


def test_publish_automated_exam_freezes_exam_flow(
    db: Session, sentence: RepeatSentence
) -> None:
    # 题目级模考设置（含音频地址）在发布时冻结进快照
    sentence.exam_settings = {"audio_url": "https://cdn.example.com/a.mp3"}
    db.add(sentence)
    db.commit()

    classroom = _classroom(db)
    snapshots = [
        _snap(
            AttemptItemType.REPEAT,
            sentence.id,
            exam_kind="ielts_p2",
            prep_seconds=45,
        )
    ]
    exercise = exercise_service.publish_exercise(
        db,
        classroom,
        None,
        snapshots,
        is_exam=True,
        time_limit_minutes=30,
        automated_exam=True,
    )
    db.commit()

    item = cast(list[dict[str, Any]], exercise.snapshot_items)[0]
    assert item["audio_url"] == "https://cdn.example.com/a.mp3"
    assert item["exam_flow"]["prep_seconds"] == 45
