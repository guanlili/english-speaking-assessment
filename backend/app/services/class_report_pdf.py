"""教师全班分析报告 PDF：窗口内班级指标、分数分布、进步趋势、题项对比。

复用学情报告（student_report_pdf）的排版原语、时间窗口与「题位最新
一次」评分口径；按日走势复用 class_trend.summarize（教师端趋势卡同源，
按 PRACTICE_TZ 切日）。每生均分只算情景问答（与学情报告/百分位同口径）；
题项对比覆盖所有有参考分的题型。
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlmodel import Session, col

from app.core.config import settings
from app.crud import classroom_teacher_allowed
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Classroom,
    PracticeSession,
    Student,
    User,
)
from app.services import class_trend
from app.services.audio_export import sanitize_component, to_shanghai
from app.services.student_report_pdf import (
    FONT_PATH,
    PdfBuild,
    ReportForbidden,
    TrendRow,
    _as_uuid,
    _aware,
    _locked_exam_session_ids,
    _num,
    _parse_dt,
    _ReportPDF,
    _stamp,
)

# 题项对比最多展示的低分题目数；超出截断并在文末说明
ITEM_LIMIT = 20
ITEM_TITLE_LIMIT = 40


@dataclass(frozen=True)
class StudentScoreRow:
    name: str
    student_no: str
    avg: float | None
    question_slots: int


@dataclass(frozen=True)
class ItemScoreRow:
    title: str
    avg: float | None
    attempts: int


@dataclass(frozen=True)
class ClassReport:
    classroom_name: str
    classroom_code: str
    window_start: datetime
    window_end: datetime
    student_count: int
    active_students: int
    done_count: int
    question_avg: float | None
    repeat_avg: float | None
    trend: tuple[TrendRow, ...]
    students: tuple[StudentScoreRow, ...]
    items: tuple[ItemScoreRow, ...]


def class_report_download_name(
    *, classroom_name: str, start: datetime, end: datetime
) -> str:
    who = sanitize_component(classroom_name or "班级", "班级", 24)
    span = (
        f"{to_shanghai(start).strftime('%Y%m%d')}-{to_shanghai(end).strftime('%Y%m%d')}"
    )
    root = sanitize_component(f"SpeakUp_班级报告_{who}_{span}", "SpeakUp_班级报告", 180)
    if not root.startswith("SpeakUp_"):
        root = f"SpeakUp_{root}"
    return f"{root[:180]}.pdf"


def load_class_report(
    session: Session,
    filt: dict[str, object],
    requester_user_id: uuid.UUID,
) -> ClassReport:
    """按冻结的 filter 读取班级数据。身份/归属不符抛 ReportForbidden。"""
    if str(filt.get("requester_user_id") or "") != str(requester_user_id):
        raise ReportForbidden
    user = session.get(User, requester_user_id)
    if user is None or user.role == "student":
        raise ReportForbidden
    classroom_id = _as_uuid(filt.get("classroom_id"))
    classroom = session.get(Classroom, classroom_id) if classroom_id else None
    if classroom is None or not classroom_teacher_allowed(classroom, user):
        raise ReportForbidden
    start = _parse_dt(filt.get("from"))
    end = _parse_dt(filt.get("to"))
    if start is None or end is None or end < start:
        raise ValueError("export_range_too_wide")
    start = _aware(start)
    end = _aware(end)

    roster = session.exec(  # ty: ignore[no-matching-overload]
        select(Student, User)
        .outerjoin(User, col(Student.user_id) == User.id)
        .where(
            Student.classroom_id == classroom.id  # ty: ignore[invalid-argument-type]
        )
        .order_by(Student.display_name)
    ).all()
    student_ids = [student.id for student, _ in roster]
    locked = _locked_exam_session_ids(session, classroom.id, start.date(), end.date())

    trend_days = [
        day
        for day in class_trend.summarize(
            session, student_ids, start, settings.PRACTICE_TZ
        )
        if date.fromisoformat(day.date) <= to_shanghai(end).date()
    ]
    trend = tuple(
        TrendRow(
            date=day.date,
            question_avg=day.question_avg,
            repeat_completeness_avg=day.repeat_completeness_avg,
            attempt_count=day.question_attempts,
        )
        for day in trend_days
    )

    active_students, done_count, question_avg, repeat_avg = (
        session.connection()
        .execute(
            select(
                func.count(func.distinct(Attempt.student_id)),
                func.count(),
                func.avg(Attempt.overall).filter(
                    col(Attempt.item_type) == AttemptItemType.QUESTION
                ),
                func.avg(Attempt.completeness).filter(
                    col(Attempt.item_type) == AttemptItemType.REPEAT
                ),
            ).where(
                col(Attempt.student_id).in_(student_ids),
                col(Attempt.status) == AttemptStatus.DONE,
                col(Attempt.created_at) >= start,
                col(Attempt.created_at) <= end,
                *([col(Attempt.session_id).not_in(locked)] if locked else []),
            )
        )
        .one()
    )

    # 题位最新一次：每生均分（情景问答）与题项对比（所有有分题型）同一份数据
    latest_stmt = (
        select(  # ty: ignore[no-matching-overload]
            Attempt.student_id,
            Attempt.session_id,
            Attempt.item_id,
            Attempt.item_type,
            Attempt.overall,
            Attempt.created_at,
            Attempt.id,
        )
        .join(PracticeSession, col(Attempt.session_id) == PracticeSession.id)
        .where(
            col(Attempt.student_id).in_(student_ids),
            col(PracticeSession.classroom_id) == classroom.id,
            col(Attempt.status) == AttemptStatus.DONE,
            col(Attempt.created_at) >= start,
            col(Attempt.created_at) <= end,
            col(Attempt.overall).is_not(None),
            *([col(Attempt.session_id).not_in(locked)] if locked else []),
        )
    )
    latest: dict[
        tuple[uuid.UUID, uuid.UUID, uuid.UUID],
        tuple[datetime, uuid.UUID, int, str | None],
    ] = {}
    for row in session.connection().execute(latest_stmt).all():
        student_id, session_id, item_id, item_type, overall, created_at, attempt_id = (
            row
        )
        if student_id is None or session_id is None or created_at is None:
            continue
        if not isinstance(overall, int):
            continue
        key = (student_id, session_id, item_id)
        previous = latest.get(key)
        if previous is None or (created_at, attempt_id) >= (previous[0], previous[1]):
            latest[key] = (created_at, attempt_id, overall, item_type)

    # 每生均分只算情景问答（与学情报告/百分位同源、与页首 question_avg 同口径）；
    # 题项对比保持全题型（跟读/复述的 overall 同样有参考意义）
    per_student: dict[uuid.UUID, list[int]] = {}
    per_item: dict[uuid.UUID, list[int]] = {}
    for (student_id, _session_id, item_id), (
        _created,
        _attempt_id,
        overall,
        item_type,
    ) in latest.items():
        if item_type == AttemptItemType.QUESTION:
            per_student.setdefault(student_id, []).append(overall)
        per_item.setdefault(item_id, []).append(overall)

    students = tuple(
        StudentScoreRow(
            name=student.display_name,
            student_no=(user.username or "") if user is not None else "",
            avg=(round(sum(scores) / len(scores), 1) if scores else None),
            question_slots=len(scores),
        )
        for student, user in roster
        if (scores := per_student.get(student.id)) is not None
    ) + tuple(
        StudentScoreRow(
            name=student.display_name,
            student_no=(user.username or "") if user is not None else "",
            avg=None,
            question_slots=0,
        )
        for student, user in roster
        if per_student.get(student.id) is None
    )
    students = tuple(sorted(students, key=lambda r: (r.avg is None, -(r.avg or 0))))

    item_rows: list[ItemScoreRow] = []
    if per_item:
        title_rows = (
            session.connection()
            .execute(
                select(Attempt.item_id, Attempt.item_snapshot)  # ty: ignore[no-matching-overload]
                .distinct(Attempt.item_id)
                .where(col(Attempt.item_id).in_(list(per_item.keys())))
                .order_by(Attempt.item_id, col(Attempt.created_at).desc())
            )
            .all()
        )
        titles = {
            item_id: (
                (snapshot or {}).get("title") or (snapshot or {}).get("text") or ""
                if isinstance(snapshot, dict)
                else ""
            )
            for item_id, snapshot in title_rows
        }
        item_rows = sorted(
            (
                ItemScoreRow(
                    title=str(titles.get(item_id, "")).strip() or "（未命名题目）",
                    avg=round(sum(scores) / len(scores), 1),
                    attempts=len(scores),
                )
                for item_id, scores in per_item.items()
            ),
            key=lambda row: (row.avg is None, row.avg or 0),
        )

    return ClassReport(
        classroom_name=classroom.name,
        classroom_code=classroom.code,
        window_start=start,
        window_end=end,
        student_count=len(roster),
        active_students=int(active_students or 0),
        done_count=int(done_count or 0),
        question_avg=round(float(question_avg), 1)
        if question_avg is not None
        else None,
        repeat_avg=round(float(repeat_avg), 1) if repeat_avg is not None else None,
        trend=trend,
        students=students,
        items=tuple(item_rows[:ITEM_LIMIT]),
    )


def render_class_report(report: ClassReport, dest: Path) -> PdfBuild:
    """写成 PDF。调用方负责在事务外落盘。"""
    if not FONT_PATH.is_file():
        raise FileNotFoundError(f"chinese font missing: {FONT_PATH.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(f".{dest.name}.partial")
    try:
        pdf = _ReportPDF()
        pdf.add_page()
        _draw(pdf, report)
        payload = bytes(pdf.output())
        partial.write_bytes(payload)
        partial.replace(dest)
    except Exception:
        partial.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        raise
    return PdfBuild(
        byte_size=dest.stat().st_size,
        artifact_name=dest.name,
        included=report.done_count,
    )


def _draw(pdf: _ReportPDF, report: ClassReport) -> None:
    pdf.heading("班级分析报告", 22)
    pdf.small("Class analysis report")
    pdf.body("参考分不是官方成绩。")
    pdf.gap(0.5)
    pdf.meta("班级", f"{report.classroom_name}（{report.classroom_code}）", "Class")
    pdf.meta(
        "统计窗口",
        f"{_stamp(report.window_start)} ~ {_stamp(report.window_end)}",
        "Window",
    )
    pdf.meta("学生数", str(report.student_count), "Students")
    pdf.meta("生成时间", _stamp(datetime.now(UTC)), "Generated at")

    pdf.section("一、班级概览", "Class overview")
    pdf.body(
        f"窗口内有已完成作答的学生 {report.active_students} / {report.student_count} 人；"
        f"共 {report.done_count} 次已完成作答。"
    )
    pdf.body(
        f"情景问答参考分均分 {_num(report.question_avg)}；"
        f"跟读完整度均分 {_num(report.repeat_avg)}。"
    )
    if report.active_students == 0:
        pdf.body("窗口内暂无已出分作答，以下各节为空。")

    pdf.section("二、分数分布", "Score distribution")
    scored = [row for row in report.students if row.avg is not None]
    buckets = [
        ("90 分及以上", lambda v: v >= 90),
        ("80 – 89", lambda v: 80 <= v < 90),
        ("70 – 79", lambda v: 70 <= v < 80),
        ("60 – 69", lambda v: 60 <= v < 70),
        ("60 分以下", lambda v: v < 60),
    ]
    if scored:
        for label, hit in buckets:
            count = sum(1 for row in scored if hit(row.avg or 0))
            pdf.body(f"{label}：{count} 人")
        pdf.gap(0.3)
        for row in report.students:
            mark = _num(row.avg) if row.avg is not None else "暂无"
            no = f"（{row.student_no}）" if row.student_no else ""
            pdf.small(f"{row.name}{no}  {mark} · {row.question_slots} 个题位")
    else:
        pdf.body("窗口内暂无已出分的情景问答作答。")

    pdf.section("三、进步趋势", "Progress trend")
    if report.trend:
        pdf.trend_table(report.trend)
    else:
        pdf.body("窗口内暂无可聚合的每日趋势。")

    pdf.section("四、题项对比（由低到高）", "Item comparison")
    if report.items:
        for index, row in enumerate(report.items, start=1):
            title = row.title[:ITEM_TITLE_LIMIT]
            pdf.small(f"{index}. {title} · 均 {_num(row.avg)} · {row.attempts} 人次")
    else:
        pdf.body("窗口内暂无题位级评分数据。")
    if len(report.items) >= ITEM_LIMIT:
        pdf.small(f"仅列出得分最低的前 {ITEM_LIMIT} 个题位。")

    pdf.gap(0.5)
    pdf.small(
        "口径说明：每生均分取窗口内情景问答每个题位最新一次参考分的均值；"
        "题项对比覆盖所有有参考分的题型，同样按题位最新一次计；"
        "未结束的考试不计入；参考分与模拟分不是官方成绩。"
    )
