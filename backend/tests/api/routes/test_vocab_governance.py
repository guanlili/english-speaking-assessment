"""版权/授权台账 + 词库版本历史/回滚（#517）测试。

覆盖口径：
- 发布门禁：textbook/licensed 缺授权方 / 缺凭证 / 已过期分别 422 稳定错误码；
  self_built/ai/demo 不受授权门禁约束；整本与显式 word_ids 两条路径同口径；
- 管理端：管理员可读写授权并写前后值审计；教师改授权 403；临期/过期提醒；
  CSV 导出；跨校 404 不泄露；
- 版本：建库/加词/移除/编辑/审核留快照；词条级对比（新增/删除/释义/例句/
  词法）；回滚还原内容并生成新 rollback 版本；已发布任务快照不被改写；
  教师不可回滚（403）；跨校 404；内容哈希确定性。
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core import security
from app.core.security import get_password_hash
from app.models import (
    MODULE_VOCABULARY,
    Tenant,
    TenantModule,
    User,
    UserCreate,
    VocabularyAssignment,
    VocabularyBook,
    VocabularyBookItem,
    VocabularyBookVersion,
    VocabularyContentReviewAudit,
    VocabularyWord,
)
from app.services import vocab_governance
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"
LICENSE = f"{VOCAB}/license"
ADMIN_LICENSE = "/api/v1/admin/vocabulary/license"

FUTURE = datetime.now(UTC) + timedelta(days=60)
PAST = datetime.now(UTC) - timedelta(days=1)


# ── 身份与建库辅助 ──────────────────────────────────────────────────


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


def _token_headers(user: User) -> dict[str, str]:
    token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=10),
        role=user.role,
        password_hash=user.hashed_password,
        tenant_id=str(user.tenant_id),
    )
    return {"Authorization": f"Bearer {token}"}


def _login_admin(
    db: Session, client: TestClient, tenant_user: User
) -> tuple[User, dict[str, str]]:
    email, password = random_email(), random_lower_string()
    admin = User(
        email=email,
        hashed_password=get_password_hash(password),
        role="school_admin",
        tenant_id=tenant_user.tenant_id,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin, _token_headers(admin)


def _create_classroom(client: TestClient, headers: dict[str, str]) -> dict:
    resp = client.post("/api/v1/classes", json={"class_size": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _words(n: int, prefix: str) -> list[dict]:
    return [
        {"headword": f"{prefix}{i:02d}", "part_of_speech": "n.", "meaning_zh": f"词{i}"}
        for i in range(1, n + 1)
    ]


def _make_book(
    client: TestClient,
    headers: dict[str, str],
    classroom_id: str,
    words: list[dict],
    title: str | None = None,
) -> dict:
    body: dict = {
        "title": title or f"治理库{uuid.uuid4().hex[:6]}",
        "scope": "classroom",
        "classroom_id": classroom_id,
        "words": words,
    }
    resp = client.post(f"{VOCAB}/books", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _approve(client: TestClient, headers: dict[str, str], word_ids: list[str]) -> None:
    resp = client.post(
        f"{VOCAB}/reviews",
        json={"word_ids": word_ids, "action": "approve"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


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


def _set_words(db: Session, words: list[VocabularyWord], **fields: object) -> None:
    for word in words:
        for key, value in fields.items():
            setattr(word, key, value)
        db.add(word)
    db.commit()


def _set_book(db: Session, book_id: str, **fields: object) -> VocabularyBook:
    book = db.get(VocabularyBook, uuid.UUID(book_id))
    assert book is not None
    for key, value in fields.items():
        setattr(book, key, value)
    db.add(book)
    db.commit()
    db.refresh(book)
    return book


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


def _approved_book(
    client: TestClient, db: Session, n: int, prefix: str
) -> tuple[User, dict[str, str], dict, dict]:
    teacher, headers = _login_teacher(db, client)
    classroom = _create_classroom(client, headers)
    book = _make_book(client, headers, classroom["id"], _words(n, prefix))
    _approve(client, headers, [w["id"] for w in book["words"]])
    return teacher, headers, classroom, book


# ── A. 发布授权门禁 ──────────────────────────────────────────────────


def test_textbook_missing_owner_blocked_publish(
    client: TestClient, db: Session
) -> None:
    """缺授权方 → 422 vocabulary_license_owner_missing。"""
    _teacher, headers, classroom, book = _approved_book(client, db, 2, "mo")
    words = _book_words(db, book["id"])
    _set_words(
        db,
        words,
        source_type="textbook",
        license_owner=None,
        license_ref="JYB-2026-01",
        license_expires_at=FUTURE,
    )

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 422, body
    assert body["detail"] == "vocabulary_license_owner_missing:2"


def test_textbook_missing_ref_blocked_publish_whole_book(
    client: TestClient, db: Session
) -> None:
    """缺凭证（文号与授权书 URL 都空）→ 422 vocabulary_license_ref_missing。"""
    _teacher, headers, classroom, book = _approved_book(client, db, 2, "rf")
    words = _book_words(db, book["id"])
    _set_words(
        db,
        words,
        source_type="textbook",
        license_owner="人教社",
        license_ref=None,
        authorization_doc_url=None,
        license_expires_at=FUTURE,
    )

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 422, body
    assert body["detail"] == "vocabulary_license_ref_missing:2"


def test_textbook_missing_ref_blocked_publish_explicit_ids(
    client: TestClient, db: Session
) -> None:
    """显式 word_ids 路径同口径门禁。"""
    _teacher, headers, classroom, book = _approved_book(client, db, 2, "ri")
    words = _book_words(db, book["id"])
    _set_words(
        db,
        words,
        source_type="licensed",
        license_owner="外研社",
        license_ref=None,
        authorization_doc_url=None,
        license_expires_at=FUTURE,
    )

    status, body = _publish(
        client, headers, classroom["code"], word_ids=[str(words[0].id)]
    )
    assert status == 422, body
    assert body["detail"] == "vocabulary_license_ref_missing:1"


def test_license_expired_blocked_publish(client: TestClient, db: Session) -> None:
    """已过期 → 422 vocabulary_license_expired。"""
    _teacher, headers, classroom, book = _approved_book(client, db, 2, "ex")
    words = _book_words(db, book["id"])
    _set_words(
        db,
        words,
        source_type="textbook",
        license_owner="人教社",
        license_ref="JYB-2026-01",
        license_expires_at=PAST,
    )

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 422, body
    assert body["detail"] == "vocabulary_license_expired:2"


def test_book_level_license_gate(client: TestClient, db: Session) -> None:
    """词库级 licensed 缺授权方同样拦截（词条 self_built 不豁免词库级）。"""
    _teacher, headers, classroom, book = _approved_book(client, db, 1, "bl")
    _set_book(
        db,
        book["id"],
        source_type="licensed",
        license_owner=None,
        license_ref="LX-001",
        license_expires_at=FUTURE,
    )

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 422, body
    assert body["detail"] == "vocabulary_license_owner_missing:1"


def test_self_built_publish_unaffected(client: TestClient, db: Session) -> None:
    """self_built 无授权字段不触发授权门禁，审核通过即可发布。"""
    _teacher, headers, classroom, book = _approved_book(client, db, 1, "sb")
    make_student(db, client, classroom["code"])

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 200, body


def test_textbook_complete_license_publishes(client: TestClient, db: Session) -> None:
    """授权齐备且未过期 → 放行。"""
    _teacher, headers, classroom, book = _approved_book(client, db, 1, "ok")
    words = _book_words(db, book["id"])
    _set_words(
        db,
        words,
        source_type="textbook",
        license_owner="人教社",
        license_ref="JYB-2026-01",
        authorization_doc_url="https://example.com/license.pdf",
        license_expires_at=FUTURE,
    )
    make_student(db, client, classroom["code"])

    status, body = _publish(client, headers, classroom["code"], book_id=book["id"])
    assert status == 200, body


# ── A. 管理端授权 / 审计 / 提醒 / CSV ────────────────────────────────


def test_admin_patch_book_license_writes_audit(client: TestClient, db: Session) -> None:
    teacher, headers, classroom, book = _approved_book(client, db, 1, "au")
    _admin, admin_headers = _login_admin(db, client, teacher)

    resp = client.patch(
        f"{VOCAB}/books/{book['id']}/license",
        json={
            "source_type": "licensed",
            "license_owner": "外研社",
            "license_ref": "WY-2026-01",
            "license_expires_at": FUTURE.isoformat(),
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["license"]["license_owner"] == "外研社"
    assert payload["license"]["source_type"] == "licensed"

    audit = client.get(
        f"{LICENSE}/audit", params={"book_id": book["id"]}, headers=admin_headers
    )
    assert audit.status_code == 200, audit.text
    rows = audit.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["target_type"] == "book"
    assert row["changes"]["license_owner"] == {"from": None, "to": "外研社"}
    assert row["changes"]["license_ref"]["to"] == "WY-2026-01"

    # 普通教师不可改授权
    forbidden = client.patch(
        f"{VOCAB}/books/{book['id']}/license",
        json={"license_owner": "越权"},
        headers=headers,
    )
    assert forbidden.status_code == 403


def test_word_license_patch_admin_only(client: TestClient, db: Session) -> None:
    teacher, headers, classroom, book = _approved_book(client, db, 1, "wl")
    words = _book_words(db, book["id"])
    word_id = str(words[0].id)
    _admin, admin_headers = _login_admin(db, client, teacher)

    forbidden = client.patch(
        f"{VOCAB}/words/{word_id}/license",
        json={"license_owner": "教师越权"},
        headers=headers,
    )
    assert forbidden.status_code == 403

    resp = client.patch(
        f"{VOCAB}/words/{word_id}/license",
        json={
            "source_type": "textbook",
            "license_owner": "人教社",
            "license_ref": "RJ-1",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    audit = client.get(
        f"{LICENSE}/audit", params={"word_id": word_id}, headers=admin_headers
    )
    rows = audit.json()
    assert rows[0]["target_type"] == "word"
    assert rows[0]["word_id"] == word_id


def test_license_alerts_expiring_and_expired(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, _book = _approved_book(client, db, 1, "al")

    def _make_alert_book(prefix: str, expires_at: datetime) -> None:
        b = _make_book(client, headers, classroom["id"], _words(1, prefix))
        w = _book_words(db, b["id"])[0]
        _set_words(
            db,
            [w],
            source_type="textbook",
            license_owner="人教社",
            license_ref="RJ-1",
            license_expires_at=expires_at,
        )

    _make_alert_book("old", PAST)
    _make_alert_book("soon", datetime.now(UTC) + timedelta(days=10))
    _make_alert_book("safe", FUTURE)

    resp = client.get(f"{LICENSE}/alerts", headers=headers)
    assert resp.status_code == 200, resp.text
    alerts = resp.json()
    statuses = {
        a["headword"]: a["license_status"] for a in alerts if a["target_type"] == "word"
    }
    assert statuses["old01"] == "expired"
    assert statuses["soon01"] == "expiring"
    assert "safe01" not in statuses


def test_license_csv_export(client: TestClient, db: Session) -> None:
    teacher, headers, classroom, book = _approved_book(client, db, 1, "csv")
    _admin, admin_headers = _login_admin(db, client, teacher)
    _set_book(
        db,
        book["id"],
        source_type="licensed",
        license_owner="外研社",
        license_ref="WY-1",
        license_expires_at=FUTURE,
    )

    resp = client.get(f"{LICENSE}/export.csv", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers["content-type"]
    text = resp.content.decode("utf-8-sig")
    header = text.splitlines()[0]
    for column in ("词库/词条", "source_type", "授权方", "凭证", "到期日", "状态"):
        assert column in header
    assert "外研社" in text

    # 教师不可导出
    forbidden = client.get(f"{LICENSE}/export.csv", headers=headers)
    assert forbidden.status_code == 403


def test_cross_tenant_license_404(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, book = _approved_book(client, db, 1, "xt")

    other = Tenant(slug=f"xt-{uuid.uuid4().hex[:8]}", name_zh="授权乙校")
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
    outsider_headers = _token_headers(outsider)

    assert (
        client.get(
            f"{VOCAB}/books/{book['id']}/license", headers=outsider_headers
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"{VOCAB}/books/{book['id']}/license",
            json={"license_owner": "越权"},
            headers=outsider_headers,
        ).status_code
        == 404
    )


def test_read_book_license(client: TestClient, db: Session) -> None:
    """按词库读取授权：词库级 + 词条级清单。"""
    teacher, headers, classroom, book = _approved_book(client, db, 2, "rd")
    words = _book_words(db, book["id"])
    _set_words(
        db,
        words,
        source_type="textbook",
        license_owner="人教社",
        license_ref="RJ-1",
        license_expires_at=FUTURE,
    )

    resp = client.get(f"{VOCAB}/books/{book['id']}/license", headers=headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    # 词库级未改授权（self_built）；词条级为 textbook
    assert payload["license"]["source_type"] == "self_built"
    assert payload["license"]["license_status"] == "not_required"
    assert len(payload["words"]) == 2
    assert payload["words"][0]["source_type"] == "textbook"
    assert payload["words"][0]["license_owner"] == "人教社"
    assert payload["words"][0]["license_ref"] == "RJ-1"
    assert payload["words"][0]["license_status"] == "active"


def test_admin_alerts_sees_school_books(client: TestClient, db: Session) -> None:
    """学校管理员提醒口径覆盖全校词库。"""
    teacher, headers, classroom, _book = _approved_book(client, db, 1, "al2")
    _admin, admin_headers = _login_admin(db, client, teacher)
    b = _make_book(client, headers, classroom["id"], _words(1, "al2x"))
    w = _book_words(db, b["id"])[0]
    _set_words(
        db,
        [w],
        source_type="textbook",
        license_owner="人教社",
        license_ref="RJ-1",
        license_expires_at=PAST,
    )

    resp = client.get(f"{LICENSE}/alerts", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert any(a["license_status"] == "expired" for a in resp.json())


def test_platform_admin_audit_readonly(
    client: TestClient, operator_token_headers: dict[str, str]
) -> None:
    resp = client.get(f"{ADMIN_LICENSE}/audit", headers=operator_token_headers)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


def test_platform_admin_csv_export(
    client: TestClient, operator_token_headers: dict[str, str]
) -> None:
    resp = client.get(f"{ADMIN_LICENSE}/export.csv", headers=operator_token_headers)
    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers["content-type"]
    text = resp.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("学校,")


def test_platform_admin_status_ledger(
    client: TestClient,
    db: Session,
    operator_token_headers: dict[str, str],
) -> None:
    """平台台账：当前状态清单 + 学校/词库/状态筛选；学校 token 不可达。"""
    teacher, headers, _classroom, book = _approved_book(client, db, 1, "st-active")
    _set_book(
        db,
        book["id"],
        source_type="licensed",
        license_owner="外研社",
        license_ref="WY-1",
        license_expires_at=FUTURE,
    )

    other = Tenant(slug=f"st-{uuid.uuid4().hex[:8]}", name_zh="授权乙校")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(TenantModule(tenant_id=other.id, module_key=MODULE_VOCABULARY, enabled=True))
    db.commit()

    missing = VocabularyBook(
        tenant_id=other.id,
        title="乙校缺失库",
        source_type="textbook",
    )
    expired = VocabularyBook(
        tenant_id=other.id,
        title="乙校过期库",
        source_type="licensed",
        license_owner="外研社",
        license_ref="WY-2",
        license_expires_at=PAST,
    )
    self_built = VocabularyBook(
        tenant_id=other.id, title="乙校自建库", source_type="self_built"
    )
    db.add_all([missing, expired, self_built])
    db.commit()
    for row in (missing, expired, self_built):
        db.refresh(row)

    resp = client.get(f"{ADMIN_LICENSE}/status", headers=operator_token_headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    by_title = {item["title"]: item for item in payload["items"]}
    assert payload["total"] == len(payload["items"])

    assert by_title[book["title"]]["license_status"] == "active"
    assert by_title[book["title"]]["tenant_name"]
    assert by_title["乙校缺失库"]["license_status"] == "missing"
    assert by_title["乙校过期库"]["license_status"] == "expired"
    assert by_title["乙校自建库"]["license_status"] == "not_required"
    assert by_title["乙校缺失库"]["tenant_name"] == "授权乙校"
    assert by_title["乙校缺失库"]["authorization_doc_url"] is None

    # 状态筛选：missing（测试库 session 级共享，只断言口径一致 + 目标行在内）
    rows = client.get(
        f"{ADMIN_LICENSE}/status",
        params={"status": "missing"},
        headers=operator_token_headers,
    ).json()["items"]
    assert all(row["license_status"] == "missing" for row in rows)
    assert "乙校缺失库" in [row["title"] for row in rows]

    # 状态筛选：active 桶纳入 not_required（免授权来源）
    rows = client.get(
        f"{ADMIN_LICENSE}/status",
        params={"status": "active"},
        headers=operator_token_headers,
    ).json()["items"]
    assert {row["license_status"] for row in rows} <= {"active", "not_required"}

    # 学校筛选（中文名模糊）
    rows = client.get(
        f"{ADMIN_LICENSE}/status",
        params={"tenant": "乙校"},
        headers=operator_token_headers,
    ).json()["items"]
    assert all(row["tenant_name"] == "授权乙校" for row in rows)
    assert "乙校缺失库" in [row["title"] for row in rows]

    # 词库标题筛选
    rows = client.get(
        f"{ADMIN_LICENSE}/status",
        params={"book": "过期"},
        headers=operator_token_headers,
    ).json()["items"]
    assert all("过期" in row["title"] for row in rows)
    assert "乙校过期库" in [row["title"] for row in rows]

    # 非法状态值 422
    bad = client.get(
        f"{ADMIN_LICENSE}/status",
        params={"status": "nope"},
        headers=operator_token_headers,
    )
    assert bad.status_code == 422

    # 学校 token 不可达平台台账（aud 不符 → 401）
    forbidden = client.get(f"{ADMIN_LICENSE}/status", headers=headers)
    assert forbidden.status_code == 401


# ── B. 版本历史 / 对比 / 回滚 ────────────────────────────────────────


def test_version_created_on_create_and_add_words(
    client: TestClient, db: Session
) -> None:
    _teacher, headers, classroom, book = _approved_book(client, db, 2, "v1")

    resp = client.get(f"{VOCAB}/books/{book['id']}/versions", headers=headers)
    assert resp.status_code == 200, resp.text
    listed = resp.json()
    assert listed["total"] >= 1
    create_entry = next(v for v in listed["items"] if v["action"] == "create")
    assert create_entry["version_no"] == 1
    assert create_entry["word_count"] == 2

    added = client.post(
        f"{VOCAB}/books/{book['id']}/words",
        json=[{"headword": "v103", "part_of_speech": "n.", "meaning_zh": "词3"}],
        headers=headers,
    )
    assert added.status_code == 200, added.text

    listed = client.get(f"{VOCAB}/books/{book['id']}/versions", headers=headers).json()
    latest = listed["items"][0]
    assert latest["action"] == "add_words"
    assert latest["word_count"] == 3


def test_version_compare_added_removed_changed(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, book = _approved_book(client, db, 2, "cp")
    words = _book_words(db, book["id"])
    a, b = words[0], words[1]

    # 加 C、删 B、改 A 的释义 / 例句 / 词法
    added = client.post(
        f"{VOCAB}/books/{book['id']}/words",
        json=[{"headword": "cp03", "part_of_speech": "n.", "meaning_zh": "词3"}],
        headers=headers,
    )
    assert added.status_code == 200, added.text
    c_id = added.json()["words"][-1]["id"]
    removed = client.delete(f"{VOCAB}/books/{book['id']}/words/{b.id}", headers=headers)
    assert removed.status_code == 200, removed.text
    edited = client.patch(
        f"{VOCAB}/words/{a.id}",
        json={
            "meaning_zh": "释义改后",
            "example_en": "Example after.",
            "part_of_speech": "v.",
        },
        headers=headers,
    )
    assert edited.status_code == 200, edited.text

    versions = client.get(
        f"{VOCAB}/books/{book['id']}/versions", headers=headers
    ).json()
    latest_no = versions["items"][0]["version_no"]

    resp = client.get(
        f"{VOCAB}/books/{book['id']}/versions/compare",
        params={"from_version": 1, "to_version": latest_no},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    diff = resp.json()
    added_ids = {x["word_id"] for x in diff["added"]}
    removed_ids = {x["word_id"] for x in diff["removed"]}
    assert str(c_id) in added_ids
    assert str(b.id) in removed_ids

    changed = diff["changed"]
    assert len(changed) == 1
    entry = changed[0]
    assert entry["word_id"] == str(a.id)
    assert set(entry["fields"]) == {"meaning", "example", "morphology"}


def test_rollback_restores_content_new_version_and_snapshot_unchanged(
    client: TestClient, db: Session
) -> None:
    teacher, headers, classroom, book = _approved_book(client, db, 2, "rb")
    make_student(db, client, classroom["code"])
    words = _book_words(db, book["id"])
    a, b = words[0], words[1]
    original_meaning = a.meaning_zh

    # 先发布任务，固化快照
    status, assignment = _publish(
        client, headers, classroom["code"], book_id=book["id"]
    )
    assert status == 200, assignment
    assignment_row = db.exec(
        select(VocabularyAssignment).where(
            VocabularyAssignment.classroom_id == uuid.UUID(classroom["id"])
        )
    ).first()
    assert assignment_row is not None
    snapshot_before = assignment_row.snapshot_items

    # 改动：加 C、删 B、改 A 释义
    added = client.post(
        f"{VOCAB}/books/{book['id']}/words",
        json=[{"headword": "rb03", "part_of_speech": "n.", "meaning_zh": "词3"}],
        headers=headers,
    )
    assert added.status_code == 200, added.text
    client.delete(f"{VOCAB}/books/{book['id']}/words/{b.id}", headers=headers)
    client.patch(
        f"{VOCAB}/words/{a.id}",
        json={"meaning_zh": "释义被改掉"},
        headers=headers,
    )

    _admin, admin_headers = _login_admin(db, client, teacher)
    rollback = client.post(
        f"{VOCAB}/books/{book['id']}/versions/1/rollback", headers=admin_headers
    )
    assert rollback.status_code == 200, rollback.text
    rolled = rollback.json()
    assert rolled["action"] == "rollback"
    assert rolled["word_count"] == 2

    # 词库内容还原为 v1 快照
    restored = _book_words(db, book["id"])
    restored_by_id = {str(w.id): w for w in restored}
    assert str(a.id) in restored_by_id
    assert restored_by_id[str(a.id)].meaning_zh == original_meaning
    assert str(b.id) in restored_by_id
    assert len(restored) == 2

    # 回滚生成了新版本，历史版本未被删除
    versions = client.get(
        f"{VOCAB}/books/{book['id']}/versions", headers=admin_headers
    ).json()
    actions = [v["action"] for v in versions["items"]]
    assert "rollback" in actions
    assert versions["total"] >= 3

    # 已发布任务快照未被改写
    db.refresh(assignment_row)
    assert assignment_row.snapshot_items == snapshot_before


def test_rollback_restores_review_approved_snapshot_and_writes_audit(
    client: TestClient, db: Session
) -> None:
    """D1 回归：回滚到已审版本应恢复 approved 审核快照（审核人/时间/清空 note），
    并逐条写 rollback 审计（from/to 版本、操作者、时间）；回滚后再编辑仍回 pending。"""
    teacher, headers, classroom, book = _approved_book(client, db, 2, "rbmeta")
    make_student(db, client, classroom["code"])
    words = _book_words(db, book["id"])
    a = words[0]
    original_meaning = a.meaning_zh

    versions = client.get(
        f"{VOCAB}/books/{book['id']}/versions", headers=headers
    ).json()
    review_row = next(v for v in versions["items"] if v["action"] == "review")
    review_no = review_row["version_no"]

    _admin, admin_headers = _login_admin(db, client, teacher)

    # 编辑 approved 词条 → 回退 pending、清空审核人/时间、打编辑后待审标识
    edited = client.patch(
        f"{VOCAB}/words/{a.id}",
        json={"meaning_zh": "释义被改掉"},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    db.refresh(a)
    assert a.review_status == "pending"
    assert a.reviewer_id is None
    assert a.reviewed_at is None
    assert a.review_note == "edited_after_approval"

    rollback = client.post(
        f"{VOCAB}/books/{book['id']}/versions/{review_no}/rollback",
        headers=admin_headers,
    )
    assert rollback.status_code == 200, rollback.text

    db.refresh(a)
    # 内容与审核快照一并复原
    assert a.meaning_zh == original_meaning
    assert a.review_status == "approved"
    assert a.reviewer_id == teacher.id
    assert a.reviewed_at is not None
    assert a.review_note is None

    # 逐条 rollback 审计：from pending → approved，note 带 from/to 版本与操作者
    audits = list(
        db.exec(
            select(VocabularyContentReviewAudit).where(
                VocabularyContentReviewAudit.word_id == a.id
            )
        )
    )
    rollback_rows = [row for row in audits if row.action == "rollback"]
    assert len(rollback_rows) == 1
    rb = rollback_rows[0]
    assert rb.from_status == "pending"
    assert rb.to_status == "approved"
    assert rb.actor_id == _admin.id
    assert f"v{review_no}" in (rb.note or "")

    # 回滚后再次编辑：仍按既有门禁回 pending，并写 reset 审计
    re_edit = client.patch(
        f"{VOCAB}/words/{a.id}",
        json={"meaning_zh": "又改一次"},
        headers=headers,
    )
    assert re_edit.status_code == 200, re_edit.text
    db.refresh(a)
    assert a.review_status == "pending"
    reset_rows = [row for row in audits if row.action == "reset"]
    assert reset_rows, "再次编辑应写 reset 审计"


def test_rollback_old_snapshot_without_review_meta_is_compatible(
    client: TestClient, db: Session
) -> None:
    """兼容旧版本：快照未收录 reviewer/reviewed_at/note 时，回滚还原 review_status，
    审核人/时间保留当前值，note 清空，不报错。"""
    teacher, headers, _classroom, book = _approved_book(client, db, 1, "rbold")
    words = _book_words(db, book["id"])
    a = words[0]
    _admin, admin_headers = _login_admin(db, client, teacher)

    # 模拟旧快照：缺 reviewer_id / reviewed_at / review_note 键
    entry = vocab_governance._entry_from_word(a)
    for legacy_key in ("reviewer_id", "reviewed_at", "review_note"):
        entry.pop(legacy_key, None)
    legacy_row = VocabularyBookVersion(
        tenant_id=teacher.tenant_id,
        book_id=uuid.UUID(book["id"]),
        version_no=99,
        snapshot=[entry],
        content_hash="legacy",
        action="review",
        summary="旧版快照（无审核元数据）",
    )
    db.add(legacy_row)
    db.commit()

    # 先编辑回退 pending、清空审核人
    client.patch(
        f"{VOCAB}/words/{a.id}",
        json={"meaning_zh": "旧快照回归测试"},
        headers=headers,
    )
    db.refresh(a)
    assert a.review_status == "pending"
    assert a.reviewer_id is None

    book_row = db.get(VocabularyBook, uuid.UUID(book["id"]))
    assert book_row is not None
    vocab_governance.rollback_to_version(db, book_row, legacy_row, _admin)
    db.commit()
    db.refresh(a)

    assert a.review_status == "approved"
    assert a.review_note is None
    # 旧快照无审核人快照：保留当前（已被清空），不臆造审核人
    assert a.reviewer_id is None


def test_rollback_forbidden_for_teacher(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, book = _approved_book(client, db, 1, "rf")

    resp = client.post(
        f"{VOCAB}/books/{book['id']}/versions/1/rollback", headers=headers
    )
    assert resp.status_code == 403


def test_cross_tenant_versions_404(client: TestClient, db: Session) -> None:
    _teacher, headers, classroom, book = _approved_book(client, db, 1, "xv")

    other = Tenant(slug=f"xv-{uuid.uuid4().hex[:8]}", name_zh="版本乙校")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(TenantModule(tenant_id=other.id, module_key=MODULE_VOCABULARY, enabled=True))
    db.commit()
    outsider = User(
        email=f"xv-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="teacher",
        tenant_id=other.id,
    )
    db.add(outsider)
    db.commit()
    db.refresh(outsider)
    outsider_headers = _token_headers(outsider)

    assert (
        client.get(
            f"{VOCAB}/books/{book['id']}/versions", headers=outsider_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"{VOCAB}/books/{book['id']}/versions/compare",
            params={"from_version": 1, "to_version": 2},
            headers=outsider_headers,
        ).status_code
        == 404
    )


def test_content_hash_deterministic() -> None:
    entry_a: dict[str, object] = {
        "word_id": "11111111-1111-1111-1111-111111111111",
        "headword": "apple",
        "part_of_speech": "n.",
        "meaning_zh": "苹果",
        "meaning_en": "fruit",
        "accepted_spellings": ["apple"],
        "example_en": "An apple.",
        "audio_url": None,
        "morphology": [],
        "status": "active",
        "review_status": "approved",
    }
    entry_b = dict(entry_a)
    entry_b["word_id"] = "22222222-2222-2222-2222-222222222222"

    # 顺序无关
    assert vocab_governance.content_hash(
        [entry_a, entry_b]
    ) == vocab_governance.content_hash([entry_b, entry_a])
    # 拼写顺序归一化后同值
    reordered = dict(entry_a)
    reordered["accepted_spellings"] = ["apple", "aplle"]
    reordered2 = dict(entry_a)
    reordered2["accepted_spellings"] = ["aplle", "apple"]
    assert vocab_governance.content_hash([reordered]) == vocab_governance.content_hash(
        [reordered2]
    )
    # 内容变化 → 哈希变化
    changed = dict(entry_a)
    changed["meaning_zh"] = "梨子"
    assert vocab_governance.content_hash([entry_a]) != vocab_governance.content_hash(
        [changed]
    )
