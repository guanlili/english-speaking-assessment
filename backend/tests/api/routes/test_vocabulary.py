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
