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
import re
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
    needs_review: bool = False
    sources: list[str] = field(default_factory=list)  # 行级来源（如场景/章节/天）
    note: str | None = None
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
            elif name in ("needs_review", "待核对", "待人工核对"):
                col_map.setdefault("needs_review", idx)
            elif name in ("sources", "来源"):
                col_map.setdefault("sources", idx)
            elif name == "note":
                col_map.setdefault("note", idx)
        if "headword" not in col_map:
            raise HTTPException(
                status_code=422,
                detail="CSV 需要表头：headword[,part_of_speech][,meaning_zh][,needs_review][,sources]",
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
        needs_review = (
            cells[col_map["needs_review"]].strip().casefold()
            in ("true", "1", "yes", "是")
            if "needs_review" in col_map and col_map["needs_review"] < len(cells)
            else False
        )
        row_sources = (
            [
                part.strip()
                for part in re.split(r"[;；]", cells[col_map["sources"]])
                if part.strip()
            ]
            if "sources" in col_map and col_map["sources"] < len(cells)
            else []
        )
        note = (
            cells[col_map["note"]].strip()
            if "note" in col_map and col_map["note"] < len(cells)
            else ""
        )
        # 安全默认：缺释义的行强制待核对（不参与两模块统计，人工核对后才生效）
        rows.append(
            ParsedRow(
                headword=normalize_spelling(headword_raw),
                part_of_speech=pos or None,
                meaning_zh=meaning or None,
                needs_review=needs_review or not meaning,
                sources=row_sources,
                note=note or None,
                line=line_no,
            )
        )
    return rows


def _validate_rows(
    rows: list[ParsedRow],
) -> tuple[list[ParsedRow], list[VocabularyLevelImportIssue]]:
    """结构有效性：headword 必须是拉丁词形（词/词组），长度 ≤64。"""
    # 允许词内数字（如 b2/OCR 噪声），首字符必须是字母
    valid_re = re.compile(r"^[a-zA-Z][a-zA-Z0-9'\-]*(?: [a-zA-Z0-9][a-zA-Z0-9'\-]*)*$")
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


def _meaning_key(meaning: str | None) -> str:
    return normalize_spelling(meaning or "")


@dataclass
class _BatchGroup:
    """批内聚合组：同 (headword, 规范化释义) 的行合并来源后再与库比对。"""

    headword: str
    meaning_key: str
    meaning_zh: str | None
    part_of_speech: str | None
    needs_review: bool
    note: str | None
    sources: list[str]
    first_line: int
    lines: list[int]


def plan_import(
    session: Session,
    level: str,
    source_label: str,
    rows: list[ParsedRow],
) -> ImportPlan:
    """构建导入计划（不写库）。

    聚合与匹配口径：
    1. 批内先按 (headword, 规范化释义) 聚合——同键重复合并来源（duplicate_in_file
       提示）；同词不同释义 = 同形异义，各成一组；
    2. 每组与库中 (headword, level, 规范化释义) 匹配：命中 → merge（来源追加、
       空位补齐）；未命中 → 新建行，sense_no 按「库中该词头已有最大 sense_no +
       批内顺序」连续分配（绝不撞 uq_vocab_level_sense）；
    3. headword 存在于其他级别 → cross_level_conflict 提示（不阻断，实际难度
       自动取更早一级）。
    """
    plan = ImportPlan()

    # 1) 批内聚合（保持首次出现顺序）
    groups: dict[tuple[str, str], _BatchGroup] = {}
    group_order: list[tuple[str, str]] = []
    first_line_by_headword: dict[str, int] = {}
    for row in rows:
        key = (row.headword, _meaning_key(row.meaning_zh))
        group = groups.get(key)
        # 行级来源（工具产物带 sources 列）优先；为空才用 source_label 兜底
        row_sources = list(row.sources) or (
            [source_label] if source_label else ["未命名来源"]
        )
        if group is None:
            groups[key] = _BatchGroup(
                headword=row.headword,
                meaning_key=key[1],
                meaning_zh=row.meaning_zh,
                part_of_speech=row.part_of_speech,
                needs_review=row.needs_review,
                note=row.note,
                sources=row_sources,
                first_line=row.line,
                lines=[row.line],
            )
            group_order.append(key)
        else:
            group.lines.append(row.line)
            for source in row_sources:
                if source not in group.sources:
                    group.sources.append(source)
            group.needs_review = group.needs_review or row.needs_review
            if not group.part_of_speech and row.part_of_speech:
                group.part_of_speech = row.part_of_speech
            if not group.note and row.note:
                group.note = row.note
        if row.headword not in first_line_by_headword:
            first_line_by_headword[row.headword] = row.line

    # 批内重复/同形异义提示
    headword_groups: dict[str, list[_BatchGroup]] = {}
    for key in group_order:
        headword_groups.setdefault(key[0], []).append(groups[key])
    for headword, word_groups in headword_groups.items():
        if len(word_groups) > 1:
            # 同词多组：每组与第一组互为「同词不同释义」
            first = word_groups[0]
            for group in word_groups[1:]:
                plan.duplicates_in_file.append(
                    VocabularyLevelImportIssue(
                        kind="duplicate_in_file",
                        line=group.first_line,
                        headword=headword,
                        reason=f"与第 {first.first_line} 行同词不同释义，按同形异义各自成行",
                    )
                )
        for group in word_groups:
            if len(group.lines) > 1:
                plan.duplicates_in_file.append(
                    VocabularyLevelImportIssue(
                        kind="duplicate_in_file",
                        line=group.lines[1],
                        headword=headword,
                        reason=f"与第 {group.lines[0]} 行重复（同词同释义），来源将合并",
                    )
                )

    # 2) 库中既有行（含归档：sense_no 的唯一约束覆盖全部状态，
    #    分配新序号必须计入归档行，否则重新导入会同号撞约束）
    headwords = list(headword_groups.keys())
    existing_same_level: dict[tuple[str, str], VocabularyLevelEntry] = {}
    existing_sense_max: dict[str, int] = {}
    other_levels: dict[str, set[str]] = {}
    if headwords:
        for entry in session.exec(
            select(VocabularyLevelEntry).where(
                col(VocabularyLevelEntry.headword).in_(headwords),  # type: ignore[operator]
            )
        ).all():
            if entry.level == level:
                existing_sense_max[entry.headword] = max(
                    existing_sense_max.get(entry.headword, 0), entry.sense_no
                )
                if entry.status == "active":
                    existing_same_level[
                        (entry.headword, _meaning_key(entry.meaning_zh))
                    ] = entry
            else:
                other_levels.setdefault(entry.headword, set()).add(entry.level)

    # 3) 逐组生成计划：merge 或新建（sense_no 连续分配）
    for key in group_order:
        group = groups[key]
        existing = existing_same_level.get(key)
        if existing is not None:
            plan.merge_count += 1
            plan.merges.append(
                (
                    existing,
                    list(group.sources) if group.sources else [],
                    group.part_of_speech,
                    group.meaning_zh,
                )
            )
            continue

        headword = group.headword
        if headword in other_levels:
            easier = min(other_levels[headword] | {level}, key=VOCAB_LEVEL_ORDER.index)
            plan.cross_level_conflicts.append(
                VocabularyLevelImportIssue(
                    kind="cross_level_conflict",
                    line=group.first_line,
                    headword=headword,
                    reason="该词已存在于其他级别，实际难度将取最早（最易）一级",
                    existing_level=easier if easier != level else None,
                )
            )
        new_sense_no = existing_sense_max.get(headword, 0) + 1
        existing_sense_max[headword] = new_sense_no
        sources = group.sources or ([source_label] if source_label else ["未命名来源"])
        plan.new_entries.append(
            VocabularyLevelEntry(
                headword=headword,
                level=level,
                sense_no=new_sense_no,
                part_of_speech=group.part_of_speech,
                meaning_zh=group.meaning_zh,
                # 安全默认：缺释义的行强制待核对（不参与两模块统计）
                needs_review=group.needs_review or not group.meaning_zh,
                is_phrase=" " in headword,
                note=group.note,
                sources=sources,
            )
        )

    plan.new_count = len(plan.new_entries)
    return plan


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
            for source in sources or []:
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
            col(VocabularyLevelEntry.meaning_zh).is_not(None),  # type: ignore[union-attr]
            col(VocabularyLevelEntry.meaning_zh) != "",  # type: ignore[union-attr]
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
