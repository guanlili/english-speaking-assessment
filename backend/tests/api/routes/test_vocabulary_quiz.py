"""词汇限时测验：准入/个人计时/到时结算/一次作答/判分/补考/公布 闭环测试。

对应需求批次 2026-10-06（词汇限时测验与成绩管理）：
- 规则先行：未明确点开始不下发题面、不计时；
- 服务端强约束：开放/截止/参与次数/补考授权/个人计时全部服务端口径，
  刷新、多端进入、改客户端时间不能重置考试；
- 到时惰性结算：不依赖学生页面在线（教师侧触碰同样收口）；
- 每题一次 + 幂等键重传；测验回执只确认接收，不提前泄露答案与正误；
- 成绩公布与答案公布分别控制；未公布前学生只能看到提交状态，
  错词本不收录未公布测验的作答；
- 未答按零分计入必答题分母但与答错分列；
- 补考产生新答卷保留原答卷，有效成绩默认取最好；
- 切屏只计异常事件；练习重试机制不受影响。
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from httpx import Response
from sqlmodel import Session, select

from app.models import (
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularySession,
)
from tests.api.routes.test_vocabulary_student import (
    _create_classroom,
    _login_teacher,
    _make_class_book,
    _start_self,
    _words,
    _wrong_words,
)
from tests.utils.credential import make_student

VOCAB = "/api/v1/vocabulary"
TODAY = "/api/v1/classes/{code}/vocabulary/today"
RESULTS = "/api/v1/classes/{code}/vocabulary/results"


def _publish_quiz(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    word_ids: list[str],
    **extra: object,
) -> dict:
    body: dict = {
        "word_ids": word_ids,
        "prompt_types": ["meaning"],
        "mode": "quiz",
        "duration_minutes": 30,
        "pass_line": 60,
        **extra,
    }
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments", json=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start_quiz(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    assignment_id: str,
) -> Response:
    return client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions",
        json={"assignment_id": assignment_id},
        headers=headers,
    )


def _today(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.get(TODAY.format(code=code), headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _answer(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    item_index: int,
    answer: str,
    key: str | None = None,
) -> Response:
    return client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={
            "item_index": item_index,
            "prompt_type": "meaning",
            "answer": answer,
            **({"idempotency_key": key} if key else {}),
        },
        headers=headers,
    )


def _submit_quiz(client: TestClient, headers: dict[str, str], session_id: str):
    return client.post(f"{VOCAB}/sessions/{session_id}/submit", headers=headers)


def _expire_started_quiz(db: Session, session_id: str, minutes_ago: int = 40) -> None:
    """把已开始答卷的计时起点拨到过去（模拟时间流逝，服务器口径不变）。"""
    vocab_session = db.exec(
        select(VocabularySession).where(
            VocabularySession.id == uuid.UUID(session_id)  # type: ignore[arg-type]
        )
    ).one()
    vocab_session.quiz_started_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    db.add(vocab_session)
    db.commit()


def _quiz_setup(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    word_count: int = 4,
) -> tuple[dict[str, str], dict, dict, dict]:
    """教师 + 班级 + 词库 + 学生 + 已发布测验（默认 30 分钟 / 及格 60）。"""
    teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(
        client, teacher_headers, classroom["id"], _words(word_count)
    )
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    assignment = _publish_quiz(client, teacher_headers, classroom["code"], word_ids)
    return teacher_headers, student, classroom, assignment


# ── 发布校验 ───────────────────────────────────────────────────────


def test_quiz_publish_validation(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """测验发布：时长必填（5–240）、开放早于截止、听音要求标准音。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    _student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(4))
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    base_body = {"word_ids": word_ids, "prompt_types": ["meaning"], "mode": "quiz"}

    def publish(**extra: object) -> Response:
        return client.post(
            f"/api/v1/classes/{classroom['code']}/vocabulary/assignments",
            json={**base_body, **extra},
            headers=teacher_headers,
        )

    # 时长缺失 / 过短 → 422
    assert publish().status_code == 422
    assert publish(duration_minutes=3).status_code == 422
    # 截止在过去 → 422；开放晚于截止 → 422
    assert (
        publish(
            duration_minutes=30,
            due_at="2020-01-01T00:00:00Z",
        ).status_code
        == 422
    )
    assert (
        publish(
            duration_minutes=30,
            opens_at="2030-01-02T00:00:00Z",
            due_at="2030-01-01T00:00:00Z",
        ).status_code
        == 422
    )
    # 听音题型缺标准音 → 422（浏览器语音不能作为测验题源）
    assert (
        publish(
            duration_minutes=30,
            prompt_types=["meaning", "audio"],
        ).status_code
        == 422
    )
    # 合法发布
    resp = publish(duration_minutes=30)
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "quiz"
    assert resp.json()["duration_minutes"] == 30
    assert resp.json()["pass_line"] == 60
    # 练习任务不接受考试时长
    assert (
        client.post(
            f"/api/v1/classes/{classroom['code']}/vocabulary/assignments",
            json={
                "word_ids": word_ids,
                "prompt_types": ["meaning"],
                "mode": "practice",
                "duration_minutes": 30,
            },
            headers=teacher_headers,
        ).status_code
        == 422
    )


# ── 规则先行与个人计时 ─────────────────────────────────────────────


def test_quiz_rules_then_explicit_start(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """未开始只下发规则（无题面）；明确开始才计时；续做不重置计时。"""
    _teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db
    )
    code = classroom["code"]

    # 未开始：规则可见（时长/及格线/参与次数），题面为空
    plan = _today(client, student["headers"], code)
    assert plan["quiz"] is not None
    assert plan["quiz"]["status"] == "not_started"
    assert plan["quiz"]["duration_minutes"] == 30
    assert plan["quiz"]["pass_line"] == 60
    assert plan["quiz"]["attempts_allowed"] == 1
    assert plan["items"] == []

    # 明确开始：落个人计时（服务器时间），题面下发
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    assert resp.status_code == 200, resp.text
    started_at = resp.json()
    assert started_at["round_no"] == 1

    plan = _today(client, student["headers"], code)
    assert plan["quiz"]["status"] == "in_progress"
    assert plan["quiz"]["started_at"] is not None
    assert 0 < plan["quiz"]["remaining_seconds"] <= 30 * 60
    assert len(plan["items"]) == 4
    # 未作答不透露拼写
    assert all(item["headword"] is None for item in plan["items"])

    # 刷新 / 多端再次开始：同一答卷、计时起点不变
    vocab_session = db.exec(
        select(VocabularySession).where(
            VocabularySession.id == uuid.UUID(started_at["session_id"])  # type: ignore[arg-type]
        )
    ).one()
    first_start = vocab_session.quiz_started_at
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    assert resp.status_code == 200
    assert resp.json()["session_id"] == started_at["session_id"]
    db.refresh(vocab_session)
    assert vocab_session.quiz_started_at == first_start


def test_quiz_access_window(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """准入：未到开放时间不能开始；过截止不能开始（服务器时间口径）。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(3))
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assignment = _publish_quiz(
        client, teacher_headers, classroom["code"], word_ids, opens_at=future
    )
    resp = _start_quiz(client, student["headers"], classroom["code"], assignment["id"])
    assert resp.status_code == 422
    assert "尚未开放" in resp.json()["detail"]
    plan = _today(client, student["headers"], classroom["code"])
    assert plan["quiz"]["status"] == "not_started"
    assert plan["session_closed_reason"] == "not_open"

    # 截止时间已过：发布校验禁止过去时间，先正常发布再把 due_at 拨到过去
    # （模拟时间流逝；开给的 due 在发布时必须是未来时刻）
    assignment2 = _publish_quiz(client, teacher_headers, classroom["code"], word_ids)
    va = db.exec(
        select(VocabularyAssignment).where(
            VocabularyAssignment.id == uuid.UUID(assignment2["id"])  # type: ignore[arg-type]
        )
    ).one()
    va.due_at = datetime.now(UTC) - timedelta(hours=1)
    db.add(va)
    db.commit()
    resp = _start_quiz(client, student["headers"], classroom["code"], assignment2["id"])
    assert resp.status_code == 422
    assert "截止" in resp.json()["detail"]


# ── 一次作答 / 回执不泄露 / 主动交卷 ───────────────────────────────


def test_quiz_one_attempt_and_receipt(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """每题一次；断网重传走幂等键；回执只确认接收不返回答案与正误。"""
    _teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=3
    )
    code = classroom["code"]
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    session_id = resp.json()["session_id"]

    key = "quiz-retry-key-1"
    first = _answer(client, student["headers"], session_id, 0, "w01", key=key)
    assert first.status_code == 200, first.text
    body = first.json()
    # 回执不泄露：没有 is_correct / correct_spelling 字段
    assert "is_correct" not in body
    assert "correct_spelling" not in body
    assert body["received"] is True
    assert body["answered_count"] == 1

    # 同题第二次（新幂等键）→ 422
    second = _answer(client, student["headers"], session_id, 0, "w01", key="other")
    assert second.status_code == 422
    assert "一次" in second.json()["detail"]

    # 同幂等键重传（断网重试）→ 返回同一回执，不误伤
    replay = _answer(client, student["headers"], session_id, 0, "w01", key=key)
    assert replay.status_code == 200
    assert replay.json()["answered_count"] == 1

    # 主动交卷：终结答卷；此后作答 422；重复交卷幂等
    done = _submit_quiz(client, student["headers"], session_id)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "submitted"
    assert done.json()["end_reason"] == "manual"
    again = _submit_quiz(client, student["headers"], session_id)
    assert again.status_code == 200
    assert again.json()["end_reason"] == "manual"
    blocked = _answer(client, student["headers"], session_id, 1, "w02")
    assert blocked.status_code == 422

    # 教师未公布前：学生看到提交状态，无成绩无对错
    plan = _today(client, student["headers"], code)
    assert plan["quiz"]["status"] == "submitted"
    assert plan["quiz"]["score"] is None
    assert plan["quiz"]["score_visible"] is False
    assert plan["correct_first_count"] == 0  # 成绩维度被掩码
    answered_items = [i for i in plan["items"] if i["answered"]]
    assert all(
        i["headword"] is None and i["is_correct"] is None for i in answered_items
    )


# ── 到时结算（不依赖学生在线）──────────────────────────────────────


def test_quiz_timeout_settlement_without_student(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """到时惰性结算：教师侧触碰收口；此后拒绝作答；submitted_at=截止时刻。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=4
    )
    code = classroom["code"]
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    session_id = resp.json()["session_id"]
    # 答对 1 题、答错 1 题、留 2 题未答（未答按零分计入分母）。
    # 作答回执必须断言成功：否则被拒的作答会在结算断言处才爆（score=0），
    # 失败点远离真实原因（2026-10-08 CI 全量跑实际踩过）
    assert _answer(client, student["headers"], session_id, 0, "w01").status_code == 200
    assert (
        _answer(client, student["headers"], session_id, 1, "wrong-input").status_code
        == 200
    )

    # 时间流逝 40 分钟（时长 30）——学生不再发任何请求
    _expire_started_quiz(db, session_id, minutes_ago=40)

    # 教师查看结果 = 服务端结算触发点（无需学生在线）
    results = client.get(
        f"{RESULTS.format(code=code)}?assignment_id={assignment['id']}",
        headers=teacher_headers,
    ).json()
    row = next(
        r for r in results["students"] if r["student_id"] == student["student"]["id"]
    )
    assert row["status"] == "completed"
    assert row["quiz_end_reason"] == "timeout"
    assert results["timed_out_count"] == 1
    # 未答按零分计入分母：答对 1 / 总 4 → 25 分，不及格
    assert row["score"] == 25
    assert row["passed"] is False
    assert row["answered_count"] == 2
    assert row["correct_first_count"] == 1
    assert row["total_count"] == 4

    # 结算后学生作答被拒（服务端口径：客户端改时间无效）
    blocked = _answer(client, student["headers"], session_id, 2, "w03")
    assert blocked.status_code == 422
    assert "时间已到" in blocked.json()["detail"]

    # 学生侧视图：超时结束；submitted_at = 个人截止时刻（非结算触碰时刻）
    plan = _today(client, student["headers"], code)
    assert plan["quiz"]["status"] == "timed_out"
    assert plan["quiz"]["end_reason"] == "timeout"
    assert plan["quiz"]["submitted_at"] is not None


def test_quiz_deadline_earlier_of_personal_or_due(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """有效结束时间 = 个人开始+时长 与 任务截止 中较早者（此处截止先到）。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(2, "d"))
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    # 任务截止先到：先正常发布并开始，再把 due_at 拨到过去 1 分钟
    # （发布校验要求 due 为未来时刻；开考后时间流逝由服务端口径判定）
    assignment = _publish_quiz(client, teacher_headers, classroom["code"], word_ids)
    resp = _start_quiz(client, student["headers"], classroom["code"], assignment["id"])
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]
    va = db.exec(
        select(VocabularyAssignment).where(
            VocabularyAssignment.id == uuid.UUID(assignment["id"])  # type: ignore[arg-type]
        )
    ).one()
    va.due_at = datetime.now(UTC) - timedelta(minutes=1)
    db.add(va)
    db.commit()
    # 个人开始拨到 6 分钟前：个人时长（30 分钟）未到，但任务截止（1 分钟前）已过
    _expire_started_quiz(db, session_id, minutes_ago=6)
    results = client.get(
        f"{RESULTS.format(code=classroom['code'])}?assignment_id={assignment['id']}",
        headers=teacher_headers,
    ).json()
    row = next(
        r for r in results["students"] if r["student_id"] == student["student"]["id"]
    )
    assert row["quiz_end_reason"] == "timeout"
    assert row["status"] == "completed"


# ── 并发开始 / 并发交卷 ────────────────────────────────────────────


def test_quiz_concurrent_start(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """并发开始只产生一份答卷（唯一索引 + 冲突重查）。"""
    from concurrent.futures import ThreadPoolExecutor

    _teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=3
    )
    code = classroom["code"]
    base = f"/api/v1/classes/{code}/vocabulary/sessions"

    def start() -> dict:
        resp = client.post(
            base,
            json={"assignment_id": assignment["id"]},
            headers=student["headers"],
        )
        return {"status": resp.status_code, "body": resp.json()}

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: start(), range(2)))
    assert all(o["status"] == 200 for o in outcomes), outcomes
    assert len({o["body"]["session_id"] for o in outcomes}) == 1


# ── 成绩/答案公布与可见规则 ────────────────────────────────────────


def test_quiz_publish_grades_and_answers(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """成绩与答案分别公布；错词本只收录已公布答案的测验作答。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=3
    )
    code = classroom["code"]
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    session_id = resp.json()["session_id"]
    # 作答必须成功落库：回执弱断言会把 422 吞成下游「成绩为 0 / 错词缺失」
    # 的漂移失败，失败点远离真实原因（2026-10-08 CI 全量跑实际踩过）
    assert _answer(client, student["headers"], session_id, 0, "w01").status_code == 200
    assert (
        _answer(client, student["headers"], session_id, 1, "bad-input").status_code
        == 200
    )
    _submit_quiz(client, student["headers"], session_id)

    # 未公布：错词本不含测验作答（bad-input 对应的 w02 不出现）
    wrong = _wrong_words(client, student["headers"], code)
    assert all(w["headword"] != "w02" for w in wrong)
    # 历史行掩码：只有提交状态，无成绩
    history = client.get(
        f"/api/v1/classes/{code}/vocabulary/student/history",
        headers=student["headers"],
    ).json()["items"]
    quiz_rows = [h for h in history if h["is_quiz"]]
    assert quiz_rows and all(h["masked"] for h in quiz_rows)
    assert all(h["correct_first_count"] == 0 for h in quiz_rows)

    # 公布成绩：学生看到分数（best），答案仍不揭示
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}/publish-grades",
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    plan = _today(client, student["headers"], code)
    assert plan["quiz"]["score_visible"] is True
    assert plan["quiz"]["score"] == 33  # 1/3 → 33
    assert plan["quiz"]["passed"] is False
    assert plan["quiz"]["answers_visible"] is False
    answered_items = [i for i in plan["items"] if i["answered"]]
    assert all(
        i["headword"] is None and i["is_correct"] is None for i in answered_items
    )
    # 错词本仍然不含（答案未公布）
    wrong = _wrong_words(client, student["headers"], code)
    assert all(w["headword"] != "w02" for w in wrong)

    # 公布答案：答卷揭示拼写与对错，错词本收录
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}/publish-answers",
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    plan = _today(client, student["headers"], code)
    answered_items = [i for i in plan["items"] if i["answered"]]
    assert all(i["headword"] is not None for i in answered_items)
    assert any(i["is_correct"] is False for i in answered_items)
    wrong = _wrong_words(client, student["headers"], code)
    assert any(w["headword"] == "w02" for w in wrong)

    # 公布操作幂等
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}/publish-answers",
        headers=teacher_headers,
    )
    assert resp.status_code == 200


# ── 补考授权 ───────────────────────────────────────────────────────


def test_quiz_retake_flow(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """默认一次参与；授权后补考产生新答卷保留原答卷；有效成绩取最好。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=2
    )
    code = classroom["code"]
    first = _start_quiz(client, student["headers"], code, assignment["id"])
    first_session = first.json()["session_id"]
    _answer(client, student["headers"], first_session, 0, "w01")  # 对 1
    _answer(client, student["headers"], first_session, 1, "nope")  # 错 1
    _submit_quiz(client, student["headers"], first_session)

    # 未授权补考：再次开始 → 422
    denied = _start_quiz(client, student["headers"], code, assignment["id"])
    assert denied.status_code == 422
    assert "补考" in denied.json()["detail"]

    # 授权补考（教师；非名单学生 404）
    other = make_student(db, client, code, name="旁听")
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}"
        f"/students/{other['student']['id']}/grant-retake",
        headers=teacher_headers,
    )
    assert resp.status_code == 404, resp.text
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}"
        f"/students/{student['student']['id']}/grant-retake",
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text

    # 补考：新答卷（round_no=2），原答卷保留
    retake = _start_quiz(client, student["headers"], code, assignment["id"])
    assert retake.status_code == 200, retake.text
    second_session = retake.json()
    assert second_session["round_no"] == 2
    assert second_session["session_id"] != first_session
    _answer(client, student["headers"], second_session["session_id"], 0, "w01")
    _answer(client, student["headers"], second_session["session_id"], 1, "w02")
    _submit_quiz(client, student["headers"], second_session["session_id"])

    # 有效成绩 = 最好（第二次 100 > 第一次 50），教师结果可见两次参与
    results = client.get(
        f"{RESULTS.format(code=code)}?assignment_id={assignment['id']}",
        headers=teacher_headers,
    ).json()
    row = next(
        r for r in results["students"] if r["student_id"] == student["student"]["id"]
    )
    assert row["attempt_count"] == 2
    assert row["retake_granted"] is True
    assert row["score"] == 100
    assert row["passed"] is True
    assert len(row["rounds"]) == 2
    # 学生侧公布后看到最好成绩
    client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}/publish-grades",
        headers=teacher_headers,
    )
    plan = _today(client, student["headers"], code)
    assert plan["quiz"]["score"] == 100
    assert plan["quiz"]["attempts_allowed"] == 2
    # 补考次数用完
    third = _start_quiz(client, student["headers"], code, assignment["id"])
    assert third.status_code == 422
    assert "补考次数也已用完" in third.json()["detail"]


# ── 切屏事件 / 导出 / 练习不受影响 ─────────────────────────────────


def test_quiz_tab_switch_record_only(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """切屏只计异常事件供教师参考；非测验会话不记录切屏。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    student = make_student(db, client, classroom["code"])
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(2))
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    assignment = _publish_quiz(client, teacher_headers, classroom["code"], word_ids)
    code = classroom["code"]
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    session_id = resp.json()["session_id"]
    for _ in range(2):
        resp = client.post(
            f"{VOCAB}/sessions/{session_id}/tab-switch", headers=student["headers"]
        )
        assert resp.status_code == 200, resp.text
    assert resp.json()["tab_switch_count"] == 2

    # 教师结果可见事件数（仅记录，不改变状态与成绩）
    results = client.get(
        f"{RESULTS.format(code=code)}?assignment_id={assignment['id']}",
        headers=teacher_headers,
    ).json()
    row = next(
        r for r in results["students"] if r["student_id"] == student["student"]["id"]
    )
    assert row["tab_switch_count"] == 2

    # 非测验会话（自主练习轮）切屏 → 422
    self_session = _start_self(client, student["headers"], code, book["id"])
    resp = client.post(
        f"{VOCAB}/sessions/{self_session['session_id']}/tab-switch",
        headers=student["headers"],
    )
    assert resp.status_code == 422


def test_quiz_results_export_csv(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """成绩导出：CSV 含固定应考名单与状态/成绩/切屏列。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=2
    )
    code = classroom["code"]
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    session_id = resp.json()["session_id"]
    _answer(client, student["headers"], session_id, 0, "w01")
    _submit_quiz(client, student["headers"], session_id)

    resp = client.get(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}/results-export",
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.content.decode("utf-8-sig")
    lines = [line for line in text.strip().splitlines() if line]
    assert lines[0].startswith("姓名")
    # 表头 + 名单内全部学生（含未参加者）
    assert len(lines) == 2
    assert "50" in lines[1]  # 1/2 → 50 分
    assert "主动交卷" in lines[1]


def test_quiz_roster_and_unattended_student(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """固定应考名单：未参加学生也在结果里，状态未开始。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=2
    )
    code = classroom["code"]
    classmate = make_student(db, client, code, name="未参加同学")
    del classmate
    # 名单在发布时固化：后入班同学不在名单内，但首发名单学生未参加仍在
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    session_id = resp.json()["session_id"]
    _submit_quiz(client, student["headers"], session_id)
    results = client.get(
        f"{RESULTS.format(code=code)}?assignment_id={assignment['id']}",
        headers=teacher_headers,
    ).json()
    assert results["target_count"] == 1  # 发布时名单 1 人
    row = results["students"][0]
    assert row["status"] == "completed"
    assert row["score"] == 0  # 未答按零分计入分母，与答错分列
    assert row["answered_count"] == 0
    assert row["correct_first_count"] == 0


# ── 断网重传与交卷/结算竞态（wise-quarry-trout 批次03）───────────────


def _answer_body(item_index: int, answer: str, key: str | None) -> dict:
    body: dict = {
        "item_index": item_index,
        "prompt_type": "meaning",
        "answer": answer,
    }
    if key:
        body["idempotency_key"] = key
    return body


def test_quiz_replay_after_submit_returns_receipt(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """作答成功但回包丢失：交卷/到时后原键重试仍取得成功回执，不新增答案。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db
    )
    resp = _start_quiz(client, student["headers"], classroom["code"], assignment["id"])
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]

    key = f"lost-{uuid.uuid4()}"
    accepted = _answer(client, student["headers"], session_id, 0, "apple", key)
    assert accepted.status_code == 200, accepted.text

    # 手动交卷后原键重试（模拟回包丢失后的重传）
    assert _submit_quiz(client, student["headers"], session_id).status_code == 200
    replay = _answer(client, student["headers"], session_id, 0, "apple", key)
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["received"] is True
    assert body["item_index"] == 0
    assert body["session_status"] == "submitted"
    # 回执不泄露正误与答案
    assert "is_correct" not in body
    assert "correct_spelling" not in body

    # 不新增答案；重放不改写终态
    answers = db.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == uuid.UUID(session_id)  # type: ignore[arg-type]
        )
    ).all()
    assert len(answers) == 1

    # 同键不同答案：稳定 422（客户端误用，不得返回旧作答）
    mismatch = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json=_answer_body(0, "banana", key),
        headers=student["headers"],
    )
    assert mismatch.status_code == 422
    assert "幂等键" in mismatch.json()["detail"]

    # 交卷后新键新答案：正常门禁拒绝（重放豁免不得成为绕过口）
    fresh = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json=_answer_body(1, "banana", None),
        headers=student["headers"],
    )
    assert fresh.status_code == 422
    assert "交卷" in fresh.json()["detail"]


def test_quiz_replay_after_deadline_returns_receipt(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """到时结算后原键重试同样取得回执（截止门禁不挡成功重放）。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db
    )
    resp = _start_quiz(client, student["headers"], classroom["code"], assignment["id"])
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]

    key = f"late-{uuid.uuid4()}"
    accepted = _answer(client, student["headers"], session_id, 0, "apple", key)
    assert accepted.status_code == 200, accepted.text

    _expire_started_quiz(db, session_id)
    replay = _answer(client, student["headers"], session_id, 0, "apple", key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["received"] is True
    answers = db.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == uuid.UUID(session_id)  # type: ignore[arg-type]
        )
    ).all()
    assert len(answers) == 1


def test_quiz_concurrent_same_item_different_keys(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """并发同题不同键（测验每题一次）：恰好一个 200、一个 422，不再出现 500。"""
    import threading

    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db
    )
    resp = _start_quiz(client, student["headers"], classroom["code"], assignment["id"])
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]

    barrier = threading.Barrier(2)

    def submit(key: str) -> int:
        barrier.wait()
        return _answer(
            client, student["headers"], session_id, 0, "apple", key
        ).status_code

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(submit, f"race-a-{uuid.uuid4()}"),
            pool.submit(submit, f"race-b-{uuid.uuid4()}"),
        ]
        statuses = sorted(f.result() for f in futures)

    assert statuses == [200, 422], statuses
    answers = db.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == uuid.UUID(session_id),  # type: ignore[arg-type]
            VocabularyAnswer.item_index == 0,
        )
    ).all()
    assert len(answers) == 1


def test_quiz_concurrent_same_key(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """并发同键重传：两个都拿到成功回执，落库恰好一条。"""
    import concurrent.futures
    import threading

    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db
    )
    resp = _start_quiz(client, student["headers"], classroom["code"], assignment["id"])
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]

    key = f"same-{uuid.uuid4()}"
    barrier = threading.Barrier(2)

    def submit() -> int:
        barrier.wait()
        return _answer(
            client, student["headers"], session_id, 0, "apple", key
        ).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        statuses = [f.result() for f in futures]

    assert statuses == [200, 200], statuses
    answers = db.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == uuid.UUID(session_id)  # type: ignore[arg-type]
        )
    ).all()
    assert len(answers) == 1


def test_quiz_concurrent_answer_vs_manual_submit(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """作答与手动交卷并发：无 500；若作答被接纳则计入成绩，交卷后不再接纳。"""
    import concurrent.futures
    import threading

    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db
    )
    resp = _start_quiz(client, student["headers"], classroom["code"], assignment["id"])
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]
    session_uuid = uuid.UUID(session_id)

    barrier = threading.Barrier(2)

    def answer() -> int:
        barrier.wait()
        return _answer(
            client, student["headers"], session_id, 0, "apple", f"vs-{uuid.uuid4()}"
        ).status_code

    def submit() -> int:
        barrier.wait()
        return _submit_quiz(client, student["headers"], session_id).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f_answer = pool.submit(answer)
        f_submit = pool.submit(submit)
        answer_status = f_answer.result()
        submit_status = f_submit.result()

    assert submit_status == 200
    assert answer_status in (200, 422), answer_status
    db.expire_all()
    vocab_session = db.get(VocabularySession, session_uuid)
    assert vocab_session is not None
    assert vocab_session.status == "submitted"
    answers = db.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == session_uuid,  # type: ignore[arg-type]
            VocabularyAnswer.item_index == 0,
        )
    ).all()
    if answer_status == 200:
        assert len(answers) == 1  # 交卷前被锁内接纳，计入成绩
    else:
        assert len(answers) == 0  # 交卷已生效，锁内拒绝


def test_quiz_answer_vs_timeout_settlement_race(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    """到时后作答与结算并发：作答被锁内终结拒绝，结算与作答二选一终结，状态一致。"""
    import concurrent.futures
    import threading

    from app.services import vocab_quiz as quiz_service

    teacher_headers, student, classroom, assignment_row = _quiz_setup(
        client, superuser_token_headers, db
    )
    resp = _start_quiz(
        client, student["headers"], classroom["code"], assignment_row["id"]
    )
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]
    session_uuid = uuid.UUID(session_id)
    _expire_started_quiz(db, session_id)

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def answer() -> None:
        barrier.wait()
        results["answer"] = _answer(
            client, student["headers"], session_id, 0, "apple", f"to-{uuid.uuid4()}"
        ).status_code

    def settle() -> None:
        barrier.wait()
        with Session(db.get_bind()) as session:
            assignment = session.get(
                VocabularyAssignment, uuid.UUID(assignment_row["id"])
            )
            vocab_session = session.get(VocabularySession, session_uuid)
            assert assignment is not None and vocab_session is not None
            quiz_service.settle_due_sessions(session, assignment)
        results["settle"] = "ok"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(answer), pool.submit(settle)]
        for f in futures:
            f.result()

    assert results["answer"] == 422, results
    assert (
        "自动交卷"
        in client.post(
            f"{VOCAB}/sessions/{session_id}/answers",
            json=_answer_body(0, "apple", None),
            headers=student["headers"],
        ).json()["detail"]
    )
    db.expire_all()
    vocab_session = db.get(VocabularySession, session_uuid)
    assert vocab_session is not None
    assert vocab_session.status == "submitted"
    assert vocab_session.end_reason == "timeout"
    answers = db.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == session_uuid  # type: ignore[arg-type]
        )
    ).all()
    assert len(answers) == 0


# ── 有效成绩口径统一与查询消重（wise-quarry-trout 批次05）──────────


def _results_row(
    client: TestClient,
    teacher_headers: dict[str, str],
    code: str,
    assignment_id: str,
    student_id: str,
) -> dict:
    resp = client.get(
        f"{RESULTS.format(code=code)}?assignment_id={assignment_id}",
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    return next(r for r in resp.json()["students"] if r["student_id"] == student_id)


def _grant_retake(
    client: TestClient,
    teacher_headers: dict[str, str],
    code: str,
    assignment_id: str,
    student: dict,
) -> None:
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment_id}"
        f"/students/{student['student']['id']}/grant-retake",
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text


def test_quiz_effective_grade_counts_share_same_paper(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """两题两轮各对不同一题：成绩 50、答对 1/2 来自同一份答卷（同分取较早轮），
    逐词错误分布不被补考的正确掩盖——不再出现「50 分但 2/2 对」。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=2
    )
    code = classroom["code"]
    first = _start_quiz(client, student["headers"], code, assignment["id"]).json()
    _answer(client, student["headers"], first["session_id"], 0, "w01")  # 对
    _answer(client, student["headers"], first["session_id"], 1, "nope")  # 错
    _submit_quiz(client, student["headers"], first["session_id"])

    _grant_retake(client, teacher_headers, code, assignment["id"], student)
    second = _start_quiz(client, student["headers"], code, assignment["id"]).json()
    assert second["round_no"] == 2
    _answer(client, student["headers"], second["session_id"], 0, "nah")  # 错
    _answer(client, student["headers"], second["session_id"], 1, "w02")  # 对
    _submit_quiz(client, student["headers"], second["session_id"])

    row = _results_row(
        client, teacher_headers, code, assignment["id"], student["student"]["id"]
    )
    # 同分（各 50）取较早轮：成绩与答对/答错/未答同源
    assert row["score"] == 50
    assert row["effective_round_no"] == 1
    assert row["correct_first_count"] == 1
    assert row["answered_count"] == 2
    assert row["total_count"] == 2
    # 逐轮明细仍独立可见（补考轮 1/2）
    assert [r["round_no"] for r in row["rounds"]] == [1, 2]
    assert row["rounds"][1]["correct_first_count"] == 1

    # 逐词错误分布来自有效答卷（第 1 轮）：w02 的错没有被第 2 轮的对称
    words = {
        w["headword"]: w
        for w in client.get(
            f"{RESULTS.format(code=code)}?assignment_id={assignment['id']}",
            headers=teacher_headers,
        ).json()["words"]
    }
    assert words["w01"]["correct_first_count"] == 1
    assert words["w01"]["error_count"] == 0
    assert words["w02"]["error_count"] == 1
    assert words["w02"]["correct_first_count"] == 0
    assert any(m["answer"] == "nope" for m in words["w02"]["misspellings"])


def test_quiz_in_progress_retake_keeps_finalized_grade(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """补考进行中只作进度：不改写已终结的有效成绩与计数来源。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=2
    )
    code = classroom["code"]
    first = _start_quiz(client, student["headers"], code, assignment["id"]).json()
    _answer(client, student["headers"], first["session_id"], 0, "w01")
    _submit_quiz(client, student["headers"], first["session_id"])  # 1/2 = 50

    _grant_retake(client, teacher_headers, code, assignment["id"], student)
    second = _start_quiz(client, student["headers"], code, assignment["id"]).json()
    _answer(client, student["headers"], second["session_id"], 0, "w01")  # 进行中 1/2

    row = _results_row(
        client, teacher_headers, code, assignment["id"], student["student"]["id"]
    )
    assert row["status"] == "in_progress"
    assert row["score"] == 50  # 已终结成绩不被进行中补考覆盖
    assert row["effective_round_no"] == 1
    assert row["correct_first_count"] == 1  # 计数来自有效答卷
    assert row["rounds"][1]["answered_count"] == 1  # 进度按轮展示


def test_quiz_class_results_query_count_constant(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """class_results 查询数不随参与学生数增长（批量读取 + 纯聚合）。"""
    from sqlalchemy import event

    from app.services import vocabulary as vocab_service

    # 名单在发布时固定：先入班、后发布
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    code = classroom["code"]
    roster = [make_student(db, client, code, f"查询{i}") for i in range(8)]
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(2))
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    assignment = _publish_quiz(client, teacher_headers, code, word_ids)

    def _run_student(made: dict) -> None:
        _start = _start_quiz(client, made["headers"], code, assignment["id"])
        assert _start.status_code == 200, _start.text
        started = _start.json()
        _answer(client, made["headers"], started["session_id"], 0, "w01")
        _answer(client, made["headers"], started["session_id"], 1, "w02")
        _submit_quiz(client, made["headers"], started["session_id"])

    counts: list[int] = []

    def _count_queries() -> int:
        counter = {"n": 0}

        def _before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):  # type: ignore[no-untyped-def]
            if statement.lstrip().upper().startswith("SELECT"):
                counter["n"] += 1

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", _before_cursor_execute)
        try:
            with Session(engine) as session:
                assignment_row = session.get(
                    VocabularyAssignment, uuid.UUID(assignment["id"])
                )
                assert assignment_row is not None
                vocab_service.class_results(session, assignment_row)
        finally:
            event.remove(engine, "before_cursor_execute", _before_cursor_execute)
        return counter["n"]

    # 阶段一：名单全班（8 人固定）但只有 2 人交卷
    for made in roster[:2]:
        _run_student(made)
    counts.append(_count_queries())
    # 阶段二：其余 6 人也交卷（参与者 ×4）
    for made in roster[2:]:
        _run_student(made)
    counts.append(_count_queries())
    # 参与学生数 2 → 8，查询数不得增长（名单数固定，聚合复用批量读取）
    assert counts[1] == counts[0], counts


def test_quiz_export_csv_formula_guard(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """导出 CSV：以 =/+/-/@ 开头的姓名加 ' 前缀防公式执行；数字成绩不受影响。"""
    import csv as csv_module
    import io

    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=1
    )
    code = classroom["code"]
    # 直接改显示名（导入通道之外的极端姓名）
    with Session(db.get_bind()) as session:
        from app.models import Student

        row = session.get(Student, uuid.UUID(student["student"]["id"]))
        assert row is not None
        row.display_name = '=HYPERLINK("http://evil","x")'
        session.add(row)
        session.commit()

    started = _start_quiz(client, student["headers"], code, assignment["id"]).json()
    _answer(client, student["headers"], started["session_id"], 0, "w01")
    _submit_quiz(client, student["headers"], started["session_id"])

    resp = client.get(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}"
        f"/results-export",
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("utf-8-sig")
    rows = list(csv_module.reader(io.StringIO(text)))
    header = rows[0]
    body = rows[1]
    name_cell = body[header.index("姓名")]
    assert name_cell.startswith("'=")
    score_cell = body[header.index("成绩")]
    assert score_cell == "100"  # 数字成绩不加前缀


# ── 返修C（R08/R09/R10/R11）：终态规则 / 结算范围 / 进行中进度 / NFKC 重放 ──


def test_manual_submit_not_rewritten_by_late_answer(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """R08：先主动交卷、后到时——已确认的 manual 终态不被改写成 timeout。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=2
    )
    code = classroom["code"]
    started = _start_quiz(client, student["headers"], code, assignment["id"]).json()
    _answer(client, student["headers"], started["session_id"], 0, "w01")
    assert (
        _submit_quiz(client, student["headers"], started["session_id"]).status_code
        == 200
    )

    _expire_started_quiz(db, started["session_id"])
    # 到时后的作答：终态先判 → 422 已交卷（不是「已自动交卷」）
    late = _answer(client, student["headers"], started["session_id"], 1, "w02")
    assert late.status_code == 422
    assert "交卷" in late.json()["detail"]

    row = db.exec(
        select(VocabularySession).where(
            VocabularySession.id == uuid.UUID(started["session_id"])  # type: ignore[arg-type]
        )
    ).one()
    assert row.status == "submitted"
    assert row.end_reason == "manual"  # 不被覆写为 timeout
    assert row.submitted_at is not None
    manual_at = row.submitted_at
    # 教师触碰触发的批量结算同样不改写
    client.get(
        f"{RESULTS.format(code=code)}?assignment_id={assignment['id']}",
        headers=teacher_headers,
    )
    db.refresh(row)
    assert row.end_reason == "manual"
    assert row.submitted_at == manual_at


def test_manual_submit_crossing_deadline_settles_timeout(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """R08：交卷等锁/延迟期间跨过截止——按超时结算，submitted_at 取截止时刻。"""
    from app.services import vocab_quiz as quiz_service

    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=2
    )
    code = classroom["code"]
    started = _start_quiz(client, student["headers"], code, assignment["id"]).json()
    session_uuid = uuid.UUID(started["session_id"])

    with Session(db.get_bind()) as session:
        # 截止已过（未结算）：交卷在锁内按服务器时间判 timeout
        _expire_started_quiz(db, started["session_id"])
        vocab_session = session.get(VocabularySession, session_uuid)
        assignment_row = session.get(VocabularyAssignment, uuid.UUID(assignment["id"]))
        assert vocab_session is not None and assignment_row is not None
        finalized = quiz_service.submit_quiz_session(
            session, vocab_session, assignment_row
        )
        assert finalized.end_reason == "timeout"
        deadline = quiz_service.quiz_deadline(vocab_session, assignment_row)
        assert deadline is not None
        assert finalized.submitted_at == deadline


def test_concurrent_submits_and_bulk_settle_no_deadlock(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """R09：两份已到期答卷并发手动交卷 + 批量结算——无跨会话锁环、无 500。"""
    import concurrent.futures
    import threading

    from app.services import vocab_quiz as quiz_service

    teacher_headers, classroom = None, None
    teacher_headers = _login_teacher(db, client)[1]
    classroom = _create_classroom(client, teacher_headers)
    code = classroom["code"]
    students = [make_student(db, client, code, f"死锁{i}") for i in range(2)]
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(2))
    word_ids = [
        w["id"]
        for w in client.get(
            f"{VOCAB}/books/{book['id']}", headers=teacher_headers
        ).json()["words"]
    ]
    assignment = _publish_quiz(client, teacher_headers, code, word_ids)

    session_ids = []
    for made in students:
        started = _start_quiz(client, made["headers"], code, assignment["id"]).json()
        _answer(client, made["headers"], started["session_id"], 0, "w01")
        _expire_started_quiz(db, started["session_id"])
        session_ids.append(uuid.UUID(started["session_id"]))

    barrier = threading.Barrier(3)
    outcomes: dict[str, object] = {}

    def manual_submit(sid: uuid.UUID) -> None:
        barrier.wait()
        try:
            with Session(db.get_bind()) as session:
                vocab_session = session.get(VocabularySession, sid)
                assert vocab_session is not None
                assignment_row = session.get(
                    VocabularyAssignment, uuid.UUID(assignment["id"])
                )
                assert assignment_row is not None
                quiz_service.submit_quiz_session(session, vocab_session, assignment_row)
            outcomes[str(sid)] = "ok"
        except Exception as exc:  # noqa: BLE001
            outcomes[str(sid)] = repr(exc)

    def bulk_settle() -> None:
        barrier.wait()
        try:
            with Session(db.get_bind()) as session:
                assignment_row = session.get(
                    VocabularyAssignment, uuid.UUID(assignment["id"])
                )
                assert assignment_row is not None
                quiz_service.settle_due_sessions(session, assignment_row)
            outcomes["bulk"] = "ok"
        except Exception as exc:  # noqa: BLE001
            outcomes["bulk"] = repr(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(manual_submit, sid) for sid in session_ids]
        futures.append(pool.submit(bulk_settle))
        for f in futures:
            f.result(timeout=15)

    for key, value in outcomes.items():
        assert value == "ok", (key, value)  # 无 DeadlockDetected / 无异常
    for sid in session_ids:
        db.expire_all()
        row = db.get(VocabularySession, sid)
        assert row is not None
        assert row.status == "submitted"


def test_first_quiz_in_progress_shows_progress_not_zero(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """R10：首考进行中已答一题——主行进度 1/2（不是 0），成绩保持空。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=2
    )
    code = classroom["code"]
    started = _start_quiz(client, student["headers"], code, assignment["id"]).json()
    _answer(client, student["headers"], started["session_id"], 0, "w01")

    row = _results_row(
        client, teacher_headers, code, assignment["id"], student["student"]["id"]
    )
    assert row["status"] == "in_progress"
    assert row["answered_count"] == 1  # 实时进度，不再报 0
    assert row["correct_first_count"] == 1
    assert row["score"] is None  # 尚无有效成绩
    assert row["effective_round_no"] is None

    # CSV：未答 = 1（2-1），不把已答当未答
    import csv as csv_module
    import io

    resp = client.get(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}"
        f"/results-export",
        headers=teacher_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = list(csv_module.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    header, body = rows[0], rows[1]
    assert body[header.index("状态")].startswith("进行中")
    assert body[header.index("答对")] == "1"
    assert body[header.index("未答")] == "1"
    assert body[header.index("成绩")] == ""


def test_nfkc_expanding_answers_length_guard_and_replay(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """R11：NFKC 扩长载荷先按长度拒绝；等价展开的原文可作同键重放。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=1
    )
    code = classroom["code"]
    started = _start_quiz(client, student["headers"], code, assignment["id"]).json()
    session_id = started["session_id"]

    # 原文 86 字符、NFKC 后 258 字符：422 拒绝（不落库截断值）
    too_long = _answer(client, student["headers"], session_id, 0, "ﬃ" * 86)
    assert too_long.status_code == 422
    assert "过长" in too_long.json()["detail"]

    # 255 字符等价原文：正常落库；同键用 NFKC 等价写法（ﬃ×85）可重放
    key = f"nfkc-{uuid.uuid4()}"
    first = _answer(client, student["headers"], session_id, 0, "ffi" * 85, key)
    assert first.status_code == 200, first.text
    replay = _answer(client, student["headers"], session_id, 0, "ﬃ" * 85, key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["item_index"] == 0

    # 超限载荷即便带同键也先按长度拒绝，不进入截断碰撞比较
    over = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json=_answer_body(0, "ﬃ" * 86, key),
        headers=student["headers"],
    )
    assert over.status_code == 422
    assert "过长" in over.json()["detail"]
