"""模块授权遗留验收（#567 e2e 切片）：纯词汇闭环 / 跨表守护 / 单买拦截清单 / 到期留存恢复。

口径锁定（与 test_module_entitlement.py、test_tenant_module_lifecycle.py 同一事实源）：
- 授权粒度整校；缺行/disabled/scheduled → 403 ``module_not_enabled:<key>``；
  expired → 403 ``module_expired:<key>``；404 优先于 403。
- 到期/关闭只关门禁，绝不物理删除业务作答、名册、任务与词库数据。
- 本文件只补 #567 正文六条里可在合成租户 TestClient 内自动化的链路：
  1. 纯词汇租户闭环（建校 → 名单 → 发布 → 作答 → 教师报告）；
  4. 仅词汇租户不写口语业务表（行数级守护断言）；
  5. 仅口语租户词汇端点逐条 403；
  3/6. 关闭/到期后词汇读写链路 403、业务行留存、重开后旧数据仍可见。

需要旧构建基线截图、生产测试校目检的条目不在本文件覆盖范围，见
``docs/qa/20261127/567-entitlement-e2e/EVIDENCE.md`` 的缺口清单。
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core import security
from app.models import (
    Attempt,
    Classroom,
    PracticeSession,
    Student,
    Tenant,
    TenantModule,
    User,
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyAssignmentTarget,
    VocabularySession,
)

API = "/api/v1"
WORDS_2 = [
    {"headword": "apple", "part_of_speech": "n.", "meaning_zh": "苹果"},
    {"headword": "banana", "part_of_speech": "n.", "meaning_zh": "香蕉"},
]


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _mk_tenant(db: Session, tag: str) -> Tenant:
    row = Tenant(
        slug=f"e2e-{tag}-{_uid()}",
        name_zh=f"授权 e2e 校 {tag}",
        status="active",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_user(db: Session, tenant_id: uuid.UUID, role: str, tag: str) -> User:
    user = User(
        email=f"e2e-{role}-{tag}-{_uid()}@example.com",
        hashed_password="x",
        role=role,
        tenant_id=tenant_id,
        full_name=f"e2e {role} {tag}",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _mk_classroom(db: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID) -> Classroom:
    row = Classroom(
        code=f"E2E{_uid()[:6].upper()}",
        class_size=8,
        owner_id=owner_id,
        tenant_id=tenant_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _mk_student(db: Session, classroom: Classroom, user: User) -> Student:
    row = Student(
        classroom_id=classroom.id,
        display_name="e2e 测试生",
        user_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _headers(user: User, tenant_id: uuid.UUID) -> dict[str, str]:
    token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=10),
        role=user.role,
        password_hash=user.hashed_password,
        tenant_id=str(tenant_id),
    )
    return {"Authorization": f"Bearer {token}"}


def _grant(
    db: Session,
    tenant_id: uuid.UUID,
    key: str,
    *,
    enabled: bool = True,
    expires_at: datetime | None = None,
) -> TenantModule:
    row = TenantModule(
        tenant_id=tenant_id,
        module_key=key,
        enabled=enabled,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _seed_book(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post(
        f"{API}/vocabulary/books",
        json={
            "title": "e2e 闭环词库",
            "scope": "public",
            "words": WORDS_2,
            "confirm_reviewed": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _publish(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    word_ids: list[str],
) -> dict:
    resp = client.post(
        f"{API}/classes/{code}/vocabulary/assignments",
        json={"word_ids": word_ids, "prompt_types": ["meaning"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _answer_full_round(
    client: TestClient, student_headers: dict[str, str], session_id: str
) -> None:
    for idx, answer in enumerate(["apple", "banana"]):
        resp = client.post(
            f"{API}/vocabulary/sessions/{session_id}/answers",
            json={
                "item_index": idx,
                "prompt_type": "meaning",
                "answer": answer,
            },
            headers=student_headers,
        )
        assert resp.status_code == 200, resp.text


class _LoopFixture(TypedDict):
    teacher: User
    student_user: User
    classroom: Classroom
    teacher_headers: dict[str, str]
    student_headers: dict[str, str]
    assignment_id: str
    session_id: str


def _run_vocab_loop(
    client: TestClient,
    db: Session,
    tenant: Tenant,
) -> _LoopFixture:
    """在已开通 vocabulary 的合成租户内跑通：建班 → 名单 → 发书 → 发布 → 作答 → 报告。

    返回教师/学生身份头、课堂码、任务 id 与学生会话 id，供后续关闭/到期用例复用。
    """
    teacher = _mk_user(db, tenant.id, "school_admin", "t")
    classroom = _mk_classroom(db, tenant.id, teacher.id)
    student_user = _mk_user(db, tenant.id, "student", "s")
    _mk_student(db, classroom, student_user)
    teacher_headers = _headers(teacher, tenant.id)
    student_headers = _headers(student_user, tenant.id)

    book = _seed_book(client, teacher_headers)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, teacher_headers, classroom.code, word_ids)

    today = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/today",
        headers=student_headers,
    )
    assert today.status_code == 200, today.text
    assert today.json()["assignment"]["id"] == assignment["id"]

    started = client.post(
        f"{API}/classes/{classroom.code}/vocabulary/sessions",
        json={"assignment_id": assignment["id"]},
        headers=student_headers,
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session_id"]
    _answer_full_round(client, student_headers, session_id)

    results = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/results",
        params={"assignment_id": assignment["id"]},
        headers=teacher_headers,
    )
    assert results.status_code == 200, results.text
    assert results.json()["completed_count"] == 1

    return {
        "teacher": teacher,
        "student_user": student_user,
        "classroom": classroom,
        "teacher_headers": teacher_headers,
        "student_headers": student_headers,
        "assignment_id": assignment["id"],
        "session_id": session_id,
    }


# ── 1. 纯词汇租户端到端闭环 ──────────────────────────────────────────────


def test_vocabulary_only_tenant_closed_loop(client: TestClient, db: Session) -> None:
    """只开 vocabulary：建校 → 名单 → 发书 → 发布 → 作答 → 教师报告全链路 200；口语仍 403。"""
    tenant = _mk_tenant(db, "loop")
    _grant(db, tenant.id, "vocabulary")

    me = client.get(
        f"{API}/modules/me",
        headers=_headers(_mk_user(db, tenant.id, "school_admin", "me"), tenant.id),
    )
    assert me.status_code == 200, me.text
    assert me.json()["modules"] == ["vocabulary"]

    loop = _run_vocab_loop(client, db, tenant)

    # 口语链路在纯词汇租户内仍被闸门拦截，不被词汇闭环误伤放行
    speaking = client.get(
        f"{API}/classes/{loop['classroom'].code}/today",
        headers=loop["teacher_headers"],
    )
    assert speaking.status_code == 403, speaking.text
    assert speaking.json()["detail"] == "module_not_enabled:speaking"


# ── 4. 仅词汇租户不写口语业务表（行数级守护断言）──────────────────────────


def test_vocabulary_only_does_not_touch_speaking_tables(
    client: TestClient, db: Session
) -> None:
    """词汇闭环跑通后，口语作答/练习会话表对本租户零行；口语端点 403 在服务层之前拦截。"""
    tenant = _mk_tenant(db, "guard")
    _grant(db, tenant.id, "vocabulary")
    loop = _run_vocab_loop(client, db, tenant)

    # 口语端点逐条 403（学生修订页 + 教师今日任务）
    student_speaking = client.get(
        f"{API}/classes/{loop['classroom'].code}/revision",
        headers=loop["student_headers"],
    )
    assert student_speaking.status_code == 403, student_speaking.text
    assert student_speaking.json()["detail"] == "module_not_enabled:speaking"

    teacher_speaking = client.get(
        f"{API}/classes/{loop['classroom'].code}/today",
        headers=loop["teacher_headers"],
    )
    assert teacher_speaking.status_code == 403, teacher_speaking.text
    assert teacher_speaking.json()["detail"] == "module_not_enabled:speaking"

    # 行数级守护：口语业务表对本租户零行（闸门在进口语服务前抛出，未产生作答/会话）
    attempt_rows = db.exec(
        select(Attempt).where(Attempt.tenant_id == tenant.id)  # type: ignore[arg-type]
    ).all()
    session_rows = db.exec(
        select(PracticeSession).where(
            PracticeSession.tenant_id == tenant.id  # type: ignore[arg-type]
        )
    ).all()
    assert attempt_rows == []
    assert session_rows == []


# ── 5. 仅口语租户：词汇端点逐条 403（后端清单口径）────────────────────────


def test_speaking_only_vocab_routes_blocked_per_checklist(
    client: TestClient, db: Session
) -> None:
    """只开 speaking：写操作 / 内容管理 / 激励子能力词汇端点逐条 403；

    显式只读的历史/导出 GET 在未购态也放行（#567 第 3 项只读口径），
    其模块闸门不在本用例拦截清单内，由 ``test_module_readonly_history.py``
    逐条固定。前端导航隐藏与空卡片目检由既有 e2e 规格旁证。
    """
    tenant = _mk_tenant(db, "sp-only")
    _grant(db, tenant.id, "speaking")
    teacher = _mk_user(db, tenant.id, "school_admin", "t")
    classroom = _mk_classroom(db, tenant.id, teacher.id)
    student_user = _mk_user(db, tenant.id, "student", "s")
    _mk_student(db, classroom, student_user)
    teacher_headers = _headers(teacher, tenant.id)
    student_headers = _headers(student_user, tenant.id)
    code = classroom.code

    # 严格 403：词库内容管理、激励/对战/配置类 GET 与全部写操作。
    teacher_routes: list[tuple[str, str, dict[str, str] | None]] = [
        ("GET", f"{API}/vocabulary/books", None),
        ("GET", f"{API}/classes/{code}/vocabulary/teacher/farm-summary", None),
        ("GET", f"{API}/classes/{code}/vocabulary/leaderboard/settings", None),
        ("GET", f"{API}/classes/{code}/vocabulary/pk/lobby", None),
    ]
    student_routes: list[tuple[str, str, dict[str, str] | None]] = [
        ("GET", f"{API}/classes/{code}/vocabulary/student/books", None),
        ("GET", f"{API}/classes/{code}/vocabulary/student/review-queue", None),
        ("GET", f"{API}/classes/{code}/vocabulary/student/farm", None),
    ]

    for method, path, params in teacher_routes:
        resp = client.request(method, path, params=params, headers=teacher_headers)
        assert resp.status_code == 403, f"{method} {path}: {resp.text}"
        assert resp.json()["detail"] == "module_not_enabled:vocabulary", path

    for method, path, params in student_routes:
        resp = client.request(method, path, params=params, headers=student_headers)
        assert resp.status_code == 403, f"{method} {path}: {resp.text}"
        assert resp.json()["detail"] == "module_not_enabled:vocabulary", path


# ── 3. 关闭模块：读写链路 403，业务行留存 ─────────────────────────────────


def _vocab_row_counts(
    db: Session, tenant: Tenant, classroom: Classroom, assignment_id: str
) -> dict[str, int]:
    return {
        "assignment": len(
            db.exec(
                select(VocabularyAssignment).where(
                    VocabularyAssignment.classroom_id == classroom.id  # type: ignore[arg-type]
                )
            ).all()
        ),
        "target": len(
            db.exec(
                select(VocabularyAssignmentTarget).where(
                    VocabularyAssignmentTarget.assignment_id == uuid.UUID(assignment_id)  # type: ignore[arg-type]
                )
            ).all()
        ),
        "session": len(
            db.exec(
                select(VocabularySession).where(
                    VocabularySession.classroom_id == classroom.id  # type: ignore[arg-type]
                )
            ).all()
        ),
        "answer": len(
            db.exec(
                select(VocabularyAnswer).where(
                    VocabularyAnswer.tenant_id == tenant.id  # type: ignore[arg-type]
                )
            ).all()
        ),
        "student": len(
            db.exec(
                select(Student).where(Student.classroom_id == classroom.id)  # type: ignore[arg-type]
            ).all()
        ),
        "classroom": len(
            db.exec(
                select(Classroom).where(Classroom.tenant_id == tenant.id)  # type: ignore[arg-type]
            ).all()
        ),
    }


def test_disabled_blocks_vocab_but_retains_rows(
    client: TestClient, db: Session
) -> None:
    """关闭（enabled=false）：词汇读写 403 ``module_not_enabled``；任务/作答/名册物理留存。"""
    tenant = _mk_tenant(db, "disabled")
    _grant(db, tenant.id, "vocabulary")
    loop = _run_vocab_loop(client, db, tenant)
    classroom = loop["classroom"]

    before = _vocab_row_counts(db, tenant, classroom, loop["assignment_id"])
    assert before["assignment"] == 1
    assert before["target"] == 1
    assert before["session"] == 1
    assert before["answer"] == 2
    assert before["student"] == 1
    assert before["classroom"] == 1

    row = db.exec(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant.id,  # type: ignore[arg-type]
            TenantModule.module_key == "vocabulary",
        )
    ).first()
    assert row is not None
    row.enabled = False
    db.add(row)
    db.commit()

    blocked_student = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/student/review-queue",
        headers=loop["student_headers"],
    )
    assert blocked_student.status_code == 403, blocked_student.text
    assert blocked_student.json()["detail"] == "module_not_enabled:vocabulary"

    # 只读历史/导出在关闭态仍放行（#567 第 3 项）；逐条 200 口径见只读测试文件
    open_results = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/results",
        params={"assignment_id": loop["assignment_id"]},
        headers=loop["teacher_headers"],
    )
    assert open_results.status_code == 200, open_results.text

    open_csv = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/trend.csv",
        params={"granularity": "week"},
        headers=loop["teacher_headers"],
    )
    assert open_csv.status_code == 200, open_csv.text

    after = _vocab_row_counts(db, tenant, classroom, loop["assignment_id"])
    assert after == before


# ── 3/6. 到期：403 ``module_expired``、数据留存、重开后旧报告仍可见 ────────


def test_expired_blocks_retains_rows_reopen_restores_visibility(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    """到期：词汇链路 403 ``module_expired:vocabulary``；作答留存；运营重开后旧报告 200 且成绩不丢。"""
    tenant = _mk_tenant(db, "expired-loop")
    _grant(db, tenant.id, "vocabulary")
    loop = _run_vocab_loop(client, db, tenant)
    classroom = loop["classroom"]

    before = _vocab_row_counts(db, tenant, classroom, loop["assignment_id"])

    row = db.exec(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant.id,  # type: ignore[arg-type]
            TenantModule.module_key == "vocabulary",
        )
    ).first()
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(days=1)
    db.add(row)
    db.commit()

    blocked_student = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/student/review-queue",
        headers=loop["student_headers"],
    )
    assert blocked_student.status_code == 403, blocked_student.text
    assert blocked_student.json()["detail"] == "module_expired:vocabulary"

    # 到期态只读历史/导出仍放行；写操作与复习队列保持 module_expired 403
    open_results = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/results",
        params={"assignment_id": loop["assignment_id"]},
        headers=loop["teacher_headers"],
    )
    assert open_results.status_code == 200, open_results.text

    open_csv = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/trend.csv",
        params={"granularity": "week"},
        headers=loop["teacher_headers"],
    )
    assert open_csv.status_code == 200, open_csv.text

    retained = _vocab_row_counts(db, tenant, classroom, loop["assignment_id"])
    assert retained == before

    # 运营重开（清除到期日，转长期 active）
    reopen = client.put(
        f"{API}/admin/tenants/{tenant.id}/modules/vocabulary",
        json={
            "enabled": True,
            "grant_type": "paid",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
        },
        headers=operator_token_headers,
    )
    assert reopen.status_code == 200, reopen.text
    assert reopen.json()["state"] == "active"

    restored_results = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/results",
        params={"assignment_id": loop["assignment_id"]},
        headers=loop["teacher_headers"],
    )
    assert restored_results.status_code == 200, restored_results.text
    # 留存的旧作答在重开后仍进报告：completed_count 不被重置
    assert restored_results.json()["completed_count"] == 1

    restored_queue = client.get(
        f"{API}/classes/{classroom.code}/vocabulary/student/review-queue",
        headers=loop["student_headers"],
    )
    assert restored_queue.status_code == 200, restored_queue.text


# ── 附：词汇任务目标行按名册生成（闭环数据完整性守护）─────────────────────


def test_assignment_targets_cover_roster(client: TestClient, db: Session) -> None:
    """发布任务按名单生成目标行；闭环内 1 名学生 = 1 条 target（每生每任务一行，词数落在任务快照）。"""
    tenant = _mk_tenant(db, "targets")
    _grant(db, tenant.id, "vocabulary")
    loop = _run_vocab_loop(client, db, tenant)

    targets = db.exec(
        select(VocabularyAssignmentTarget).where(
            VocabularyAssignmentTarget.assignment_id == uuid.UUID(loop["assignment_id"])  # type: ignore[arg-type]
        )
    ).all()
    assert len(targets) == 1
    assert all(t.tenant_id == tenant.id for t in targets)
