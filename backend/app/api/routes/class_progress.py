"""学生进步轨迹与单元学习路径。"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query
from sqlalchemy.orm import load_only
from sqlmodel import col, select

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
    LearningPath,
    MySessionSummary,
    Passage,
    PathUnit,
    PracticeSession,
    TrailData,
    Unit,
)
from app.scoring.bands import BAND_ORDER
from app.services import exam as exam_service
from app.services import trail as trail_service

logger = logging.getLogger(__name__)


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
        locked_session_ids = {
            ps.id
            for ps, exercise in exam_rows
            if exam_service.exam_feedback_locked(
                session, ps, exercise, first_submitted=first.get(ps.id, {})
            )
        }
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
