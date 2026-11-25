"""#517 扩展区 + CEFR 标签：字段校验 / 快照兼容 / 扩展区门禁测试。

口径：
- exam_tags ∈ SAT/ACT/GRE/CET4/IELTS/TOEFL（多选，去空白大写去重）；
  cefr_band ∈ A1–C2，nullable；非法值 422 / pydantic ValidationError；
- CEFR 只是词条内容标签：学生侧只读展示 CEFR，不下发 exam_tags，不做等级评定；
- 已发布任务按快照稳定展示；旧快照无 cefr_band 字段安全回落 None；
- 扩展区转入与发布同门禁：必须 approved、可见词库归属、命中高级标签；
  textbook/licensed 授权不齐 422；demo/self_built/ai 免授权但仍需 approved。
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, select

from app import crud
from app.models import (
    User,
    UserCreate,
    VocabularyBookItem,
    VocabularyWord,
    normalize_cefr_band,
    normalize_exam_tags,
)
from app.models.vocabulary.levels import VocabularyLevelEntryUpdate
from app.models.vocabulary.words import (
    VocabularyWordIn,
    VocabularyWordUpdate,
)
from app.services.vocabulary import (
    build_word_snapshot,
    snapshot_cefr_band,
)
from tests.utils.credential import make_student
from tests.utils.utils import random_email, random_lower_string

VOCAB = "/api/v1/vocabulary"
ADVANCED = f"{VOCAB}/advanced-words"

FUTURE = datetime.now(UTC) + timedelta(days=30)


# ── 规范化与 schema 校验（纯单元，不连库）──────────────────────────────


def test_normalize_exam_tags_trim_upper_dedupe() -> None:
    assert normalize_exam_tags(None) == []
    assert normalize_exam_tags([" sat ", "GRE", "sat", ""]) == ["SAT", "GRE"]


def test_normalize_exam_tags_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="exam_tag_invalid"):
        normalize_exam_tags(["LSAT"])


def test_normalize_cefr_band_empty_to_none_and_valid() -> None:
    assert normalize_cefr_band(None) is None
    assert normalize_cefr_band("") is None
    assert normalize_cefr_band(" c1 ") == "C1"


def test_normalize_cefr_band_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="cefr_band_invalid"):
        normalize_cefr_band("B9")


def test_word_in_rejects_invalid_tag_and_band() -> None:
    with pytest.raises(ValidationError):
        VocabularyWordIn(
            headword="abate",
            meaning_zh="减少",
            exam_tags=["LSAT"],
        )
    with pytest.raises(ValidationError):
        VocabularyWordIn(
            headword="abate",
            meaning_zh="减少",
            cefr_band="B9",
        )


def test_word_in_normalizes_valid_tags_and_band() -> None:
    word_in = VocabularyWordIn(
        headword="abate",
        meaning_zh="减少",
        exam_tags=[" gre ", "SAT"],
        cefr_band=" c1 ",
    )
    assert word_in.exam_tags == ["GRE", "SAT"]
    assert word_in.cefr_band == "C1"


def test_word_update_null_clears_fields() -> None:
    update = VocabularyWordUpdate(exam_tags=None, cefr_band=None)
    assert update.exam_tags is None
    assert update.cefr_band is None


def test_level_entry_update_rejects_invalid_tag_and_band() -> None:
    """五级条目更新体复用同一套标签 / 档位校验。"""
    with pytest.raises(ValidationError):
        VocabularyLevelEntryUpdate(exam_tags=["LSAT"])
    with pytest.raises(ValidationError):
        VocabularyLevelEntryUpdate(cefr_band="B9")
    ok = VocabularyLevelEntryUpdate(exam_tags=[" ielts "], cefr_band=" b2 ")
    assert ok.exam_tags == ["IELTS"]
    assert ok.cefr_band == "B2"


def test_model_defaults_empty_tags_and_null_band() -> None:
    """模型默认值：exam_tags 空列表、cefr_band 空；存量回填只做空值。"""
    word = VocabularyWord(headword="legacy", meaning_zh="旧词")
    assert word.exam_tags == []
    assert word.cefr_band is None


# ── 快照兼容：旧快照无字段安全回落 ──────────────────────────────────────


def test_snapshot_cefr_band_falls_back_for_legacy_and_invalid() -> None:
    # 旧快照没有 cefr_band 字段
    assert snapshot_cefr_band({"headword": "apple"}) is None
    # 非法档位不展示
    assert snapshot_cefr_band({"cefr_band": "B9"}) is None
    # 合法小写归一化为大写
    assert snapshot_cefr_band({"cefr_band": "c2"}) == "C2"


def test_build_word_snapshot_carries_tags_and_band() -> None:
    word = VocabularyWord(
        headword="abate",
        meaning_zh="减少",
        exam_tags=["GRE"],
        cefr_band="C1",
    )
    snapshot = build_word_snapshot(word, ["meaning"])
    assert snapshot["exam_tags"] == ["GRE"]
    assert snapshot["cefr_band"] == "C1"


# ── 端点门禁与浏览 ──────────────────────────────────────────────────────


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
    *,
    confirm_reviewed: bool,
    title: str,
) -> dict:
    resp = client.post(
        f"{VOCAB}/books",
        json={
            "title": title,
            "scope": "public",
            "words": words,
            "confirm_reviewed": confirm_reviewed,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


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


APPROVED_ADVANCED = [
    {
        "headword": "abate",
        "part_of_speech": "v.",
        "meaning_zh": "减少",
        "exam_tags": ["GRE"],
        "cefr_band": "C1",
    },
    {
        "headword": "candid",
        "part_of_speech": "adj.",
        "meaning_zh": "坦率的",
        "exam_tags": ["SAT"],
        "cefr_band": "C1",
    },
]
# 非高级标签（TOEFL）：不进扩展区
NON_ADVANCED = [
    {
        "headword": "eloquent",
        "part_of_speech": "adj.",
        "meaning_zh": "雄辩的",
        "exam_tags": ["TOEFL"],
        "cefr_band": "B2",
    },
]
# 待审高级词：可在扩展区浏览，但转入被门禁拦截
PENDING_ADVANCED = [
    {
        "headword": "garrulous",
        "part_of_speech": "adj.",
        "meaning_zh": "啰嗦的",
        "exam_tags": ["GRE"],
        "cefr_band": "C2",
    },
]


def _seed(
    client: TestClient, db: Session, superuser_headers: dict[str, str]
) -> tuple[dict, dict, dict]:
    """公共库：approved 高级词 + 非高级词；另建一本 pending 高级词库。"""
    approved = _make_public_book(
        client,
        superuser_headers,
        APPROVED_ADVANCED + NON_ADVANCED,
        confirm_reviewed=True,
        title="扩展区 approved 公共库",
    )
    pending = _make_public_book(
        client,
        superuser_headers,
        PENDING_ADVANCED,
        confirm_reviewed=False,
        title="扩展区 pending 公共库",
    )
    _teacher, teacher_headers = _login_teacher(db, client)
    classroom = _create_classroom(client, teacher_headers)
    target = client.post(
        f"{VOCAB}/books",
        json={
            "title": "转入目标班级库",
            "scope": "classroom",
            "classroom_id": classroom["id"],
            "words": [],
            "confirm_reviewed": True,
        },
        headers=teacher_headers,
    )
    assert target.status_code == 200, target.text
    return (
        approved,
        pending,
        {
            "teacher_headers": teacher_headers,
            "classroom": classroom,
            "target": target.json(),
        },
    )


def test_advanced_listing_filters_and_validates_query(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    approved, pending, ctx = _seed(client, db, superuser_token_headers)
    headers = ctx["teacher_headers"]
    approved_by = {w["headword"]: w for w in approved["words"]}
    pending_by = {w["headword"]: w for w in pending["words"]}

    resp = client.get(ADVANCED, headers=headers)
    assert resp.status_code == 200, resp.text
    listed = {w["headword"] for w in resp.json()}
    # 高级标签命中即列出（含待审，浏览口径）；非高级标签不出现
    assert {"abate", "candid", "garrulous"} <= listed
    assert "eloquent" not in listed

    # 按考试标签过滤
    sat = client.get(ADVANCED, params={"exam_tag": "SAT"}, headers=headers)
    assert sat.status_code == 200, sat.text
    assert {w["headword"] for w in sat.json()} == {"candid"}

    # 按 CEFR 档位过滤
    c2 = client.get(ADVANCED, params={"cefr_band": "C2"}, headers=headers)
    assert c2.status_code == 200, c2.text
    assert {w["headword"] for w in c2.json()} == {"garrulous"}

    # 标签 / 档位非法取值 → 422
    assert (
        client.get(ADVANCED, params={"exam_tag": "LSAT"}, headers=headers).status_code
        == 422
    )
    assert (
        client.get(ADVANCED, params={"cefr_band": "B9"}, headers=headers).status_code
        == 422
    )

    # 返回体携带标签与档位（教师侧）
    abate = next(w for w in resp.json() if w["headword"] == "abate")
    assert abate["exam_tags"] == ["GRE"]
    assert abate["cefr_band"] == "C1"
    assert approved_by  # 防未使用告警
    assert pending_by


def test_transfer_approved_advanced_words_carries_tags(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    approved, _pending, ctx = _seed(client, db, superuser_token_headers)
    headers = ctx["teacher_headers"]
    target = ctx["target"]
    approved_by = {w["headword"]: w for w in approved["words"]}

    resp = client.post(
        f"{ADVANCED}/transfer",
        json={
            "word_ids": [approved_by["abate"]["id"], approved_by["candid"]["id"]],
            "book_id": target["id"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created_count"] == 2
    assert body["skipped_existing"] == 0

    target_words = _book_words(db, target["id"])
    by_headword = {w.headword: w for w in target_words}
    assert set(by_headword) == {"abate", "candid"}
    assert by_headword["abate"].exam_tags == ["GRE"]
    assert by_headword["abate"].cefr_band == "C1"
    assert by_headword["candid"].exam_tags == ["SAT"]
    assert by_headword["candid"].cefr_band == "C1"

    # 重复转入：同库词头 + 释义一致 → 跳过，不重复建词
    again = client.post(
        f"{ADVANCED}/transfer",
        json={"word_ids": [approved_by["abate"]["id"]], "book_id": target["id"]},
        headers=headers,
    )
    assert again.status_code == 200, again.text
    assert again.json()["created_count"] == 0
    assert again.json()["skipped_existing"] == 1


def test_transfer_rejects_pending_word(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    _approved, pending, ctx = _seed(client, db, superuser_token_headers)
    headers = ctx["teacher_headers"]
    pending_word = pending["words"][0]

    resp = client.post(
        f"{ADVANCED}/transfer",
        json={
            "word_ids": [pending_word["id"]],
            "book_id": ctx["target"]["id"],
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "vocabulary_words_not_approved:1"


def test_transfer_rejects_non_advanced_word(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    approved, _pending, ctx = _seed(client, db, superuser_token_headers)
    headers = ctx["teacher_headers"]
    eloquent = next(w for w in approved["words"] if w["headword"] == "eloquent")

    resp = client.post(
        f"{ADVANCED}/transfer",
        json={"word_ids": [eloquent["id"]], "book_id": ctx["target"]["id"]},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "advanced_words_not_advanced:1"


def test_transfer_rejects_textbook_without_license(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    approved, _pending, ctx = _seed(client, db, superuser_token_headers)
    headers = ctx["teacher_headers"]
    abate = next(w for w in approved["words"] if w["headword"] == "abate")

    # 改为 textbook 来源但缺授权方 → 授权门禁 422（与发布路径同口径）
    row = db.get(VocabularyWord, uuid.UUID(abate["id"]))
    assert row is not None
    row.source_type = "textbook"
    row.license_owner = None
    row.license_ref = "JYB-2026-01"
    row.license_expires_at = FUTURE
    db.add(row)
    db.commit()

    resp = client.post(
        f"{ADVANCED}/transfer",
        json={"word_ids": [abate["id"]], "book_id": ctx["target"]["id"]},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "vocabulary_license_owner_missing:1"


def test_transfer_creates_new_classroom_book(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    approved, _pending, ctx = _seed(client, db, superuser_token_headers)
    headers = ctx["teacher_headers"]
    classroom = ctx["classroom"]
    abate = next(w for w in approved["words"] if w["headword"] == "abate")

    resp = client.post(
        f"{ADVANCED}/transfer",
        json={
            "word_ids": [abate["id"]],
            "classroom_id": classroom["id"],
            "new_book_title": "扩展区转入新词库",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "classroom"
    assert body["created_count"] == 1
    new_words = _book_words(db, body["id"])
    assert new_words[0].exam_tags == ["GRE"]
    assert new_words[0].cefr_band == "C1"


def test_student_book_detail_exposes_only_cefr_not_exam_tags(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
) -> None:
    approved, _pending, ctx = _seed(client, db, superuser_token_headers)
    classroom = ctx["classroom"]
    student = make_student(db, client, classroom["code"], "学生甲")

    resp = client.get(
        f"/api/v1/classes/{classroom['code']}/vocabulary/student/books/{approved['id']}",
        headers=student["headers"],
    )
    assert resp.status_code == 200, resp.text
    words = {w["headword"]: w for w in resp.json()["words"]}
    abate = words["abate"]
    # 学生侧只下发 CEFR，不下发考试标签
    assert abate["cefr_band"] == "C1"
    assert abate["exam_tags"] == []
