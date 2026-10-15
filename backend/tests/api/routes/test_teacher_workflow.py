import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models import (
    Attempt,
    Classroom,
    ComposerDraft,
    Passage,
    PracticeSession,
    get_datetime_utc,
)
from tests.utils.credential import make_student


def draft_state() -> dict:
    return {
        "title": "Saved preparation",
        "types": {"reading": False, "repeat": True, "qa": False, "instruction": False},
        "selection": {
            "passages": [],
            "sentences": [str(uuid.uuid4())],
            "scenarioIds": [],
            "instructions": [],
            "questions": [],
        },
        "ordered_keys": [],
        "is_exam": False,
        "exam_minutes": 30,
    }


def test_draft_is_private_conflict_checked_and_removed_atomically_on_publish(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    headers = superuser_token_headers
    endpoint = "/api/v1/classes/DEMO01/composer-draft"
    classroom = db.exec(select(Classroom).where(Classroom.code == "DEMO01")).one()
    old = (
        classroom.current_exercise_id,
        classroom.assigned_items,
        classroom.current_unit_id,
    )
    existing = db.exec(
        select(ComposerDraft).where(ComposerDraft.classroom_id == classroom.id)
    ).all()
    for row in existing:
        db.delete(row)
    db.commit()
    try:
        assert client.get(endpoint, headers=headers).json() is None
        saved = client.put(
            endpoint,
            json={"expected_revision": 0, "state": draft_state()},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        revision = saved.json()["revision"]
        assert revision > 0
        assert (
            client.get(endpoint, headers=headers).json()["state"]
            == saved.json()["state"]
        )
        assert (
            client.put(
                endpoint,
                json={"expected_revision": 0, "state": draft_state()},
                headers=headers,
            ).status_code
            == 409
        )
        # Unauthorized teachers cannot see or change another classroom's draft.
        assert (
            client.get(endpoint, headers=normal_user_token_headers).status_code == 403
        )
        student = make_student(db, client, "DEMO01", "草稿权限")
        assert client.get(endpoint, headers=student["headers"]).status_code == 403
        assignment = "/api/v1/classes/DEMO01/assignment"
        invalid = client.put(
            assignment,
            headers=headers,
            json={
                "draft_revision": revision,
                "items": [{"type": "repeat", "id": str(uuid.uuid4())}],
            },
        )
        assert invalid.status_code == 404
        assert client.get(endpoint, headers=headers).json()["revision"] == revision
        assert (
            client.put(
                assignment,
                headers=headers,
                json={"draft_revision": revision - 1, "items": []},
            ).status_code
            == 409
        )
        assert (
            client.put(
                assignment,
                headers=headers,
                json={"draft_revision": revision, "items": []},
            ).status_code
            == 200
        )
        assert client.get(endpoint, headers=headers).json() is None
        recreated = client.put(
            endpoint,
            headers=headers,
            json={"expected_revision": 0, "state": draft_state()},
        ).json()
        assert recreated["revision"] != revision
        assert (
            client.put(
                endpoint,
                headers=headers,
                json={"expected_revision": revision, "state": draft_state()},
            ).status_code
            == 409
        )
    finally:
        db.rollback()
        for row in db.exec(
            select(ComposerDraft).where(ComposerDraft.classroom_id == classroom.id)
        ).all():
            db.delete(row)
        (
            classroom.current_exercise_id,
            classroom.assigned_items,
            classroom.current_unit_id,
        ) = old
        db.add(classroom)
        db.commit()


def test_history_seed_collapses_reading_segments_and_does_not_publish(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    from app.models import ClassroomExercise

    classroom = db.exec(select(Classroom).where(Classroom.code == "DEMO01")).one()
    original = classroom.current_exercise_id
    passage = db.exec(select(Passage)).first()
    assert passage is not None
    exercise = ClassroomExercise(
        classroom_id=classroom.id,
        version_no=999999,
        title="Earlier exam",
        is_exam=True,
        time_limit_minutes=45,
        snapshot_items=[
            {"type": "passage", "id": str(uuid.uuid4()), "parent_id": str(passage.id)},
            {"type": "passage", "id": str(uuid.uuid4()), "parent_id": str(passage.id)},
        ],
    )
    db.add(exercise)
    db.commit()
    try:
        seed = client.get(
            f"/api/v1/classes/DEMO01/exercises/{exercise.id}/composer-seed",
            headers=superuser_token_headers,
        )
        assert seed.status_code == 200, seed.text
        data = seed.json()
        assert data["selection"]["passages"] == [str(passage.id)]
        assert data["ordered_keys"] == [f"passage:{passage.id}"]
        assert data["is_exam"] and data["exam_minutes"] == 45
        assert (
            client.get(
                f"/api/v1/classes/DEMO01/exercises/{uuid.uuid4()}/composer-seed",
                headers=superuser_token_headers,
            ).status_code
            == 404
        )
        db.refresh(classroom)
        assert classroom.current_exercise_id == original
    finally:
        db.delete(exercise)
        db.commit()


def test_diagnostics_scope_expiry_and_latest_success(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    student = make_student(db, client, "DEMO01", "异常上报")
    plan = client.get("/api/v1/classes/DEMO01/today", headers=student["headers"]).json()
    ps = db.get(PracticeSession, uuid.UUID(plan["session_id"]))
    assert ps is not None
    report = "/api/v1/classes/DEMO01/runtime-issue"
    diagnostic = "/api/v1/classes/DEMO01/diagnostics"
    assert (
        client.put(
            report,
            json={"session_id": str(uuid.uuid4()), "issue": "device"},
            headers=student["headers"],
        ).status_code
        == 404
    )
    other = make_student(db, client, "DEMO01", "另一个学生")
    assert (
        client.put(
            report,
            json={"session_id": str(ps.id), "issue": "device"},
            headers=other["headers"],
        ).status_code
        == 404
    )
    assert (
        client.put(
            report,
            json={"session_id": str(ps.id), "issue": "device"},
            headers=student["headers"],
        ).status_code
        == 200
    )
    assert client.get(diagnostic, headers=student["headers"]).status_code == 403
    rows = client.get(diagnostic, headers=superuser_token_headers).json()["issues"]
    assert any(
        r["student_id"] == str(ps.student_id) and r["kind"] == "device" for r in rows
    )
    ps.runtime_issue_at = get_datetime_utc() - timedelta(minutes=6)
    db.add(ps)
    db.commit()
    assert not any(
        r["student_id"] == str(ps.student_id)
        for r in client.get(diagnostic, headers=superuser_token_headers).json()[
            "issues"
        ]
    )
    item_id = uuid.uuid4()
    started = get_datetime_utc() - timedelta(minutes=3)
    slow = Attempt(
        session_id=ps.id,
        student_id=ps.student_id,
        item_id=item_id,
        item_type="repeat",
        audio_path="unused",
        duration_s=2,
        status="scoring",
        created_at=started,
        claimed_at=started,
    )
    db.add(slow)
    db.commit()
    done = None
    try:
        rows = client.get(diagnostic, headers=superuser_token_headers).json()["issues"]
        assert any(
            r["attempt_id"] == str(slow.id) and r["kind"] == "scoring_slow"
            for r in rows
        )
        done = Attempt(
            session_id=ps.id,
            student_id=ps.student_id,
            item_id=item_id,
            item_type="repeat",
            audio_path="unused",
            duration_s=2,
            status="done",
        )
        db.add(done)
        db.commit()
        assert not any(
            r["attempt_id"] == str(slow.id)
            for r in client.get(diagnostic, headers=superuser_token_headers).json()[
                "issues"
            ]
        )
        done.status = "failed"
        db.add(done)
        db.commit()
        assert any(
            r["kind"] == "scoring_failed"
            for r in client.get(diagnostic, headers=superuser_token_headers).json()[
                "issues"
            ]
        )
        assert (
            client.put(
                report,
                json={"session_id": str(ps.id), "issue": None},
                headers=student["headers"],
            ).status_code
            == 200
        )
    finally:
        db.delete(slow)
        if done is not None:
            db.delete(done)
        db.commit()


def test_authorized_teachers_have_separate_drafts(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    owner = client.get("/api/v1/users/me", headers=normal_user_token_headers).json()[
        "id"
    ]
    classroom = Classroom(
        code=uuid.uuid4().hex[:6].upper(),
        name="Private drafts",
        class_size=10,
        owner_id=uuid.UUID(owner),
    )
    db.add(classroom)
    db.commit()
    endpoint = f"/api/v1/classes/{classroom.code}/composer-draft"
    try:
        admin = client.put(
            endpoint,
            headers=superuser_token_headers,
            json={"expected_revision": 0, "state": draft_state()},
        )
        assert admin.status_code == 200
        assert client.get(endpoint, headers=normal_user_token_headers).json() is None
        teacher_state = {**draft_state(), "title": "Only the classroom owner sees this"}
        assert (
            client.put(
                endpoint,
                headers=normal_user_token_headers,
                json={"expected_revision": 0, "state": teacher_state},
            ).status_code
            == 200
        )
        assert (
            client.get(endpoint, headers=superuser_token_headers).json()["state"][
                "title"
            ]
            == "Saved preparation"
        )
        assert (
            client.get(endpoint, headers=normal_user_token_headers).json()["state"][
                "title"
            ]
            == teacher_state["title"]
        )
    finally:
        db.delete(classroom)
        db.commit()
