"""#567 第 3 项：模块关闭 / 到期 / 待生效后的只读历史与导出（后端 e2e）。

口径锁定（与 ``test_module_entitlement_e2e.py`` 同一状态机事实源）：
- 非 active 状态（``not_granted`` / ``disabled`` / ``scheduled`` / ``expired``）下，
  仅**显式声明只读**的历史 / 结果 / 趋势 / 榜单历史周 / CSV 导出 GET 放行；
  全部写操作（发布、作答、复习、自主开轮、PK、农场收获、测一测）保持原 403。
- 只读放宽只作用于模块闸门，不放宽成员 / 归属 / 跨租户权限：学生只见本人历史，
  教师只见本班；跨班 / 跨校仍按 404 / 成员 403 拒绝。
- CSV 导出沿用原授权与名单口径，数据范围不随只读放宽而扩大。
- 到期 403 标识 ``module_expired:<key>``；其余非 active 403 标识
  ``module_not_enabled:<key>``。
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import TenantModule
from tests.api.routes.test_module_entitlement_e2e import (
    API,
    _answer_full_round,
    _grant,
    _headers,
    _LoopFixture,
    _mk_classroom,
    _mk_student,
    _mk_tenant,
    _mk_user,
    _run_vocab_loop,
    _seed_book,
)


def _set_state(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    enabled: bool,
    expires_at: datetime | None = None,
    effective_at: datetime | None = None,
) -> None:
    row = db.exec(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant_id,  # type: ignore[arg-type]
            TenantModule.module_key == "vocabulary",
        )
    ).first()
    assert row is not None
    row.enabled = enabled
    row.expires_at = expires_at
    row.effective_at = effective_at
    db.add(row)
    db.commit()


# ── 只读 / 写操作探针清单 ──────────────────────────────────────────────


def _teacher_readonly_routes(
    code: str, assignment_id: str
) -> list[tuple[str, str, dict[str, str] | None]]:
    return [
        ("GET", f"{API}/classes/{code}/vocabulary/assignments", None),
        (
            "GET",
            f"{API}/classes/{code}/vocabulary/results",
            {"assignment_id": assignment_id},
        ),
        (
            "GET",
            f"{API}/classes/{code}/vocabulary/mastery",
            {"assignment_id": assignment_id},
        ),
        ("GET", f"{API}/classes/{code}/vocabulary/trend", {"granularity": "week"}),
        ("GET", f"{API}/classes/{code}/vocabulary/trend.csv", {"granularity": "week"}),
        ("GET", f"{API}/classes/{code}/vocabulary/placement/results", None),
        ("GET", f"{API}/classes/{code}/vocabulary/leaderboard", None),
    ]


def _student_readonly_routes(
    code: str, session_id: str
) -> list[tuple[str, str, dict[str, str] | None]]:
    return [
        ("GET", f"{API}/classes/{code}/vocabulary/today", None),
        ("GET", f"{API}/classes/{code}/vocabulary/student/history", None),
        ("GET", f"{API}/classes/{code}/vocabulary/student/sessions/{session_id}", None),
        ("GET", f"{API}/classes/{code}/vocabulary/wrong-words", None),
        ("GET", f"{API}/classes/{code}/vocabulary/student/review-stats", None),
        ("GET", f"{API}/classes/{code}/vocabulary/placement/history", None),
    ]


def _write_routes(
    code: str, assignment_id: str, session_id: str
) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        # 教师写：发布 / 归档
        ("POST", f"{API}/classes/{code}/vocabulary/assignments", {"word_ids": []}),
        (
            "POST",
            f"{API}/classes/{code}/vocabulary/assignments/{assignment_id}/archive",
            None,
        ),
        # 学生写：任务开轮 / 作答 / 交卷 / 自主开轮 / 测一测 / 农场收获 / PK 加入
        (
            "POST",
            f"{API}/classes/{code}/vocabulary/sessions",
            {"assignment_id": assignment_id},
        ),
        (
            "POST",
            f"{API}/vocabulary/sessions/{session_id}/answers",
            {"item_index": 0, "prompt_type": "meaning", "answer": "apple"},
        ),
        ("POST", f"{API}/vocabulary/sessions/{session_id}/submit", None),
        (
            "POST",
            f"{API}/classes/{code}/vocabulary/student/sessions",
            {"kind": "self", "word_count": 2},
        ),
        ("POST", f"{API}/classes/{code}/vocabulary/placement/start", None),
        ("POST", f"{API}/classes/{code}/vocabulary/student/farm/harvest", None),
        ("POST", f"{API}/classes/{code}/vocabulary/pk/lobby/join", {"joined": True}),
    ]


def _assert_readonly_open(client: TestClient, loop: _LoopFixture) -> None:
    code = loop["classroom"].code
    for method, path, params in _teacher_readonly_routes(code, loop["assignment_id"]):
        resp = client.request(
            method, path, params=params, headers=loop["teacher_headers"]
        )
        assert resp.status_code == 200, f"teacher {method} {path}: {resp.text}"
    for method, path, params in _student_readonly_routes(code, loop["session_id"]):
        resp = client.request(
            method, path, params=params, headers=loop["student_headers"]
        )
        assert resp.status_code == 200, f"student {method} {path}: {resp.text}"


def _assert_writes_blocked(client: TestClient, loop: _LoopFixture, detail: str) -> None:
    code = loop["classroom"].code
    for method, path, body in _write_routes(
        code, loop["assignment_id"], loop["session_id"]
    ):
        resp = client.request(method, path, json=body, headers=loop["student_headers"])
        # 教师写用教师身份；其余学生写用学生身份
        if "/assignments" in path and "archive" not in path:
            resp = client.request(
                method, path, json=body, headers=loop["teacher_headers"]
            )
        elif "archive" in path:
            resp = client.request(
                method, path, json=body, headers=loop["teacher_headers"]
            )
        assert resp.status_code == 403, f"{method} {path}: {resp.text}"
        assert resp.json()["detail"] == detail, f"{method} {path}: {resp.text}"


# ── 关闭（disabled）：只读 200 / 写 403 ──────────────────────────────────


def test_disabled_readonly_history_open_writes_blocked(
    client: TestClient, db: Session
) -> None:
    """enabled=false：历史/结果/趋势/榜单/CSV 只读 200；写操作 403 ``module_not_enabled``。"""
    tenant = _mk_tenant(db, "ro-disabled")
    _grant(db, tenant.id, "vocabulary")
    loop = _run_vocab_loop(client, db, tenant)

    _set_state(db, tenant.id, enabled=False)

    _assert_readonly_open(client, loop)
    _assert_writes_blocked(client, loop, "module_not_enabled:vocabulary")


# ── 到期（expired）：只读 200 / 写 403 ──────────────────────────────────


def test_expired_readonly_history_open_writes_blocked(
    client: TestClient, db: Session
) -> None:
    """expired：只读历史/导出 200；写操作 403 ``module_expired:vocabulary``。"""
    tenant = _mk_tenant(db, "ro-expired")
    _grant(db, tenant.id, "vocabulary")
    loop = _run_vocab_loop(client, db, tenant)

    _set_state(
        db,
        tenant.id,
        enabled=True,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    _assert_readonly_open(client, loop)
    _assert_writes_blocked(client, loop, "module_expired:vocabulary")


# ── 待生效（scheduled）：只读 200 / 写 403 ──────────────────────────────


def test_scheduled_readonly_history_open_writes_blocked(
    client: TestClient, db: Session
) -> None:
    """effective_at 在未来：只读 200；写操作 403 ``module_not_enabled``。"""
    tenant = _mk_tenant(db, "ro-scheduled")
    _grant(db, tenant.id, "vocabulary")
    loop = _run_vocab_loop(client, db, tenant)

    _set_state(
        db,
        tenant.id,
        enabled=True,
        effective_at=datetime.now(UTC) + timedelta(days=7),
    )

    _assert_readonly_open(client, loop)
    _assert_writes_blocked(client, loop, "module_not_enabled:vocabulary")


# ── 重开后写操作恢复 ────────────────────────────────────────────────────


def test_reopen_restores_writes(client: TestClient, db: Session) -> None:
    """到期后运营重开：写操作恢复 200 口径；旧历史仍在。"""
    tenant = _mk_tenant(db, "ro-reopen")
    _grant(db, tenant.id, "vocabulary")
    loop = _run_vocab_loop(client, db, tenant)

    _set_state(
        db,
        tenant.id,
        enabled=True,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    blocked = client.post(
        f"{API}/classes/{loop['classroom'].code}/vocabulary/sessions",
        json={"assignment_id": loop["assignment_id"]},
        headers=loop["student_headers"],
    )
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"] == "module_expired:vocabulary"

    # 重开：清除到期日，转长期 active
    _set_state(db, tenant.id, enabled=True, expires_at=None)

    reopened = client.post(
        f"{API}/classes/{loop['classroom'].code}/vocabulary/sessions",
        json={"assignment_id": loop["assignment_id"], "round": "new"},
        headers=loop["student_headers"],
    )
    assert reopened.status_code == 200, reopened.text

    restored = client.get(
        f"{API}/classes/{loop['classroom'].code}/vocabulary/results",
        params={"assignment_id": loop["assignment_id"]},
        headers=loop["teacher_headers"],
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["completed_count"] == 1


# ── 只读放宽不跨班 / 不跨租户 ────────────────────────────────────────────


def test_readonly_does_not_cross_class_or_tenant(
    client: TestClient, db: Session
) -> None:
    """关闭态：成员/归属门先于模块门；跨班学生 404、非本班教师 403、跨校 404。"""
    tenant = _mk_tenant(db, "ro-cross")
    _grant(db, tenant.id, "vocabulary")
    loop = _run_vocab_loop(client, db, tenant)
    code = loop["classroom"].code

    # 同校另一间课堂 + 另一教师 / 另一学生
    other_teacher = _mk_user(db, tenant.id, "teacher", "t2")
    other_classroom = _mk_classroom(db, tenant.id, other_teacher.id)
    other_student = _mk_user(db, tenant.id, "student", "s2")
    _mk_student(db, other_classroom, other_student)

    _set_state(db, tenant.id, enabled=False)

    # 跨班学生：他人课堂历史 → 404（成员门先于模块只读放宽）
    outsider_student = client.get(
        f"{API}/classes/{code}/vocabulary/student/history",
        headers=_headers(other_student, tenant.id),
    )
    assert outsider_student.status_code == 404, outsider_student.text

    # 跨班教师：他人课堂结果 → 403 成员门（非授权教师），不是模块 403
    outsider_teacher = client.get(
        f"{API}/classes/{code}/vocabulary/results",
        params={"assignment_id": loop["assignment_id"]},
        headers=_headers(other_teacher, tenant.id),
    )
    assert outsider_teacher.status_code == 403, outsider_teacher.text
    assert "module_" not in str(outsider_teacher.json().get("detail", ""))

    # 跨租户：他校教师访问本校课堂 → 成员门拒绝（403，非模块 403），只读放宽不越权
    other_tenant = _mk_tenant(db, "ro-cross-other")
    other_tenant_teacher = _mk_user(db, other_tenant.id, "teacher", "t3")
    cross = client.get(
        f"{API}/classes/{code}/vocabulary/results",
        params={"assignment_id": loop["assignment_id"]},
        headers=_headers(other_tenant_teacher, other_tenant.id),
    )
    assert cross.status_code in (403, 404), cross.text
    assert "module_" not in str(cross.json().get("detail", ""))


# ── CSV 导出：关闭态可导出，名单范围不扩大 ──────────────────────────────


def test_readonly_csv_export_scope_not_expanded(
    client: TestClient, db: Session
) -> None:
    """关闭态 trend.csv 与测验 results-export 仍 200；CSV 名单 = 原固定应考名单，不扩容。"""
    tenant = _mk_tenant(db, "ro-csv")
    _grant(db, tenant.id, "vocabulary")
    teacher = _mk_user(db, tenant.id, "school_admin", "t")
    classroom = _mk_classroom(db, tenant.id, teacher.id)
    student_user = _mk_user(db, tenant.id, "student", "s")
    _mk_student(db, classroom, student_user)
    teacher_headers = _headers(teacher, tenant.id)
    student_headers = _headers(student_user, tenant.id)
    code = classroom.code

    book = _seed_book(client, teacher_headers)
    word_ids = [w["id"] for w in book["words"]]
    # 测验任务：发布 → 开始 → 两题作答 → 交卷
    quiz = client.post(
        f"{API}/classes/{code}/vocabulary/assignments",
        json={
            "word_ids": word_ids,
            "prompt_types": ["meaning"],
            "mode": "quiz",
            "duration_minutes": 30,
            "pass_line": 60,
        },
        headers=teacher_headers,
    )
    assert quiz.status_code == 200, quiz.text
    assignment_id = quiz.json()["id"]

    started = client.post(
        f"{API}/classes/{code}/vocabulary/sessions",
        json={"assignment_id": assignment_id},
        headers=student_headers,
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session_id"]
    _answer_full_round(client, student_headers, session_id)
    submitted = client.post(
        f"{API}/vocabulary/sessions/{session_id}/submit",
        headers=student_headers,
    )
    assert submitted.status_code == 200, submitted.text

    # 关闭模块
    _set_state(db, tenant.id, enabled=False)

    trend_csv = client.get(
        f"{API}/classes/{code}/vocabulary/trend.csv",
        params={"granularity": "week"},
        headers=teacher_headers,
    )
    assert trend_csv.status_code == 200, trend_csv.text
    assert trend_csv.headers["content-type"].startswith("text/csv")

    quiz_csv = client.get(
        f"{API}/classes/{code}/vocabulary/assignments/{assignment_id}/results-export",
        headers=teacher_headers,
    )
    assert quiz_csv.status_code == 200, quiz_csv.text
    text = quiz_csv.content.decode("utf-8-sig")
    lines = [line for line in text.strip().splitlines() if line]
    # 表头 + 固定应考名单 1 人（后入班学生不在名单内，不随只读放宽扩容）
    assert len(lines) == 2, text
    assert "e2e 测试生" in lines[1], text
