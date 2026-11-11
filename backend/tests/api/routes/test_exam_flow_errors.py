"""apply_event 的拒绝路径：四个错误分支的 status code 与 detail 文案。

`test_exam_flow.py` 覆盖了整场状态机的正常流转（95%），但 apply_event 里还有四条
只会在异常输入时走到的分支没有断言。它们的价值不在「提高覆盖率百分比」，而在于
**契约冻结**：前端靠这些 detail 文案区分「已交卷」「不是当前题」「音频没在播」，
改措辞或换 status code 会让客户端的错误提示错位。
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import (
    Classroom,
    ClassroomExercise,
    ExamItemSettings,
    Passage,
    PracticeSession,
)
from app.services import exam
from app.services.exam_flow import apply_event
from tests.api.routes.test_exam import _cleanup_classroom, _resp_json, _today
from tests.utils.credential import make_student


class Scenario(NamedTuple):
    code: str
    sid: str
    ids: list[uuid.UUID]
    classroom: dict[str, object]
    passage: Passage
    exercise: ClassroomExercise
    headers: dict[str, str]
    clock: dict[str, datetime]

    def event(self, client: TestClient, item_id: str, name: str) -> int:
        response = client.post(
            f"/api/v1/classes/{self.code}/exam/flow",
            json={"session_id": self.sid, "item_id": item_id, "event": name},
            headers=self.headers,
        )
        return response.status_code

    def detail(self, client: TestClient, item_id: str, name: str) -> str:
        response = client.post(
            f"/api/v1/classes/{self.code}/exam/flow",
            json={"session_id": self.sid, "item_id": item_id, "event": name},
            headers=self.headers,
        )
        return str(response.json().get("detail", ""))


def _scenario(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    limit_minutes: int = 5,
    start: bool = True,
) -> Scenario:
    """两道 passage 题的最小自动化考试，可选是否已经开始作答。"""
    classroom = _resp_json(
        client.post(
            "/api/v1/classes", json={"class_size": 10}, headers=superuser_token_headers
        )
    )
    code = classroom["code"]
    made = make_student(db, client, code)
    ids = [uuid.uuid4(), uuid.uuid4()]
    # daily session 的 passage_id 取自快照里 passage 类型题的 id，
    # 实体必须用同一个 id，否则建 session 时外键不通
    passage = Passage(
        id=ids[0],
        slug=f"flow-err-{ids[0]}",
        title="Read",
        text="Read this.",
        cefr_band="B1",
    )
    db.add(passage)
    db.commit()
    settings = ExamItemSettings(
        wait_seconds=3, after_audio_seconds=2, prep_seconds=7
    ).model_dump()
    exercise = ClassroomExercise(
        classroom_id=uuid.UUID(str(classroom["id"])),
        is_exam=True,
        time_limit_minutes=limit_minutes,
        snapshot_items=[
            {
                "id": str(item_id),
                "type": "passage",
                "text": "Read this.",
                "suggested_seconds": 10,
                "exam_flow": settings,
            }
            for item_id in ids
        ],
    )
    db.add(exercise)
    db.flush()
    row = db.get(Classroom, exercise.classroom_id)
    assert row is not None
    row.current_exercise_id = exercise.id
    db.add(row)
    db.commit()
    clock: dict[str, datetime] = {"now": datetime.now(UTC)}
    monkeypatch.setattr(exam, "_now", lambda: clock["now"])
    sid = _today(client, made["headers"], code)["session_id"]
    if start:
        response = client.post(
            f"/api/v1/classes/{code}/exam/start",
            json={"session_id": sid},
            headers=made["headers"],
        )
        assert response.status_code == 200
    return Scenario(
        code=code,
        sid=str(sid),
        ids=ids,
        classroom=classroom,
        passage=passage,
        exercise=exercise,
        headers=made["headers"],
        clock=clock,
    )


def _teardown(db: Session, scenario: Scenario) -> None:
    _cleanup_classroom(db, str(scenario.classroom["id"]))
    db.delete(scenario.passage)
    db.commit()


def test_event_for_item_outside_snapshot_returns_404(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """快照里找不到该题 → 404，而不是当成未知事件返回 422。

    这条区分很重要：前端拿到 404 说明「题目已被替换或版本对不上」，应该刷新页面；
    拿到 422 只会当成一次普通操作失败重试，永远好不了。
    """
    scenario = _scenario(client, db, superuser_token_headers, monkeypatch)
    try:
        missing = str(uuid.uuid4())
        assert scenario.event(client, missing, "audio-ended") == 404
        assert scenario.detail(client, missing, "audio-ended") == "Item not found"
    finally:
        _teardown(db, scenario)


def test_event_after_global_deadline_returns_auto_submit_422(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整场截止后任何事件都被拒，文案要明确是「已自动交卷」而非普通失败。

    学生看到「已自动交卷」才会停止操作；看到模糊的失败提示会一直重试，
    而这些请求在服务端永远不会成功。
    """
    scenario = _scenario(
        client, db, superuser_token_headers, monkeypatch, limit_minutes=5
    )
    try:
        scenario.clock["now"] += timedelta(minutes=6)
        assert scenario.event(client, str(scenario.ids[0]), "audio-ended") == 422
        assert (
            scenario.detail(client, str(scenario.ids[0]), "audio-ended")
            == "考试时间已到，已自动交卷"
        )
    finally:
        _teardown(db, scenario)


def test_event_for_not_current_item_returns_422(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """给还没轮到的题发事件 → 422。

    多标签页 / 预加载前端最容易踩到：第 2 题的音频可能已经缓存好并提前回调
    audio-ended，服务端必须拒掉，否则下一题的 started_at 会被提前写入，
    整场的节奏就乱了。
    """
    scenario = _scenario(client, db, superuser_token_headers, monkeypatch)
    try:
        assert scenario.event(client, str(scenario.ids[1]), "audio-ended") == 422
        assert (
            scenario.detail(client, str(scenario.ids[1]), "audio-ended")
            == "本题作答时间已结束或尚未开始"
        )
    finally:
        _teardown(db, scenario)


def test_unknown_event_name_is_rejected_at_service_layer(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知事件名在 service 层必须 422，不能静默成功。

    HTTP 层已经是 `Literal["audio-ended", "next"]`，拼错的事件名在请求校验阶段就被
    挡住，走不到 apply_event 的 else 分支。这里覆盖的是**绕过 schema 直接调
    apply_event** 的情况（未来的新调用方、迁移脚本、队列消费）。
    静默成功最危险：调用方以为推进了，服务端状态没变，两边从此错开且无法自愈。
    """
    scenario = _scenario(client, db, superuser_token_headers, monkeypatch)
    try:
        ps = db.get(PracticeSession, uuid.UUID(scenario.sid))
        assert ps is not None
        with pytest.raises(HTTPException) as caught:
            apply_event(
                db,
                ps,
                scenario.exercise,
                scenario.ids[0],
                "pause",
                scenario.clock["now"],
            )
        assert caught.value.status_code == 422
        assert caught.value.detail == "Invalid exam event"
        db.rollback()
    finally:
        _teardown(db, scenario)
