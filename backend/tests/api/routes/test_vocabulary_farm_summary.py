"""教师端班级农场聚合摘要（#517 E）后端测试。

口径守点：
- 只读聚合：participants / mature_plots / harvested_total / badge_counts / top_harvesters；
  不改 XP、徽章、streak、plot。
- 地块按登录账号跨班连续；只统计当前在册学生名下地块，跨班地块不重复计入。
- 仅本班教师；学生 403，跨班 404，vocabulary 模块关闭 403。
- 看板 ``vocabulary_farm`` 与独立接口同口径；模块未开通时看板内为 null。
"""

import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.models import (
    BADGE_FARM_FIRST_HARVEST,
    StudentBadge,
    TenantModule,
    UserCreate,
    VocabFarmPlot,
    VocabularyAnswer,
)
from app.services import vocabulary_farm as farm_service
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

FARM_SUMMARY = "/api/v1/classes/{code}/vocabulary/teacher/farm-summary"
BOARD = "/api/v1/classes/{code}/board"


def _login_teacher(db: Session, client: TestClient):
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


def _create_classroom(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post("/api/v1/classes", json={"class_size": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed_plot(db: Session, user_id: uuid.UUID, *, points: int, harvest: int) -> None:
    plot = farm_service._get_or_create_plot(db, user_id)
    plot.growth_points = points
    plot.harvest_count = harvest
    db.add(plot)
    db.commit()
    db.refresh(plot)


def _add_badge(db: Session, student_id: uuid.UUID, key: str) -> None:
    db.add(StudentBadge(student_id=student_id, badge_key=key))
    db.commit()


def _summary(client: TestClient, headers: dict[str, str], code: str):
    resp = client.get(FARM_SUMMARY.format(code=code), headers=headers)
    return resp.status_code, resp.json()


# ── 聚合口径 ──────────────────────────────────────────────────────────


def test_farm_summary_counts_participants_mature_badges_and_top(
    client: TestClient, db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    s1 = make_student(db, client, classroom["code"], "收获达人")
    s2 = make_student(db, client, classroom["code"], "成长中同学")
    make_student(db, client, classroom["code"], "无地块同学")

    _seed_plot(db, s1["user"].id, points=25, harvest=3)
    _seed_plot(db, s2["user"].id, points=12, harvest=0)
    _add_badge(db, uuid.UUID(s1["student"]["id"]), BADGE_FARM_FIRST_HARVEST)
    _add_badge(db, uuid.UUID(s2["student"]["id"]), "streak_3")

    status, summary = _summary(client, headers, classroom["code"])
    assert status == 200, summary
    assert summary["participants"] == 2
    assert summary["mature_plots"] == 1
    assert summary["harvested_total"] == 3

    badge_counts = {b["key"]: b for b in summary["badge_counts"]}
    assert badge_counts[BADGE_FARM_FIRST_HARVEST]["count"] == 1
    assert badge_counts[BADGE_FARM_FIRST_HARVEST]["label"] == "首次收获"
    assert badge_counts["streak_3"]["count"] == 1

    top = summary["top_harvesters"]
    assert len(top) == 1
    assert top[0]["display_name"] == "收获达人"
    assert top[0]["harvest_count"] == 3


def test_farm_summary_isolates_cross_class_plots(
    client: TestClient, db: Session
) -> None:
    teacher_a, headers_a = _login_teacher(db, client)
    room_a = _create_classroom(client, headers_a)
    teacher_b, headers_b = _login_teacher(db, client)
    room_b = _create_classroom(client, headers_b)

    s_a = make_student(db, client, room_a["code"], "A班同学")
    s_b = make_student(db, client, room_b["code"], "B班同学")
    _seed_plot(db, s_a["user"].id, points=25, harvest=2)
    _seed_plot(db, s_b["user"].id, points=25, harvest=5)

    status_a, summary_a = _summary(client, headers_a, room_a["code"])
    assert status_a == 200, summary_a
    assert summary_a["participants"] == 1
    assert summary_a["harvested_total"] == 2
    assert summary_a["top_harvesters"][0]["display_name"] == "A班同学"

    status_b, summary_b = _summary(client, headers_b, room_b["code"])
    assert status_b == 200, summary_b
    assert summary_b["participants"] == 1
    assert summary_b["harvested_total"] == 5


def test_farm_summary_empty_classroom(client: TestClient, db: Session) -> None:
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    status, summary = _summary(client, headers, classroom["code"])
    assert status == 200, summary
    assert summary == {
        "participants": 0,
        "mature_plots": 0,
        "harvested_total": 0,
        "badge_counts": [],
        "top_harvesters": [],
    }


# ── 权限 ──────────────────────────────────────────────────────────────


def test_farm_summary_student_forbidden(client: TestClient, db: Session) -> None:
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"], "学生")
    status, body = _summary(client, student["headers"], classroom["code"])
    assert status == 403, body


def test_farm_summary_non_teacher_and_unknown_classroom(
    client: TestClient, db: Session
) -> None:
    _teacher_a, headers_a = _login_teacher(db, client)
    room_a = _create_classroom(client, headers_a)
    _teacher_b, headers_b = _login_teacher(db, client)
    room_b = _create_classroom(client, headers_b)
    outsider = make_student(db, client, room_b["code"], "外班同学")

    # 非本班教师/外班学生 → 403（教师路由既有口径）；课堂不存在 → 404
    status, _ = _summary(client, outsider["headers"], room_a["code"])
    assert status == 403
    status, _ = _summary(client, headers_b, room_a["code"])
    assert status == 403
    status, _ = _summary(client, headers_a, "NOPE404")
    assert status == 404


def test_farm_summary_module_disabled_403(client: TestClient, db: Session) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)

    module_rows = list(
        db.exec(
            select(TenantModule).where(
                TenantModule.tenant_id == teacher.tenant_id,  # type: ignore[arg-type]
                TenantModule.module_key == "vocabulary",
            )
        ).all()
    )
    for row in module_rows:
        row.enabled = False
    db.commit()
    try:
        status, body = _summary(client, headers, classroom["code"])
        assert status == 403, body
        assert "module_not_enabled" in body["detail"]
    finally:
        for row in module_rows:
            row.enabled = True
        db.commit()


# ── 看板内嵌摘要 + 口径分离 ───────────────────────────────────────────


def test_board_farm_summary_same_as_standalone(client: TestClient, db: Session) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    answers_before = len(db.exec(select(VocabularyAnswer)).all())
    s1 = make_student(db, client, classroom["code"], "看板收获家")
    s2 = make_student(db, client, classroom["code"], "看板新苗")
    _seed_plot(db, s1["user"].id, points=20, harvest=2)
    _seed_plot(db, s2["user"].id, points=5, harvest=0)
    _add_badge(db, uuid.UUID(s1["student"]["id"]), BADGE_FARM_FIRST_HARVEST)

    status, standalone = _summary(client, headers, classroom["code"])
    assert status == 200, standalone

    resp = client.get(BOARD.format(code=classroom["code"]), headers=headers)
    assert resp.status_code == 200, resp.text
    board = resp.json()
    farm = board["vocabulary_farm"]
    assert farm is not None
    assert farm["participants"] == standalone["participants"] == 2
    assert farm["mature_plots"] == standalone["mature_plots"] == 1
    assert farm["harvested_total"] == standalone["harvested_total"] == 2
    assert farm["badge_counts"] == standalone["badge_counts"]
    assert farm["top_harvesters"] == standalone["top_harvesters"]

    # 农场聚合不产生任务作答，也不改看板既有提交口径
    answers_after = len(db.exec(select(VocabularyAnswer)).all())
    assert answers_after == answers_before
    assert board["submitted_count"] == 0
    assert board["completed_count"] == 0


def test_board_farm_summary_null_when_module_disabled(
    client: TestClient, db: Session
) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"], "关闭模块同学")
    _seed_plot(db, student["user"].id, points=25, harvest=1)

    module_rows = list(
        db.exec(
            select(TenantModule).where(
                TenantModule.tenant_id == teacher.tenant_id,  # type: ignore[arg-type]
                TenantModule.module_key == "vocabulary",
            )
        ).all()
    )
    for row in module_rows:
        row.enabled = False
    db.commit()
    try:
        resp = client.get(BOARD.format(code=classroom["code"]), headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["vocabulary_farm"] is None
        assert resp.json()["vocabulary_pk"] is None
    finally:
        for row in module_rows:
            row.enabled = True
        db.commit()


def test_farm_summary_does_not_mutate_plots(client: TestClient, db: Session) -> None:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"], "只读同学")
    _seed_plot(db, student["user"].id, points=12, harvest=0)

    status, _ = _summary(client, headers, classroom["code"])
    assert status == 200
    plot = db.exec(
        select(VocabFarmPlot).where(VocabFarmPlot.user_id == student["user"].id)  # type: ignore[arg-type]
    ).first()
    assert plot is not None
    assert plot.growth_points == 12
    assert plot.harvest_count == 0
