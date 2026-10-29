"""教师班级分析报告 PDF：权限、内容、空态、窗口上限。"""

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlmodel import Session, delete

from app.api.deps import get_export_submitter
from app.core.config import settings
from app.core.security import get_password_hash
from app.exporting.worker import process_export_job
from app.main import app
from app.models import (
    Attempt,
    Classroom,
    ExportAudit,
    ExportJob,
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
    monkeypatch.setattr(settings, "EXPORT_MAX_IN_PROGRESS", 2)


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


def _teacher(db: Session, client: TestClient) -> tuple[User, dict[str, str]]:
    email = random_email()
    password = random_lower_string()
    user = User(
        email=email,
        full_name="王老师",
        role="teacher",
        hashed_password=get_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, user_authentication_headers(
        client=client, email=email, password=password
    )


def _classroom(db: Session, owner: User) -> Classroom:
    room = Classroom(
        code=uuid.uuid4().hex[:12],
        name="宠物班",
        owner_id=owner.id,
        class_size=60,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def _enroll(db: Session, client: TestClient, room: Classroom, name: str):
    user = create_student_user(db, full_name=name)
    student = Student(classroom_id=room.id, user_id=user.id, display_name=name)
    db.add(student)
    db.commit()
    db.refresh(student)
    return user, student


def _session(db: Session, room: Classroom, student_id: uuid.UUID) -> PracticeSession:
    row = PracticeSession(
        classroom_id=room.id,
        student_id=student_id,
        band="A2",
        mode="daily",
        session_date=datetime.now(UTC).date(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _attempt(
    db: Session,
    student_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    item_type: str = "question",
    overall: int | None = 80,
    created_at: datetime | None = None,
    title: str = "Pets",
) -> Attempt:
    row = Attempt(
        item_type=item_type,
        item_id=uuid.uuid4(),
        student_id=student_id,
        session_id=session_id,
        audio_path="unused",
        audio_mime="audio/webm",
        duration_s=30,
        status="done",
        overall=overall,
        completeness=70 if item_type == "repeat" else None,
        item_snapshot={"type": item_type, "title": title, "text": "I like pets."},
        created_at=created_at or datetime.now(UTC) - timedelta(days=1),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    return raw.replace("\x00", "")


def _post(client: TestClient, headers: dict[str, str], payload: dict):
    return client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json=payload,
    )


def test_class_report_succeeds(
    client: TestClient, db: Session, sync_exports: None
) -> None:
    teacher, headers = _teacher(db, client)
    room = _classroom(db, teacher)
    _u1, s1 = _enroll(db, client, room, "李雷")
    _u2, s2 = _enroll(db, client, room, "韩梅梅")
    _u3, s3 = _enroll(db, client, room, "无作答")
    sess1 = _session(db, room, s1.id)
    sess2 = _session(db, room, s2.id)
    a1 = _attempt(db, s1.id, sess1.id, overall=90, title="Pets")
    _attempt(db, s1.id, sess1.id, item_type="repeat", overall=70)
    _attempt(db, s2.id, sess2.id, overall=60, title="Sports")
    created = _post(
        client,
        headers,
        {
            "kind": "class_report_pdf",
            "scope": "classroom",
            "classroom_id": str(room.id),
            "days": 90,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "succeeded", body
    assert body["kind"] == "class_report_pdf"
    assert body["included_count"] == 3
    assert body["download_name"].startswith("SpeakUp_班级报告_宠物班_")
    assert body["download_name"].endswith(".pdf")
    download = client.get(
        f"{settings.API_V1_STR}/exports/{body['id']}/download",
        headers=headers,
    )
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("application/pdf")
    text = _pdf_text(download.content)
    assert "班级分析报告" in text
    assert "宠物班" in text
    assert "李雷" in text and "韩梅梅" in text
    assert "无作答" in text
    assert "题项对比" in text
    assert str(a1.id) not in text  # 作答证据不放 ID，只有统计
    assert "http" not in text.lower()


def test_permissions_and_payload_guards(
    client: TestClient, db: Session, sync_exports: None
) -> None:
    teacher, headers = _teacher(db, client)
    room = _classroom(db, teacher)
    other_teacher, other_headers = _teacher(db, client)
    student_user, _student = _enroll(db, client, room, "李雷")
    assert student_user.username is not None
    student_headers = login_headers(client, student_user.username)
    # 学生不能导出班级报告
    denied = _post(
        client,
        student_headers,
        {
            "kind": "class_report_pdf",
            "scope": "classroom",
            "classroom_id": str(room.id),
        },
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"] == "export_class_report_teacher_only"
    # 非本班 owner 教师不能导出
    forbidden = _post(
        client,
        other_headers,
        {
            "kind": "class_report_pdf",
            "scope": "classroom",
            "classroom_id": str(room.id),
        },
    )
    assert forbidden.status_code == 403, forbidden.text
    # 不支持练习/轮次过滤
    unsupported = _post(
        client,
        headers,
        {
            "kind": "class_report_pdf",
            "scope": "classroom",
            "classroom_id": str(room.id),
            "exercise_id": str(uuid.uuid4()),
        },
    )
    assert unsupported.status_code == 422, unsupported.text
    assert unsupported.json()["detail"] == "export_exercise_not_supported"


def test_empty_report_and_range_cap(
    client: TestClient, db: Session, sync_exports: None
) -> None:
    teacher, headers = _teacher(db, client)
    room = _classroom(db, teacher)
    _enroll(db, client, room, "李雷")
    created = _post(
        client,
        headers,
        {
            "kind": "class_report_pdf",
            "scope": "classroom",
            "classroom_id": str(room.id),
            "days": 7,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "succeeded"
    assert body["included_count"] == 0
    download = client.get(
        f"{settings.API_V1_STR}/exports/{body['id']}/download",
        headers=headers,
    )
    assert download.status_code == 200
    assert "窗口内暂无已出分作答" in _pdf_text(download.content)
    too_wide = _post(
        client,
        headers,
        {
            "kind": "class_report_pdf",
            "scope": "classroom",
            "classroom_id": str(room.id),
            "from": (datetime.now(UTC) - timedelta(days=200)).isoformat(),
            "to": datetime.now(UTC).isoformat(),
        },
    )
    assert too_wide.status_code == 422, too_wide.text
    assert too_wide.json()["detail"] == "export_range_too_wide"
