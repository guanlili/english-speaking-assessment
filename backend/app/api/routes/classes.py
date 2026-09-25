"""课堂与学生练习接口（PRD 附录 A 的 2 周形态，公开、无登录）。

POST /classes                      创建课堂（管理员），返回课堂码
POST /classes/{code}/join          显示名进入，返回 student_id（US-04）
GET  /classes/{code}/today         今天的 3 句复述 + 2 道该档问答（US-05）
GET  /classes/{code}/next-question 同主题同档下一题（US-06 换一题）
GET  /classes/{code}/board         老师名单表（谁交了/每题分数/音频）
"""

import logging
import secrets
import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, select

from app.api.deps import SessionDep, SuperUserDep
from app.core.config import settings
from app.crud import (
    create_classroom,
    get_classroom_by_code,
    get_or_create_today_session,
    get_student,
    join_classroom,
)
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptStatus,
    BoardData,
    BoardItem,
    BoardStudent,
    Classroom,
    ClassroomCreate,
    ClassroomPublic,
    NextQuestion,
    Passage,
    PlanAttempt,
    PlanItem,
    PracticeSession,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    ScenarioQuestionPublic,
    Student,
    StudentJoin,
    StudentPublic,
    TodayPlan,
    TrailData,
    TrailSession,
)
from app.scoring.bands import BAND_ORDER, adjust_band

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classes", tags=["classes"])

# 课堂码字母表去掉易混字符（0/O/1/I）
CLASSROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CLASSROOM_CODE_LENGTH = 6
QUESTIONS_PER_ROUND = 2


def _today_in_practice_tz() -> date:
    """练习日按配置时区取日期（教室在中国，UTC 会在早八点切日）。"""
    from datetime import datetime

    return datetime.now(ZoneInfo(settings.PRACTICE_TZ)).date()


def _generate_classroom_code() -> str:
    return "".join(
        secrets.choice(CLASSROOM_CODE_ALPHABET) for _ in range(CLASSROOM_CODE_LENGTH)
    )


def _active_passage(session: Any) -> Passage:
    """课堂练习用的篇目 = 当前激活篇目（试点单班单主题）。"""
    passage = session.exec(
        select(Passage)
        .where(Passage.is_active)  # type: ignore[attr-defined]
        .order_by(col(Passage.created_at))
        .limit(1)
    ).first()
    if passage is None:
        raise HTTPException(status_code=404, detail="No active passage")
    return passage


def _scenario_for_topic(session: Any, topic: str) -> Scenario:
    scenario = session.exec(select(Scenario).where(Scenario.topic == topic)).first()
    if scenario is None:
        raise HTTPException(status_code=404, detail="No scenario configured")
    return scenario


def _get_classroom(session: SessionDep, code: str) -> Classroom:
    classroom = get_classroom_by_code(session=session, code=code.upper())
    if classroom is None or not classroom.is_active:
        raise HTTPException(status_code=404, detail="Classroom not found")
    return classroom


def _get_student_of_classroom(
    session: SessionDep, classroom: Classroom, student_id: uuid.UUID
) -> Student:
    student = get_student(session=session, student_id=student_id)
    if student is None or student.classroom_id != classroom.id:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


@router.post("", response_model=ClassroomPublic)
def create_class(
    session: SessionDep,
    _current_user: SuperUserDep,  # noqa: ARG001 - 权限闸门
    class_in: ClassroomCreate,
) -> Any:
    """创建课堂，返回课堂码（老师把它当作进入链接分发）。"""
    for _ in range(5):
        code = _generate_classroom_code()
        if get_classroom_by_code(session=session, code=code) is None:
            classroom = Classroom(code=code, class_size=class_in.class_size)
            return create_classroom(session=session, classroom=classroom)
    raise HTTPException(status_code=500, detail="无法生成唯一课堂码")


@router.post("/{code}/join", response_model=StudentPublic)
def join_class(session: SessionDep, code: str, join_in: StudentJoin) -> Any:
    """学生凭课堂码 + 显示名进入；同名追加 4 位区分码（US-04）。"""
    classroom = _get_classroom(session, code)
    display_name = join_in.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="显示名不能为空")
    return join_classroom(
        session=session, classroom=classroom, display_name=display_name
    )


def _latest_done_attempts(
    session: Any, student_id: uuid.UUID, session_id: uuid.UUID
) -> list[Attempt]:
    """本轮内每条题目的最新一次作答（含 queued/failed，供进度恢复）。"""
    attempts = session.exec(
        select(Attempt)
        .where(
            Attempt.student_id == student_id,
            Attempt.session_id == session_id,
        )
        .order_by(col(Attempt.created_at))
    ).all()
    latest: dict[uuid.UUID, Attempt] = {}
    for attempt in attempts:
        latest[attempt.item_id] = attempt
    return list(latest.values())


def _repeat_attempts_of_session(
    session: Any, practice_session: PracticeSession
) -> list[Attempt]:
    attempts = session.exec(
        select(Attempt)
        .where(
            Attempt.session_id == practice_session.id,
            Attempt.item_type == AttemptItemType.REPEAT,
        )
        .order_by(col(Attempt.created_at))
    ).all()
    latest: dict[uuid.UUID, Attempt] = {}
    for attempt in attempts:
        latest[attempt.item_id] = attempt
    return list(latest.values())


def _pick_questions(
    session: Any,
    scenario: Scenario,
    band: str,
    student_id: uuid.UUID,
    limit: int = QUESTIONS_PER_ROUND,
    fill_with_done: bool = True,
) -> tuple[list[ScenarioQuestion], bool]:
    """同主题同档、未做过的优先，按 order_index 稳定排序。

    返回 (题目列表, 是否已用尽)。选择是确定性的：刷新不会换题。
    fill_with_done=True 用于 /today（一轮必须凑满题数，练习允许重做）；
    换一题（US-06）只允许未做过的，用尽即 exhausted。
    """
    questions = session.exec(
        select(ScenarioQuestion)
        .where(
            ScenarioQuestion.scenario_id == scenario.id,
            ScenarioQuestion.band == band,
        )
        .order_by(col(ScenarioQuestion.order_index))
    ).all()
    done_ids = set(
        session.exec(
            select(Attempt.item_id).where(
                Attempt.student_id == student_id,
                Attempt.item_type == AttemptItemType.QUESTION,
            )
        ).all()
    )
    undone = [q for q in questions if q.id not in done_ids]
    exhausted = len(undone) == 0
    picked = undone[:limit]
    if fill_with_done and len(picked) < limit:
        # 未做的不足时用做过的补齐（练习场景允许重做）
        picked += [q for q in questions if q not in picked][: limit - len(picked)]
    return picked, exhausted


def _question_band_for_session(
    session: Any, practice_session: PracticeSession, student: Student
) -> str:
    """本轮 3 句复述全部 done 后，按平均完整度/流利度调整问答档（US-05）。

    调整同时写回 student.current_band（下一轮沿用）与 session.question_band。
    未完成复述时沿用会话档位。
    """
    if practice_session.question_band is not None:
        return practice_session.question_band

    passage = _active_passage(session)
    sentences = session.exec(
        select(RepeatSentence)
        .where(RepeatSentence.passage_id == passage.id)
        .order_by(col(RepeatSentence.order_index))
    ).all()
    repeats = _repeat_attempts_of_session(session, practice_session)
    done = [a for a in repeats if a.status == AttemptStatus.DONE]
    if not sentences or len(done) < len(sentences):
        return practice_session.band

    avg_c = sum(a.completeness or 0 for a in done) / len(done)
    avg_f = sum(a.fluency or 0 for a in done) / len(done)
    adjusted = adjust_band(avg_c, avg_f, student.current_band)
    student.current_band = adjusted
    practice_session.question_band = adjusted
    session.add(student)
    session.add(practice_session)
    session.commit()
    return adjusted


@router.get("/{code}/today", response_model=TodayPlan)
def read_today_plan(
    session: SessionDep,
    code: str,
    student_id: uuid.UUID = Query(...),
) -> Any:
    """今天的练习计划：3 句听后复述 + 2 道该档情景问答（US-05）。"""
    classroom = _get_classroom(session, code)
    student = _get_student_of_classroom(session, classroom, student_id)
    today = _today_in_practice_tz()
    practice_session = get_or_create_today_session(
        session=session, classroom=classroom, student=student, today=today
    )

    passage = _active_passage(session)
    sentences = session.exec(
        select(RepeatSentence)
        .where(RepeatSentence.passage_id == passage.id)
        .order_by(col(RepeatSentence.order_index))
    ).all()
    if not sentences:
        raise HTTPException(status_code=404, detail="No repeat sentences configured")
    scenario = _scenario_for_topic(session, passage.topic)

    band = _question_band_for_session(session, practice_session, student)
    questions, exhausted = _pick_questions(
        session, scenario, band, student.id, QUESTIONS_PER_ROUND
    )

    items = [
        PlanItem(
            type=AttemptItemType.REPEAT,
            id=s.id,
            text=s.text,
            audio_url=s.audio_url,
            suggested_seconds=s.suggested_seconds,
        )
        for s in sentences
    ] + [
        PlanItem(
            type=AttemptItemType.QUESTION,
            id=q.id,
            text=q.text,
            audio_url=q.audio_url,
            suggested_seconds=q.suggested_seconds,
            band=q.band,
        )
        for q in questions
    ]

    attempts = _latest_done_attempts(session, student.id, practice_session.id)
    plan_attempts = [
        PlanAttempt(
            item_id=a.item_id,
            attempt_id=a.id,
            status=a.status,
            overall=a.overall,
            completeness=a.completeness,
            fluency=a.fluency,
            transcript=a.transcript,
            advice=a.advice,
            error=a.error,
        )
        for a in attempts
    ]

    return TodayPlan(
        session_id=practice_session.id,
        classroom_code=classroom.code,
        band=band,
        items=items,
        attempts=plan_attempts,
        questions_exhausted=exhausted,
    )


@router.get("/{code}/next-question", response_model=NextQuestion)
def read_next_question(
    session: SessionDep,
    code: str,
    student_id: uuid.UUID = Query(...),
    exclude_ids: list[uuid.UUID] = Query(default=[]),
) -> Any:
    """换一题：同主题、同档、未做过的问题（US-06）。用尽时 exhausted=true。"""
    classroom = _get_classroom(session, code)
    student = _get_student_of_classroom(session, classroom, student_id)
    practice_session = get_or_create_today_session(
        session=session,
        classroom=classroom,
        student=student,
        today=_today_in_practice_tz(),
    )
    band = practice_session.question_band or practice_session.band

    passage = _active_passage(session)
    scenario = _scenario_for_topic(session, passage.topic)

    questions, _ = _pick_questions(
        session, scenario, band, student.id, 1, fill_with_done=False
    )
    excluded = set(exclude_ids)
    candidates = [q for q in questions if q.id not in excluded]
    if not candidates:
        return NextQuestion(question=None, exhausted=True)
    return NextQuestion(
        question=ScenarioQuestionPublic.model_validate(candidates[0]),
        exhausted=False,
    )


@router.get("/{code}/board", response_model=BoardData)
def read_class_board(session: SessionDep, code: str) -> Any:
    """老师名单表（PRD §8.5 2 周）：谁交了、每题分数、音频；允许先显示评分中。

    聚合本课堂所有学生「今日会话」里每题的最新作答。数据在评分写入后出现，
    不承诺秒级；有 pending 时前端轮询（US-10：最后一人提交后 2 分钟内一致）。
    """
    classroom = _get_classroom(session, code)
    today = _today_in_practice_tz()

    # 题目骨架：激活篇目的 3 句复述（当前学生可能各有 2 道不同档的问答，
    # 表头只列复述骨架，问答分数体现在均分里，明细在每生的 items）
    passage = _active_passage(session)
    sentences = session.exec(
        select(RepeatSentence)
        .where(RepeatSentence.passage_id == passage.id)
        .order_by(col(RepeatSentence.order_index))
    ).all()
    skeleton = [
        BoardItem(
            item_id=s.id,
            type=AttemptItemType.REPEAT,
            status="missing",
        )
        for s in sentences
    ]

    students = session.exec(
        select(Student).where(Student.classroom_id == classroom.id)
    ).all()
    today_sessions = session.exec(
        select(PracticeSession).where(
            PracticeSession.classroom_id == classroom.id,
            PracticeSession.session_date == today,
        )
    ).all()
    session_by_student = {s.student_id: s for s in today_sessions}

    # 7 日未练口径：加入超过 7 天且窗口内无任何作答（US-10 简化实现）
    from datetime import timedelta

    now = datetime.now(ZoneInfo(settings.PRACTICE_TZ))
    week_ago = (now - timedelta(days=7)).date()
    recent_attempts = session.exec(select(Attempt)).all()
    recent_by_student: dict[uuid.UUID, list[Attempt]] = {}
    for attempt in recent_attempts:
        if attempt.student_id is None or attempt.created_at is None:
            continue
        if (
            attempt.created_at.astimezone(ZoneInfo(settings.PRACTICE_TZ)).date()
            >= week_ago
        ):
            recent_by_student.setdefault(attempt.student_id, []).append(attempt)

    band_distribution = {"A2": 0, "B1": 0, "B2": 0}
    board_students: list[BoardStudent] = []
    submitted_count = 0
    pending_count = 0
    for student in students:
        practice_session = session_by_student.get(student.id)
        items: list[BoardItem] = []
        repeat_scores: list[float] = []
        question_scores: list[float] = []
        has_pending = False

        if practice_session is not None:
            attempts = session.exec(
                select(Attempt)
                .where(
                    Attempt.student_id == student.id,
                    Attempt.session_id == practice_session.id,
                )
                .order_by(col(Attempt.created_at))
            ).all()
            latest: dict[uuid.UUID, Attempt] = {}
            for attempt in attempts:
                latest[attempt.item_id] = attempt

            # 骨架顺序：复述句
            for s in sentences:
                attempt = latest.get(s.id)
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
            # 问答（每个学生的题可能不同）
            for item_id, attempt in latest.items():
                if attempt.item_type != AttemptItemType.QUESTION:
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

        done_count = sum(1 for i in items if i.status == AttemptStatus.DONE)
        if any(i.status != "missing" for i in items):
            submitted_count += 1
        if has_pending:
            pending_count += 1
        joined_before_window = (
            student.created_at is not None
            and student.created_at.astimezone(ZoneInfo(settings.PRACTICE_TZ)).date()
            < week_ago
        )
        inactive = joined_before_window and student.id not in recent_by_student
        band_distribution[student.current_band] = (
            band_distribution.get(student.current_band, 0) + 1
        )
        board_students.append(
            BoardStudent(
                student_id=student.id,
                display_name=student.display_name,
                suffix=student.suffix,
                done_count=done_count,
                total_count=len(items),
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
                current_band=student.current_band,
                inactive_days7=inactive,
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

    return BoardData(
        classroom_code=classroom.code,
        class_size=classroom.class_size,
        submitted_count=submitted_count,
        pending_count=pending_count,
        band_distribution=band_distribution,
        students=board_students,
        items=skeleton,
    )


@router.get("/{code}/trail", response_model=TrailData)
def read_student_trail(
    session: SessionDep,
    code: str,
    student_id: uuid.UUID = Query(...),
) -> Any:
    """学生进步轨迹（PRD US-09）：按练习日聚合口语参考分与词汇档。

    口语参考分 = 当日问答总评均值；跟读完整度单独一列，不混线。
    少于 2 次由前端只列表不画趋势。
    """
    classroom = _get_classroom(session, code)
    student = _get_student_of_classroom(session, classroom, student_id)

    attempts = session.exec(
        select(Attempt)
        .where(Attempt.student_id == student.id)
        .order_by(col(Attempt.created_at))
    ).all()

    tz = ZoneInfo(settings.PRACTICE_TZ)
    by_date: dict[str, dict[str, Any]] = {}
    for attempt in attempts:
        day = (
            attempt.created_at.astimezone(tz).date().isoformat()
            if attempt.created_at
            else None
        )
        if day is None or attempt.status != AttemptStatus.DONE:
            continue
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
        .order_by(col(PracticeSession.created_at))
    ).all()
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

    return TrailData(
        classroom_code=classroom.code,
        student_id=student.id,
        display_name=student.display_name,
        suffix=student.suffix,
        sessions=sessions,
        band_change=band_change,
    )
