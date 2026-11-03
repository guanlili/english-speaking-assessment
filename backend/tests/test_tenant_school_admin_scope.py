"""多租户 AC-03/05/06/08：school_admin「看全部」放行分支的租户收口补测。

背景：school_admin 放大分支此前在应用层无租户过滤——生产由 RLS（esa_app
受限角色）兜底，但无 RLS 的测试/开发/配置回落环境会跨校泄露。本文件锁住
修复后的应用层语义（与 RLS 激活环境一致，CLAUDE.md 多租户不变量④）：

- AC-08 课堂列表：管理员「看全部」= 本校全部
- AC-06 批量作答读取：他校 id 与不存在同为 404
- AC-03 学生密码重置：跨校课堂按不存在处理（404）
- AC-05 词库列表/详情：他校词库（含 public）不可见
- AC-06 词库编辑/发布/词条编辑：跨校写路径 404/403
- AC-05 级别词条查询：他校词行不出现在结果中

既有覆盖：test_tenant_c5_acceptance.py（对象级越权）、
test_tenant_c4a_rls.py（RLS 策略层）；本文件补 school_admin 放大分支。
"""

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import security
from app.models import (
    DEFAULT_TENANT_ID,
    Attempt,
    Classroom,
    PracticeSession,
    Student,
    Tenant,
    User,
    VocabularyBook,
    VocabularyBookItem,
    VocabularyLevelEntry,
    VocabularyWord,
)


def _uid() -> str:
    """函数级唯一：CI rerun 重试会重跑用例，module 级常量会撞唯一键。"""
    return uuid.uuid4().hex[:8]


def _mk_user(db: Session, tenant_id, role: str, name: str) -> User:
    user = User(
        email=f"sa-{name}-{_uid()}@example.com",
        hashed_password="x",
        role=role,
        tenant_id=tenant_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _token(user: User, tenant_id) -> dict[str, str]:
    token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=10),
        role=user.role,
        password_hash=user.hashed_password,
        tenant_id=str(tenant_id),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def b_tenant(db: Session) -> Tenant:
    row = Tenant(slug=f"sa-{_uid()}", name_zh="收口乙校")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture(scope="module")
def users(db: Session, b_tenant) -> dict[str, User]:
    """甲校（默认租户）教师 + 乙校教师/管理员——乙校账号是攻击者视角。"""
    return {
        "teacher_a": _mk_user(db, DEFAULT_TENANT_ID, "teacher", "ta"),
        "teacher_b": _mk_user(db, b_tenant.id, "teacher", "tb"),
        "admin_b": _mk_user(db, b_tenant.id, "school_admin", "ab"),
    }


@pytest.fixture(scope="module")
def a_classroom(db: Session) -> Classroom:
    row = Classroom(code=f"SAA{_uid()[:6].upper()}", class_size=5)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture(scope="module")
def b_classroom(db: Session, b_tenant, users) -> Classroom:
    row = Classroom(
        code=f"SAB{_uid()[:6].upper()}",
        class_size=5,
        owner_id=users["teacher_b"].id,
        tenant_id=b_tenant.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture(scope="module")
def a_attempt(db: Session, a_classroom) -> Attempt:
    student = Student(classroom_id=a_classroom.id, display_name="甲校生")
    db.add(student)
    db.flush()
    session_row = PracticeSession(
        classroom_id=a_classroom.id,
        student_id=student.id,
        band="B1",
        session_date=date.today(),
    )
    db.add(session_row)
    db.flush()
    attempt = Attempt(
        item_type="question",
        item_id=uuid.uuid4(),
        student_id=student.id,
        session_id=session_row.id,
        audio_path="a.webm",
        duration_s=3.0,
        status="done",
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


@pytest.fixture(scope="module")
def a_student(db: Session, a_classroom) -> Student:
    """甲校学生（绑定账号）——乙校管理员尝试重置其密码。"""
    user = _mk_user(db, DEFAULT_TENANT_ID, "student", "st")
    row = Student(
        classroom_id=a_classroom.id,
        display_name="甲校生号",
        user_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture(scope="module")
def a_book(db: Session) -> VocabularyBook:
    row = VocabularyBook(title=f"甲校词库{_uid()[:4]}", scope="public")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture(scope="module")
def b_book(db: Session, b_tenant) -> VocabularyBook:
    row = VocabularyBook(
        title=f"乙校词库{_uid()[:4]}",
        scope="public",
        tenant_id=b_tenant.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture(scope="module")
def a_word(db: Session, a_book) -> VocabularyWord:
    """甲校词 + 词库条目 + 五级分级行（级别查询链路需要分级命中）。"""
    headword = f"zax{_uid()[:8]}"
    word = VocabularyWord(headword=headword, meaning_zh="甲校释义", status="active")
    db.add(word)
    db.flush()
    db.add(VocabularyBookItem(book_id=a_book.id, word_id=word.id, position=1))
    db.add(
        VocabularyLevelEntry(
            headword=headword,
            level="KET",
            meaning_zh="甲校释义",
        )
    )
    db.commit()
    db.refresh(word)
    return word


def test_ac08_admin_classroom_list_scoped_to_school(
    client: TestClient, users, b_tenant, a_classroom, b_classroom
) -> None:
    """课堂列表：乙校管理员只见本校课堂；甲校课堂不在任何乙校账号列表里。"""
    admin_b = users["admin_b"]
    resp = client.get("/api/v1/classes", headers=_token(admin_b, b_tenant.id))
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert str(b_classroom.id) in ids  # 正向：本校课堂可见
    assert str(a_classroom.id) not in ids  # 跨校不可见

    teacher_b = users["teacher_b"]
    resp = client.get("/api/v1/classes", headers=_token(teacher_b, b_tenant.id))
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert str(b_classroom.id) in ids
    assert str(a_classroom.id) not in ids


def test_ac06_batch_read_cross_tenant_404(
    client: TestClient, users, b_tenant, a_attempt
) -> None:
    """批量作答读取：他校 attempt id 与不存在同为 404，不泄露作答存在性。"""
    body = {"attempt_ids": [str(a_attempt.id)]}
    for key in ("teacher_b", "admin_b"):
        resp = client.post(
            "/api/v1/attempts/batch-read",
            json=body,
            headers=_token(users[key], b_tenant.id),
        )
        assert resp.status_code == 404, f"{key}: {resp.text}"

    # 对照：不存在的 id 同为 404（响应一致才不构成存在性预言）
    resp = client.post(
        "/api/v1/attempts/batch-read",
        json={"attempt_ids": [str(uuid.uuid4())]},
        headers=_token(users["admin_b"], b_tenant.id),
    )
    assert resp.status_code == 404, resp.text


def test_ac03_cross_school_student_reset_404(
    client: TestClient, users, b_tenant, a_student
) -> None:
    """入口篡改：乙校管理员重置甲校学生密码 → 404（跨校课堂不存在）。

    修复前该路径会因 school_admin 放行直接改密（账号接管面）。
    """
    resp = client.post(
        f"/api/v1/students/{a_student.id}/reset-password",
        headers=_token(users["admin_b"], b_tenant.id),
    )
    assert resp.status_code == 404, resp.text


def test_ac05_admin_book_list_scoped_to_school(
    client: TestClient, users, b_tenant, a_book, b_book
) -> None:
    """词库列表：乙校管理员只见本校词库——他校 public 词库也不出现。"""
    resp = client.get(
        "/api/v1/vocabulary/books", headers=_token(users["admin_b"], b_tenant.id)
    )
    assert resp.status_code == 200, resp.text
    ids = [row["id"] for row in resp.json()]
    assert str(b_book.id) in ids
    assert str(a_book.id) not in ids


def test_ac05_cross_school_book_detail_403(
    client: TestClient, users, b_tenant, a_book, b_book
) -> None:
    """词库详情：乙校账号读甲校词库 → 403（与本校他人词库同响应）。"""
    for key in ("admin_b", "teacher_b"):
        resp = client.get(
            f"/api/v1/vocabulary/books/{a_book.id}",
            headers=_token(users[key], b_tenant.id),
        )
        assert resp.status_code == 403, f"{key}: {resp.text}"

    # 正向对照：本校词库详情可用
    resp = client.get(
        f"/api/v1/vocabulary/books/{b_book.id}",
        headers=_token(users["admin_b"], b_tenant.id),
    )
    assert resp.status_code == 200, resp.text


def test_ac06_cross_school_book_edit_404(
    client: TestClient, users, b_tenant, a_book, b_book
) -> None:
    """词库编辑：乙校管理员改甲校词库名 → 404（跨校按不存在处理）。"""
    resp = client.patch(
        f"/api/v1/vocabulary/books/{a_book.id}",
        json={"title": "越权改名"},
        headers=_token(users["admin_b"], b_tenant.id),
    )
    assert resp.status_code == 404, resp.text

    # 正向对照：本校词库可改
    resp = client.patch(
        f"/api/v1/vocabulary/books/{b_book.id}",
        json={"title": b_book.title},
        headers=_token(users["admin_b"], b_tenant.id),
    )
    assert resp.status_code == 200, resp.text


def test_ac06_publish_cross_school_book_403(
    client: TestClient, users, b_tenant, b_classroom, a_book
) -> None:
    """发布词汇任务：词单来源带甲校词库 → 403（发布链路不读他校词库）。"""
    body = {"book_id": str(a_book.id), "prompt_types": ["meaning"]}
    for key in ("admin_b", "teacher_b"):
        resp = client.post(
            f"/api/v1/classes/{b_classroom.code}/vocabulary/assignments",
            json=body,
            headers=_token(users[key], b_tenant.id),
        )
        assert resp.status_code == 403, f"{key}: {resp.text}"


def test_ac06_cross_school_word_update_404(
    client: TestClient, users, b_tenant, a_word
) -> None:
    """词条编辑：乙校管理员改甲校词条释义 → 404。"""
    resp = client.patch(
        f"/api/v1/vocabulary/words/{a_word.id}",
        json={"meaning_zh": "越权改写"},
        headers=_token(users["admin_b"], b_tenant.id),
    )
    assert resp.status_code == 404, resp.text


def test_ac05_teaching_words_level_scoped_to_school(
    client: TestClient, users, b_tenant, a_word
) -> None:
    """级别词条查询：甲校词不出现在乙校任何账号的结果里。"""
    for key in ("admin_b", "teacher_b"):
        resp = client.get(
            "/api/v1/vocabulary/words",
            params={"level": "KET", "limit": 500},
            headers=_token(users[key], b_tenant.id),
        )
        assert resp.status_code == 200, f"{key}: {resp.text}"
        heads = [row["headword"] for row in resp.json()]
        assert a_word.headword not in heads, f"{key} 泄露他校词条"

    # 正向对照：甲校教师能查到本校词（证明端点本身返回该词，非空断言）
    resp = client.get(
        "/api/v1/vocabulary/words",
        params={"level": "KET", "limit": 500},
        headers=_token(users["teacher_a"], DEFAULT_TENANT_ID),
    )
    assert resp.status_code == 200, resp.text
    heads = [row["headword"] for row in resp.json()]
    assert a_word.headword in heads
