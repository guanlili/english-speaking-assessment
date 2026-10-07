"""模考模式：确认页显式开考 + 整场限时（服务端强约束）+ 每题一次作答 + 防切屏（次数/离屏时长）+ 监考展示。"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, col, select

from app.models import Passage, PracticeSession
from tests.utils.audio import wav_upload
from tests.utils.credential import make_student
from tests.utils.utils import random_lower_string


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
