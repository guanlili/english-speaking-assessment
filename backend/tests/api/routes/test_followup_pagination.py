"""Follow-up filtering is performed in SQL before the bounded list page."""

import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete

from app.api.routes.class_followups import FollowupPublic
from app.models import (
    Attempt,
    Classroom,
    ClassroomExercise,
    PracticeSession,
    Student,
    get_datetime_utc,
)
from tests.utils.credential import make_student


@dataclass
class FollowupRound:
    db: Session
    client: TestClient
    code: str
    classroom_id: uuid.UUID
    teacher: dict[str, str]
    students: list[Student]
    headers: list[dict[str, str]]
    now: datetime
    version: int = 0

    @property
    def endpoint(self) -> str:
        return f"/api/v1/classes/{self.code}/followups"

    def task(
        self,
        recipients: list[Student],
        *,
        status: str = "followup",
        created_at: datetime | None = None,
        item_count: int = 1,
    ) -> ClassroomExercise:
        self.version += 1
        task = ClassroomExercise(
            classroom_id=self.classroom_id,
            version_no=self.version,
            title=f"Frozen follow-up {self.version}",
            status=status,
            created_at=created_at or self.now,
            target_students=[
                {"student_id": str(s.id), "display_name": s.display_name}
                for s in recipients
            ],
            snapshot_items=[
                {"id": str(uuid.uuid4()), "type": "repeat", "text": "Frozen item."}
                for _ in range(item_count)
            ]
            + [{"id": str(uuid.uuid4()), "type": "instruction", "text": "Read me."}],
        )
        self.db.add(task)
        self.db.flush()
        return task

    def practice(self, task: ClassroomExercise, student: Student) -> PracticeSession:
        ps = PracticeSession(
            classroom_id=self.classroom_id,
            student_id=student.id,
            assignment_id=task.id,
            mode="followup",
            band="B1",
            session_date=self.now.date(),
        )
        self.db.add(ps)
        self.db.flush()
        return ps

    def answer(
        self,
        task: ClassroomExercise,
        ps: PracticeSession,
        status: str,
        *,
        item_index: int = 0,
        created_at: datetime | None = None,
        attempt_id: uuid.UUID | None = None,
    ) -> Attempt:
        attempt = Attempt(
            id=attempt_id or uuid.uuid4(),
            session_id=ps.id,
            student_id=ps.student_id,
            item_id=uuid.UUID(str(task.snapshot_items[item_index]["id"])),
            item_type="repeat",
            audio_path="unused-followup-pagination",
            duration_s=2,
            status=status,
            created_at=created_at or self.now,
        )
        self.db.add(attempt)
        return attempt

    def page(
        self,
        headers: dict[str, str],
        status: str = "active",
        offset: int = 0,
        limit: int = 50,
    ) -> list[FollowupPublic]:
        self.db.commit()
        response = self.client.get(
            self.endpoint,
            headers=headers,
            params={"status": status, "offset": offset, "limit": limit},
        )
        assert response.status_code == 200, response.text
        return [FollowupPublic.model_validate(row) for row in response.json()]


@pytest.fixture
def followup_round(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> Generator[FollowupRound]:
    # Use only conftest's guarded app_test engine; never create another engine.
    assert db.get_bind().engine.url.database == "app_test"
    response = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
    )
    assert response.status_code == 200, response.text
    classroom_id = uuid.UUID(response.json()["id"])
    code = response.json()["code"]
    accounts = [make_student(db, client, code, name) for name in ("Alice", "Ben")]
    students = [db.get(Student, uuid.UUID(a["student"]["id"])) for a in accounts]
    assert all(s is not None for s in students)
    fixture = FollowupRound(
        db=db,
        client=client,
        code=code,
        classroom_id=classroom_id,
        teacher=superuser_token_headers,
        students=[s for s in students if s is not None],
        headers=[a["headers"] for a in accounts],
        now=get_datetime_utc(),
    )
    try:
        yield fixture
    finally:
        db.rollback()
        # Delete only this fixture's rows, including pending attempts (no workers).
        db.exec(
            delete(Attempt).where(
                col(Attempt.student_id).in_([s.id for s in fixture.students])
            )
        )  # type: ignore[call-overload]
        db.exec(delete(Classroom).where(col(Classroom.id) == classroom_id))  # type: ignore[call-overload]
        db.commit()


def test_history_and_other_students_cannot_crowd_out_active(
    followup_round: FollowupRound,
) -> None:
    r = followup_round
    alice, ben = r.students
    active = r.task([alice], created_at=r.now - timedelta(days=10))
    # More than the old limit, mixing completed and withdrawn tasks.
    for index in range(60):
        task = r.task([alice], status="followup_closed" if index % 2 else "followup")
        if task.status == "followup":
            r.answer(task, r.practice(task, alice), "done")
    for _ in range(60):
        r.task([ben], created_at=r.now + timedelta(seconds=1))
    assert [row.id for row in r.page(r.headers[0], limit=1)] == [active.id]
    assert r.page(r.headers[0], offset=1, limit=1) == []
    history = r.page(r.headers[0], "history", limit=100)
    assert len(history) == 60 and all(row.id != active.id for row in history)
    assert all(
        [row.student_id for row in task.targets] == [alice.id] for task in history
    )
    teacher_active = r.page(r.teacher, limit=100)
    assert len(teacher_active) == 61 and active.id in {row.id for row in teacher_active}
    assert len(r.page(r.teacher, "history", limit=100)) == 60
    assert len(r.page(r.headers[0], "all", limit=100)) == 61
    assert len(r.page(r.headers[1], "all", limit=100)) == 60


@pytest.mark.parametrize("task_status", ["followup", "followup_closed"])
def test_tied_created_at_has_stable_pages_and_lookahead(
    followup_round: FollowupRound, task_status: str
) -> None:
    r = followup_round
    tasks = [r.task([r.students[0]], status=task_status) for _ in range(23)]
    status = "active" if task_status == "followup" else "history"
    expected = sorted((task.id for task in tasks), reverse=True)
    for headers in (r.teacher, r.headers[0]):
        pages = [
            r.page(headers, status, offset=offset, limit=7) for offset in (0, 7, 14, 21)
        ]
        assert [row.id for page in pages for row in page] == expected
        assert [len(page) for page in pages] == [7, 7, 7, 2]
        assert [row.id for row in r.page(headers, status, limit=8)][:7] == expected[:7]
        assert [
            row.id for row in r.page(headers, status, offset=7, limit=8)
        ] == expected[7:15]
        assert [
            row.id for row in r.page(headers, status, offset=7, limit=7)
        ] == expected[7:14]
        assert r.page(headers, status, offset=23, limit=7) == []
    # Existing callers without status retain the combined list contract.
    r.db.commit()
    response = r.client.get(r.endpoint, headers=r.teacher)
    assert response.status_code == 200
    assert [uuid.UUID(row["id"]) for row in response.json()] == expected


@pytest.mark.parametrize("latest_status", ["queued", "scoring", "failed", "done"])
def test_completion_uses_latest_attempt_and_every_frozen_item(
    followup_round: FollowupRound, latest_status: str
) -> None:
    r = followup_round
    task = r.task(r.students, item_count=2)
    alice_ps = r.practice(task, r.students[0])
    # A larger UUID cannot outrank a newer timestamp.
    r.answer(
        task,
        alice_ps,
        "done",
        created_at=r.now - timedelta(seconds=1),
        attempt_id=uuid.UUID(int=(1 << 128) - 1),
    )
    # Deliberately tied timestamps: UUID is the required secondary order.
    r.answer(task, alice_ps, "done", attempt_id=uuid.UUID(int=1))
    r.answer(task, alice_ps, latest_status, attempt_id=uuid.UUID(int=2))
    r.answer(task, alice_ps, "done", item_index=1)
    # A non-snapshot success must not replace a missing/failed snapshot item.
    unrelated = Attempt(
        session_id=alice_ps.id,
        student_id=alice_ps.student_id,
        item_id=uuid.uuid4(),
        status="done",
        audio_path="unused-followup-pagination",
        duration_s=2,
    )
    r.db.add(unrelated)
    completed = latest_status == "done"
    own_status = "history" if completed else "active"
    own = r.page(r.headers[0], own_status)[0]
    assert own.item_count == 2
    assert own.targets[0].done_count == (2 if completed else 1)
    assert own.targets[0].total_count == 2
    assert own.targets[0].has_pending == (latest_status in ("queued", "scoring"))
    assert own.targets[0].has_failures == (latest_status == "failed")
    assert r.page(r.headers[0], "active" if completed else "history") == []
    # Alice's completion does not complete Ben's work or the teacher's task.
    assert [row.id for row in r.page(r.teacher)] == [task.id]
    assert [row.id for row in r.page(r.headers[1])] == [task.id]
    assert r.page(r.teacher, "history") == []
    # Later successes clear failure/pending flags and finally finish the task.
    r.answer(task, alice_ps, "done", created_at=r.now + timedelta(seconds=1))
    ben_ps = r.practice(task, r.students[1])
    r.answer(task, ben_ps, "done")
    assert [row.id for row in r.page(r.teacher)] == [task.id]
    r.answer(task, ben_ps, "done", item_index=1)
    assert r.page(r.teacher) == []
    finished = r.page(r.teacher, "history")[0]
    assert all(row.done_count == 2 for row in finished.targets)
    assert all(not row.has_pending and not row.has_failures for row in finished.targets)


def test_withdrawal_and_roster_changes_preserve_history(
    followup_round: FollowupRound,
) -> None:
    r = followup_round
    task = r.task(r.students)
    r.answer(task, r.practice(task, r.students[0]), "done")
    r.answer(task, r.practice(task, r.students[1]), "done")
    r.page(r.teacher, "history")
    # Names/roster change after publication; completion still uses the fixed targets.
    r.students[0].display_name = "Alice renamed"
    r.students[1].user_id = None
    r.db.add_all(r.students)
    history = r.page(r.teacher, "history")
    assert [row.id for row in history] == [task.id]
    assert [row.display_name for row in history[0].targets] == ["Alice", "Ben"]
    assert r.page(r.teacher) == []
    r.db.commit()
    assert r.client.get(r.endpoint, headers=r.headers[1]).status_code == 404
    withdrawn = r.task([r.students[0]], status="followup_closed")
    assert r.page(r.headers[0]) == []
    assert {row.id for row in r.page(r.headers[0], "history")} == {
        task.id,
        withdrawn.id,
    }
    assert {row.id for row in r.page(r.teacher, "history")} == {task.id, withdrawn.id}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": -1},
        {"limit": 101},
        {"offset": -1},
        {"offset": 1_000_001},
        {"status": "done"},
        {"offset": "not-an-integer"},
    ],
)
def test_list_pagination_validation(
    followup_round: FollowupRound, params: dict[str, str | int]
) -> None:
    r = followup_round
    response = r.client.get(r.endpoint, headers=r.teacher, params=params)
    assert response.status_code == 422, response.text


def test_pagination_does_not_bypass_class_permissions(
    followup_round: FollowupRound, normal_user_token_headers: dict[str, str]
) -> None:
    r = followup_round
    r.task(r.students)
    r.db.commit()
    for status in ("active", "history", "all"):
        response = r.client.get(
            r.endpoint,
            headers=normal_user_token_headers,
            params={"status": status, "offset": 1, "limit": 1},
        )
        assert response.status_code == 403, response.text
