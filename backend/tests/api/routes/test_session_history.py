"""学生历史练习回看测试：

- 地基：readTodayPlan 传 session_id 能回看昨日发布练习会话的题单与作答
  （学生「我的成长」页历史列表跳转结果页依赖该路径）；
- my-sessions：本人学生凭证、最近会话行的统计口径与权限边界。
"""

import uuid
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_scoring_submitter
from app.core.config import settings
from app.main import app
from app.models import (
    Attempt,
    AttemptStatus,
    Classroom,
    PracticeSession,
    Student,
    StudentBadge,
    User,
)
from app.scoring import worker
from tests.utils.audio import wav_upload
from tests.utils.credential import (
    anonymous,
    create_student_user,
    login_headers,
    make_student,
)


@pytest.fixture
def inline_scoring(
    db: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[Callable[[dict[str, str]], None]]:
    """音频落盘临时目录，评分同步执行；返回设置假转写的函数。"""
    monkeypatch.setattr(settings, "AUDIO_STORAGE_DIR", str(tmp_path))

    def run_inline(attempt_id: uuid.UUID) -> None:
        with Session(db.get_bind()) as session:
            worker.process_attempt(session, attempt_id)
        # 自动重试：评分失败后重排队列，继续处理到终态
        while True:
            with Session(db.get_bind()) as check:
                attempt = check.get(Attempt, attempt_id)
                if attempt is None or attempt.status != AttemptStatus.QUEUED:
                    break
            with Session(db.get_bind()) as session:
                worker.process_attempt(session, attempt_id)

    def override_submitter() -> Callable[[uuid.UUID], None]:
        return run_inline

    app.dependency_overrides[get_scoring_submitter] = override_submitter

    def set_transcripts(transcripts: dict[str, str]) -> None:
        monkeypatch.setattr(worker, "build_asr_provider", lambda: _FakeAsr(transcripts))

    yield set_transcripts
    app.dependency_overrides.pop(get_scoring_submitter, None)


class _FakeAsr:
    """按 MIME 返回可控转写（与 test_classroom.FakeAsr 同构）。"""

    name = "fake"

    def __init__(self, transcripts: dict[str, str]) -> None:
        self.transcripts = transcripts

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        return self.transcripts.get(mime_type, "")


def _classroom(client: TestClient, superuser_token_headers: dict[str, str]) -> dict:
    resp = client.post(
        "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _submit(
    client: TestClient,
    item: dict,
    headers: dict[str, str],
    session_id: str,
    duration: float = 6.0,
) -> Any:
    return client.post(
        "/api/v1/attempts",
        files={"audio": wav_upload(duration)},
        data={
            "item_type": item["type"],
            "item_id": item["id"],
            "duration_s": str(duration),
            "session_id": session_id,
        },
        headers=headers,
    )


def _cleanup_student(db: Session, made: dict) -> None:
    """清掉本用例自建的学生及其作答/会话/徽章（conftest 只在整轮后清库）。"""
    sid = uuid.UUID(made["student"]["id"])
    uid = uuid.UUID(made["student"]["user_id"])
    for model in (Attempt, PracticeSession, StudentBadge):
        for row in db.exec(
            select(model).where(model.student_id == sid)  # type: ignore[attr-defined]
        ).all():
            db.delete(row)
    db.delete(db.get_one(Student, sid))
    if uid is not None:
        db.delete(db.get_one(User, uid))
    db.commit()


def _unassign(db: Session, code: str) -> None:
    classroom = db.exec(select(Classroom).where(Classroom.code == code)).first()
    if classroom is not None:
        classroom.current_unit_id = None
        classroom.current_exercise_id = None
        classroom.assigned_items = None
        db.add(classroom)
        db.commit()


def test_yesterday_assignment_session_readable_by_session_id(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    inline_scoring: Callable[[dict[str, str]], None],
    db: Session,
) -> None:
    """地基验证：昨日发布练习会话传 session_id 调 /today 返回该轮题单与 attempts。

    学生第二天从「我的成长」历史列表点「查看反馈」跳
    /p/{code}/result?session=<id>，结果页即走这条路径。
    """
    classroom = _classroom(client, superuser_token_headers)
    code = classroom["code"]
    made = make_student(db, client, code, "回看学生")
    try:
        # 发布按题练习：种子情景的一道问答题
        scenarios = client.get(
            "/api/v1/admin/scenarios", headers=superuser_token_headers
        ).json()["data"]
        scenario = next(s for s in scenarios if s["topic"] == "Pets")
        question_id = scenario["questions"][0]["id"]
        publish = client.put(
            f"/api/v1/classes/{code}/assignment",
            json={"items": [{"type": "question", "id": question_id}]},
            headers=superuser_token_headers,
        )
        assert publish.status_code == 200, publish.text

        plan = client.get(
            f"/api/v1/classes/{code}/today", headers=made["headers"]
        ).json()
        session_id = plan["session_id"]
        question = next(i for i in plan["items"] if i["type"] == "question")

        # 答完该题（mock 引擎同步出分）；题干投影随回执/轮询一并下发
        inline_scoring({"audio/wav": "i think it is good"})
        resp = _submit(client, question, made["headers"], session_id)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "done"
        assert resp.json()["item_text"] == question["text"]
        assert resp.json()["item_title"] is None  # 问答题快照无标题
        polled = client.get(
            f"/api/v1/attempts/{resp.json()['id']}", headers=made["headers"]
        )
        assert polled.status_code == 200
        assert polled.json()["item_text"] == question["text"]

        # 模拟第二天回看：会话日期改到昨天
        row = db.get_one(PracticeSession, uuid.UUID(session_id))
        row.session_date = row.session_date - timedelta(days=1)
        db.add(row)
        db.commit()

        # 带 session_id 返回昨天的轮次：题单、作答、分数齐全
        review = client.get(
            f"/api/v1/classes/{code}/today",
            params={"session_id": session_id},
            headers=made["headers"],
        )
        assert review.status_code == 200, review.text
        reviewed = review.json()
        assert reviewed["session_id"] == session_id
        assert [i["id"] for i in reviewed["items"]] == [question["id"]]
        assert len(reviewed["attempts"]) == 1
        assert reviewed["attempts"][0]["item_id"] == question["id"]
        assert reviewed["attempts"][0]["status"] == "done"
        assert reviewed["attempts"][0]["overall"] is not None

        # 他人会话不可回看（404，与 today 的既有口径一致）
        other = make_student(db, client, code, "别的学生")
        try:
            foreign = client.get(
                f"/api/v1/classes/{code}/today",
                params={"session_id": session_id},
                headers=other["headers"],
            )
            assert foreign.status_code == 404
        finally:
            _cleanup_student(db, other)
    finally:
        _unassign(db, code)
        _cleanup_student(db, made)


def test_my_sessions_requires_student_credential(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """权限边界：未登录 401；教师角色 403；未入本班的学生 404（与 today/trail 同口径）。"""
    classroom = _classroom(client, superuser_token_headers)
    code = classroom["code"]
    url = f"/api/v1/classes/{code}/my-sessions"

    with anonymous(client):
        assert client.get(url).status_code == 401

    # 真实教师（非管理员）：角色门 403
    teacher_email = f"teacher-{uuid.uuid4().hex[:8]}@example.com"
    teacher_password = "teacher-pass-123"
    from app import crud
    from app.models import UserCreate

    crud.create_user(
        session=db,
        user_create=UserCreate(
            email=teacher_email, password=teacher_password, role="teacher"
        ),
    )
    login = client.post(
        "/api/v1/login/access-token",
        data={"username": teacher_email, "password": teacher_password},
    )
    assert login.status_code == 200, login.text
    resp = client.get(
        url, headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert resp.status_code == 403

    # 学生账号但未加入该课堂：档案不存在 → 404（前端引导去加入页）
    stranger = create_student_user(db, full_name="班外学生")
    assert stranger.username is not None
    stranger_headers = login_headers(client, stranger.username)
    resp = client.get(url, headers=stranger_headers)
    assert resp.status_code == 404

    from app.models import User

    db.delete(db.get_one(User, stranger.id))
    db.commit()


def test_my_sessions_rows_and_stats(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    inline_scoring: Callable[[dict[str, str]], None],
    db: Session,
) -> None:
    """数据正确性：发布轮按快照分母统计 done/total 与参考分均值、标题透出；
    自主轮按实际作答题位计；按练习日倒序。
    """
    classroom = _classroom(client, superuser_token_headers)
    code = classroom["code"]
    made = make_student(db, client, code, "历史学生")
    try:
        # 发布 3 题练习：朗读篇目（带标题快照）+ 两道问答
        passages = client.get(
            "/api/v1/admin/passages", headers=superuser_token_headers
        ).json()["data"]
        passage = next(p for p in passages if p["slug"] == "demo-pets")
        scenarios = client.get(
            "/api/v1/admin/scenarios", headers=superuser_token_headers
        ).json()["data"]
        scenario = next(s for s in scenarios if s["topic"] == "Pets")
        q1_id, q2_id = (q["id"] for q in scenario["questions"][:2])
        publish = client.put(
            f"/api/v1/classes/{code}/assignment",
            json={
                "title": "期中口语练习",
                "items": [
                    {"type": "passage", "id": passage["id"]},
                    {"type": "question", "id": q1_id},
                    {"type": "question", "id": q2_id},
                ],
            },
            headers=superuser_token_headers,
        )
        assert publish.status_code == 200, publish.text

        plan = client.get(
            f"/api/v1/classes/{code}/today", headers=made["headers"]
        ).json()
        session_a = plan["session_id"]
        passage_item = next(i for i in plan["items"] if i["type"] == "passage")
        q1 = next(i for i in plan["items"] if i["type"] == "question")

        # 昨天那轮：答朗读 + Q1，留 Q2 未做
        inline_scoring({"audio/wav": passage_item["text"]})
        passage_resp = _submit(client, passage_item, made["headers"], session_a)
        assert passage_resp.status_code == 200, passage_resp.text
        # 朗读条目快照带篇目标题（题干投影 title）
        assert passage_resp.json()["item_title"] == passage["title"]
        assert passage_resp.json()["item_text"] == passage_item["text"]

        inline_scoring({"audio/wav": "i think it is good"})
        q1_resp = _submit(client, q1, made["headers"], session_a)
        assert q1_resp.status_code == 200, q1_resp.text

        row = db.get_one(PracticeSession, uuid.UUID(session_a))
        row.session_date = row.session_date - timedelta(days=1)
        db.add(row)
        db.commit()

        # 今天再开一轮（同发布仍当前）：新会话，未作答
        plan_b = client.get(
            f"/api/v1/classes/{code}/today", headers=made["headers"]
        ).json()
        assert plan_b["session_id"] != session_a

        # 清除发布 → 自主练习轮，做一题
        clear = client.put(
            f"/api/v1/classes/{code}/assignment",
            json={"items": []},
            headers=superuser_token_headers,
        )
        assert clear.status_code == 200, clear.text
        plan_c = client.get(
            f"/api/v1/classes/{code}/today", headers=made["headers"]
        ).json()
        assert plan_c["session_id"] not in {session_a, plan_b["session_id"]}
        repeat_c = next(i for i in plan_c["items"] if i["type"] == "repeat")
        inline_scoring({"audio/wav": repeat_c["text"]})
        repeat_resp = _submit(client, repeat_c, made["headers"], plan_c["session_id"])
        assert repeat_resp.status_code == 200, repeat_resp.text

        rows = client.get(
            f"/api/v1/classes/{code}/my-sessions", headers=made["headers"]
        ).json()
        assert len(rows) == 3
        # 倒序：今天的自主轮 → 今天的发布轮 → 昨天的发布轮
        by_id = {r["session_id"]: r for r in rows}
        assert [r["session_id"] for r in rows] == [
            plan_c["session_id"],
            plan_b["session_id"],
            session_a,
        ]
        # 昨天的发布轮：标题透出、2/3 完成、均分 = 两题参考分均值
        row_a = by_id[session_a]
        assert row_a["title"] == "期中口语练习"
        assert row_a["mode"] == "daily"
        assert row_a["done_count"] == 2
        assert row_a["total_count"] == 3
        expected_avg = round(
            (passage_resp.json()["overall"] + q1_resp.json()["overall"]) / 2,
            1,
        )
        assert row_a["overall_avg"] == expected_avg
        # 今天的发布轮：0/3、无均分
        row_b = by_id[plan_b["session_id"]]
        assert row_b["title"] == "期中口语练习"
        assert row_b["done_count"] == 0
        assert row_b["total_count"] == 3
        assert row_b["overall_avg"] is None
        # 自主轮：无发布标题、按实际作答题位计 1/1、有均分
        row_c = by_id[plan_c["session_id"]]
        assert row_c["title"] is None
        assert row_c["done_count"] == 1
        assert row_c["total_count"] == 1
        assert row_c["overall_avg"] == repeat_resp.json()["overall"]
    finally:
        _unassign(db, code)
        _cleanup_student(db, made)


def test_my_sessions_exam_scores_masked_until_ended(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    inline_scoring: Callable[[dict[str, str]], None],
    db: Session,
) -> None:
    """模考未终结的轮次：完成计数可见，参考分均值不下发（与 trail 遮罩同口径）。"""
    classroom = _classroom(client, superuser_token_headers)
    code = classroom["code"]
    made = make_student(db, client, code, "模考历史")
    try:
        questions = client.get(
            "/api/v1/admin/scenarios", headers=superuser_token_headers
        ).json()["data"][0]["questions"]
        publish = client.put(
            f"/api/v1/classes/{code}/assignment",
            json={
                "items": [
                    {"type": "question", "id": questions[0]["id"]},
                    {"type": "question", "id": questions[1]["id"]},
                ],
                "is_exam": True,
                "time_limit_minutes": 30,
            },
            headers=superuser_token_headers,
        )
        assert publish.status_code == 200, publish.text

        plan = client.get(
            f"/api/v1/classes/{code}/today", headers=made["headers"]
        ).json()
        started = client.post(
            f"/api/v1/classes/{code}/exam/start",
            json={"session_id": plan["session_id"]},
            headers=made["headers"],
        )
        assert started.status_code == 200, started.text
        # 只答第一题：第二题未答且在窗口内 → 考试进行中
        first = next(i for i in plan["items"] if i["type"] == "question")
        inline_scoring({"audio/wav": "i think it is good"})
        resp = _submit(client, first, made["headers"], plan["session_id"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "done"
        # 回执在考试中被遮罩；分数从库里取（教师视角的基准值）
        attempt_row = db.get_one(Attempt, uuid.UUID(resp.json()["id"]))
        assert attempt_row is not None and attempt_row.overall is not None

        rows = client.get(
            f"/api/v1/classes/{code}/my-sessions", headers=made["headers"]
        ).json()
        assert len(rows) == 1
        # 考试进行中（时间未到未交卷）：状态/计数可见，分数聚合不下发
        assert rows[0]["done_count"] == 1
        assert rows[0]["total_count"] == 2
        assert rows[0]["overall_avg"] is None

        # 考试终结（交卷）后：分数恢复
        session_row = db.get_one(PracticeSession, uuid.UUID(plan["session_id"]))
        session_row.exam_ended_at = datetime.now(UTC)
        db.add(session_row)
        db.commit()

        rows_after = client.get(
            f"/api/v1/classes/{code}/my-sessions", headers=made["headers"]
        ).json()
        assert rows_after[0]["overall_avg"] == attempt_row.overall
    finally:
        _unassign(db, code)
        _cleanup_student(db, made)
