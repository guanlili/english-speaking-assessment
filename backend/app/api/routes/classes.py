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
from sqlmodel import SQLModel, col, select

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
    AssignmentInfo,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    BadgePublic,
    BoardData,
    BoardItem,
    BoardStudent,
    Classroom,
    ClassroomCreate,
    ClassroomPublic,
    GamificationInfo,
    LearningPath,
    NextQuestion,
    Passage,
    PathUnit,
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
    Unit,
)
from app.scoring.bands import BAND_ORDER, adjust_band
from app.scoring.gamification import (
    BADGE_BY_KEY,
    settle_session,
    student_badges,
)

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


def _assignment_unit(session: Any, classroom: Classroom) -> Unit | None:
    """老师指派的当前单元（教学工具定位：全班同步）。"""
    if classroom.current_unit_id is None:
        return None
    unit = session.get(Unit, classroom.current_unit_id)
    if unit is None or not unit.is_active:
        return None
    return unit


def _active_passage(session: Any, student: Student | None = None) -> Passage:
    """课堂练习篇目（优先级）：老师指派单元 > 学生路径 > 全局第一篇。"""
    units = session.exec(
        select(Unit)
        .where(Unit.is_active)  # type: ignore[attr-defined]
        .order_by(col(Unit.order_index))
    ).all()
    if student is not None:
        classroom = session.get(Classroom, student.classroom_id)
        assigned = _assignment_unit(session, classroom) if classroom else None
        if assigned is not None:
            passage = session.exec(
                select(Passage)
                .where(Passage.unit_id == assigned.id, Passage.is_active)  # type: ignore[attr-defined]
                .limit(1)
            ).first()
            if passage is not None:
                return passage
            raise HTTPException(
                status_code=404,
                detail=f"指派的单元「{assigned.title}」还没有篇目，请联系老师",
            )
    if student is None or not units:
        passage = session.exec(
            select(Passage)
            .where(Passage.is_active)  # type: ignore[attr-defined]
            .order_by(col(Passage.created_at))
            .limit(1)
        ).first()
        if passage is None:
            raise HTTPException(status_code=404, detail="No active passage")
        return passage

    classroom = session.get(Classroom, student.classroom_id)
    unlock_all = bool(classroom and classroom.unlock_all)
    # 各单元完成轮数（按 session.passage → unit 聚合已结算轮）
    settled = session.exec(
        select(PracticeSession).where(
            PracticeSession.student_id == student.id,
            col(PracticeSession.stars).is_not(None),
            col(PracticeSession.passage_id).is_not(None),
        )
    ).all()
    passage_ids = {ps.passage_id for ps in settled if ps.passage_id}
    passages = session.exec(select(Passage)).all()
    unit_done: dict = {}
    for passage in passages:
        if passage.unit_id is not None and passage.id in passage_ids:
            unit_done[passage.unit_id] = True

    chosen: Unit | None = None
    if not unlock_all:
        # 第一个未完成的激活单元
        for unit in units:
            if not unit_done.get(unit.id):
                chosen = unit
                break
    if chosen is None:
        chosen = units[-1]  # 全部完成（或全开）→ 复练最后单元

    passage = next(
        (p for p in passages if p.unit_id == chosen.id and p.is_active),
        None,
    )
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
    session_id: uuid.UUID | None = Query(default=None),
) -> Any:
    """今天的练习计划：3 句听后复述 + 2 道该档情景问答（US-05）。

    传 session_id 时返回该会话的计划（主题探索的自由练习轮）。
    """
    classroom = _get_classroom(session, code)
    student = _get_student_of_classroom(session, classroom, student_id)
    today = _today_in_practice_tz()
    if session_id is not None:
        practice_session = session.get(PracticeSession, session_id)
        if practice_session is None or practice_session.student_id != student.id:
            raise HTTPException(status_code=404, detail="Session not found")
        passage = (
            session.get(Passage, practice_session.passage_id)
            if practice_session.passage_id
            else _active_passage(session, student)
        )
        if passage is None:
            raise HTTPException(status_code=404, detail="No active passage")
    else:
        passage = _active_passage(session, student)
        practice_session = get_or_create_today_session(
            session=session,
            classroom=classroom,
            student=student,
            today=today,
            passage_id=passage.id,
        )
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

    # 激励结算（幂等）：本轮全部终态时计算星/XP/连胜/徽章
    settle_session(session, practice_session, student, today, len(items))

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

    session.refresh(student)
    session.refresh(practice_session)
    badges = [
        BadgePublic(
            key=b.badge_key,
            label=BADGE_BY_KEY[b.badge_key].label
            if b.badge_key in BADGE_BY_KEY
            else b.badge_key,
            description=BADGE_BY_KEY[b.badge_key].description
            if b.badge_key in BADGE_BY_KEY
            else "",
            awarded_at=b.awarded_at,
        )
        for b in student_badges(session, student.id)
    ]

    assigned_unit = _assignment_unit(session, classroom)
    return TodayPlan(
        session_id=practice_session.id,
        classroom_code=classroom.code,
        band=band,
        assigned_unit_title=assigned_unit.title if assigned_unit else None,
        items=items,
        attempts=plan_attempts,
        questions_exhausted=exhausted,
        gamification=GamificationInfo(
            xp=student.xp,
            streak_days=student.streak_days,
            session_stars=practice_session.stars,
            badges=badges,
        ),
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
    passage = _active_passage(session, student)
    practice_session = get_or_create_today_session(
        session=session,
        classroom=classroom,
        student=student,
        today=_today_in_practice_tz(),
        passage_id=passage.id,
    )
    band = practice_session.question_band or practice_session.band
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
            PracticeSession.mode == "daily",
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

    assigned_unit_board = _assignment_unit(session, classroom)
    latest_engine = session.exec(
        select(Attempt.engine)
        .where(Attempt.status == AttemptStatus.DONE)
        .order_by(col(Attempt.created_at).desc())
        .limit(1)
    ).first()

    return BoardData(
        classroom_code=classroom.code,
        class_size=classroom.class_size,
        engine=latest_engine or "mock",
        assignment=(
            AssignmentInfo(
                unit_id=assigned_unit_board.id, title=assigned_unit_board.title
            )
            if assigned_unit_board
            else None
        ),
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


@router.get("/{code}/path", response_model=LearningPath)
def read_learning_path(
    session: SessionDep,
    code: str,
    student_id: uuid.UUID = Query(...),
) -> Any:
    """关卡地图（PRD 拾阶而上 → 多邻国式路径）：单元有序 + 完成轮数/星级 + 锁定。"""
    classroom = _get_classroom(session, code)
    student = _get_student_of_classroom(session, classroom, student_id)

    units = session.exec(
        select(Unit)
        .where(Unit.is_active)  # type: ignore[attr-defined]
        .order_by(col(Unit.order_index))
    ).all()
    passages = session.exec(select(Passage)).all()
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


class AssignmentRequest(SQLModel):
    unit_id: uuid.UUID | None  # None = 清除指派，回到个人路径


@router.get("/{code}/units", response_model=list[AssignmentInfo])
def list_units_for_class(session: SessionDep, code: str) -> Any:
    """课堂的单元列表（老师面板指派选择器用；课堂码即凭据，同面板口径）。"""
    from app.models import AssignmentInfo as _AI

    _get_classroom(session, code)  # 仅做课堂码校验
    units = session.exec(
        select(Unit)
        .where(Unit.is_active)  # type: ignore[attr-defined]
        .order_by(col(Unit.order_index))
    ).all()
    return [_AI(unit_id=u.id, title=u.title) for u in units]


@router.put("/{code}/assignment", response_model=AssignmentInfo | None)
def set_assignment(session: SessionDep, code: str, body: AssignmentRequest) -> Any:
    """老师设置/清除今日指派单元（课堂码即老师凭据，与面板同口径）。

    设置后全班学生的 /today 同步用该单元；清除则回退个人路径。
    """
    classroom = _get_classroom(session, code)
    if body.unit_id is None:
        classroom.current_unit_id = None
        session.add(classroom)
        session.commit()
        return None
    unit = session.get(Unit, body.unit_id)
    if unit is None or not unit.is_active:
        raise HTTPException(status_code=404, detail="Unit not found")
    classroom.current_unit_id = unit.id
    session.add(classroom)
    session.commit()
    return AssignmentInfo(unit_id=unit.id, title=unit.title)


class ExploreRequest(SQLModel):
    unit_id: uuid.UUID
    student_id: uuid.UUID


class ExploreStarted(SQLModel):
    session_id: uuid.UUID
    unit_title: str


@router.post("/{code}/explore", response_model=ExploreStarted)
def start_explore(session: SessionDep, code: str, body: ExploreRequest) -> Any:
    """主题探索：学生选择单元开始/继续当日自由练习轮（不计入课堂完成率）。"""
    classroom = _get_classroom(session, code)
    student = _get_student_of_classroom(session, classroom, body.student_id)
    unit = session.get(Unit, body.unit_id)
    if unit is None or not unit.is_active:
        raise HTTPException(status_code=404, detail="Unit not found")
    passage = session.exec(
        select(Passage)
        .where(Passage.unit_id == unit.id, Passage.is_active)  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    if passage is None:
        raise HTTPException(status_code=404, detail=f"单元「{unit.title}」还没有篇目")
    practice_session = get_or_create_today_session(
        session=session,
        classroom=classroom,
        student=student,
        today=_today_in_practice_tz(),
        passage_id=passage.id,
        mode="explore",
    )
    return {"session_id": practice_session.id, "unit_title": unit.title}
