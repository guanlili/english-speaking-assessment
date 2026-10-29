"""学生个人学情 PDF：仅本人、空报告成功、百分位、重试、过期，且不改 ZIP。"""

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF
from pypdf import PdfReader
from sqlmodel import Session, col, delete, select

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
    ExportJobStatus,
    ExportKind,
    PracticeSession,
    User,
)
from app.services.student_report_pdf import (
    FONT_PATH,
    PercentileView,
    StudentReport,
    TrendRow,
    percentile_view,
    render_student_report,
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
    monkeypatch.setattr(settings, "REPORT_PDF_MAX_BYTES", 20 * 1024 * 1024)


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


def _classroom(db: Session, owner: User, *, percentile: bool = True) -> Classroom:
    room = Classroom(
        code=uuid.uuid4().hex[:12],
        name="宠物班",
        owner_id=owner.id,
        class_size=60,
        show_report_percentile=percentile,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def _enroll(db: Session, client: TestClient, room: Classroom, name: str):
    user = create_student_user(db, full_name=name)
    from app.models import Student

    student = Student(classroom_id=room.id, user_id=user.id, display_name=name)
    db.add(student)
    db.commit()
    db.refresh(student)
    assert user.username is not None
    return user, student, login_headers(client, user.username)


def _session(
    db: Session,
    room: Classroom,
    student_id: uuid.UUID,
    day: date | None = None,
) -> PracticeSession:
    row = PracticeSession(
        classroom_id=room.id,
        student_id=student_id,
        band="A2",
        mode="daily",
        session_date=day or datetime.now(UTC).date(),
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
    feedback: str | None = None,
    alignment: dict[str, object] | None = None,
    rubric: dict[str, object] | None = None,
    text: str = "I like pets.",
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
        item_snapshot={"type": item_type, "text": text},
        teacher_feedback=feedback,
        word_alignment=alignment,
        rubric=rubric,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io_bytes(content))
    raw = "\n".join(page.extract_text() or "" for page in reader.pages)
    # 子集字体的 ToUnicode 有时会在字符之间插入 NUL，去掉后再比对正文。
    return raw.replace("\x00", "")


def io_bytes(content: bytes):
    import io

    return io.BytesIO(content)


def _post(client: TestClient, headers: dict[str, str], payload: dict):
    return client.post(
        f"{settings.API_V1_STR}/exports",
        headers=headers,
        json=payload,
    )


def test_percentile_view_rules() -> None:
    assert percentile_view(
        enabled=False, mine=90, sample_size=8, below_others=7
    ).mode == ("hidden")
    low = percentile_view(enabled=True, mine=90, sample_size=4, below_others=3)
    assert low == PercentileView("insufficient")
    missing = percentile_view(enabled=True, mine=None, sample_size=6, below_others=0)
    assert missing.mode == "no_score"
    ranked = percentile_view(enabled=True, mine=90, sample_size=5, below_others=4)
    assert ranked == PercentileView("value", 100)


def test_chinese_font_renders_one_page(tmp_path: Path) -> None:
    assert FONT_PATH.is_file()
    report = StudentReport(
        display_name="王小明",
        classroom_name="宠物班",
        classroom_code="DEMO01",
        start=datetime(2026, 8, 1, tzinfo=UTC),
        end=datetime(2026, 10, 27, tzinfo=UTC),
        session_count=0,
        completed_items=0,
        total_items=0,
        speaking_minutes=0,
        reading_avg=None,
        question_avg=None,
        percentile=PercentileView("insufficient"),
        trend=(TrendRow("2026-10-20", 80.0, 70.0, 2),),
        missed_words=(("cat", 2),),
        dimension_means={},
        weakest_dimension=None,
        evidence=(),
        feedback=(),
        evidence_truncated=False,
        feedback_truncated=False,
        has_active_exam=False,
        scored_count=0,
    )
    dest = tmp_path / "smoke.pdf"
    built = render_student_report(report, dest)
    raw = dest.read_bytes()
    assert raw.startswith(b"%PDF")
    assert built.byte_size == len(raw)
    text = _pdf_text(raw)
    assert "学情报告" in text
    assert "参考分不是官方成绩" in text
    assert "王小明" in text
    assert "班级样本不足" in text
    reader = PdfReader(io_bytes(raw))
    for page in reader.pages:
        assert not page.get("/Annots")
    # 排版库能把中文写进页面，且默认字体对象不是空的
    probe = FPDF()
    probe.add_font("Noto", fname=str(FONT_PATH))
    probe.add_page()
    probe.set_font("Noto", size=16)
    probe.cell(0, 10, "学情报告")
    assert bytes(probe.output()).startswith(b"%PDF")


def test_empty_report_succeeds_without_links(
    client: TestClient, db: Session, sync_exports: None
) -> None:
    _teacher_user, headers_teacher = _teacher(db, client)
    room = _classroom(db, _teacher_user)
    _user, _student, headers = _enroll(db, client, room, "王小明")
    created = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "code": room.code,
            "days": 7,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "succeeded"
    assert body["kind"] == "student_report_pdf"
    assert body["included_count"] == 0
    assert body["error"] is None
    assert body["download_name"].startswith("BELP_学情报告_王小明_")
    assert body["download_name"].endswith(".pdf")
    download = client.get(
        f"{settings.API_V1_STR}/exports/{body['id']}/download",
        headers=headers,
    )
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("application/pdf")
    text = _pdf_text(download.content)
    assert "本阶段暂无已出分作答" in text
    assert "http" not in text.lower()
    assert b"http://" not in download.content
    assert b"https://" not in download.content


def test_teacher_and_cross_user_forbidden(
    client: TestClient, db: Session, sync_exports: None
) -> None:
    teacher, teacher_headers = _teacher(db, client)
    room = _classroom(db, teacher)
    other = _classroom(db, teacher, percentile=True)
    _user, _student, headers = _enroll(db, client, room, "王小明")
    _other_user, _other_student, other_headers = _enroll(db, client, other, "李四")
    teacher_job = _post(
        client,
        teacher_headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_id": str(room.id),
        },
    )
    assert teacher_job.status_code == 403
    assert teacher_job.json()["detail"] == "export_report_student_only"
    classroom_scope = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "classroom",
            "classroom_id": str(room.id),
        },
    )
    assert classroom_scope.status_code == 403
    assert classroom_scope.json()["detail"] == "export_report_student_only"
    foreign = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_id": str(other.id),
            "days": 30,
        },
    )
    assert foreign.status_code == 403
    assert foreign.json()["detail"] == "export_report_forbidden"
    own = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_code": room.code,
            "days": 30,
        },
    )
    assert own.status_code == 200, own.text
    peeked = client.get(
        f"{settings.API_V1_STR}/exports/{own.json()['id']}",
        headers=other_headers,
    )
    assert peeked.status_code == 403
    stolen = client.get(
        f"{settings.API_V1_STR}/exports/{own.json()['id']}/download",
        headers=other_headers,
    )
    assert stolen.status_code == 403


def test_custom_range_capped_at_90_days(
    client: TestClient, db: Session, sync_exports: None
) -> None:
    teacher, _headers = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, _student, headers = _enroll(db, client, room, "王小明")
    now = datetime.now(UTC)
    too_wide = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_id": str(room.id),
            "from": (now - timedelta(days=120)).isoformat(),
            "to": now.isoformat(),
        },
    )
    assert too_wide.status_code == 422
    assert too_wide.json()["detail"] == "export_range_too_wide"
    narrow = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_id": str(room.id),
            "from": (now - timedelta(days=10)).isoformat(),
            "to": now.isoformat(),
        },
    )
    assert narrow.status_code == 200, narrow.text
    defaulted = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_id": str(room.id),
        },
    )
    assert defaulted.status_code == 200, defaulted.text
    window = defaulted.json()["filter"]
    start = datetime.fromisoformat(window["from"])
    end = datetime.fromisoformat(window["to"])
    assert timedelta(days=89) <= (end - start) <= timedelta(days=91)


def test_percentile_on_off_and_small_sample(
    client: TestClient, db: Session, sync_exports: None
) -> None:
    teacher, teacher_headers = _teacher(db, client)
    room = _classroom(db, teacher, percentile=True)
    created = client.post(
        f"{settings.API_V1_STR}/classes",
        headers=teacher_headers,
        json={"name": "开关班", "class_size": 30},
    )
    assert created.status_code == 200, created.text
    assert created.json()["show_report_percentile"] is True
    when = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    names = ["泄漏甲", "泄漏乙", "泄漏丙", "泄漏丁"]
    scores = [13, 27, 41, 63]
    for name, score in zip(names, scores, strict=True):
        _user, student, _headers = _enroll(db, client, room, name)
        practice = _session(db, room, student.id, when.date())
        _attempt(
            db,
            student.id,
            practice.id,
            overall=score,
            created_at=when,
            text="secret prompt",
        )
    _user, me, headers = _enroll(db, client, room, "本人小明")
    mine = _session(db, room, me.id, when.date())
    _attempt(
        db,
        me.id,
        mine.id,
        overall=90,
        created_at=when,
        text="I like pets.",
        feedback="多读一遍 https://evil.example/signed?token=abc",
        rubric={"fluency": 1, "vocabulary": 3, "grammar": 3, "task": 3},
    )
    _attempt(
        db,
        me.id,
        mine.id,
        item_type="passage",
        overall=88,
        created_at=when,
        alignment={"words": [{"text": "cat", "status": "missing"}]},
        text="I have a cat.",
    )

    hidden = client.patch(
        f"{settings.API_V1_STR}/classes/{room.code}/report-settings",
        headers=teacher_headers,
        json={"show_report_percentile": False},
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["show_report_percentile"] is False
    off = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_id": str(room.id),
            "days": 30,
        },
    )
    assert off.status_code == 200, off.text
    off_pdf = client.get(
        f"{settings.API_V1_STR}/exports/{off.json()['id']}/download",
        headers=headers,
    )
    off_text = _pdf_text(off_pdf.content)
    assert "超过班级" not in off_text
    assert "班级样本不足" not in off_text
    assert "泄漏甲" not in off_text
    for score in scores:
        # 作答编号是十六进制，日期里也会出现数字；只查写成一位小数的分数。
        assert f"{score}.0" not in off_text

    shown = client.patch(
        f"{settings.API_V1_STR}/classes/{room.code}/report-settings",
        headers=teacher_headers,
        json={"show_report_percentile": True},
    )
    assert shown.status_code == 200, shown.text
    on = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_id": str(room.id),
            "from": "2026-10-01T00:00:00+00:00",
            "to": "2026-10-27T23:59:59+00:00",
        },
    )
    assert on.status_code == 200, on.text
    on_pdf = client.get(
        f"{settings.API_V1_STR}/exports/{on.json()['id']}/download",
        headers=headers,
    )
    assert on_pdf.headers["content-type"].startswith("application/pdf")
    on_text = _pdf_text(on_pdf.content)
    assert "超过班级 100%" in on_text
    assert "本人小明" in on_text
    assert "cat" in on_text
    assert "流利度" in on_text
    assert "多读一遍" in on_text
    assert "请在 App 中打开" in on_text
    assert "evil.example" not in on_text
    assert "http" not in on_text.lower()
    assert "token=" not in on_text
    for name in names:
        assert name not in on_text
    for score in scores:
        assert f"{score}.0" not in on_text
    assert on.json()["filter"].get("kind") == "student_report_pdf"
    for name in names:
        assert name not in str(on.json()["filter"])

    room.show_report_percentile = True
    db.add(room)
    db.commit()
    # 去掉一名同学后样本变为 4（含本人），只提示样本不足
    from app.models import Student

    extra = db.exec(
        select(Student).where(
            Student.display_name == "泄漏丁",
            Student.classroom_id == room.id,
        )
    ).first()
    assert extra is not None
    db.exec(delete(Attempt).where(col(Attempt.student_id) == extra.id))
    db.exec(delete(PracticeSession).where(col(PracticeSession.student_id) == extra.id))
    db.delete(extra)
    db.commit()
    small = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_id": str(room.id),
            "days": 90,
        },
    )
    assert small.status_code == 200, small.text
    small_pdf = client.get(
        f"{settings.API_V1_STR}/exports/{small.json()['id']}/download",
        headers=headers,
    )
    small_text = _pdf_text(small_pdf.content)
    assert "班级样本不足" in small_text
    assert "超过班级" not in small_text
    assert "泄漏甲" not in small_text


def test_worker_rejects_mismatched_requester(db: Session, client: TestClient) -> None:
    teacher, _headers = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, student, _student_headers = _enroll(db, client, room, "王小明")
    now = datetime.now(UTC)
    job = ExportJob(
        requester_user_id=teacher.id,
        scope="self",
        kind=ExportKind.STUDENT_REPORT_PDF,
        filter_json={
            "kind": ExportKind.STUDENT_REPORT_PDF,
            "scope": "self",
            "requester_user_id": str(teacher.id),
            "classroom_id": str(room.id),
            "from": (now - timedelta(days=7)).isoformat(),
            "to": now.isoformat(),
        },
        status=ExportJobStatus.QUEUED,
        download_name="BELP_学情报告_越权.pdf",
    )
    db.add(job)
    db.commit()
    process_export_job(job.id)
    db.refresh(job)
    assert job.status == "failed"
    assert job.error == "export_report_forbidden"
    assert job.artifact_relpath is None
    assert list(Path(settings.EXPORT_STORAGE_DIR).glob("*.pdf")) == []
    mismatched = ExportJob(
        requester_user_id=student.user_id,  # type: ignore[arg-type]
        scope="self",
        kind=ExportKind.STUDENT_REPORT_PDF,
        filter_json={
            "kind": ExportKind.STUDENT_REPORT_PDF,
            "requester_user_id": str(uuid.uuid4()),
            "classroom_id": str(room.id),
            "from": (now - timedelta(days=7)).isoformat(),
            "to": now.isoformat(),
        },
        status=ExportJobStatus.QUEUED,
        download_name="BELP_学情报告_错人.pdf",
    )
    db.add(mismatched)
    db.commit()
    process_export_job(mismatched.id)
    db.refresh(mismatched)
    assert mismatched.status == "failed"
    assert mismatched.error == "export_report_forbidden"


def test_retry_and_expire(
    client: TestClient, db: Session, sync_exports: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher, _headers = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, _student, headers = _enroll(db, client, room, "王小明")
    real = render_student_report
    calls = {"n": 0}

    def flaky(report: StudentReport, dest: Path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(report, dest)

    monkeypatch.setattr("app.services.student_report_pdf.render_student_report", flaky)
    created = _post(
        client,
        headers,
        {
            "kind": "student_report_pdf",
            "scope": "self",
            "classroom_id": str(room.id),
            "days": 7,
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "failed"
    assert created.json()["error"].startswith("export_failed")
    retried = client.post(
        f"{settings.API_V1_STR}/exports/{created.json()['id']}/retry",
        headers=headers,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "succeeded"
    job = db.get(ExportJob, uuid.UUID(retried.json()["id"]))
    assert job is not None
    job.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.add(job)
    db.commit()
    expired = client.get(
        f"{settings.API_V1_STR}/exports/{job.id}/download",
        headers=headers,
    )
    assert expired.status_code == 410
    assert expired.json()["detail"] == "export_expired"
    db.refresh(job)
    assert job.status == "expired"
    assert list(Path(settings.EXPORT_STORAGE_DIR).glob(f"{job.id}.pdf")) == []


def test_audio_zip_kind_stays_zip(
    client: TestClient, db: Session, sync_exports: None
) -> None:
    teacher, _headers = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, _student, headers = _enroll(db, client, room, "王小明")
    created = _post(client, headers, {"scope": "self"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["kind"] == "audio_zip"
    assert body["status"] == "failed"
    assert body["error"] == "export_empty"
    assert (body["download_name"] or "").endswith(".zip")


def test_report_settings_student_forbidden(client: TestClient, db: Session) -> None:
    teacher, teacher_headers = _teacher(db, client)
    room = _classroom(db, teacher)
    _user, _student, headers = _enroll(db, client, room, "王小明")
    denied = client.patch(
        f"{settings.API_V1_STR}/classes/{room.code}/report-settings",
        headers=headers,
        json={"show_report_percentile": False},
    )
    assert denied.status_code == 403
    kept = client.patch(
        f"{settings.API_V1_STR}/classes/{room.code}/report-settings",
        headers=teacher_headers,
        json={"show_report_percentile": False},
    )
    assert kept.status_code == 200, kept.text
    db.refresh(room)
    assert room.show_report_percentile is False
