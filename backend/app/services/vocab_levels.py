"""五级词库域逻辑：统一分级数据源的导入、归类与查询。

不变量（设计约束）：
- 级别固定顺序 KET→PET→学术→四级→雅思&托福；实际难度默认取最早（最易）一级；
- 同 (headword, level) 不同释义 = 同形异义，各占一行（sense_no 区分）；
  同义词既不是同形异义，也绝不进入任何词条的「可接受拼写」；
- 同 (headword, level, 释义) 的重复行合并，来源标签全部保留；
- 导入是单事务：任何失败整体回滚，绝不落半批；
- 只写 vocab_level_entry：已发布任务快照与历史 A2/B1/B2 词汇分析
  结果永远不会被五级导入重新解释。
"""

import csv
import io
import uuid
from dataclasses import dataclass, field

import sqlalchemy as sa
from fastapi import HTTPException
from sqlmodel import Session, col, func, select

from app.models import (
    VOCAB_LEVEL_IMPORT_MAX_ROWS,
    VOCAB_LEVEL_ORDER,
    VocabularyLevelEntry,
    VocabularyLevelEntryPublic,
    VocabularyLevelImportIssue,
    VocabularyLevelImportPreview,
    VocabularyLevelLevelCount,
    VocabularyLevelStats,
    VocabularyWord,
    VocabularyWordIn,
    VocabularyWordPublic,
    effective_vocab_level,
)
from app.services.vocabulary import normalize_spelling

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def validate_level(level: str) -> str:
    if level not in VOCAB_LEVEL_ORDER:
        raise HTTPException(
            status_code=422,
            detail="未知词库级别，可选：" + "/".join(VOCAB_LEVEL_ORDER),
        )
    return level


@dataclass
class ParsedRow:
    headword: str  # 已规范化
    part_of_speech: str | None = None
    meaning_zh: str | None = None
    line: int = 0


def parse_upload(text: str) -> list[ParsedRow]:
    """解析上传的 CSV/TXT：表头 headword[,part_of_speech][,meaning_zh]，
    或无表头的每行一词（可选「单词 词性 释义」空格分隔）。

    解析只做结构与格式校验；语义问题（重复/跨级冲突）在预览阶段报告。
    """
    rows: list[ParsedRow] = []
    reader = csv.reader(io.StringIO(text))
    raw_rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not raw_rows:
        raise HTTPException(status_code=422, detail="文件为空")
    header = [cell.strip().casefold() for cell in raw_rows[0]]
    has_header = "headword" in header or "单词" in header
    col_map: dict[str, int] = {}
    if has_header:
        for idx, name in enumerate(header):
            if name in ("headword", "单词", "word"):
                col_map.setdefault("headword", idx)
            elif name in ("part_of_speech", "词性", "pos"):
                col_map.setdefault("part_of_speech", idx)
            elif name in ("meaning_zh", "释义", "中文释义", "meaning"):
                col_map.setdefault("meaning_zh", idx)
        if "headword" not in col_map:
            raise HTTPException(
                status_code=422,
                detail="CSV 需要表头：headword[,part_of_speech][,meaning_zh]",
            )
        data_rows = raw_rows[1:]
    else:
        col_map = {"headword": 0, "part_of_speech": 1, "meaning_zh": 2}
        data_rows = raw_rows

    if len(data_rows) > VOCAB_LEVEL_IMPORT_MAX_ROWS:
        raise HTTPException(
            status_code=422,
            detail=f"单次导入最多 {VOCAB_LEVEL_IMPORT_MAX_ROWS} 行",
        )
    for line_no, cells in enumerate(data_rows, start=2 if has_header else 1):
        headword_raw = (
            cells[col_map["headword"]].strip()
            if col_map["headword"] < len(cells)
            else ""
        )
        if not headword_raw:
            continue
        pos = (
            cells[col_map["part_of_speech"]].strip()
            if "part_of_speech" in col_map and col_map["part_of_speech"] < len(cells)
            else ""
        )
        meaning = (
            cells[col_map["meaning_zh"]].strip()
            if "meaning_zh" in col_map and col_map["meaning_zh"] < len(cells)
            else ""
        )
        rows.append(
            ParsedRow(
                headword=normalize_spelling(headword_raw),
                part_of_speech=pos or None,
                meaning_zh=meaning or None,
                line=line_no,
            )
        )
    return rows


def _validate_rows(
    rows: list[ParsedRow],
) -> tuple[list[ParsedRow], list[VocabularyLevelImportIssue]]:
    """结构有效性：headword 必须是拉丁词形（词/词组），长度 ≤64。"""
    import re

    valid_re = re.compile(r"^[a-zA-Z][a-zA-Z'\-]*(?: [a-zA-Z][a-zA-Z'\-]*)*$")
    valid: list[ParsedRow] = []
    invalid: list[VocabularyLevelImportIssue] = []
    for row in rows:
        if not row.headword:
            continue
        if len(row.headword) > 64 or not valid_re.match(row.headword):
            invalid.append(
                VocabularyLevelImportIssue(
                    kind="invalid",
                    line=row.line,
                    headword=row.headword[:32],
                    reason="单词格式无效（仅支持英文字母/连字符/撇号与词组空格）",
                )
            )
            continue
        valid.append(row)
    return valid, invalid


@dataclass
class ImportPlan:
    """一次导入的执行计划：新建行 + 待合并的既有行。"""

    new_entries: list[VocabularyLevelEntry] = field(default_factory=list)
    merges: list[tuple[VocabularyLevelEntry, list[str], str | None, str | None]] = (
        field(default_factory=list)
    )  # (existing, new_sources, pos_if_empty, meaning_if_empty)
    duplicates_in_file: list[VocabularyLevelImportIssue] = field(default_factory=list)
    cross_level_conflicts: list[VocabularyLevelImportIssue] = field(
        default_factory=list
    )
    new_count: int = 0
    merge_count: int = 0


def plan_import(
    session: Session,
    level: str,
    source_label: str,
    rows: list[ParsedRow],
) -> ImportPlan:
    """构建导入计划（不写库）：批内去重、既有匹配、跨级冲突提示。

    匹配口径：(headword, level, 规范化释义)。
    - 批内同键 → duplicate_in_file（来源将合并）
    - 批内同 (headword, level) 不同释义 → 同形异义，各成一行
    - 与库中同键 → merge（来源追加，空位补齐）
    - headword 存在于其他级别 → cross_level_conflict 提示（不阻断：
      实际难度自动取更早一级）
    """
    plan = ImportPlan()
    seen_batch: dict[str, ParsedRow] = {}
    batch_entries: list[tuple[ParsedRow, VocabularyLevelEntry]] = []
    headwords = {row.headword for row in rows}

    # 库中既有：同 headword 的本级别行 + 其他级别行（跨级冲突用）
    existing_same_level: dict[tuple[str, str], VocabularyLevelEntry] = {}
    other_levels: dict[str, set[str]] = {}
    if headwords:
        for entry in session.exec(
            select(VocabularyLevelEntry).where(
                col(VocabularyLevelEntry.headword).in_(list(headwords)),  # type: ignore[operator]
                VocabularyLevelEntry.status == "active",
            )
        ).all():
            if entry.level == level:
                existing_same_level[
                    (entry.headword, _meaning_key(entry.meaning_zh))
                ] = entry
            else:
                other_levels.setdefault(entry.headword, set()).add(entry.level)

    for row in rows:
        source = f"{source_label}" if source_label else "未命名来源"
        existing = existing_same_level.get((row.headword, _meaning_key(row.meaning_zh)))
        if existing is not None:
            plan.merge_count += 1
            plan.merges.append((existing, [source], row.part_of_speech, row.meaning_zh))
            if row.headword in seen_batch:
                plan.duplicates_in_file.append(
                    VocabularyLevelImportIssue(
                        kind="duplicate_in_file",
                        line=row.line,
                        headword=row.headword,
                        reason=f"与第 {seen_batch[row.headword].line} 行重复（同词同释义），来源将合并",
                    )
                )
            continue
        if row.headword in seen_batch:
            # 同词不同释义：同形异义，各成一行（不是重复）
            plan.duplicates_in_file.append(
                VocabularyLevelImportIssue(
                    kind="duplicate_in_file",
                    line=row.line,
                    headword=row.headword,
                    reason=f"与第 {seen_batch[row.headword].line} 行同词不同释义，按同形异义各自成行",
                )
            )
        seen_batch.setdefault(row.headword, row)
        if row.headword in other_levels:
            easier = min(
                other_levels[row.headword] | {level}, key=VOCAB_LEVEL_ORDER.index
            )
            plan.cross_level_conflicts.append(
                VocabularyLevelImportIssue(
                    kind="cross_level_conflict",
                    line=row.line,
                    headword=row.headword,
                    reason="该词已存在于其他级别，实际难度将取最早（最易）一级",
                    existing_level=easier if easier != level else None,
                )
            )
        sense_no = _next_sense_no(
            [
                entry
                for key, entry in existing_same_level.items()
                if key[0] == row.headword
            ]
        )
        entry = VocabularyLevelEntry(
            headword=row.headword,
            level=level,
            sense_no=sense_no,
            part_of_speech=row.part_of_speech,
            meaning_zh=row.meaning_zh,
            is_phrase=" " in row.headword,
            sources=[source],
        )
        batch_entries.append((row, entry))

    # 批内同 (headword, level) 多义：sense_no 在新建行之间也要错开
    sense_counter: dict[str, int] = {}
    for _row, entry in batch_entries:
        if entry.sense_no == 1 and entry.headword in sense_counter:
            sense_counter[entry.headword] += 1
            entry.sense_no = sense_counter[entry.headword]
        else:
            sense_counter.setdefault(entry.headword, entry.sense_no)
    plan.new_entries = [entry for _row, entry in batch_entries]
    plan.new_count = len(plan.new_entries)
    return plan


def _meaning_key(meaning: str | None) -> str:
    return normalize_spelling(meaning or "")


def _next_sense_no(existing_entries: list[VocabularyLevelEntry]) -> int:
    return max((entry.sense_no for entry in existing_entries), default=0) + 1


def preview_import(
    session: Session,
    level: str,
    source_label: str,
    rows: list[ParsedRow],
) -> VocabularyLevelImportPreview:
    validate_level(level)
    valid, invalid = _validate_rows(rows)
    plan = plan_import(session, level, source_label, valid)
    counts_after = level_counts(session)
    for count in counts_after:
        if count.level == level:
            count.entry_count += plan.new_count
    return VocabularyLevelImportPreview(
        level=level,
        source_label=source_label,
        valid_rows=[
            VocabularyWordIn(
                headword=row.headword,
                part_of_speech=row.part_of_speech,
                meaning_zh=row.meaning_zh or "",
            )
            for row in valid
        ],
        invalid=invalid,
        duplicates_in_file=plan.duplicates_in_file[:50],
        cross_level_conflicts=plan.cross_level_conflicts[:50],
        new_count=plan.new_count,
        merge_count=plan.merge_count,
        counts_after=counts_after,
    )


def _commit(session: Session) -> None:
    """小封装便于测试注入失败验证回滚。"""
    session.commit()


def apply_import(
    session: Session,
    level: str,
    source_label: str,
    rows: list[ParsedRow],
) -> tuple[int, int, int]:
    """事务性导入：全部成功才提交，任何异常整体回滚。返回 (新增, 合并, 跳过)。"""
    validate_level(level)
    valid, invalid = _validate_rows(rows)
    plan = plan_import(session, level, source_label, valid)
    try:
        for entry in plan.new_entries:
            session.add(entry)
        for existing, sources, pos, meaning in plan.merges:
            for source in sources:
                if source not in (existing.sources or []):
                    existing.sources = list(existing.sources or []) + [source]
            if not existing.part_of_speech and pos:
                existing.part_of_speech = pos
            if not existing.meaning_zh and meaning:
                existing.meaning_zh = meaning
        _commit(session)
    except Exception:
        session.rollback()
        raise
    return plan.new_count, plan.merge_count, len(invalid)


def level_counts(session: Session) -> list[VocabularyLevelLevelCount]:
    rows = session.exec(
        select(
            VocabularyLevelEntry.level,
            func.count(),
            func.sum(sa.cast(col(VocabularyLevelEntry.is_phrase), sa.Integer)),
            func.sum(sa.cast(col(VocabularyLevelEntry.needs_review), sa.Integer)),
        )
        .where(VocabularyLevelEntry.status == "active")
        .group_by(VocabularyLevelEntry.level)  # type: ignore[arg-type]
    ).all()
    by_level = {row[0]: row for row in rows}
    counts = []
    for level in VOCAB_LEVEL_ORDER:
        row = by_level.get(level)
        counts.append(
            VocabularyLevelLevelCount(
                level=level,
                entry_count=int(row[1]) if row else 0,
                phrase_count=int(row[2] or 0) if row else 0,
                needs_review_count=int(row[3] or 0) if row else 0,
            )
        )
    return counts


def level_stats(session: Session) -> VocabularyLevelStats:
    counts = level_counts(session)
    source_rows = session.exec(select(VocabularyLevelEntry.sources)).all()
    sources: set[str] = set()
    for source_list in source_rows:
        sources.update(source_list or [])
    return VocabularyLevelStats(
        levels=counts,
        total_entries=sum(count.entry_count for count in counts),
        total_sources=len(sources),
    )


def effective_level_map(
    session: Session, headwords: list[str]
) -> dict[str, tuple[str, list[str]]]:
    """headword → (实际难度=最早一级, 全部级别)。供两个模块共用。"""
    if not headwords:
        return {}
    normalized = sorted({normalize_spelling(word) for word in headwords if word})
    levels_by_word: dict[str, list[str]] = {}
    for entry in session.exec(
        select(VocabularyLevelEntry.headword, VocabularyLevelEntry.level).where(
            col(VocabularyLevelEntry.headword).in_(normalized),  # type: ignore[operator]
            VocabularyLevelEntry.status == "active",
            VocabularyLevelEntry.needs_review.is_(False),  # type: ignore[union-attr]  # ty: ignore[unresolved-attribute]
        )
    ).all():
        levels_by_word.setdefault(entry[0], []).append(entry[1])
    result: dict[str, tuple[str, list[str]]] = {}
    for headword, levels in levels_by_word.items():
        effective = effective_vocab_level(levels)
        if effective is not None:
            result[headword] = (
                effective,
                sorted(set(levels), key=VOCAB_LEVEL_ORDER.index),
            )
    return result


def entry_public(entry: VocabularyLevelEntry) -> VocabularyLevelEntryPublic:
    return VocabularyLevelEntryPublic(
        id=entry.id,
        headword=entry.headword,
        level=entry.level,
        sense_no=entry.sense_no,
        part_of_speech=entry.part_of_speech,
        meaning_zh=entry.meaning_zh,
        is_phrase=entry.is_phrase,
        needs_review=entry.needs_review,
        note=entry.note,
        sources=entry.sources or [],
        status=entry.status,
    )


def get_entry(session: Session, entry_id: uuid.UUID) -> VocabularyLevelEntry:
    entry = session.get(VocabularyLevelEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="词条不存在")
    return entry


def attach_word_levels(
    session: Session, words: list[VocabularyWord]
) -> list[VocabularyWordPublic]:
    """背单词词条 → 附加五级归属（实际难度 + 全部级别）。两模块共用同一数据源。"""
    level_map = effective_level_map(session, [word.headword for word in words])
    out: list[VocabularyWordPublic] = []
    for word in words:
        info = level_map.get(normalize_spelling(word.headword))
        out.append(
            VocabularyWordPublic(
                id=word.id,
                headword=word.headword,
                part_of_speech=word.part_of_speech,
                meaning_zh=word.meaning_zh,
                meaning_en=word.meaning_en,
                accepted_spellings=word.accepted_spellings,
                example_en=word.example_en,
                audio_url=word.audio_url,
                status=word.status,
                level=info[0] if info else None,
                all_levels=info[1] if info else [],
            )
        )
    return out
