"""模考模式：确认页显式开考 + 整场限时（服务端强约束）+ 每题一次作答 + 防切屏（次数/离屏时长）+ 监考展示。"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, col, select

from app.models import Passage, PracticeSession
from app.services import exam as exam_service
from tests.utils.audio import wav_upload
from tests.utils.credential import make_student
from tests.utils.utils import random_lower_string


def test_exam_item_deadlines_restore_progress_and_lock_order(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """准备时间不许提前答；未答自动推进，刷新和题库编辑不重置。"""
    from app.models import Classroom, ClassroomExercise

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code)
    headers = made["headers"]
    ids = [uuid.uuid4() for _ in range(3)]
    passages = [
        Passage(
            id=item_id,
            slug=f"exam-{item_id}",
            title="Timed article",
            text="Timed article.",
            cefr_band="B1",
        )
        for item_id in ids[1:]
    ]
    db.add_all(passages)
    db.commit()
    snapshot: list[dict[str, object]] = [
        {
            "type": "question",
            "id": str(ids[0]),
            "text": "Describe your school.",
            "exam_kind": "ielts_p2",
            "prep_seconds": 10,
            "suggested_seconds": 20,
        },
        {
            "type": "passage",
            "id": str(ids[1]),
            "text": "Second article.",
            "suggested_seconds": 20,
        },
        {
            "type": "passage",
            "id": str(ids[2]),
            "text": "Last article.",
            "suggested_seconds": 20,
        },
    ]
    exercise = ClassroomExercise(
        classroom_id=uuid.UUID(classroom["id"]),
        snapshot_items=snapshot,
        is_exam=True,
        time_limit_minutes=30,
    )
    db.add(exercise)
    db.flush()
    row = db.get(Classroom, exercise.classroom_id)
    assert row is not None
    row.current_exercise_id = exercise.id
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    monkeypatch.setattr(exam_service, "_now", lambda: now)
    try:
        plan = _today(client, headers, code)
        start = client.post(
            f"/api/v1/classes/{code}/exam/start",
            json={"session_id": plan["session_id"]},
            headers=headers,
        )
        assert start.status_code == 200
        assert start.json()["current_item_index"] == 0
        assert start.json()["prep_remaining_seconds"] == 10
        assert start.json()["item_remaining_seconds"] == 30
        # 不能在准备时间作答，也不能跳到后面的题。
        for index in (0, 1):
            response = _submit(
                client, headers, code, plan["items"][index], plan["session_id"]
            )
            assert response.status_code == 422
            assert response.json()["detail"] == "本题作答时间已结束或尚未开始"
        now += timedelta(seconds=11)
        refreshed = _today(client, headers, code)
        assert refreshed["exam"]["current_item_index"] == 0
        assert refreshed["exam"]["prep_remaining_seconds"] == 0
        assert refreshed["exam"]["item_remaining_seconds"] == 19
        # 不录音也会在截止时推进。
        now += timedelta(seconds=20)
        refreshed = _today(client, headers, code)
        assert refreshed["exam"]["current_item_index"] == 1
        assert refreshed["exam"]["item_remaining_seconds"] == 19
        now += timedelta(seconds=16)
        late = _submit(client, headers, code, plan["items"][0], plan["session_id"])
        assert late.status_code == 422
        now += timedelta(seconds=24)
        finished = _today(client, headers, code)
        assert finished["exam"]["ended"] is True
        assert finished["exam"]["current_item_index"] == 3
        assert finished["attempts"] == []
    finally:
        _cleanup_classroom(db, classroom["id"])
        for passage in passages:
            db.delete(passage)
        db.commit()


def test_exam_upload_advances_before_scoring_and_preserves_timeout_anchor(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """queued/failed 都锁定一次提交；截止后的短传输不重置下一题计时。"""
    from app.models import Attempt, ClassroomExercise

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code)
    passage = _demo_passage(db)
    another = Passage(
        slug=f"exam-{uuid.uuid4().hex}",
        title="Next article",
        text="We learn together.",
        cefr_band="B1",
        suggested_seconds=20,
    )
    db.add(another)
    db.commit()
    try:
        published = _publish_exam(
            client,
            superuser_token_headers,
            code,
            [
                {"type": "passage", "id": str(passage.id)},
                {"type": "passage", "id": str(another.id)},
            ],
        )
        assert published.status_code == 200
        plan = _today(client, made["headers"], code)
        ps = db.get(PracticeSession, uuid.UUID(plan["session_id"]))
        assert ps is not None
        exercise = db.get(ClassroomExercise, ps.assignment_id)
        assert exercise is not None
        now = datetime.now(UTC)
        ps.exam_started_at = now - timedelta(seconds=10)
        db.add(ps)
        db.commit()
        monkeypatch.setattr(exam_service, "_now", lambda: now)
        answer = Attempt(
            session_id=ps.id,
            student_id=ps.student_id,
            item_type="passage",
            item_id=passage.id,
            audio_path="unused-test-audio",
            duration_s=6,
            status="queued",
            created_at=now,
        )
        db.add(answer)
        db.commit()
        status = exam_service.exam_status_payload(db, ps, exercise)
        assert status.current_item_index == 1
        assert status.item_remaining_seconds == 20
        answer.status = "failed"
        db.add(answer)
        db.commit()
        now += timedelta(seconds=5)
        refreshed = _today(client, made["headers"], code)
        assert refreshed["exam"]["current_item_index"] == 1
        assert refreshed["exam"]["item_remaining_seconds"] == 15
        second = _submit(
            client, made["headers"], code, plan["items"][0], plan["session_id"]
        )
        assert second.status_code == 422
        assert "一次" in second.json()["detail"]
        # 模拟先到时切题、录音随后在传输窗口落库。
        answer.created_at = ps.exam_started_at + timedelta(
            seconds=passage.suggested_seconds + 2
        )
        db.add(answer)
        db.commit()
        now = answer.created_at + timedelta(seconds=1)
        status = exam_service.exam_status_payload(db, ps, exercise)
        assert status.current_item_index == 1
        assert status.item_remaining_seconds == 17
    finally:
        _cleanup_classroom(db, classroom["id"])
        db.delete(another)
        db.commit()


def _demo_passage(db: Session) -> Passage:
    passage = db.exec(select(Passage).where(Passage.slug == "demo-pets")).first()
    assert passage is not None
    return passage


def _publish_exam(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    items: list[dict],
    **extra: object,
) -> Response:
    body: dict = {"items": items, "is_exam": True, "time_limit_minutes": 30}
    body.update(extra)
    resp = client.put(f"/api/v1/classes/{code}/assignment", json=body, headers=headers)
    return resp


def _today(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.get(f"/api/v1/classes/{code}/today", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _submit(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    item: dict,
    session_id: str,
    key: str | None = None,
):
    return client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(6.0)},
        data={
            "item_type": item["type"],
            "item_id": item["id"],
            "duration_s": "6.0",
            "session_id": session_id,
            **({"idempotency_key": key} if key else {}),
        },
        headers=headers,
    )


def test_publish_exam_validation(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """模考必须带 5–240 分钟限时；非法值 422，合法值发布成功。"""
    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    passage = _demo_passage(db)
    items = [{"type": "passage", "id": str(passage.id)}]
    try:
        assert (
            _publish_exam(
                client, superuser_token_headers, code, items, time_limit_minutes=None
            ).status_code
            == 422
        )
        assert (
            _publish_exam(
                client, superuser_token_headers, code, items, time_limit_minutes=3
            ).status_code
            == 422
        )
        resp = _publish_exam(client, superuser_token_headers, code, items)
        assert resp.status_code == 200, resp.text

        exercises = client.get(
            f"/api/v1/classes/{code}/exercises", headers=superuser_token_headers
        ).json()
        current = next(e for e in exercises if e["status"] == "published")
        assert current["is_exam"] is True
        assert current["time_limit_minutes"] == 30
    finally:
        _cleanup_classroom(db, classroom["id"])


def _resp_json(resp: Response) -> dict:
    assert resp.status_code == 200, getattr(resp, "text", resp)
    return resp.json()


def _cleanup_classroom(db: Session, classroom_id: str) -> None:
    from app.models import Classroom

    row = db.get(Classroom, uuid.UUID(classroom_id))
    if row is not None:
        db.delete(row)
    db.commit()


def test_exam_lifecycle_and_one_shot(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """确认页开考计时 → 每题一次作答（幂等重试不受影响）→ 到时拒绝继续。"""
    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code, "考生甲")
    headers = made["headers"]
    passage = _demo_passage(db)
    items = [{"type": "passage", "id": str(passage.id)}]
    try:
        resp = _publish_exam(client, superuser_token_headers, code, items)
        assert resp.status_code == 200, resp.text

        # today 只透出考试状态，不自动开考（防止误触打开即烧时间）
        plan = _today(client, headers, code)
        assert plan["exam"] is not None
        assert plan["exam"]["started"] is False
        assert plan["exam"]["ended"] is False
        assert plan["exam"]["time_limit_minutes"] == 30

        # 未开考直接作答被拒
        item = plan["items"][0]
        early = _submit(client, headers, code, item, plan["session_id"], "early-key")
        assert early.status_code == 422
        assert "尚未开始" in early.json()["detail"]

        # 确认页显式开考：落服务器时间；重复调用幂等不重置
        start = client.post(
            f"/api/v1/classes/{code}/exam/start",
            json={"session_id": plan["session_id"]},
            headers=headers,
        )
        assert start.status_code == 200, start.text
        assert start.json()["started"] is True
        assert start.json()["ended"] is False
        assert 0 < start.json()["remaining_seconds"] <= 30 * 60
        restart = client.post(
            f"/api/v1/classes/{code}/exam/start",
            json={"session_id": plan["session_id"]},
            headers=headers,
        )
        assert restart.status_code == 200
        assert restart.json()["started"] is True
        assert restart.json()["remaining_seconds"] <= start.json()["remaining_seconds"]

        plan = _today(client, headers, code)
        assert plan["exam"]["started"] is True
        assert 0 < plan["exam"]["remaining_seconds"] <= 30 * 60

        # 首题作答成功；同题第二次（新幂等键）被拒
        key = f"exam-{random_lower_string()}"
        first = _submit(client, headers, code, item, plan["session_id"], key)
        assert first.status_code == 200, first.text
        second = _submit(client, headers, code, item, plan["session_id"], "another-key")
        assert second.status_code == 422
        assert "一次" in second.json()["detail"]

        # 同幂等键重试（断网重传）：返回既有作答，不被一次性限制误伤
        replay = _submit(client, headers, code, item, plan["session_id"], key)
        assert replay.status_code == 200
        assert replay.json()["id"] == first.json()["id"]

        # 考试中不能换题
        nxt = client.get(
            f"/api/v1/classes/{code}/next-question",
            params={"session_id": plan["session_id"]},
            headers=headers,
        )
        assert nxt.status_code == 422
        assert "换题" in nxt.json()["detail"]

        # 把开始时间拨回过去 → 惰性终结：today 显示已结束，提交被拒
        ps = db.exec(
            select(PracticeSession).where(
                PracticeSession.id == uuid.UUID(plan["session_id"])
            )
        ).first()
        assert ps is not None
        ps.exam_started_at = datetime.now(UTC) - timedelta(minutes=31)
        db.add(ps)
        db.commit()

        plan2 = _today(client, headers, code)
        assert plan2["exam"]["ended"] is True
        assert plan2["exam"]["remaining_seconds"] == 0
        assert (
            _submit(
                client, headers, code, item, plan2["session_id"], "late-key"
            ).status_code
            == 422
        )
    finally:
        _cleanup_classroom(db, classroom["id"])


def test_tab_switch_reporting_and_board(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """切屏上报计数与离屏时长（非考试/未开考拒绝）；教师面板与发布历史展示。"""
    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code, "考生乙")
    headers = made["headers"]
    passage = _demo_passage(db)
    items = [{"type": "passage", "id": str(passage.id)}]
    try:
        assert (
            _publish_exam(client, superuser_token_headers, code, items).status_code
            == 200
        )
        plan = _today(client, headers, code)
        violation_url = f"/api/v1/classes/{code}/exam/violation"

        # 未开考不可上报（确认页阶段切 tab 不算作弊）
        early = client.post(
            violation_url,
            json={"session_id": plan["session_id"]},
            headers=headers,
        )
        assert early.status_code == 422
        assert "尚未开始" in early.json()["detail"]

        start = client.post(
            f"/api/v1/classes/{code}/exam/start",
            json={"session_id": plan["session_id"]},
            headers=headers,
        )
        assert start.status_code == 200

        # hidden 相位：只计数；visible 相位：带离屏秒数累计时长
        report = client.post(
            violation_url,
            json={"session_id": plan["session_id"]},
            headers=headers,
        )
        assert report.status_code == 200, report.text
        assert report.json()["tab_switch_count"] == 1
        assert report.json()["tab_switch_seconds"] == 0
        report = client.post(
            violation_url,
            json={"session_id": plan["session_id"], "away_seconds": 90},
            headers=headers,
        )
        assert report.json()["tab_switch_count"] == 1
        assert report.json()["tab_switch_seconds"] == 90
        report = client.post(
            violation_url,
            json={"session_id": plan["session_id"]},
            headers=headers,
        )
        assert report.json()["tab_switch_count"] == 2
        report = client.post(
            violation_url,
            json={"session_id": plan["session_id"], "away_seconds": 45},
            headers=headers,
        )
        assert report.json()["tab_switch_count"] == 2
        assert report.json()["tab_switch_seconds"] == 135
        # 单次上报封顶 1 小时（异常值防刷）
        report = client.post(
            violation_url,
            json={"session_id": plan["session_id"], "away_seconds": 999_999},
            headers=headers,
        )
        assert report.json()["tab_switch_seconds"] == 135 + 3600

        # 他人会话不可上报
        stranger = make_student(db, client, code, "无关学生")
        assert (
            client.post(
                violation_url,
                json={"session_id": plan["session_id"]},
                headers=stranger["headers"],
            ).status_code
            == 404
        )

        # 教师面板展示监考字段
        board = client.get(
            f"/api/v1/classes/{code}/board", headers=superuser_token_headers
        ).json()
        row = next(s for s in board["students"] if s["display_name"] == "考生乙")
        assert row["exam_tab_switches"] == 2
        assert row["exam_tab_switch_seconds"] == 135 + 3600
        assert row["exam_time_used_seconds"] is not None
        assert row["exam_ended"] is False

        # 发布历史结果页同样可见
        exercises = client.get(
            f"/api/v1/classes/{code}/exercises", headers=superuser_token_headers
        ).json()
        current = next(e for e in exercises if e["status"] == "published")
        results = client.get(
            f"/api/v1/classes/{code}/exercises/{current['id']}/results",
            headers=superuser_token_headers,
        ).json()
        rrow = next(r for r in results if r["display_name"] == "考生乙")
        assert rrow["exam_tab_switches"] == 2
        assert rrow["exam_tab_switch_seconds"] == 135 + 3600

        # 非考试会话上报被拒（自主练习轮）
        ps_self = db.exec(
            select(PracticeSession).where(
                PracticeSession.student_id == uuid.UUID(made["student"]["id"]),
                col(PracticeSession.assignment_id).is_(None),  # type: ignore[operator]
            )
        ).first()
        if ps_self is not None:
            assert (
                client.post(
                    violation_url,
                    json={"session_id": str(ps_self.id)},
                    headers=headers,
                ).status_code
                == 422
            )
    finally:
        _cleanup_classroom(db, classroom["id"])


def test_regular_practice_unaffected(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """普通发布（非考试）：today 无考试信息、可重录、可换题、上报被拒。"""
    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code, "普通学生")
    headers = made["headers"]
    passage = _demo_passage(db)
    try:
        resp = client.put(
            f"/api/v1/classes/{code}/assignment",
            json={"items": [{"type": "passage", "id": str(passage.id)}]},
            headers=superuser_token_headers,
        )
        assert resp.status_code == 200, resp.text
        plan = _today(client, headers, code)
        assert plan["exam"] is None

        item = plan["items"][0]
        assert (
            _submit(client, headers, code, item, plan["session_id"]).status_code == 200
        )
        # 重录（新键、同题）在普通模式仍可
        again = _submit(client, headers, code, item, plan["session_id"], "redo-key")
        assert again.status_code == 200, again.text
    finally:
        _cleanup_classroom(db, classroom["id"])


# AttemptPublic（GET/POST 作答出口）需要遮罩的反馈字段
MASKED_ATTEMPT_FIELDS = (
    "transcript",
    "completeness",
    "fluency",
    "accuracy",
    "overall",
    "advice",
    "vocab",
    "rubric",
    "error",
)
# PlanAttempt（today 计划出口）没有 accuracy 字段，其余同上
MASKED_PLAN_FIELDS = tuple(f for f in MASKED_ATTEMPT_FIELDS if f != "accuracy")


@pytest.fixture
def inline_scoring(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None, None, None]:
    """同步评分：POST 内联跑完 mock 引擎，反馈内容可确定性断言。"""
    from app.api.deps import get_scoring_submitter
    from app.core.config import settings
    from app.main import app
    from app.scoring import worker

    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))

    class FakeAsr:
        name = "mock"

        def transcribe(self, audio: bytes, mime_type: str) -> str:
            return "i have a cat and a dog"

    monkeypatch.setattr(worker, "build_asr_provider", lambda: FakeAsr())

    def run_inline(attempt_id: uuid.UUID) -> None:
        with Session(db.get_bind()) as session:
            worker.process_attempt(session, attempt_id)

    app.dependency_overrides[get_scoring_submitter] = lambda: run_inline
    yield
    app.dependency_overrides.pop(get_scoring_submitter, None)


def test_exam_feedback_masked_server_side_until_ended(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    inline_scoring: None,
) -> None:
    """模考反馈限制必须在服务端生效：进行中学生 GET/幂等重放/today 都拿不到
    分数、转写、建议；授权教师不受影响；考试终结后反馈恢复；无关学生 403。

    两题考试、只答第一题（评分已完成）——第二题未答且在窗口内，考试进行中。
    """
    from app.models import Classroom, ClassroomExercise

    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code, "遮罩考生")
    headers = made["headers"]
    other = make_student(db, client, code, "无关考生")
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    db.add_all(
        [
            Passage(
                id=first_id,
                slug=f"mask-a-{first_id}",
                title="First article",
                text="First article.",
                cefr_band="B1",
            ),
            Passage(
                id=second_id,
                slug=f"mask-b-{second_id}",
                title="Second article",
                text="Second article.",
                cefr_band="B1",
            ),
        ]
    )
    db.commit()
    snapshot: list[dict[str, object]] = [
        {
            "type": "passage",
            "id": str(first_id),
            "text": "First article.",
            "suggested_seconds": 20,
        },
        {
            "type": "passage",
            "id": str(second_id),
            "text": "Second article.",
            "suggested_seconds": 20,
        },
    ]
    exercise = ClassroomExercise(
        classroom_id=uuid.UUID(classroom["id"]),
        snapshot_items=snapshot,
        is_exam=True,
        time_limit_minutes=30,
    )
    db.add(exercise)
    db.flush()
    row = db.get(Classroom, exercise.classroom_id)
    assert row is not None
    row.current_exercise_id = exercise.id
    db.add(row)
    db.commit()
    fake_now = datetime.now(UTC)
    monkeypatch.setattr(exam_service, "_now", lambda: fake_now)
    try:
        plan = _today(client, headers, code)
        assert (
            client.post(
                f"/api/v1/classes/{code}/exam/start",
                json={"session_id": plan["session_id"]},
                headers=headers,
            ).status_code
            == 200
        )

        # 首题上传（内联评分即完成）→ 考试仍在进行（第二题未答）
        key = f"mask-{random_lower_string()}"
        first = _submit(client, headers, code, plan["items"][0], plan["session_id"], key)
        assert first.status_code == 200, first.text
        attempt_id = first.json()["id"]
        assert first.json()["status"] == "done"

        # 学生 GET：状态保留，反馈字段全部为空（前端不显示不是安全边界）
        got = _resp_json(client.get(f"/api/v1/attempts/{attempt_id}", headers=headers))
        assert got["status"] == "done"
        assert got["id"] == attempt_id
        for field in MASKED_ATTEMPT_FIELDS:
            assert got[field] is None, f"{field} 不应在模考进行中下发"

        # 同幂等键重放（断网重传）：回执遮罩，不泄露评分结果
        replay = _submit(
            client, headers, code, plan["items"][0], plan["session_id"], key
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["id"] == attempt_id
        for field in MASKED_ATTEMPT_FIELDS:
            assert replay.json()[field] is None

        # today：plan_attempts 只剩题目/作答/状态回执
        plan = _today(client, headers, code)
        assert plan["exam"]["ended"] is False
        pa = next(a for a in plan["attempts"] if str(a["attempt_id"]) == attempt_id)
        assert pa["status"] == "done"
        for field in MASKED_PLAN_FIELDS:
            assert pa[field] is None

        # 授权教师（课堂 owner，此处为 superuser）：完整反馈不受遮罩影响
        teacher = _resp_json(
            client.get(f"/api/v1/attempts/{attempt_id}", headers=superuser_token_headers)
        )
        assert teacher["transcript"] == "i have a cat and a dog"
        assert teacher["overall"] is not None

        # 无关学生：403（本来就不许读他人作答）
        assert (
            client.get(
                f"/api/v1/attempts/{attempt_id}", headers=other["headers"]
            ).status_code
            == 403
        )

        # 到时终结（第二题窗口与宽限期都过去）→ 学生反馈完整恢复
        fake_now += timedelta(seconds=40)
        plan2 = _today(client, headers, code)
        assert plan2["exam"]["ended"] is True
        pa2 = next(a for a in plan2["attempts"] if str(a["attempt_id"]) == attempt_id)
        assert pa2["transcript"] == "i have a cat and a dog"
        assert pa2["overall"] is not None

        got2 = _resp_json(client.get(f"/api/v1/attempts/{attempt_id}", headers=headers))
        assert got2["transcript"] == "i have a cat and a dog"
    finally:
        _cleanup_classroom(db, classroom["id"])


def test_practice_feedback_not_masked_outside_exam(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    inline_scoring: None,
) -> None:
    """普通发布练习（非模考）：遮罩逻辑不得误伤——评分完成后反馈照常可读。"""
    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code, "普通练习生")
    headers = made["headers"]
    passage = _demo_passage(db)
    try:
        resp = client.put(
            f"/api/v1/classes/{code}/assignment",
            json={"items": [{"type": "passage", "id": str(passage.id)}]},
            headers=superuser_token_headers,
        )
        assert resp.status_code == 200, resp.text
        plan = _today(client, headers, code)
        item = plan["items"][0]
        posted = _submit(client, headers, code, item, plan["session_id"])
        assert posted.status_code == 200, posted.text
        assert posted.json()["status"] == "done"
        attempt_id = posted.json()["id"]

        # 上传回执与轮询都直接带反馈（普通练习无遮罩）
        assert posted.json()["transcript"] == "i have a cat and a dog"
        assert posted.json()["overall"] is not None
        got = _resp_json(client.get(f"/api/v1/attempts/{attempt_id}", headers=headers))
        assert got["transcript"] == "i have a cat and a dog"
        assert got["overall"] is not None

        plan2 = _today(client, headers, code)
        pa = next(a for a in plan2["attempts"] if str(a["attempt_id"]) == attempt_id)
        assert pa["transcript"] == "i have a cat and a dog"
        assert pa["overall"] is not None
    finally:
        _cleanup_classroom(db, classroom["id"])
