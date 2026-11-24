"""#517 B 部分：按租户按天用量聚合 API 测试。

覆盖：跨租户隔离、每日补零与本地日界、9 项指标计数与去重口径、空数据全 0、
非法范围 422 / 404、非平台运营 401、CSV BOM/表头/无明细泄漏、7/30 天汇总与
daily 一致、农场下限口径在 limitations 披露。

造数尽量直插模型，不走业务流程；只保留聚合数，断言不回读学生明细。
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import (
    Classroom,
    ClassroomExercise,
    ExportAudit,
    Student,
    Tenant,
    User,
    VocabFarmPlot,
    VocabPkLobby,
    VocabPkMatch,
    VocabPlacementResult,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyContentReviewAudit,
    VocabularySession,
)

TZ = ZoneInfo("Asia/Shanghai")
API = settings.API_V1_STR
METRIC_KEYS = (
    "active_teachers",
    "active_students",
    "vocab_answers",
    "published_tasks",
    "completed_students",
    "pk_matches",
    "farm_harvests",
    "placement_tests",
    "exports",
)


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _utc(day: date, hour: int, minute: int = 0) -> datetime:
    """本地自然日时刻转 UTC（日界按租户时区）。"""
    return datetime.combine(
        day, datetime.min.time().replace(hour=hour, minute=minute), tzinfo=TZ
    ).astimezone(UTC)


def _mk_tenant(db: Session, tz: str = "Asia/Shanghai") -> Tenant:
    row = Tenant(slug=f"usage-{_uid()}", name_zh="用量校", timezone=tz)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_user(db: Session, tenant_id: uuid.UUID, role: str) -> User:
    user = User(
        username=f"u{_uid()}",
        email=f"{role}-{_uid()}@example.com",
        hashed_password=get_password_hash("Passw0rd!2026"),
        role=role,
        tenant_id=tenant_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _mk_classroom(db: Session, tenant: Tenant, owner_id: uuid.UUID) -> Classroom:
    classroom = Classroom(
        code=f"U{_uid()[:8].upper()}",
        tenant_id=tenant.id,
        class_size=30,
        owner_id=owner_id,
    )
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return classroom


def _mk_student(
    db: Session, tenant: Tenant, classroom: Classroom
) -> tuple[User, Student]:
    user = _mk_user(db, tenant.id, "student")
    profile = Student(
        classroom_id=classroom.id,
        user_id=user.id,
        display_name="测试学生",
        tenant_id=tenant.id,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return user, profile


def _seed_usage(
    db: Session,
    *,
    tenant: Tenant,
    classroom: Classroom,
    teacher: User,
    student_profile: Student,
    student_user: User,
    day: date,
    answers: int = 2,
) -> None:
    """在指定本地日落九类指标样本（教师三类操作同人 → 去重 1）。"""
    ts = _utc(day, 10)

    assignment = VocabularyAssignment(
        tenant_id=tenant.id,
        classroom_id=classroom.id,
        created_by=teacher.id,
        published_at=ts,
        snapshot_items=[{"headword": "dog"}],
        prompt_types=["meaning"],
        version_no=1,
        title="词汇任务",
    )
    db.add(assignment)
    db.flush()

    db.add(
        ClassroomExercise(
            tenant_id=tenant.id,
            classroom_id=classroom.id,
            created_by=teacher.id,
            published_at=ts,
            snapshot_items=[],
            version_no=1,
        )
    )
    db.add(
        VocabularyContentReviewAudit(
            tenant_id=tenant.id,
            word_id=uuid.uuid4(),
            headword="dog",
            actor_id=teacher.id,
            action="approve",
            created_at=ts,
        )
    )

    session = VocabularySession(
        tenant_id=tenant.id,
        classroom_id=classroom.id,
        student_id=student_profile.id,
        assignment_id=assignment.id,
        kind="task",
        status="submitted",
        submitted_at=ts,
        round_no=1,
    )
    db.add(session)
    db.flush()

    for item_index in range(answers):
        db.add(
            VocabularyAnswer(
                tenant_id=tenant.id,
                session_id=session.id,
                item_index=item_index,
                attempt_no=1,
                prompt_type="meaning",
                answer_raw="dog",
                answer_normalized="dog",
                is_correct=True,
                word_id=uuid.uuid4(),
                headword="dog",
                meaning_zh="狗",
                answered_at=ts,
            )
        )

    lobby = VocabPkLobby(
        tenant_id=tenant.id,
        classroom_id=classroom.id,
        created_by=teacher.id,
        snapshot_items=[],
        prompt_types=["meaning"],
        question_count=8,
        per_question_seconds=20,
    )
    db.add(lobby)
    db.flush()
    db.add(
        VocabPkMatch(
            tenant_id=tenant.id,
            lobby_id=lobby.id,
            classroom_id=classroom.id,
            snapshot_items=[],
            question_count=8,
            per_question_seconds=20,
            started_at=ts,
        )
    )

    db.add(
        VocabFarmPlot(
            tenant_id=tenant.id,
            user_id=student_user.id,
            harvest_count=2,
            last_harvested_at=ts,
        )
    )
    db.add(
        VocabPlacementResult(
            tenant_id=tenant.id,
            classroom_id=classroom.id,
            student_id=student_profile.id,
            recommended_band="PET",
            question_count=12,
            answered_count=10,
            correct_count=6,
            submitted_at=ts,
        )
    )
    # create 计入导出次数；download 不计
    db.add(
        ExportAudit(
            tenant_id=tenant.id,
            actor_user_id=teacher.id,
            action="create",
            created_at=ts,
        )
    )
    db.add(
        ExportAudit(
            tenant_id=tenant.id,
            actor_user_id=teacher.id,
            action="download",
            created_at=ts,
        )
    )
    db.commit()


def _cleanup(db: Session, tenant_ids: list[uuid.UUID]) -> None:
    for model in (
        VocabPkMatch,
        VocabPkLobby,
        VocabularyAnswer,
        VocabularySession,
        VocabularyAssignment,
        ClassroomExercise,
        VocabularyContentReviewAudit,
        VocabFarmPlot,
        VocabPlacementResult,
        ExportAudit,
        Student,
        Classroom,
    ):
        db.exec(delete(model).where(col(model.tenant_id).in_(tenant_ids)))  # type: ignore[attr-defined]
    db.exec(delete(User).where(col(User.tenant_id).in_(tenant_ids)))
    db.exec(delete(Tenant).where(col(Tenant.id).in_(tenant_ids)))
    db.commit()


def _day_row(body: dict, day: str) -> dict:
    return next(row for row in body["days"] if row["date"] == day)


def test_aggregates_all_nine_metrics(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    tenant = _mk_tenant(db)
    teacher = _mk_user(db, tenant.id, "teacher")
    classroom = _mk_classroom(db, tenant, teacher.id)
    student_user, student_profile = _mk_student(db, tenant, classroom)
    _seed_usage(
        db,
        tenant=tenant,
        classroom=classroom,
        teacher=teacher,
        student_profile=student_profile,
        student_user=student_user,
        day=yesterday,
        answers=2,
    )

    try:
        resp = client.get(
            f"{API}/admin/tenants/{tenant.id}/usage",
            params={"from": yesterday.isoformat(), "to": yesterday.isoformat()},
            headers=operator_token_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["tenant_id"] == str(tenant.id)
        assert body["timezone"] == "Asia/Shanghai"
        row = _day_row(body, yesterday.isoformat())
        # 同人三类教学操作去重 1；同生两答去重 1；导出只计 create
        expected = {
            "active_teachers": 1,
            "active_students": 1,
            "vocab_answers": 2,
            "published_tasks": 1,
            "completed_students": 1,
            "pk_matches": 1,
            "farm_harvests": 1,
            "placement_tests": 1,
            "exports": 1,
        }
        for key, value in expected.items():
            assert row[key] == value, (key, row[key])
        assert body["totals"] == expected

        # 限制说明：登录缺口 + 农场地下限都必须显式披露
        joined = " ".join(body["limitations"])
        assert "登录" in joined and "last_login_at" in joined
        assert "下限" in joined and "last_harvested_at" in joined

        # 不泄漏学生标识
        raw = resp.text
        assert str(student_profile.id) not in raw
        assert str(student_user.id) not in raw
        assert student_user.username not in raw
    finally:
        _cleanup(db, [tenant.id])


def test_cross_tenant_isolation(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    yesterday = datetime.now(TZ).date() - timedelta(days=1)

    tenant_a = _mk_tenant(db)
    teacher_a = _mk_user(db, tenant_a.id, "teacher")
    room_a = _mk_classroom(db, tenant_a, teacher_a.id)
    user_a, profile_a = _mk_student(db, tenant_a, room_a)
    _seed_usage(
        db,
        tenant=tenant_a,
        classroom=room_a,
        teacher=teacher_a,
        student_profile=profile_a,
        student_user=user_a,
        day=yesterday,
        answers=2,
    )

    tenant_b = _mk_tenant(db)
    teacher_b = _mk_user(db, tenant_b.id, "teacher")
    room_b = _mk_classroom(db, tenant_b, teacher_b.id)
    user_b, profile_b = _mk_student(db, tenant_b, room_b)
    _seed_usage(
        db,
        tenant=tenant_b,
        classroom=room_b,
        teacher=teacher_b,
        student_profile=profile_b,
        student_user=user_b,
        day=yesterday,
        answers=1,
    )

    try:
        resp_a = client.get(
            f"{API}/admin/tenants/{tenant_a.id}/usage",
            params={"from": yesterday.isoformat(), "to": yesterday.isoformat()},
            headers=operator_token_headers,
        )
        body_a = resp_a.json()
        row_a = _day_row(body_a, yesterday.isoformat())
        # A 校两答一学生；不计入 B 校任何行
        assert row_a["active_students"] == 1
        assert row_a["vocab_answers"] == 2
        assert str(profile_b.id) not in resp_a.text

        resp_b = client.get(
            f"{API}/admin/tenants/{tenant_b.id}/usage",
            params={"from": yesterday.isoformat(), "to": yesterday.isoformat()},
            headers=operator_token_headers,
        )
        body_b = resp_b.json()
        row_b = _day_row(body_b, yesterday.isoformat())
        assert row_b["active_students"] == 1
        assert row_b["vocab_answers"] == 1
        assert str(profile_a.id) not in resp_b.text
    finally:
        _cleanup(db, [tenant_a.id, tenant_b.id])


def test_zero_fill_and_local_day_boundary(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    today = datetime.now(TZ).date()
    day_d = today - timedelta(days=2)
    day_prev = day_d - timedelta(days=1)

    tenant = _mk_tenant(db)
    teacher = _mk_user(db, tenant.id, "teacher")
    classroom = _mk_classroom(db, tenant, teacher.id)
    student_user, student_profile = _mk_student(db, tenant, classroom)

    # 本地 D 00:30（UTC D-1 16:30）→ 落在本地 D
    early = datetime.combine(
        day_d, datetime.min.time().replace(hour=0, minute=30), tzinfo=TZ
    )
    # 本地 D-1 23:59（UTC D-1 15:59）→ 落在本地 D-1
    late_prev = datetime.combine(
        day_prev, datetime.min.time().replace(hour=23, minute=59), tzinfo=TZ
    )

    for when in (early, late_prev):
        session = VocabularySession(
            tenant_id=tenant.id,
            classroom_id=classroom.id,
            student_id=student_profile.id,
            kind="task",
            status="in_progress",
            submitted_at=None,
            round_no=1,
        )
        db.add(session)
        db.flush()
        db.add(
            VocabularyAnswer(
                tenant_id=tenant.id,
                session_id=session.id,
                item_index=0,
                attempt_no=1,
                prompt_type="meaning",
                answer_raw="dog",
                answer_normalized="dog",
                is_correct=True,
                word_id=uuid.uuid4(),
                headword="dog",
                meaning_zh="狗",
                answered_at=when.astimezone(UTC),
            )
        )
    db.commit()

    try:
        resp = client.get(
            f"{API}/admin/tenants/{tenant.id}/usage",
            params={"from": day_prev.isoformat(), "to": day_d.isoformat()},
            headers=operator_token_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 范围内两天，逐日补零无缺日
        assert [row["date"] for row in body["days"]] == [
            day_prev.isoformat(),
            day_d.isoformat(),
        ]
        row_prev = _day_row(body, day_prev.isoformat())
        row_d = _day_row(body, day_d.isoformat())
        assert row_prev["vocab_answers"] == 1
        assert row_d["vocab_answers"] == 1
        # 边界时刻：UTC 16:30 归本地次日，15:59 归本地当日
        assert row_prev["active_students"] == 1
        assert row_d["active_students"] == 1
        # 其余指标无数据补零
        for key in (
            "published_tasks",
            "completed_students",
            "pk_matches",
            "farm_harvests",
            "placement_tests",
            "exports",
            "active_teachers",
        ):
            assert row_prev[key] == 0
            assert row_d[key] == 0
    finally:
        _cleanup(db, [tenant.id])


def test_empty_tenant_all_zero(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    today = datetime.now(TZ).date()
    tenant = _mk_tenant(db)
    try:
        resp = client.get(
            f"{API}/admin/tenants/{tenant.id}/usage",
            params={
                "from": (today - timedelta(days=1)).isoformat(),
                "to": today.isoformat(),
            },
            headers=operator_token_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["days"]) == 2
        for row in body["days"]:
            for key in METRIC_KEYS:
                assert row[key] == 0
        for key in METRIC_KEYS:
            assert body["totals"][key] == 0
    finally:
        _cleanup(db, [tenant.id])


def test_invalid_ranges_return_422(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    tenant = _mk_tenant(db)
    try:
        # from > to
        resp = client.get(
            f"{API}/admin/tenants/{tenant.id}/usage",
            params={"from": "2026-11-24", "to": "2026-11-01"},
            headers=operator_token_headers,
        )
        assert resp.status_code == 422

        # 非法日期
        resp = client.get(
            f"{API}/admin/tenants/{tenant.id}/usage",
            params={"from": "not-a-date", "to": "2026-11-24"},
            headers=operator_token_headers,
        )
        assert resp.status_code == 422

        # 范围超 366 天
        resp = client.get(
            f"{API}/admin/tenants/{tenant.id}/usage",
            params={"from": "2025-01-01", "to": "2026-11-24"},
            headers=operator_token_headers,
        )
        assert resp.status_code == 422
    finally:
        _cleanup(db, [tenant.id])


def test_tenant_not_found_404(
    client: TestClient, operator_token_headers: dict[str, str]
) -> None:
    resp = client.get(
        f"{API}/admin/tenants/{uuid.uuid4()}/usage",
        headers=operator_token_headers,
    )
    assert resp.status_code == 404


def test_requires_platform_operator(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    tenant = _mk_tenant(db)
    try:
        # 匿名 → 401
        resp = client.get(f"{API}/admin/tenants/{tenant.id}/usage")
        assert resp.status_code == 401

        # 学校用户 token → 401（audience 不符，平台路由拒收）
        resp = client.get(
            f"{API}/admin/tenants/{tenant.id}/usage",
            headers=superuser_token_headers,
        )
        assert resp.status_code == 401
    finally:
        _cleanup(db, [tenant.id])


def test_csv_export_shape_and_no_leak(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    tenant = _mk_tenant(db)
    teacher = _mk_user(db, tenant.id, "teacher")
    classroom = _mk_classroom(db, tenant, teacher.id)
    student_user, student_profile = _mk_student(db, tenant, classroom)
    _seed_usage(
        db,
        tenant=tenant,
        classroom=classroom,
        teacher=teacher,
        student_profile=student_profile,
        student_user=student_user,
        day=yesterday,
        answers=2,
    )

    try:
        resp = client.get(
            f"{API}/admin/tenants/{tenant.id}/usage.csv",
            params={"from": yesterday.isoformat(), "to": yesterday.isoformat()},
            headers=operator_token_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "text/csv; charset=utf-8"
        # UTF-8 BOM
        assert resp.content[:3] == b"\xef\xbb\xbf"
        disposition = resp.headers["Content-Disposition"]
        assert (
            f"tenant-{tenant.slug}-usage-{yesterday.isoformat()}-{yesterday.isoformat()}.csv"
            in disposition
        )

        text = resp.content.decode("utf-8-sig")
        lines = [line for line in text.splitlines() if line.strip()]
        assert len(lines) == 2  # 表头 + 一行数据
        header = lines[0].split(",")
        assert header == [
            "日期",
            "活跃教师数",
            "活跃学生数",
            "词汇作答数",
            "发布任务数",
            "完成任务人数",
            "PK 对局数",
            "农场收获数（下限）",
            "placement 测试数",
            "导出次数",
        ]
        row = lines[1].split(",")
        assert row[0] == yesterday.isoformat()
        # 9 项聚合数：1,1,2,1,1,1,1,1,1
        assert row[1:] == ["1", "1", "2", "1", "1", "1", "1", "1", "1"]

        # 无学生 id / 账号泄漏
        assert str(student_profile.id) not in text
        assert str(student_user.id) not in text
        assert student_user.username not in text
    finally:
        _cleanup(db, [tenant.id])


def test_summary_matches_daily_window(
    client: TestClient, operator_token_headers: dict[str, str], db: Session
) -> None:
    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    tenant = _mk_tenant(db)
    teacher = _mk_user(db, tenant.id, "teacher")
    classroom = _mk_classroom(db, tenant, teacher.id)
    student_user, student_profile = _mk_student(db, tenant, classroom)
    _seed_usage(
        db,
        tenant=tenant,
        classroom=classroom,
        teacher=teacher,
        student_profile=student_profile,
        student_user=student_user,
        day=yesterday,
        answers=2,
    )

    try:
        summary = client.get(
            f"{API}/admin/tenants/usage-summary",
            headers=operator_token_headers,
        )
        assert summary.status_code == 200, summary.text
        item = next(
            row for row in summary.json()["items"] if row["tenant_id"] == str(tenant.id)
        )
        expected = {
            "active_teachers": 1,
            "active_students": 1,
            "vocab_answers": 2,
            "published_tasks": 1,
            "completed_students": 1,
            "pk_matches": 1,
            "farm_harvests": 1,
            "placement_tests": 1,
            "exports": 1,
        }
        assert item["summary_7d"] == expected
        assert item["summary_30d"] == expected

        # 与 daily 近 7 天汇总一致（本样本单日，日去重与整窗去重结果相同）
        daily = client.get(
            f"{API}/admin/tenants/{tenant.id}/usage",
            params={
                "from": (yesterday - timedelta(days=6)).isoformat(),
                "to": yesterday.isoformat(),
            },
            headers=operator_token_headers,
        )
        assert daily.status_code == 200, daily.text
        assert daily.json()["totals"] == expected
    finally:
        _cleanup(db, [tenant.id])
