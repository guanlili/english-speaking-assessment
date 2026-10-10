"""教师课堂面板：board 聚合（名单/题位/统计）。"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import load_only
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
)
from app.api.routes.class_shared import (
    _active_passage,
    _assigned_active_passages,
    _assignment_unit,
    _BoardRef,
    _get_classroom,
    _include_type,
    _repeat_sentences_of_passages,
    _require_classroom_teacher,
    _today_in_practice_tz,
    router,
)
from app.core.config import settings
from app.models import (
    AssignmentInfo,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    BoardData,
    BoardItem,
    BoardStudent,
    ClassroomExercise,
    ClassroomExercisePublic,
    InstructionAck,
    PracticeSession,
    Student,
)
from app.services import exam as exam_service
from app.services import exercise as exercise_service

logger = logging.getLogger(__name__)


@router.get("/{code}/board", response_model=BoardData)
def read_class_board(session: SessionDep, code: str, current_user: CurrentUser) -> Any:
    """老师名单表（PRD §8.5 2 周）：谁交了、每题分数、音频；允许先显示评分中。

    需要教师身份：本课指派教师或管理员（课堂码不能当教师凭据）。
    """
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    today = _today_in_practice_tz()

    current_exercise = (
        session.get(ClassroomExercise, classroom.current_exercise_id)
        if classroom.current_exercise_id is not None
        else None
    )
    # 已发布版本优先：名单表也必须按快照渲染，避免题库编辑后题位漂移。
    if current_exercise is not None:
        snapshot_refs: dict[str, list[_BoardRef]] = {
            AttemptItemType.PASSAGE: [],
            AttemptItemType.REPEAT: [],
            AttemptItemType.QUESTION: [],
            AttemptItemType.INSTRUCTION: [],
        }
        for item in current_exercise.snapshot_items:
            item_type = str(item.get("type", ""))
            item_id = item.get("id")
            if item_type not in snapshot_refs or item_id is None:
                continue
            try:
                snapshot_refs[item_type].append(_BoardRef(uuid.UUID(str(item_id))))
            except ValueError:
                logger.warning("invalid exercise snapshot item id: %s", item_id)
        board_item_objects = (
            snapshot_refs[AttemptItemType.PASSAGE],
            snapshot_refs[AttemptItemType.REPEAT],
            snapshot_refs[AttemptItemType.QUESTION],
            snapshot_refs[AttemptItemType.INSTRUCTION],
        )
    else:
        resolved = exercise_service.resolve_assigned_items(session, classroom)
        # 说明只随按题发布进卷子；旧路径（单元指派）补空桶保持四元组同构
        board_item_objects = (*resolved, []) if resolved is not None else None
    assigned_unit_board = _assignment_unit(session, classroom)
    include_reading = include_repeat = False
    if board_item_objects is not None:
        (
            board_passages,
            board_sentences,
            board_questions,
            board_instructions,
        ) = board_item_objects
        board_passage = board_passages[0] if board_passages else None
        include_reading = True
        include_repeat = True
        skeleton = (
            [
                BoardItem(
                    item_id=p.id,
                    type=AttemptItemType.PASSAGE,
                    status="missing",
                )
                for p in board_passages
            ]
            + [
                BoardItem(
                    item_id=s.id,
                    type=AttemptItemType.REPEAT,
                    status="missing",
                )
                for s in board_sentences
            ]
            + [
                BoardItem(
                    item_id=q.id,
                    type=AttemptItemType.QUESTION,
                    status="missing",
                )
                for q in board_questions
            ]
            + [
                BoardItem(
                    item_id=i.id,
                    type=AttemptItemType.INSTRUCTION,
                    status="missing",
                )
                for i in board_instructions
            ]
        )
        # 按题轮的学生行渲染需要这些集合
        board_repeat_sentences = board_sentences
    else:
        # 当前指派单元的篇目（面板和档位计算都用它，不用全局首篇）；
        # 组内多篇各自占一个朗读题位，锚点（第一篇）用于会话匹配
        if assigned_unit_board is not None:
            board_passages = _assigned_active_passages(session, classroom)
        else:
            board_passages = []
        board_passage = board_passages[0] if board_passages else None
        if board_passage is None:
            board_passage = _active_passage(session)
            board_passages = [board_passage]

        # 题目骨架：按指派题型裁剪（复述默认含；朗读勾选后含）
        include_reading = _include_type(classroom, "reading")
        include_repeat = _include_type(classroom, "repeat")
        board_questions = []
        board_repeat_sentences = []
        # 说明只随按题发布进卷子，单元指派/自主路径永远没有说明题位
        board_instructions = []
        if include_repeat:
            board_sentences_by_passage = _repeat_sentences_of_passages(
                session, board_passages
            )
            for p in board_passages:
                board_repeat_sentences.extend(board_sentences_by_passage.get(p.id, []))
        skeleton = [
            BoardItem(
                item_id=s.id,
                type=AttemptItemType.REPEAT,
                status="missing",
            )
            for s in board_repeat_sentences
        ]
        if include_reading:
            skeleton = [
                BoardItem(
                    item_id=p.id,
                    type=AttemptItemType.PASSAGE,
                    status="missing",
                )
                for p in board_passages
            ] + skeleton
        # 非按题指派：每位学生问答题不同，骨架不占位，在每生作答里展示
        board_questions = []

    students = session.exec(
        select(Student).where(Student.classroom_id == classroom.id)
    ).all()
    today_sessions = session.exec(
        select(PracticeSession)
        .where(
            PracticeSession.classroom_id == classroom.id,
            PracticeSession.session_date == today,
            PracticeSession.mode == "daily",
        )
        .order_by(col(PracticeSession.created_at))
    ).all()

    # A→B→A 修复：优先匹配当前指派篇目的会话，而非仅按创建时间取最新
    student_sessions: dict[uuid.UUID, list[PracticeSession]] = {}
    for s in today_sessions:
        student_sessions.setdefault(s.student_id, []).append(s)
    session_by_student: dict[uuid.UUID, PracticeSession] = {}
    assigned_passage_id = board_passage.id if board_passage else None
    for sid, sessions in student_sessions.items():
        if current_exercise is not None:
            matching = [s for s in sessions if s.assignment_id == current_exercise.id]
            if matching:
                session_by_student[sid] = matching[-1]
            # 当前发布版本没有开始过，就不要回退到已归档版本的同篇目会话。
            continue
        if assigned_passage_id is not None:
            matching = [s for s in sessions if s.passage_id == assigned_passage_id]
            if matching:
                session_by_student[sid] = matching[-1]
                continue
        session_by_student[sid] = sessions[-1]

    # 7 日未练口径：加入超过 7 天且窗口内无任何作答（US-10 简化实现）

    now = datetime.now(ZoneInfo(settings.PRACTICE_TZ))
    week_ago = (now - timedelta(days=7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_ago_utc = week_ago.astimezone(ZoneInfo("UTC"))
    student_ids = [s.id for s in students]
    # 7 日活跃判定只需「谁有过作答」：单列 distinct，不整行加载（含大 JSON 列）
    recent_student_ids = set(
        session.exec(
            select(Attempt.student_id)
            .where(
                Attempt.student_id.in_(student_ids),  # type: ignore
                Attempt.created_at >= week_ago_utc,  # type: ignore
            )
            .distinct()
        ).all()
    )

    board_students: list[BoardStudent] = []
    submitted_count = 0
    completed_count = 0
    pending_count = 0
    # 预取所有学生的作答（一次查询替代 N+1）。
    # load_only 只取看板用到的列：item_snapshot/transcript/rubric 等 JSON 大列
    # 不进内存（轮询热路径，全班 × 多题时每行可省数 KB）
    practice_session_ids = [
        ps.id for ps in session_by_student.values() if ps is not None
    ]
    attempts_map: dict[tuple[uuid.UUID, uuid.UUID], list[Attempt]] = {}
    if practice_session_ids:
        all_attempts = session.exec(
            select(Attempt)
            .options(
                load_only(
                    Attempt.id,  # ty: ignore[invalid-argument-type]
                    Attempt.student_id,  # ty: ignore[invalid-argument-type]
                    Attempt.session_id,  # ty: ignore[invalid-argument-type]
                    Attempt.item_id,  # ty: ignore[invalid-argument-type]
                    Attempt.item_type,  # ty: ignore[invalid-argument-type]
                    Attempt.status,  # ty: ignore[invalid-argument-type]
                    Attempt.overall,  # ty: ignore[invalid-argument-type]
                )
            )
            .where(
                Attempt.student_id.in_(student_ids),  # type: ignore
                Attempt.session_id.in_(practice_session_ids),  # type: ignore
            )
            .order_by(col(Attempt.created_at))
        ).all()
        for attempt in all_attempts:
            if attempt.student_id is None or attempt.session_id is None:
                continue
            key = (attempt.student_id, attempt.session_id)
            if key not in attempts_map:
                attempts_map[key] = []
            attempts_map[key].append(attempt)

    # 说明「已读」预取：本面板各学生会话的 ack（学生, 题目）集合
    ack_keys: set[tuple[uuid.UUID, uuid.UUID]] = set()
    if practice_session_ids and board_instructions:
        acks = session.exec(
            select(InstructionAck).where(
                InstructionAck.session_id.in_(practice_session_ids)  # type: ignore
            )
        ).all()
        ack_keys = {(ack.student_id, ack.item_id) for ack in acks}

    for student in students:
        practice_session = session_by_student.get(student.id)
        items: list[BoardItem] = []
        repeat_scores: list[float] = []
        question_scores: list[float] = []
        has_pending = False
        round_status = "not_started"

        # 未开始当前轮的学生不渲染骨架（教师面板口径：not_started = 空题单）。
        # 已开始的学生按当前题单骨架 + 作答渲染，缺的题位显示 missing。
        if practice_session is not None:
            attempts = attempts_map.get((student.id, practice_session.id), [])
            latest: dict[uuid.UUID, Attempt] = {}
            for attempt in attempts:
                latest[attempt.item_id] = attempt

            def _status_for(
                item_id: uuid.UUID, _latest: dict[uuid.UUID, Attempt] = latest
            ) -> Attempt | None:
                return _latest.get(item_id)

            # 朗读题位
            if include_reading:
                for board_p in board_passages:
                    attempt = _status_for(board_p.id)
                    if attempt is None:
                        items.append(
                            BoardItem(
                                item_id=board_p.id,
                                type=AttemptItemType.PASSAGE,
                                status="missing",
                            )
                        )
                    else:
                        if attempt.status in (
                            AttemptStatus.QUEUED,
                            AttemptStatus.SCORING,
                        ):
                            has_pending = True
                        if (
                            attempt.status == AttemptStatus.DONE
                            and attempt.overall is not None
                        ):
                            repeat_scores.append(attempt.overall)
                        items.append(
                            BoardItem(
                                item_id=board_p.id,
                                type=AttemptItemType.PASSAGE,
                                status=attempt.status,
                                overall=attempt.overall,
                                attempt_id=attempt.id,
                            )
                        )
            # 复述题位
            for s in board_repeat_sentences:
                attempt = _status_for(s.id)
                if attempt is None:
                    items.append(
                        BoardItem(
                            item_id=s.id, type=AttemptItemType.REPEAT, status="missing"
                        )
                    )
                    continue
                if (
                    attempt.status == AttemptStatus.QUEUED
                    or attempt.status == AttemptStatus.SCORING
                ):
                    has_pending = True
                if attempt.status == AttemptStatus.DONE and attempt.overall is not None:
                    repeat_scores.append(attempt.overall)
                items.append(
                    BoardItem(
                        item_id=s.id,
                        type=AttemptItemType.REPEAT,
                        status=attempt.status,
                        overall=attempt.overall,
                        attempt_id=attempt.id,
                    )
                )
            # 问答题位
            rendered_qids: set[uuid.UUID] = set()
            for board_q in board_questions:
                rendered_qids.add(board_q.id)
                attempt = _status_for(board_q.id)
                if attempt is None:
                    items.append(
                        BoardItem(
                            item_id=board_q.id,
                            type=AttemptItemType.QUESTION,
                            status="missing",
                        )
                    )
                    continue
                if attempt.status in (
                    AttemptStatus.QUEUED,
                    AttemptStatus.SCORING,
                ):
                    has_pending = True
                if attempt.status == AttemptStatus.DONE and attempt.overall is not None:
                    question_scores.append(attempt.overall)
                items.append(
                    BoardItem(
                        item_id=board_q.id,
                        type=AttemptItemType.QUESTION,
                        status=attempt.status,
                        overall=attempt.overall,
                        attempt_id=attempt.id,
                    )
                )
            # 已做但不在骨架的问答题（换题产生的额外题）
            for item_id, attempt in latest.items():
                if attempt.item_type != AttemptItemType.QUESTION:
                    continue
                if item_id in rendered_qids:
                    continue
                if attempt.status in (AttemptStatus.QUEUED, AttemptStatus.SCORING):
                    has_pending = True
                if attempt.status == AttemptStatus.DONE and attempt.overall is not None:
                    question_scores.append(attempt.overall)
                items.append(
                    BoardItem(
                        item_id=item_id,
                        type=AttemptItemType.QUESTION,
                        status=attempt.status,
                        overall=attempt.overall,
                        attempt_id=attempt.id,
                    )
                )
            # 说明题位：已读=done / 未读=missing；不进评分与提交统计
            for board_i in board_instructions:
                items.append(
                    BoardItem(
                        item_id=board_i.id,
                        type=AttemptItemType.INSTRUCTION,
                        status=(
                            AttemptStatus.DONE
                            if (student.id, board_i.id) in ack_keys
                            else "missing"
                        ),
                    )
                )

        # 统一统计口径：not_started / scoring / in_progress / all_done / has_failures
        # 说明无作答，不参与统计（只展示已读状态）
        stat_items = [i for i in items if i.type != AttemptItemType.INSTRUCTION]
        non_missing = [i for i in stat_items if i.status != "missing"]
        terminal = [
            i
            for i in stat_items
            if i.status in (AttemptStatus.DONE, AttemptStatus.FAILED)
        ]
        if not non_missing:
            round_status = "not_started"
        elif has_pending:
            round_status = "scoring"
        elif len(terminal) < len(stat_items):
            round_status = "in_progress"
        elif all(i.status == AttemptStatus.DONE for i in terminal):
            round_status = "all_done"
        else:
            round_status = "has_failures"

        done_count = sum(1 for i in stat_items if i.status == AttemptStatus.DONE)
        if any(i.status != "missing" for i in stat_items):
            submitted_count += 1
        if round_status in ("all_done", "has_failures"):
            completed_count += 1
        if has_pending:
            pending_count += 1
        joined_before_window = (
            student.created_at is not None
            and student.created_at.astimezone(ZoneInfo(settings.PRACTICE_TZ)).date()
            < week_ago.date()
        )
        inactive = joined_before_window and student.id not in recent_student_ids
        # 模考监考：当前发布为考试时，给出该生切屏次数/离屏时长/用时/是否交卷
        exam_switches: int | None = None
        exam_switch_seconds: int | None = None
        exam_used: int | None = None
        exam_ended_flag: bool | None = None
        if current_exercise is not None and current_exercise.is_exam:
            ps = session_by_student.get(student.id)
            if ps is not None and ps.exam_started_at is not None:
                exam_service.finalize_if_expired(session, ps, current_exercise)
                exam_switches = ps.tab_switch_count
                exam_switch_seconds = ps.tab_switch_seconds
                exam_used = exam_service.exam_time_used_seconds(ps)
                exam_ended_flag = ps.exam_ended_at is not None
        board_students.append(
            BoardStudent(
                student_id=student.id,
                display_name=student.display_name,
                suffix=student.suffix,
                done_count=done_count,
                total_count=len(stat_items),
                repeat_avg=(
                    round(sum(repeat_scores) / len(repeat_scores), 1)
                    if repeat_scores
                    else None
                ),
                question_avg=(
                    round(sum(question_scores) / len(question_scores), 1)
                    if question_scores
                    else None
                ),
                has_pending=has_pending,
                exam_tab_switches=exam_switches,
                exam_tab_switch_seconds=exam_switch_seconds,
                exam_time_used_seconds=exam_used,
                exam_ended=exam_ended_flag,
                round_status=round_status,
                inactive_days7=inactive,
                xp=student.xp,
                streak_days=student.streak_days,
                items=items,
            )
        )

    # 交了的在前，其次按完成数降序，再按名字
    board_students.sort(
        key=lambda s: (
            -min(s.done_count, 1),
            -s.done_count,
            s.display_name,
        )
    )

    latest_engine = session.exec(
        select(Attempt.engine)
        .where(Attempt.status == AttemptStatus.DONE)
        .order_by(col(Attempt.created_at).desc())
        .limit(1)
    ).first()

    return BoardData(
        classroom_code=classroom.code,
        classroom_name=classroom.name,
        classroom_grade=classroom.grade,
        teaching_goal=classroom.teaching_goal,
        class_size=classroom.class_size,
        assigned_items=classroom.assigned_items,
        current_exercise=(
            ClassroomExercisePublic(
                id=current_exercise.id,
                classroom_id=current_exercise.classroom_id,
                version_no=current_exercise.version_no,
                title=current_exercise.title,
                status=current_exercise.status,
                item_count=len(current_exercise.snapshot_items),
                created_at=current_exercise.created_at,
                published_at=current_exercise.published_at,
                archived_at=current_exercise.archived_at,
                is_exam=current_exercise.is_exam,
                time_limit_minutes=current_exercise.time_limit_minutes,
            )
            if current_exercise is not None
            else None
        ),
        engine=latest_engine or "mock",
        assignment=(
            AssignmentInfo(
                unit_id=assigned_unit_board.id, title=assigned_unit_board.title
            )
            if assigned_unit_board
            else None
        ),
        submitted_count=submitted_count,
        completed_count=completed_count,
        pending_count=pending_count,
        students=board_students,
        items=skeleton,
    )
