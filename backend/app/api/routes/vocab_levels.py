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
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Field, Session, SQLModel, col, select

from app.api.deps import (
    PlatformOperatorDep,
    PlatformSessionDep,
    SessionDep,
    TeacherUserDep,
)
from app.api.routes.classes import _require_classroom_teacher
from app.api.routes.vocabulary_shared import _book_public
from app.models import (
    Classroom,
    User,
    VocabularyBook,
    VocabularyBookDetail,
    VocabularyBookItem,
    VocabularyLevelEntry,
    VocabularyLevelEntryPublic,
    VocabularyLevelEntryUpdate,
    VocabularyLevelImportPreview,
    VocabularyLevelImportResult,
    VocabularyLevelStats,
    VocabularyWord,
    VocabularyWordIn,
    VocabularyWordPublic,
)
from app.services import vocab_levels as levels_service
from app.services.vocabulary import (
    _create_word,
    normalize_spelling,
)
from app.services.vocabulary import (
    get_book_or_404 as _get_book,
)
from app.services.vocabulary import (
    require_book_editor as _require_book_editor,
)

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
def vocab_level_stats(
    session: PlatformSessionDep, _operator: PlatformOperatorDep
) -> Any:
    """各级数量、词组数、待人工核对数与来源统计。"""
    return levels_service.level_stats(session)


@router.post(
    "/admin/vocab-levels/import-preview", response_model=VocabularyLevelImportPreview
)
async def vocab_level_import_preview(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    file: UploadFile,
    level: str = Form(...),
    source_label: str = Form(...),
) -> Any:
    """分级导入预览：解析、无效行、批内重复、跨级冲突与导入后各级数量。"""
    text = await _read_upload(file)
    # 解析（5MB/2 万行 CPU 级）与库内比对都放线程池：async 路由里同步跑会
    # 卡住整个事件循环，导入期间学生端所有请求无响应
    return await run_in_threadpool(
        levels_service.preview_import,
        session,
        level,
        source_label.strip() or "未命名来源",
        await run_in_threadpool(levels_service.parse_upload, text),
    )


@router.post(
    "/admin/vocab-levels/import-confirm", response_model=VocabularyLevelImportResult
)
async def vocab_level_import_confirm(
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
    file: UploadFile,
    level: str = Form(...),
    source_label: str = Form(...),
) -> Any:
    """确认导入：单事务，任何失败整体回滚。"""
    text = await _read_upload(file)
    imported_new, merged_existing, skipped = await run_in_threadpool(
        levels_service.apply_import,
        session,
        level,
        source_label.strip() or "未命名来源",
        await run_in_threadpool(levels_service.parse_upload, text),
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
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
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
    session: PlatformSessionDep,
    _operator: PlatformOperatorDep,
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


def _visible_book_ids(session: Session, current_user: User) -> list[uuid.UUID] | None:
    """当前教师可见的词库 id（本校公共库或本人班级库）；管理员=本校全部。

    多租户：谓词始终带本校过滤——他校词库在 RLS 激活环境本就不可见，
    这里是无 RLS 环境的应用层等价防线（CLAUDE.md 不变量④）。
    """
    conditions = [VocabularyBook.tenant_id == current_user.tenant_id]
    if current_user.role != "school_admin":
        conditions.append(
            (VocabularyBook.scope == "public")  # type: ignore[union-attr]
            | (VocabularyBook.owner_id == current_user.id)  # type: ignore[operator]
        )
    rows = session.exec(select(VocabularyBook.id).where(*conditions)).all()
    return list(rows)


@router.get("/vocabulary/words", response_model=list[VocabularyWordPublic])
def list_teaching_words_by_level(
    session: SessionDep,
    current_user: TeacherUserDep,
    level: str = Query(...),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """背单词模块按实际难度选教学词条（含五级归属信息）。

    可见性：只返回当前教师可见词库（公共库或本人班级库；管理员全看）中的
    词条——防止借级别查询读到其他教师班级词库的词头与释义。只返回有教学
    释义且已启用、且词头命中五级数据源（不含待核对行）的词条；实际难度 =
    该词全部级别中最早（最易）一级。先过滤后分页，避免漏词/空页。

    性能：先取候选词头（单列）→ 五级映射筛出目标级别词头 → 只取命中词
    的词行分页；避免全量词行 + 全量分级附加后在 Python 过滤切片（词库
    增长后每次请求都是全表扫描 + 大内存）。
    """
    levels_service.validate_level(level)
    visible_ids = _visible_book_ids(session, current_user)
    # 多租户：词行也按本校过滤——同词头的他校词行在 RLS 激活环境不可见，
    # 无 RLS 环境保持同语义（CLAUDE.md 不变量④）
    headword_stmt = select(VocabularyWord.headword).where(
        VocabularyWord.status == "active",
        VocabularyWord.tenant_id == current_user.tenant_id,
    )
    if visible_ids is not None:
        headword_stmt = headword_stmt.join(
            VocabularyBookItem,
            VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
        ).where(
            col(VocabularyBookItem.book_id).in_(visible_ids)  # type: ignore[operator]
        )
    candidate_headwords = set(session.exec(headword_stmt).all())
    level_map = levels_service.effective_level_map(session, list(candidate_headwords))
    matched_headwords = {
        raw
        for raw in candidate_headwords
        if level_map.get(normalize_spelling(raw), ("", []))[0] == level
    }
    stmt = (
        select(VocabularyWord)
        .where(
            VocabularyWord.status == "active",
            VocabularyWord.tenant_id == current_user.tenant_id,
            col(VocabularyWord.headword).in_(matched_headwords),  # type: ignore[operator]
        )
        .order_by(col(VocabularyWord.headword), col(VocabularyWord.id))
        .offset(offset)
        .limit(limit)
    )
    # 单表查询无 join，词行天然不重复，分页直接下推 SQL（原全量取回后
    # Python 去重切片，词库增长后每次都是全量传输）
    page = list(session.exec(stmt).all())
    return levels_service.attach_word_levels(session, page)


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
    # 过滤（实际难度 + 排除已入库）后剩余未导入的候选数：>0 时可继续下一批
    remaining_count: int = 0


def _resolve_import_target(
    session: Session,
    current_user: User,
    body: VocabularyFromLevelsRequest,
) -> VocabularyBook:
    """解析已有词库，或按课堂新建一个班级词库。"""
    if body.book_id is not None:
        book = _get_book(session, body.book_id)
        _require_book_editor(book, current_user)
        if book.status != "active":
            raise HTTPException(status_code=422, detail="词库已归档，不能继续加词")
        return book
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
    return book


def _entry_headword_map(
    session: Session, level: str
) -> dict[str, VocabularyLevelEntry]:
    """该级别 active + 已核对 + 有释义的词条，按词头取第一条释义。"""
    entries = session.exec(
        select(VocabularyLevelEntry)
        .where(
            VocabularyLevelEntry.level == level,  # type: ignore[arg-type]
            VocabularyLevelEntry.status == "active",
            VocabularyLevelEntry.needs_review == False,  # noqa: E712
            col(VocabularyLevelEntry.meaning_zh).is_not(None),  # type: ignore[union-attr]
            col(VocabularyLevelEntry.meaning_zh) != "",  # type: ignore[union-attr]
        )
        .order_by(
            col(VocabularyLevelEntry.headword), col(VocabularyLevelEntry.sense_no)
        )
    ).all()
    first_by_headword: dict[str, VocabularyLevelEntry] = {}
    for entry in entries:
        first_by_headword.setdefault(entry.headword, entry)
    return first_by_headword


def _effective_headwords(
    session: Session,
    first_by_headword: dict[str, VocabularyLevelEntry],
    level: str,
) -> list[str]:
    """只保留「实际难度（最易级）恰好等于所选级别」的词头。"""
    effective = levels_service.effective_level_map(
        session, list(first_by_headword.keys())
    )
    return [
        headword
        for headword in first_by_headword
        if effective.get(headword, ("", []))[0] == level
    ]


def _book_headwords(session: Session, book_id: uuid.UUID) -> set[str]:
    """目标词库已有词头（归一化后）。"""
    return {
        normalize_spelling(word.headword)
        for word in session.exec(
            select(VocabularyWord)
            .join(
                VocabularyBookItem,
                VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
            )
            .where(VocabularyBookItem.book_id == book_id)  # type: ignore[arg-type]
        ).all()
    }


def _next_position(session: Session, book_id: uuid.UUID) -> int:
    """书内下一个可用序号。"""
    position = session.exec(
        select(VocabularyBookItem.position)
        .where(VocabularyBookItem.book_id == book_id)  # type: ignore[arg-type]
        .order_by(col(VocabularyBookItem.position).desc())
    ).first()
    return (position or 0) + 1


def _create_level_words(
    session: Session,
    book: VocabularyBook,
    headwords: list[str],
    entries: dict[str, VocabularyLevelEntry],
    position: int,
) -> int:
    """逐词建教学词条并挂到书上，返回新建数量。"""
    created = 0
    for headword in headwords:
        entry = entries[headword]
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
    return created


def _book_word_rows(session: Session, book_id: uuid.UUID) -> list[VocabularyWord]:
    """书内全部词条，按书内序号排。"""
    return list(
        session.exec(
            select(VocabularyWord)
            .join(
                VocabularyBookItem,
                VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
            )
            .where(VocabularyBookItem.book_id == book_id)  # type: ignore[arg-type]
            .order_by(col(VocabularyBookItem.position))
        ).all()
    )


@router.post("/vocabulary/words/from-levels", response_model=VocabularyFromLevelsResult)
def import_words_from_levels(
    session: SessionDep,
    current_user: TeacherUserDep,
    body: VocabularyFromLevelsRequest,
) -> Any:
    """教师把五级词库中**已核对且有释义**的词条转为教学词条并入词库。

    口径：
    - **按实际难度筛选**：只转入「实际难度（最易级）恰好为所选级别」的词条，
      与教师词库按级别筛选的口径一致（来源级别 ≠ 实际难度）；
    - **先排除目标词库已有词，再限量**：重复调用按 offset 续导不会卡在同一批；
    - 未核对（needs_review）或缺释义的分级词条跳过；
    - 生成的教学词条与既有发布流程一致（按 word_ids 发布 → 快照），快照语义不变。
    """
    levels_service.validate_level(body.level)
    book = _resolve_import_target(session, current_user, body)

    first_by_headword = _entry_headword_map(session, body.level)
    candidates = _effective_headwords(session, first_by_headword, body.level)

    # 先排除目标词库已有词，再分页（重复调用按 offset 续导）
    existing_headwords = _book_headwords(session, book.id)
    remaining = [
        headword
        for headword in sorted(candidates)
        if headword not in existing_headwords
    ]
    page_headwords = remaining[: body.limit]

    created = _create_level_words(
        session,
        book,
        page_headwords,
        first_by_headword,
        _next_position(session, book.id),
    )
    skipped_existing = len(candidates) - len(remaining)
    if created:
        book.version += 1
        session.add(book)
    session.commit()
    session.refresh(book)

    items = _book_word_rows(session, book.id)
    return VocabularyFromLevelsResult(
        **_book_public(book, len(items)).model_dump(),
        words=levels_service.attach_word_levels(session, list(items)),
        created_count=created,
        skipped_existing=skipped_existing,
        remaining_count=max(0, len(remaining) - created),
    )
