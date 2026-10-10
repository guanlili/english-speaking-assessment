"""学生进步轨迹与单元学习路径。"""

import logging
import uuid
from datetime import datetime, timedelta
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
    Passage,
    PathUnit,
    PracticeSession,
    TrailData,
    TrailSession,
    Unit,
)
from app.scoring.bands import BAND_ORDER
from app.services import exam as exam_service

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

    attempts = session.exec(
        select(Attempt)
        .options(
            # 学习足迹只要聚合小列：item_snapshot/rubric 等 JSON 大列不进内存
            # （窗口可达 30 天 × 全部作答）
            load_only(
                Attempt.id,  # ty: ignore[invalid-argument-type]
                Attempt.created_at,  # ty: ignore[invalid-argument-type]
                Attempt.item_type,  # ty: ignore[invalid-argument-type]
                Attempt.status,  # ty: ignore[invalid-argument-type]
                Attempt.session_id,  # ty: ignore[invalid-argument-type]
                Attempt.overall,  # ty: ignore[invalid-argument-type]
                Attempt.completeness,  # ty: ignore[invalid-argument-type]
                Attempt.vocab,  # ty: ignore[invalid-argument-type]
            )
        )
        .where(
            Attempt.student_id == student.id,
            Attempt.created_at >= window_start_utc,  # type: ignore
        )
        .order_by(col(Attempt.created_at))
    ).all()
    # 模考反馈可见性（返修R03）：学生视角排除「考试未终结」的作答——
    # 当天只有一道已评分题时，speaking_avg/completeness_avg 就是该题分数；
    # 授权教师/管理员查看保持全量。与 today/attempts 出口共用
    # exam_feedback_locked 判定，不改 ORM、不提前关卷
    locked_session_ids: set[uuid.UUID] = set()
    if current_user.role == "student" and not current_user.is_superuser:
        seen_session_ids = {a.session_id for a in attempts if a.session_id}
        if seen_session_ids:
            candidate_sessions = [
                ps
                for ps in session.exec(
                    select(PracticeSession).where(
                        col(PracticeSession.id).in_(seen_session_ids)  # type: ignore[operator]
                    )
                ).all()
                if ps.assignment_id is not None
            ]
            # 批量预取涉及的练习快照（替代逐会话 session.get 的 N+1；90 天
            # 窗口内会话数随使用线性增长，identity map 只挡重复 assignment）
            exercises_by_id: dict[uuid.UUID, ClassroomExercise] = {}
            if candidate_sessions:
                for ex in session.exec(
                    select(ClassroomExercise).where(
                        col(ClassroomExercise.id).in_(  # type: ignore[operator]
                            [ps.assignment_id for ps in candidate_sessions]
                        )
                    )
                ).all():
                    exercises_by_id[ex.id] = ex
            exam_sessions = [
                ps
                for ps in candidate_sessions
                if (exercise := exercises_by_id.get(ps.assignment_id)) is not None
                and exercise.is_exam
                and exam_service.exam_feedback_locked(session, ps, exercise)
            ]
            locked_session_ids = {ps.id for ps in exam_sessions}

    by_date: dict[str, dict[str, Any]] = {}
    for attempt in attempts:
        day = (
            attempt.created_at.astimezone(tz).date().isoformat()
            if attempt.created_at
            else None
        )
        if day is None or attempt.status != AttemptStatus.DONE:
            continue
        if attempt.session_id is not None and attempt.session_id in locked_session_ids:
            continue  # 考试进行中：该作答的分数不进学生聚合
        bucket = by_date.setdefault(
            day,
            {
                "speaking": [],
                "completeness": [],
                "vocab": None,
                "count": 0,
            },
        )
        bucket["count"] += 1
        if attempt.item_type == AttemptItemType.QUESTION:
            if attempt.overall is not None:
                bucket["speaking"].append(attempt.overall)
            # 当日最新一次问答的词汇档（按时间顺序覆盖）
            if attempt.vocab and isinstance(attempt.vocab, dict):
                cefr = attempt.vocab.get("cefr")
                if isinstance(cefr, str):
                    bucket["vocab"] = cefr
        elif (
            attempt.item_type == AttemptItemType.REPEAT
            and attempt.completeness is not None
        ):
            bucket["completeness"].append(attempt.completeness)

    sessions = [
        TrailSession(
            date=day,
            speaking_avg=(
                round(sum(v["speaking"]) / len(v["speaking"]), 1)
                if v["speaking"]
                else None
            ),
            repeat_completeness_avg=(
                round(sum(v["completeness"]) / len(v["completeness"]), 1)
                if v["completeness"]
                else None
            ),
            vocab_cefr=v["vocab"],
            attempt_count=v["count"],
        )
        for day, v in sorted(by_date.items())
    ]

    # 最近一轮档位动向（PRD US-10）：对比最近会话的调整后档与开始档。
    # 先幂等触发一次档位计算（作答后学生可能没再打开 /today）
    band_change: str | None = None
    practice_sessions = session.exec(
        select(PracticeSession)
        .where(PracticeSession.student_id == student.id)
        .order_by(col(PracticeSession.created_at).desc())
        .limit(100)
    ).all()
    practice_sessions.reverse()  # type: ignore
    if practice_sessions:
        latest = practice_sessions[-1]
        _question_band_for_session(session, latest, student)
        # question_band 已写入才算完成过一轮调整；复述未完成 → 无建议
        if latest.question_band is not None:
            if latest.question_band == latest.band:
                band_change = "keep"
            elif BAND_ORDER.index(latest.question_band) > BAND_ORDER.index(latest.band):
                band_change = "up"
            else:
                band_change = "down"

    # 累计开口分钟 + 词汇命中（与轨迹窗口一致，只统计已完成作答）。
    # vocab_counts = 老词表 A2/B1/B2 口径（仅历史作答携带，零变化保留）；
    # level_counts = 五级词库口径（现行为标准，来自 level_stats）。
    done_attempts = [a for a in attempts if a.status == AttemptStatus.DONE]
    total_minutes = round(sum(a.duration_s for a in done_attempts) / 60)
    vocab_counts: dict[str, int] = {}
    level_counts: dict[str, int] = {}
    for a in done_attempts:
        vocab = a.vocab if isinstance(a.vocab, dict) else None
        if not vocab:
            continue
        hits = vocab.get("hits")
        if isinstance(hits, dict):
            for band, words in hits.items():
                if not isinstance(band, str) or not isinstance(words, list):
                    continue
                vocab_counts[band] = vocab_counts.get(band, 0) + len(words)
        level_stats = vocab.get("level_stats")
        if isinstance(level_stats, dict):
            hits_by_level = level_stats.get("hits_by_level")
            if isinstance(hits_by_level, dict):
                for level, count in hits_by_level.items():
                    if not isinstance(level, str) or not isinstance(count, int):
                        continue
                    level_counts[level] = level_counts.get(level, 0) + count

    return TrailData(
        classroom_code=classroom.code,
        student_id=student.id,
        display_name=student.display_name,
        suffix=student.suffix,
        sessions=sessions,
        band_change=band_change,
        total_minutes=total_minutes,
        vocab_counts=vocab_counts,
        level_counts=level_counts,
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
