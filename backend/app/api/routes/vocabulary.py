"""词汇学习（背单词）模块接口。

    /vocabulary/books                 词库 CRUD + 词库内加词（教师/管理员）
    /vocabulary/books/import-preview  CSV 解析预览（不落库）
    /vocabulary/words/{id}            词条编辑
    /classes/{code}/vocabulary/...    课堂发布 / 学生任务 / 结果 / 错词本
    /vocabulary/sessions/{id}/answers 学生作答（服务端判分）

权限口径（设计文档 §5）：词库编辑/发布 = 课堂所有者教师或管理员；
学生任务仅目标名单内的本班学生；原始作答仅本人与该班教师可读。
401 只表示登录失效；权限不足一律 403。
"""

import csv
import io
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, col, func, select

from app.api.deps import SessionDep, StudentUserDep, TeacherUserDep
from app.api.routes.classes import (
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
)
from app.core.config import settings
from app.models import (
    Classroom,
    Student,
    User,
    VocabularyAnswerRequest,
    VocabularyAnswerResult,
    VocabularyAssignment,
    VocabularyAssignmentCreate,
    VocabularyAssignmentPublic,
    VocabularyBook,
    VocabularyBookCreate,
    VocabularyBookDetail,
    VocabularyBookItem,
    VocabularyBookPublic,
    VocabularyBookUpdate,
    VocabularyClassResults,
    VocabularyImportIssue,
    VocabularyImportPreview,
    VocabularyImportRow,
    VocabularyRoundSummaryRow,
    VocabularySession,
    VocabularySessionCreate,
    VocabularyTeacherAssignmentRow,
    VocabularyTodayItem,
    VocabularyTodayPlan,
    VocabularyWord,
    VocabularyWordIn,
    VocabularyWordPublic,
    VocabularyWordUpdate,
    VocabularyWrongWords,
)
from app.services import vocab_levels as vocab_levels_service
from app.services import vocabulary as vocab_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vocabulary"])

MAX_BOOK_WORDS = 500


# ── 权限与组装辅助 ──────────────────────────────────────────────────


def _word_public(word: VocabularyWord) -> VocabularyWordPublic:
    return VocabularyWordPublic(
        id=word.id,
        headword=word.headword,
        part_of_speech=word.part_of_speech,
        meaning_zh=word.meaning_zh,
        meaning_en=word.meaning_en,
        accepted_spellings=word.accepted_spellings,
        example_en=word.example_en,
        audio_url=word.audio_url,
        status=word.status,
    )


def _book_word_count(
    session: Session, book_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not book_ids:
        return {}
    rows = session.exec(
        select(VocabularyBookItem.book_id, func.count())
        .where(col(VocabularyBookItem.book_id).in_(book_ids))  # type: ignore[operator]
        .group_by(VocabularyBookItem.book_id)  # ty: ignore[invalid-argument-type]
    ).all()
    return dict(rows)


def _book_public(book: VocabularyBook, word_count: int) -> VocabularyBookPublic:
    return VocabularyBookPublic(
        id=book.id,
        title=book.title,
        description=book.description,
        scope=book.scope,
        classroom_id=book.classroom_id,
        owner_id=book.owner_id,
        status=book.status,
        word_count=word_count,
        created_at=book.created_at,
    )


def _assignment_public(assignment: VocabularyAssignment) -> VocabularyAssignmentPublic:
    return vocab_service.assignment_public(assignment)


def _get_book(session: Session, book_id: uuid.UUID) -> VocabularyBook:
    book = session.get(VocabularyBook, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="词库不存在")
    return book


def _require_book_editor(book: VocabularyBook, current_user: User) -> None:
    """词库编辑权：公共词库仅管理员；班级词库为本班教师或管理员。"""
    if current_user.is_superuser:
        return
    if (
        book.scope == "classroom"
        and book.classroom_id is not None
        and book.owner_id == current_user.id
    ):
        return
    raise HTTPException(status_code=403, detail="没有权限编辑这个词库")


def _book_visible(book: VocabularyBook, current_user: User) -> bool:
    if current_user.is_superuser:
        return True
    if book.scope == "public":
        return True
    return book.owner_id == current_user.id


def _create_word(session: Session, word_in: VocabularyWordIn) -> VocabularyWord:
    word = VocabularyWord(
        headword=word_in.headword.strip(),
        part_of_speech=(word_in.part_of_speech or "").strip() or None,
        meaning_zh=word_in.meaning_zh.strip(),
        meaning_en=(word_in.meaning_en or "").strip() or None,
        accepted_spellings=[
            spelling.strip()
            for spelling in (word_in.accepted_spellings or [])
            if spelling.strip()
        ]
        or None,
        example_en=(word_in.example_en or "").strip() or None,
        audio_url=(word_in.audio_url or "").strip() or None,
    )
    session.add(word)
    return word


def _next_position(session: Session, book_id: uuid.UUID) -> int:
    latest = session.exec(
        select(VocabularyBookItem.position)
        .where(VocabularyBookItem.book_id == book_id)
        .order_by(col(VocabularyBookItem.position).desc())
    ).first()
    return (latest or 0) + 1


def _add_words_to_book(
    session: Session, book: VocabularyBook, words_in: list[VocabularyWordIn]
) -> int:
    """词库内加词；同库已收的词（headword+释义一致）跳过。返回新增数。"""
    if not words_in:
        return 0
    if len(words_in) > MAX_BOOK_WORDS:
        raise HTTPException(
            status_code=422, detail=f"单次最多加入 {MAX_BOOK_WORDS} 个词"
        )
    existing_items = session.exec(
        select(VocabularyBookItem.word_id).where(
            VocabularyBookItem.book_id == book.id  # type: ignore[arg-type]
        )
    ).all()
    existing_words = {
        w.id: w
        for w in session.exec(
            select(VocabularyWord).where(
                col(VocabularyWord.id).in_(existing_items or [uuid.uuid4()])
            )  # type: ignore[operator]
        ).all()
    }
    known = {(w.headword.casefold(), w.meaning_zh) for w in existing_words.values()}
    position = _next_position(session, book.id)
    added = 0
    for word_in in words_in:
        key = (word_in.headword.strip().casefold(), word_in.meaning_zh.strip())
        if key in known:
            continue
        known.add(key)
        word = _create_word(session, word_in)
        session.flush()
        session.add(
            VocabularyBookItem(book_id=book.id, word_id=word.id, position=position)
        )
        position += 1
        added += 1
    if added:
        book.version += 1
        session.add(book)
    session.commit()
    return added


# ── CSV 导入预览 ────────────────────────────────────────────────────

IMPORT_HEADERS = [
    "headword",
    "part_of_speech",
    "meaning_zh",
    "meaning_en",
    "accepted_spellings",
    "example_en",
]


async def _read_csv_upload(file: UploadFile) -> str:
    max_bytes = settings.MAX_WORDLIST_CSV_MB * 1024 * 1024
    raw = bytearray()
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"CSV 超过 {settings.MAX_WORDLIST_CSV_MB}MB 上限",
            )
    try:
        return raw.decode("utf-8-sig")  # 兼容 Excel 导出的 BOM
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV 必须是 UTF-8 编码") from exc


def _parse_vocab_csv(text: str) -> VocabularyImportPreview:
    reader = csv.DictReader(io.StringIO(text))
    if (
        not reader.fieldnames
        or "headword" not in reader.fieldnames
        or "meaning_zh" not in reader.fieldnames
    ):
        raise HTTPException(
            status_code=422,
            detail="CSV 需要表头：headword,meaning_zh（第一行，可选 part_of_speech/"
            "meaning_en/accepted_spellings/example_en）",
        )
    rows: list[VocabularyImportRow] = []
    invalid: list[VocabularyImportIssue] = []
    duplicates: list[VocabularyImportIssue] = []
    seen: set[tuple[str, str]] = set()
    for lineno, row in enumerate(reader, start=2):
        headword = (row.get("headword") or "").strip()
        meaning_zh = (row.get("meaning_zh") or "").strip()
        if not headword:
            invalid.append(
                VocabularyImportIssue(line=lineno, reason="缺少单词（headword）")
            )
            continue
        if len(headword) > 64:
            invalid.append(
                VocabularyImportIssue(line=lineno, reason=f"单词超长：{headword[:20]}…")
            )
            continue
        if not meaning_zh:
            invalid.append(
                VocabularyImportIssue(
                    line=lineno, reason=f"{headword} 缺少中文释义（meaning_zh）"
                )
            )
            continue
        key = (headword.casefold(), meaning_zh)
        if key in seen:
            duplicates.append(
                VocabularyImportIssue(line=lineno, reason=f"{headword} 与前文重复")
            )
            continue
        seen.add(key)
        accepted = [
            spelling.strip()
            for spelling in (row.get("accepted_spellings") or "").split("|")
            if spelling.strip()
        ]
        rows.append(
            VocabularyImportRow(
                line=lineno,
                word=VocabularyWordIn(
                    headword=headword,
                    part_of_speech=(row.get("part_of_speech") or "").strip() or None,
                    meaning_zh=meaning_zh,
                    meaning_en=(row.get("meaning_en") or "").strip() or None,
                    accepted_spellings=accepted or None,
                    example_en=(row.get("example_en") or "").strip() or None,
                ),
            )
        )
    return VocabularyImportPreview(rows=rows, invalid=invalid, duplicates=duplicates)


@router.post("/vocabulary/books/import-preview", response_model=VocabularyImportPreview)
async def import_vocab_preview(_teacher: TeacherUserDep, file: UploadFile) -> Any:
    """CSV 导入预览：解析与校验，不写库；确认后在创建词库/加词时提交。"""
    text = await _read_csv_upload(file)
    return await run_in_threadpool(_parse_vocab_csv, text)


# ── 词库 CRUD ──────────────────────────────────────────────────────


@router.get("/vocabulary/books", response_model=list[VocabularyBookPublic])
def list_books(session: SessionDep, current_user: TeacherUserDep) -> Any:
    """词库列表：公共词库全体教师可见；班级词库仅本班教师（管理员全见）。"""
    books = session.exec(
        select(VocabularyBook).order_by(col(VocabularyBook.created_at))
    ).all()
    visible = [b for b in books if _book_visible(b, current_user)]
    counts = _book_word_count(session, [b.id for b in visible])
    return [_book_public(b, counts.get(b.id, 0)) for b in visible]


@router.post("/vocabulary/books", response_model=VocabularyBookDetail)
def create_book(
    session: SessionDep, current_user: TeacherUserDep, book_in: VocabularyBookCreate
) -> Any:
    """创建词库：公共词库仅管理员；班级词库为本班任课教师或管理员。"""
    scope = book_in.scope
    if scope not in {"public", "classroom"}:
        raise HTTPException(
            status_code=422, detail="词库作用域必须是 public 或 classroom"
        )
    if scope == "public" and not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="公共词库由管理员维护，教师可创建班级词库"
        )
    if scope == "classroom":
        if book_in.classroom_id is None:
            raise HTTPException(status_code=422, detail="班级词库需要指定课堂")
        classroom = session.get(Classroom, book_in.classroom_id)
        if classroom is None:
            raise HTTPException(status_code=404, detail="课堂不存在")
        _require_classroom_teacher(classroom, current_user)

    title = book_in.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="词库名称不能为空")
    if len(book_in.words) > MAX_BOOK_WORDS:
        raise HTTPException(
            status_code=422, detail=f"词库一次最多导入 {MAX_BOOK_WORDS} 个词"
        )

    book = VocabularyBook(
        title=title,
        description=(book_in.description or "").strip() or None,
        scope=scope,
        owner_id=current_user.id,
        classroom_id=book_in.classroom_id if scope == "classroom" else None,
    )
    session.add(book)
    session.flush()
    for word_in in book_in.words:
        word = _create_word(session, word_in)
        session.flush()
        session.add(VocabularyBookItem(book_id=book.id, word_id=word.id))
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
    return VocabularyBookDetail(
        **_book_public(book, len(items)).model_dump(),
        words=[_word_public(w) for w in items],
    )


@router.get("/vocabulary/books/{book_id}", response_model=VocabularyBookDetail)
def read_book(
    session: SessionDep,
    current_user: TeacherUserDep,
    book_id: uuid.UUID,
    level: str | None = Query(default=None),
) -> Any:
    """词库详情：词条附五级归属（实际难度/全部级别）；level 传入时按实际难度过滤。

    级别数据来自两模块共用的 vocab_level_entry（不含待核对行）；未命中分级的词 level 为 null。
    """
    if level is not None:
        vocab_levels_service.validate_level(level)
    book = _get_book(session, book_id)
    if not _book_visible(book, current_user):
        raise HTTPException(status_code=403, detail="没有权限查看这个词库")
    items = session.exec(
        select(VocabularyWord)
        .join(
            VocabularyBookItem,
            VocabularyBookItem.word_id == VocabularyWord.id,  # ty: ignore[invalid-argument-type]
        )
        .where(VocabularyBookItem.book_id == book.id)  # type: ignore[arg-type]
        .order_by(col(VocabularyBookItem.position))
    ).all()
    words = vocab_levels_service.attach_word_levels(session, list(items))
    if level is not None:
        words = [word for word in words if word.level == level]
    return VocabularyBookDetail(
        **_book_public(book, len(items)).model_dump(),
        words=words,
    )


@router.patch("/vocabulary/books/{book_id}", response_model=VocabularyBookPublic)
def update_book(
    session: SessionDep,
    current_user: TeacherUserDep,
    book_id: uuid.UUID,
    book_in: VocabularyBookUpdate,
) -> Any:
    book = _get_book(session, book_id)
    _require_book_editor(book, current_user)
    update = book_in.model_dump(exclude_unset=True)
    if "title" in update:
        title = (update["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=422, detail="词库名称不能为空")
        book.title = title
    if "description" in update:
        book.description = (update["description"] or "").strip() or None
    if "status" in update and update["status"] is not None:
        if update["status"] not in {"active", "archived"}:
            raise HTTPException(status_code=422, detail="状态只能是 active/archived")
        book.status = update["status"]
    session.add(book)
    session.commit()
    session.refresh(book)
    counts = _book_word_count(session, [book.id])
    return _book_public(book, counts.get(book.id, 0))


@router.post("/vocabulary/books/{book_id}/words", response_model=VocabularyBookDetail)
def add_book_words(
    session: SessionDep,
    current_user: TeacherUserDep,
    book_id: uuid.UUID,
    words_in: list[VocabularyWordIn],
) -> Any:
    """词库加词（手动录入或导入确认）；重复词跳过并按新增数递增版本。"""
    book = _get_book(session, book_id)
    _require_book_editor(book, current_user)
    if book.status != "active":
        raise HTTPException(status_code=422, detail="词库已归档，不能继续加词")
    if len(words_in) > MAX_BOOK_WORDS:
        raise HTTPException(
            status_code=422, detail=f"单次最多加入 {MAX_BOOK_WORDS} 个词"
        )
    _add_words_to_book(session, book, words_in)
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
    return VocabularyBookDetail(
        **_book_public(book, len(items)).model_dump(),
        words=[_word_public(w) for w in items],
    )


@router.delete("/vocabulary/books/{book_id}/words/{word_id}")
def remove_book_word(
    session: SessionDep,
    current_user: TeacherUserDep,
    book_id: uuid.UUID,
    word_id: uuid.UUID,
) -> Any:
    """从词库移除词条（不改词本身；已发布任务按快照不受影响）。"""
    book = _get_book(session, book_id)
    _require_book_editor(book, current_user)
    item = session.exec(
        select(VocabularyBookItem).where(
            VocabularyBookItem.book_id == book_id,  # type: ignore[arg-type]
            VocabularyBookItem.word_id == word_id,  # type: ignore[arg-type]
        )
    ).first()
    if item is None:
        raise HTTPException(status_code=404, detail="该词不在此词库中")
    session.delete(item)
    book.version += 1
    session.add(book)
    session.commit()
    return {"message": "词条已从词库移除"}


@router.patch("/vocabulary/words/{word_id}", response_model=VocabularyWordPublic)
def update_word(
    session: SessionDep,
    current_user: TeacherUserDep,
    word_id: uuid.UUID,
    word_in: VocabularyWordUpdate,
) -> Any:
    """编辑词条（词库内容版本化更新；历史任务与报告仍按发布快照）。"""
    word = session.get(VocabularyWord, word_id)
    if word is None:
        raise HTTPException(status_code=404, detail="词条不存在")
    # 权限：管理员任意；教师只能改自己班级词库里的词
    if not current_user.is_superuser:
        editable_book = session.exec(
            select(VocabularyBook.id)
            .join(
                VocabularyBookItem,
                VocabularyBookItem.book_id == VocabularyBook.id,  # ty: ignore[invalid-argument-type]
            )
            .where(
                VocabularyBookItem.word_id == word_id,  # type: ignore[arg-type]
                VocabularyBook.scope == "classroom",
                VocabularyBook.owner_id == current_user.id,  # type: ignore[arg-type]
            )
            .limit(1)
        ).first()
        if editable_book is None:
            raise HTTPException(status_code=403, detail="没有权限编辑这个词条")
    update = word_in.model_dump(exclude_unset=True)
    for field in ("part_of_speech", "meaning_en", "example_en", "audio_url"):
        if field in update:
            value = update[field]
            setattr(
                word,
                field,
                (value or "").strip() or None if isinstance(value, str) else value,
            )
    if "meaning_zh" in update and update["meaning_zh"] is not None:
        word.meaning_zh = update["meaning_zh"].strip()
    if "accepted_spellings" in update:
        word.accepted_spellings = [
            s.strip() for s in update["accepted_spellings"] if s and s.strip()
        ] or None
    if "status" in update and update["status"] is not None:
        if update["status"] not in {"active", "archived"}:
            raise HTTPException(status_code=422, detail="状态只能是 active/archived")
        word.status = update["status"]
    session.add(word)
    session.commit()
    session.refresh(word)
    return _word_public(word)


# ── 课堂发布（教师） ────────────────────────────────────────────────


def _get_assignment(
    session: Session, classroom_id: uuid.UUID, assignment_id: uuid.UUID
) -> VocabularyAssignment:
    assignment = session.get(VocabularyAssignment, assignment_id)
    if assignment is None or assignment.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="词汇任务不存在")
    return assignment


@router.get(
    "/classes/{code}/vocabulary/assignments",
    response_model=list[VocabularyTeacherAssignmentRow],
)
def list_assignments(
    session: SessionDep, code: str, current_user: TeacherUserDep
) -> Any:
    """教师任务列表：全部任务（含已结束）+ 名单进度汇总，按发布倒序。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    return vocab_service.teacher_assignment_rows(session, classroom.id)


@router.post(
    "/classes/{code}/vocabulary/assignments", response_model=VocabularyAssignmentPublic
)
def publish_vocab_assignment(
    session: SessionDep,
    code: str,
    current_user: TeacherUserDep,
    body: VocabularyAssignmentCreate,
) -> Any:
    """发布词汇任务：固化快照与目标名单，归档旧任务（本班教师/管理员）。

    词单来源同时受可见性约束：公共词库或本人班级词库（管理员不限），
    显式 word_ids 的词也必须归属可见词库。
    """
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    prompt_types = vocab_service.validate_prompt_types(body.prompt_types)
    words = vocab_service.resolve_publish_words(
        session, body.book_id, body.word_ids, viewer=current_user
    )
    assignment = vocab_service.publish_assignment(
        session=session,
        classroom_id=classroom.id,
        created_by=current_user.id,
        title=body.title,
        words=words,
        prompt_types=prompt_types,
        mode=body.mode,
        due_at=body.due_at,
    )
    return _assignment_public(assignment)


@router.post("/classes/{code}/vocabulary/assignments/{assignment_id}/archive")
def archive_vocab_assignment(
    session: SessionDep,
    code: str,
    assignment_id: uuid.UUID,
    current_user: TeacherUserDep,
) -> Any:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    assignment = _get_assignment(session, classroom.id, assignment_id)
    if assignment.status != "published":
        raise HTTPException(status_code=422, detail="该任务已结束")
    vocab_service.archive_assignment(session, assignment)
    return {"message": "词汇任务已结束"}


@router.get("/classes/{code}/vocabulary/results", response_model=VocabularyClassResults)
def read_vocab_results(
    session: SessionDep,
    code: str,
    current_user: TeacherUserDep,
    assignment_id: uuid.UUID | None = None,
) -> Any:
    """班级完成统计：默认当前任务；逐学生完成状态 + 逐词错误分布（首答口径）。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    assignment = (
        _get_assignment(session, classroom.id, assignment_id)
        if assignment_id is not None
        else vocab_service.current_published_assignment(session, classroom.id)
    )
    if assignment is None:
        return VocabularyClassResults(assignment=None)
    student_rows, word_rows = vocab_service.class_results(session, assignment)
    return VocabularyClassResults(
        assignment=_assignment_public(assignment),
        target_count=len(student_rows),
        completed_count=sum(1 for r in student_rows if r.status == "completed"),
        in_progress_count=sum(1 for r in student_rows if r.status == "in_progress"),
        not_started_count=sum(1 for r in student_rows if r.status == "not_started"),
        students=student_rows,
        words=word_rows,
    )


# ── 学生端 ─────────────────────────────────────────────────────────


def _student_rounds(
    session: Session, assignment_id: uuid.UUID, student_id: uuid.UUID
) -> list[VocabularySession]:
    """该学生在此任务的全部轮次（round_no 升序；归属由 student_id 过滤）。"""
    return list(
        session.exec(
            select(VocabularySession)
            .where(
                VocabularySession.assignment_id == assignment_id,  # type: ignore[arg-type]
                VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            )
            .order_by(col(VocabularySession.round_no))
        ).all()
    )


def _focused_vocab_session(
    session: Session,
    assignment_id: uuid.UUID,
    student_id: uuid.UUID,
    round_no: int | None = None,
) -> VocabularySession | None:
    """展示轮次：显式 round_no 回看指定轮；缺省未结束轮优先，否则最新轮。"""
    rounds = _student_rounds(session, assignment_id, student_id)
    if round_no is not None:
        return next((r for r in rounds if r.round_no == round_no), None)
    unfinished = next((r for r in rounds if r.status == "in_progress"), None)
    return unfinished if unfinished is not None else (rounds[-1] if rounds else None)


def _session_closed_reason(assignment: VocabularyAssignment) -> str | None:
    """任务级作答门禁原因（独立于会话状态）：due_passed / archived；开放为 None。

    已完成会话同样计算——「是否还能开练/作答」只取决于任务本身。
    """
    if assignment.status != "published":
        return "archived"
    if assignment.due_at is not None and datetime.now(UTC) >= assignment.due_at:
        return "due_passed"
    return None


def _round_summary_rows(
    session: Session, rounds: list[VocabularySession]
) -> list[VocabularyRoundSummaryRow]:
    """各轮首答摘要（口径与教师统计一致：attempt_no=1）。"""
    if not rounds:
        return []
    firsts = vocab_service.first_answers_by_session(session, [vs.id for vs in rounds])
    return [
        VocabularyRoundSummaryRow(
            round_no=vs.round_no,
            status=vs.status,
            answered_count=len(firsts.get(vs.id, {})),
            correct_first_count=sum(
                1 for a in firsts.get(vs.id, {}).values() if a.is_correct
            ),
            submitted_at=vs.submitted_at,
        )
        for vs in rounds
    ]


def _today_plan_payload(
    session: Session,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    assignment_id: uuid.UUID | None = None,
    round_no: int | None = None,
) -> VocabularyTodayPlan:
    assignments = vocab_service.student_assignment_rows(
        session, classroom_id, student_id
    )
    if assignment_id is not None:
        # 显式指定任务：不存在/非本班/不在名单一律 404，不静默回落
        assignment = session.get(VocabularyAssignment, assignment_id)
        if (
            assignment is None
            or assignment.classroom_id != classroom_id
            or not vocab_service.student_targeted(session, assignment, student_id)
        ):
            raise HTTPException(status_code=404, detail="词汇任务不存在")
    else:
        assignment = vocab_service.focused_assignment(session, classroom_id, student_id)
        if assignment is None or not vocab_service.student_targeted(
            session, assignment, student_id
        ):
            wrong = vocab_service.wrong_words(session, student_id)
            return VocabularyTodayPlan(
                assignments=assignments, wrong_word_count=len(wrong)
            )

    rounds = _student_rounds(session, assignment.id, student_id)
    vocab_session = _focused_vocab_session(
        session, assignment.id, student_id, round_no=round_no
    )
    if round_no is not None and vocab_session is None:
        # 显式回看不存在的轮次（含他学生的轮次）：404，不回落
        raise HTTPException(status_code=404, detail="轮次不存在")
    # 当前可练轮独立于展示轮计算：未结束轮优先，否则最新轮
    practice_session = _focused_vocab_session(session, assignment.id, student_id)
    current_round = practice_session.round_no if practice_session is not None else None
    grouped = (
        vocab_service.answers_by_item(session, vocab_session.id)
        if vocab_session is not None
        else {}
    )
    items: list[VocabularyTodayItem] = []
    answered_count = 0
    correct_first = 0
    for idx, snapshot_item in enumerate(assignment.snapshot_items):
        attempts = grouped.get(idx, [])
        first = next((a for a in attempts if a.attempt_no == 1), None)
        if first is not None:
            answered_count += 1
            if first.is_correct:
                correct_first += 1
        # 听音口径（设计文档 §5）：任务含 audio 且该词有稳定标准音；
        # 已作答的词拼写已揭示，可退回设备朗读练耳。其余一律看义拼词，
        # 避免播音按钮无内容可放。
        audio_allowed = "audio" in (assignment.prompt_types or []) and (
            snapshot_item.get("audio_url") is not None or first is not None
        )
        prompt_type = "audio" if audio_allowed else "meaning"
        items.append(
            VocabularyTodayItem(
                item_index=idx,
                prompt_type=prompt_type,
                part_of_speech=(
                    str(snapshot_item["part_of_speech"])
                    if snapshot_item.get("part_of_speech") is not None
                    else None
                ),
                meaning_zh=str(snapshot_item["meaning_zh"]),
                meaning_en=(
                    str(snapshot_item["meaning_en"])
                    if snapshot_item.get("meaning_en") is not None
                    else None
                ),
                audio_url=(
                    str(snapshot_item["audio_url"])
                    if snapshot_item.get("audio_url") is not None
                    else None
                ),
                # 未作答不透露拼写（防看 API 直接抄）
                headword=first.headword if first is not None else None,
                answered=first is not None,
                is_correct=first.is_correct if first is not None else None,
                attempt_count=len(attempts),
            )
        )
    wrong = vocab_service.wrong_words(session, student_id)
    return VocabularyTodayPlan(
        assignment=_assignment_public(assignment),
        session_id=vocab_session.id if vocab_session is not None else None,
        session_status=vocab_session.status if vocab_session is not None else None,
        session_round=vocab_session.round_no if vocab_session is not None else None,
        current_round=current_round,
        session_closed_reason=_session_closed_reason(assignment),
        items=items,
        # 展示轮的进度（回看历史轮时是该轮的记录）；任务整体进度看 assignments（首轮口径）
        answered_count=answered_count,
        correct_first_count=correct_first,
        rounds=_round_summary_rows(session, rounds),
        assignments=assignments,
        wrong_word_count=len(wrong),
    )


@router.get("/classes/{code}/vocabulary/today", response_model=VocabularyTodayPlan)
def read_vocab_today(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    assignment_id: uuid.UUID | None = None,
    round_no: int | None = None,
) -> Any:
    """学生词汇任务视图：任务列表 + 聚焦任务进度（未答题不透露拼写）。

    assignment_id 缺省 = 聚焦任务（最早截止的未完成者）；显式指定时返回
    该任务的聚焦轮次（多任务切换练习用）。round_no 显式回看指定轮次
    （只读，归属校验：只允许本人轮次，不存在 404）。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    return _today_plan_payload(
        session, classroom.id, student.id, assignment_id, round_no
    )


@router.post("/classes/{code}/vocabulary/sessions")
def start_vocab_session(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    body: VocabularySessionCreate,
) -> Any:
    """创建/恢复作答轮次（幂等）。仅目标名单内的本班学生。

    缺省 assignment_id = 聚焦任务；未结束轮存在时一律续做（重复点击
    不产生重复轮次），全部轮次已结束则开新一轮（「再练一轮」）。
    """
    if body.round not in (None, "continue", "new"):
        raise HTTPException(status_code=422, detail="未知的轮次请求参数")
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    if body.assignment_id is None:
        # 缺省 = 聚焦任务（最早截止的未完成进行中任务）
        assignment = vocab_service.focused_assignment(session, classroom.id, student.id)
        if assignment is None:
            raise HTTPException(status_code=404, detail="当前没有进行中的词汇任务")
    else:
        assignment = session.get(VocabularyAssignment, body.assignment_id)
    if assignment is None or assignment.classroom_id != classroom.id:
        raise HTTPException(status_code=404, detail="词汇任务不存在")
    vocab_service.ensure_assignment_open(assignment)
    if not vocab_service.student_targeted(session, assignment, student.id):
        raise HTTPException(
            status_code=403,
            detail="你不在此任务的名单内（任务发布后加入的同学请联系老师补派）",
        )
    vocab_session = vocab_service.get_or_create_session(
        session, classroom.id, student.id, assignment, round_request=body.round
    )
    return {
        "session_id": str(vocab_session.id),
        "status": vocab_session.status,
        "round_no": vocab_session.round_no,
    }


@router.post(
    "/vocabulary/sessions/{session_id}/answers", response_model=VocabularyAnswerResult
)
def submit_vocab_answer(
    session: SessionDep,
    session_id: uuid.UUID,
    current_user: StudentUserDep,
    body: VocabularyAnswerRequest,
) -> Any:
    """提交拼写作答：服务端规范化判分；幂等键重放返回同一结果。"""
    vocab_session = session.get(VocabularySession, session_id)
    if vocab_session is None:
        raise HTTPException(status_code=404, detail="作答会话不存在")
    # 会话归属：必须是本人会话（学生档案 → user）
    student = session.exec(
        select(Student).where(
            Student.id == vocab_session.student_id,  # type: ignore[arg-type]
            Student.user_id == current_user.id,  # type: ignore[arg-type]
        )
    ).first()
    if student is None:
        raise HTTPException(status_code=404, detail="作答会话不存在")
    assignment = (
        session.get(VocabularyAssignment, vocab_session.assignment_id)
        if vocab_session.assignment_id is not None
        else None
    )
    if assignment is None:
        raise HTTPException(status_code=422, detail="会话没有绑定任务，不能作答")
    vocab_service.ensure_assignment_open(assignment)
    if vocab_session.mode == "quiz" and vocab_session.status == "submitted":
        raise HTTPException(status_code=422, detail="测验已交卷，不能继续作答")

    answer = vocab_service.submit_answer(
        session=session,
        vocab_session=vocab_session,
        assignment=assignment,
        item_index=body.item_index,
        prompt_type=body.prompt_type,
        answer_raw=body.answer,
        idempotency_key=body.idempotency_key,
    )
    session.refresh(vocab_session)
    answered_count, correct_first = vocab_service.session_progress(
        session, vocab_session
    )
    snapshot_item = assignment.snapshot_items[body.item_index]
    return VocabularyAnswerResult(
        item_index=answer.item_index,
        attempt_no=answer.attempt_no,
        is_correct=answer.is_correct,
        correct_spelling=str(snapshot_item["headword"]),
        meaning_zh=str(snapshot_item["meaning_zh"]),
        session_status=vocab_session.status,
        answered_count=answered_count,
        correct_first_count=correct_first,
    )


@router.get(
    "/classes/{code}/vocabulary/wrong-words", response_model=VocabularyWrongWords
)
def read_wrong_words(
    session: SessionDep, code: str, current_user: StudentUserDep
) -> Any:
    """错词本：本课堂学生档案下全部词汇任务的首答错词（跨任务聚合）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    return VocabularyWrongWords(
        classroom_code=classroom.code,
        items=vocab_service.wrong_words(session, student.id),
    )
