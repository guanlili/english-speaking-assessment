"""教师课堂面板：board 聚合（名单/题位/统计）。"""

import logging
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
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
    ClassWeakSpots,
    InstructionAck,
    PracticeSession,
    Student,
    WeakItem,
    WeakWord,
)
from app.services import exam as exam_service
from app.services import exercise as exercise_service
from app.services.class_gaps import (
    aggregate_low_items,
    aggregate_word_gaps,
    snapshot_label,
)

logger = logging.getLogger(__name__)


def _resolve_board_skeleton(
    session: Any,
    classroom: Any,
    current_exercise: ClassroomExercise | None,
    assigned_unit_board: Any,
) -> tuple[list[Any], Any, list[Any], list[Any], list[Any], bool, list[BoardItem]]:
    """解析本轮题位骨架：发布快照优先，其次按题指派，最后单元/自主路径。

    返回 (朗读篇目, 锚点篇目, 复述句, 问答, 说明, 是否含朗读, 骨架)。
    """
    board_item_objects: tuple[list[Any], list[Any], list[Any], list[Any]] | None = None
    if current_exercise is not None:
        board_item_objects = _snapshot_board_refs(current_exercise)
    else:
        board_item_objects = _assigned_board_refs(session, classroom)
    if board_item_objects is not None:
        return _skeleton_from_published_items(board_item_objects)
    return _skeleton_from_unit_path(session, classroom, assigned_unit_board)


def _snapshot_board_refs(
    current_exercise: ClassroomExercise,
) -> tuple[list[_BoardRef], list[_BoardRef], list[_BoardRef], list[_BoardRef]]:
    """已发布快照优先：名单表也必须按快照渲染，避免题库编辑后题位漂移。"""
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
    return (
        snapshot_refs[AttemptItemType.PASSAGE],
        snapshot_refs[AttemptItemType.REPEAT],
        snapshot_refs[AttemptItemType.QUESTION],
        snapshot_refs[AttemptItemType.INSTRUCTION],
    )


def _assigned_board_refs(
    session: Any, classroom: Any
) -> tuple[list[Any], list[Any], list[Any], list[Any]] | None:
    """按题指派的题位；单元指派路径补空说明桶保持四元组同构。"""
    resolved = exercise_service.resolve_assigned_items(session, classroom)
    # 说明只随按题发布进卷子；旧路径（单元指派）补空桶保持四元组同构
    return (*resolved, []) if resolved is not None else None


def _skeleton_from_published_items(
    board_item_objects: tuple[list[Any], list[Any], list[Any], list[Any]],
) -> tuple[list[Any], Any, list[Any], list[Any], list[Any], bool, list[BoardItem]]:
    """按题发布路径：四类题位直接落骨架，朗读与复述恒含。"""
    (
        board_passages,
        board_sentences,
        board_questions,
        board_instructions,
    ) = board_item_objects
    board_passage = board_passages[0] if board_passages else None
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
    return (
        board_passages,
        board_passage,
        board_sentences,
        board_questions,
        board_instructions,
        True,
        skeleton,
    )


def _skeleton_from_unit_path(
    session: Any, classroom: Any, assigned_unit_board: Any
) -> tuple[list[Any], Any, list[Any], list[Any], list[Any], bool, list[BoardItem]]:
    """单元指派/自主路径：篇目按当前单元取，题位按勾选题型裁剪。"""
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
    return (
        board_passages,
        board_passage,
        board_repeat_sentences,
        board_questions,
        board_instructions,
        include_reading,
        skeleton,
    )


def _render_board_items(
    *,
    student_id: uuid.UUID,
    practice_session: PracticeSession | None,
    attempts: list[Attempt],
    board_passages: list[Any],
    board_repeat_sentences: list[Any],
    board_questions: list[Any],
    board_instructions: list[Any],
    include_reading: bool,
    ack_keys: set[tuple[uuid.UUID, uuid.UUID]],
) -> tuple[list[BoardItem], list[float], list[float], bool]:
    """按当前题单骨架 + 作答渲染题位（纯内存）。

    返回 (题位, 朗读分, 问答分, 是否有待评分)。
    未开始当前轮的学生不渲染骨架（教师面板口径：not_started = 空题单）。
    """
    items: list[BoardItem] = []
    repeat_scores: list[float] = []
    question_scores: list[float] = []
    has_pending = False
    if practice_session is None:
        return items, repeat_scores, question_scores, has_pending

    latest: dict[uuid.UUID, Attempt] = {}
    for attempt in attempts:
        latest[attempt.item_id] = attempt

    # 朗读题位
    if include_reading:
        rendered, pending = _render_passage_items(board_passages, latest, repeat_scores)
        items.extend(rendered)
        has_pending = has_pending or pending
    # 复述题位
    rendered, pending = _render_repeat_items(
        board_repeat_sentences, latest, repeat_scores
    )
    items.extend(rendered)
    has_pending = has_pending or pending
    # 问答题位
    rendered, pending = _render_question_items(board_questions, latest, question_scores)
    items.extend(rendered)
    has_pending = has_pending or pending
    # 已做但不在骨架的问答题（换题产生的额外题）
    rendered, pending = _render_extra_question_items(
        latest, board_questions, question_scores
    )
    items.extend(rendered)
    has_pending = has_pending or pending
    # 说明题位：已读=done / 未读=missing；不进评分与提交统计
    items.extend(_render_instruction_items(board_instructions, student_id, ack_keys))
    return items, repeat_scores, question_scores, has_pending


def _render_item(
    item_id: uuid.UUID,
    item_type: str,
    attempt: Attempt | None,
    scores: list[float],
) -> tuple[BoardItem, bool]:
    """渲染单个题位：无作答记 missing；返回是否待评分；DONE 且有分进对应分桶。"""
    if attempt is None:
        return BoardItem(item_id=item_id, type=item_type, status="missing"), False
    pending = attempt.status in (AttemptStatus.QUEUED, AttemptStatus.SCORING)
    if attempt.status == AttemptStatus.DONE and attempt.overall is not None:
        scores.append(attempt.overall)
    return (
        BoardItem(
            item_id=item_id,
            type=item_type,
            status=attempt.status,
            overall=attempt.overall,
            attempt_id=attempt.id,
            teacher_focus=attempt.teacher_focus,
        ),
        pending,
    )


def _render_passage_items(
    board_passages: list[Any],
    latest: dict[uuid.UUID, Attempt],
    scores: list[float],
) -> tuple[list[BoardItem], bool]:
    """朗读题位（是否渲染由调用方按题型勾选决定）。"""
    items: list[BoardItem] = []
    has_pending = False
    for board_p in board_passages:
        item, pending = _render_item(
            board_p.id, AttemptItemType.PASSAGE, latest.get(board_p.id), scores
        )
        items.append(item)
        has_pending = has_pending or pending
    return items, has_pending


def _render_repeat_items(
    board_repeat_sentences: list[Any],
    latest: dict[uuid.UUID, Attempt],
    scores: list[float],
) -> tuple[list[BoardItem], bool]:
    """复述题位。"""
    items: list[BoardItem] = []
    has_pending = False
    for s in board_repeat_sentences:
        item, pending = _render_item(
            s.id, AttemptItemType.REPEAT, latest.get(s.id), scores
        )
        items.append(item)
        has_pending = has_pending or pending
    return items, has_pending


def _render_question_items(
    board_questions: list[Any],
    latest: dict[uuid.UUID, Attempt],
    scores: list[float],
) -> tuple[list[BoardItem], bool]:
    """骨架内的问答题位。"""
    items: list[BoardItem] = []
    has_pending = False
    for board_q in board_questions:
        item, pending = _render_item(
            board_q.id, AttemptItemType.QUESTION, latest.get(board_q.id), scores
        )
        items.append(item)
        has_pending = has_pending or pending
    return items, has_pending


def _render_extra_question_items(
    latest: dict[uuid.UUID, Attempt],
    board_questions: list[Any],
    scores: list[float],
) -> tuple[list[BoardItem], bool]:
    """已做但不在骨架的问答题（换题产生的额外题）。"""
    skeleton_qids = {q.id for q in board_questions}
    items: list[BoardItem] = []
    has_pending = False
    for item_id, attempt in latest.items():
        if attempt.item_type != AttemptItemType.QUESTION:
            continue
        if item_id in skeleton_qids:
            continue
        item, pending = _render_item(item_id, AttemptItemType.QUESTION, attempt, scores)
        items.append(item)
        has_pending = has_pending or pending
    return items, has_pending


def _render_instruction_items(
    board_instructions: list[Any],
    student_id: uuid.UUID,
    ack_keys: set[tuple[uuid.UUID, uuid.UUID]],
) -> list[BoardItem]:
    """说明题位：已读=done / 未读=missing；不进评分与提交统计。"""
    return [
        BoardItem(
            item_id=board_i.id,
            type=AttemptItemType.INSTRUCTION,
            status=(
                AttemptStatus.DONE
                if (student_id, board_i.id) in ack_keys
                else "missing"
            ),
        )
        for board_i in board_instructions
    ]


def _board_round_status(stat_items: list[BoardItem], has_pending: bool) -> str:
    """统一统计口径：not_started / scoring / in_progress / all_done / has_failures。"""
    non_missing = [i for i in stat_items if i.status != "missing"]
    terminal = [
        i for i in stat_items if i.status in (AttemptStatus.DONE, AttemptStatus.FAILED)
    ]
    if not non_missing:
        return "not_started"
    if has_pending:
        return "scoring"
    if len(terminal) < len(stat_items):
        return "in_progress"
    if all(i.status == AttemptStatus.DONE for i in terminal):
        return "all_done"
    return "has_failures"


def _exam_monitor_fields(
    practice_session: PracticeSession | None, exam: ClassroomExercise | None
) -> tuple[int | None, int | None, int | None, bool | None]:
    """模考监考：切屏次数/离屏时长/用时/是否交卷（非考试或无会话时全 None）。"""
    if exam is None or not exam.is_exam:
        return None, None, None, None
    if practice_session is None or practice_session.exam_started_at is None:
        # 终结已在循环外批量完成；这里只读字段
        return None, None, None, None
    return (
        practice_session.tab_switch_count,
        practice_session.tab_switch_seconds,
        exam_service.exam_time_used_seconds(practice_session),
        practice_session.exam_ended_at is not None,
    )


def _avg_rounded(scores: list[int | float]) -> float | None:
    """一组分数取一位小数的均值；空集合返回 None。

    跟读均分与问答均分共用同一口径，原实现把这段写了两遍。
    """
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


def _student_row_stats(
    items: list[BoardItem], has_pending: bool
) -> tuple[str, int, int, bool, bool]:
    """按题单渲染结果算整轮统计。

    返回 (round_status, done_count, total_count, submitted, completed)：
    - instruction 说明题无作答、不参与统计（只展示已读状态）；
    - total_count 与 done_count 同口径，都排除 instruction；
    - submitted 判据是「至少一题不是 missing」；
    - completed 与 round_status 的两档终态一致。
    """
    stat_items = [i for i in items if i.type != AttemptItemType.INSTRUCTION]
    round_status = _board_round_status(stat_items, has_pending)
    done_count = sum(1 for i in stat_items if i.status == AttemptStatus.DONE)
    submitted = any(i.status != "missing" for i in stat_items)
    completed = round_status in ("all_done", "has_failures")
    return round_status, done_count, len(stat_items), submitted, completed


def _student_is_inactive(
    student: Student,
    recent_student_ids: set[uuid.UUID],
    week_ago: datetime,
) -> bool:
    """入班早于统计窗口、且窗口内没有作答，才算 7 日不活跃。"""
    joined_before_window = (
        student.created_at is not None
        and student.created_at.astimezone(ZoneInfo(settings.PRACTICE_TZ)).date()
        < week_ago.date()
    )
    return joined_before_window and student.id not in recent_student_ids


def _student_row_payload(
    student: Student,
    items: list[BoardItem],
    *,
    round_status: str,
    done_count: int,
    total_count: int,
    repeat_scores: list[int | float],
    question_scores: list[int | float],
    has_pending: bool,
    exam_fields: tuple[int | None, int | None, int | None, bool | None],
    inactive: bool,
) -> BoardStudent:
    """把已算好的各字段拼成一行 BoardStudent（纯构造，无计算）。"""
    exam_switches, exam_switch_seconds, exam_used, exam_ended_flag = exam_fields
    return BoardStudent(
        student_id=student.id,
        display_name=student.display_name,
        suffix=student.suffix,
        done_count=done_count,
        total_count=total_count,
        repeat_avg=_avg_rounded(repeat_scores),
        question_avg=_avg_rounded(question_scores),
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


def _build_student_row(
    student: Student,
    practice_session: PracticeSession | None,
    attempts: list[Attempt],
    *,
    board_passages: list[Any],
    board_repeat_sentences: list[Any],
    board_questions: list[Any],
    board_instructions: list[Any],
    include_reading: bool,
    ack_keys: set[tuple[uuid.UUID, uuid.UUID]],
    recent_student_ids: set[uuid.UUID],
    week_ago: datetime,
    exam: ClassroomExercise | None,
) -> tuple[BoardStudent, bool, bool, bool]:
    """按当前题单骨架 + 作答渲染单个学生行（纯内存组装，无 DB 往返）。

    返回 (行数据, 是否已提交, 是否已完成, 是否评分中)。
    """
    items, repeat_scores, question_scores, has_pending = _render_board_items(
        student_id=student.id,
        practice_session=practice_session,
        attempts=attempts,
        board_passages=board_passages,
        board_repeat_sentences=board_repeat_sentences,
        board_questions=board_questions,
        board_instructions=board_instructions,
        include_reading=include_reading,
        ack_keys=ack_keys,
    )
    round_status, done_count, total_count, submitted, completed = _student_row_stats(
        items, has_pending
    )
    inactive = _student_is_inactive(student, recent_student_ids, week_ago)
    exam_fields = _exam_monitor_fields(practice_session, exam)
    row = _student_row_payload(
        student,
        items,
        round_status=round_status,
        done_count=done_count,
        total_count=total_count,
        repeat_scores=repeat_scores,
        question_scores=question_scores,
        has_pending=has_pending,
        exam_fields=exam_fields,
        inactive=inactive,
    )
    return row, submitted, completed, has_pending


def _pick_student_sessions(
    student_sessions: dict[uuid.UUID, list[PracticeSession]],
    current_exercise: ClassroomExercise | None,
    assigned_passage_id: uuid.UUID | None,
) -> dict[uuid.UUID, PracticeSession]:
    """A→B→A 修复：优先匹配当前指派篇目的会话，而非仅按创建时间取最新。"""
    by_student: dict[uuid.UUID, PracticeSession] = {}
    for sid, sessions in student_sessions.items():
        if current_exercise is not None:
            matching = [s for s in sessions if s.assignment_id == current_exercise.id]
            if matching:
                by_student[sid] = matching[-1]
            # 当前发布版本没有开始过，就不要回退到已归档版本或课后作业会话。
            continue
        self_practice = [s for s in sessions if s.assignment_id is None]
        if assigned_passage_id is not None:
            matching = [s for s in self_practice if s.passage_id == assigned_passage_id]
            if matching:
                by_student[sid] = matching[-1]
                continue
        if self_practice:
            by_student[sid] = self_practice[-1]
    return by_student


def _finalize_exam_sessions(
    session: Any,
    session_by_student: dict[uuid.UUID, PracticeSession],
    current_exercise: ClassroomExercise | None,
) -> None:
    """模考批量终结：预取全班首答后纯计算、单次 commit。

    替代学生循环内的逐会话 finalize（每会话 2 条查询 + 整行大 JSON，
    监考轮询热路径）。
    """
    if current_exercise is None or not current_exercise.is_exam:
        return
    started = [
        ps for ps in session_by_student.values() if ps.exam_started_at is not None
    ]
    if not started:
        return
    first_by_session = exam_service.first_submitted_by_session(
        session, [ps.id for ps in started]
    )
    exam_service.finalize_if_expired_batch(
        session, started, current_exercise, first_by_session
    )


def _recent_active_student_ids(
    session: Any, student_ids: list[uuid.UUID], week_ago_utc: datetime
) -> set[uuid.UUID]:
    """7 日活跃判定只需「谁有过作答」：单列 distinct，不整行加载（含大 JSON 列）。"""
    return set(
        session.exec(
            select(Attempt.student_id)
            .where(
                Attempt.student_id.in_(student_ids),  # type: ignore
                Attempt.created_at >= week_ago_utc,  # type: ignore
            )
            .distinct()
        ).all()
    )


def _load_attempts_map(
    session: Any,
    student_ids: list[uuid.UUID],
    practice_session_ids: list[uuid.UUID],
) -> dict[tuple[uuid.UUID, uuid.UUID], list[Attempt]]:
    """预取所有学生的作答（一次查询替代 N+1）。

    load_only 只取看板用到的列：item_snapshot/transcript/rubric 等 JSON 大列
    不进内存（轮询热路径，全班 × 多题时每行可省数 KB）。
    """
    attempts_map: dict[tuple[uuid.UUID, uuid.UUID], list[Attempt]] = {}
    if not practice_session_ids:
        return attempts_map
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
                Attempt.teacher_focus,  # ty: ignore[invalid-argument-type]
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
        attempts_map.setdefault(key, []).append(attempt)
    return attempts_map


def _load_ack_keys(
    session: Any,
    practice_session_ids: list[uuid.UUID],
    board_instructions: list[Any],
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """说明「已读」预取：本面板各学生会话的 ack（学生, 题目）集合。"""
    if not practice_session_ids or not board_instructions:
        return set()
    acks = session.exec(
        select(InstructionAck).where(
            InstructionAck.session_id.in_(practice_session_ids)  # type: ignore
        )
    ).all()
    return {(ack.student_id, ack.item_id) for ack in acks}


def _build_board_rows(
    students: Sequence[Student],
    session_by_student: dict[uuid.UUID, PracticeSession],
    attempts_map: dict[tuple[uuid.UUID, uuid.UUID], list[Attempt]],
    *,
    board_passages: list[Any],
    board_repeat_sentences: list[Any],
    board_questions: list[Any],
    board_instructions: list[Any],
    include_reading: bool,
    ack_keys: set[tuple[uuid.UUID, uuid.UUID]],
    recent_student_ids: set[uuid.UUID],
    week_ago: datetime,
    exam: ClassroomExercise | None,
) -> tuple[list[BoardStudent], int, int, int]:
    """逐个学生渲染名单行，返回 (行集合, 已提交数, 已完成数, 评分中数)。"""
    rows: list[BoardStudent] = []
    submitted_count = 0
    completed_count = 0
    pending_count = 0
    for student in students:
        practice_session = session_by_student.get(student.id)
        attempts = (
            attempts_map.get((student.id, practice_session.id), [])
            if practice_session is not None
            else []
        )
        row, is_submitted, is_completed, is_pending = _build_student_row(
            student,
            practice_session,
            attempts,
            board_passages=board_passages,
            board_repeat_sentences=board_repeat_sentences,
            board_questions=board_questions,
            board_instructions=board_instructions,
            include_reading=include_reading,
            ack_keys=ack_keys,
            recent_student_ids=recent_student_ids,
            week_ago=week_ago,
            exam=exam,
        )
        submitted_count += 1 if is_submitted else 0
        completed_count += 1 if is_completed else 0
        pending_count += 1 if is_pending else 0
        rows.append(row)
    return rows, submitted_count, completed_count, pending_count


def _sort_board_students(rows: list[BoardStudent]) -> None:
    """名单排序：交了的在前，其次按完成数降序，最后按名字。"""
    rows.sort(
        key=lambda s: (
            -min(s.done_count, 1),
            -s.done_count,
            s.display_name,
        )
    )


def _board_payload(
    session: SessionDep,
    classroom: Any,
    skeleton: Any,
    rows: list[BoardStudent],
    counts: tuple[int, int, int],
    *,
    current_exercise: ClassroomExercise | None,
    assigned_unit_board: Any,
) -> BoardData:
    """组装名单表响应（纯构造，无额外查询）。

    counts 是 (submitted, completed, pending) 三元组，与 `_build_board_rows`
    的返回后三值同序。
    """
    submitted_count, completed_count, pending_count = counts
    homework = _homework_exercise_of(session, classroom)
    return BoardData(
        classroom_code=classroom.code,
        classroom_name=classroom.name,
        classroom_grade=classroom.grade,
        teaching_goal=classroom.teaching_goal,
        class_size=classroom.class_size,
        assigned_items=classroom.assigned_items,
        current_exercise=_exercise_public(current_exercise),
        engine=_latest_scoring_engine(session),
        assignment=_board_assignment(assigned_unit_board),
        submitted_count=submitted_count,
        completed_count=completed_count,
        pending_count=pending_count,
        students=rows,
        items=skeleton,
        homework_title=homework.title if homework is not None else None,
        homework_exercise_id=homework.id if homework is not None else None,
    )


@router.get("/{code}/board", response_model=BoardData)
def read_class_board(session: SessionDep, code: str, current_user: CurrentUser) -> Any:
    """老师名单表（PRD §8.5 2 周）：谁交了、每题分数、音频；允许先显示评分中。

    需要教师身份：本课指派教师或管理员（课堂码不能当教师凭据）。
    """
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    today = _today_in_practice_tz()

    current_exercise = _current_exercise_of(session, classroom)
    assigned_unit_board = _assignment_unit(session, classroom)
    (
        board_passages,
        board_passage,
        board_repeat_sentences,
        board_questions,
        board_instructions,
        include_reading,
        skeleton,
    ) = _resolve_board_skeleton(
        session, classroom, current_exercise, assigned_unit_board
    )
    students, session_by_student = _load_board_sessions(
        session, classroom, today, current_exercise, board_passage
    )

    # 7 日未练口径：加入超过 7 天且窗口内无任何作答（US-10 简化实现）
    week_ago, week_ago_utc = _recent_active_window()
    student_ids = [s.id for s in students]
    recent_student_ids = _recent_active_student_ids(session, student_ids, week_ago_utc)

    practice_session_ids = [ps.id for ps in session_by_student.values()]
    attempts_map = _load_attempts_map(session, student_ids, practice_session_ids)
    ack_keys = _load_ack_keys(session, practice_session_ids, board_instructions)

    board_students, submitted_count, completed_count, pending_count = _build_board_rows(
        students,
        session_by_student,
        attempts_map,
        board_passages=board_passages,
        board_repeat_sentences=board_repeat_sentences,
        board_questions=board_questions,
        board_instructions=board_instructions,
        include_reading=include_reading,
        ack_keys=ack_keys,
        recent_student_ids=recent_student_ids,
        week_ago=week_ago,
        exam=current_exercise,
    )
    _sort_board_students(board_students)
    return _board_payload(
        session,
        classroom,
        skeleton,
        board_students,
        (submitted_count, completed_count, pending_count),
        current_exercise=current_exercise,
        assigned_unit_board=assigned_unit_board,
    )


def _current_exercise_of(session: Any, classroom: Any) -> ClassroomExercise | None:
    """当前课上发布版（未发布则 None）。"""
    if classroom.current_exercise_id is None:
        return None
    return session.get(ClassroomExercise, classroom.current_exercise_id)


def _homework_exercise_of(session: Any, classroom: Any) -> ClassroomExercise | None:
    """当前课后作业版（未发布则 None）。"""
    if classroom.homework_exercise_id is None:
        return None
    return session.get(ClassroomExercise, classroom.homework_exercise_id)


def _load_board_sessions(
    session: Any,
    classroom: Any,
    today: Any,
    current_exercise: ClassroomExercise | None,
    board_passage: Any,
) -> tuple[list[Student], dict[uuid.UUID, PracticeSession]]:
    """班内学生 + 今日 daily 会话，按学生分组并挑出本轮；顺带收尾过期考试会话。"""
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

    student_sessions: dict[uuid.UUID, list[PracticeSession]] = {}
    for s in today_sessions:
        student_sessions.setdefault(s.student_id, []).append(s)
    assigned_passage_id = board_passage.id if board_passage else None
    session_by_student = _pick_student_sessions(
        student_sessions, current_exercise, assigned_passage_id
    )
    _finalize_exam_sessions(session, session_by_student, current_exercise)
    return list(students), session_by_student


def _recent_active_window() -> tuple[datetime, datetime]:
    """7 日未练口径的窗口：本地零点往前 7 天，及其 UTC 对应。"""
    now = datetime.now(ZoneInfo(settings.PRACTICE_TZ))
    week_ago = (now - timedelta(days=7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return week_ago, week_ago.astimezone(ZoneInfo("UTC"))


def _exercise_public(
    exercise: ClassroomExercise | None,
) -> ClassroomExercisePublic | None:
    """发布版对外摘要；item_count 不计说明题位。"""
    if exercise is None:
        return None
    return ClassroomExercisePublic(
        id=exercise.id,
        classroom_id=exercise.classroom_id,
        version_no=exercise.version_no,
        title=exercise.title,
        status=exercise.status,
        item_count=sum(i.get("type") != "instruction" for i in exercise.snapshot_items),
        created_at=exercise.created_at,
        published_at=exercise.published_at,
        archived_at=exercise.archived_at,
        is_exam=exercise.is_exam,
        time_limit_minutes=exercise.time_limit_minutes,
    )


def _latest_scoring_engine(session: Any) -> str:
    """最近一次完成作答用的引擎（面板页脚展示），无作答则 mock。"""
    latest_engine = session.exec(
        select(Attempt.engine)
        .where(Attempt.status == AttemptStatus.DONE)
        .order_by(col(Attempt.created_at).desc())
        .limit(1)
    ).first()
    return latest_engine or "mock"


def _board_assignment(unit: Any) -> AssignmentInfo | None:
    """当前单元指派摘要（无则 None）。"""
    if unit is None:
        return None
    return AssignmentInfo(unit_id=unit.id, title=unit.title)


def _weak_spot_session_ids(
    session: SessionDep,
    classroom_id: uuid.UUID,
    exercise_id: uuid.UUID,
    today: date,
) -> list[uuid.UUID]:
    """本节课当前作业在今日 daily 模式下已开的练习会话 id。"""
    return list(
        session.exec(
            select(PracticeSession.id).where(
                PracticeSession.classroom_id == classroom_id,
                PracticeSession.session_date == today,
                PracticeSession.mode == "daily",
                PracticeSession.assignment_id == exercise_id,
            )
        ).all()
    )


def _load_weak_attempts(
    session: SessionDep, session_ids: list[uuid.UUID]
) -> list[Attempt]:
    """取这些会话里已出分（DONE）的作答。

    只读已出分的转写，不进名单轮询；load_only 窄列避免 rubric 大 JSON 进内存。
    """
    return list(
        session.exec(
            select(Attempt)
            .options(
                load_only(
                    Attempt.id,  # ty: ignore[invalid-argument-type]
                    Attempt.student_id,  # ty: ignore[invalid-argument-type]
                    Attempt.item_id,  # ty: ignore[invalid-argument-type]
                    Attempt.item_type,  # ty: ignore[invalid-argument-type]
                    Attempt.overall,  # ty: ignore[invalid-argument-type]
                    Attempt.transcript,  # ty: ignore[invalid-argument-type]
                    Attempt.item_snapshot,  # ty: ignore[invalid-argument-type]
                    Attempt.created_at,  # ty: ignore[invalid-argument-type]
                    Attempt.status,  # ty: ignore[invalid-argument-type]
                )
            )
            .where(
                col(Attempt.session_id).in_(session_ids),
                Attempt.status == AttemptStatus.DONE,
            )
            .order_by(col(Attempt.created_at))
        ).all()
    )


def _split_weak_rows(
    attempts: list[Attempt],
) -> tuple[
    list[tuple[uuid.UUID, str, str]],
    list[tuple[uuid.UUID, uuid.UUID, str, str, int | None]],
]:
    """同一学生同一题只留最后一次作答，并分流成「漏词样本」与「题目样本」两组。

    返回 (word_rows, item_rows)：word_rows 只收 passage/repeat（跟读类才有
    参考文本可做漏词比对），item_rows 收全部题型供偏低题判定。
    """
    latest: dict[tuple[uuid.UUID, uuid.UUID], Attempt] = {}
    for attempt in attempts:
        if attempt.student_id is None:
            continue
        latest[(attempt.student_id, attempt.item_id)] = attempt
    word_rows: list[tuple[uuid.UUID, str, str]] = []
    item_rows: list[tuple[uuid.UUID, uuid.UUID, str, str, int | None]] = []
    for attempt in latest.values():
        assert attempt.student_id is not None
        snapshot = (
            attempt.item_snapshot if isinstance(attempt.item_snapshot, dict) else None
        )
        raw_text = snapshot.get("text") if snapshot is not None else None
        reference = raw_text if isinstance(raw_text, str) else ""
        if attempt.item_type in (AttemptItemType.PASSAGE, AttemptItemType.REPEAT):
            word_rows.append((attempt.student_id, reference, attempt.transcript or ""))
        item_rows.append(
            (
                attempt.student_id,
                attempt.item_id,
                attempt.item_type,
                snapshot_label(snapshot, attempt.item_type),
                attempt.overall,
            )
        )
    return word_rows, item_rows


def _weak_spots_payload(
    word_rows: list[tuple[uuid.UUID, str, str]],
    item_rows: list[tuple[uuid.UUID, uuid.UUID, str, str, int | None]],
) -> ClassWeakSpots:
    """把两类样本交给聚合器，产出前端要的漏词榜与偏低题榜。"""
    return ClassWeakSpots(
        word_gaps=[
            WeakWord(word=word, student_count=count)
            for word, count in aggregate_word_gaps(word_rows)
        ],
        low_items=[
            WeakItem.model_validate(item) for item in aggregate_low_items(item_rows)
        ],
    )


@router.get("/{code}/weak-spots", response_model=ClassWeakSpots)
def read_class_weak_spots(
    session: SessionDep, code: str, current_user: CurrentUser
) -> ClassWeakSpots:
    """今日当前发布的共同漏词和偏低题目。只读已出分的转写，不进名单轮询。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    exercise = (
        session.get(ClassroomExercise, classroom.current_exercise_id)
        if classroom.current_exercise_id is not None
        else None
    )
    if exercise is None:
        return ClassWeakSpots(word_gaps=[], low_items=[])
    today = _today_in_practice_tz()
    session_ids = _weak_spot_session_ids(session, classroom.id, exercise.id, today)
    if not session_ids:
        return ClassWeakSpots(word_gaps=[], low_items=[])
    word_rows, item_rows = _split_weak_rows(_load_weak_attempts(session, session_ids))
    return _weak_spots_payload(word_rows, item_rows)
