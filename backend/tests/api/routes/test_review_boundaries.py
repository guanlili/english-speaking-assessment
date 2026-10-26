"""Security-boundary regression guards from the 2026-10-12 review.

The six P0 issues found that day were fixed on master (PR #121); these tests
pin the fixed behavior. The rubric-metrics gap flagged as P3 in the same
review was fixed later and is pinned here as well.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.api.deps import get_scoring_submitter
from app.api.routes import attempts as attempts_route
from app.core.config import settings
from app.main import app
from app.models import Classroom, ClassroomExercise, ExamItemSettings, Passage
from app.scoring.audio_convert import AudioProbeResult
from app.services import exam
from tests.api.routes.test_exam import _cleanup_classroom, _resp_json, _today
from tests.utils.audio import wav_upload
from tests.utils.credential import make_student


@pytest.fixture
def review_exam(client, superuser_token_headers, db, monkeypatch, tmp_path):
    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code)
    ids = [uuid.uuid4(), uuid.uuid4()]
    passages = [
        Passage(
            id=item_id,
            slug=f"review-{item_id}",
            title="Read",
            text="Read this.",
            cefr_band="B1",
        )
        for item_id in ids
    ]
    db.add_all(passages)
    db.commit()
    exercise = ClassroomExercise(
        classroom_id=uuid.UUID(classroom["id"]),
        is_exam=True,
        time_limit_minutes=5,
        snapshot_items=[
            {
                "id": str(item_id),
                "type": "passage",
                "text": "Read this.",
                "suggested_seconds": 5,
                "exam_flow": ExamItemSettings(wait_seconds=0).model_dump(),
            }
            for item_id in ids
        ],
    )
    db.add(exercise)
    db.flush()
    row = db.get(Classroom, exercise.classroom_id)
    row.current_exercise_id = exercise.id
    db.add(row)
    db.commit()
    clock = [datetime.now(UTC)]
    monkeypatch.setattr(exam, "_now", lambda: clock[0])
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))
    app.dependency_overrides[get_scoring_submitter] = lambda: lambda _id: None
    try:
        sid = _today(client, made["headers"], code)["session_id"]
        response = client.post(
            f"/api/v1/classes/{code}/exam/start",
            json={"session_id": sid},
            headers=made["headers"],
        )
        assert response.status_code == 200
        yield client, made["headers"], code, sid, ids, clock
    finally:
        app.dependency_overrides.pop(get_scoring_submitter, None)
        _cleanup_classroom(db, classroom["id"])
        for passage in passages:
            db.delete(passage)
        db.commit()


def upload(ctx, item_id, key):
    client, headers, _code, sid, _ids, _clock = ctx
    return client.post(
        "/api/v1/attempts",
        headers=headers,
        files={"audio": wav_upload(2.0)},
        data={
            "session_id": sid,
            "item_type": "passage",
            "item_id": str(item_id),
            "duration_s": "2",
            "idempotency_key": key,
        },
    )


def test_fixed_key_reused_for_other_item_is_rejected(review_exam):
    ids, clock = review_exam[4:]
    clock[0] += timedelta(seconds=2)
    key = f"review-{uuid.uuid4()}"
    first = upload(review_exam, ids[0], key)
    assert first.status_code == 200, first.text
    second = upload(review_exam, ids[1], key)
    assert second.status_code == 422
    assert second.json()["detail"] == "作答凭证已失效，请重新录音后提交"


def test_fixed_probe_crosses_deadline_rejects_upload(review_exam, monkeypatch):
    ids, clock = review_exam[4:]
    deadline = clock[0] + timedelta(minutes=5)
    clock[0] = deadline - timedelta(seconds=1)

    def probe_crossing_deadline(_data, _suffix):
        clock[0] = deadline + timedelta(seconds=1)
        return AudioProbeResult(2.0, True, 1, 16000)

    monkeypatch.setattr(attempts_route, "probe_audio", probe_crossing_deadline)
    response = upload(review_exam, ids[0], f"review-{uuid.uuid4()}")
    assert response.status_code == 422
    assert response.json()["detail"] == "考试时间已到，已自动交卷"


def test_fixed_idempotency_length_rejected_before_database(review_exam):
    ids, clock = review_exam[4:]
    clock[0] += timedelta(seconds=2)
    # The database column is VARCHAR(64); the Form now enforces max_length=64.
    response = upload(review_exam, ids[0], "x" * 65)
    assert response.status_code == 422
    assert "idempotency_key" in response.text


@pytest.mark.parametrize("bulk", [False, True])
def test_fixed_teacher_cannot_reset_enrolled_admin(client, db, bulk):
    from app import crud
    from app.core import security
    from app.models import UserCreate
    from tests.api.routes.test_students import _cleanup, _login_teacher, _new_classroom

    teacher, teacher_headers = _login_teacher(db, client)
    admin = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"review-{uuid.uuid4().hex}@example.com",
            password=uuid.uuid4().hex,
            full_name="Isolated Review Admin",
            role="admin",
            is_superuser=True,
        ),
    )
    original_hash = admin.hashed_password
    headers = {
        "Authorization": "Bearer "
        + security.create_access_token(
            admin.id, timedelta(minutes=5), role=admin.role, password_hash=original_hash
        )
    }
    classroom_id = None
    try:
        classroom = _new_classroom(client, teacher_headers)
        classroom_id = uuid.UUID(classroom["id"])
        joined = client.post(
            f"/api/v1/classes/{classroom['code']}/join", headers=headers, json={}
        )
        assert joined.status_code == 200, joined.text
        student_id = joined.json()["id"]
        if bulk:
            response = client.post(
                "/api/v1/students/bulk-reset-password",
                params={"classroom_id": str(classroom_id)},
                headers=teacher_headers,
            )
            assert response.status_code == 200, response.text
            assert response.json()["skipped"] == 1
            assert response.json()["reset"] == 0
        else:
            response = client.post(
                f"/api/v1/students/{student_id}/reset-password", headers=teacher_headers
            )
            assert response.status_code == 403
            assert response.json()["detail"] == "没有权限：只能重置学生账号的密码"
        db.refresh(admin)
        assert admin.hashed_password == original_hash
        login = client.post(
            "/api/v1/login/access-token",
            data={
                "username": admin.email,
                "password": security.DEFAULT_STUDENT_PASSWORD,
            },
        )
        assert login.status_code == 400
    finally:
        _cleanup(db, classroom_id, teacher, admin)


def test_fixed_asr_runs_without_open_transaction(review_exam, db, monkeypatch):
    from app.scoring import worker

    ids, clock = review_exam[4:]
    clock[0] += timedelta(seconds=2)
    response = upload(review_exam, ids[0], f"review-{uuid.uuid4()}")
    assert response.status_code == 200
    observed = []
    with Session(db.get_bind()) as scoring_session:

        class StubAsr:
            name = "mock"

            def transcribe(self, _audio, _mime):
                observed.append(scoring_session.in_transaction())
                return "Read this."

        monkeypatch.setattr(worker, "build_asr_provider", StubAsr)
        worker.process_attempt(scoring_session, uuid.UUID(response.json()["id"]))
    assert observed == [False]


def test_rubric_requests_update_metrics():
    import json

    import httpx

    from app.core import metrics
    from app.scoring.rubric import ArkRubricScorer, RubricQuestionContext

    payload = {
        "fluency": 2,
        "vocabulary": 2,
        "grammar": 2,
        "task": 2,
        "advice": [],
        "upgrades": [],
    }
    metrics.reset_for_tests()
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )
    )
    with httpx.Client(transport=transport) as client:
        scorer = ArkRubricScorer(
            api_key="dummy-review-key",
            model="test",
            base_url="https://review.invalid",
            client=client,
        )
        scorer.score(RubricQuestionContext(text="Describe school."), "I like school.")
    # 评审时的 P3 缺口（rubric 调用不上报 metrics）已修复：调用须计入 llm_rubric
    stats = metrics.call_stats()
    assert stats["llm_rubric"]["calls"] == 1.0
    assert stats["llm_rubric"]["failures"] == 0.0
