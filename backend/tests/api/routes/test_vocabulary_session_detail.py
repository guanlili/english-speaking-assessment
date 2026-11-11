"""答卷详情端点测试：学生侧练习/测验详情 + 教师侧答卷（reveal=True）。

这两个端点此前没有任何测试覆盖，导致 `vocabulary.student_plan` 的测验分支
（到时结算、倒计时、公布掩码）长期落在未覆盖行里。补这里是为了让拆分
`student_plan` 时的等价性有测试兜住，而不是靠人眼比对。

覆盖点：
- 练习详情：未答不揭示拼写，已答回填本人首答输入
- 测验详情：进行中给剩余秒数；触碰即结算到时答卷（不依赖学生在线）
- 答案/成绩未公布 → masked + 不揭示拼写与对错
- 教师答卷 reveal=True 不受公布规则约束，全量揭示
- 他人/不存在的会话一律 404，不区分报错
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import VocabularySession
from tests.api.routes.test_vocabulary_quiz import (
    _answer,
    _quiz_setup,
    _start_quiz,
    _submit_quiz,
)
from tests.api.routes.test_vocabulary_student import (
    _create_classroom,
    _login_teacher,
    _make_class_book,
    _start_self,
    _words,
)
from tests.utils.credential import make_student

VOCAB = "/api/v1/vocabulary"


def _detail(client: TestClient, headers: dict[str, str], code: str, session_id: str):
    return client.get(
        f"/api/v1/classes/{code}/vocabulary/student/sessions/{session_id}",
        headers=headers,
    )


def _answer_sheet(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    assignment_id: str,
    student_id: str,
    round_no: int | None = None,
):
    url = (
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment_id}"
        f"/students/{student_id}/answer-sheet"
    )
    params = {"round_no": round_no} if round_no is not None else None
    return client.get(url, headers=headers, params=params)


def test_practice_session_detail_masks_unanswered(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """练习详情：未答不揭示拼写，已答回填首答输入与尝试次数。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    code = classroom["code"]
    student = make_student(db, client, code)
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(3))
    session_id = _start_self(client, student["headers"], code, book["id"])["session_id"]

    detail = _detail(client, student["headers"], code, session_id).json()
    assert detail["is_quiz"] is False
    assert detail["total_count"] == 3
    assert detail["answered_count"] == 0
    assert detail["masked"] is False
    assert detail["answers_visible"] is True
    # 未作答一律不给拼写
    assert all(item["headword"] is None for item in detail["items"])
    assert all(item["answered"] is False for item in detail["items"])

    resp = _answer(client, student["headers"], session_id, 0, "w01")
    assert resp.status_code == 200, resp.text
    detail = _detail(client, student["headers"], code, session_id).json()
    first = detail["items"][0]
    assert first["answered"] is True
    # 题序可能被打乱，只断言「已答即揭示拼写」与回填本人首答输入
    assert first["headword"] is not None
    assert first["first_answer"] == "w01"
    assert first["attempt_count"] == 1
    assert detail["answered_count"] == 1
    # 未答不揭示拼写（其余题仍 blank）
    assert detail["items"][1]["headword"] is None


def test_quiz_session_detail_in_progress_gives_countdown(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """测验进行中：给截止时刻与剩余秒数；成绩未公布 → masked。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=15
    )
    code = classroom["code"]
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]

    detail = _detail(client, student["headers"], code, session_id).json()
    assert detail["is_quiz"] is True
    assert detail["status"] == "in_progress"
    assert detail["deadline"] is not None
    assert detail["remaining_seconds"] is not None
    assert 0 < detail["remaining_seconds"] <= 30 * 60
    # 未公布成绩 → 打码且首答数置 0
    assert detail["masked"] is True
    assert detail["score_visible"] is False
    assert detail["correct_first_count"] == 0


def test_quiz_session_detail_settles_timeout_on_touch(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """触碰答卷即结算到时（不依赖学生页面在线）：状态转 submitted/timeout。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=3
    )
    code = classroom["code"]
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]
    assert _answer(client, student["headers"], session_id, 0, "w01").status_code == 200

    # 把个人计时起点拨到过去（服务器口径不变，只模拟时间流逝）
    vocab_session = db.get(VocabularySession, session_id)
    assert vocab_session is not None
    vocab_session.quiz_started_at = datetime.now(UTC) - timedelta(minutes=40)
    db.add(vocab_session)
    db.commit()

    detail = _detail(client, student["headers"], code, session_id).json()
    assert detail["status"] == "submitted"
    assert detail["end_reason"] == "timeout"
    # 已结算：不再给剩余秒数
    assert detail["remaining_seconds"] is None


def test_quiz_answer_sheet_reveals_everything(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """教师查看答卷：不受公布规则约束，拼写与对错全量揭示。"""
    teacher_headers, student, classroom, assignment = _quiz_setup(
        client, superuser_token_headers, db, word_count=3
    )
    code = classroom["code"]
    resp = _start_quiz(client, student["headers"], code, assignment["id"])
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]
    assert _answer(client, student["headers"], session_id, 0, "w01").status_code == 200
    assert (
        _answer(client, student["headers"], session_id, 1, "bad-input").status_code
        == 200
    )
    _submit_quiz(client, student["headers"], session_id)

    sheet = _answer_sheet(
        client, teacher_headers, code, assignment["id"], student["student"]["id"]
    )
    assert sheet.status_code == 200, sheet.text
    body = sheet.json()
    assert body["is_quiz"] is True
    assert body["answers_visible"] is True
    assert body["score_visible"] is True
    assert body["masked"] is False
    answered = [item for item in body["items"] if item["answered"]]
    assert answered
    assert all(item["headword"] is not None for item in answered)
    assert any(item["is_correct"] is False for item in answered)
    assert body["correct_first_count"] >= 1


def test_session_detail_rejects_foreign_session(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """他人的/不存在的会话一律 404，不区分报错（不泄露是否存在）。"""
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    code = classroom["code"]
    owner = make_student(db, client, code)
    other = make_student(db, client, code)
    book = _make_class_book(client, teacher_headers, classroom["id"], _words(3))
    session_id = _start_self(client, owner["headers"], code, book["id"])["session_id"]

    assert _detail(client, other["headers"], code, session_id).status_code == 404
    assert (
        _detail(
            client, owner["headers"], code, "00000000-0000-0000-0000-000000000000"
        ).status_code
        == 404
    )
