"""词汇学习（背单词）模块接口：assignments 域。

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
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import SessionDep, StudentUserDep, TeacherUserDep
from app.api.routes.classes import (
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
)
from app.api.routes.vocabulary_shared import (
    _assignment_public,
    _get_assignment,
    _today_plan_payload,
    read_vocab_results_payload,
)
from app.models import (
    Student,
    VocabularyAnswerRequest,
    VocabularyAnswerResult,
    VocabularyAssignment,
    VocabularyAssignmentCreate,
    VocabularyAssignmentPublic,
    VocabularyClassResults,
    VocabularyQuizAnswerReceipt,
    VocabularySession,
    VocabularySessionCreate,
    VocabularyTeacherAssignmentRow,
    VocabularyTodayPlan,
)
from app.services import vocab_quiz
from app.services import vocabulary as vocab_service

router = APIRouter()


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
        opens_at=body.opens_at,
        duration_minutes=body.duration_minutes,
        pass_line=body.pass_line,
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
    """班级完成统计：默认当前任务；逐学生完成状态 + 逐词错误分布（首答口径）。

    测验任务先到时结算（结果不依赖学生页面在线），并附成绩/及格/切屏/
    补考授权等扩展字段。
    """
    if assignment_id is not None:
        return read_vocab_results_payload(session, code, assignment_id, current_user)
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    assignment = vocab_service.current_published_assignment(session, classroom.id)
    if assignment is None:
        return VocabularyClassResults(assignment=None)
    return read_vocab_results_payload(session, code, assignment.id, current_user)


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
    if assignment.mode == "quiz":
        # 测验：明确开始才计时（服务端落 quiz_started_at；续做不重置）。
        # 准入（开放/截止/参与次数/补考授权）全部服务端校验。
        vocab_session = vocab_quiz.start_quiz_session(
            session,
            classroom_id=classroom.id,
            student_id=student.id,
            assignment=assignment,
        )
    else:
        vocab_session = vocab_service.get_or_create_session(
            session, classroom.id, student.id, assignment, round_request=body.round
        )
    return {
        "session_id": str(vocab_session.id),
        "status": vocab_session.status,
        "round_no": vocab_session.round_no,
    }


@router.post(
    "/vocabulary/sessions/{session_id}/answers",
    response_model=VocabularyAnswerResult | VocabularyQuizAnswerReceipt,
)
def submit_vocab_answer(
    session: SessionDep,
    session_id: uuid.UUID,
    current_user: StudentUserDep,
    body: VocabularyAnswerRequest,
) -> Any:
    """提交拼写作答：服务端规范化判分；幂等键重放返回同一结果。

    任务轮校验任务开放（截止/归档门禁）；自主/复习轮题单创建时已固化，
    随时可作答，不依赖任务状态。
    测验答卷：到时先结算；每题只收一次（幂等键重传不误伤）；回执只确认
    已接收，不返回答案与正误（公布规则之外零泄露）。
    """
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
    is_quiz = assignment is not None and assignment.mode == "quiz"

    # 已成功提交的幂等键识别（断网重传回执）：先于截止/归档/交卷门禁——
    # 作答已落库但回包丢失时，交卷或截止后原键重试仍取得成功确认，
    # 不新增答案；测验回执只确认已接收，不泄露正误与未公布答案
    replay = vocab_service.recognize_answer_replay(
        session,
        vocab_session,
        item_index=body.item_index,
        prompt_type=body.prompt_type,
        answer_raw=body.answer,
        idempotency_key=body.idempotency_key,
    )
    if replay is not None:
        answered_count, correct_first = vocab_service.session_progress(
            session, vocab_session
        )
        if is_quiz:
            deadline = (
                vocab_quiz.quiz_deadline(vocab_session, assignment)
                if assignment is not None
                else None
            )
            remaining = (
                max(
                    0,
                    int(
                        (
                            deadline - datetime.now(UTC)  # type: ignore[operator]
                        ).total_seconds()
                    ),
                )
                if deadline is not None and vocab_session.status == "in_progress"
                else None
            )
            return VocabularyQuizAnswerReceipt(
                item_index=replay.item_index,
                answered_count=answered_count,
                session_status=vocab_session.status,
                remaining_seconds=remaining,
            )
        snapshot_items = vocab_service.session_snapshot(session, vocab_session)
        snapshot_item = snapshot_items[replay.item_index]
        return VocabularyAnswerResult(
            item_index=replay.item_index,
            attempt_no=replay.attempt_no,
            is_correct=replay.is_correct,
            correct_spelling=str(snapshot_item["headword"]),
            meaning_zh=str(snapshot_item["meaning_zh"]),
            session_status=vocab_session.status,
            answered_count=answered_count,
            correct_first_count=correct_first,
        )

    if vocab_session.assignment_id is not None:
        if assignment is None:
            raise HTTPException(status_code=422, detail="会话没有绑定任务，不能作答")
        vocab_service.ensure_assignment_open(assignment)
    if is_quiz and assignment is not None:
        # 测验门禁：到时先结算，再拒绝已终结答卷（交卷/超时都不能续答）；
        # 终态竞态由 submit_answer 的会话行锁兜底
        vocab_quiz.ensure_quiz_answerable(session, vocab_session, assignment)
    elif vocab_session.mode == "quiz" and vocab_session.status == "submitted":
        raise HTTPException(status_code=422, detail="测验已交卷，不能继续作答")
    snapshot_items = vocab_service.session_snapshot(session, vocab_session)

    answer = vocab_service.submit_answer(
        session=session,
        vocab_session=vocab_session,
        snapshot_items=snapshot_items,
        item_index=body.item_index,
        prompt_type=body.prompt_type,
        answer_raw=body.answer,
        idempotency_key=body.idempotency_key,
        one_attempt_per_item=is_quiz,
        assignment=assignment if is_quiz else None,
    )
    session.refresh(vocab_session)
    answered_count, _correct_first = vocab_service.session_progress(
        session, vocab_session
    )
    if is_quiz:
        # 回执只确认已接收；剩余时间由服务器计算下发
        deadline = vocab_quiz.quiz_deadline(vocab_session, assignment)  # type: ignore[arg-type]
        remaining = (
            max(0, int((deadline - datetime.now(UTC)).total_seconds()))
            if deadline is not None and vocab_session.status == "in_progress"
            else None
        )
        return VocabularyQuizAnswerReceipt(
            item_index=answer.item_index,
            answered_count=answered_count,
            session_status=vocab_session.status,
            remaining_seconds=remaining,
        )
    snapshot_item = snapshot_items[body.item_index]
    return VocabularyAnswerResult(
        item_index=answer.item_index,
        attempt_no=answer.attempt_no,
        is_correct=answer.is_correct,
        correct_spelling=str(snapshot_item["headword"]),
        meaning_zh=str(snapshot_item["meaning_zh"]),
        session_status=vocab_session.status,
        answered_count=answered_count,
        correct_first_count=_correct_first,
    )


@router.post("/vocabulary/sessions/{session_id}/submit")
def submit_quiz_session(
    session: SessionDep,
    session_id: uuid.UUID,
    current_user: StudentUserDep,
) -> Any:
    """主动交卷（测验）：终结答卷，幂等；到时答卷已由结算先行终结。"""
    vocab_session = session.get(VocabularySession, session_id)
    if vocab_session is None:
        raise HTTPException(status_code=404, detail="作答会话不存在")
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
    if assignment is None or assignment.mode != "quiz":
        raise HTTPException(status_code=422, detail="只有测验可以手动交卷")
    vocab_session = vocab_quiz.submit_quiz_session(session, vocab_session, assignment)
    return {
        "session_id": str(vocab_session.id),
        "status": vocab_session.status,
        "end_reason": vocab_session.end_reason,
        "submitted_at": vocab_session.submitted_at,
    }


@router.post("/vocabulary/sessions/{session_id}/tab-switch")
def report_quiz_tab_switch(
    session: SessionDep,
    session_id: uuid.UUID,
    current_user: StudentUserDep,
) -> Any:
    """测验切屏上报：只计异常事件次数供教师参考，不自动认定作弊。"""
    vocab_session = session.get(VocabularySession, session_id)
    if vocab_session is None:
        raise HTTPException(status_code=404, detail="作答会话不存在")
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
    if assignment is None or assignment.mode != "quiz":
        raise HTTPException(status_code=422, detail="只有测验记录切屏事件")
    count = vocab_quiz.record_tab_switch(session, vocab_session, assignment)
    return {"tab_switch_count": count}
