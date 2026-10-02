"""背单词模块 P0：词库/发布快照/判分/幂等/权限/统计闭环测试。

口径（设计文档 §5 + §7 验收场景）：
- 判分确定性：NFKC + casefold + 去首尾空白；只认快照拼写与显式变体；
- 发布快照不可变：词库后续编辑不改变进行中任务与历史报告；
- 幂等键重放返回同一作答；练习重试按 attempt_no 递增，统计看首答；
- 目标名单固定：完成率分母 = 发布时名单，后入班学生不在名单内；
- 权限：401=登录失效，403=权限不足；班级数据仅本班教师可读。
"""

import csv
import io
import uuid

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.models import User, UserCreate
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"


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


def _csv(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _make_public_book(
    client: TestClient,
    admin_headers: dict[str, str],
    words: list[dict],
    title: str = "测试公共词库",
) -> dict:
    resp = client.post(
        f"{VOCAB}/books",
        json={"title": title, "scope": "public", "words": words},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


WORDS_3 = [
    {"headword": "apple", "part_of_speech": "n.", "meaning_zh": "苹果"},
    {"headword": "banana", "part_of_speech": "n.", "meaning_zh": "香蕉"},
    {
        "headword": "favourite",
        "part_of_speech": "adj.",
        "meaning_zh": "最喜欢的",
        "accepted_spellings": ["favorite"],
    },
]


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


def _today(client: TestClient, headers: dict[str, str], code: str) -> dict:
    resp = client.get(f"/api/v1/classes/{code}/vocabulary/today", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _start_session(client: TestClient, headers: dict[str, str], code: str) -> str:
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions", json={}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


def _answer(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    item_index: int,
    answer: str,
    key: str | None = None,
) -> dict:
    resp = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={
            "item_index": item_index,
            "prompt_type": "meaning",
            "answer": answer,
            **({"idempotency_key": key} if key else {}),
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── CSV 导入预览 ────────────────────────────────────────────────────


def test_import_preview_validation(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    """有效行/无效行/文件内重复分别报告；表头缺失 422。"""
    csv_bytes = _csv(
        [
            ["headword", "part_of_speech", "meaning_zh", "accepted_spellings"],
            ["dog", "n.", "狗", ""],
            ["", "n.", "空的", ""],
            ["cat", "n.", "猫", ""],
            ["dog", "n.", "狗", ""],
        ]
    )
    resp = client.post(
        f"{VOCAB}/books/import-preview",
        files={"file": ("words.csv", csv_bytes, "text/csv")},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert len(preview["rows"]) == 2
    assert preview["rows"][0]["word"]["headword"] == "dog"
    assert len(preview["invalid"]) == 1
    assert preview["invalid"][0]["line"] == 3
    assert len(preview["duplicates"]) == 1
    assert preview["duplicates"][0]["line"] == 5

    bad = _csv([["word", "band"], ["dog", "A2"]])
    assert (
        client.post(
            f"{VOCAB}/books/import-preview",
            files={"file": ("bad.csv", bad, "text/csv")},
            headers=superuser_token_headers,
        ).status_code
        == 422
    )


# ── 词库权限 ────────────────────────────────────────────────────────


def test_book_scope_permissions(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """教师不能建公共词库；能建自己班级的词库；别的教师看不见也改不了。"""
    teacher_a, headers_a = _login_teacher(db, client)
    _teacher_b, headers_b = _login_teacher(db, client)
    classroom = _create_classroom(client, headers_a)

    # 教师建公共词库 → 403
    assert (
        client.post(
            f"{VOCAB}/books",
            json={"title": "越权公共库", "scope": "public"},
            headers=headers_a,
        ).status_code
        == 403
    )
    # 管理员建公共词库 → 200
    public = _make_public_book(client, superuser_token_headers, WORDS_3)
    # 教师创建自己班级的词库
    resp = client.post(
        f"{VOCAB}/books",
        json={
            "title": "A 的班级词库",
            "scope": "classroom",
            "classroom_id": classroom["id"],
            "words": WORDS_3,
        },
        headers=headers_a,
    )
    assert resp.status_code == 200, resp.text
    book_a = resp.json()

    # B 的列表：见公共库，不见 A 的班级库
    listing = client.get(f"{VOCAB}/books", headers=headers_b).json()
    ids = {book["id"] for book in listing}
    assert public["id"] in ids
    assert book_a["id"] not in ids
    # B 直接访问/编辑 A 的班级库 → 403
    assert (
        client.get(f"{VOCAB}/books/{book_a['id']}", headers=headers_b).status_code
        == 403
    )
    assert (
        client.patch(
            f"{VOCAB}/books/{book_a['id']}", json={"title": "抢注"}, headers=headers_b
        ).status_code
        == 403
    )


# ── 发布与快照 ──────────────────────────────────────────────────────


def test_publish_validation_and_snapshot_immutability(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """发布校验（空课堂/未知题型）；词库后续编辑不改快照；重发归档旧任务。"""
    teacher, headers = _login_teacher(db, client)
    _other, other_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]

    book = _make_public_book(client, superuser_token_headers, WORDS_3)
    word_ids = [word["id"] for word in book["words"]]

    # 空课堂不能发布（目标名单为空）
    assert (
        client.post(
            f"/api/v1/classes/{code}/vocabulary/assignments",
            json={"word_ids": word_ids},
            headers=headers,
        ).status_code
        == 422
    )

    student = make_student(db, client, code, "学生甲")

    # 非本班教师发布 → 403
    assert (
        client.post(
            f"/api/v1/classes/{code}/vocabulary/assignments",
            json={"word_ids": word_ids},
            headers=other_headers,
        ).status_code
        == 403
    )
    # 未知出题方式 → 422
    assert (
        client.post(
            f"/api/v1/classes/{code}/vocabulary/assignments",
            json={"word_ids": word_ids, "prompt_types": ["oracle"]},
            headers=headers,
        ).status_code
        == 422
    )

    assignment = _publish(client, headers, code, word_ids, title="第一期")
    assert assignment["status"] == "published"
    assert assignment["word_count"] == 3
    assert assignment["version_no"] == 1

    # 修改词库里的词（管理员改公共词库词条）
    apple_id = word_ids[0]
    resp = client.patch(
        f"{VOCAB}/words/{apple_id}",
        json={"meaning_zh": "改过的释义"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text

    # 学生视图仍显示发布时的快照释义
    plan = _today(client, student["headers"], code)
    assert plan["assignment"]["id"] == assignment["id"]
    apple_item = next(i for i in plan["items"] if i["meaning_zh"] == "苹果")
    assert apple_item["headword"] is None  # 未作答不透露拼写

    # 教师重发新任务 → 旧任务归档
    second = _publish(client, headers, code, word_ids, title="第二期")
    assert second["version_no"] == 2
    assignments = client.get(
        f"/api/v1/classes/{code}/vocabulary/assignments", headers=headers
    ).json()
    statuses = {a["id"]: a["status"] for a in assignments}
    assert statuses[assignment["id"]] == "archived"
    assert statuses[second["id"]] == "published"


# ── 判分 / 幂等 / 重试 ──────────────────────────────────────────────


def test_scoring_normalization_and_idempotency(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """NFKC/大小写/空白折叠判对；变体拼写判对；幂等重放同结果；重试递增。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "判分学生")

    book = _make_public_book(client, superuser_token_headers, WORDS_3)
    word_ids = [word["id"] for word in book["words"]]
    _publish(client, headers, code, word_ids)

    session_id = _start_session(client, student["headers"], code)

    # 全角字母 + 首尾空白 + 大小写 → 判对
    result = _answer(client, student["headers"], session_id, 0, "  ＡＰｐLe ")
    assert result["is_correct"] is True
    assert result["correct_spelling"] == "apple"
    assert result["attempt_no"] == 1

    # 错拼（复数不放宽）→ 判错并揭示正确拼写
    wrong = _answer(client, student["headers"], session_id, 1, "bananas")
    assert wrong["is_correct"] is False
    assert wrong["correct_spelling"] == "banana"

    # 显式配置的变体拼写 → 判对
    variant = _answer(client, student["headers"], session_id, 2, "Favorite")
    assert variant["is_correct"] is True

    # 幂等键重放：返回同一作答，不新增尝试
    key = f"retry-{random_lower_string()}"
    first = _answer(client, student["headers"], session_id, 1, "banana", key)
    assert first["attempt_no"] == 2  # 该题第二次提交（第一次是错拼）
    replay = _answer(client, student["headers"], session_id, 1, "banana", key)
    assert replay["attempt_no"] == 2
    assert replay == first

    # 全部题至少一答 → 会话完成
    plan = _today(client, student["headers"], code)
    assert plan["session_status"] == "submitted"
    assert plan["answered_count"] == 3
    # 首答口径：banana 首答是 bananAs 错拼 → 正确 2
    assert plan["correct_first_count"] == 2


# ── 目标名单 / 完成统计 / 错词本 ────────────────────────────────────


def test_targets_results_and_wrong_words(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """名单固定（后入班不在分母）；完成统计三态；逐词误拼；错词本。"""
    teacher, headers = _login_teacher(db, client)
    _other, other_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]

    student_a = make_student(db, client, code, "完成者")
    student_b = make_student(db, client, code, "进行者")
    make_student(db, client, code, "未开始者")

    book = _make_public_book(client, superuser_token_headers, WORDS_3[:2])
    word_ids = [word["id"] for word in book["words"]]
    assignment = _publish(client, headers, code, word_ids)

    # A 全对完成
    session_a = _start_session(client, student_a["headers"], code)
    _answer(client, student_a["headers"], session_a, 0, "apple")
    _answer(client, student_a["headers"], session_a, 1, "banana")
    # B 只答一题且拼错
    session_b = _start_session(client, student_b["headers"], code)
    _answer(client, student_b["headers"], session_b, 0, "aple")

    # 发布后入班的学生不在名单内：看不到任务、不能开会话
    late = make_student(db, client, code, "迟到者")
    late_plan = _today(client, late["headers"], code)
    assert late_plan["assignment"] is None
    assert (
        client.post(
            f"/api/v1/classes/{code}/vocabulary/sessions",
            json={"assignment_id": assignment["id"]},
            headers=late["headers"],
        ).status_code
        == 403
    )

    # 教师结果面板：三态 + 逐词统计
    results = client.get(
        f"/api/v1/classes/{code}/vocabulary/results", headers=headers
    ).json()
    assert results["target_count"] == 3  # 分母 = 发布时名单（迟到者不计）
    assert results["completed_count"] == 1
    assert results["in_progress_count"] == 1
    assert results["not_started_count"] == 1
    by_name = {row["display_name"]: row for row in results["students"]}
    assert by_name["完成者"]["status"] == "completed"
    assert by_name["完成者"]["correct_first_count"] == 2
    assert by_name["进行者"]["status"] == "in_progress"
    apple_stat = next(w for w in results["words"] if w["headword"] == "apple")
    assert apple_stat["error_count"] == 1
    assert apple_stat["misspellings"][0]["answer"] == "aple"

    # 非本班教师读结果 → 403
    assert (
        client.get(
            f"/api/v1/classes/{code}/vocabulary/results", headers=other_headers
        ).status_code
        == 403
    )

    # B 的错词本：apple 在列（快照内容展示）
    wrong = client.get(
        f"/api/v1/classes/{code}/vocabulary/wrong-words",
        headers=student_b["headers"],
    ).json()
    assert len(wrong["items"]) == 1
    assert wrong["items"][0]["headword"] == "apple"
    assert wrong["items"][0]["meaning_zh"] == "苹果"
    assert wrong["items"][0]["wrong_count"] == 1

    # 他人会话不可作答（B 不能用 A 的 session 提交）
    hijack = client.post(
        f"{VOCAB}/sessions/{session_a}/answers",
        json={"item_index": 0, "prompt_type": "meaning", "answer": "apple"},
        headers=student_b["headers"],
    )
    assert hijack.status_code == 404

    # 归档后学生继续作答 → 422
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}/archive",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert _answer_code(client, student_b["headers"], session_b, 1, "banana") == 422


def _answer_code(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    item_index: int,
    answer: str,
) -> int:
    resp = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={"item_index": item_index, "prompt_type": "meaning", "answer": answer},
        headers=headers,
    )
    return resp.status_code


# ── 学生身份边界 ────────────────────────────────────────────────────


def test_student_cannot_manage_books(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """学生账号进不了词库管理（403），也读不了教师结果面板。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "普通学生")

    assert client.get(f"{VOCAB}/books", headers=student["headers"]).status_code == 403
    assert (
        client.post(
            f"{VOCAB}/books",
            json={"title": "学生建的库", "scope": "public"},
            headers=student["headers"],
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/classes/{code}/vocabulary/results", headers=student["headers"]
        ).status_code
        == 403
    )
    # 未登录 → 401
    assert client.get(f"{VOCAB}/books").status_code == 401


def test_word_edit_permission_scoped(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """教师只能改自己班级词库里的词；公共词库词条仅管理员可改。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    resp = client.post(
        f"{VOCAB}/books",
        json={
            "title": "班级词库",
            "scope": "classroom",
            "classroom_id": classroom["id"],
            "words": WORDS_3[:1],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    own_word_id = resp.json()["words"][0]["id"]

    # 公共词库词条：教师改 → 403
    public = _make_public_book(client, superuser_token_headers, WORDS_3)
    public_word_id = public["words"][0]["id"]
    assert (
        client.patch(
            f"{VOCAB}/words/{public_word_id}",
            json={"meaning_zh": "教师改公共词"},
            headers=headers,
        ).status_code
        == 403
    )
    # 自己班级词库词条：教师改 → 200
    assert (
        client.patch(
            f"{VOCAB}/words/{own_word_id}",
            json={"meaning_zh": "教师改班级词"},
            headers=headers,
        ).status_code
        == 200
    )
    # 管理员改公共词库词条 → 200
    assert (
        client.patch(
            f"{VOCAB}/words/{public_word_id}",
            json={"meaning_zh": "管理员改"},
            headers=superuser_token_headers,
        ).status_code
        == 200
    )
    # 不存在的词条 → 404
    assert (
        client.patch(
            f"{VOCAB}/words/{uuid.uuid4()}",
            json={"meaning_zh": "不存在"},
            headers=superuser_token_headers,
        ).status_code
        == 404
    )


# ── 评审修复项回归 ──────────────────────────────────────────────────


def test_publish_cannot_use_other_teachers_words(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """发布词单受可见性约束：他人班级词库（整本或词清单）→ 403；公共库正常。"""
    teacher_a, headers_a = _login_teacher(db, client)
    teacher_b, headers_b = _login_teacher(db, client)
    classroom_a = _create_classroom(client, headers_a)
    classroom_b = _create_classroom(client, headers_b)
    # B 班要有学生（发布校验要求名单非空）
    make_student(db, client, classroom_b["code"], "B班学生")

    # A 建班级词库
    resp = client.post(
        f"{VOCAB}/books",
        json={
            "title": "A 的班级词库",
            "scope": "classroom",
            "classroom_id": classroom_a["id"],
            "words": WORDS_3[:2],
        },
        headers=headers_a,
    )
    assert resp.status_code == 200, resp.text
    book_a = resp.json()
    word_ids_a = [word["id"] for word in book_a["words"]]

    # B 整本引用 A 的班级词库 → 403
    assert (
        client.post(
            f"/api/v1/classes/{classroom_b['code']}/vocabulary/assignments",
            json={"book_id": book_a["id"]},
            headers=headers_b,
        ).status_code
        == 403
    )
    # B 用 A 库里的词清单发布到自己班 → 403（防借结果接口读拼写释义）
    assert (
        client.post(
            f"/api/v1/classes/{classroom_b['code']}/vocabulary/assignments",
            json={"word_ids": word_ids_a},
            headers=headers_b,
        ).status_code
        == 403
    )
    # B 用公共词库发布 → 正常（_publish 内部断言 200）
    public = _make_public_book(client, superuser_token_headers, WORDS_3[:1])
    public_ids = [word["id"] for word in public["words"]]
    _publish(client, headers_b, classroom_b["code"], public_ids)
    # 管理员不受限（可以用 A 的班级词库发布到 B 班）
    assert (
        client.post(
            f"/api/v1/classes/{classroom_b['code']}/vocabulary/assignments",
            json={"book_id": book_a["id"]},
            headers=superuser_token_headers,
        ).status_code
        == 200
    )


def test_due_at_enforced_server_side(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """截止时间以服务器时间为准：过期后不能开会话、不能继续作答。"""
    from datetime import UTC, datetime, timedelta

    from app.models import VocabularyAssignment

    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "赶时间学生")

    book = _make_public_book(client, superuser_token_headers, WORDS_3[:2])
    word_ids = [word["id"] for word in book["words"]]
    # 截止时间必须晚于现在 → 设过去直接 422
    assert (
        client.post(
            f"/api/v1/classes/{code}/vocabulary/assignments",
            json={
                "word_ids": word_ids,
                "due_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            },
            headers=headers,
        ).status_code
        == 422
    )

    assignment = _publish(
        client,
        headers,
        code,
        word_ids,
        due_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    session_id = _start_session(client, student["headers"], code)
    _answer(client, student["headers"], session_id, 0, "apple")

    # 把截止时间拨到过去 → 开会话（另一学生）与作答均被拒
    row = db.get(VocabularyAssignment, uuid.UUID(assignment["id"]))
    assert row is not None
    row.due_at = datetime.now(UTC) - timedelta(minutes=1)
    db.add(row)
    db.commit()

    late_student = make_student(db, client, code, "迟到赶时间")
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/sessions",
        json={"assignment_id": assignment["id"]},
        headers=late_student["headers"],
    )
    assert resp.status_code == 422
    assert "截止" in resp.json()["detail"]
    assert _answer_code(client, student["headers"], session_id, 1, "banana") == 422


def test_idempotency_key_bound_to_item(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """幂等键复用到另一题：422 明确拒绝，不返回旧作答。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "幂等学生")

    book = _make_public_book(client, superuser_token_headers, WORDS_3[:2])
    word_ids = [word["id"] for word in book["words"]]
    _publish(client, headers, code, word_ids)
    session_id = _start_session(client, student["headers"], code)

    key = f"bound-{random_lower_string()}"
    first = _answer(client, student["headers"], session_id, 0, "apple", key)
    assert first["item_index"] == 0

    # 同键同题 → 幂等重放
    replay = _answer(client, student["headers"], session_id, 0, "apple", key)
    assert replay == first
    # 同键异题 → 422
    resp = client.post(
        f"{VOCAB}/sessions/{session_id}/answers",
        json={
            "item_index": 1,
            "prompt_type": "meaning",
            "answer": "banana",
            "idempotency_key": key,
        },
        headers=student["headers"],
    )
    assert resp.status_code == 422
    assert "幂等键" in resp.json()["detail"]


def test_audio_only_requires_standard_audio(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """纯听音任务要求全部词有标准音；混合题型无音词回落看义。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    # 先入班（目标名单在发布时固定）
    student = make_student(db, client, code, "听音学生")

    # 一个有音、一个无音
    words = [
        {"headword": "dog", "meaning_zh": "狗", "audio_url": "/audio/dog.mp3"},
        {"headword": "cat", "meaning_zh": "猫"},
    ]
    book = _make_public_book(client, superuser_token_headers, words)
    word_ids = [word["id"] for word in book["words"]]

    # 纯听音 → 422（cat 无标准音）
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments",
        json={"word_ids": word_ids, "prompt_types": ["audio"]},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "标准音" in resp.json()["detail"]

    # 混合题型发布成功；today 里无音词=meaning、有音词=audio
    _publish(client, headers, code, word_ids, prompt_types=["meaning", "audio"])
    plan = client.get(
        f"/api/v1/classes/{code}/vocabulary/today", headers=student["headers"]
    ).json()
    by_meaning = {item["meaning_zh"]: item["prompt_type"] for item in plan["items"]}
    assert by_meaning["狗"] == "audio"
    assert by_meaning["猫"] == "meaning"


def test_results_after_archiving_last_round(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """归档最后一期且未发新任务：默认结果为空，但按 id 仍可回看历史快照成绩。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "历史学生")

    book = _make_public_book(client, superuser_token_headers, WORDS_3[:2])
    word_ids = [word["id"] for word in book["words"]]
    assignment = _publish(client, headers, code, word_ids)
    session_id = _start_session(client, student["headers"], code)
    _answer(client, student["headers"], session_id, 0, "apple")
    _answer(client, student["headers"], session_id, 1, "banana")

    # 结束任务（唯一一期被归档）
    assert (
        client.post(
            f"/api/v1/classes/{code}/vocabulary/assignments/{assignment['id']}/archive",
            headers=headers,
        ).status_code
        == 200
    )
    # 默认结果：无进行中任务 → assignment 为空
    default_results = client.get(
        f"/api/v1/classes/{code}/vocabulary/results", headers=headers
    ).json()
    assert default_results["assignment"] is None
    # 按 id 回看：归档期数的成绩完整
    archived = client.get(
        f"/api/v1/classes/{code}/vocabulary/results",
        params={"assignment_id": assignment["id"]},
        headers=headers,
    ).json()
    assert archived["assignment"]["id"] == assignment["id"]
    assert archived["assignment"]["status"] == "archived"
    assert archived["completed_count"] == 1
    row = next(r for r in archived["students"] if r["display_name"] == "历史学生")
    assert row["status"] == "completed"
    assert row["correct_first_count"] == 2


def test_concurrent_same_key_different_items(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """并发同幂等键跨题：任何成功回包都必须属于请求自己的题号（归属不混淆）。"""
    from concurrent.futures import ThreadPoolExecutor

    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    code = classroom["code"]
    student = make_student(db, client, code, "并发学生")

    book = _make_public_book(client, superuser_token_headers, WORDS_3[:2])
    word_ids = [word["id"] for word in book["words"]]
    _publish(client, headers, code, word_ids)
    session_id = _start_session(client, student["headers"], code)
    token = student["headers"]["Authorization"]
    key = f"concurrent-{random_lower_string()}"

    def submit(item_index: int) -> tuple[int, dict | None]:
        resp = client.post(
            f"{VOCAB}/sessions/{session_id}/answers",
            json={
                "item_index": item_index,
                "prompt_type": "meaning",
                "answer": "apple" if item_index == 0 else "banana",
                "idempotency_key": key,
            },
            headers={"Authorization": token},
        )
        return resp.status_code, (resp.json() if resp.status_code == 200 else None)

    # 同键同时打两道题：两请求都过预检查时，唯一索引只放行一个；
    # 另一个走回退分支，必须 422 而不是拿到别人的判分结果
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, 0), pool.submit(submit, 1)]
        results_pair = [future.result() for future in futures]

    # 同键唯一约束：必然恰好一个成功、一个被拒（预检查或并发回退拦截）
    statuses = sorted(status for status, _ in results_pair)
    assert statuses == [200, 422]
    for status, body in results_pair:
        if status == 200:
            assert body is not None
            assert body["attempt_no"] == 1
            assert body["item_index"] in (0, 1)
