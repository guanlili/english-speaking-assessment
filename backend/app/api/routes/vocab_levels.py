"""五级词库接口（KET/PET/学术/四级/雅思&托福 共用分级数据源）。

    /admin/vocab-levels/stats          各级数量与来源统计（管理员）
    /admin/vocab-levels/import-preview 分级导入预览（无效/重复/跨级冲突提示）
    /admin/vocab-levels/import-confirm 确认导入（单事务，失败整体回滚）
    /admin/vocab-levels/entries        词条浏览（needs_review 人工核对过滤）
    /admin/vocab-levels/entries/{id}   人工核对修正（释义/词性/核对标记）
    /vocabulary/words                  背单词模块按实际难度选教学词条（教师）

版权口径：学校资料未确认线上使用授权前不得导入生产库；导入只写
vocab_level_entry，已发布任务快照与历史 A2/B1/B2 结果不受影响。
401 只表示登录失效；权限不足一律 403。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile
from sqlmodel import Field, SQLModel, col, select

from app.api.deps import SessionDep, SuperUserDep, TeacherUserDep
from app.api.routes.classes import _require_classroom_teacher
from app.api.routes.vocabulary import (
    VocabularyWordIn,
    _book_public,
    _create_word,
    _get_book,
    _require_book_editor,
)
from app.models import (
    Classroom,
    VocabularyBookDetail,
    VocabularyLevelEntry,
    VocabularyLevelEntryPublic,
    VocabularyLevelEntryUpdate,
    VocabularyLevelImportPreview,
    VocabularyLevelImportResult,
    VocabularyLevelStats,
    VocabularyWord,
    VocabularyWordPublic,
)
from app.services import vocab_levels as levels_service
from app.services.vocabulary import normalize_spelling

router = APIRouter(tags=["vocab-levels"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


async def _read_upload(file: UploadFile) -> str:
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 5MB 上限")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="文件必须是 UTF-8 编码") from exc


@router.get("/admin/vocab-levels/stats", response_model=VocabularyLevelStats)
def vocab_level_stats(session: SessionDep, _admin: SuperUserDep) -> Any:
    """各级数量、词组数、待人工核对数与来源统计。"""
    return levels_service.level_stats(session)


@router.post(
    "/admin/vocab-levels/import-preview", response_model=VocabularyLevelImportPreview
)
async def vocab_level_import_preview(
    session: SessionDep,
    _admin: SuperUserDep,
    file: UploadFile,
    level: str = Form(...),
    source_label: str = Form(...),
) -> Any:
    """分级导入预览：解析、无效行、批内重复、跨级冲突与导入后各级数量。"""
    text = await _read_upload(file)
    rows = levels_service.parse_upload(text)
    return levels_service.preview_import(
        session, level, source_label.strip() or "未命名来源", rows
    )


@router.post(
    "/admin/vocab-levels/import-confirm", response_model=VocabularyLevelImportResult
)
async def vocab_level_import_confirm(
    session: SessionDep,
    _admin: SuperUserDep,
    file: UploadFile,
    level: str = Form(...),
    source_label: str = Form(...),
) -> Any:
    """确认导入：单事务，任何失败整体回滚。"""
    text = await _read_upload(file)
    rows = levels_service.parse_upload(text)
    imported_new, merged_existing, skipped = levels_service.apply_import(
        session, level, source_label.strip() or "未命名来源", rows
    )
    return VocabularyLevelImportResult(
        imported_new=imported_new,
        merged_existing=merged_existing,
        skipped_invalid=skipped,
        counts=levels_service.level_counts(session),
    )


@router.get(
    "/admin/vocab-levels/entries", response_model=list[VocabularyLevelEntryPublic]
)
def list_vocab_level_entries(
    session: SessionDep,
    _admin: SuperUserDep,
    level: str | None = Query(default=None),
    needs_review: bool | None = Query(default=None),
    headword: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """词条浏览：人工核对工作流按 needs_review / level / 词头过滤。"""
    if level is not None:
        levels_service.validate_level(level)
    stmt = select(VocabularyLevelEntry).order_by(
        col(VocabularyLevelEntry.headword),
        col(VocabularyLevelEntry.sense_no),
    )
    if level is not None:
        stmt = stmt.where(VocabularyLevelEntry.level == level)  # type: ignore[arg-type]
    if needs_review is not None:
        stmt = stmt.where(VocabularyLevelEntry.needs_review == needs_review)  # type: ignore[arg-type,union-attr]
    if headword is not None:
        stmt = stmt.where(
            VocabularyLevelEntry.headword == normalize_spelling(headword)  # type: ignore[arg-type]
        )
    entries = session.exec(stmt.offset(offset).limit(limit)).all()
    return [levels_service.entry_public(entry) for entry in entries]


@router.patch(
    "/admin/vocab-levels/entries/{entry_id}",
    response_model=VocabularyLevelEntryPublic,
)
def update_vocab_level_entry(
    session: SessionDep,
    _admin: SuperUserDep,
    entry_id: uuid.UUID,
    entry_in: VocabularyLevelEntryUpdate,
) -> Any:
    """人工核对修正：补释义/词性、标记核对完成或归档。"""
    entry = levels_service.get_entry(session, entry_id)
    update = entry_in.model_dump(exclude_unset=True)
    if "part_of_speech" in update:
        entry.part_of_speech = (update["part_of_speech"] or "").strip() or None
    if "meaning_zh" in update:
        entry.meaning_zh = (update["meaning_zh"] or "").strip() or None
    if "note" in update:
        entry.note = (update["note"] or "").strip() or None
    if update.get("needs_review") is not None:
        if not update["needs_review"] and not (entry.meaning_zh or "").strip():
            raise HTTPException(
                status_code=422,
                detail="释义为空时不能标记已核对：请先补录中文释义",
            )
        entry.needs_review = update["needs_review"]
    if update.get("status") is not None:
        if update["status"] not in {"active", "archived"}:
            raise HTTPException(status_code=422, detail="状态只能是 active/archived")
        entry.status = update["status"]
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return levels_service.entry_public(entry)


@router.get("/vocabulary/words", response_model=list[VocabularyWordPublic])
def list_teaching_words_by_level(
    session: SessionDep,
    current_user: TeacherUserDep,  # noqa: ARG001 — 权限门（教师/管理员可读），本体不用用户对象
    level: str = Query(...),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """背单词模块按实际难度选教学词条（含五级归属信息）。

    只返回有教学释义且已启用、且词头命中五级数据源（不含待核对行）的词条；
    实际难度 = 该词全部级别中最早（最易）一级。
    """
    levels_service.validate_level(level)
    # 先全量附加级别再过滤，最后分页——避免「先截取后过滤」漏词/空页
    words = session.exec(
        select(VocabularyWord)
        .where(VocabularyWord.status == "active")
        .order_by(col(VocabularyWord.headword))
    ).all()
    matched = levels_service.attach_word_levels(session, list(words))
    matched = [word for word in matched if word.level == level]
    return matched[offset : offset + limit]


class VocabularyFromLevelsRequest(SQLModel):
    """从五级词库导入教学词条到词库（仅已核对、有释义的词条）。"""

    level: str
    book_id: uuid.UUID | None = None  # 省略则新建班级词库（需 classroom_id）
    classroom_id: uuid.UUID | None = None
    new_book_title: str | None = Field(default=None, max_length=255)
    limit: int = Field(default=200, ge=1, le=500)


class VocabularyFromLevelsResult(VocabularyBookDetail):
    """建库/并库结果 + 本次从分级库转入的统计。"""

    created_count: int = 0
    skipped_existing: int = 0


@router.post("/vocabulary/words/from-levels", response_model=VocabularyFromLevelsResult)
def import_words_from_levels(
    session: SessionDep,
    current_user: TeacherUserDep,
    body: VocabularyFromLevelsRequest,
) -> Any:
    """教师把五级词库中**已核对且有释义**的词条转为教学词条并入词库。

    - 已有同词头教学词条：跳过（不重复建词）；
    - 未核对（needs_review）或缺释义的分级词条：跳过并在结果中说明；
    - 生成的教学词条与既有发布流程一致（按 word_ids 发布 → 快照），快照语义不变。
    """
    from app.models import (
        VocabularyBook,
        VocabularyBookItem,
    )

    levels_service.validate_level(body.level)
    if body.book_id is not None:
        book = _get_book(session, body.book_id)
        _require_book_editor(book, current_user)
    else:
        if body.classroom_id is None:
            raise HTTPException(
                status_code=422,
                detail="需要指定已有词库（book_id）或课堂（classroom_id）新建",
            )
        classroom = session.get(Classroom, body.classroom_id)
        if classroom is None:
            raise HTTPException(status_code=404, detail="课堂不存在")
        _require_classroom_teacher(classroom, current_user)
        book = VocabularyBook(
            title=(body.new_book_title or "").strip() or f"五级词库 · {body.level}",
            scope="classroom",
            owner_id=current_user.id,
            classroom_id=classroom.id,
        )
        session.add(book)
        session.flush()

    # 已核对且有释义的分级词条（active）
    entries = session.exec(
        select(VocabularyLevelEntry)
        .where(
            VocabularyLevelEntry.level == body.level,  # type: ignore[arg-type]
            VocabularyLevelEntry.status == "active",
            VocabularyLevelEntry.needs_review == False,  # noqa: E712
            col(VocabularyLevelEntry.meaning_zh).is_not(None),  # type: ignore[union-attr]
            col(VocabularyLevelEntry.meaning_zh) != "",  # type: ignore[union-attr]
        )
        .order_by(
            col(VocabularyLevelEntry.headword), col(VocabularyLevelEntry.sense_no)
        )
        .limit(body.limit)
    ).all()

    existing_headwords = {
        normalize_spelling(word.headword)
        for word in session.exec(
            select(VocabularyWord)
            .join(
                VocabularyBookItem,
                VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
            )
            .where(VocabularyBookItem.book_id == book.id)  # type: ignore[arg-type]
        ).all()
    }

    created = 0
    skipped_existing = 0
    position = session.exec(
        select(VocabularyBookItem.position)
        .where(VocabularyBookItem.book_id == book.id)  # type: ignore[arg-type]
        .order_by(col(VocabularyBookItem.position).desc())
    ).first()
    position = (position or 0) + 1
    seen_this_batch: set[str] = set()
    for entry in entries:
        if normalize_spelling(entry.headword) in existing_headwords:
            skipped_existing += 1
            continue
        if entry.headword in seen_this_batch:
            continue  # 同形异义只取第一条释义作教学词条
        seen_this_batch.add(entry.headword)
        word = _create_word(
            session,
            VocabularyWordIn(
                headword=entry.headword,
                part_of_speech=entry.part_of_speech,
                meaning_zh=entry.meaning_zh or "",
            ),
        )
        session.flush()
        session.add(
            VocabularyBookItem(book_id=book.id, word_id=word.id, position=position)
        )
        position += 1
        created += 1
    if created:
        book.version += 1
        session.add(book)
    session.commit()
    session.refresh(book)

    items = session.exec(
        select(VocabularyWord)
        .join(
            VocabularyBookItem,
            VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
        )
        .where(VocabularyBookItem.book_id == book.id)  # type: ignore[arg-type]
        .order_by(col(VocabularyBookItem.position))
    ).all()
    return VocabularyFromLevelsResult(
        **_book_public(book, len(items)).model_dump(),
        words=levels_service.attach_word_levels(session, list(items)),
        created_count=created,
        skipped_existing=skipped_existing,
    )
