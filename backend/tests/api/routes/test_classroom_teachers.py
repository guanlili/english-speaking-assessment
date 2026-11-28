"""多老师共管课堂：membership、权限分级、教师团队 API 与清理。"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.security import get_password_hash
from app.models import Classroom, ClassroomTeacher, User


def _make_teacher(db: Session, name: str) -> tuple[User, dict[str, str]]:
    password = "teacherpass123"
    user = User(
        username=f"t{uuid.uuid4().hex[:8]}",
        full_name=name,
        role="teacher",
        hashed_password=get_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, {}


def _login(
    client: TestClient, user: User, password: str = "teacherpass123"
) -> dict[str, str]:
    resp = client.post(
        "/api/v1/login/access-token",
        data={"username": user.username or "", "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_class(
    client: TestClient, headers: dict[str, str], name: str = "共管班"
) -> dict:
    resp = client.post("/api/v1/classes", json={"name": name}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _memberships(db: Session, classroom_id: uuid.UUID) -> list[ClassroomTeacher]:
    return list(
        db.exec(
            select(ClassroomTeacher).where(
                ClassroomTeacher.classroom_id == classroom_id
            )
        ).all()
    )


def test_create_classroom_backfills_owner_membership(
    client: TestClient, db: Session
) -> None:
    owner, _ = _make_teacher(db, "主教师")
    owner_headers = _login(client, owner)
    data = _create_class(client, owner_headers)
    classroom = db.get(Classroom, uuid.UUID(data["id"]))
    assert classroom is not None and classroom.owner_id == owner.id

    members = _memberships(db, classroom.id)
    assert len(members) == 1
    assert members[0].user_id == owner.id
    assert members[0].role == "owner"
    assert members[0].tenant_id == classroom.tenant_id

    listed = client.get("/api/v1/classes", headers=owner_headers).json()
    assert listed[0]["viewer_role"] == "owner"
    assert listed[0]["owner_name"] == "主教师"


def test_co_teacher_gets_membership_and_access_but_not_owner_actions(
    client: TestClient, db: Session
) -> None:
    owner, _ = _make_teacher(db, "主教师")
    co, _ = _make_teacher(db, "共管教师")
    owner_headers = _login(client, owner)
    co_headers = _login(client, co)
    data = _create_class(client, owner_headers)
    classroom_id = uuid.UUID(data["id"])
    code = data["code"]

    added = client.post(
        f"/api/v1/classes/{code}/teachers",
        json={"user_id": str(co.id)},
        headers=owner_headers,
    )
    assert added.status_code == 200, added.text
    assert added.json()["role"] == "co_teacher"
    assert added.json()["is_me"] is False

    # 重复添加幂等：不新增第二行，也不报错。
    again = client.post(
        f"/api/v1/classes/{code}/teachers",
        json={"user_id": str(co.id)},
        headers=owner_headers,
    )
    assert again.status_code == 200
    assert len(_memberships(db, classroom_id)) == 2

    teachers = client.get(f"/api/v1/classes/{code}/teachers", headers=co_headers).json()
    assert {row["role"] for row in teachers} == {"owner", "co_teacher"}

    # 共管教师立即获得名单/课堂读取权限（不依赖缓存）。
    students = client.get(
        f"/api/v1/students?classroom_id={classroom_id}", headers=co_headers
    )
    assert students.status_code == 200, students.text
    listed = client.get("/api/v1/classes", headers=co_headers).json()
    assert listed[0]["viewer_role"] == "co_teacher"
    assert listed[0]["co_teacher_count"] == 1

    # 共管教师不能删课堂、改班容、加教师。
    assert (
        client.delete(f"/api/v1/classes/{code}", headers=co_headers).status_code == 403
    )
    assert (
        client.patch(
            f"/api/v1/classes/{code}",
            json={"class_size": 61},
            headers=co_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/classes/{code}/teachers",
            json={"user_id": str(owner.id)},
            headers=co_headers,
        ).status_code
        == 403
    )


def test_co_teacher_can_leave_but_owner_cannot_be_removed(
    client: TestClient, db: Session
) -> None:
    owner, _ = _make_teacher(db, "主教师")
    co, _ = _make_teacher(db, "共管教师")
    owner_headers = _login(client, owner)
    co_headers = _login(client, co)
    data = _create_class(client, owner_headers)
    classroom_id = uuid.UUID(data["id"])
    code = data["code"]

    client.post(
        f"/api/v1/classes/{code}/teachers",
        json={"user_id": str(co.id)},
        headers=owner_headers,
    )
    assert (
        client.delete(
            f"/api/v1/classes/{code}/teachers/{owner.id}", headers=owner_headers
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/classes/{code}/teachers/{co.id}", headers=co_headers
        ).status_code
        == 200
    )
    assert len(_memberships(db, classroom_id)) == 1
    assert (
        client.get(
            f"/api/v1/students?classroom_id={classroom_id}", headers=co_headers
        ).status_code
        == 403
    )

    # 主教师不能移除自己；删除课堂后 membership 一并清理。
    assert (
        client.delete(
            f"/api/v1/classes/{code}/teachers/{owner.id}", headers=owner_headers
        ).status_code
        == 403
    )
    deleted = client.delete(f"/api/v1/classes/{code}", headers=owner_headers)
    assert deleted.status_code == 200, deleted.text
    assert _memberships(db, classroom_id) == []


def test_add_rejects_student_and_duplicate_owner(
    client: TestClient, db: Session
) -> None:
    owner, _ = _make_teacher(db, "主教师")
    student = User(
        username=f"s{uuid.uuid4().hex[:8]}",
        full_name="学生",
        role="student",
        hashed_password=get_password_hash("studentpass123"),
    )
    db.add(student)
    db.commit()
    owner_headers = _login(client, owner)
    data = _create_class(client, owner_headers)
    code = data["code"]

    bad = client.post(
        f"/api/v1/classes/{code}/teachers",
        json={"user_id": str(student.id)},
        headers=owner_headers,
    )
    assert bad.status_code == 422
    dup_owner = client.post(
        f"/api/v1/classes/{code}/teachers",
        json={"user_id": str(owner.id)},
        headers=owner_headers,
    )
    assert dup_owner.status_code == 200
    assert dup_owner.json()["role"] == "owner"


def test_teacher_candidates_excludes_members(client: TestClient, db: Session) -> None:
    owner, _ = _make_teacher(db, "主教师")
    co, _ = _make_teacher(db, "待加入")
    owner_headers = _login(client, owner)
    data = _create_class(client, owner_headers)
    code = data["code"]
    client.post(
        f"/api/v1/classes/{code}/teachers",
        json={"user_id": str(co.id)},
        headers=owner_headers,
    )
    candidates = client.get(
        f"/api/v1/classes/{code}/teacher-candidates", headers=owner_headers
    ).json()
    ids = {row["id"] for row in candidates}
    assert str(owner.id) not in ids
    assert str(co.id) not in ids


def test_teacher_joins_by_class_code(client: TestClient, db: Session) -> None:
    """存量漏加教师的自助路径：拿课堂码加入，落 co_teacher，重复加入幂等。"""
    owner, _ = _make_teacher(db, "主教师")
    teacher, _ = _make_teacher(db, "未分配教师")
    owner_headers = _login(client, owner)
    teacher_headers = _login(client, teacher)
    data = _create_class(client, owner_headers)
    code = data["code"]
    classroom = db.get(Classroom, uuid.UUID(data["id"]))
    assert classroom is not None

    resp = client.post(f"/api/v1/classes/{code}/teachers/join", headers=teacher_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "co_teacher"

    members = _memberships(db, classroom.id)
    assert {m.user_id for m in members} == {owner.id, teacher.id}
    assert all(m.tenant_id == classroom.tenant_id for m in members)

    # 幂等：再点一次不产生第二行
    again = client.post(
        f"/api/v1/classes/{code}/teachers/join", headers=teacher_headers
    )
    assert again.status_code == 200
    assert len(_memberships(db, classroom.id)) == 2

    # 加入后自己的课堂列表里能看到这个班，且角色是共管
    listed = client.get("/api/v1/classes", headers=teacher_headers).json()
    assert [row["viewer_role"] for row in listed] == ["co_teacher"]


def test_owner_join_returns_owner_and_student_is_rejected(
    client: TestClient, db: Session
) -> None:
    owner, _ = _make_teacher(db, "主教师")
    owner_headers = _login(client, owner)
    code = _create_class(client, owner_headers)["code"]

    resp = client.post(f"/api/v1/classes/{code}/teachers/join", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "owner"

    student = User(
        username=f"s{uuid.uuid4().hex[:8]}",
        full_name="学生",
        role="student",
        hashed_password=get_password_hash("studentpass123"),
    )
    db.add(student)
    db.commit()
    student_headers = _login(client, student, "studentpass123")
    denied = client.post(
        f"/api/v1/classes/{code}/teachers/join", headers=student_headers
    )
    assert denied.status_code in {401, 403}
