"""管理员使用记录导出（CSV）：2026-10-23 手工导出 runbook 的服务化。

三口径与手工版一致：作答明细 / 练习轮次 / 学生汇总；北京时间时间戳、
中文列名、UTF-8 BOM（Excel 直开）。JSON 列读 Python 对象即可（SQLAlchemy
已反序列化），无需 ::jsonb。
"""

import csv
import io
from collections.abc import Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Classroom,
    ClassroomExercise,
    ItemListen,
    PracticeSession,
    Student,
    StudentBadge,
    User,
)
from app.services.csv_safety import csv_safe_row

BOM = "\ufeff"

ITEM_LABELS = {
    AttemptItemType.PASSAGE: "朗读跟读",
    AttemptItemType.REPEAT: "复述句子",
    AttemptItemType.QUESTION: "情景问答",
}
STATUS_LABELS = {
    AttemptStatus.DONE: "已评分",
    AttemptStatus.FAILED: "评分失败",
    AttemptStatus.QUEUED: "排队中",
    AttemptStatus.SCORING: "评分中",
}
MODE_LABELS = {"daily": "课堂练习", "explore": "自主练习", "followup": "补练"}


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.PRACTICE_TZ)


def _classroom_label(c: Classroom | None) -> str:
    return f"{c.name}（{c.code}）" if c else ""


def _dt(v: datetime | None) -> str:
    return v.astimezone(_tz()).strftime("%Y-%m-%d %H:%M:%S") if v else ""


def _num(v: float | int | None) -> object:
    return v if v is not None else ""


def _csv(rows: list[list[object]]) -> io.StringIO:
    buf = io.StringIO()
    buf.write(BOM)
    # 学生姓名/教师反馈等用户可控文本必须挡公式前缀（Excel/WPS 打开即求值）
    csv.writer(buf).writerows(csv_safe_row(row) for row in rows)
    buf.seek(0)
    return buf


def _cutoff(limit_days: int) -> datetime | None:
    if limit_days <= 0:
        return None
    return datetime.now(_tz()) - timedelta(days=limit_days)


def _guard_rows(count: int) -> None:
    """行数护栏超限即拒（稳定标识由路由层转 422），不产出部分 CSV。"""
    if count > settings.USAGE_EXPORT_MAX_ROWS:
        raise ValueError("usage_export_too_many_rows")


_ATTEMPT_HEADER: list[object] = [
    "日期",
    "时间",
    "学生",
    "区分码",
    "学号",
    "课堂",
    "练习模式",
    "发布练习",
    "题型",
    "题目标题",
    "题目内容",
    "录音时长秒",
    "状态",
    "评分引擎",
    "学生转写",
    "完整度",
    "流利度",
    "准确度",
    "总分",
    "AI建议",
    "教师批注",
    "标重点",
    "音频已清理",
]
_SESSION_HEADER: list[object] = [
    "练习日期",
    "开始时间",
    "学生",
    "区分码",
    "学号",
    "课堂",
    "模式",
    "发布练习",
    "模考限时",
    "档位",
    "星级",
    "作答题数",
    "已评分数",
    "平均总分",
    "最高分",
    "开考时间",
    "交卷时间",
    "考试用时分钟",
    "切屏次数",
    "离屏秒数",
]
_STUDENT_HEADER: list[object] = [
    "学生",
    "区分码",
    "学号",
    "课堂",
    "当前档位",
    "练习轮次",
    "作答总数",
    "已评分数",
    "平均总分",
    "最高总分",
    "首次使用",
    "最近使用",
    "听音次数",
    "徽章数",
    "被批注次数",
    "经验值",
    "连胜天数",
    "最近练习日",
    "建档日期",
]


def _load_attempt_rows(session: Session, limit_days: int) -> Sequence[tuple]:
    """作答明细的行集：六表左连、按创建时间正序，超出行数上限即拒。"""
    stmt = (
        select(  # ty: ignore[no-matching-overload] - 6 实体超出 exec 重载宽度
            Attempt, PracticeSession, ClassroomExercise, Student, User, Classroom
        )
        .join(
            PracticeSession,
            col(PracticeSession.id) == col(Attempt.session_id),
            isouter=True,
        )
        .join(
            ClassroomExercise,
            col(ClassroomExercise.id) == col(PracticeSession.assignment_id),
            isouter=True,
        )
        .join(Student, col(Student.id) == col(Attempt.student_id), isouter=True)
        .join(User, col(User.id) == col(Student.user_id), isouter=True)
        .join(
            Classroom,
            col(Classroom.id)
            == func.coalesce(
                col(PracticeSession.classroom_id), col(Student.classroom_id)
            ),
            isouter=True,
        )
        .order_by(col(Attempt.created_at))
    )
    cutoff = _cutoff(limit_days)
    if cutoff is not None:
        stmt = stmt.where(col(Attempt.created_at) >= cutoff)  # type: ignore[union-attr]
    # 行数护栏：LIMIT 上限+1 探测，超限即拒，不全量载入（与学生音频导出同思路）
    stmt = stmt.limit(settings.USAGE_EXPORT_MAX_ROWS + 1)
    rows = session.exec(stmt).all()  # type: ignore[arg-type]
    _guard_rows(len(rows))
    return rows


def _attempt_row(
    a: Attempt,
    ps: PracticeSession | None,
    ce: ClassroomExercise | None,
    s: Student | None,
    u: User | None,
    c: Classroom | None,
) -> list[object]:
    """一行一次录音的全部列。"""
    snap = a.item_snapshot or {}
    return [
        _dt(a.created_at)[:10],
        _dt(a.created_at)[11:19],
        s.display_name if s else "",
        s.suffix if s else "",
        u.username if u else "",
        _classroom_label(c),
        MODE_LABELS.get(ps.mode, ps.mode) if ps else "",
        ce.title if ce else "",
        ITEM_LABELS.get(a.item_type, a.item_type),
        snap.get("title", ""),
        snap.get("text", ""),
        round(a.duration_s, 1),
        STATUS_LABELS.get(a.status, a.status),
        a.engine,
        a.transcript or "",
        _num(a.completeness),
        _num(a.fluency),
        _num(a.accuracy),
        _num(a.overall),
        " ｜ ".join(str(x) for x in a.advice) if a.advice else "",
        a.teacher_feedback or "",
        "★" if a.teacher_focus else "",
        "是" if a.audio_purged_at else "",
    ]


def export_attempts(session: Session, limit_days: int) -> io.StringIO:
    """作答明细：一行一次录音（时间正序）。limit_days=0 表示全部。"""
    rows = _load_attempt_rows(session, limit_days)
    out: list[list[object]] = [_ATTEMPT_HEADER]
    for a, ps, ce, s, u, c in rows:
        out.append(_attempt_row(a, ps, ce, s, u, c))
    return _csv(out)


def _load_session_rows(session: Session, limit_days: int) -> Sequence[tuple]:
    """练习轮次的行集：按练习日 + 创建时间正序，超出行数上限即拒。"""
    stmt = (
        select(  # ty: ignore[no-matching-overload] - 5 实体超出 exec 重载宽度
            PracticeSession, Student, User, Classroom, ClassroomExercise
        )
        .join(Student, col(Student.id) == col(PracticeSession.student_id))
        .join(User, col(User.id) == col(Student.user_id), isouter=True)
        .join(Classroom, col(Classroom.id) == col(PracticeSession.classroom_id))
        .join(
            ClassroomExercise,
            col(ClassroomExercise.id) == col(PracticeSession.assignment_id),
            isouter=True,
        )
        .order_by(col(PracticeSession.session_date), col(PracticeSession.created_at))
    )
    cutoff = _cutoff(limit_days)
    if cutoff is not None:
        stmt = stmt.where(col(PracticeSession.created_at) >= cutoff)  # type: ignore[union-attr]
    stmt = stmt.limit(settings.USAGE_EXPORT_MAX_ROWS + 1)
    rows = session.exec(stmt).all()  # type: ignore[arg-type]
    _guard_rows(len(rows))
    return rows


def _session_attempt_aggregates(session: Session) -> dict[object, tuple]:
    """作答聚合一次 GROUP BY 预取（逐轮查询在轮次多时是 N+1）。"""
    attempt_agg: dict[object, tuple[int, int, float | None, int | None]] = {}
    for r in session.connection().execute(
        select(  # ty: ignore[no-matching-overload] - filter 链降级重载
            col(Attempt.session_id),
            func.count(),
            func.count().filter(col(Attempt.status) == AttemptStatus.DONE),
            func.avg(Attempt.overall).filter(col(Attempt.status) == AttemptStatus.DONE),
            func.max(Attempt.overall).filter(col(Attempt.status) == AttemptStatus.DONE),
        ).group_by(col(Attempt.session_id))
    ):
        attempt_agg[r[0]] = (r[1], r[2], r[3], r[4])
    return attempt_agg


def _session_row(
    ps: PracticeSession,
    s: Student,
    u: User | None,
    c: Classroom,
    ce: ClassroomExercise | None,
    aggs: tuple,
) -> list[object]:
    """一行一轮练习的全部列。"""
    used_min = (
        round((ps.exam_ended_at - ps.exam_started_at).total_seconds() / 60, 1)
        if ps.exam_started_at and ps.exam_ended_at
        else ""
    )
    return [
        ps.session_date.isoformat(),
        _dt(ps.created_at)[11:16],
        s.display_name,
        s.suffix or "",
        u.username if u else "",
        _classroom_label(c),
        MODE_LABELS.get(ps.mode, ps.mode),
        ce.title if ce else "",
        f"{ce.time_limit_minutes} 分钟" if ce and ce.is_exam else "",
        ps.band,
        _num(ps.stars),
        aggs[0],
        aggs[1],
        round(float(aggs[2]), 1) if aggs[2] is not None else "",
        _num(aggs[3]),
        _dt(ps.exam_started_at),
        _dt(ps.exam_ended_at),
        used_min,
        ps.tab_switch_count,
        ps.tab_switch_seconds,
    ]


def export_sessions(session: Session, limit_days: int) -> io.StringIO:
    """练习轮次：一行一轮（练习日正序）。"""
    rows = _load_session_rows(session, limit_days)
    attempt_agg = _session_attempt_aggregates(session)
    out: list[list[object]] = [_SESSION_HEADER]
    for ps, s, u, c, ce in rows:
        aggs = attempt_agg.get(ps.id, (0, 0, None, None))
        out.append(_session_row(ps, s, u, c, ce, aggs))
    return _csv(out)


def _load_student_rows(session: Session) -> Sequence[tuple[Student, User, Classroom]]:
    """学生档案行集：按课堂名 + 显示名排序，超出行数上限即拒。"""
    stmt = (
        select(Student, User, Classroom)
        .join(User, col(User.id) == col(Student.user_id), isouter=True)
        .join(Classroom, col(Classroom.id) == col(Student.classroom_id))
        .order_by(col(Classroom.name), col(Student.display_name))
        .limit(settings.USAGE_EXPORT_MAX_ROWS + 1)
    )
    rows = session.exec(stmt).all()
    _guard_rows(len(rows))
    return rows


def _student_attempt_aggregates(session: Session) -> dict[object, tuple]:
    """作答聚合一次预取（数量/完成/均分/最高/首末/批注）。"""
    student_agg: dict[object, tuple] = {}
    for r in session.connection().execute(
        select(  # ty: ignore[no-matching-overload] - filter 链降级重载
            col(Attempt.student_id),
            func.count(),
            func.count().filter(col(Attempt.status) == AttemptStatus.DONE),
            func.avg(Attempt.overall).filter(col(Attempt.status) == AttemptStatus.DONE),
            func.max(Attempt.overall).filter(col(Attempt.status) == AttemptStatus.DONE),
            func.min(col(Attempt.created_at)),
            func.max(col(Attempt.created_at)),
            func.count().filter(col(Attempt.teacher_feedback).is_not(None)),
        ).group_by(col(Attempt.student_id))
    ):
        student_agg[r[0]] = tuple(r[1:])
    return student_agg


def _student_session_counts(session: Session) -> dict[object, int]:
    """每个学生的练习轮次数。"""
    session_counts: dict[object, int] = {}
    for sid, n in session.connection().execute(
        select(col(PracticeSession.student_id), func.count()).group_by(
            col(PracticeSession.student_id)
        )
    ):
        session_counts[sid] = n
    return session_counts


def _student_listen_counts(session: Session) -> dict[object, int]:
    """每个学生的听音次数合计。"""
    listen_counts: dict[object, int] = {}
    for sid, total in session.connection().execute(
        select(col(ItemListen.student_id), func.sum(col(ItemListen.count))).group_by(
            col(ItemListen.student_id)
        )
    ):
        listen_counts[sid] = int(total or 0)
    return listen_counts


def _student_badge_counts(session: Session) -> dict[object, int]:
    """每个学生的徽章数。"""
    badge_counts: dict[object, int] = {}
    for sid, n in session.connection().execute(
        select(col(StudentBadge.student_id), func.count()).group_by(
            col(StudentBadge.student_id)
        )
    ):
        badge_counts[sid] = n
    return badge_counts


def _student_row(
    s: Student,
    u: User | None,
    c: Classroom,
    aggs: tuple,
    session_counts: dict[object, int],
    listen_counts: dict[object, int],
    badge_counts: dict[object, int],
) -> list[object]:
    """一行一个学生档案的全部列。"""
    return [
        s.display_name,
        s.suffix or "",
        u.username if u else "",
        _classroom_label(c),
        s.current_band,
        session_counts.get(s.id, 0),
        aggs[0],
        aggs[1],
        round(float(aggs[2]), 1) if aggs[2] is not None else "",
        _num(aggs[3]),
        _dt(aggs[4]),
        _dt(aggs[5]),
        listen_counts.get(s.id, 0),
        badge_counts.get(s.id, 0),
        aggs[6],
        s.xp,
        s.streak_days,
        s.last_practice_date.isoformat() if s.last_practice_date else "",
        _dt(s.created_at)[:10],
    ]


def export_students(session: Session) -> io.StringIO:
    """学生汇总：一行一个学生档案（课堂内排序）。"""
    rows = _load_student_rows(session)
    student_agg = _student_attempt_aggregates(session)
    session_counts = _student_session_counts(session)
    listen_counts = _student_listen_counts(session)
    badge_counts = _student_badge_counts(session)
    out: list[list[object]] = [_STUDENT_HEADER]
    for s, u, c in rows:
        aggs = student_agg.get(s.id, (0, 0, None, None, None, None, 0))
        out.append(
            _student_row(s, u, c, aggs, session_counts, listen_counts, badge_counts)
        )
    return _csv(out)
