"""学生进步轨迹与单元学习路径。"""

import logging
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query
from sqlalchemy.orm import load_only
from sqlmodel import col, or_, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    StudentUserDep,
)
from app.api.routes.class_shared import (
    _assignment_unit,
    _get_classroom,
    _get_student_of_classroom,
    _question_band_for_session,
    _require_classroom_teacher,
    _student_profile_of,
    router,
)
from app.core.config import settings
from app.models import (
    AssignmentInfo,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    ClassroomExercise,
    DimensionPoint,
    LearningPath,
    MySessionSummary,
    Passage,
    PathUnit,
    PracticeSession,
    Student,
    StudentDiagnostics,
    TrailData,
    Unit,
)
from app.scoring.bands import BAND_ORDER
from app.scoring.heuristic import align_words
from app.services import exam as exam_service
from app.services import trail as trail_service

logger = logging.getLogger(__name__)


def _feedback_locked_exam_session_ids(
    session: SessionDep, student: Student
) -> set[uuid.UUID]:
    """考试反馈遮罩共用的锁定会话集合（trail / diagnostics / my-sessions 同口径）。

    只排除「已开始且未终结」的考试会话：终结前分数/转写/建议一律不下发。
    查询期间首次评分也可能完成：先固定提交上界，再检查学生全部未落结束
    的考试会话（不能只检查「已有 done 作答」的会话，否则首答刚出分会漏遮罩）。
    """
    exam_rows = session.exec(
        select(PracticeSession, ClassroomExercise)
        .join(
            ClassroomExercise,
            col(PracticeSession.assignment_id) == col(ClassroomExercise.id),
        )
        .where(
            PracticeSession.student_id == student.id,
            col(PracticeSession.exam_ended_at).is_(None),
            ClassroomExercise.is_exam,
        )
    ).all()
    first = exam_service.first_submitted_by_session(
        session, [ps.id for ps, _ in exam_rows if ps.exam_started_at is not None]
    )
    return {
        ps.id
        for ps, exercise in exam_rows
        if exam_service.exam_feedback_locked(
            session, ps, exercise, first_submitted=first.get(ps.id, {})
        )
    }


@router.get("/{code}/trail", response_model=TrailData)
def read_student_trail(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
    days: int = Query(default=90, ge=1, le=3650, description="查询最近多少天的轨迹"),
    student_id: uuid.UUID | None = Query(
        default=None, description="教师查看指定学生；学生查看自己时省略"
    ),
) -> Any:
    """学生进步轨迹（PRD US-09）：按练习日聚合口语参考分与词汇档。

    学生账号省略 student_id 看自己；教师/管理员传 student_id（授权范围内）。
    """
    classroom = _get_classroom(session, code)
    if current_user.role == "student" and not current_user.is_superuser:
        student = _student_profile_of(session, classroom, current_user)
    else:
        if student_id is None:
            raise HTTPException(status_code=422, detail="教师查看需传 student_id")
        _require_classroom_teacher(classroom, current_user)
        student = _get_student_of_classroom(session, classroom, student_id)

    tz = ZoneInfo(settings.PRACTICE_TZ)
    now_tz = datetime.now(tz)
    window_start = (now_tz - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    window_start_utc = window_start.astimezone(ZoneInfo("UTC"))

    # 查询期间首次评分也可能完成：先固定提交上界，再检查学生全部未落结束
    # 的考试会话（不能只检查「已有 done 作答」的会话，否则首答刚出分会漏遮罩）。
    as_of = datetime.now(UTC)
    locked_session_ids: set[uuid.UUID] = set()
    if current_user.role == "student" and not current_user.is_superuser:
        locked_session_ids = _feedback_locked_exam_session_ids(session, student)
    summary = trail_service.summarize(
        session,
        student.id,
        window_start_utc,
        settings.PRACTICE_TZ,
        locked_session_ids,
        as_of=as_of,
    )

    band_change: str | None = None
    # 最近一轮档位动向（PRD US-10）：对比最近会话的调整后档与开始档。
    # 先幂等触发一次档位计算（作答后学生可能没再打开 /today）。
    # 只消费最新一条会话，limit(1) 即可（原 limit(100) 取整行再丢 99 条）
    latest = session.exec(
        select(PracticeSession)
        .where(PracticeSession.student_id == student.id)
        .order_by(col(PracticeSession.created_at).desc())
        .limit(1)
    ).first()
    if latest is not None:
        _question_band_for_session(session, latest, student)
        # question_band 已写入才算完成过一轮调整；复述未完成 → 无建议
        if latest.question_band is not None:
            if latest.question_band == latest.band:
                band_change = "keep"
            elif BAND_ORDER.index(latest.question_band) > BAND_ORDER.index(latest.band):
                band_change = "up"
            else:
                band_change = "down"

    return TrailData(
        classroom_code=classroom.code,
        student_id=student.id,
        display_name=student.display_name,
        suffix=student.suffix,
        sessions=summary.sessions,
        band_change=band_change,
        total_minutes=summary.total_minutes,
        vocab_counts=summary.vocab_counts,
        level_counts=summary.level_counts,
    )


@router.get("/{code}/diagnostics/me", response_model=StudentDiagnostics)
def read_student_diagnostics(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
    days: int = Query(default=90, ge=1, le=3650, description="查询最近多少天"),
    student_id: uuid.UUID | None = Query(
        default=None, description="教师查看指定学生；学生查看自己时省略"
    ),
) -> Any:
    """个人弱项诊断（成长页诊断卡）：高频漏词 + 四维均值/最弱维度 + 四维趋势。

    路径用 /diagnostics/me 与教师端全班问题列表（/diagnostics，ClassroomDiagnostics）
    区分：本接口是学生个人数据，只取单生窗口内 DONE 作答。
    与 trail 同口径：排除未终结考试的反馈；漏词来自词级对齐（新作答）或
    item_snapshot 回退对齐（历史作答），error/missing 均计入。
    """
    classroom = _get_classroom(session, code)
    if current_user.role == "student" and not current_user.is_superuser:
        student = _student_profile_of(session, classroom, current_user)
    else:
        if student_id is None:
            raise HTTPException(status_code=422, detail="教师查看需传 student_id")
        _require_classroom_teacher(classroom, current_user)
        student = _get_student_of_classroom(session, classroom, student_id)

    tz = ZoneInfo(settings.PRACTICE_TZ)
    now_tz = datetime.now(tz)
    window_start = (now_tz - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    window_start_utc = window_start.astimezone(ZoneInfo("UTC"))
    as_of = datetime.now(UTC)
    locked_session_ids = (
        _feedback_locked_exam_session_ids(session, student)
        if current_user.role == "student" and not current_user.is_superuser
        else set()
    )

    conditions = [
        col(Attempt.student_id) == student.id,
        col(Attempt.status) == AttemptStatus.DONE,
        col(Attempt.created_at) >= window_start_utc,
        col(Attempt.created_at) <= as_of,
    ]
    if locked_session_ids:
        conditions.append(
            or_(
                col(Attempt.session_id).is_(None),
                col(Attempt.session_id).not_in(locked_session_ids),
            )
        )
    rows = session.exec(
        select(Attempt)
        .where(*conditions)
        .order_by(col(Attempt.created_at), col(Attempt.id))
        .options(
            load_only(
                Attempt.item_type,  # ty: ignore[invalid-argument-type]
                Attempt.item_snapshot,  # ty: ignore[invalid-argument-type]
                Attempt.transcript,  # ty: ignore[invalid-argument-type]
                Attempt.word_alignment,  # ty: ignore[invalid-argument-type]
                Attempt.rubric,  # ty: ignore[invalid-argument-type]
                Attempt.created_at,  # ty: ignore[invalid-argument-type]
            )
        )
    ).all()

    missed: Counter[str] = Counter()
    rubric_points: list[DimensionPoint] = []
    dim_sums: dict[str, float] = {}
    dim_count = 0
    for attempt in rows:
        if attempt.item_type in (AttemptItemType.PASSAGE, AttemptItemType.REPEAT):
            _accumulate_missed_words(missed, attempt)
        elif attempt.item_type == AttemptItemType.QUESTION:
            created_at = attempt.created_at
            if created_at is None:
                continue
            rubric = attempt.rubric if isinstance(attempt.rubric, dict) else None
            if rubric is None:
                continue
            values = {
                key: rubric.get(key)
                for key in ("fluency", "vocabulary", "grammar", "task")
            }
            if not all(isinstance(v, (int, float)) for v in values.values()):
                continue
            # all() 已保证四个维度都是数值，这里收窄为 float 供求和/趋势使用
            floats: dict[str, float] = {
                key: float(value)
                for key, value in values.items()
                if isinstance(value, (int, float))
            }
            for key, value in floats.items():
                dim_sums[key] = dim_sums.get(key, 0.0) + value
            dim_count += 1
            date_key = created_at.astimezone(tz).date().isoformat()
            rubric_points.append(
                DimensionPoint(
                    date=date_key,
                    fluency=floats["fluency"],
                    vocabulary=floats["vocabulary"],
                    grammar=floats["grammar"],
                    task=floats["task"],
                )
            )

    means: dict[str, float] = {}
    for key in ("fluency", "vocabulary", "grammar", "task"):
        if key in dim_sums and dim_count:
            means[key] = round(dim_sums[key] / dim_count, 1)
    weakest: str | None = None
    if means:
        weakest = min(
            ("fluency", "vocabulary", "grammar", "task"),
            key=lambda k: means[k],
        )

    top_missed: list[dict[str, object]] = [
        {"word": word, "count": count} for word, count in missed.most_common(12)
    ]
    return StudentDiagnostics(
        classroom_code=classroom.code,
        student_id=student.id,
        top_missed_words=top_missed,
        dimension_means=means,
        weakest_dimension=weakest,
        dimension_count=dim_count,
        dimension_trend=rubric_points[-14:],
    )


def _accumulate_missed_words(counter: Counter[str], attempt: Attempt) -> None:
    """从词级对齐统计漏读/错读词；旧作答（无对齐）用题面快照文本现算。"""
    alignment = (
        attempt.word_alignment if isinstance(attempt.word_alignment, dict) else None
    )
    words = alignment.get("words") if alignment is not None else None
    if isinstance(words, list):
        for entry in words:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") in ("missing", "error"):
                text = entry.get("text")
                if isinstance(text, str) and text:
                    counter[text.lower()] += 1
        return
    snapshot = (
        attempt.item_snapshot if isinstance(attempt.item_snapshot, dict) else None
    )
    ref = snapshot.get("text") if snapshot else None
    if not isinstance(ref, str) or not ref or not attempt.transcript:
        return
    aligned = align_words(ref, attempt.transcript)
    for entry in aligned["words"]:
        if entry["status"] in ("missing", "error"):
            counter[entry["text"].lower()] += 1


@router.get("/{code}/path", response_model=LearningPath)
def read_learning_path(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
) -> Any:
    """学习路径：单元有序 + 完成轮数/星级 + 锁定（主题探索与首页消费）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)

    units = session.exec(
        select(Unit).where(Unit.is_active).order_by(col(Unit.order_index))
    ).all()
    # 全表只为建 passage→unit 映射与各单元首篇：裁掉正文等大列
    passages = session.exec(
        select(Passage).options(
            load_only(
                Passage.id,  # ty: ignore[invalid-argument-type]
                Passage.unit_id,  # ty: ignore[invalid-argument-type]
                Passage.is_active,  # ty: ignore[invalid-argument-type]
            )
        )
    ).all()
    settled = session.exec(
        select(PracticeSession).where(
            PracticeSession.student_id == student.id,
            col(PracticeSession.stars).is_not(None),
            col(PracticeSession.passage_id).is_not(None),
        )
    ).all()
    # unit → {rounds, best_stars}
    stats: dict = {}
    passage_to_unit = {p.id: p.unit_id for p in passages}
    for ps in settled:
        uid = passage_to_unit.get(ps.passage_id)
        if uid is None:
            continue
        bucket = stats.setdefault(uid, {"rounds": 0, "best": 0})
        bucket["rounds"] += 1
        bucket["best"] = max(bucket["best"], ps.stars or 0)

    assigned_unit = _assignment_unit(session, classroom)
    result: list[PathUnit] = []
    prev_done = True  # 第一关始终解锁
    for unit in units:
        unit_passage = next(
            (p for p in passages if p.unit_id == unit.id and p.is_active), None
        )
        done = stats.get(unit.id, {"rounds": 0, "best": 0})
        locked = (
            (not classroom.unlock_all)
            and not prev_done
            and (assigned_unit is None or unit.id != assigned_unit.id)
        )
        result.append(
            PathUnit(
                unit_id=unit.id,
                order_index=unit.order_index,
                title=unit.title,
                topic=unit.topic,
                rounds_done=done["rounds"],
                best_stars=done["best"] if done["rounds"] else None,
                locked=locked,
                passage_id=unit_passage.id if unit_passage else None,
            )
        )
        prev_done = done["rounds"] > 0

    return LearningPath(
        classroom_code=classroom.code,
        unlock_all=classroom.unlock_all,
        assignment=(
            AssignmentInfo(unit_id=assigned_unit.id, title=assigned_unit.title)
            if assigned_unit
            else None
        ),
        units=result,
    )


@router.get("/{code}/my-sessions", response_model=list[MySessionSummary])
def read_my_sessions(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    limit: int = Query(default=30, ge=1, le=100),
) -> Any:
    """学生本人的历史练习列表（按练习日倒序，最近 N 轮）。

    每行给出该轮的完成口径（题单位最新作答 done 计数，与 board 一致）
    与参考分均值，供「我的成长」页跳 /p/{code}/result?session=<id> 回看
    详细反馈。仅学生本人凭证；考试未终结的轮次参考分不下发（与
    trail/today 的模考遮罩口径一致，完成计数照常——学生本就可见状态）。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)

    return _session_history(session, student.id, limit, mask_exam_feedback=True)


@router.get(
    "/{code}/students/{student_id}/sessions", response_model=list[MySessionSummary]
)
def read_student_sessions(
    session: SessionDep,
    code: str,
    student_id: uuid.UUID,
    current_user: CurrentUser,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """授权教师回看学生所有练习/考试轮次，包含自主练习与历史发布。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    student = _get_student_of_classroom(session, classroom, student_id)
    return _session_history(
        session, student.id, limit, mask_exam_feedback=False, offset=offset
    )


def _session_history(
    session: SessionDep,
    student_id: uuid.UUID,
    limit: int,
    *,
    mask_exam_feedback: bool,
    offset: int = 0,
) -> list[MySessionSummary]:
    sessions = session.exec(
        select(PracticeSession)
        .where(PracticeSession.student_id == student_id)
        .order_by(
            col(PracticeSession.session_date).desc(),
            col(PracticeSession.created_at).desc(),
            col(PracticeSession.id).desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()
    if not sessions:
        return []

    # 批量预取：作答（最新一次覆盖，与 board/latest 口径一致）+ 绑定练习
    latest_by_session: dict[uuid.UUID, dict[uuid.UUID, Attempt]] = {}
    for attempt in session.exec(
        select(Attempt)
        .options(
            # 列表只要小列：transcript/item_snapshot 等 JSON 大列不进内存
            load_only(
                Attempt.id,  # ty: ignore[invalid-argument-type]
                Attempt.session_id,  # ty: ignore[invalid-argument-type]
                Attempt.item_id,  # ty: ignore[invalid-argument-type]
                Attempt.status,  # ty: ignore[invalid-argument-type]
                Attempt.overall,  # ty: ignore[invalid-argument-type]
            )
        )
        .where(
            col(Attempt.session_id).in_(  # type: ignore[operator]
                [ps.id for ps in sessions]
            )
        )
        .order_by(col(Attempt.created_at))
    ).all():
        sid = attempt.session_id
        if sid is None:  # in_ 过滤后理论不可达，类型收窄用
            continue
        latest_by_session.setdefault(sid, {})[attempt.item_id] = attempt

    assignment_ids = {
        ps.assignment_id for ps in sessions if ps.assignment_id is not None
    }
    exercises_by_id: dict[uuid.UUID, ClassroomExercise] = {}
    if assignment_ids:
        for exercise in session.exec(
            select(ClassroomExercise).where(
                col(ClassroomExercise.id).in_(  # type: ignore[operator]
                    assignment_ids
                )
            )
        ).all():
            exercises_by_id[exercise.id] = exercise

    rows: list[MySessionSummary] = []
    for ps in sessions:
        latest = latest_by_session.get(ps.id, {})
        exercise = (
            exercises_by_id.get(ps.assignment_id)
            if ps.assignment_id is not None
            else None
        )
        required: list[uuid.UUID]
        if exercise is not None:
            # 发布轮：题单 = 快照题位（题目说明无作答，不进分母）；
            # 快照 id 非法的历史行跳过该题位（不因脏数据 500）
            required = []
            for item in exercise.snapshot_items:
                if str(item.get("type", "")) == AttemptItemType.INSTRUCTION:
                    continue
                raw_id = item.get("id")
                if raw_id is None:
                    continue
                try:
                    required.append(uuid.UUID(str(raw_id)))
                except ValueError:
                    logger.warning("invalid exercise snapshot item id: %s", raw_id)
        else:
            # 自主轮：无固定快照分母，按该轮实际作答过的题位计
            required = list(latest.keys())
        done = [
            latest[item_id]
            for item_id in required
            if item_id in latest and latest[item_id].status == AttemptStatus.DONE
        ]
        exam_locked = exam_service.exam_feedback_locked(session, ps, exercise)
        feedback_locked = mask_exam_feedback and exam_locked
        overalls = [a.overall for a in done if a.overall is not None]
        rows.append(
            MySessionSummary(
                attempt_ids=[]
                if feedback_locked
                else [attempt.id for attempt in latest.values()],
                is_exam=bool(exercise and exercise.is_exam),
                exam_ended=bool(exercise and exercise.is_exam and not exam_locked),
                session_id=ps.id,
                session_date=ps.session_date,
                mode=ps.mode,
                title=exercise.title if exercise is not None else None,
                done_count=len(done),
                total_count=len(required),
                overall_avg=(
                    None
                    if feedback_locked or not overalls
                    else round(sum(overalls) / len(overalls), 1)
                ),
            )
        )
    return rows
