"""词汇学习（背单词）模块接口：student 域。

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
from sqlmodel import col, select

from app.api.deps import SessionDep, StudentUserDep
from app.api.routes.classes import (
    _get_classroom,
    _student_profile_of,
)
from app.api.routes.vocabulary_shared import (
    _book_public,
    _word_public,
)
from app.models import (
    SELF_PRACTICE_MAX_WORDS,
    VocabularyBook,
    VocabularyBookDetail,
    VocabularyBookPublic,
    VocabularySession,
    VocabularyStudentHistory,
    VocabularyStudentPlan,
    VocabularyStudentSessionCreate,
    VocabularyStudentSessionCreated,
    VocabularyWrongWords,
)
from app.services import vocabulary as vocab_service
from app.services.vocabulary import (
    get_book_or_404 as _get_book,
)

router = APIRouter()


@router.get(
    "/classes/{code}/vocabulary/wrong-words", response_model=VocabularyWrongWords
)
def read_wrong_words(
    session: SessionDep, code: str, current_user: StudentUserDep
) -> Any:
    """错词本：本课堂学生档案下全部词汇轮次的首答错词（跨任务/自主聚合）。

    历史错误次数、最近独立首答、最近答对三个维度分列（一次答对不删词）；
    practiceable 标注词条是否仍在当前可练词库内，可直接进错词专项复习。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    items = vocab_service.wrong_word_items(
        session,
        student.id,
        vocab_service.student_practiceable_word_ids(session, classroom.id),
    )
    pos_map = vocab_service.pos_by_word_ids(session, [i.word_id for i in items])
    for item in items:
        item.part_of_speech = pos_map.get(item.word_id)
    return VocabularyWrongWords(classroom_code=classroom.code, items=items)


# ── 学生自主练习与学习报告 ─────────────────────────────────────────


@router.get(
    "/classes/{code}/vocabulary/student/books",
    response_model=list[VocabularyBookPublic],
)
def list_student_books(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    search: str | None = Query(default=None, max_length=64),
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> Any:
    """学生可浏览的词库：active 公共词库 + 本班词库，支持按词库名称搜索。"""
    classroom = _get_classroom(session, code)
    _student_profile_of(session, classroom, current_user)
    books = session.exec(
        select(VocabularyBook)
        .where(
            VocabularyBook.status == "active",
            (VocabularyBook.scope == "public")  # type: ignore[operator]
            | (VocabularyBook.classroom_id == classroom.id),  # type: ignore[operator,arg-type]
        )
        .order_by(col(VocabularyBook.created_at))
    ).all()
    if search:
        needle = search.strip().casefold()
        if needle:
            books = [b for b in books if needle in b.title.casefold()]
    # 搜索是 Python 侧过滤，故切片放在过滤之后，避免分页丢命中
    if offset:
        books = books[offset:]
    if limit is not None:
        books = books[:limit]
    counts = vocab_service.student_book_word_counts(session, [b.id for b in books])
    return [_book_public(b, counts.get(b.id, 0)) for b in books]


@router.get(
    "/classes/{code}/vocabulary/student/books/{book_id}",
    response_model=VocabularyBookDetail,
)
def read_student_book(
    session: SessionDep,
    code: str,
    book_id: uuid.UUID,
    current_user: StudentUserDep,
    search: str | None = Query(default=None, max_length=64),
) -> Any:
    """词库详情（学生）：active 词条附词性与释义，支持库内单词/释义搜索。

    搜索在拼写、中文释义、英文释义上不区分大小写匹配。
    """
    classroom = _get_classroom(session, code)
    _student_profile_of(session, classroom, current_user)
    book = _get_book(session, book_id)
    if book.status != "active" or book.id not in vocab_service.student_book_ids(
        session, classroom.id
    ):
        raise HTTPException(status_code=403, detail="没有权限查看这个词库")
    # word_count 始终为全库 active 词条数（开练前的词数预告不受搜索影响）；
    # words 为搜索过滤后的列表（search 缺省 = 全部）
    all_words = vocab_service.student_book_words(session, book.id)
    words = (
        vocab_service.student_book_words(session, book.id, search)
        if search
        else all_words
    )
    return VocabularyBookDetail(
        **_book_public(book, len(all_words)).model_dump(),
        words=[_word_public(w) for w in words],
    )


@router.post(
    "/classes/{code}/vocabulary/student/sessions",
    response_model=VocabularyStudentSessionCreated,
)
def start_student_session(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    body: VocabularyStudentSessionCreate,
) -> Any:
    """学生自主开轮：kind=self 从词库练（可混 30% 错词），kind=review 错词专项。

    - 同款未结束轮直接续做（刷新/重复点击不产生重复轮次）；
    - 题单与题序创建后固化；词数不足按实际数量出题（响应里 total_count
      即实际题数，前端开练前明确展示）；
    - 自主轮与教师任务完全独立，不产生任务进度与成绩。
    """
    if body.word_count > SELF_PRACTICE_MAX_WORDS:
        raise HTTPException(
            status_code=422,
            detail=f"一次练习最多 {SELF_PRACTICE_MAX_WORDS} 个词",
        )
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    vocab_session, title, wrong_used = vocab_service.create_student_session(
        session,
        classroom_id=classroom.id,
        student_id=student.id,
        kind=body.kind,
        book_id=body.book_id,
        word_count=body.word_count,
        mix_wrong=body.mix_wrong,
    )
    return VocabularyStudentSessionCreated(
        session_id=vocab_session.id,
        kind=vocab_session.kind,
        title=title,
        book_id=vocab_session.source_book_id,
        total_count=len(vocab_session.snapshot_items or []),
        wrong_word_count=wrong_used,
        started_at=vocab_session.started_at,
    )


@router.get(
    "/classes/{code}/vocabulary/student/sessions/{session_id}",
    response_model=VocabularyStudentPlan,
)
def read_student_session(
    session: SessionDep,
    code: str,
    session_id: uuid.UUID,
    current_user: StudentUserDep,
) -> Any:
    """单次练习详情（三类轮次统一）：作答视图 + 单轮报告数据。

    未答题不透露拼写；已答回填本人首答输入。首答正确率口径 =
    correct_first_count / answered_count（分母为已答题数），完成进度
    分母为 total_count，由前端分别展示。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    vocab_session = session.get(VocabularySession, session_id)
    if vocab_session is None or vocab_session.student_id != student.id:
        # 他人的/不存在的一律 404，不区分报错
        raise HTTPException(status_code=404, detail="练习记录不存在")
    return vocab_service.student_plan(session, vocab_session)


@router.get(
    "/classes/{code}/vocabulary/student/history",
    response_model=VocabularyStudentHistory,
)
def read_student_history(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """练习历史列表：任务轮/自主轮/复习轮统一（kind 区分），按开始倒序。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    return VocabularyStudentHistory(
        items=vocab_service.history_rows(session, student.id, limit=limit)
    )
