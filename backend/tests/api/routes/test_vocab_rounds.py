"""词汇多任务并存与多轮练习回归测试。

口径：
- 多任务并存：新发布不归档其他任务；聚焦 = 名单内进行中任务里最早截止的
  未完成者，全部完成（或无 due 区分）则最近发布；
- 轮次：同学生同任务至多一个未结束轮次；重复/并发开练幂等续做；
  全部轮次结束后再开练 → round_no=max+1 的新复习轮；
- 任务成绩锁定首轮（round_no=1 首答）：复习轮不改写教师统计与完成度；
- 截止/归档：不再接受新作答，历史可见；未结束轮标记关闭原因；
- 存量数据：迁移后旧会话 round_no=1，行为不变。
"""

import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app import crud
from app.models import User, UserCreate, VocabularyAssignment, VocabularySession
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"

WORDS_2 = [
    {"headword": "apple", "part_of_speech": "n.", "meaning_zh": "苹果"},
    {"headword": "banana", "part_of_speech": "n.", "meaning_zh": "香蕉"},
]


def _login_teacher(db: Session, client: TestClient) -> tuple[User, dict[str, str]]:
    email, password = random_email(), random_lower_string()
    user = crud.create_user(
        session=db, user_create=UserCreate(email=email, password=password)
    )
    resp = client.post(
        "/api/v1/login/access-token",
        data={"username": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return user, {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_classroom(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post("/api/v1/classes", json={"class_size": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_public_book(
    client: TestClient,
    admin_headers: dict[str, str],
    words: list[dict],
    title: str = "多轮测试词库",
) -> dict:
    resp = client.post(
        f"{VOCAB}/books",
        json={"title": title, "scope": "public", "words": words},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _publish(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    word_ids: list[str],
    **extra: object,
) -> dict:
    body: dict = {"word_ids": word_ids, "prompt_types": ["meaning"]}
    body.update(extra)
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments", json=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _today(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    assignment_id: str | None = None,
    round_no: str | None = None,
) -> dict:
    params: dict[str, str] = {}
    if assignment_id is not None:
        params["assignment_id"] = assignment_id
    if round_no is not None:
        params["round_no"] = round_no
    resp = client.get(
        f"/api/v1/classes/{code}/vocabulary/today",
        params=params or None,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    assignment_id: str | None = None,
    round_: str | None = None,
) -> dict:
    body: dict = {}
    if assignment_id is not None:
        body["assignment_id"] = assignment_id
    if round_ is not None:
        body["round"] = round_
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions", json=body, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _answer(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    item_index: int,
    answer: str,
    expect: int = 200,
) -> dict:
    resp = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={
            "item_index": item_index,
            "prompt_type": "meaning",
            "answer": answer,
        },
        headers=headers,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _results(
    client: TestClient, headers: dict[str, str], code: str, assignment_id: str
) -> dict:
    resp = client.get(
        f"/api/v1/classes/{code}/vocabulary/results",
        params={"assignment_id": assignment_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rounds_of(db: Session, assignment_id: str) -> list[VocabularySession]:
    return list(
        db.exec(
            select(VocabularySession).where(
                col(VocabularySession.assignment_id) == uuid.UUID(assignment_id)
            )
        ).all()
    )


def _finish_round(
    client: TestClient, headers: dict[str, str], session_id: str, correct: bool
) -> None:
    """把一轮 2 词全部作答完（全部判对或全部判错）。"""
    answers = ["apple", "banana"] if correct else ["xxx", "yyy"]
    for idx, answer in enumerate(answers):
        _answer(client, headers, session_id, idx, answer)


def test_multi_task_coexist_and_focus(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """多任务并存：互不归档；聚焦=最早截止的未完成；完成一个不影响另一个。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "多任务学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]

    first = _publish(
        client,
        headers,
        code,
        word_ids,
        title="第一期",
        due_at=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
    )
    second = _publish(
        client,
        headers,
        code,
        word_ids,
        title="第二期",
        due_at=(datetime.now(UTC) + timedelta(days=7)).isoformat(),
    )
    assert first["status"] == "published"
    assert second["status"] == "published"

    plan = _today(client, student["headers"], code)
    rows = {r["assignment_id"]: r for r in plan["assignments"]}
    assert set(rows) == {first["id"], second["id"]}
    assert all(r["progress"] == "not_started" for r in rows.values())
    assert not any(r["overdue"] for r in rows.values())
    # 聚焦：最早截止的未完成任务 = 第一期
    assert plan["assignment"]["id"] == first["id"]

    # 教师任务列表：两任务并行，各自名单汇总
    teacher_rows = {
        r["assignment"]["id"]: r
        for r in client.get(
            f"/api/v1/classes/{code}/vocabulary/assignments", headers=headers
        ).json()
    }
    assert set(teacher_rows) == {first["id"], second["id"]}
    assert all(r["target_count"] == 1 for r in teacher_rows.values())
    assert all(r["not_started_count"] == 1 for r in teacher_rows.values())

    # 完成第一期 → 教师面板该任务 completed=1，第二期不受影响
    session_id = _start(client, student["headers"], code, first["id"])["session_id"]
    _finish_round(client, student["headers"], session_id, correct=True)
    results_first = _results(client, headers, code, first["id"])
    assert results_first["completed_count"] == 1
    results_second = _results(client, headers, code, second["id"])
    assert results_second["not_started_count"] == 1

    # 聚焦切换到第二期（第一期已完成）
    plan = _today(client, student["headers"], code)
    assert plan["assignment"]["id"] == second["id"]
    rows = {r["assignment_id"]: r for r in plan["assignments"]}
    assert rows[first["id"]]["progress"] == "completed"
    assert rows[second["id"]]["progress"] == "not_started"


def test_rounds_continue_and_new_round(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """续做幂等；全部结束后再开练 → 新轮次独立记录；首轮成绩不被改写。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "轮次学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    # 重复开练 → 同一轮次（幂等续做）
    first_start = _start(client, student["headers"], code, assignment["id"])
    assert first_start["round_no"] == 1
    again = _start(client, student["headers"], code, assignment["id"])
    assert again["session_id"] == first_start["session_id"]
    assert again["round_no"] == 1

    # 答一半 → 续做仍是同一轮（至多一个未结束轮次）
    _answer(client, student["headers"], first_start["session_id"], 0, "apple")
    third = _start(client, student["headers"], code, assignment["id"])
    assert third["session_id"] == first_start["session_id"]
    _finish_round(client, student["headers"], first_start["session_id"], correct=True)

    # 任务完成（锁定首轮判定）后再开练：缺省/continue 不新建轮次（422）
    plan = _today(client, student["headers"], code)
    rows = {r["assignment_id"]: r for r in plan["assignments"]}
    assert rows[assignment["id"]]["progress"] == "completed"
    assert rows[assignment["id"]]["round_count"] == 1
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions",
        json={"assignment_id": assignment["id"], "round": "continue"},
        headers=student["headers"],
    )
    assert resp.status_code == 422, resp.text
    assert len(_rounds_of(db, assignment["id"])) == 1

    # 显式 round="new"（「再练一轮」）才开新复习轮 round_no=2
    second_round = _start(
        client, student["headers"], code, assignment["id"], round_="new"
    )
    assert second_round["session_id"] != first_start["session_id"]
    assert second_round["round_no"] == 2

    # 复习轮全答错 → 任务成绩仍是首轮（2/2 对），round_count=2
    _finish_round(client, student["headers"], second_round["session_id"], correct=False)
    results = _results(client, headers, code, assignment["id"])
    (row,) = [
        r for r in results["students"] if r["student_id"] == student["student"]["id"]
    ]
    assert row["status"] == "completed"
    assert row["correct_first_count"] == 2
    assert row["round_count"] == 2
    assert [r["round_no"] for r in row["rounds"]] == [1, 2]
    assert row["rounds"][0]["correct_first_count"] == 2
    assert row["rounds"][1]["correct_first_count"] == 0


def test_first_round_locked_word_stats_and_wrong_words(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """逐词错误分布锁定首轮首答；复习轮判错的词进入错词本（跨轮聚合）。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "锁分学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    round1 = _start(client, student["headers"], code, assignment["id"])["session_id"]
    _answer(client, student["headers"], round1, 0, "apple")  # 对
    _answer(client, student["headers"], round1, 1, "bananas")  # 错（复数不放宽）

    results = _results(client, headers, code, assignment["id"])
    banana = next(w for w in results["words"] if w["headword"] == "banana")
    assert banana["error_count"] == 1

    # 复习轮把 banana 答对、apple 答错 → 逐词统计仍是首轮口径
    round2 = _start(client, student["headers"], code, assignment["id"], round_="new")
    assert round2["round_no"] == 2
    _answer(client, student["headers"], round2["session_id"], 0, "zzz")  # apple 错
    _answer(client, student["headers"], round2["session_id"], 1, "banana")  # 对
    results = _results(client, headers, code, assignment["id"])
    apple = next(w for w in results["words"] if w["headword"] == "apple")
    banana = next(w for w in results["words"] if w["headword"] == "banana")
    assert apple["error_count"] == 0
    assert banana["error_count"] == 1

    # 错词本跨轮聚合：banana（轮1）+ apple（轮2）
    wrong = client.get(
        f"/api/v1/classes/{code}/vocabulary/wrong-words",
        headers=student["headers"],
    ).json()
    wrong_words = {i["headword"]: i["wrong_count"] for i in wrong["items"]}
    assert wrong_words == {"apple": 1, "banana": 1}


def test_due_passed_blocks_answers_and_marks_reason(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """截止后：新作答 422、历史可见、未结束轮标记 due_passed、列表显示逾期。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "截止学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    vocab_session_id = _start(client, student["headers"], code, assignment["id"])[
        "session_id"
    ]
    _answer(client, student["headers"], vocab_session_id, 0, "apple")

    # 直接把 due 改到过去（API 层不允许发布时设过去的 due）
    assignment_row = db.get(VocabularyAssignment, uuid.UUID(assignment["id"]))
    assert assignment_row is not None
    assignment_row.due_at = datetime.now(UTC) - timedelta(minutes=1)
    db.add(assignment_row)
    db.commit()

    # 新作答 → 422
    _answer(client, student["headers"], vocab_session_id, 1, "banana", expect=422)
    # today：聚焦轮标记 due_passed；任务行逾期且进度仍是 in_progress
    plan = _today(client, student["headers"], code)
    assert plan["session_closed_reason"] == "due_passed"
    assert plan["session_status"] == "in_progress"
    (row,) = [r for r in plan["assignments"] if r["assignment_id"] == assignment["id"]]
    assert row["overdue"] is True
    assert row["progress"] == "in_progress"
    # 历史可见：已答的词仍展示首答结果
    answered = [i for i in plan["items"] if i["answered"]]
    assert len(answered) == 1
    assert answered[0]["headword"] == "apple"

    # 截止后开练（再练一轮）也被拒
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions",
        json={"assignment_id": assignment["id"], "round": "new"},
        headers=student["headers"],
    )
    assert resp.status_code == 422


def test_archive_keeps_history_and_other_tasks(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """手动归档：该任务停止作答并标记 archived；其他任务不受影响；历史可见。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "归档学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    first = _publish(client, headers, code, word_ids, title="将被归档")
    second = _publish(client, headers, code, word_ids, title="继续有效")

    session_id = _start(client, student["headers"], code, first["id"])["session_id"]
    _answer(client, student["headers"], session_id, 0, "apple")

    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{first['id']}/archive",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # 归档任务：新作答 422
    _answer(client, student["headers"], session_id, 1, "banana", expect=422)
    # 聚焦切到仍发布的第二期（first 已不在聚焦池）
    plan = _today(client, student["headers"], code)
    assert plan["assignment"]["id"] == second["id"]
    rows = {r["assignment_id"]: r for r in plan["assignments"]}
    assert rows[first["id"]]["progress"] == "in_progress"
    assert rows[second["id"]]["progress"] == "not_started"

    # 归档任务的历史成绩教师仍可读
    results = _results(client, headers, code, first["id"])
    (row,) = [
        r for r in results["students"] if r["student_id"] == student["student"]["id"]
    ]
    assert row["answered_count"] == 1

    # 归档不能再开新轮（再练一轮 → 422）
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions",
        json={"assignment_id": first["id"], "round": "new"},
        headers=student["headers"],
    )
    assert resp.status_code == 422


def test_round_param_validation_and_cross_student(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """round 非法值 422；他学生会话 404（不泄露存在性）。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student_a = make_student(db, client, code, "学生A")
    student_b = make_student(db, client, code, "学生B")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions",
        json={"assignment_id": assignment["id"], "round": "bogus"},
        headers=student_a["headers"],
    )
    assert resp.status_code == 422

    session_a = _start(client, student_a["headers"], code, assignment["id"])[
        "session_id"
    ]
    # 学生 B 拿 A 的会话作答 → 404
    _answer(client, student_b["headers"], session_a, 0, "apple", expect=404)


def test_legacy_session_defaults_to_round1(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """存量会话（迁移前）round_no=1：教师统计正常、可续做。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "存量学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    # 模拟存量行：不指定 round_no（依赖 server_default=1）
    legacy = VocabularySession(
        classroom_id=uuid.UUID(classroom["id"]),
        student_id=student["student"]["id"],
        assignment_id=uuid.UUID(assignment["id"]),
        mode="practice",
    )
    db.add(legacy)
    db.commit()
    db.refresh(legacy)
    assert legacy.round_no == 1

    # 续做返回同一轮（round_no=1）
    resumed = _start(client, student["headers"], code, assignment["id"])
    assert resumed["session_id"] == str(legacy.id)
    assert resumed["round_no"] == 1

    # 教师统计可见（作答后 in_progress）
    _answer(client, student["headers"], str(legacy.id), 0, "apple")
    results = _results(client, headers, code, assignment["id"])
    (row,) = [
        r for r in results["students"] if r["student_id"] == student["student"]["id"]
    ]
    assert row["status"] == "in_progress"
    assert row["round_count"] == 1


def test_today_by_assignment_id_and_cross_class(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """today?assignment_id 返回指定任务聚焦轮；他班任务/无效 id → 404。"""
    teacher_a, headers_a = _login_teacher(db, client)
    classroom_a = _create_classroom(client, headers_a)
    student = make_student(db, client, classroom_a["code"], "切换学生")
    teacher_b, headers_b = _login_teacher(db, client)
    classroom_b = _create_classroom(client, headers_b)
    make_student(db, client, classroom_b["code"], "别班学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    mine = _publish(client, headers_a, classroom_a["code"], word_ids)
    theirs = _publish(client, headers_b, classroom_b["code"], word_ids)

    # 指定本班任务 → 返回该任务
    plan = client.get(
        f"/api/v1/classes/{classroom_a['code']}/vocabulary/today",
        params={"assignment_id": mine["id"]},
        headers=student["headers"],
    )
    assert plan.status_code == 200, plan.text
    assert plan.json()["assignment"]["id"] == mine["id"]

    # 他班任务 / 无效 id → 404（不静默回落聚焦任务）
    for bad in (theirs["id"], str(uuid.uuid4())):
        resp = client.get(
            f"/api/v1/classes/{classroom_a['code']}/vocabulary/today",
            params={"assignment_id": bad},
            headers=student["headers"],
        )
        assert resp.status_code == 404, resp.text


def test_concurrent_start_single_unfinished_round(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """并发开练：唯一索引兜底，同任务至多一个未结束轮次。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "并发学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    results: list[dict] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            with TestClient(client.app) as thread_client:
                results.append(
                    _start(thread_client, student["headers"], code, assignment["id"])
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors

    session_ids = {r["session_id"] for r in results}
    assert len(session_ids) == 1
    assert all(r["round_no"] == 1 for r in results)

    sessions = db.exec(
        select(VocabularySession).where(
            col(VocabularySession.assignment_id) == uuid.UUID(assignment["id"])
        )
    ).all()
    assert len(sessions) == 1


def test_continue_never_creates_rounds_and_concurrent_new(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """全结后：continue/缺省绝不新建轮次（422）；并发 round="new" 只产生一轮。"""
    import threading

    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "续做学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    # 完成第一轮
    round1 = _start(client, student["headers"], code, assignment["id"])
    _finish_round(client, student["headers"], round1["session_id"], correct=True)
    assert len(_rounds_of(db, assignment["id"])) == 1

    # continue / 缺省多次请求 → 全部 422，轮次数不变
    for body in (
        {"assignment_id": assignment["id"], "round": "continue"},
        {"assignment_id": assignment["id"]},
    ):
        for _ in range(2):
            resp = client.post(
                f"/api/v1/classes/{code}/vocabulary/sessions",
                json=body,
                headers=student["headers"],
            )
            assert resp.status_code == 422, resp.text
    assert len(_rounds_of(db, assignment["id"])) == 1

    # 并发 round="new" ×4 → 只产生一个第二轮
    results: list[dict] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            with TestClient(client.app) as thread_client:
                results.append(
                    _start(
                        thread_client,
                        student["headers"],
                        code,
                        assignment["id"],
                        round_="new",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    round_ids = {r["session_id"] for r in results}
    assert len(round_ids) == 1
    assert all(r["round_no"] == 2 for r in results)
    rounds = _rounds_of(db, assignment["id"])
    assert len(rounds) == 2

    # 第二轮完成后 continue 仍 422（不悄悄出现第三轮）
    _finish_round(client, student["headers"], results[0]["session_id"], correct=False)
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions",
        json={"assignment_id": assignment["id"], "round": "continue"},
        headers=student["headers"],
    )
    assert resp.status_code == 422, resp.text
    assert len(_rounds_of(db, assignment["id"])) == 2


def test_closed_reason_for_all_session_states(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """关闭原因是任务级：未开始/进行中/已完成三种状态统一计算。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "三态学生")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    # 进行中：任务开放 → None
    session_id = _start(client, student["headers"], code, assignment["id"])[
        "session_id"
    ]
    _answer(client, student["headers"], session_id, 0, "apple")
    plan = _today(client, student["headers"], code)
    assert plan["session_closed_reason"] is None

    # 已完成：完成任务后 due 未过 → 仍 None（可再练一轮）
    _finish_round(client, student["headers"], session_id, correct=True)
    plan = _today(client, student["headers"], code)
    assert plan["session_closed_reason"] is None
    assert plan["session_status"] == "submitted"

    # 已完成 + 截止已过 → due_passed（此前只对 in_progress 计算会漏）
    assignment_row = db.get(VocabularyAssignment, uuid.UUID(assignment["id"]))
    assert assignment_row is not None
    assignment_row.due_at = datetime.now(UTC) - timedelta(minutes=1)
    db.add(assignment_row)
    db.commit()
    plan = _today(client, student["headers"], code)
    assert plan["session_closed_reason"] == "due_passed"

    # 已完成 + 已归档 → archived（归档任务退出聚焦池，显式指定回看）
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}/archive",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    plan = _today(
        client,
        student["headers"],
        code,
        assignment_id=assignment["id"],
    )
    assert plan["session_closed_reason"] == "archived"
    assert plan["session_status"] == "submitted"


def test_view_specific_round_readonly(
    db: Session, client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """today?round_no 回看指定轮（归属校验）；他学生轮次 404。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "回看学生")
    other = make_student(db, client, code, "同学乙")
    book = _make_public_book(client, superuser_token_headers, WORDS_2)
    word_ids = [w["id"] for w in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    # 轮 1：apple 对、banana 错
    round1 = _start(client, student["headers"], code, assignment["id"])["session_id"]
    _answer(client, student["headers"], round1, 0, "apple")
    _answer(client, student["headers"], round1, 1, "bananas")
    # 轮 2：全对
    round2 = _start(client, student["headers"], code, assignment["id"], round_="new")[
        "session_id"
    ]
    _finish_round(client, student["headers"], round2, correct=True)

    def _today_round(round_no: str, headers_: dict[str, str]) -> Any:
        resp = client.get(
            f"/api/v1/classes/{code}/vocabulary/today",
            params={"assignment_id": assignment["id"], "round_no": round_no},
            headers=headers_,
        )
        return resp

    # 回看轮 1：展示第一轮首答口径（banana 错已揭示拼写），轮次列表 2 行
    resp = _today_round("1", student["headers"])
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["session_round"] == 1
    # 展示轮 ≠ 当前可练轮：回看历史轮时 current_round 仍是最新轮（前端只读判定依据）
    assert plan["current_round"] == 2
    assert plan["session_status"] == "submitted"
    assert plan["answered_count"] == 2
    assert plan["correct_first_count"] == 1
    banana = next(i for i in plan["items"] if i["headword"] == "banana")
    assert banana["is_correct"] is False
    assert [(r["round_no"], r["correct_first_count"]) for r in plan["rounds"]] == [
        (1, 1),
        (2, 2),
    ]

    # 缺省（无 round_no）= 未结束轮优先，否则最新轮 → 轮 2；此时展示轮=可练轮
    plan_default = _today(client, student["headers"], code)
    assert plan_default["session_round"] == 2
    assert plan_default["current_round"] == 2

    # 不存在的轮次 → 404
    assert _today_round("99", student["headers"]).status_code == 404

    # 他学生的轮次（同学乙的名单内有任务但没有轮次）→ 404
    assert _today_round("1", other["headers"]).status_code == 404
    assert _today_round("2", other["headers"]).status_code == 404
