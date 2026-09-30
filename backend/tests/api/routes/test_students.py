"""students 路由测试：批量导入（含历史匿名档案绑定）、重置、移出、名单。

此前该模块覆盖率全项目最低（46%）：导入与「同名历史档案自动绑定」是
数据迁移型逻辑，绑错会把学生 XP/作答历史挂到错误账号。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.security import DEFAULT_STUDENT_PASSWORD
from app.models import Classroom, Student, User, UserCreate
from tests.utils.utils import random_email, random_lower_string


def _login_teacher(db: Session, client: TestClient) -> tuple[User, dict[str, str]]:
    email, password = random_email(), random_lower_string()
    user = crud.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    resp = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return user, {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _new_classroom(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post("/api/v1/classes", json={"class_size": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _cleanup(db: Session, classroom_id: uuid.UUID | None, *users: User) -> None:
    """conftest 的 db 是整轮会话级：自建的课堂/账号必须 finally 清理。"""
    if classroom_id is not None:
        classroom = db.get(Classroom, classroom_id)
        if classroom is not None:
            db.delete(classroom)
    for user in users:
        row = db.get(User, user.id)
        if row is not None:
            db.delete(row)
    db.commit()


def _import(
    client: TestClient, headers: dict[str, str], classroom_id: str, lines: list[dict]
) -> dict:
    resp = client.post(
        "/api/v1/students/import",
        json={"classroom_id": classroom_id, "lines": lines},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_import_creates_students_with_default_password(
    client: TestClient, db: Session
) -> None:
    """导入新学生：建账号（默认密码可登录）+ 建档案，名单回显学号。"""
    teacher, headers = _login_teacher(db, client)
    classroom_id = None
    try:
        classroom_id = uuid.UUID(_new_classroom(client, headers)["id"])
        suffix = uuid.uuid4().hex[:6]
        result = _import(
            client,
            headers,
            str(classroom_id),
            [
                {"username": f"s{suffix}a", "full_name": "张三"},
                {"username": f"s{suffix}b", "full_name": "李四"},
            ],
        )
        assert result["created"] == 2
        assert result["merged"] == 0
        assert result["skipped"] == 0
        assert all(
            r["initial_password"] == DEFAULT_STUDENT_PASSWORD for r in result["rows"]
        )

        # 默认密码可登录
        login = client.post(
            "/api/v1/login/access-token",
            data={"username": f"s{suffix}a", "password": DEFAULT_STUDENT_PASSWORD},
        )
        assert login.status_code == 200

        # 名单回显
        roster = client.get(
            "/api/v1/students", params={"classroom_id": classroom_id}, headers=headers
        ).json()
        usernames = {r["username"] for r in roster}
        assert {f"s{suffix}a", f"s{suffix}b"} <= usernames
    finally:
        _cleanup(db, classroom_id, teacher)


def test_import_merges_legacy_anonymous_archive(
    client: TestClient, db: Session
) -> None:
    """同名历史匿名档案自动绑定：XP/档案保留，账号接管（不新建第二条档案）。"""
    teacher, headers = _login_teacher(db, client)
    classroom_id = None
    try:
        classroom_id = uuid.UUID(_new_classroom(client, headers)["id"])
        legacy = Student(
            classroom_id=classroom_id,
            display_name="王五",
            xp=77,
        )
        db.add(legacy)
        db.commit()
        db.refresh(legacy)

        username = f"stu{uuid.uuid4().hex[:8]}"
        result = _import(
            client,
            headers,
            str(classroom_id),
            [{"username": username, "full_name": "王五"}],
        )
        assert result["created"] == 0
        assert result["merged"] == 1
        assert result["rows"][0]["merged_existing"] is True
        assert uuid.UUID(result["rows"][0]["student_id"]) == legacy.id

        db.refresh(legacy)
        assert legacy.user_id is not None
        assert legacy.xp == 77  # 历史激励数据保留
    finally:
        _cleanup(db, classroom_id, teacher)


def test_import_skips_invalid_and_duplicate_rows(
    client: TestClient, db: Session
) -> None:
    """空学号 / 空白字符学号 / 名单内重复 / 已存在学号：逐行报错不中断整批。"""
    teacher, headers = _login_teacher(db, client)
    classroom_id = None
    try:
        classroom_id = uuid.UUID(_new_classroom(client, headers)["id"])
        existing = f"stu{uuid.uuid4().hex[:8]}"
        _import(
            client,
            headers,
            str(classroom_id),
            [{"username": existing, "full_name": "先来的"}],
        )

        dup = f"stu{uuid.uuid4().hex[:8]}"
        result = _import(
            client,
            headers,
            str(classroom_id),
            [
                {"username": "", "full_name": "空学号"},
                {"username": "has space", "full_name": "带空格"},
                {"username": dup, "full_name": "第一个"},
                {"username": dup, "full_name": "第二个"},
                {"username": existing, "full_name": "撞已有"},
                {"username": f"stu{uuid.uuid4().hex[:8]}", "full_name": "正常的"},
            ],
        )
        # dup 第一次出现是正常创建，第二次才报重复：跳过 4 行、创建 2 行
        assert result["skipped"] == 4
        assert result["created"] == 2
        errors = {
            r["username"]: r.get("error") for r in result["rows"] if r.get("error")
        }
        assert errors[""] == "学号为空"
        assert "空白" in errors["has space"]
        assert errors[dup] == "名单内学号重复"
        assert "已存在" in errors[existing]
    finally:
        _cleanup(db, classroom_id, teacher)


def test_import_rejects_oversized_batch(client: TestClient, db: Session) -> None:
    """500 行上限：防超大名单撑爆单事务（每行还有哈希+插入）。"""
    teacher, headers = _login_teacher(db, client)
    classroom_id = None
    try:
        classroom_id = uuid.UUID(_new_classroom(client, headers)["id"])
        lines = [
            {"username": f"bulk{i}{uuid.uuid4().hex[:6]}", "full_name": f"学生{i}"}
            for i in range(501)
        ]
        resp = client.post(
            "/api/v1/students/import",
            json={"classroom_id": str(classroom_id), "lines": lines},
            headers=headers,
        )
        assert resp.status_code == 422
    finally:
        _cleanup(db, classroom_id, teacher)


def test_reset_and_remove_student(client: TestClient, db: Session) -> None:
    """单个重置回默认密码；移出课堂解绑账号但保留档案（可重新导入找回）。"""
    teacher, headers = _login_teacher(db, client)
    classroom_id = None
    try:
        classroom_id = uuid.UUID(_new_classroom(client, headers)["id"])
        username = f"stu{uuid.uuid4().hex[:8]}"
        result = _import(
            client,
            headers,
            str(classroom_id),
            [{"username": username, "full_name": "赵六"}],
        )
        student_id = result["rows"][0]["student_id"]

        # 学生改密后，教师重置 → 回默认密码可登录
        login = client.post(
            "/api/v1/login/access-token",
            data={"username": username, "password": DEFAULT_STUDENT_PASSWORD},
        )
        assert login.status_code == 200
        reset = client.post(
            f"/api/v1/students/{student_id}/reset-password", headers=headers
        )
        assert reset.status_code == 200
        assert reset.json()["new_password"] == DEFAULT_STUDENT_PASSWORD

        # 移出：解绑但档案保留
        removed = client.delete(f"/api/v1/students/{student_id}", headers=headers)
        assert removed.status_code == 200
        row = db.get(Student, uuid.UUID(student_id))
        assert row is not None and row.user_id is None

        # 重新导入（新学号 + 同名）→ 找回同一条档案。
        # 原学号仍存在于账号表，直接重导会被"学号已存在"跳过
        again = _import(
            client,
            headers,
            str(classroom_id),
            [{"username": f"stu{uuid.uuid4().hex[:8]}", "full_name": "赵六"}],
        )
        assert again["merged"] == 1
        assert again["rows"][0]["student_id"] == student_id
    finally:
        _cleanup(db, classroom_id, teacher)
