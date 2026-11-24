"""AC4 词条内容治理：审核状态机 / 发布门禁 / 权限矩阵 / 乐观锁 / 回退审计 测试。

口径以 ac4-contract.md 为准：
- 新建/导入默认 pending；confirm_reviewed 直接 approved（self_confirmed 留痕）；
- 审核动作只能 pending → approved|rejected；非 pending 冲突 409；拒绝必填意见；
- 未 approved 禁止发布（整本 / 显式词清单双路径），422 `vocabulary_words_not_approved:<n>`；
- 学生自主练习 / 词库浏览 / 错词可练只取 approved；
- approved/rejected 内容被编辑 → 回 pending 并写 reset 审计；
- 词条 PATCH 乐观锁 409、同库重复键 409；word.version 与 book.version 各自 +1；
- 教师只审本人班级库；school_admin 审全校；平台运营只读；跨校 404。
"""

import uuid
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app import crud
from app.core import security
from app.models import (
    MODULE_VOCABULARY,
    Tenant,
    TenantModule,
    User,
    UserCreate,
    VocabularyAssignment,
    VocabularyBook,
    VocabularyBookItem,
    VocabularyLevelEntry,
    VocabularyWord,
)
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"
REVIEWS = f"{VOCAB}/reviews"
REVIEW_AUDIT = f"{VOCAB}/reviews/audit"
ADMIN_REVIEWS = "/api/v1/admin/vocabulary/reviews"
ADMIN_REVIEW_AUDIT = "/api/v1/admin/vocabulary/reviews/audit"


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


def _words(n: int, prefix: str = "g") -> list[dict]:
    return [
        {"headword": f"{prefix}{i:02d}", "part_of_speech": "n.", "meaning_zh": f"词{i}"}
        for i in range(1, n + 1)
    ]


def _make_book(
    client: TestClient,
    headers: dict[str, str],
    classroom_id: str,
    words: list[dict],
    *,
    confirm_reviewed: bool = False,
    title: str | None = None,
    scope: str = "classroom",
) -> dict:
    body: dict = {
        "title": title or f"治理词库{uuid.uuid4().hex[:6]}",
        "scope": scope,
        "words": words,
        "confirm_reviewed": confirm_reviewed,
    }
    if scope == "classroom":
        body["classroom_id"] = classroom_id
    resp = client.post(f"{VOCAB}/books", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _publish(
    client: TestClient,
    headers: dict[str, str],
    code: str,
    *,
    book_id: str | None = None,
    word_ids: list[str] | None = None,
) -> tuple[int, dict]:
    body: dict = {"prompt_types": ["meaning"]}
    if book_id is not None:
        body["book_id"] = book_id
    if word_ids is not None:
        body["word_ids"] = word_ids
    resp = client.post(
        f"/api/v1/classes/{code}/vocabulary/assignments", json=body, headers=headers
    )
    return resp.status_code, resp.json()


def _review(
    client: TestClient,
    headers: dict[str, str],
    word_ids: list[str],
    action: str,
    note: str | None = None,
) -> tuple[int, dict]:
    resp = client.post(
        REVIEWS,
        json={"word_ids": word_ids, "action": action, "note": note},
        headers=headers,
    )
    return resp.status_code, resp.json()


def _book_words(db: Session, book_id: str) -> list[VocabularyWord]:
    return list(
        db.exec(
            select(VocabularyWord)
            .join(
                VocabularyBookItem,
                VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
            )
            .where(VocabularyBookItem.book_id == uuid.UUID(book_id))
        )
    )


# ── 发布门禁：未 approved 禁发布（双路径）──────────────────────────────


def test_pending_whole_book_blocked_publish(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """整本词库路径：pending 词未审 → 422，detail 带未审数量。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(2, "wh"))

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 422
    assert body["detail"] == "vocabulary_words_not_approved:2"


def test_pending_explicit_word_ids_blocked_publish(
    client: TestClient, db: Session
) -> None:
    """显式词清单路径：pending 词同样被拦，n=清单内未审数。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(2, "ex"))
    word_ids = [w["id"] for w in book["words"]]

    status, body = _publish(client, headers, classroom["code"], word_ids=word_ids)
    assert status == 422
    assert body["detail"] == "vocabulary_words_not_approved:2"


def test_approve_then_publish_succeeds(client: TestClient, db: Session) -> None:
    """审核通过后两条路径都放行；审计逐词留痕。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    make_student(db, client, classroom["code"])
    book = _make_book(client, headers, classroom["id"], _words(2, "ap"))
    word_ids = [w["id"] for w in book["words"]]

    status, body = _review(client, headers, word_ids, "approve")
    assert status == 200, body
    assert body == {"updated": 2, "status": "approved"}

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 200, body
    status, _ = _publish(client, headers, classroom["code"], word_ids=word_ids)
    assert status == 200


def test_rejected_words_cannot_publish(client: TestClient, db: Session) -> None:
    """驳回词不可发布；拒绝必须带意见。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(2, "rj"))
    word_ids = [w["id"] for w in book["words"]]

    status, body = _review(client, headers, word_ids, "reject", "释义与课标不符")
    assert status == 200, body
    assert body["status"] == "rejected"

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 422
    assert body["detail"] == "vocabulary_words_not_approved:2"


def test_reject_requires_note(client: TestClient, db: Session) -> None:
    """拒绝意见为空 → 422；通过意见可空。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(1, "rn"))
    word_ids = [w["id"] for w in book["words"]]

    status, body = _review(client, headers, word_ids, "reject", "   ")
    assert status == 422
    assert "意见" in body["detail"]

    status, body = _review(client, headers, word_ids, "approve", None)
    assert status == 200, body


def test_non_pending_review_conflict_409(client: TestClient, db: Session) -> None:
    """已 approved/rejected 的词再次审核 → 409 `review_state_conflict:<n>`。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(1, "cf"))
    word_ids = [w["id"] for w in book["words"]]

    status, _ = _review(client, headers, word_ids, "approve")
    assert status == 200

    status, body = _review(client, headers, word_ids, "approve")
    assert status == 409
    assert body["detail"] == "review_state_conflict:1"


# ── 写路径默认口径：pending / self_confirmed / ai / textbook ──────────


def test_confirm_reviewed_creates_approved_self_confirmed(
    client: TestClient, db: Session
) -> None:
    """建库勾选已核对 → approved，reviewer=当前用户，note=self_confirmed。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(
        client, headers, classroom["id"], _words(2, "sc"), confirm_reviewed=True
    )
    words = _book_words(db, book["id"])
    assert len(words) == 2
    for word in words:
        assert word.review_status == "approved"
        assert word.reviewer_id == teacher.id
        assert word.reviewed_at is not None
        assert word.review_note == "self_confirmed"


def test_add_words_default_pending_and_confirmed_approved(
    client: TestClient, db: Session
) -> None:
    """词库加词：缺省 pending；query confirm_reviewed=true → approved。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], [])

    resp = client.post(
        f"{VOCAB}/books/{book['id']}/words",
        json=[
            {"headword": "pending01", "part_of_speech": "n.", "meaning_zh": "待审词"}
        ],
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    pending = [w for w in resp.json()["words"] if w["headword"] == "pending01"][0]
    assert pending["review_status"] == "pending"

    resp = client.post(
        f"{VOCAB}/books/{book['id']}/words",
        params={"confirm_reviewed": True},
        json=[{"headword": "done01", "part_of_speech": "n.", "meaning_zh": "已核对词"}],
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    approved = [w for w in resp.json()["words"] if w["headword"] == "done01"][0]
    assert approved["review_status"] == "approved"
    assert approved["review_note"] == "self_confirmed"


def test_ai_import_source_ai_default_pending(client: TestClient, db: Session) -> None:
    """AI 草稿入库 source 固定 ai；缺省 pending，勾选已核对 → approved。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], [])

    resp = client.post(
        f"{VOCAB}/ai/word-drafts/import",
        json={
            "book_id": book["id"],
            "drafts": [
                {"headword": "aidraft", "part_of_speech": "n.", "meaning_zh": "AI草稿"}
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ai_word = [w for w in _book_words(db, book["id"]) if w.headword == "aidraft"][0]
    assert ai_word.source == "ai"
    assert ai_word.review_status == "pending"

    resp = client.post(
        f"{VOCAB}/ai/word-drafts/import",
        json={
            "book_id": book["id"],
            "confirm_reviewed": True,
            "drafts": [
                {
                    "headword": "aidraft2",
                    "part_of_speech": "n.",
                    "meaning_zh": "AI已核对",
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    approved = [w for w in _book_words(db, book["id"]) if w.headword == "aidraft2"][0]
    assert approved.source == "ai"
    assert approved.review_status == "approved"


def test_level_conversion_textbook_approved(client: TestClient, db: Session) -> None:
    """五级目录转入：source=textbook、approved、note=level_catalog_verified。"""
    db.exec(delete(VocabularyLevelEntry))  # type: ignore[call-overload]
    db.add(
        VocabularyLevelEntry(
            headword="lemondrop", level="KET", meaning_zh="柠檬糖", sources=["测试"]
        )
    )
    db.commit()

    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], [])

    resp = client.post(
        f"{VOCAB}/words/from-levels",
        json={"level": "KET", "book_id": book["id"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    word = [w for w in _book_words(db, book["id"]) if w.headword == "lemondrop"][0]
    assert word.source == "textbook"
    assert word.review_status == "approved"
    assert word.review_note == "level_catalog_verified"
    assert word.reviewed_at is not None


# ── 审核队列 / 审计留痕 ──────────────────────────────────────────────


def test_review_queue_filters_and_counts(client: TestClient, db: Session) -> None:
    """队列默认 pending；返回待审/驳回/通过计数与来源、状态字段。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(3, "q"))
    word_ids = [w["id"] for w in book["words"]]

    status, _ = _review(client, headers, word_ids[:2], "approve")
    assert status == 200
    status, _ = _review(client, headers, word_ids[2:], "reject", "需补充例句")
    assert status == 200

    resp = client.get(REVIEWS, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pending_count"] == 0
    assert body["approved_count"] == 2
    assert body["rejected_count"] == 1

    resp = client.get(REVIEWS, params={"status": "rejected"}, headers=headers)
    assert resp.status_code == 200
    assert [i["headword"] for i in resp.json()["items"]] == ["q03"]


def test_audit_records_each_word_with_snapshot(client: TestClient, db: Session) -> None:
    """通过 / 拒绝 / 回退逐词一条审计；actor 与 headword 快照落库。"""
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(2, "au"))
    word_ids = [w["id"] for w in book["words"]]

    status, _ = _review(client, headers, word_ids, "approve")
    assert status == 200

    resp = client.get(REVIEW_AUDIT, params={"word_id": word_ids[0]}, headers=headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "approve"
    assert row["from_status"] == "pending"
    assert row["to_status"] == "approved"
    assert row["actor_id"] == str(teacher.id)
    assert row["actor_role"] == "teacher"
    assert row["headword"] == "au01"


# ── 权限矩阵 ─────────────────────────────────────────────────────────


def test_teacher_cannot_review_other_teacher_book(
    client: TestClient, db: Session
) -> None:
    """教师 B 不能审核教师 A 的班级词库 → 403。"""
    teacher_a, headers_a = _login_teacher(db, client)
    classroom_a = _create_classroom(client, headers_a)
    book_a = _make_book(client, headers_a, classroom_a["id"], _words(1, "ta"))

    _teacher_b, headers_b = _login_teacher(db, client)
    word_ids = [w["id"] for w in book_a["words"]]
    status, body = _review(client, headers_b, word_ids, "approve")
    assert status == 403, body


def test_teacher_cannot_review_public_book(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """教师不能审核公共词库 → 403；公共库由 school_admin 维护。"""
    _teacher, headers = _login_teacher(db, client)
    public = _make_book(
        client,
        superuser_token_headers,
        "",
        _words(1, "pub"),
        scope="public",
        title=f"公共库{uuid.uuid4().hex[:6]}",
    )
    word_ids = [w["id"] for w in public["words"]]
    status, body = _review(client, headers, word_ids, "approve")
    assert status == 403, body


def test_school_admin_can_review_school_book(
    client: TestClient, db: Session, superuser_token_headers: dict[str, str]
) -> None:
    """school_admin 可审核本校任意词条（含教师班级库）。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(1, "ad"))
    word_ids = [w["id"] for w in book["words"]]

    status, body = _review(client, superuser_token_headers, word_ids, "approve")
    assert status == 200, body
    assert body["status"] == "approved"


def test_cross_tenant_review_returns_404(client: TestClient, db: Session) -> None:
    """跨校词条按不存在处理 → 404。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(1, "xt"))
    word_ids = [w["id"] for w in book["words"]]

    other = Tenant(slug=f"xt-{uuid.uuid4().hex[:8]}", name_zh="AC4 乙校")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(TenantModule(tenant_id=other.id, module_key=MODULE_VOCABULARY, enabled=True))
    db.commit()
    outsider = User(
        email=f"xt-{uuid.uuid4().hex[:8]}@example.com",
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

    status, body = _review(client, outsider_headers, word_ids, "approve")
    assert status == 404, body


def test_platform_operator_read_only(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    operator_token_headers: dict[str, str],
) -> None:
    """平台运营：跨校只读队列/审计；不能走校级审核写接口。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(2, "op"))
    word_ids = [w["id"] for w in book["words"]]
    _review(client, headers, word_ids, "approve")

    resp = client.get(ADMIN_REVIEWS, headers=operator_token_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] >= 1
    resp = client.get(ADMIN_REVIEW_AUDIT, headers=operator_token_headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) >= 1

    # 平台 token 不能执行校级审核动作
    resp = client.post(
        REVIEWS,
        json={"word_ids": word_ids, "action": "reject", "note": "越权尝试"},
        headers=operator_token_headers,
    )
    assert resp.status_code in (401, 403), resp.text


# ── 词条 PATCH：乐观锁 / 重复键 / 回 pending 审计 ────────────────────


def test_patch_optimistic_lock_and_version_bump(
    client: TestClient, db: Session
) -> None:
    """expected_version 不一致 → 409；命中后 word.version 与 book.version 各 +1。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(
        client, headers, classroom["id"], _words(1, "vl"), confirm_reviewed=True
    )
    word_id = book["words"][0]["id"]
    book_row = db.get(VocabularyBook, uuid.UUID(book["id"]))
    assert book_row is not None
    assert book_row.version == 1

    resp = client.patch(
        f"{VOCAB}/words/{word_id}",
        json={"meaning_zh": "冲突释义", "expected_version": 99},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "vocabulary_word_version_conflict"

    resp = client.patch(
        f"{VOCAB}/words/{word_id}",
        json={"meaning_zh": "更新释义", "expected_version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2

    db.refresh(book_row)
    assert book_row.version == 2


def test_patch_duplicate_key_conflict(client: TestClient, db: Session) -> None:
    """同库同 headword + 释义撞键 → 409 `vocabulary_word_duplicate:<headword>`。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(
        client,
        headers,
        classroom["id"],
        [
            {"headword": "bank", "part_of_speech": "n.", "meaning_zh": "河岸"},
            {"headword": "bank", "part_of_speech": "n.", "meaning_zh": "银行"},
        ],
        confirm_reviewed=True,
    )
    first = [w for w in book["words"] if w["meaning_zh"] == "河岸"][0]

    resp = client.patch(
        f"{VOCAB}/words/{first['id']}",
        json={"meaning_zh": "银行", "expected_version": 1},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "vocabulary_word_duplicate:bank"


def test_approved_edit_resets_to_pending_with_audit(
    client: TestClient, db: Session
) -> None:
    """approved 词条内容被编辑 → 回 pending、清空 reviewer/reviewed_at、
    note=edited_after_approval，并写 reset 审计；回退后不可直接发布。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    make_student(db, client, classroom["code"])
    book = _make_book(
        client, headers, classroom["id"], _words(1, "rs"), confirm_reviewed=True
    )
    word_id = book["words"][0]["id"]

    resp = client.patch(
        f"{VOCAB}/words/{word_id}",
        json={"meaning_zh": "修订后的释义", "expected_version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["review_status"] == "pending"
    assert body["reviewer_id"] is None
    assert body["reviewed_at"] is None
    assert body["review_note"] == "edited_after_approval"

    word = db.get(VocabularyWord, uuid.UUID(word_id))
    assert word is not None
    assert word.review_status == "pending"
    assert word.reviewer_id is None
    assert word.reviewed_at is None

    resp = client.get(REVIEW_AUDIT, params={"word_id": word_id}, headers=headers)
    reset_row = [r for r in resp.json() if r["action"] == "reset"][0]
    assert reset_row["from_status"] == "approved"
    assert reset_row["to_status"] == "pending"

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 422
    assert body["detail"] == "vocabulary_words_not_approved:1"


def test_rejected_edit_keeps_note_and_resets_pending(
    client: TestClient, db: Session
) -> None:
    """rejected 词条被编辑 → 回 pending，保留原拒绝理由，清空 reviewer/reviewed_at。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(1, "rj2"))
    word_id = book["words"][0]["id"]
    status, _ = _review(client, headers, [word_id], "reject", "原拒绝理由")
    assert status == 200

    resp = client.patch(
        f"{VOCAB}/words/{word_id}",
        json={"meaning_zh": "重写释义", "expected_version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["review_status"] == "pending"
    assert body["reviewer_id"] is None
    assert body["review_note"] == "原拒绝理由"


def test_status_only_change_does_not_reset_review(
    client: TestClient, db: Session
) -> None:
    """仅改 active/archived 不重置审核状态。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(
        client, headers, classroom["id"], _words(1, "st"), confirm_reviewed=True
    )
    word_id = book["words"][0]["id"]

    resp = client.patch(
        f"{VOCAB}/words/{word_id}",
        json={"status": "archived", "expected_version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_status"] == "approved"


# ── 快照不受影响 / 学生端过滤 ────────────────────────────────────────


def test_published_snapshot_unaffected_after_reset(
    client: TestClient, db: Session
) -> None:
    """已发布任务快照不随后续审核回退 / 编辑改变。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    make_student(db, client, classroom["code"])
    book = _make_book(
        client, headers, classroom["id"], _words(2, "sn"), confirm_reviewed=True
    )
    word_ids = [w["id"] for w in book["words"]]
    status, assignment = _publish(client, headers, classroom["code"], word_ids=word_ids)
    assert status == 200

    row = db.get(VocabularyAssignment, uuid.UUID(assignment["id"]))
    assert row is not None
    snapshot_headwords = {item["headword"] for item in (row.snapshot_items or [])}
    assert snapshot_headwords == {"sn01", "sn02"}

    # 编辑词条使其回 pending；快照题面/拼写保持发布时形态
    for word_id in word_ids:
        resp = client.patch(
            f"{VOCAB}/words/{word_id}",
            json={"meaning_zh": "快照之后改的释义", "expected_version": 1},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    db.refresh(row)
    assert {
        item["headword"] for item in (row.snapshot_items or [])
    } == snapshot_headwords


def test_self_practice_and_browse_only_approved(
    client: TestClient, db: Session
) -> None:
    """学生端：待审词库不出现在浏览列表，自主练习不可开；approved 库可见可练。"""
    _teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    student = make_student(db, client, classroom["code"])

    pending_book = _make_book(
        client, headers, classroom["id"], _words(2, "pd"), title="待审词库"
    )
    approved_book = _make_book(
        client,
        headers,
        classroom["id"],
        _words(2, "ap"),
        confirm_reviewed=True,
        title="已审词库",
    )

    base = f"/api/v1/classes/{classroom['code']}/vocabulary/student"
    resp = client.get(f"{base}/books", headers=student["headers"])
    assert resp.status_code == 200, resp.text
    titles = {b["title"] for b in resp.json()}
    assert "已审词库" in titles
    assert "待审词库" not in titles

    # 待审库开练 → 422 无可练词条
    resp = client.post(
        f"{base}/sessions",
        json={"kind": "self", "book_id": pending_book["id"]},
        headers=student["headers"],
    )
    assert resp.status_code == 422, resp.text

    # 已审库可开练
    resp = client.post(
        f"{base}/sessions",
        json={"kind": "self", "book_id": approved_book["id"]},
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
