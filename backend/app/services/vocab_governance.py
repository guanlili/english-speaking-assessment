"""版权/授权台账 + 词库版本历史域逻辑（#517）。

不变量：
- **发布门禁**：textbook/licensed 来源的词库或词条，发布任务时必须带授权方
  与凭证（授权文号或授权书 URL），有效期填写则须晚于当前时间；缺授权方 /
  缺凭证 / 已过期分别返回稳定错误码 422。self_built/ai/demo 仍走既有
  approved 审核门禁，本门禁不放宽。
- **快照不可变**：版本快照落库后不改写；回滚只生成新版本、不删除历史；
  已有 ``vocabulary_assignment.snapshot_items`` 永不被本模块改写。
- **哈希确定性**：词条集合归一化（字段排序、列表规范化）后序列化，同内容
  同值，与入库顺序无关。
"""

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    LICENSE_ERROR_EXPIRED,
    LICENSE_ERROR_OWNER_MISSING,
    LICENSE_ERROR_REF_MISSING,
    LICENSE_EXPIRING_DAYS,
    LICENSE_REQUIRED_SOURCE_TYPES,
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_EXPIRED,
    LICENSE_STATUS_EXPIRING,
    LICENSE_STATUS_NOT_REQUIRED,
    VOCAB_SOURCE_TYPES,
    VocabularyBook,
    VocabularyBookItem,
    VocabularyBookVersion,
    VocabularyLicenseAudit,
    VocabularyVersionDiffEntry,
    VocabularyWord,
    get_datetime_utc,
)
from app.services import vocabulary_prompt_types as prompt_types_mod

# 授权台账可更新字段（与请求体一致）
LICENSE_FIELDS = (
    "source_type",
    "license_owner",
    "license_ref",
    "license_expires_at",
    "authorization_doc_url",
    "license_note",
)

# 版本快照收录的词条内容字段（review_status 一并快照，供对比展示；
# 回滚只还原内容字段，不回退审核状态治理结果）。
VERSION_CONTENT_FIELDS = (
    "headword",
    "part_of_speech",
    "meaning_zh",
    "meaning_en",
    "accepted_spellings",
    "example_en",
    "audio_url",
    "morphology",
    "status",
    "review_status",
)

# 对比维度 → 快照字段分组
_DIFF_FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "headword": ("headword",),
    "meaning": ("meaning_zh", "meaning_en"),
    "example": ("example_en",),
    "morphology": (
        "part_of_speech",
        "accepted_spellings",
        "morphology",
    ),
}

_PRIORITY_ERRORS = (
    LICENSE_ERROR_OWNER_MISSING,
    LICENSE_ERROR_REF_MISSING,
    LICENSE_ERROR_EXPIRED,
)


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _iso(value: Any) -> str | None:
    """审计前后值规范化：datetime → ISO 字符串；其余原样。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def source_type_from_source(source: str | None) -> str:
    """旧 ``source`` 标识 → 新 ``source_type``（与迁移回填同口径）。"""
    if source in ("ai", "demo", "textbook"):
        return source
    return "self_built"


def _str_field(entry: dict[str, object], key: str) -> str | None:
    value = entry.get(key)
    return value if isinstance(value, str) else None


def _str_list_field(entry: dict[str, object], key: str) -> list[str] | None:
    value = entry.get(key)
    if not isinstance(value, list):
        return None
    return [str(item) for item in value]


# ── 授权状态与发布门禁 ──────────────────────────────────────────────


def license_status(
    source_type: str | None,
    expires_at: datetime | None,
    now: datetime,
    expiring_days: int = LICENSE_EXPIRING_DAYS,
) -> str:
    """授权状态：免授权 / 有效 / 临期 / 已过期。"""
    if source_type not in LICENSE_REQUIRED_SOURCE_TYPES:
        return LICENSE_STATUS_NOT_REQUIRED
    if expires_at is None:
        return LICENSE_STATUS_ACTIVE
    if expires_at <= now:
        return LICENSE_STATUS_EXPIRED
    if (expires_at - now).total_seconds() <= expiring_days * 86400:
        return LICENSE_STATUS_EXPIRING
    return LICENSE_STATUS_ACTIVE


def _license_violation(
    *,
    source_type: str | None,
    owner: str | None,
    ref: str | None,
    doc_url: str | None,
    expires_at: datetime | None,
    now: datetime,
) -> str | None:
    """单实体（词库/词条）授权校验；返回稳定错误码或 None（通过）。"""
    if source_type not in LICENSE_REQUIRED_SOURCE_TYPES:
        return None
    if not _clean_text(owner):
        return LICENSE_ERROR_OWNER_MISSING
    if not (_clean_text(ref) or _clean_text(doc_url)):
        return LICENSE_ERROR_REF_MISSING
    if expires_at is not None and expires_at <= now:
        return LICENSE_ERROR_EXPIRED
    return None


def _books_of_words(
    session: Session, words: Sequence[VocabularyWord]
) -> list[VocabularyBook]:
    """词条归属的词库去重集合（可见性已由发布前门禁保证）。"""
    if not words:
        return []
    word_ids = [w.id for w in words]
    book_ids = set(
        session.exec(
            select(VocabularyBookItem.book_id).where(
                col(VocabularyBookItem.word_id).in_(word_ids)  # type: ignore[operator]
            )
        ).all()
    )
    if not book_ids:
        return []
    return list(
        session.exec(
            select(VocabularyBook).where(col(VocabularyBook.id).in_(book_ids))  # type: ignore[operator]
        ).all()
    )


def enforce_publish_license(session: Session, words: Sequence[VocabularyWord]) -> None:
    """发布授权门禁：整本词库与显式词清单两条路径同口径。

    先校验词条归属词库级授权，再校验词条级授权；按错误优先级聚合计数，
    首个未通过的错误码 422（detail 形如 ``<code>:<n>``）。
    """
    now = get_datetime_utc()
    violations: dict[str, int] = {}

    def _record(code: str | None) -> None:
        if code is not None:
            violations[code] = violations.get(code, 0) + 1

    for book in _books_of_words(session, words):
        _record(
            _license_violation(
                source_type=book.source_type,
                owner=book.license_owner,
                ref=book.license_ref,
                doc_url=book.authorization_doc_url,
                expires_at=book.license_expires_at,
                now=now,
            )
        )
    for word in words:
        _record(
            _license_violation(
                source_type=word.source_type,
                owner=word.license_owner,
                ref=word.license_ref,
                doc_url=word.authorization_doc_url,
                expires_at=word.license_expires_at,
                now=now,
            )
        )

    for code in _PRIORITY_ERRORS:
        if code in violations:
            raise HTTPException(status_code=422, detail=f"{code}:{violations[code]}")


# ── 授权变更审计 ───────────────────────────────────────────────────


def apply_license_update(
    session: Session,
    *,
    target: VocabularyBook | VocabularyWord,
    target_type: str,
    book_id: uuid.UUID | None,
    word_id: uuid.UUID | None,
    actor: Any,
    payload: dict[str, Any],
    note: str | None = None,
) -> dict[str, dict[str, str | None]]:
    """把请求体落到目标实体；逐字段记录前后值并写审计行。返回变更字段快照。"""
    changes: dict[str, dict[str, str | None]] = {}
    for field in LICENSE_FIELDS:
        if field not in payload:
            continue
        new_value = payload[field]
        if (
            field == "source_type"
            and new_value is not None
            and new_value not in VOCAB_SOURCE_TYPES
        ):
            raise HTTPException(status_code=422, detail="source_type_invalid")
        old_value = getattr(target, field)
        if _iso(old_value) != _iso(new_value):
            changes[field] = {"from": _iso(old_value), "to": _iso(new_value)}
            setattr(target, field, new_value)
    if not changes:
        return changes
    session.add(
        VocabularyLicenseAudit(
            tenant_id=target.tenant_id,  # type: ignore[union-attr]
            target_type=target_type,
            book_id=book_id,
            word_id=word_id,
            actor_id=actor.id if actor else None,
            actor_name=(actor.full_name or actor.username or actor.email)
            if actor
            else None,
            actor_role=actor.role if actor else None,
            changes=changes,
            note=note,
        )
    )
    return changes


# ── 版本快照：采集 / 哈希 / 列表 / 对比 / 回滚 ──────────────────────


def _entry_from_word(word: VocabularyWord) -> dict[str, object]:
    return {
        "word_id": str(word.id),
        "headword": word.headword,
        "part_of_speech": word.part_of_speech,
        "meaning_zh": word.meaning_zh,
        "meaning_en": word.meaning_en,
        "accepted_spellings": sorted(word.accepted_spellings or []),
        "example_en": word.example_en,
        "audio_url": word.audio_url,
        "morphology": prompt_types_mod.normalize_morphology(word.morphology),
        "status": word.status,
        "review_status": word.review_status,
    }


def _load_book_entries(
    session: Session, book: VocabularyBook
) -> list[dict[str, object]]:
    words = list(
        session.exec(
            select(VocabularyWord)
            .join(
                VocabularyBookItem,
                VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
            )
            .where(VocabularyBookItem.book_id == book.id)  # type: ignore[arg-type]
            .order_by(col(VocabularyBookItem.position))
        ).all()
    )
    return [_entry_from_word(word) for word in words]


def _normalize_entry(entry: dict[str, object]) -> dict[str, object]:
    """哈希归一化：拼写列表排序、词法规范化，消除顺序带来的伪差异。"""
    normalized = dict(entry)
    spellings = entry.get("accepted_spellings")
    normalized["accepted_spellings"] = (
        sorted(str(item) for item in spellings) if isinstance(spellings, list) else []
    )
    normalized["morphology"] = prompt_types_mod.normalize_morphology(
        entry.get("morphology")
    )
    return normalized


def content_hash(entries: Sequence[dict[str, object]]) -> str:
    """确定性哈希：条目按序列化串排序，字段 sort_keys、紧凑分隔、不转义中文。"""
    serialized = sorted(
        json.dumps(
            _normalize_entry(entry),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for entry in entries
    )
    digest = hashlib.sha256()
    digest.update("\n".join(serialized).encode("utf-8"))
    return digest.hexdigest()


def _latest_version(
    session: Session, book_id: uuid.UUID
) -> VocabularyBookVersion | None:
    return session.exec(
        select(VocabularyBookVersion)
        .where(VocabularyBookVersion.book_id == book_id)  # type: ignore[arg-type]
        .order_by(col(VocabularyBookVersion.version_no).desc())
    ).first()


def capture_version(
    session: Session,
    book: VocabularyBook,
    *,
    actor: Any,
    action: str,
    summary: str | None = None,
    force: bool = False,
) -> VocabularyBookVersion | None:
    """采集当前词库快照；内容与上一版一致且非强制时不落无意义版本。

    必须在写操作同一事务内、commit 前调用；返回新快照行（或跳过 None）。
    """
    entries = _load_book_entries(session, book)
    digest = content_hash(entries)
    latest = _latest_version(session, book.id)
    if not force and latest is not None and latest.content_hash == digest:
        return None
    version_no = (latest.version_no if latest is not None else 0) + 1
    row = VocabularyBookVersion(
        tenant_id=book.tenant_id,  # type: ignore[union-attr]
        book_id=book.id,
        version_no=version_no,
        snapshot=entries,
        content_hash=digest,
        actor_id=actor.id if actor else None,
        actor_name=(actor.full_name or actor.username or actor.email)
        if actor
        else None,
        actor_role=actor.role if actor else None,
        action=action,
        summary=summary,
    )
    session.add(row)
    return row


def list_versions(
    session: Session, book: VocabularyBook
) -> list[VocabularyBookVersion]:
    return list(
        session.exec(
            select(VocabularyBookVersion)
            .where(VocabularyBookVersion.book_id == book.id)  # type: ignore[arg-type]
            .order_by(col(VocabularyBookVersion.version_no).desc())
        ).all()
    )


def get_version_or_404(
    session: Session, book: VocabularyBook, version_no: int
) -> VocabularyBookVersion:
    row = session.exec(
        select(VocabularyBookVersion).where(
            VocabularyBookVersion.book_id == book.id,  # type: ignore[arg-type]
            VocabularyBookVersion.version_no == version_no,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="词库版本不存在")
    return row


def _diff_fields(
    from_entry: dict[str, object], to_entry: dict[str, object]
) -> list[str]:
    changed: list[str] = []
    for dimension, fields in _DIFF_FIELD_GROUPS.items():
        if any(from_entry.get(f) != to_entry.get(f) for f in fields):
            changed.append(dimension)
    return changed


def compare_versions(
    from_row: VocabularyBookVersion, to_row: VocabularyBookVersion
) -> dict[str, list[VocabularyVersionDiffEntry]]:
    """词条级对比：新增 / 删除 / 变更（变更带维度与前后条目）。"""
    from_map = {str(e["word_id"]): e for e in (from_row.snapshot or [])}
    to_map = {str(e["word_id"]): e for e in (to_row.snapshot or [])}
    added: list[VocabularyVersionDiffEntry] = []
    removed: list[VocabularyVersionDiffEntry] = []
    changed: list[VocabularyVersionDiffEntry] = []

    for wid in sorted(to_map.keys() - from_map.keys()):
        to_entry = to_map[wid]
        added.append(
            VocabularyVersionDiffEntry(
                word_id=uuid.UUID(wid),
                headword=str(to_entry["headword"]),
                change_kind="added",
                fields=[],
                from_entry=None,
                to_entry=to_entry,
            )
        )
    for wid in sorted(from_map.keys() - to_map.keys()):
        from_entry = from_map[wid]
        removed.append(
            VocabularyVersionDiffEntry(
                word_id=uuid.UUID(wid),
                headword=str(from_entry["headword"]),
                change_kind="removed",
                fields=[],
                from_entry=from_entry,
                to_entry=None,
            )
        )
    for wid in sorted(from_map.keys() & to_map.keys()):
        from_entry = from_map[wid]
        to_entry = to_map[wid]
        fields = _diff_fields(from_entry, to_entry)
        if fields:
            changed.append(
                VocabularyVersionDiffEntry(
                    word_id=uuid.UUID(wid),
                    headword=str(to_entry["headword"]),
                    change_kind="changed",
                    fields=fields,
                    from_entry=from_entry,
                    to_entry=to_entry,
                )
            )
    return {"added": added, "removed": removed, "changed": changed}


def _restore_content(word: VocabularyWord, entry: dict[str, object]) -> None:
    word.headword = str(entry["headword"])
    word.part_of_speech = _str_field(entry, "part_of_speech")
    word.meaning_zh = str(entry["meaning_zh"])
    word.meaning_en = _str_field(entry, "meaning_en")
    word.accepted_spellings = _str_list_field(entry, "accepted_spellings")
    word.example_en = _str_field(entry, "example_en")
    word.audio_url = _str_field(entry, "audio_url")
    word.morphology = prompt_types_mod.normalize_morphology(entry.get("morphology"))
    word.status = str(entry.get("status") or "active")
    word.version += 1


def rollback_to_version(
    session: Session,
    book: VocabularyBook,
    target_row: VocabularyBookVersion,
    actor: Any,
) -> VocabularyBookVersion:
    """回滚到指定版本：词库内容等于目标快照，并生成一条新的 rollback 版本。

    只改词库词条与词库条目；不触碰任何 ``vocabulary_assignment.snapshot_items``
    与历史作答。目标快照中仍存在的词条行按快照还原内容；条目被移除的词
    重新挂回；词条行已被硬删的按快照重建（历史作答按其自身快照解释，不受影响）。
    """
    target_entries: list[dict[str, object]] = list(target_row.snapshot or [])
    target_map = {str(e["word_id"]): e for e in target_entries}

    current_items = list(
        session.exec(
            select(VocabularyBookItem).where(
                VocabularyBookItem.book_id == book.id  # type: ignore[arg-type]
            )
        ).all()
    )
    current_item_by_word = {str(item.word_id): item for item in current_items}

    # 目标快照之外的条目移出词库（词条行保留，与既有「移除词条」口径一致）
    for item in current_items:
        if str(item.word_id) not in target_map:
            session.delete(item)

    target_ids = [uuid.UUID(wid) for wid in target_map]
    existing_words = {
        str(word.id): word
        for word in session.exec(
            select(VocabularyWord).where(col(VocabularyWord.id).in_(target_ids))  # type: ignore[operator]
        ).all()
    }

    for position, entry in enumerate(target_entries, start=1):
        wid = str(entry["word_id"])
        word = existing_words.get(wid)
        if word is None:
            word = VocabularyWord(
                tenant_id=book.tenant_id,  # type: ignore[union-attr]
                headword=str(entry["headword"]),
                part_of_speech=_str_field(entry, "part_of_speech"),
                meaning_zh=str(entry["meaning_zh"]),
                meaning_en=_str_field(entry, "meaning_en"),
                accepted_spellings=_str_list_field(entry, "accepted_spellings"),
                example_en=_str_field(entry, "example_en"),
                audio_url=_str_field(entry, "audio_url"),
                morphology=prompt_types_mod.normalize_morphology(
                    entry.get("morphology")
                ),
                status=str(entry.get("status") or "active"),
                review_status=str(entry.get("review_status") or "pending"),
            )
            session.add(word)
            session.flush()
        else:
            _restore_content(word, entry)
        item = current_item_by_word.get(wid)
        if item is None:
            session.add(
                VocabularyBookItem(book_id=book.id, word_id=word.id, position=position)
            )
        else:
            item.position = position

    book.version += 1
    session.add(book)
    session.flush()

    rolled_back = capture_version(
        session,
        book,
        actor=actor,
        action="rollback",
        summary=f"回滚到版本 v{target_row.version_no}",
        force=True,
    )
    assert rolled_back is not None
    return rolled_back
