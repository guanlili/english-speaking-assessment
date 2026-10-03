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


@pytest.fixture(autouse=True)
def _cleanup_level_entries_after(db: Session):
    """每个用例结束后清空五级表：防止残留分级数据影响后续文件
    （如 test_vocab_trail 的「未配置词表」场景依赖 vocab 为 None）。"""
    yield
    db.exec(delete(VocabularyLevelEntry))  # type: ignore[call-overload]
    db.commit()


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
        [["headword", "meaning_zh"], ["lemon", "柠檬"]],
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

    # 分级数据：lemon 在 KET 与 CET4（带释义——缺释义行默认不参与统计）
    _upload(
        client,
        superuser_token_headers,
        "KET",
        [["headword", "meaning_zh"], ["lemon", "柠檬"]],
        confirm=True,
    )
    _upload(
        client,
        superuser_token_headers,
        "CET4",
        [["headword", "meaning_zh"], ["lemon", "柠檬"]],
        confirm=True,
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


# ── 二审修复回归 ────────────────────────────────────────────────────


def test_same_batch_duplicates_and_sense_allocation(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """批内同词同释义合并为一行；既有 sense 后再导入多个新释义，sense_no 连续不冲突。"""
    _clear_level_entries(db)
    # 空库同批两行 cat,猫 → 合并 1 行（来源合并），duplicate_in_file 提示
    preview = _upload(
        client,
        superuser_token_headers,
        "KET",
        [
            ["headword", "meaning_zh", "sources"],
            ["cat", "猫", "KET·A"],
            ["Cat", "猫", "KET·B"],
        ],
        confirm=False,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["new_count"] == 1
    assert any("重复" in issue["reason"] for issue in body["duplicates_in_file"])

    resp = _upload(
        client,
        superuser_token_headers,
        "KET",
        [
            ["headword", "meaning_zh", "sources"],
            ["cat", "猫", "KET·A"],
            ["Cat", "猫", "KET·B"],
        ],
        confirm=True,
    )
    assert resp.status_code == 200, resp.text
    cats = db.exec(
        select(VocabularyLevelEntry)
        .where(VocabularyLevelEntry.headword == "cat")
        .order_by(col(VocabularyLevelEntry.sense_no))
    ).all()
    assert len(cats) == 1
    assert cats[0].sources == ["KET·A", "KET·B"]

    # 既有 cat sense1；同批导入两个新释义 → sense 2、3（不再撞唯一约束）
    resp = _upload(
        client,
        superuser_token_headers,
        "KET",
        [
            ["headword", "meaning_zh"],
            ["cat", "猫科动物"],
            ["cat", "盖尔软帽"],
        ],
        confirm=True,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported_new"] == 2
    senses = [
        entry.sense_no
        for entry in db.exec(
            select(VocabularyLevelEntry)
            .where(VocabularyLevelEntry.headword == "cat")
            .order_by(col(VocabularyLevelEntry.sense_no))
        ).all()
    ]
    assert senses == [1, 2, 3]


def test_ocr_csv_preserves_review_and_sources(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """OCR 产物 CSV（needs_review/sources 列）：状态与来源逐行保留；
    未核对行不参与两模块统计，人工核对 + 补释义后才计入。"""
    _clear_level_entries(db)
    csv_text = (
        "headword,part_of_speech,meaning_zh,needs_review,sources,note\n"
        "alike,adv,,true,PET扫描件OCR,拼法变体（OCR）：alike\n"
        "quiet,adj,,false,PET扫描件OCR·Food,\n"
    )
    resp = client.post(
        f"{LEVELS}/import-confirm",
        files={"file": ("pet.csv", csv_text.encode("utf-8"), "text/csv")},
        data={"level": "PET", "source_label": "PET扫描件OCR"},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text

    alike = db.exec(
        select(VocabularyLevelEntry).where(VocabularyLevelEntry.headword == "alike")
    ).one()
    quiet = db.exec(
        select(VocabularyLevelEntry).where(VocabularyLevelEntry.headword == "quiet")
    ).one()
    assert alike.needs_review is True and alike.meaning_zh is None
    assert quiet.needs_review is True  # 缺释义 → 强制待核对（安全默认）
    assert quiet.sources == ["PET扫描件OCR·Food"]

    # 两行都未核对（quiet 缺释义被强制待核对）→ 不参与统计
    assert levels_service.effective_level_map(db, ["alike", "quiet"]) == {}

    # 补录释义并标记已核对 → quiet 计入，alike 仍不参与
    resp = client.patch(
        f"{LEVELS}/entries/{quiet.id}",
        json={"meaning_zh": "安静的", "needs_review": False},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    mapping = levels_service.effective_level_map(db, ["quiet"])
    assert mapping["quiet"][0] == "PET"
    assert levels_service.effective_level_map(db, ["alike"]) == {}

    # 空释义行禁止直接标记已核对
    resp = client.patch(
        f"{LEVELS}/entries/{alike.id}",
        json={"needs_review": False},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 422


def test_teacher_imports_from_levels(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """教师从已核对分级词条创建班级词库并发布：未核对/缺释义跳过；快照语义不变。"""
    _clear_level_entries(db)
    classroom = client.post(
        "/api/v1/classes", json={"class_size": 5}, headers=superuser_token_headers
    ).json()
    student = __import__(
        "tests.utils.credential", fromlist=["make_student"]
    ).make_student(db, client, classroom["code"], "分级学生")

    # 分级词条：quiet 已核对有释义；alike 未核对；cloudy 缺释义已核对
    for headword, level, meaning, review in [
        ("quiet", "PET", "安静的", False),
        ("alike", "PET", None, True),
        ("cloudy", "PET", "多云的", False),
    ]:
        row = VocabularyLevelEntry(
            headword=headword,
            level=level,
            meaning_zh=meaning,
            needs_review=review,
            sources=["测试"],
        )
        if meaning is None:
            row.meaning_zh = ""
        db.add(row)
    db.commit()

    resp = client.post(
        "/api/v1/vocabulary/words/from-levels",
        json={
            "level": "PET",
            "classroom_id": classroom["id"],
            "new_book_title": "PET 已核对词",
        },
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created_count"] == 2  # alike（未核对）跳过
    headwords = {word["headword"] for word in body["words"]}
    assert headwords == {"quiet", "cloudy"}
    assert all(word["level"] == "PET" for word in body["words"])

    # 用生成的词发布 → 快照照常固化
    word_ids = [word["id"] for word in body["words"]]
    published = client.post(
        f"/api/v1/classes/{classroom['code']}/vocabulary/assignments",
        json={"title": "分级发布", "word_ids": word_ids},
        headers=superuser_token_headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["word_count"] == 2

    plan = client.get(
        f"/api/v1/classes/{classroom['code']}/vocabulary/today",
        headers=student["headers"],
    ).json()
    assert plan["assignment"]["title"] == "分级发布"

    # 二次导入同级别 → 词头已存在全部跳过
    again = client.post(
        "/api/v1/vocabulary/words/from-levels",
        json={"level": "PET", "book_id": body["id"]},
        headers=superuser_token_headers,
    )
    assert again.status_code == 200, again.text
    assert again.json()["created_count"] == 0


def test_level_filter_pagination_across_pages(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """按级别选词分页：先过滤后分页，混合级别下不漏词、无空页。"""
    _clear_level_entries(db)
    words = [{"headword": f"ketword{i}", "meaning_zh": f"K{i}"} for i in range(3)] + [
        {"headword": "petword", "meaning_zh": "P"}
    ]
    resp = client.post(
        "/api/v1/vocabulary/books",
        json={"title": "分页测试", "scope": "public", "words": words},
        headers=superuser_token_headers,
    )
    assert resp.status_code == 200, resp.text
    _upload(
        client,
        superuser_token_headers,
        "KET",
        [
            ["headword", "meaning_zh"],
            ["ketword0", "K0"],
            ["ketword1", "K1"],
            ["ketword2", "K2"],
        ],
        confirm=True,
    )
    _upload(
        client,
        superuser_token_headers,
        "PET",
        [["headword", "meaning_zh"], ["petword", "P"]],
        confirm=True,
    )

    page1 = client.get(
        "/api/v1/vocabulary/words",
        params={"level": "PET", "limit": 1, "offset": 0},
        headers=superuser_token_headers,
    ).json()
    assert [word["headword"] for word in page1] == ["petword"]
    page2 = client.get(
        "/api/v1/vocabulary/words",
        params={"level": "KET", "limit": 2, "offset": 2},
        headers=superuser_token_headers,
    ).json()
    assert [word["headword"] for word in page2] == ["ketword2"]


def test_five_level_stats_independent_of_old_wordlist(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """旧词表为空、五级表有数据：level_stats 照常产出（两套口径独立）。"""
    _clear_level_entries(db)
    from sqlmodel import delete

    from app.models import WordlistEntry

    # 捕获原始字段：删除提交后 ORM 实例不可复用，恢复需按字段重建
    saved_wordlist = [
        (entry.lemma, entry.band) for entry in db.exec(select(WordlistEntry)).all()
    ]
    db.exec(delete(WordlistEntry))  # type: ignore[call-overload]
    db.add(
        VocabularyLevelEntry(
            headword="ocean", level="PET", meaning_zh="海洋", sources=["测试"]
        )
    )
    db.commit()
    try:
        payload = scoring_worker._analyze_vocab(db, "the ocean is big")
        assert payload is not None
        assert "wordlist" not in payload  # 旧词表空：无 A2/B1/B2 口径
        assert payload["level_stats"]["hits_by_level"] == {"PET": 1}
    finally:
        # 恢复旧词表（后续 test_vocab_trail 的「未配置词表/命中分析」场景依赖）
        for lemma, band in saved_wordlist:
            db.add(WordlistEntry(lemma=lemma, band=band))
        db.commit()
