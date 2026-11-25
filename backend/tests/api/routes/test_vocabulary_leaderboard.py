"""班内词汇学习榜（#517）API 测试：设置默认口径 / 参与隐私 / 周界计分 / 排名 / 权限矩阵。

冻结口径（见 docs/module-notes.md「背单词模块」榜单小节）：
- 默认仅教师可见、匿名编号；无库行由服务层返回默认值，不写种子；
- 未参加学生 200 空榜，看不到 entries 与人数；不可见时学生 403
  ``leaderboard_unavailable``，教师设置页仍 200 预览；
- 计分 = 本课堂最早首答正确 ∩ 本周 review_fsrs 首答正确，按词去重；
  首答错误不计、首答对但无复习不计、重复词只计一次；
- 同分并列（1,1,3）；前 10 名按 rank <= 10 返回；匿名只下发 alias_no；
- 404 先于 403：未入班/跨班 404，非本班教师 403，跨校不泄露存在性。
"""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete

from app import crud
from app.core import security
from app.core.config import settings
from app.models import (
    MODULE_VOCABULARY,
    Tenant,
    TenantModule,
    User,
    UserCreate,
    VocabularyAnswer,
    VocabularyLeaderboardParticipant,
    VocabularyLeaderboardSetting,
    VocabularySession,
    VocabularyWord,
)
from app.services import vocabulary_leaderboard as lb_service
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

BASE = "/api/v1/classes/{code}/vocabulary/leaderboard"

# 测试库为会话级清理（用例间不自动清表）；本模块直接插入的作答/词/榜单行
# 由下面的 autouse 夹具在用例结束后定向删除，避免残留 kinds 污染后续用例。
_TRACKED: dict[str, list] = {"words": [], "sessions": [], "classroom_ids": []}


@pytest.fixture(autouse=True)
def _cleanup_direct_rows(db: Session) -> Generator[None]:
    _TRACKED["words"].clear()
    _TRACKED["sessions"].clear()
    _TRACKED["classroom_ids"].clear()
    yield
    session_ids = [s.id for s in _TRACKED["sessions"]]
    if session_ids:
        db.exec(
            delete(VocabularyAnswer).where(
                col(VocabularyAnswer.session_id).in_(session_ids)  # type: ignore[operator]
            )
        )
        db.exec(
            delete(VocabularySession).where(
                col(VocabularySession.id).in_(session_ids)  # type: ignore[operator]
            )
        )
    word_ids = [w.id for w in _TRACKED["words"]]
    if word_ids:
        db.exec(
            delete(VocabularyWord).where(
                col(VocabularyWord.id).in_(word_ids)  # type: ignore[operator]
            )
        )
    if _TRACKED["classroom_ids"]:
        db.exec(
            delete(VocabularyLeaderboardParticipant).where(
                col(VocabularyLeaderboardParticipant.classroom_id).in_(  # type: ignore[operator]
                    _TRACKED["classroom_ids"]
                )
            )
        )
        db.exec(
            delete(VocabularyLeaderboardSetting).where(
                col(VocabularyLeaderboardSetting.classroom_id).in_(  # type: ignore[operator]
                    _TRACKED["classroom_ids"]
                )
            )
        )
    db.commit()


# ── 基础夹具辅助 ──────────────────────────────────────────────────────


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
    body = resp.json()
    _TRACKED["classroom_ids"].append(uuid.UUID(body["id"]))
    return body


def _add_word(db: Session, headword: str, meaning_zh: str) -> VocabularyWord:
    word = VocabularyWord(
        headword=headword, meaning_zh=meaning_zh, review_status="approved"
    )
    db.add(word)
    db.commit()
    db.refresh(word)
    _TRACKED["words"].append(word)
    return word


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.PRACTICE_TZ)


def _add_session(
    db: Session,
    classroom_id: str,
    student_id: str,
    kind: str = "task",
    started_at: datetime | None = None,
) -> VocabularySession:
    session_row = VocabularySession(
        classroom_id=uuid.UUID(classroom_id),
        student_id=uuid.UUID(student_id),
        kind=kind,
        status="submitted",
        started_at=started_at,
        submitted_at=started_at,
    )
    db.add(session_row)
    db.commit()
    db.refresh(session_row)
    _TRACKED["sessions"].append(session_row)
    return session_row


def _add_answer(
    db: Session,
    session_row: VocabularySession,
    word: VocabularyWord,
    *,
    attempt_no: int = 1,
    is_correct: bool = True,
    answered_at: datetime | None = None,
    item_index: int = 0,
) -> VocabularyAnswer:
    answer = VocabularyAnswer(
        session_id=session_row.id,
        item_index=item_index,
        attempt_no=attempt_no,
        prompt_type="meaning",
        answer_raw=word.headword,
        answer_normalized=word.headword,
        is_correct=is_correct,
        word_id=word.id,
        headword=word.headword,
        meaning_zh=word.meaning_zh,
        answered_at=answered_at,
    )
    db.add(answer)
    db.commit()
    return answer


def _enroll_word(
    db: Session,
    classroom: dict,
    student: dict,
    word: VocabularyWord,
    *,
    first_correct: bool = True,
    review_correct: bool = True,
    first_at: datetime | None = None,
    review_at: datetime | None = None,
) -> None:
    """构造一条掌握证据：任务轮首答 + （可选）review_fsrs 轮首答。"""
    first_at = first_at or datetime.now(UTC) - timedelta(days=3)
    review_at = review_at or datetime.now(UTC) - timedelta(days=1)
    task = _add_session(
        db, classroom["id"], student["student"]["id"], kind="task", started_at=first_at
    )
    _add_answer(db, task, word, is_correct=first_correct, answered_at=first_at)
    if review_correct:
        review = _add_session(
            db,
            classroom["id"],
            student["student"]["id"],
            kind="review_fsrs",
            started_at=review_at,
        )
        _add_answer(db, review, word, is_correct=True, answered_at=review_at)


def _open_settings(
    client: TestClient, headers: dict[str, str], code: str, **overrides: object
) -> dict:
    body: dict[str, object] = {
        "enabled": True,
        "audience": "students",
        "anonymous": True,
        **overrides,
    }
    resp = client.put(f"{BASE.format(code=code)}/settings", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _join(
    client: TestClient, headers: dict[str, str], code: str, joined: bool = True
) -> tuple[int, dict]:
    resp = client.put(
        f"{BASE.format(code=code)}/participation",
        json={"joined": joined},
        headers=headers,
    )
    return resp.status_code, resp.json()


def _board(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    week_start: str | None = None,
) -> tuple[int, dict]:
    params = {"week_start": week_start} if week_start else None
    resp = client.get(f"{BASE.format(code=code)}", params=params, headers=headers)
    return resp.status_code, resp.json()


# ── 设置默认口径 ──────────────────────────────────────────────────────


def test_default_settings_when_no_row(client: TestClient, db: Session) -> None:
    """无库行返回服务层默认值：开启 / 仅教师 / 匿名 / top_n=10。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)

    resp = client.get(
        f"{BASE.format(code=classroom['code'])}/settings", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "enabled": True,
        "audience": "teachers",
        "anonymous": True,
        "top_n": 10,
    }


def test_settings_update_roundtrip(client: TestClient, db: Session) -> None:
    """教师更新设置后 GET/PUT 回执一致。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)

    resp = client.put(
        f"{BASE.format(code=classroom['code'])}/settings",
        json={"enabled": False, "audience": "students", "anonymous": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "enabled": False,
        "audience": "students",
        "anonymous": False,
        "top_n": 10,
    }

    resp = client.get(
        f"{BASE.format(code=classroom['code'])}/settings", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    assert resp.json()["anonymous"] is False


# ── 可见性与隐私 ─────────────────────────────────────────────────────


def test_student_blocked_by_default_teacher_only(
    client: TestClient, db: Session
) -> None:
    """默认 audience=teachers：学生看榜 403，也不允许加入。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])

    status, body = _board(client, student["headers"], classroom["code"])
    assert status == 403, body
    assert body["detail"] == "leaderboard_unavailable"

    status, body = _join(client, student["headers"], classroom["code"], joined=True)
    assert status == 403, body
    assert body["detail"] == "leaderboard_unavailable"


def test_disabled_board_still_previewable_for_teacher(
    client: TestClient, db: Session
) -> None:
    """整班关闭：教师设置页仍 200 预览；学生 403。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])
    _open_settings(client, headers, classroom["code"], enabled=False)

    status, body = _board(client, headers, classroom["code"])
    assert status == 200, body
    assert body["settings"]["enabled"] is False

    status, body = _board(client, student["headers"], classroom["code"])
    assert status == 403, body
    assert body["detail"] == "leaderboard_unavailable"


def test_unjoined_student_sees_empty_board_without_count(
    client: TestClient, db: Session
) -> None:
    """放开学生可见后，未参加学生 200 空榜：看不到 entries 与人数。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])
    _open_settings(client, headers, classroom["code"])

    status, body = _board(client, student["headers"], classroom["code"])
    assert status == 200, body
    assert body["entries"] == []
    assert body["my_entry"] is None
    assert body["my_rank"] is None
    assert body["my_score"] == 0
    assert body["participant_count"] is None


def test_join_assigns_stable_alias_and_anonymous_entry(
    client: TestClient, db: Session
) -> None:
    """加入分配班内编号；匿名条目只带 alias_no，不下发姓名。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"], name="学生甲")
    _open_settings(client, headers, classroom["code"])

    status, body = _join(client, student["headers"], classroom["code"])
    assert status == 200, body
    assert body["joined"] is True
    assert body["alias_no"] == 1

    status, body = _board(client, student["headers"], classroom["code"])
    assert status == 200, body
    assert body["participant_count"] is None  # 学生视角看不到人数
    assert body["my_entry"] is None  # 零分不进 my_entry
    assert body["my_score"] == 0

    # 教师视角可见人数，匿名条目无姓名
    status, body = _board(client, headers, classroom["code"])
    assert status == 200
    assert body["participant_count"] == 1


def test_alias_reused_on_rejoin(client: TestClient, db: Session) -> None:
    """退出后重新加入复用原 alias_no。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])
    _open_settings(client, headers, classroom["code"])

    status, body = _join(client, student["headers"], classroom["code"], joined=True)
    assert status == 200 and body["alias_no"] == 1

    status, body = _join(client, student["headers"], classroom["code"], joined=False)
    assert status == 200 and body == {"joined": False, "alias_no": None}

    status, body = _join(client, student["headers"], classroom["code"], joined=True)
    assert status == 200 and body["alias_no"] == 1


# ── 计分口径 ──────────────────────────────────────────────────────────


def _mastered_this_week(
    db: Session, classroom: dict, student: dict, headword: str
) -> VocabularyWord:
    word = _add_word(db, headword, f"释义-{headword}")
    _enroll_word(db, classroom, student, word)
    return word


def test_score_requires_first_correct_and_fsrs_review(
    client: TestClient, db: Session
) -> None:
    """首答错误不计；首答对但无 FSRS 复习不计；两者齐备才计 1 词。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])
    _open_settings(client, headers, classroom["code"])
    _join(client, student["headers"], classroom["code"])

    # 达标词：首答对 + 本周 review_fsrs 首答对
    _mastered_this_week(db, classroom, student, "good01")
    # 首答错误：即使 FSRS 复习答对也不计
    wrong_first = _add_word(db, "wrong01", "释义-wrong01")
    _enroll_word(
        db, classroom, student, wrong_first, first_correct=False, review_correct=True
    )
    # 首答对但没有 FSRS 复习轮：不计
    no_review = _add_word(db, "norev01", "释义-norev01")
    _enroll_word(
        db, classroom, student, no_review, first_correct=True, review_correct=False
    )

    status, body = _board(client, headers, classroom["code"])
    assert status == 200, body
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["score"] == 1
    assert entry["alias_no"] == 1

    # 学生视角：本人成绩 1，且 my_entry 随本人返回
    status, body = _board(client, student["headers"], classroom["code"])
    assert status == 200, body
    assert body["my_score"] == 1
    assert body["my_entry"]["score"] == 1


def test_duplicate_word_counted_once(client: TestClient, db: Session) -> None:
    """同一词本周多条 review_fsrs 答对记录只计 1 次。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])
    _open_settings(client, headers, classroom["code"])
    _join(client, student["headers"], classroom["code"])

    word = _add_word(db, "dup01", "释义-dup01")
    now = datetime.now(UTC)
    task = _add_session(
        db,
        classroom["id"],
        student["student"]["id"],
        kind="task",
        started_at=now - timedelta(days=3),
    )
    _add_answer(db, task, word, is_correct=True, answered_at=now - timedelta(days=3))
    # 两条 review_fsrs 轮次、同词首答对
    for idx in range(2):
        review = _add_session(
            db,
            classroom["id"],
            student["student"]["id"],
            kind="review_fsrs",
            started_at=now - timedelta(days=1),
        )
        _add_answer(
            db,
            review,
            word,
            is_correct=True,
            answered_at=now - timedelta(days=1),
            item_index=idx,
        )

    status, body = _board(client, headers, classroom["code"])
    assert status == 200
    assert body["entries"][0]["score"] == 1


def test_tie_competition_ranking(client: TestClient, db: Session) -> None:
    """同分并列（1,1,3）；零分学生不进 entries。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    _open_settings(client, headers, classroom["code"])

    alice = make_student(db, client, classroom["code"], name="学生甲")
    bob = make_student(db, client, classroom["code"], name="学生乙")
    carol = make_student(db, client, classroom["code"], name="学生丙")
    for stu in (alice, bob, carol):
        _join(client, stu["headers"], classroom["code"])

    # 甲、乙各 2 词并列第 1；丙 1 词第 3
    for i in range(2):
        _mastered_this_week(db, classroom, alice, f"a{i:02d}")
        _mastered_this_week(db, classroom, bob, f"b{i:02d}")
    _mastered_this_week(db, classroom, carol, "c01")

    status, body = _board(client, headers, classroom["code"])
    assert status == 200
    entries = sorted(body["entries"], key=lambda e: (e["rank"], e["alias_no"]))
    assert [(e["rank"], e["score"]) for e in entries] == [(1, 2), (1, 2), (3, 1)]
    assert body["participant_count"] == 3


def test_anonymous_off_shows_display_name(client: TestClient, db: Session) -> None:
    """anonymous=false 时条目下发 display_name；anonymous=true 为 null。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"], name="实名学生")
    _open_settings(client, headers, classroom["code"], anonymous=True)
    _join(client, student["headers"], classroom["code"])
    _mastered_this_week(db, classroom, student, "name01")

    status, body = _board(client, headers, classroom["code"])
    assert status == 200
    assert body["entries"][0]["display_name"] is None

    _open_settings(client, headers, classroom["code"], anonymous=False)
    status, body = _board(client, headers, classroom["code"])
    assert status == 200
    entry = body["entries"][0]
    assert entry["display_name"] == "实名学生"
    assert "student_id" not in entry
    assert "user_id" not in entry


def test_zero_score_participant_not_listed(client: TestClient, db: Session) -> None:
    """参与表存在但本周零分：不进 entries，my_rank=null、my_score=0。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])
    _open_settings(client, headers, classroom["code"])
    _join(client, student["headers"], classroom["code"])

    status, body = _board(client, student["headers"], classroom["code"])
    assert status == 200
    assert body["entries"] == []
    assert body["my_entry"] is None
    assert body["my_rank"] is None
    assert body["my_score"] == 0


# ── 周界（PRACTICE_TZ）────────────────────────────────────────────────


def test_week_boundary_by_practice_tz(client: TestClient, db: Session) -> None:
    """周界按 PRACTICE_TZ 周一 00:00：周日深夜的复习归上一周，周一凌晨归本周。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])
    _open_settings(client, headers, classroom["code"])
    _join(client, student["headers"], classroom["code"])

    monday = lb_service.current_week_monday()
    tz = _tz()
    sunday_late = datetime.combine(monday - timedelta(days=1), time(23, 30), tzinfo=tz)
    monday_early = datetime.combine(monday, time(0, 10), tzinfo=tz)
    earlier = datetime.now(UTC) - timedelta(days=10)

    prior = _add_word(db, "prior01", "释义-prior01")
    current = _add_word(db, "cur01", "释义-cur01")
    for word, review_at in ((prior, sunday_late), (current, monday_early)):
        task = _add_session(
            db,
            classroom["id"],
            student["student"]["id"],
            kind="task",
            started_at=earlier,
        )
        _add_answer(db, task, word, is_correct=True, answered_at=earlier)
        review = _add_session(
            db,
            classroom["id"],
            student["student"]["id"],
            kind="review_fsrs",
            started_at=review_at,
        )
        _add_answer(
            db, review, word, is_correct=True, answered_at=review_at.astimezone(UTC)
        )

    # 本周：只有周一凌晨之后的词计入
    status, body = _board(client, headers, classroom["code"])
    assert status == 200
    assert body["entries"][0]["score"] == 1

    # 上一周：周日深夜的词计入（教师可查历史周）
    prior_monday = (monday - timedelta(days=7)).isoformat()
    status, body = _board(client, headers, classroom["code"], week_start=prior_monday)
    assert status == 200
    assert body["entries"][0]["score"] == 1


def test_week_start_must_be_monday_and_not_future(
    client: TestClient, db: Session
) -> None:
    """week_start 非周一 / 晚于本周一 → 422。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    monday = lb_service.current_week_monday()

    not_monday = (monday + timedelta(days=2)).isoformat()
    status, _ = _board(client, headers, classroom["code"], week_start=not_monday)
    assert status == 422

    future = (monday + timedelta(days=7)).isoformat()
    status, _ = _board(client, headers, classroom["code"], week_start=future)
    assert status == 422


def test_student_cannot_view_weeks_before_join(client: TestClient, db: Session) -> None:
    """学生不能查首次加入周之前的历史榜。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])
    _open_settings(client, headers, classroom["code"])
    _join(client, student["headers"], classroom["code"])

    prior_monday = (lb_service.current_week_monday() - timedelta(days=7)).isoformat()
    status, body = _board(
        client, student["headers"], classroom["code"], week_start=prior_monday
    )
    assert status == 403, body
    assert body["detail"] == "leaderboard_unavailable"


# ── 权限矩阵 ─────────────────────────────────────────────────────────


def test_non_member_teacher_forbidden(client: TestClient, db: Session) -> None:
    """非本班教师（含共管名单外）访问设置 → 403。"""
    teacher_a, headers_a = _login_teacher(db, client)
    classroom = _create_classroom(client, headers_a)

    _teacher_b, headers_b = _login_teacher(db, client)
    resp = client.get(
        f"{BASE.format(code=classroom['code'])}/settings", headers=headers_b
    )
    assert resp.status_code == 403, resp.text


def test_cross_class_student_not_found(client: TestClient, db: Session) -> None:
    """他班学生访问本班榜单 → 404（未入班不泄露课堂存在性之外的信息）。"""
    _teacher, headers = _login_teacher(db, client)
    room_a = _create_classroom(client, headers)
    room_b = _create_classroom(client, headers)
    other = make_student(db, client, room_b["code"])

    status, body = _board(client, other["headers"], room_a["code"])
    assert status == 404, body


def test_cross_tenant_teacher_forbidden(client: TestClient, db: Session) -> None:
    """跨校教师按权限不足拒绝，不泄露课堂归属细节。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)

    other = Tenant(slug=f"lb-{uuid.uuid4().hex[:8]}", name_zh="榜单乙校")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(TenantModule(tenant_id=other.id, module_key=MODULE_VOCABULARY, enabled=True))
    db.commit()
    outsider = User(
        email=f"lb-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="teacher",
        tenant_id=other.id,
    )
    db.add(outsider)
    db.commit()
    db.refresh(outsider)
    outsider_token = security.create_access_token(
        outsider.id,
        expires_delta=timedelta(minutes=10),
        role=outsider.role,
        password_hash=outsider.hashed_password,
        tenant_id=str(other.id),
    )
    outsider_headers = {"Authorization": f"Bearer {outsider_token}"}

    status, body = _board(client, outsider_headers, classroom["code"])
    assert status in (403, 404), body
