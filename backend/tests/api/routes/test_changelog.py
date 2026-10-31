"""平台更新日志：权限门（学生 403 / 教师只读 / 管理员 CRUD）+ 排序与校验。"""

import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app import crud
from app.models import ChangelogEntry, UserCreate
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string


def _purge(db: Session) -> None:
    db.exec(delete(ChangelogEntry))  # type: ignore[call-overload]
    db.commit()


def _post_entry(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = {
        "day": str(date.today()),
        "kind": "feature",
        "title_zh": "新功能",
        "title_en": "New feature",
        "body_zh": "说明",
        "body_en": "Description",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/changelog", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_changelog_permission_gates(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    operator_token_headers: dict[str, str],
    db: Session,
) -> None:
    """未登录 401；学生 403；教师可读不可写；平台运营可写（B3）。"""
    _purge(db)
    assert client.get("/api/v1/changelog").status_code == 401

    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    student = make_student(db, client, classroom["code"], "Ada")
    assert (
        client.get("/api/v1/changelog", headers=student["headers"]).status_code == 403
    )

    teacher_email, teacher_password = random_email(), random_lower_string()
    teacher = crud.create_user(
        session=db,
        user_create=UserCreate(email=teacher_email, password=teacher_password),
    )
    login = client.post(
        "/api/v1/login/access-token",
        data={"username": teacher_email, "password": teacher_password},
    )
    assert login.status_code == 200
    teacher_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # 教师只读：读 200，写 401（B3：学校 token 打平台写路由 → audience 拒绝）
    assert client.get("/api/v1/changelog", headers=teacher_headers).status_code == 200
    assert (
        client.post(
            "/api/v1/changelog",
            json={"day": "2026-10-26", "title_zh": "x", "title_en": "x"},
            headers=teacher_headers,
        ).status_code
        == 401
    )

    # 校级 admin 可读；写归平台运营
    assert (
        client.get("/api/v1/changelog", headers=superuser_token_headers).status_code
        == 200
    )
    assert _post_entry(client, operator_token_headers)["kind"] == "feature"

    # 自清理（共享库规约）：课堂级联学生，教师账号一并删
    from tests.api.routes.test_students import _cleanup

    _cleanup(db, uuid.UUID(classroom["id"]), teacher)
    _purge(db)


def test_changelog_crud_and_ordering(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    operator_token_headers: dict[str, str],
    db: Session,
) -> None:
    _purge(db)
    older = _post_entry(client, operator_token_headers, day="2026-10-01")
    newer = _post_entry(client, operator_token_headers, day="2026-10-26")
    same_day_later = _post_entry(
        client, operator_token_headers, day="2026-10-26", title_zh="后发"
    )

    resp = client.get("/api/v1/changelog", headers=superuser_token_headers)
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    # 按发布日期倒序，同日按创建先后
    assert ids == [same_day_later["id"], newer["id"], older["id"]]

    # 全量更新：改标题、清 kind
    resp = client.put(
        f"/api/v1/changelog/{older['id']}",
        json={
            "day": "2026-10-01",
            "kind": None,
            "title_zh": "改后",
            "title_en": "Updated",
            "body_zh": None,
            "body_en": None,
        },
        headers=operator_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] is None
    assert resp.json()["title_zh"] == "改后"

    # kind 非法值 422
    assert (
        client.post(
            "/api/v1/changelog",
            json={
                "day": "2026-10-26",
                "kind": "bogus",
                "title_zh": "x",
                "title_en": "x",
            },
            headers=operator_token_headers,
        ).status_code
        == 422
    )

    # 部分字段 PUT（缺必填）→ 422 而非数据库约束 500
    assert (
        client.put(
            f"/api/v1/changelog/{same_day_later['id']}",
            json={"kind": "fix"},
            headers=operator_token_headers,
        ).status_code
        == 422
    )

    # 删除 + 再删 404
    assert (
        client.delete(
            f"/api/v1/changelog/{older['id']}", headers=operator_token_headers
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/changelog/{older['id']}", headers=operator_token_headers
        ).status_code
        == 404
    )
    _purge(db)
