"""管理员平台大盘（业务数据闭环）：速览卡 / 趋势 / 课堂排行 / 资产计数。

全部只读聚合，不新建表。口径与教师端一致：练习日按 PRACTICE_TZ 切；
均分只算 DONE 作答（模考作答评分完成即 DONE，同样计入；同班级趋势口径）。
活跃定义 = 当天有提交作答（含评分失败），速览卡与趋势共用。
"""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func
from sqlalchemy import select as sa_select
from sqlmodel import col, select

from app.api.deps import SessionDep, SuperUserDep
from app.api.routes.metrics import collect_metrics
from app.core.config import settings
from app.models import (
    AdminCostReconcile,
    AdminCostReconcileIn,
    AdminMetricsDaily,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Classroom,
    ClassroomExercise,
    DashboardClassroomRow,
    DashboardContent,
    DashboardCost,
    DashboardCostMonth,
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
    def _sub(model: type, *conditions: Any) -> Any:  # noqa: ANN001
        # 17 个计数一趟取回（scalar 子查询），替代此前 19 次串行数据库往返
        stmt = sa_select(func.count()).select_from(model)
        if conditions:
            stmt = stmt.where(*conditions)
        return stmt.scalar_subquery()

    row = (
        session.connection()
        .execute(
            sa_select(
                _sub(Unit).label("units"),
                _sub(Passage).label("passages"),
                _sub(RepeatSentence).label("repeat_sentences"),
                _sub(ScenarioQuestion).label("scenario_questions"),
                _sub(Instruction).label("instructions"),
                _sub(VocabularyBook).label("vocab_books"),
                _sub(VocabularyWord).label("vocab_words"),
                _sub(VocabularyLevelEntry).label("vocab_level_entries"),
                _sub(User, col(User.role) == "admin").label("users_admin"),
                _sub(User, col(User.role) == "teacher").label("users_teacher"),
                _sub(User, col(User.role) == "student").label("student_accounts"),
                _sub(
                    User,
                    col(User.role) == "student",
                    col(User.must_change_password),
                ).label("students_must_change_password"),
                _sub(Student).label("student_profiles"),
                _sub(Classroom).label("classrooms_total"),
                _sub(Classroom, col(Classroom.is_active)).label("classrooms_active"),
                _sub(ClassroomExercise).label("publishes"),
                _sub(ClassroomExercise, col(ClassroomExercise.is_exam)).label(
                    "publishes_exam"
                ),
            )
        )
        .one()
    )
    return DashboardContent(**dict(row._mapping))


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
            audio_orphans=r.audio_orphans,
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


def _month_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


@router.get("/cost", response_model=DashboardCost)
def read_dashboard_cost(
    session: SessionDep,
    _admin: SuperUserDep,
    months: int = Query(default=6, ge=1, le=24),
) -> DashboardCost:
    """费用区：按月估算（ASR 按真实秒数精确；LLM 按调用量估 token）。

    估算口径、单价与「以云账单为准」声明见响应 note；对账金额为管理员
    手工录入的实际账单。
    """
    tz = ZoneInfo(settings.PRACTICE_TZ)
    today = datetime.now(tz).date()
    # 自然月窗口：从「往前第 months-1 个月的一号」起，避免 31*months 带
    # 出残月（残月会收整月服务器费）
    first_month = today.replace(day=1)
    for _ in range(months - 1):
        first_month = (first_month.replace(day=1) - timedelta(days=1)).replace(day=1)

    rows = session.exec(
        select(AdminMetricsDaily)
        .where(col(AdminMetricsDaily.day) >= first_month)
        .order_by(col(AdminMetricsDaily.day))
    ).all()
    by_month: dict[str, dict[str, float]] = {}
    for r in rows:
        m = _month_of(r.day)
        bucket = by_month.setdefault(
            m,
            {
                "asr_seconds": 0.0,
                "llm_calls": 0.0,
                "attempts": 0.0,
                "tokens_in": 0.0,
                "tokens_out": 0.0,
                "call_days": 0.0,
                # 有调用但当日没记到 usage 的天数（缺一天都不切真实基数）
                "call_days_missing_tokens": 0.0,
            },
        )
        bucket["asr_seconds"] += r.asr_seconds or 0.0
        bucket["attempts"] += r.attempts
        calls_today = sum((r.llm_calls_by_kind or {}).values())
        bucket["llm_calls"] += calls_today
        if calls_today:
            bucket["call_days"] += 1
        # 真实 token：非 null 才算记到（采样器保证 0 用量不落列）
        recorded = r.llm_tokens_in is not None or r.llm_tokens_out is not None
        if calls_today and not recorded:
            bucket["call_days_missing_tokens"] += 1
        if recorded:
            bucket["tokens_in"] += r.llm_tokens_in or 0
            bucket["tokens_out"] += r.llm_tokens_out or 0

    reconciles = {
        row.month: row for row in session.exec(select(AdminCostReconcile)).all()
    }

    est_cny = settings.COST_LLM_CNY_PER_MTOK_IN * settings.COST_LLM_EST_TOKENS_IN
    est_cny += settings.COST_LLM_CNY_PER_MTOK_OUT * settings.COST_LLM_EST_TOKENS_OUT
    llm_cny_per_call = est_cny / 1_000_000

    result: list[DashboardCostMonth] = []
    # 从最早有数据的月份起，逐月输出（无作答的月也输出，服务器成本仍发生）
    month_keys = sorted(set(by_month) | set(reconciles))
    for m in month_keys:
        b = by_month.get(
            m,
            {
                "asr_seconds": 0.0,
                "llm_calls": 0.0,
                "attempts": 0.0,
                "tokens_in": 0.0,
                "tokens_out": 0.0,
                "call_days": 0.0,
                "call_days_missing_tokens": 0.0,
            },
        )
        asr_cny = round(b["asr_seconds"] / 3600 * settings.COST_ASR_CNY_PER_HOUR, 2)
        # LLM 计费基数：有调用且每个调用日都记到了 usage → 真实 token；
        # 否则回退调用量估算（历史月靠回填的 rubric 估算；切换当月低估、
        # 次月起自愈）
        token_basis = b["call_days"] > 0 and b["call_days_missing_tokens"] == 0
        if token_basis:
            llm_basis = "tokens"
            llm_cny = round(
                b["tokens_in"] / 1_000_000 * settings.COST_LLM_CNY_PER_MTOK_IN
                + b["tokens_out"] / 1_000_000 * settings.COST_LLM_CNY_PER_MTOK_OUT,
                2,
            )
        else:
            llm_basis = "estimated"
            llm_cny = round(b["llm_calls"] * llm_cny_per_call, 2)
        server_cny = settings.COST_SERVER_CNY_PER_MONTH
        total = round(asr_cny + llm_cny + server_cny, 2)
        actual = reconciles.get(m)
        deviation = (
            round((actual.amount_cny - total) / total * 100, 1)
            if actual and total > 0
            else None
        )
        result.append(
            DashboardCostMonth(
                month=m,
                asr_seconds=round(b["asr_seconds"], 1),
                llm_calls=int(b["llm_calls"]),
                llm_basis=llm_basis,
                llm_tokens_in=int(b["tokens_in"]) if token_basis else None,
                llm_tokens_out=int(b["tokens_out"]) if token_basis else None,
                asr_cny=asr_cny,
                llm_cny=llm_cny,
                server_cny=server_cny,
                total_cny=total,
                attempts=int(b["attempts"]),
                actual_cny=actual.amount_cny if actual else None,
                deviation_pct=deviation,
            )
        )
    return DashboardCost(
        months=result,
        prices={
            "asr_cny_per_hour": settings.COST_ASR_CNY_PER_HOUR,
            "llm_cny_per_mtok_in": settings.COST_LLM_CNY_PER_MTOK_IN,
            "llm_cny_per_mtok_out": settings.COST_LLM_CNY_PER_MTOK_OUT,
            "server_cny_per_month": settings.COST_SERVER_CNY_PER_MONTH,
        },
        note="ASR 按作答音频秒数×单价（精确）；LLM 优先按真实 token 用量"
        "（usage 记账覆盖当月全部调用日时），否则按调用量×估算 token"
        "（历史为问答题 rubric 回算）；服务器为固定月费。实际以云账单为准。",
    )


@router.put("/cost/reconcile", response_model=AdminCostReconcile)
def upsert_cost_reconcile(
    payload: AdminCostReconcileIn,
    session: SessionDep,
    _admin: SuperUserDep,
) -> AdminCostReconcile:
    """录入/更新当月实际账单金额（对账）。"""
    import re

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", payload.month):
        raise HTTPException(status_code=422, detail="月份格式应为 YYYY-MM")
    from app.models import get_datetime_utc

    row = session.get(AdminCostReconcile, payload.month)
    if row is None:
        row = AdminCostReconcile(month=payload.month, amount_cny=payload.amount_cny)
        session.add(row)
    row.amount_cny = payload.amount_cny
    row.note = payload.note
    row.updated_at = get_datetime_utc()
    session.commit()
    session.refresh(row)
    return row
