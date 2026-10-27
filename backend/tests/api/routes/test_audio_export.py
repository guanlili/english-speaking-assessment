"""口语原音频 ZIP：权限、清单、缺失、体积、过期、重试。"""

import csv
import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from app.api.deps import get_export_submitter
from app.core.config import settings
from app.core.security import get_password_hash
from app.exporting.worker import expire_due_exports, process_export_job, worker_count
from app.main import app
from app.models import (
    Attempt,
    Classroom,
    ClassroomExercise,
    ExportAudit,
    ExportJob,
    ExportJobStatus,
    PracticeSession,
    Student,
    User,
)
from tests.utils.credential import create_student_user, login_headers
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


@pytest.fixture(autouse=True)
def _export_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
):
    monkeypatch.setattr(
        settings, "EXPORT_STORAGE_DIR", str(tmp_path_factory.mktemp("export"))
    )
    monkeypatch.setattr(settings, "EXPORT_TTL_DAYS", 7)
    monkeypatch.setattr(settings, "EXPORT_MAX_IN_PROGRESS", 2)
    monkeypatch.setattr(settings, "EXPORT_MAX_BYTES", 2 * 1024 * 1024 * 1024)


@pytest.fixture(autouse=True)
def _clear_jobs(db: Session):
    yield
    db.exec(delete(ExportAudit))
    db.exec(delete(ExportJob))
    db.commit()


@pytest.fixture
def sync_exports():
    app.dependency_overrides[get_export_submitter] = lambda: process_export_job
    yield
    app.dependency_overrides.pop(get_export_submitter, None)


@pytest.fixture
def hold_exports():
    app.dependency_overrides[get_export_submitter] = lambda: lambda _job_id: None
    yield
    app.dependency_overrides.pop(get_export_submitter, None)


def test_export_workers_ignore_scoring_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SCORING_WORKERS", 32)
    monkeypatch.setattr(settings, "EXPORT_WORKERS", 2)
    assert worker_count() == 2
    monkeypatch.setattr(settings, "EXPORT_WORKERS", 9)
    assert worker_count() == 2


def _teacher(
    db: Session, client: TestClient, name: str = "王老师"
) -> tuple[User, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    user = User(
        email=email,
        full_name=name,
        role="teacher",
        hashed_password=get_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, user_authentication_headers(
        client=client, email=email, password=password
    )


def _classroom(db: Session, owner: User, name: str = "宠物班") -> Classroom:
    room = Classroom(
        code=uuid.uuid4().hex[:12],
        name=name,
        owner_id=owner.id,
        class_size=60,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def _enroll(
    db: Session, client: TestClient, room: Classroom, name: str
) -> tuple[User, Student, dict[str, str]]:
    user = create_student_user(db, full_name=name)
    student = Student(
        classroom_id=room.id,
        user_id=user.id,
        display_name=name,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    assert user.username is not None
    return user, student, login_headers(client, user.username)


def _audio(tmp_path, name: str, payload: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(payload)
    return str(path)


def _attempt(
    db: Session,
    student: Student,
    path: str,
    *,
    status: str = "done",
    overall: int | None = 85,
    item_id: uuid.UUID | None = None,
    item_type: str = "passage",
    created_at: datetime | None = None,
    purged: datetime | None = None,
    mime: str = "audio/webm",
    title: str = "Pets",
    session_id: uuid.UUID | None = None,
) -> Attempt:
    row = Attempt(
        item_type=item_type,
        item_id=item_id or uuid.uuid4(),
        student_id=student.id,
        session_id=session_id,
        audio_path=path,
        audio_mime=mime,
        duration_s=2,
        status=status,
        overall=overall,
        item_snapshot={"type": item_type, "title": title, "text": "I like pets."},
        audio_purged_at=purged,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _zip(response) -> zipfile.ZipFile:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip")
    return zipfile.ZipFile(io.BytesIO(response.content))


def _manifest(archive: zipfile.ZipFile) -> list[dict[str, str]]:
    name = next(item for item in archive.namelist() if item.endswith("manifest.csv"))
    raw = archive.read(name)
    assert raw.startswith("\ufeff".encode())
    text = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows or text.splitlines()[0].startswith("attempt_id")
    header = text.splitlines()[0]
    for column in (
        "attempt_id",
        "student_id",
        "student_name",
        "student_no",
        "classroom_code",
        "classroom_name",
        "session_id",
        "exercise_id",
        "item_type",
        "item_id",
        "item_title",
        "created_at",
        "duration_s",
        "overall",
        "status",
        "audio_mime",
        "zip_path",
        "missing",
    ):
        assert column in header
    return rows


def test_student_exports_only_own_original_bytes(
    client: TestClient, db: Session, sync_exports, tmp_path
) -> None:
    teacher, _ = _teacher(db, client)
    room = _classroom(db, teacher)
    alice_user, alice, alice_headers = _enroll(db, client, room, "李雷")
    _bob_user, bob, _bob_headers = _enroll(db, client, room, "韩梅梅")
    created = datetime(2026, 10, 27, 2, 30, tzinfo=UTC)
    payload = b"webm-original-bytes"
    path = _audio(tmp_path, "alice.webm", payload)
    playback = tmp_path / "alice.webm.playback.wav"
    playback.write_bytes(b"reencoded-wav")
    attempt = _attempt(db, alice, path, created_at=created, title="Pets friends")
    _attempt(
        db,
        bob,
        _audio(tmp_path, "bob.webm", b"bob-secret"),
        created_at=created,
    )
    response = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=alice_headers,
        json={"scope": "self"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["download_name"].startswith("SpeakUp_我的录音_")
    assert body["included_count"] == 1
    download = client.get(
        f"{settings.API_V1_STR}/exports/{body['id']}/download",
        headers=alice_headers,
    )
    with _zip(download) as archive:
        names = archive.namelist()
        assert all(not name.endswith(".playback.wav") for name in names)
        rows = _manifest(archive)
        assert len(rows) == 1
        assert rows[0]["attempt_id"] == str(attempt.id)
        assert rows[0]["student_no"] == alice_user.username
        assert rows[0]["student_name"] == "李雷"
        assert rows[0]["created_at"] == "2026-10-27 10:30:00"
        assert rows[0]["missing"] == "0"
        assert rows[0]["overall"] == "85"
        stored = f"{body['download_name'][:-4]}/{rows[0]['zip_path']}"
        assert stored in names
        assert archive.read(stored) == payload
        assert stored.endswith(".webm")
        assert "李雷" not in stored or "文章朗读" in stored
    foreign = client.get(
        f"{settings.API_V1_STR}/exports/{body['id']}/download",
        headers=_bob_headers,
    )
    assert foreign.status_code == 403


def test_teacher_classroom_group_by_item_and_cross_class_forbidden(
    client: TestClient, db: Session, sync_exports, tmp_path
) -> None:
    teacher, headers = _teacher(db, client)
    other, other_headers = _teacher(db, client, name="其他老师")
    room = _classroom(db, teacher, name="七年级一班")
    _classroom(db, other, name="别的班")
    _alice_user, alice, _ = _enroll(db, client, room, "李雷")
    _bob_user, bob, _ = _enroll(db, client, room, "韩梅梅")
    passage_id = uuid.uuid4()
    question_id = uuid.uuid4()
    exercise = ClassroomExercise(
        classroom_id=room.id,
        version_no=1,
        title="宠物练习",
        snapshot_items=[{"type": "passage", "id": str(passage_id), "title": "Pets"}],
    )
    db.add(exercise)
    db.commit()
    db.refresh(exercise)
    practice = PracticeSession(
        classroom_id=room.id,
        student_id=alice.id,
        band="B1",
        session_date=datetime.now(UTC).date(),
        assignment_id=exercise.id,
    )
    db.add(practice)
    db.commit()
    db.refresh(practice)
    created = datetime.now(UTC) - timedelta(days=1)
    alice_bytes = b"alice-passage"
    bob_bytes = b"bob-question"
    _attempt(
        db,
        alice,
        _audio(tmp_path, "a.webm", alice_bytes),
        item_id=passage_id,
        created_at=created,
        title="My pet",
        session_id=practice.id,
    )
    _attempt(
        db,
        bob,
        _audio(tmp_path, "b.webm", bob_bytes),
        item_type="question",
        item_id=question_id,
        created_at=created + timedelta(minutes=5),
        title="Do you have a pet",
        overall=70,
    )
    denied = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=other_headers,
        json={
            "scope": "classroom",
            "classroom_id": str(room.id),
            "confirm_contains_student_audio": True,
            "group_by_item": True,
        },
    )
    assert denied.status_code == 403
    missing_confirm = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={"scope": "classroom", "classroom_id": str(room.id)},
    )
    assert missing_confirm.status_code == 422
    assert missing_confirm.json()["detail"] == "export_confirm_required"
    ok = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={
            "scope": "classroom",
            "classroom_id": str(room.id),
            "exercise_id": str(exercise.id),
            "confirm_contains_student_audio": True,
            "group_by_item": True,
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    # exercise filter keeps only Alice's passage; Bob's question has no session
    assert body["status"] == "succeeded"
    assert body["included_count"] == 1
    assert body["download_name"].startswith("SpeakUp_七年级一班_宠物练习_")
    download = client.get(
        f"{settings.API_V1_STR}/exports/{body['id']}/download",
        headers=headers,
    )
    with _zip(download) as archive:
        rows = _manifest(archive)
        assert len(rows) == 1
        assert rows[0]["student_name"] == "李雷"
        assert rows[0]["exercise_id"] == str(exercise.id)
        assert rows[0]["session_id"] == str(practice.id)
        stored = f"{body['download_name'][:-4]}/{rows[0]['zip_path']}"
        assert stored in archive.namelist()
        assert "文章朗读_" in rows[0]["zip_path"]
        assert "李雷_" in rows[0]["zip_path"]
        assert archive.read(stored) == alice_bytes
    audits = db.exec(
        select(ExportAudit).where(ExportAudit.job_id == uuid.UUID(body["id"]))
    ).all()
    actions = {row.action for row in audits}
    assert {"create", "start", "success", "download"} <= actions
    db.expire_all()
    rejects = db.exec(select(ExportAudit).where(ExportAudit.action == "reject")).all()
    assert any(
        row.detail and row.detail.get("result") == "export_confirm_required"
        for row in rejects
    )
    assert any(
        row.detail and row.detail.get("result") == "forbidden" for row in rejects
    )


def test_teacher_recent_window_excludes_old_and_in_progress(
    client: TestClient, db: Session, sync_exports, tmp_path
) -> None:
    teacher, headers = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, student, _ = _enroll(db, client, room, "李雷")
    recent = _attempt(
        db,
        student,
        _audio(tmp_path, "recent.webm", b"recent"),
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    _attempt(
        db,
        student,
        _audio(tmp_path, "old.webm", b"old"),
        created_at=datetime.now(UTC) - timedelta(days=30),
    )
    _attempt(
        db,
        student,
        _audio(tmp_path, "queued.webm", b"queued"),
        status="queued",
        overall=None,
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    _attempt(
        db,
        student,
        _audio(tmp_path, "scoring.webm", b"scoring"),
        status="scoring",
        overall=None,
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    failed = _attempt(
        db,
        student,
        _audio(tmp_path, "failed.webm", b"failed-audio"),
        status="failed",
        overall=None,
        created_at=datetime.now(UTC) - timedelta(hours=2),
    )
    wide = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={
            "scope": "classroom",
            "classroom_id": str(room.id),
            "confirm_contains_student_audio": True,
            "from": (datetime.now(UTC) - timedelta(days=120)).isoformat(),
            "to": datetime.now(UTC).isoformat(),
        },
    )
    assert wide.status_code == 422
    assert wide.json()["detail"] == "export_range_too_wide"
    # 起止日相距 90 天、结束日取到 23:59:59（教师日期控件的上限）应放行。
    start = datetime(2026, 1, 1, tzinfo=UTC)
    inclusive = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={
            "scope": "classroom",
            "classroom_id": str(room.id),
            "confirm_contains_student_audio": True,
            "from": start.isoformat(),
            "to": (start + timedelta(days=90, seconds=86399)).isoformat(),
        },
    )
    assert inclusive.status_code == 200, inclusive.text
    one_sided = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={
            "scope": "classroom",
            "classroom_id": str(room.id),
            "confirm_contains_student_audio": True,
            "from": start.isoformat(),
        },
    )
    assert one_sided.status_code == 422
    assert one_sided.json()["detail"] == "export_range_too_wide"
    over = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={
            "scope": "classroom",
            "classroom_id": str(room.id),
            "confirm_contains_student_audio": True,
            "from": start.isoformat(),
            "to": (start + timedelta(days=91, seconds=86399)).isoformat(),
        },
    )
    assert over.status_code == 422
    assert over.json()["detail"] == "export_range_too_wide"
    ok = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={
            "scope": "classroom",
            "classroom_id": str(room.id),
            "confirm_contains_student_audio": True,
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "succeeded"
    download = client.get(
        f"{settings.API_V1_STR}/exports/{body['id']}/download", headers=headers
    )
    with _zip(download) as archive:
        rows = _manifest(archive)
        ids = {row["attempt_id"] for row in rows}
        assert ids == {str(recent.id), str(failed.id)}
        failed_row = next(row for row in rows if row["attempt_id"] == str(failed.id))
        assert failed_row["overall"] == ""
        assert failed_row["status"] == "failed"
        assert "NA" in failed_row["zip_path"]
        assert all(row["zip_path"].startswith("文章朗读_") for row in rows)
        assert all("李雷_" in row["zip_path"] for row in rows)
        folders = {row["zip_path"].split("/")[0] for row in rows}
        assert len(folders) == 2
        root = body["download_name"][:-4]
        for row in rows:
            assert f"{root}/{row['zip_path']}" in archive.namelist()


def test_missing_files_and_retry_and_empty(
    client: TestClient, db: Session, sync_exports, tmp_path
) -> None:
    teacher, _ = _teacher(db, client)
    room = _classroom(db, teacher)
    user, student, headers = _enroll(db, client, room, "李雷")
    missing_path = tmp_path / "gone.webm"
    present = _audio(tmp_path, "keep.webm", b"keep-bytes")
    _attempt(db, student, str(missing_path))
    kept = _attempt(db, student, present, title="Keep")
    mixed = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={"scope": "self"},
    )
    assert mixed.status_code == 200, mixed.text
    assert mixed.json()["status"] == "succeeded"
    assert mixed.json()["missing_count"] == 1
    assert mixed.json()["included_count"] == 1
    download = client.get(
        f"{settings.API_V1_STR}/exports/{mixed.json()['id']}/download",
        headers=headers,
    )
    with _zip(download) as archive:
        rows = _manifest(archive)
        missing_row = next(row for row in rows if row["zip_path"] == "")
        assert missing_row["missing"] == "1"
        kept_row = next(row for row in rows if row["attempt_id"] == str(kept.id))
        assert kept_row["missing"] == "0"
        assert (
            f"{mixed.json()['download_name'][:-4]}/{kept_row['zip_path']}"
            in archive.namelist()
        )

    purged_user, purged_student, purged_headers = _enroll(db, client, room, "仅缺失")
    ghost = tmp_path / "purged.webm"
    ghost.write_bytes(b"should-not-pack")
    _attempt(db, purged_student, str(ghost), purged=datetime.now(UTC))
    only_missing = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=purged_headers,
        json={"scope": "self"},
    )
    assert only_missing.status_code == 200, only_missing.text
    failed = only_missing.json()
    assert failed["status"] == "failed"
    assert failed["error"] == "export_all_missing"
    assert failed["download_name"]
    job = db.get(ExportJob, uuid.UUID(failed["id"]))
    assert job is not None
    assert job.artifact_relpath is None
    blocked = client.get(
        f"{settings.API_V1_STR}/exports/{failed['id']}/download",
        headers=purged_headers,
    )
    assert blocked.status_code == 409

    ghost.write_bytes(b"restored-bytes")
    # purged flag still excludes it; clear the flag so retry can pack the file
    row = db.exec(select(Attempt).where(Attempt.student_id == purged_student.id)).one()
    row.audio_purged_at = None
    db.add(row)
    db.commit()
    retried = client.post(
        f"{settings.API_V1_STR}/exports/{failed['id']}/retry",
        headers=purged_headers,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "succeeded"
    packed = client.get(
        f"{settings.API_V1_STR}/exports/{failed['id']}/download",
        headers=purged_headers,
    )
    with _zip(packed) as archive:
        rows = _manifest(archive)
        assert rows[0]["missing"] == "0"
        stored = f"{retried.json()['download_name'][:-4]}/{rows[0]['zip_path']}"
        assert archive.read(stored) == b"restored-bytes"

    empty_user = create_student_user(db, full_name="空")
    assert empty_user.username is not None
    empty_headers = login_headers(client, empty_user.username)
    empty = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=empty_headers,
        json={"scope": "self"},
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["status"] == "failed"
    assert empty.json()["error"] == "export_empty"
    empty_job = db.get(ExportJob, uuid.UUID(empty.json()["id"]))
    assert empty_job is not None and empty_job.artifact_relpath is None
    # silence unused in case of refactor
    assert user.id


def test_hard_reject_over_size_limit(
    client: TestClient,
    db: Session,
    sync_exports,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EXPORT_MAX_BYTES", 8)
    teacher, _ = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, student, headers = _enroll(db, client, room, "李雷")
    _attempt(db, student, _audio(tmp_path, "big.webm", b"0123456789abcdef"))
    response = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={"scope": "self"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "export_too_large"
    assert db.exec(select(ExportJob)).all() == []
    audit = db.exec(select(ExportAudit).where(ExportAudit.action == "reject")).all()
    assert audit and audit[-1].detail is not None
    assert audit[-1].detail.get("result") == "export_too_large"


def test_download_auth_expire_and_list_scope(
    client: TestClient,
    db: Session,
    sync_exports,
    tmp_path,
    superuser_token_headers: dict[str, str],
) -> None:
    teacher, teacher_headers = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, student, headers = _enroll(db, client, room, "李雷")
    _attempt(db, student, _audio(tmp_path, "mine.webm", b"mine"))
    created = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={"scope": "self"},
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["id"]
    other, other_headers = _teacher(db, client, name="旁听")
    assert (
        client.get(
            f"{settings.API_V1_STR}/exports/{job_id}", headers=other_headers
        ).status_code
        == 403
    )
    admin = client.get(
        f"{settings.API_V1_STR}/exports/{job_id}", headers=superuser_token_headers
    )
    assert admin.status_code == 200
    own_list = client.get(f"{settings.API_V1_STR}/exports", headers=headers)
    assert own_list.status_code == 200
    assert own_list.json()["count"] == 1
    assert own_list.json()["unseen_ready"] == 1
    teacher_list = client.get(f"{settings.API_V1_STR}/exports", headers=teacher_headers)
    assert teacher_list.json()["count"] == 0
    first = client.get(
        f"{settings.API_V1_STR}/exports/{job_id}/download", headers=headers
    )
    assert first.status_code == 200
    listed = client.get(f"{settings.API_V1_STR}/exports", headers=headers)
    assert listed.json()["unseen_ready"] == 0

    job = db.get(ExportJob, uuid.UUID(job_id))
    assert job is not None
    job.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    job.status = ExportJobStatus.SUCCEEDED
    db.add(job)
    db.commit()
    expired = client.get(
        f"{settings.API_V1_STR}/exports/{job_id}/download", headers=headers
    )
    assert expired.status_code == 410
    assert expired.json()["detail"] == "export_expired"
    db.expire_all()
    job = db.get(ExportJob, uuid.UUID(job_id))
    assert job is not None
    assert job.status == ExportJobStatus.EXPIRED
    assert job.artifact_relpath is None
    # sweeper is idempotent on already-expired rows
    assert expire_due_exports(db) == 0
    assert other.id


def test_in_progress_cap(
    client: TestClient, db: Session, hold_exports, tmp_path
) -> None:
    teacher, _ = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, student, headers = _enroll(db, client, room, "李雷")
    _attempt(db, student, _audio(tmp_path, "a.webm", b"a"))
    first = client.post(
        f"{settings.API_V1_STR}/exports", headers=headers, json={"scope": "self"}
    )
    second = client.post(
        f"{settings.API_V1_STR}/exports", headers=headers, json={"scope": "self"}
    )
    third = client.post(
        f"{settings.API_V1_STR}/exports", headers=headers, json={"scope": "self"}
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "queued"
    assert third.status_code == 429
    assert third.json()["detail"] == "export_too_many_in_progress"
    rows = db.exec(
        select(ExportJob).where(col(ExportJob.requester_user_id) == _user.id)
    ).all()
    assert len(rows) == 2


def test_filename_collision_appends_attempt_id(
    client: TestClient, db: Session, sync_exports, tmp_path
) -> None:
    teacher, _ = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, student, headers = _enroll(db, client, room, "李雷")
    item_id = uuid.uuid4()
    created = datetime(2026, 10, 27, 1, 2, 3, tzinfo=UTC)
    first = _attempt(
        db,
        student,
        _audio(tmp_path, "one.webm", b"one"),
        item_id=item_id,
        created_at=created,
        title="Pets",
        overall=90,
    )
    second = _attempt(
        db,
        student,
        _audio(tmp_path, "two.webm", b"two"),
        item_id=item_id,
        created_at=created,
        title="Pets",
        overall=90,
    )
    response = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={"scope": "self"},
    )
    assert response.status_code == 200, response.text
    download = client.get(
        f"{settings.API_V1_STR}/exports/{response.json()['id']}/download",
        headers=headers,
    )
    with _zip(download) as archive:
        rows = _manifest(archive)
        paths = {row["attempt_id"]: row["zip_path"] for row in rows}
        assert paths[str(first.id)] != paths[str(second.id)]
        shorts = {first.id.hex[:8], second.id.hex[:8]}
        marked = [
            path for path in paths.values() if any(short in path for short in shorts)
        ]
        assert len(marked) == 1


def test_student_cannot_export_classroom(
    client: TestClient, db: Session, sync_exports
) -> None:
    teacher, _ = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, _student, headers = _enroll(db, client, room, "李雷")
    response = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={
            "scope": "classroom",
            "classroom_id": str(room.id),
            "confirm_contains_student_audio": True,
        },
    )
    assert response.status_code == 403


def test_playback_path_is_not_packed(
    client: TestClient, db: Session, sync_exports, tmp_path
) -> None:
    teacher, _ = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, student, headers = _enroll(db, client, room, "李雷")
    playback = tmp_path / "clip.webm.playback.wav"
    playback.write_bytes(b"not-original")
    original = _audio(tmp_path, "clip.webm", b"original-clip")
    _attempt(db, student, str(playback), title="Cached")
    kept = _attempt(db, student, original, title="Original")
    response = client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json={"scope": "self"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["included_count"] == 1
    assert response.json()["missing_count"] == 1
    download = client.get(
        f"{settings.API_V1_STR}/exports/{response.json()['id']}/download",
        headers=headers,
    )
    with _zip(download) as archive:
        rows = _manifest(archive)
        kept_row = next(row for row in rows if row["attempt_id"] == str(kept.id))
        assert (
            archive.read(
                f"{response.json()['download_name'][:-4]}/{kept_row['zip_path']}"
            )
            == b"original-clip"
        )
        assert all(not name.endswith(".playback.wav") for name in archive.namelist())
