"""词汇学习（背单词）模块接口：books 域。

由原 vocabulary.py 按域拆出：端点路径、参数、响应模型与实现均未改动。

    /vocabulary/books                 词库 CRUD + 词库内加词（教师/管理员）
    /vocabulary/books/import-preview  CSV 解析预览（不落库）
    /vocabulary/words/{id}            词条编辑
    /classes/{code}/vocabulary/...    课堂发布 / 学生任务 / 结果 / 错词本
    /vocabulary/sessions/{id}/answers 学生作答（服务端判分）

权限口径（设计文档 §5）：词库编辑/发布 = 课堂所有者教师或管理员；
学生任务仅目标名单内的本班学生；原始作答仅本人与该班教师可读。
401 只表示登录失效；权限不足一律 403。
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import update
from sqlmodel import col, select

from app.api.deps import SessionDep, TeacherUserDep
from app.api.pagination import paged
from app.api.routes.classes import (
    _require_classroom_teacher,
)
from app.api.routes.vocabulary_shared import (
    _book_public,
    _book_visible,
    _word_public,
)
from app.models import (
    Classroom,
    VocabularyBook,
    VocabularyBookCreate,
    VocabularyBookDetail,
    VocabularyBookItem,
    VocabularyBookPublic,
    VocabularyBookUpdate,
    VocabularyWord,
    VocabularyWordIn,
    VocabularyWordPublic,
    VocabularyWordUpdate,
)
from app.services import vocab_levels as vocab_levels_service
from app.services.vocabulary import (
    MAX_BOOK_WORDS,
    _create_word,
)
from app.services.vocabulary import (
    add_words_to_book as _add_words_to_book,
)
from app.services.vocabulary import (
    get_book_or_404 as _get_book,
)
from app.services.vocabulary import (
    require_book_editor as _require_book_editor,
)
from app.services.vocabulary import (
    word_count_by_book as _book_word_count,
)

router = APIRouter()


# ── 词库 CRUD ──────────────────────────────────────────────────────


@router.get("/vocabulary/books", response_model=list[VocabularyBookPublic])
def list_books(
    session: SessionDep,
    current_user: TeacherUserDep,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> Any:
    """词库列表：公共词库全体教师可见；班级词库仅本班教师（管理员全见）。

    可见性在 SQL 层过滤（与 _book_visible 同谓词：public 或本人创建），
    不把别人的班级词库整表拉回 Python 再丢掉。
    """
    statement = select(VocabularyBook).order_by(col(VocabularyBook.created_at))
    # 多租户：可见性谓词始终带本校过滤（管理员「全见」= 本校全见）
    statement = statement.where(VocabularyBook.tenant_id == current_user.tenant_id)  # type: ignore[union-attr]
    if current_user.role != "school_admin":
        statement = statement.where(
            (col(VocabularyBook.scope) == "public")  # type: ignore[union-attr]
            | (col(VocabularyBook.owner_id) == current_user.id)  # type: ignore[union-attr]
        )
    books = session.exec(paged(statement, offset, limit)).all()
    counts = _book_word_count(session, [b.id for b in books])
    return [_book_public(b, counts.get(b.id, 0)) for b in books]


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
    if scope == "public" and current_user.role != "school_admin":
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
    # position 必须连续赋值：全部默认 0 会让 ORDER BY position 全平局，
    # Postgres 平局返回顺序不定——教师预览词序与学生测验词序可能不一致
    # （CI 与本地实测就返回不同顺序）
    for position, word_in in enumerate(book_in.words, start=1):
        word = _create_word(session, word_in)
        session.flush()
        session.add(
            VocabularyBookItem(book_id=book.id, word_id=word.id, position=position)
        )
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
    # SQL 原子自增：并发编辑时读-改-写会丢版本号
    session.execute(  # ty: ignore[deprecated] - exec() 不接受 update 语句
        update(VocabularyBook)
        .where(col(VocabularyBook.id) == book.id)
        .values(version=VocabularyBook.version + 1)
    )
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
    if word.tenant_id != current_user.tenant_id:
        # 跨校词条按不存在处理（CLAUDE.md 不变量④；与 RLS 激活环境对齐）
        raise HTTPException(status_code=404, detail="词条不存在")
    # 权限：管理员任意；教师只能改自己班级词库里的词
    if current_user.role != "school_admin":
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
