"""多租户 C2：唯一性收窄到校内 + UPSERT/幂等键租户语义。

验收点（A 期清单 §2-1/§2-2，设计稿 §4.3）：
1. passage.slug / scenario.topic 校内唯一：两校可同名，同校重名仍撞。
2. item_listen 作用域含租户：复合约束下 UPSERT 语义不变（跨校不串计数）。
3. 幂等键保留全局唯一 + 命中跨租户按不存在处理（attempts 404 /
   vocabulary 视为无重放）——不泄露他校作答。
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.models import (
    DEFAULT_TENANT_ID,
    Attempt,
    Classroom,
    Passage,
    PracticeSession,
    Scenario,
    Student,
    Tenant,
    VocabularyAnswer,
    VocabularySession,
)


def _make_other_tenant(db: Session) -> Tenant:
    other = Tenant(slug=f"c2-{uuid.uuid4().hex[:6]}", name_zh="C2 乙校")
    db.add(other)
    db.commit()
    db.refresh(other)
    return other


def test_passage_slug_same_across_tenants_unique_within(db: Session) -> None:
    """两校同名 slug 各自成篇；同校重名仍被复合唯一拒绝。"""
    other = _make_other_tenant(db)
    slug = f"shared-{uuid.uuid4().hex[:8]}"
    a = Passage(title="甲校篇目", text="A.", slug=slug)
    b = Passage(title="乙校篇目", text="B.", slug=slug, tenant_id=other.id)
    db.add(a)
    db.add(b)
    db.commit()
    assert a.tenant_id == DEFAULT_TENANT_ID
    assert b.tenant_id == other.id

    dup = Passage(title="甲校重名", text="A2.", slug=slug)
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_scenario_topic_same_across_tenants_unique_within(db: Session) -> None:
    """两校同名情景主题各自成行；同校重名仍被拒绝。"""
    other = _make_other_tenant(db)
    topic = f"SharedTopic{uuid.uuid4().hex[:6]}"
    db.add(Scenario(topic=topic))
    db.add(Scenario(topic=topic, tenant_id=other.id))
    db.commit()

    db.add(Scenario(topic=f"{topic}-dup"))
    db.rollback()
    db.add(Scenario(topic=topic))  # 默认租户内重名
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_item_listen_scope_includes_tenant(db: Session) -> None:
    """复合约束列集 = (tenant_id, student, session, item)——跨校同三元组
    不冲突（RLS 收口前 UPSERT 语义与租户核验的正统化）。"""
    from sqlalchemy.exc import IntegrityError as IE

    from app.models import ItemListen

    other = _make_other_tenant(db)
    classroom = Classroom(code=f"L{uuid.uuid4().hex[:6].upper()}", class_size=5)
    db.add(classroom)
    db.flush()
    student = Student(classroom_id=classroom.id, display_name="C2听句")
    db.add(student)
    db.flush()
    from datetime import date as _date

    ps = PracticeSession(
        classroom_id=classroom.id,
        student_id=student.id,
        band="B1",
        session_date=_date.today(),
    )
    db.add(ps)
    db.flush()
    item = uuid.uuid4()

    def _listen(tenant_id: uuid.UUID) -> None:
        db.add(
            ItemListen(
                tenant_id=tenant_id,
                student_id=student.id,
                session_id=ps.id,
                item_id=item,
                count=1,
            )
        )
        db.commit()

    _listen(DEFAULT_TENANT_ID)
    # 同校同三元组：撞复合唯一
    with pytest.raises(IE):
        _listen(DEFAULT_TENANT_ID)
    db.rollback()
    # 他校同三元组：各自成立
    _listen(other.id)


def test_attempt_idempotent_cross_tenant_treated_as_missing(db: Session) -> None:
    """幂等键全局唯一：跨租户命中（撞他校行）→ 归属判定 404 不泄露。

    直接验证服务层语义：他校作答行存在同键时，本校上下文不得读到他校行。
    """
    from fastapi import HTTPException

    from app.api.routes.attempts import _require_attempt_access
    from app.models import User

    other = _make_other_tenant(db)
    key = f"c2k-{uuid.uuid4().hex[:12]}"
    # 本校登录学生（撞同键提交的一方）
    mine = User(
        email=f"c2-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="student",
    )
    db.add(mine)
    # 他校的学生档案（归属他校班；登录账号无关联——跨校行与本校用户
    # 唯一的交点就是全局唯一的幂等键）
    his_class = Classroom(
        code=f"H{uuid.uuid4().hex[:6].upper()}", class_size=5, tenant_id=other.id
    )
    db.add(his_class)
    db.flush()
    his_student = Student(
        classroom_id=his_class.id,
        display_name="他校生",
        tenant_id=other.id,
    )
    db.add(his_student)
    db.flush()
    # 他校的作答（带幂等键，挂他校档案）
    his = Attempt(
        tenant_id=other.id,
        item_type="question",
        item_id=uuid.uuid4(),
        student_id=his_student.id,
        audio_path="his.webm",
        duration_s=3.0,
        status="done",
        idempotency_key=key,
    )
    db.add(his)
    db.commit()

    # 本校用户撞同键：归属判定按租户把他校行视为不存在（404 不泄露）
    with pytest.raises(HTTPException) as exc:
        _require_attempt_access(db, his, mine)
    assert exc.value.status_code == 404


def test_vocab_answer_idempotent_cross_tenant_no_replay(db: Session) -> None:
    """词汇作答幂等重放：跨租户命中按无重放处理（不返回他校回执）。"""

    from app.services.vocabulary import recognize_answer_replay

    other = _make_other_tenant(db)
    key = f"vk-{uuid.uuid4().hex[:12]}"
    classroom = Classroom(code=f"V{uuid.uuid4().hex[:6].upper()}", class_size=5)
    db.add(classroom)
    db.flush()
    student = Student(classroom_id=classroom.id, display_name="C2词练")
    db.add(student)
    db.flush()
    my_session = VocabularySession(
        classroom_id=classroom.id,
        student_id=student.id,
    )
    db.add(my_session)
    db.flush()
    # 他校的作答行带同键（全局唯一撞键）
    db.add(
        VocabularyAnswer(
            tenant_id=other.id,
            session_id=my_session.id,
            item_index=0,
            prompt_type="meaning",
            answer_raw="x",
            answer_normalized="x",
            is_correct=True,
            word_id=uuid.uuid4(),
            headword="x",
            meaning_zh="义",
            idempotency_key=key,
        )
    )
    db.commit()
    # 本校重放查询：不得返回他校行（None=无重放，走正常提交路径）
    got = recognize_answer_replay(
        db,
        my_session,
        item_index=0,
        prompt_type="meaning",
        answer_raw="x",
        idempotency_key=key,
    )
    assert got is None
