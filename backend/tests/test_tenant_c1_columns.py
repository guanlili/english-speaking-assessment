"""多租户 C1：全业务表租户归属落列。

验收点（设计稿 §4.2/§9-2，B1 锚点定式推广）：
1. 30 张业务表全部带 tenant_id（NOT NULL + FK + 默认租户兜底）。
2. 身份层/平台口径表不带（tenant/platform_operator/三张平台表）。
3. 业务写入不显式给 tenant_id 时默认归默认租户（server_default 兜底）。
4. 全业务冒烟：造数链路（建班→学生→会话→作答）不受影响。
"""

import uuid

from sqlmodel import Session

from app.models import (
    DEFAULT_TENANT_ID,
    Attempt,
    Classroom,
    Passage,
    PracticeSession,
    SQLModel,
    Student,
)

# C1 落列的 30 张业务表（models 的 __tablename__）
EXPECTED_TENANT_TABLES = {
    "attempt",
    "classroom_exercise",
    "classroom_message",
    "classroom_review",
    "composer_draft",
    "export_audit",
    "export_job",
    "followup_batch",
    "instruction",
    "instruction_ack",
    "item_listen",
    "passage",
    "practice_session",
    "repeat_sentence",
    "scenario",
    "scenario_question",
    "sentence_frame",
    "student_badge",
    "student_expression_favorite",
    "student_frame_favorite",
    "unit",
    "vocab_level_entry",
    "vocabulary_ai_cache",
    "vocabulary_answer",
    "vocabulary_assignment",
    "vocabulary_assignment_target",
    "vocabulary_book",
    "vocabulary_book_item",
    "vocabulary_session",
    "vocabulary_word",
}

# 明确不带租户列的表：身份层 + 平台口径（设计稿 §4.2）
EXPECTED_NO_TENANT_TABLES = {
    "tenant",
    "platformoperator",
    "admin_metrics_daily",
    "admin_cost_reconcile",
    "changelog_entry",
}


def test_c1_column_inventory() -> None:
    """30 业务表全带 tenant_id；身份层与平台口径表不带。"""
    with_tenant = set()
    without_tenant = set()
    for table in SQLModel.metadata.sorted_tables:
        if "tenant_id" in table.c:
            with_tenant.add(table.name)
        else:
            without_tenant.add(table.name)
    # 锚点三表（B1）+ user 也带
    assert {"user", "classroom", "student"} <= with_tenant
    got_business = with_tenant - {"user", "classroom", "student"}
    assert got_business == EXPECTED_TENANT_TABLES, (
        f"missing={EXPECTED_TENANT_TABLES - got_business} "
        f"extra={got_business - EXPECTED_TENANT_TABLES}"
    )
    assert EXPECTED_NO_TENANT_TABLES <= without_tenant


def test_c1_columns_not_null_with_default() -> None:
    """列约束齐备：NOT NULL、FK 指向 tenant、server_default 兜底存量。"""
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in EXPECTED_TENANT_TABLES:
            continue
        col = table.c["tenant_id"]
        assert not col.nullable, table.name
        fks = list(col.foreign_keys)
        assert len(fks) == 1 and fks[0].column.table.name == "tenant", table.name
        assert col.server_default is not None, table.name


def test_c1_default_tenant_backfill(db: Session) -> None:
    """业务写入不显式给租户 → server_default 归默认租户（增量漏写不可能）。"""
    classroom = Classroom(code=f"c1-{uuid.uuid4().hex[:8]}", class_size=5)
    db.add(classroom)
    db.flush()
    passage = Passage(
        title="C1 归属冒烟",
        text="Tenant column smoke.",
        slug=f"c1-{uuid.uuid4().hex[:8]}",
    )
    db.add(passage)
    db.commit()
    db.refresh(classroom)
    db.refresh(page := passage)
    assert classroom.tenant_id == DEFAULT_TENANT_ID
    assert page.tenant_id == DEFAULT_TENANT_ID


def test_c1_business_chain_smoke(db: Session) -> None:
    """造数主链路（班→学生→会话→作答）全部落默认租户——零行为变化。"""
    classroom = Classroom(code=f"c1c-{uuid.uuid4().hex[:8]}", class_size=5)
    db.add(classroom)
    db.flush()
    student = Student(classroom_id=classroom.id, display_name="C1同学")
    db.add(student)
    db.flush()
    from datetime import date as _date

    session = PracticeSession(
        classroom_id=classroom.id,
        student_id=student.id,
        band="B1",
        session_date=_date.today(),
    )
    db.add(session)
    db.flush()
    attempt = Attempt(
        item_type="question",
        item_id=uuid.uuid4(),
        student_id=student.id,
        session_id=session.id,
        audio_path="c1.webm",
        duration_s=3.0,
        status="done",
    )
    db.add(attempt)
    db.commit()

    db.refresh(classroom)
    db.refresh(student)
    db.refresh(session)
    db.refresh(attempt)
    for row in (classroom, student, session, attempt):
        assert row.tenant_id == DEFAULT_TENANT_ID, type(row).__name__
