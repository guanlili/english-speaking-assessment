"""管理员平台大盘（业务数据闭环）：速览卡 / 趋势 / 课堂排行 / 资产计数。

全部只读聚合，不新建表。口径与教师端一致：练习日按 PRACTICE_TZ 切；
均分只算 DONE 作答（未终结模考的作答不是 DONE，天然排除，同班级趋势）。
活跃定义 = 当天有提交作答（含评分失败），速览卡与趋势共用。
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select
from sqlmodel import col

from app.api.deps import SessionDep, SuperUserDep
from app.core.config import settings
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Classroom,
    ClassroomExercise,
    DashboardClassroomRow,
    DashboardContent,
    DashboardDailyPoint,
    DashboardOverview,
    DashboardRangeCards,
    DashboardUsage,
    Instruction,
    Passage,
    PracticeSession,
    RepeatSentence,
    ScenarioQuestion,
    Student,
    Unit,
    User,
    VocabularyBook,
    VocabularyLevelEntry,
    VocabularyWord,
)

router = APIRouter(prefix="/admin/dashboard", tags=["admin"])

# 「全部」档位的实际上限（前端把"全部"映射为大 days）
MAX_DAYS = 3650
# 沉默课堂判定：最近 N 天零提交（历史有用过）
SILENT_DAYS = 14


def _round1(value: float | None) -> float | None:
    return round(float(value), 1) if value is not None else None


@router.get("/overview", response_model=DashboardOverview)
def read_dashboard_overview(
    session: SessionDep,
    _admin: SuperUserDep,
    days: int = Query(default=7, ge=1, le=MAX_DAYS),
) -> DashboardOverview:
    tz = ZoneInfo(settings.PRACTICE_TZ)
    today = datetime.now(tz).date()
    since_date = today - timedelta(days=days - 1)

    day = func.date(func.timezone(settings.PRACTICE_TZ, col(Attempt.created_at)))
    a = session.execute(
        select(
            func.count().filter(day == today).label("t_attempts"),
            func.count().filter(day >= since_date).label("r_attempts"),
            func.count(func.distinct(Attempt.student_id))
            .filter(day == today)
            .label("t_students"),
            func.count(func.distinct(Attempt.student_id))
            .filter(day >= since_date)
            .label("r_students"),
            func.count()
            .filter(col(Attempt.status) == AttemptStatus.DONE, day == today)
            .label("t_done"),
            func.count()
            .filter(col(Attempt.status) == AttemptStatus.DONE, day >= since_date)
            .label("r_done"),
            func.count()
            .filter(col(Attempt.status) == AttemptStatus.FAILED, day == today)
            .label("t_failed"),
            func.count()
            .filter(col(Attempt.status) == AttemptStatus.FAILED, day >= since_date)
            .label("r_failed"),
        )
    ).one()

    # 活跃课堂要经会话归属课堂（作答本身没有课堂列）
    c = session.execute(
        select(
            func.count(func.distinct(PracticeSession.classroom_id))
            .filter(day == today)
            .label("t_classrooms"),
            func.count(func.distinct(PracticeSession.classroom_id))
            .filter(day >= since_date)
            .label("r_classrooms"),
        )
        .select_from(Attempt)
        .join(PracticeSession, col(PracticeSession.id) == col(Attempt.session_id))
    ).one()

    # 模考场次与运行异常按 session_date（业务日）统计
    s = session.execute(
        select(
            func.count()
            .filter(
                col(PracticeSession.session_date) == today,
                col(PracticeSession.exam_started_at).is_not(None),
            )
            .label("t_exams"),
            func.count()
            .filter(
                col(PracticeSession.session_date) >= since_date,
                col(PracticeSession.exam_started_at).is_not(None),
            )
            .label("r_exams"),
            func.count()
            .filter(
                col(PracticeSession.session_date) == today,
                col(PracticeSession.runtime_issue).is_not(None),
            )
            .label("t_issues"),
            func.count()
            .filter(
                col(PracticeSession.session_date) >= since_date,
                col(PracticeSession.runtime_issue).is_not(None),
            )
            .label("r_issues"),
        )
    ).one()

    return DashboardOverview(
        days=days,
        range_start=since_date.isoformat(),
        today=DashboardRangeCards(
            attempts=a.t_attempts,
            active_students=a.t_students,
            active_classrooms=c.t_classrooms,
            scored_done=a.t_done,
            scored_failed=a.t_failed,
            exam_sessions=s.t_exams,
            runtime_issues=s.t_issues,
        ),
        range=DashboardRangeCards(
            attempts=a.r_attempts,
            active_students=a.r_students,
            active_classrooms=c.r_classrooms,
            scored_done=a.r_done,
            scored_failed=a.r_failed,
            exam_sessions=s.r_exams,
            runtime_issues=s.r_issues,
        ),
    )


@router.get("/usage", response_model=DashboardUsage)
def read_dashboard_usage(
    session: SessionDep,
    _admin: SuperUserDep,
    days: int = Query(default=30, ge=1, le=MAX_DAYS),
) -> DashboardUsage:
    tz = ZoneInfo(settings.PRACTICE_TZ)
    today = datetime.now(tz).date()
    since_date = today - timedelta(days=days - 1)
    since_ts = datetime.combine(since_date, time.min, tz)
    recent_ts = datetime.combine(today - timedelta(days=SILENT_DAYS), time.min, tz)

    day = func.date(func.timezone(settings.PRACTICE_TZ, col(Attempt.created_at)))
    rows = session.execute(
        select(
            day.label("day"),
            func.count(func.distinct(Attempt.student_id)).label("active_students"),
            func.count().label("attempts"),
            func.count()
            .filter(col(Attempt.item_type) == AttemptItemType.PASSAGE)
            .label("attempts_passage"),
            func.count()
            .filter(col(Attempt.item_type) == AttemptItemType.REPEAT)
            .label("attempts_repeat"),
            func.count()
            .filter(col(Attempt.item_type) == AttemptItemType.QUESTION)
            .label("attempts_question"),
            func.count()
            .filter(col(Attempt.status) == AttemptStatus.FAILED)
            .label("scored_failed"),
            func.avg(Attempt.overall)
            .filter(
                col(Attempt.status) == AttemptStatus.DONE,
                col(Attempt.item_type) == AttemptItemType.QUESTION,
            )
            .label("question_avg"),
            func.avg(Attempt.completeness)
            .filter(
                col(Attempt.status) == AttemptStatus.DONE,
                col(Attempt.item_type) == AttemptItemType.REPEAT,
            )
            .label("repeat_avg"),
        )
        .where(day >= since_date)
        .group_by(day)
        .order_by(day)
    ).all()

    crows = session.execute(
        select(
            day.label("day"),
            func.count(func.distinct(PracticeSession.classroom_id)).label(
                "active_classrooms"
            ),
        )
        .select_from(Attempt)
        .join(PracticeSession, col(PracticeSession.id) == col(Attempt.session_id))
        .where(day >= since_date)
        .group_by(day)
    ).all()
    classrooms_by_day = {row.day: row.active_classrooms for row in crows}

    points = [
        DashboardDailyPoint(
            date=row.day.isoformat(),
            active_students=row.active_students,
            active_classrooms=classrooms_by_day.get(row.day, 0),
            attempts=row.attempts,
            attempts_passage=row.attempts_passage,
            attempts_repeat=row.attempts_repeat,
            attempts_question=row.attempts_question,
            scored_failed=row.scored_failed,
            question_avg=_round1(row.question_avg),
            repeat_completeness_avg=_round1(row.repeat_avg),
        )
        for row in rows
    ]
    item_distribution = {
        AttemptItemType.PASSAGE: sum(p.attempts_passage for p in points),
        AttemptItemType.REPEAT: sum(p.attempts_repeat for p in points),
        AttemptItemType.QUESTION: sum(p.attempts_question for p in points),
    }

    # 课堂排行：classroom→session→attempt 是线性链；学生数单独查避免叉积。
    # LEFT JOIN 下 COUNT(*) 会把无作答的课堂行也计 1，必须数非空的 attempt.id。
    crow = session.execute(
        select(
            Classroom.id.label("classroom_id"),
            Classroom.name,
            Classroom.code,
            Classroom.grade,
            User.full_name.label("owner_full_name"),
            User.email.label("owner_email"),
            func.count(col(Attempt.id)).label("attempts_all"),
            func.count(col(Attempt.id))
            .filter(col(Attempt.created_at) >= since_ts)
            .label("attempts_range"),
            func.count(col(Attempt.id))
            .filter(col(Attempt.created_at) >= recent_ts)
            .label("attempts_recent"),
            func.avg(Attempt.overall)
            .filter(
                col(Attempt.created_at) >= since_ts,
                col(Attempt.status) == AttemptStatus.DONE,
            )
            .label("avg_score"),
            func.max(col(Attempt.created_at)).label("last_active"),
        )
        .select_from(Classroom)
        .outerjoin(User, col(User.id) == col(Classroom.owner_id))
        .outerjoin(
            PracticeSession, col(PracticeSession.classroom_id) == col(Classroom.id)
        )
        .outerjoin(Attempt, col(Attempt.session_id) == col(PracticeSession.id))
        .group_by(
            Classroom.id,
            Classroom.name,
            Classroom.code,
            Classroom.grade,
            User.full_name,
            User.email,
        )
        .order_by(
            desc(
                func.count(col(Attempt.id)).filter(col(Attempt.created_at) >= since_ts)
            ),
            desc(func.count(col(Attempt.id))),
        )
    ).all()
    student_counts = dict(
        session.execute(
            select(Student.classroom_id, func.count()).group_by(Student.classroom_id)
        ).all()
    )

    classrooms: list[DashboardClassroomRow] = []
    silent: list[DashboardClassroomRow] = []
    for row in crow:
        silent_days = None
        if row.attempts_all > 0 and row.last_active is not None:
            silent_days = (today - row.last_active.astimezone(tz).date()).days
        item = DashboardClassroomRow(
            classroom_id=row.classroom_id,
            name=row.name,
            code=row.code,
            grade=row.grade,
            owner_name=row.owner_full_name or row.owner_email,
            students=student_counts.get(row.classroom_id, 0),
            attempts=row.attempts_range,
            avg_score=_round1(row.avg_score),
            attempts_all=row.attempts_all,
            last_active=row.last_active,
            silent_days=silent_days,
        )
        classrooms.append(item)
        if row.attempts_all > 0 and row.attempts_recent == 0:
            silent.append(item)
    silent.sort(key=lambda r: -(r.silent_days or 0))

    return DashboardUsage(
        points=points,
        item_distribution=item_distribution,
        classrooms=classrooms,
        silent_classrooms=silent,
    )


@router.get("/content", response_model=DashboardContent)
def read_dashboard_content(
    session: SessionDep,
    _admin: SuperUserDep,
) -> DashboardContent:
    def count(model: type) -> int:  # noqa: ANN001
        # 动态 model 走不进 sqlmodel 的标量重载，显式取标量
        return session.execute(select(func.count()).select_from(model)).scalar_one()

    roles = dict(
        session.execute(select(User.role, func.count()).group_by(User.role)).all()
    )

    return DashboardContent(
        units=count(Unit),
        passages=count(Passage),
        repeat_sentences=count(RepeatSentence),
        scenario_questions=count(ScenarioQuestion),
        instructions=count(Instruction),
        vocab_books=count(VocabularyBook),
        vocab_words=count(VocabularyWord),
        vocab_level_entries=count(VocabularyLevelEntry),
        users_admin=roles.get("admin", 0),
        users_teacher=roles.get("teacher", 0),
        student_accounts=roles.get("student", 0),
        students_must_change_password=session.execute(
            select(func.count())
            .select_from(User)
            .where(col(User.role) == "student", col(User.must_change_password))
        ).scalar_one(),
        student_profiles=count(Student),
        classrooms_total=count(Classroom),
        classrooms_active=session.execute(
            select(func.count()).select_from(Classroom).where(col(Classroom.is_active))
        ).scalar_one(),
        publishes=count(ClassroomExercise),
        publishes_exam=session.execute(
            select(func.count())
            .select_from(ClassroomExercise)
            .where(col(ClassroomExercise.is_exam))
        ).scalar_one(),
    )
