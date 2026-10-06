"""students 路由测试：批量导入（含历史匿名档案绑定、多班归属）、重置、移出、名单。

此前该模块覆盖率全项目最低（46%）：导入与「同名历史档案自动绑定」是
数据迁移型逻辑，绑错会把学生 XP/作答历史挂到错误账号。
多班归属（2026-10）：学号已存在且同名 → 加入本班；异名阻断；不重置密码；
移出后重导入按孤儿档案找回。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

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
    """空学号 / 空白字符学号 / 名单内重复 / 已存在学号异名：逐行报错不中断整批。"""
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
        # 已存在学号 + 异名：冲突阻断（多班归属只放行同名）
        assert "已存在" in errors[existing] and "姓名" in errors[existing]
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


# ── 多班归属（2026-10）：一个账号可被不同教师分别导入各自班级 ────────────


def test_same_student_id_imported_by_two_teachers_joins_existing_account(
    client: TestClient, db: Session
) -> None:
    """同一学号被两位教师分别导入各自班级：只建一个账号，各班一份档案。"""
    teacher_a, headers_a = _login_teacher(db, client)
    teacher_b, headers_b = _login_teacher(db, client)
    classroom_a_id = classroom_b_id = None
    try:
        classroom_a_id = uuid.UUID(_new_classroom(client, headers_a)["id"])
        classroom_b_id = uuid.UUID(_new_classroom(client, headers_b)["id"])
        username = f"stu{uuid.uuid4().hex[:8]}"

        first = _import(
            client,
            headers_a,
            str(classroom_a_id),
            [{"username": username, "full_name": "张三"}],
        )
        assert first["created"] == 1

        second = _import(
            client,
            headers_b,
            str(classroom_b_id),
            [{"username": username, "full_name": "张三"}],
        )
        # 不再跳过：姓名一致即同一学生，加入本班；密码不重置（无初始密码下发）
        assert second["joined"] == 1
        assert second["created"] == 0
        assert second["skipped"] == 0
        row = second["rows"][0]
        assert row["status"] == "joined_existing"
        assert row["initial_password"] is None
        assert row["student_id"] not in (None, first["rows"][0]["student_id"])

        # 只有一个账号
        users = db.exec(
            select(User).where(col(User.username) == username)  # type: ignore[arg-type]
        ).all()
        assert len(users) == 1

        # 两个班各一份档案，绑同一账号
        profiles = db.exec(
            select(Student).where(col(Student.user_id) == users[0].id)  # type: ignore[arg-type]
        ).all()
        assert {str(p.classroom_id) for p in profiles} == {
            str(classroom_a_id),
            str(classroom_b_id),
        }

        # B 班花名册可见该学生
        roster = client.get(
            "/api/v1/students",
            params={"classroom_id": classroom_b_id},
            headers=headers_b,
        ).json()
        assert any(r["username"] == username for r in roster)
    finally:
        _cleanup(db, classroom_a_id, teacher_a, teacher_b)
        _cleanup(db, classroom_b_id)


def test_import_same_id_different_name_blocked(client: TestClient, db: Session) -> None:
    """学号相同但姓名不同：冲突阻断，不加入本班（验收红线）。"""
    teacher_a, headers_a = _login_teacher(db, client)
    teacher_b, headers_b = _login_teacher(db, client)
    classroom_a_id = classroom_b_id = None
    try:
        classroom_a_id = uuid.UUID(_new_classroom(client, headers_a)["id"])
        classroom_b_id = uuid.UUID(_new_classroom(client, headers_b)["id"])
        username = f"stu{uuid.uuid4().hex[:8]}"
        _import(
            client,
            headers_a,
            str(classroom_a_id),
            [{"username": username, "full_name": "张三"}],
        )

        result = _import(
            client,
            headers_b,
            str(classroom_b_id),
            [{"username": username, "full_name": "李四"}],
        )
        assert result["skipped"] == 1
        assert result["joined"] == 0
        assert "姓名" in result["rows"][0]["error"]

        roster = client.get(
            "/api/v1/students",
            params={"classroom_id": classroom_b_id},
            headers=headers_b,
        ).json()
        assert roster == []
    finally:
        _cleanup(db, classroom_a_id, teacher_a, teacher_b)
        _cleanup(db, classroom_b_id)


def test_join_existing_account_keeps_password(client: TestClient, db: Session) -> None:
    """加入本班不重置密码：学生在 A 班改过密码，被导入 B 班后新密码仍有效。"""
    teacher_a, headers_a = _login_teacher(db, client)
    teacher_b, headers_b = _login_teacher(db, client)
    classroom_a_id = classroom_b_id = None
    try:
        classroom_a_id = uuid.UUID(_new_classroom(client, headers_a)["id"])
        classroom_b_id = uuid.UUID(_new_classroom(client, headers_b)["id"])
        username = f"stu{uuid.uuid4().hex[:8]}"
        _import(
            client,
            headers_a,
            str(classroom_a_id),
            [{"username": username, "full_name": "张三"}],
        )

        # 学生自己改密
        login = client.post(
            "/api/v1/login/access-token",
            data={"username": username, "password": DEFAULT_STUDENT_PASSWORD},
        )
        assert login.status_code == 200
        new_password = random_lower_string()
        change = client.patch(
            "/api/v1/users/me/password",
            json={
                "current_password": DEFAULT_STUDENT_PASSWORD,
                "new_password": new_password,
            },
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert change.status_code == 200, change.text

        # B 班教师导入同名学号 → 加入本班，密码不动
        result = _import(
            client,
            headers_b,
            str(classroom_b_id),
            [{"username": username, "full_name": "张三"}],
        )
        assert result["joined"] == 1

        login_old = client.post(
            "/api/v1/login/access-token",
            data={"username": username, "password": DEFAULT_STUDENT_PASSWORD},
        )
        assert login_old.status_code == 400
        login_new = client.post(
            "/api/v1/login/access-token",
            data={"username": username, "password": new_password},
        )
        assert login_new.status_code == 200
    finally:
        _cleanup(db, classroom_a_id, teacher_a, teacher_b)
        _cleanup(db, classroom_b_id)


def test_remove_then_reimport_same_id_rebinds_orphan_profile(
    client: TestClient, db: Session
) -> None:
    """移出后用原学号重导入：孤儿档案找回归位（XP 保留），不新建档案。"""
    teacher, headers = _login_teacher(db, client)
    classroom_id = None
    try:
        classroom_id = uuid.UUID(_new_classroom(client, headers)["id"])
        username = f"stu{uuid.uuid4().hex[:8]}"
        result = _import(
            client,
            headers,
            str(classroom_id),
            [{"username": username, "full_name": "张三"}],
        )
        student_id = uuid.UUID(result["rows"][0]["student_id"])
        profile = db.get(Student, student_id)
        assert profile is not None
        profile.xp = 66
        db.add(profile)
        db.commit()

        removed = client.delete(f"/api/v1/students/{student_id}", headers=headers)
        assert removed.status_code == 200

        # 原学号重导入：账号仍在，按孤儿同名档案找回，历史 XP 不丢
        again = _import(
            client,
            headers,
            str(classroom_id),
            [{"username": username, "full_name": "张三"}],
        )
        assert again["joined"] == 1
        assert again["rows"][0]["student_id"] == str(student_id)
        assert again["rows"][0]["initial_password"] is None

        rebound = db.get(Student, student_id)
        assert rebound is not None and rebound.user_id is not None
        assert rebound.xp == 66

        # 班内仍只有一份该学生档案
        roster = client.get(
            "/api/v1/students", params={"classroom_id": classroom_id}, headers=headers
        ).json()
        assert sum(1 for r in roster if r["username"] == username) == 1
    finally:
        _cleanup(db, classroom_id, teacher)


def test_import_already_enrolled_is_idempotent(client: TestClient, db: Session) -> None:
    """同一名单重复导入：已在班内的行幂等成功，不重复建档案、不算跳过。"""
    teacher, headers = _login_teacher(db, client)
    classroom_id = None
    try:
        classroom_id = uuid.UUID(_new_classroom(client, headers)["id"])
        username = f"stu{uuid.uuid4().hex[:8]}"
        _import(
            client,
            headers,
            str(classroom_id),
            [{"username": username, "full_name": "张三"}],
        )
        again = _import(
            client,
            headers,
            str(classroom_id),
            [{"username": username, "full_name": "张三"}],
        )
        assert again["already_enrolled"] == 1
        assert again["skipped"] == 0
        assert again["rows"][0]["status"] == "already_enrolled"

        roster = client.get(
            "/api/v1/students", params={"classroom_id": classroom_id}, headers=headers
        ).json()
        assert sum(1 for r in roster if r["username"] == username) == 1
    finally:
        _cleanup(db, classroom_id, teacher)


def test_class_size_cap_blocks_import_and_self_join(
    client: TestClient, db: Session
) -> None:
    """班级人数上限（class_size）：导入超额行报错；课堂码自加入满员 409。"""
    teacher, headers = _login_teacher(db, client)
    classroom_id = None
    student_user: User | None = None
    try:
        created = client.post(
            "/api/v1/classes", json={"class_size": 1}, headers=headers
        )
        assert created.status_code == 200, created.text
        classroom = created.json()
        classroom_id = uuid.UUID(classroom["id"])

        first = f"stu{uuid.uuid4().hex[:8]}"
        result = _import(
            client,
            headers,
            str(classroom_id),
            [{"username": first, "full_name": "张三"}],
        )
        assert result["created"] == 1

        # 导入第二人：满员报错
        second = f"stu{uuid.uuid4().hex[:8]}"
        over = _import(
            client,
            headers,
            str(classroom_id),
            [{"username": second, "full_name": "李四"}],
        )
        assert over["created"] == 0
        assert over["skipped"] == 1
        assert "班级人数已满" in (over["rows"][0]["error"] or "")

        # 课堂码自加入：满员 409（detail 稳定标识，前端做双语映射）
        student_password = random_lower_string()
        student_user = crud.create_user(
            session=db,
            user_create=UserCreate(
                email=random_email(),
                password=student_password,
                full_name="王五",
                role="student",
            ),
        )
        login = client.post(
            "/api/v1/login/access-token",
            data={"username": student_user.email, "password": student_password},
        )
        assert login.status_code == 200
        join = client.post(
            f"/api/v1/classes/{classroom['code']}/join",
            json={},
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert join.status_code == 409
        assert "班级人数已满" in join.json()["detail"]

        # 已在班内不受容量限制（幂等返回）
        first_profile = db.exec(
            select(Student).where(
                Student.classroom_id == classroom_id,  # type: ignore[arg-type]
                col(Student.display_name) == "张三",  # type: ignore[arg-type]
            )
        ).first()
        assert first_profile is not None and first_profile.user_id is not None
        first_login = client.post(
            "/api/v1/login/access-token",
            data={
                "username": db.get(User, first_profile.user_id).username,  # type: ignore[arg-type]
                "password": DEFAULT_STUDENT_PASSWORD,
            },
        )
        assert first_login.status_code == 200
        rejoin = client.post(
            f"/api/v1/classes/{classroom['code']}/join",
            json={},
            headers={"Authorization": f"Bearer {first_login.json()['access_token']}"},
        )
        assert rejoin.status_code == 200

        # 移出产生孤儿档案后：同名新学号导入按档案找回，不占容量
        removed = client.delete(f"/api/v1/students/{first_profile.id}", headers=headers)
        assert removed.status_code == 200
        merged_in = _import(
            client,
            headers,
            str(classroom_id),
            [{"username": f"stu{uuid.uuid4().hex[:8]}", "full_name": "张三"}],
        )
        assert merged_in["merged"] == 1
        assert merged_in["created"] == 0
    finally:
        _cleanup(db, classroom_id, teacher)
        if student_user is not None:
            row = db.get(User, student_user.id)
            if row is not None:
                db.delete(row)
                db.commit()


def test_my_enrollments_lists_all_classes(client: TestClient, db: Session) -> None:
    """GET /students/me/classrooms：返回学生加入的全部在用班级及班内成长数据。"""
    teacher_a, headers_a = _login_teacher(db, client)
    teacher_b, headers_b = _login_teacher(db, client)
    classroom_a_id = classroom_b_id = None
    try:
        classroom_a = _new_classroom(client, headers_a)
        classroom_b = _new_classroom(client, headers_b)
        classroom_a_id = uuid.UUID(classroom_a["id"])
        classroom_b_id = uuid.UUID(classroom_b["id"])
        username = f"stu{uuid.uuid4().hex[:8]}"
        first = _import(
            client,
            headers_a,
            str(classroom_a_id),
            [{"username": username, "full_name": "张三"}],
        )
        _import(
            client,
            headers_b,
            str(classroom_b_id),
            [{"username": username, "full_name": "张三"}],
        )
        profile = db.get(Student, uuid.UUID(first["rows"][0]["student_id"]))
        assert profile is not None
        profile.xp = 120
        profile.streak_days = 4
        db.add(profile)
        db.commit()

        login = client.post(
            "/api/v1/login/access-token",
            data={"username": username, "password": DEFAULT_STUDENT_PASSWORD},
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        my_classes = client.get("/api/v1/students/me/classrooms", headers=headers)
        assert my_classes.status_code == 200, my_classes.text
        items = my_classes.json()
        assert {c["code"] for c in items} == {classroom_a["code"], classroom_b["code"]}
        a_item = next(
            c for c in items if uuid.UUID(c["classroom_id"]) == classroom_a_id
        )
        assert a_item["xp"] == 120
        assert a_item["streak_days"] == 4
        assert a_item["display_name"] == "张三"
        assert a_item["has_published_task"] is False
    finally:
        _cleanup(db, classroom_a_id, teacher_a, teacher_b)
        _cleanup(db, classroom_b_id)


def test_my_enrollments_requires_student_role(client: TestClient, db: Session) -> None:
    """教师 token 访问 /students/me/classrooms：403（学生专属入口）。"""
    teacher, headers = _login_teacher(db, client)
    resp = client.get("/api/v1/students/me/classrooms", headers=headers)
    assert resp.status_code == 403
