"""五级词库：统一分级数据源的导入与两模块共用测试。

覆盖（评审要求）：
- 跨级重复：同词多级各占一行，实际难度 = 最早（最易）一级；
- 同级重复合并且来源保留；同形异义各成一行（sense_no 区分）；
- 同义词绝不进入可接受拼写（五级导入不触碰 VocabularyWord）；
- 导入单事务：失败整体回滚；
- 背单词模块（按级别选词）与口语模块（用词来源级别）读同一数据源；
- 历史不漂移：已发布快照与旧 A2/B1/B2 词汇分析结果不被重新解释。
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from app import crud
from app.models import (
    Attempt,
    User,
    UserCreate,
    VocabularyLevelEntry,
    VocabularyWord,
)
from app.scoring import worker as scoring_worker
from app.services import vocab_levels as levels_service
from tests.utils.utils import random_email, random_lower_string

LEVELS = "/api/v1/admin/vocab-levels"


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


def _clear_level_entries(db: Session) -> None:
    """测试自清理：五级表独立于其他用例，先清空保证可重复。"""
    db.exec(delete(VocabularyLevelEntry))  # type: ignore[call-overload]
    db.commit()


def _csv(rows: list[list[str]]) -> bytes:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _upload(
    client: TestClient,
    admin_headers: dict,
    level: str,
    rows: list[list[str]],
    confirm: bool,
    label: str = "测试来源",
):
    return client.post(
        f"{LEVELS}/import-{'confirm' if confirm else 'preview'}",
        files={"file": ("words.csv", _csv(rows), "text/csv")},
        data={"level": level, "source_label": label},
        headers=admin_headers,
    )


# ── 导入：重复合并 / 来源保留 / 同形异义 / 跨级 ─────────────────────


def test_import_merge_sources_and_homographs(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """同级重复合并（来源保留）；同词不同释义 = 同形异义各成一行。"""
    _clear_level_entries(db)
    # 第一次导入：barbecue(DAY1) 与 apartment(DAY9)
    resp = _upload(
        client,
        superuser_token_headers,
        "KET",
        [
            ["headword", "part_of_speech", "meaning_zh"],
            ["Barbecue", "n.", "烤肉"],
            ["apartment", "n.", "公寓"],
        ],
        confirm=True,
        label="KET整理版·DAY1",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported_new"] == 2

    # 第二次导入：同一词（大小写不同）同释义 → 合并，来源追加；同词不同释义 → 同形异义新行
    resp = _upload(
        client,
        superuser_token_headers,
        "KET",
        [
            ["headword", "part_of_speech", "meaning_zh"],
            ["barbecue", "n.", "烤肉"],
            ["apartment", "n.", "一套住房"],
        ],
        confirm=True,
        label="KET整理版·DAY10",
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["imported_new"] == 1  # apartment 新释义 = 同形异义新行
    assert result["merged_existing"] == 1  # barbecue 合并

    bb = db.exec(
        select(VocabularyLevelEntry).where(VocabularyLevelEntry.headword == "barbecue")
    ).all()
    assert len(bb) == 1
    assert bb[0].sources == ["KET整理版·DAY1", "KET整理版·DAY10"]

    apartments = db.exec(
        select(VocabularyLevelEntry)
        .where(VocabularyLevelEntry.headword == "apartment")
        .order_by(col(VocabularyLevelEntry.sense_no))
    ).all()
    assert len(apartments) == 2
    assert [a.sense_no for a in apartments] == [1, 2]
    assert {a.meaning_zh for a in apartments} == {"公寓", "一套住房"}


def test_cross_level_duplicate_effective_lowest(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """跨级重复：同词多级各占一行；实际难度 = 最早（最易）一级；预览有冲突提示。"""
    _clear_level_entries(db)
    resp = _upload(
        client,
        superuser_token_headers,
        "KET",
        [["headword"], ["lemon"]],
        confirm=True,
    )
    assert resp.status_code == 200, resp.text

    # 预览 CET4 再导入 lemon：应报跨级冲突（已存在于 KET）
    preview = _upload(
        client,
        superuser_token_headers,
        "CET4",
        [["headword", "meaning_zh"], ["lemon", "柠檬"]],
        confirm=False,
    )
    assert preview.status_code == 200, preview.text
    conflicts = preview.json()["cross_level_conflicts"]
    assert any(
        issue["headword"] == "lemon" and issue["existing_level"] == "KET"
        for issue in conflicts
    )

    resp = _upload(
        client,
        superuser_token_headers,
        "CET4",
        [["headword", "meaning_zh"], ["lemon", "柠檬"]],
        confirm=True,
    )
    assert resp.status_code == 200, resp.text

    levels = db.exec(
        select(VocabularyLevelEntry.level).where(
            VocabularyLevelEntry.headword == "lemon"
        )
    ).all()
    assert sorted(levels) == ["CET4", "KET"]
    # 实际难度取最早一级
    mapping = levels_service.effective_level_map(db, ["lemon"])
    assert mapping["lemon"][0] == "KET"
    assert mapping["lemon"][1] == ["KET", "CET4"]


def test_preview_reports_invalid_and_counts(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """预览：无效行报告 + 导入后各级数量；确认导入各级数量正确。"""
    _clear_level_entries(db)
    preview = _upload(
        client,
        superuser_token_headers,
        "PET",
        [["headword", "meaning_zh"], ["cat", "猫"], ["", "空行头"], ["123bad", "坏词"]],
        confirm=False,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    # 空行头被解析层静默跳过；只有格式无效的「123bad」计为 invalid
    assert len(body["invalid"]) == 1
    assert body["invalid"][0]["headword"] == "123bad"
    assert body["new_count"] == 1
    counts = {c["level"]: c["entry_count"] for c in body["counts_after"]}
    assert counts["PET"] == 1

    resp = _upload(
        client,
        superuser_token_headers,
        "PET",
        [["headword", "meaning_zh"], ["cat", "猫"], ["", "空行头"], ["123bad", "坏词"]],
        confirm=True,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["skipped_invalid"] == 1
    stats = client.get(f"{LEVELS}/stats", headers=superuser_token_headers).json()
    pet = next(level for level in stats["levels"] if level["level"] == "PET")
    assert pet["entry_count"] == 1


def test_import_rollback_on_failure(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
) -> None:
    """导入单事务：提交失败 → 整体回滚，词条数不变。"""
    _clear_level_entries(db)
    before = len(db.exec(select(VocabularyLevelEntry)).all())

    original_commit = levels_service._commit

    def boom(_session: Session) -> None:
        raise RuntimeError("模拟提交失败")

    monkeypatch.setattr(levels_service, "_commit", boom)
    # TestClient 默认重抛服务器异常：导入失败以异常冒出，服务端已整体回滚
    with pytest.raises(RuntimeError, match="模拟提交失败"):
        _upload(
            client,
            superuser_token_headers,
            "CET4",
            [["headword", "meaning_zh"], ["sincere", "真诚的"], ["mood", "情绪"]],
            confirm=True,
        )
    monkeypatch.setattr(levels_service, "_commit", original_commit)

    db.rollback()
    after = len(db.exec(select(VocabularyLevelEntry)).all())
    assert after == before


# ── 两模块同源 + 历史不漂移 ─────────────────────────────────────────


def test_teaching_words_by_level_same_source(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """背单词按级别选词：读同一分级数据源，实际难度取最低级；同义词不进可接受拼写。"""
    _clear_level_entries(db)
    # 建教学词条（带可接受拼写——真正的英美变体）
    resp = client.post(
        "/api/v1/vocabulary/books",
        json={
            "title": "分级选词测试",
            "scope": "public",
            "words": [
                {"headword": "lemon", "meaning_zh": "柠檬", "accepted_spellings": None},
            ],
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text

    # 分级数据：lemon 在 KET 与 CET4
    _upload(
        client, superuser_token_headers, "KET", [["headword"], ["lemon"]], confirm=True
    )
    _upload(
        client, superuser_token_headers, "CET4", [["headword"], ["lemon"]], confirm=True
    )

    words = client.get(
        "/api/v1/vocabulary/words",
        params={"level": "KET"},
        headers=superuser_token_headers,
    ).json()
    lemon = next(word for word in words if word["headword"] == "lemon")
    assert lemon["level"] == "KET"
    assert lemon["all_levels"] == ["KET", "CET4"]
    assert (
        client.get(
            "/api/v1/vocabulary/words",
            params={"level": "IELTS_TOEFL"},
            headers=superuser_token_headers,
        ).json()
        == []
    )

    # 同形异义/同义词导入绝不改写教学词条的 accepted_spellings
    word_row = db.exec(select(VocabularyWord)).first()
    assert word_row is not None
    assert word_row.accepted_spellings is None


def test_speaking_uses_same_level_source(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """口语用词来源级别：与背单词读同一 vocab_level_entry；待核对行不计入。"""
    _clear_level_entries(db)
    db.add(
        VocabularyLevelEntry(
            headword="cat", level="KET", meaning_zh="猫", sources=["测试"]
        )
    )
    db.add(
        VocabularyLevelEntry(
            headword="distribute", level="CET4", meaning_zh="分发", sources=["测试"]
        )
    )
    # 待人工核对的行（OCR）：不计入
    db.add(
        VocabularyLevelEntry(
            headword="alike",
            level="PET",
            needs_review=True,
            sources=["PET扫描件OCR"],
        )
    )
    db.commit()

    stats = scoring_worker._five_level_stats(
        db, "I like cats. They distribute happiness. The word alike stays unmatched."
    )
    assert isinstance(stats, dict)
    hits: dict[str, int] = stats["hits_by_level"]  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
    assert hits["KET"] == 1  # cats → cat（规则屈折）
    assert hits["CET4"] == 1
    assert "PET" not in hits  # needs_review 不计入
    unmatched = stats["unmatched"]
    unmatched_raw = stats.get("unmatched")
    unmatched_count = unmatched_raw if isinstance(unmatched_raw, int) else 0
    assert unmatched_count >= 3  # i/like/they/happiness/alike/the/word/stays… 未命中

    # 无五级数据时返回 None（界面不显示该块）
    db.exec(
        __import__("sqlmodel").delete(VocabularyLevelEntry)  # type: ignore[call-overload]
    )
    db.commit()
    assert scoring_worker._five_level_stats(db, "cats distribute") is None


def test_history_not_reinterpreted(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """历史不漂移：旧的 A2/B1/B2 词汇分析 JSON 与已发布快照在五级导入后原样保留。"""
    _clear_level_entries(db)
    old_vocab: dict[str, object] = {
        "wordlist": "内置演示词表",
        "hits": {"A2": ["cat"], "B1": [], "B2": []},
        "coverage": 0.5,
        "cefr": "A2",
    }
    attempt = Attempt(
        item_type="question",
        item_id=uuid.uuid4(),
        audio_path="unused",
        duration_s=1.0,
        status="done",
        transcript="cat",
        vocab=old_vocab,
        item_snapshot={"type": "question", "id": str(uuid.uuid4()), "text": "t"},
    )
    db.add(attempt)
    db.commit()

    # 五级导入 cat（包括同词）
    _upload(
        client, superuser_token_headers, "KET", [["headword"], ["cat"]], confirm=True
    )

    db.expire_all()
    refreshed = db.get(Attempt, attempt.id)
    assert refreshed is not None
    assert refreshed.vocab == old_vocab  # 旧结果原样保留，不回填 level_stats
    assert (refreshed.item_snapshot or {}).get("type") == "question"
