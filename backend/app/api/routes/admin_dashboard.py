"""管理员平台大盘（业务数据闭环）：速览卡 / 趋势 / 课堂排行 / 资产计数。

全部只读聚合，不新建表。口径与教师端一致：练习日按 PRACTICE_TZ 切；
均分只算 DONE 作答（模考作答评分完成即 DONE，同样计入；同班级趋势口径）。
活跃定义 = 当天有提交作答（含评分失败），速览卡与趋势共用。
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import and_, func
from sqlalchemy import select as sa_select
from sqlmodel import col, select

from app.api.deps import SessionDep, SuperUserDep
from app.api.routes.metrics import collect_metrics
from app.core.config import settings
from app.models import (
    AdminMetricsDaily,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Classroom,
    ClassroomExercise,
    DashboardClassroomRow,
    DashboardContent,
    DashboardDailyPoint,
    DashboardMetricsDay,
    DashboardOverview,
    DashboardPerformance,
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
    # 区间下界的时间戳形式：让聚合查询先裁剪再 FILTER，数据量增长后不放大
    since_dt = datetime.combine(since_date, time.min, tz)

    day = func.date(func.timezone(settings.PRACTICE_TZ, col(Attempt.created_at)))
    a = (
        session.connection()
        .execute(
            sa_select(
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
            ).where(col(Attempt.created_at) >= since_dt)
        )
        .one()
    )

    # 活跃课堂要经会话归属课堂（作答本身没有课堂列）
    c = (
        session.connection()
        .execute(
            sa_select(
                func.count(func.distinct(PracticeSession.classroom_id))
                .filter(day == today)
                .label("t_classrooms"),
                func.count(func.distinct(PracticeSession.classroom_id))
                .filter(day >= since_date)
                .label("r_classrooms"),
            )
            .select_from(Attempt)
            .join(PracticeSession, col(PracticeSession.id) == col(Attempt.session_id))
            .where(col(Attempt.created_at) >= since_dt)
        )
        .one()
    )

    # 模考场次与运行异常按 session_date（业务日）统计
    s = (
        session.connection()
        .execute(
            sa_select(
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
            ).where(col(PracticeSession.session_date) >= since_date)
        )
        .one()
    )

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
    rows = (
        session.connection()
        .execute(
            sa_select(
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
            # 直接比较 created_at（可走索引/裁剪），等价于按练习日 >= since_date
            .where(col(Attempt.created_at) >= since_ts)
            .group_by(day)
            .order_by(day)
        )
        .all()
    )

    crows = (
        session.connection()
        .execute(
            sa_select(
                day.label("day"),
                func.count(func.distinct(PracticeSession.classroom_id)).label(
                    "active_classrooms"
                ),
            )
            .select_from(Attempt)
            .join(PracticeSession, col(PracticeSession.id) == col(Attempt.session_id))
            .where(col(Attempt.created_at) >= since_ts)
            .group_by(day)
        )
        .all()
    )
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

    # 课堂排行拆两查（评审 P2）：
    # A 区间/近窗指标——时间裁剪放进外连接条件（WHERE 会把窗口内零作答的
    #   课堂整行滤掉），裁剪基准取区间与近 14 天窗口的较早者（days<14 时
    #   近窗更早）；
    # B 全历史（累计作答/最近活跃，沉默判定要用）——只取三列的轻量查询，
    #   需扫全表，量级上来后考虑 created_at 索引或日期生成列。
    trim_ts = min(since_ts, recent_ts)
    crow = (
        session.connection()
        .execute(
            sa_select(
                col(Classroom.id),
                col(Classroom.name),
                col(Classroom.code),
                col(Classroom.grade),
                col(User.full_name),
                col(User.email),
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
            )
            .select_from(Classroom)
            .outerjoin(User, col(User.id) == col(Classroom.owner_id))
            .outerjoin(
                PracticeSession, col(PracticeSession.classroom_id) == col(Classroom.id)
            )
            .outerjoin(
                Attempt,
                and_(
                    col(Attempt.session_id) == col(PracticeSession.id),
                    col(Attempt.created_at) >= trim_ts,
                ),
            )
            .group_by(
                col(Classroom.id),
                col(Classroom.name),
                col(Classroom.code),
                col(Classroom.grade),
                col(User.full_name),
                col(User.email),
            )
        )
        .all()
    )
    history: dict[object, tuple[int, datetime | None]] = {}
    for cid, attempts_all, last_active in session.connection().execute(
        sa_select(
            col(PracticeSession.classroom_id),
            func.count(col(Attempt.id)),
            func.max(col(Attempt.created_at)),
        )
        .select_from(Attempt)
        .join(PracticeSession, col(PracticeSession.id) == col(Attempt.session_id))
        .group_by(col(PracticeSession.classroom_id))
    ):
        history[cid] = (attempts_all, last_active)
    student_counts: dict[object, int] = {}
    for cid, cnt in session.connection().execute(
        sa_select(col(Student.classroom_id), func.count()).group_by(
            col(Student.classroom_id)
        )
    ):
        student_counts[cid] = cnt

    classrooms: list[DashboardClassroomRow] = []
    silent: list[DashboardClassroomRow] = []
    for row in crow:
        attempts_all, last_active = history.get(row.id, (0, None))
        silent_days = None
        if attempts_all > 0 and last_active is not None:
            silent_days = (today - last_active.astimezone(tz).date()).days
        item = DashboardClassroomRow(
            classroom_id=row.id,
            name=row.name,
            code=row.code,
            grade=row.grade,
            owner_name=row.full_name or row.email,
            students=student_counts.get(row.id, 0),
            attempts=row.attempts_range,
            avg_score=_round1(row.avg_score),
            attempts_all=attempts_all,
            last_active=last_active,
            silent_days=silent_days,
        )
        classrooms.append(item)
        if attempts_all > 0 and row.attempts_recent == 0:
            silent.append(item)
    classrooms.sort(key=lambda r: (-r.attempts, -r.attempts_all))
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
        return (
            session.connection()
            .execute(sa_select(func.count()).select_from(model))
            .scalar_one()
        )

    roles: dict[str, int] = {}
    for role, cnt in session.connection().execute(
        sa_select(col(User.role), func.count()).group_by(col(User.role))
    ):
        roles[role] = cnt

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
        students_must_change_password=session.connection()
        .execute(
            sa_select(func.count())
            .select_from(User)
            .where(col(User.role) == "student", col(User.must_change_password))
        )
        .scalar_one(),
        student_profiles=count(Student),
        classrooms_total=count(Classroom),
        classrooms_active=session.connection()
        .execute(
            sa_select(func.count()).select_from(Classroom).where(col(Classroom.is_active))
        )
        .scalar_one(),
        publishes=count(ClassroomExercise),
        publishes_exam=session.connection()
        .execute(
            sa_select(func.count())
            .select_from(ClassroomExercise)
            .where(col(ClassroomExercise.is_exam))
        )
        .scalar_one(),
    )


@router.get("/performance", response_model=DashboardPerformance)
def read_dashboard_performance(
    session: SessionDep,
    _admin: SuperUserDep,
    days: int = Query(default=30, ge=1, le=MAX_DAYS),
) -> DashboardPerformance:
    """性能与稳定区：实时快照（与 /admin/metrics 同口径）+ 日快照历史。

    实时计数器自进程启动累计、重启归零（响应里带 note）；历史来自
    admin_metrics_daily 日快照线程（当日行尚在内存峰值中，未落库）。
    """
    tz = ZoneInfo(settings.PRACTICE_TZ)
    today = datetime.now(tz).date()
    since_date = today - timedelta(days=days - 1)

    rows = session.exec(
        select(AdminMetricsDaily)
        .where(col(AdminMetricsDaily.day) >= since_date)
        .order_by(col(AdminMetricsDaily.day))
    ).all()
    history = [
        DashboardMetricsDay(
            date=r.day.isoformat(),
            attempts=r.attempts,
            attempts_done=r.attempts_done,
            attempts_failed=r.attempts_failed,
            active_students=r.active_students,
            sessions=r.sessions,
            asr_seconds=r.asr_seconds,
            llm_calls_by_kind=r.llm_calls_by_kind,
            provider_failures=r.provider_failures,
            queue_max_age_s=r.queue_max_age_s,
            pool_max_checked_out=r.pool_max_checked_out,
        )
        for r in rows
    ]
    return DashboardPerformance(
        realtime=collect_metrics(session),
        history=history,
        runtime_issues_today=session.connection()
        .execute(
            sa_select(func.count())
            .select_from(PracticeSession)
            .where(
                col(PracticeSession.session_date) == today,
                col(PracticeSession.runtime_issue).is_not(None),
            )
        )
        .scalar_one(),
    )
