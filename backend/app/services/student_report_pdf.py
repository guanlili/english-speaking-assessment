"""学生个人学情报告 PDF。

聚合口径对齐学习报告 / 进步轨迹 / 个人诊断，只服务学生本人。
百分位只留下一个整数（或省略），不把其他同学的姓名和分数写进报告。
证据列表只有作答编号和「请在 App 中打开」，不放签名外链。
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fpdf import FPDF
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Classroom,
    ClassroomExercise,
    PracticeSession,
    Student,
    User,
)
from app.services import exam as exam_service
from app.services.audio_export import sanitize_component, to_shanghai

FONT_PATH = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / "fonts"
    / "NotoSansSC-Regular.otf"
)
EVIDENCE_LIMIT = 40
FEEDBACK_LIMIT = 20
MISSED_WORD_LIMIT = 12
MIN_PERCENTILE_SAMPLE = 5
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_cmap: set[int] | None = None

ITEM_LABEL = {
    AttemptItemType.PASSAGE: "文章朗读",
    AttemptItemType.REPEAT: "听句复述",
    AttemptItemType.QUESTION: "情景问答",
}
DIM_LABEL = {
    "fluency": "流利度",
    "vocabulary": "词汇",
    "grammar": "语法",
    "task": "任务完成",
}


class ReportForbidden(Exception):
    """请求人不是该课堂里的学生本人。"""


@dataclass(frozen=True)
class PercentileView:
    """hidden：开关关闭；insufficient：样本 <5；no_score：本人没有问答参考分；value：可展示。"""

    mode: str
    percent: int | None = None


@dataclass(frozen=True)
class TrendRow:
    date: str
    question_avg: float | None
    repeat_completeness_avg: float | None
    attempt_count: int


@dataclass(frozen=True)
class EvidenceItem:
    attempt_id: uuid.UUID
    item_type: str
    item_text: str
    overall: int | None
    created_at: datetime | None
    teacher_feedback: str | None
    teacher_review_tags: tuple[str, ...]


@dataclass(frozen=True)
class StudentReport:
    display_name: str
    classroom_name: str
    classroom_code: str
    start: datetime
    end: datetime
    session_count: int
    completed_items: int
    total_items: int
    speaking_minutes: float
    reading_avg: float | None
    question_avg: float | None
    percentile: PercentileView
    trend: tuple[TrendRow, ...]
    missed_words: tuple[tuple[str, int], ...]
    dimension_means: dict[str, float]
    weakest_dimension: str | None
    evidence: tuple[EvidenceItem, ...]
    feedback: tuple[EvidenceItem, ...]
    evidence_truncated: bool
    feedback_truncated: bool
    has_active_exam: bool
    scored_count: int


@dataclass(frozen=True)
class PdfBuild:
    byte_size: int
    artifact_name: str
    included: int


def percentile_view(
    *,
    enabled: bool,
    mine: float | None,
    sample_size: int,
    below_others: int,
) -> PercentileView:
    """sample_size 含本人（本人有问答参考分时）。不接收、不返回其他人的分数。"""
    if not enabled:
        return PercentileView("hidden")
    if sample_size < MIN_PERCENTILE_SAMPLE:
        return PercentileView("insufficient")
    if mine is None:
        return PercentileView("no_score")
    others = sample_size - 1
    if others <= 0:
        return PercentileView("value", 100)
    percent = int(round(100 * below_others / others))
    return PercentileView("value", max(0, min(100, percent)))


def resolve_report_window(
    *,
    start: datetime | None,
    end: datetime | None,
    days: int | None,
    recent_days: int | None,
) -> tuple[datetime, datetime]:
    """未指定范围时默认最近 90 天（且不超过 EXPORT_RECENT_DAYS_MAX）。自定义范围同样不得超过该上限。"""
    cap = settings.EXPORT_RECENT_DAYS_MAX
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("export_range_too_wide")
        start = _aware(start)
        end = _aware(end)
        if end < start or (end - start) > timedelta(
            days=cap, hours=23, minutes=59, seconds=59
        ):
            raise ValueError("export_range_too_wide")
        return start, end
    chosen = days if days is not None else recent_days
    if chosen is None:
        chosen = min(90, cap)
    if chosen < 1 or chosen > cap:
        raise ValueError("export_range_too_wide")
    return _calendar_window(chosen)


def report_download_name(*, student_name: str, start: datetime, end: datetime) -> str:
    who = sanitize_component(student_name or "学生", "学生", 24)
    span = (
        f"{to_shanghai(start).strftime('%Y%m%d')}-{to_shanghai(end).strftime('%Y%m%d')}"
    )
    root = sanitize_component(f"SpeakUp_学情报告_{who}_{span}", "SpeakUp_学情报告", 180)
    if not root.startswith("SpeakUp_"):
        root = f"SpeakUp_{root}"
    return f"{root[:180]}.pdf"


def load_student_report(
    session: Session,
    filt: dict[str, object],
    requester_user_id: uuid.UUID,
) -> StudentReport:
    """按冻结的 filter 读取本人数据。身份不符抛 ReportForbidden，不返回任何内容。"""
    if str(filt.get("requester_user_id") or "") != str(requester_user_id):
        raise ReportForbidden
    user = session.get(User, requester_user_id)
    if user is None or user.role != "student":
        raise ReportForbidden
    classroom_id = _as_uuid(filt.get("classroom_id"))
    classroom = session.get(Classroom, classroom_id) if classroom_id else None
    if classroom is None:
        raise ReportForbidden
    student = session.exec(
        select(Student).where(
            Student.user_id == user.id,
            Student.classroom_id == classroom.id,
        )
    ).first()
    if student is None or student.user_id != user.id:
        raise ReportForbidden
    start = _parse_dt(filt.get("from"))
    end = _parse_dt(filt.get("to"))
    if start is None or end is None:
        raise ValueError("export_range_too_wide")
    cap = settings.EXPORT_RECENT_DAYS_MAX
    if end < start or (end - start) > timedelta(
        days=cap, hours=23, minutes=59, seconds=59
    ):
        raise ValueError("export_range_too_wide")
    exercise_id = _as_uuid(filt.get("exercise_id"))
    start_date = to_shanghai(start).date()
    end_date = to_shanghai(end).date()
    locked = _locked_exam_session_ids(session, classroom.id, start_date, end_date)
    sessions = list(
        session.exec(
            select(PracticeSession).where(
                PracticeSession.classroom_id == classroom.id,
                PracticeSession.student_id == student.id,
                PracticeSession.session_date >= start_date,
                PracticeSession.session_date <= end_date,
            )
        ).all()
    )
    if exercise_id is not None:
        sessions = [row for row in sessions if row.assignment_id == exercise_id]
    has_active_exam = any(row.id in locked for row in sessions)
    visible = [row for row in sessions if row.id not in locked]
    visible_ids = [row.id for row in visible]
    attempts = (
        list(
            session.exec(
                select(Attempt)
                .where(
                    col(Attempt.session_id).in_(visible_ids),
                    col(Attempt.created_at) >= start,
                    col(Attempt.created_at) <= end,
                )
                .order_by(col(Attempt.created_at), col(Attempt.id))
            ).all()
        )
        if visible_ids
        else []
    )
    attempts = [row for row in attempts if row.item_type != AttemptItemType.INSTRUCTION]
    latest: dict[tuple[uuid.UUID | None, uuid.UUID], Attempt] = {}
    for row in attempts:
        latest[(row.session_id, row.item_id)] = row
    scored = [row for row in latest.values() if row.status == AttemptStatus.DONE]
    exercise_ids = {row.assignment_id for row in visible if row.assignment_id}
    exercises = (
        {
            row.id: row
            for row in session.exec(
                select(ClassroomExercise).where(
                    col(ClassroomExercise.id).in_(exercise_ids)
                )
            ).all()
        }
        if exercise_ids
        else {}
    )
    total = 0
    for practice in visible:
        exercise = (
            exercises.get(practice.assignment_id) if practice.assignment_id else None
        )
        if exercise is None:
            continue
        total += sum(
            not isinstance(item, dict) or item.get("type") != "instruction"
            for item in exercise.snapshot_items
        )
    reading_avg = _average(scored, (AttemptItemType.PASSAGE, AttemptItemType.REPEAT))
    question_avg, percentile = _overview_question(
        session,
        classroom=classroom,
        student_id=student.id,
        start=start,
        end=end,
        exercise_id=exercise_id,
        locked=locked,
    )
    done_rows = [row for row in attempts if row.status == AttemptStatus.DONE]
    means, weakest = _dimension_means(done_rows)
    feedback, feedback_truncated = _feedback(scored)
    return StudentReport(
        display_name=student.display_name,
        classroom_name=classroom.name,
        classroom_code=classroom.code,
        start=start,
        end=end,
        session_count=len(visible),
        completed_items=len(scored),
        total_items=max(total, len(latest)),
        speaking_minutes=round(sum(row.duration_s for row in attempts) / 60, 1),
        reading_avg=reading_avg,
        question_avg=question_avg,
        percentile=percentile,
        trend=tuple(_trend(done_rows)),
        missed_words=tuple(_missed(done_rows)),
        dimension_means=means,
        weakest_dimension=weakest,
        evidence=tuple(_evidence(scored)),
        feedback=tuple(feedback),
        evidence_truncated=len(scored) > EVIDENCE_LIMIT,
        feedback_truncated=feedback_truncated,
        has_active_exam=has_active_exam,
        scored_count=len(scored),
    )


def render_student_report(report: StudentReport, dest: Path) -> PdfBuild:
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
        included=report.scored_count,
    )


def _draw(pdf: _ReportPDF, report: StudentReport) -> None:
    pdf.heading("学情报告", 22)
    pdf.small("Personal learning report")
    pdf.body("参考分不是官方成绩。")
    pdf.small("These scores are a reference, not an official result.")
    pdf.gap(2)
    pdf.meta("学生", report.display_name, "Student")
    pdf.meta("课堂", f"{report.classroom_name} · {report.classroom_code}", "Classroom")
    pdf.meta(
        "时间范围",
        f"{to_shanghai(report.start).strftime('%Y-%m-%d')} - "
        f"{to_shanghai(report.end).strftime('%Y-%m-%d')}",
        "Period",
    )
    pdf.meta(
        "生成时间",
        to_shanghai(datetime.now(UTC)).strftime("%Y-%m-%d %H:%M") + "（北京时间）",
        "Generated",
    )
    pdf.gap(2)
    pdf.body(
        "本报告中的跟读参考分、情景问答参考分都是练习参考，不是官方成绩。"
        "未结束的考试不进入本报告。"
    )
    pdf.small("Reference scores are practice feedback, not an official result.")
    if report.scored_count == 0:
        pdf.gap(3)
        pdf.body("本阶段暂无已出分作答。报告已生成，之后有练习记录时可以重新导出。")
        pdf.small("No scored answers in this period.")

    pdf.section("一、学习概览", "Overview")
    pdf.body(
        f"练习 {report.session_count} 轮，完成 {report.completed_items}/{report.total_items} 题"
        f"，开口 {report.speaking_minutes} 分钟"
    )
    pdf.body(f"跟读参考分均值：{_num(report.reading_avg)}")
    pdf.small("Reading and repeat reference average")
    pdf.body(f"情景问答参考分均值：{_num(report.question_avg)}")
    pdf.small("Question reference average")
    _draw_percentile(pdf, report.percentile)
    if report.has_active_exam:
        pdf.body("部分考试尚未结束，结束后可以重新导出。")

    pdf.section("二、进步趋势", "Trend")
    pdf.small("每日情景问答参考分与听句复述完整度，按已出分作答统计。")
    if not report.trend:
        pdf.body("本阶段暂无已出分趋势。")
    else:
        pdf.trend_table(report.trend)

    pdf.section("三、弱项", "Weaknesses")
    if report.missed_words:
        words = "、".join(f"{word}（{count}）" for word, count in report.missed_words)
        pdf.body(f"跟读 / 复述高频漏词：{words}")
    else:
        pdf.body("本阶段暂无跟读或复述漏词。")
    if report.dimension_means:
        parts = [
            f"{DIM_LABEL[key]} {_num(report.dimension_means.get(key))}"
            for key in ("fluency", "vocabulary", "grammar", "task")
            if key in report.dimension_means
        ]
        weakest = DIM_LABEL.get(report.weakest_dimension or "", "")
        pdf.body("情景问答维度均值（0-4）：" + "，".join(parts))
        if weakest:
            pdf.body(f"相对较弱的维度：{weakest}")
        pdf.small(
            "Question rubric means. The lowest dimension is only a practice hint."
        )
    else:
        pdf.body("本阶段暂无情景问答维度样本。")

    pdf.section("四、作答证据", "Evidence")
    pdf.small("只有作答编号。请在 App 中打开，报告里没有外链。")
    if not report.evidence:
        pdf.body("本阶段暂无已出分作答。")
    for item in report.evidence:
        pdf.evidence(item)
    if report.evidence_truncated:
        pdf.body(f"仅列出最近 {EVIDENCE_LIMIT} 条。更早的记录请在 App 中查看。")

    if report.feedback:
        pdf.section("五、教师建议", "Teacher feedback")
        for item in report.feedback:
            pdf.feedback(item)
        if report.feedback_truncated:
            pdf.body(f"仅列出最近 {FEEDBACK_LIMIT} 条教师建议。")


def _draw_percentile(pdf: _ReportPDF, view: PercentileView) -> None:
    if view.mode == "hidden":
        return
    if view.mode == "insufficient":
        pdf.body("班级样本不足")
        pdf.small("Not enough classmates with a scored question in this window.")
        return
    if view.mode == "no_score":
        pdf.body("本阶段没有情景问答参考分，不显示班级位置。")
        return
    if view.mode == "value" and view.percent is not None:
        pdf.body(f"情景问答参考分超过班级 {view.percent}% 的同学。")
        pdf.small(
            "Same classroom and window. Classmates need at least one scored question. "
            "Other students' scores are not shown."
        )


class _ReportPDF(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4", unit="mm")
        self.add_font("Noto", fname=str(FONT_PATH))
        self.set_margins(15, 18, 15)
        self.set_auto_page_break(auto=True, margin=16)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_xy(self.l_margin, 8)
        self.set_font("Noto", size=9)
        self.set_text_color(110, 110, 110)
        self.cell(
            0,
            6,
            _fit("学情报告 / 参考分不是官方成绩"),
            new_x="LMARGIN",
            new_y="NEXT",
        )

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Noto", size=8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, _fit(f"{self.page_no()}"), align="C")

    def heading(self, text: str, size: float) -> None:
        self.set_font("Noto", size=size)
        self.set_text_color(28, 25, 23)
        self.multi_cell(0, 10, _fit(text), new_x="LMARGIN", new_y="NEXT")

    def section(self, title: str, english: str) -> None:
        self.ln(3)
        self.set_font("Noto", size=14)
        self.set_text_color(28, 25, 23)
        self.multi_cell(0, 8, _fit(title), new_x="LMARGIN", new_y="NEXT")
        self.small(english)

    def body(self, text: str) -> None:
        self.set_font("Noto", size=11)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 6.5, _fit(_public(text)), new_x="LMARGIN", new_y="NEXT")

    def small(self, text: str) -> None:
        self.set_font("Noto", size=9)
        self.set_text_color(110, 110, 110)
        self.multi_cell(0, 5, _fit(_public(text)), new_x="LMARGIN", new_y="NEXT")

    def gap(self, lines: float) -> None:
        self.ln(lines)

    def meta(self, label: str, value: str, english: str) -> None:
        self.set_font("Noto", size=11)
        self.set_text_color(40, 40, 40)
        self.multi_cell(
            0,
            6.5,
            _fit(_public(f"{label}：{value}")),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.small(english)

    def trend_table(self, rows: tuple[TrendRow, ...]) -> None:
        widths = (
            self.epw * 0.24,
            self.epw * 0.28,
            self.epw * 0.30,
            self.epw * 0.18,
        )
        headers = ("日期", "问答参考分", "复述完整度", "作答数")
        self._table_row(headers, widths, header=True)
        for row in rows:
            self._table_row(
                (
                    row.date,
                    _num(row.question_avg),
                    _num(row.repeat_completeness_avg),
                    str(row.attempt_count),
                ),
                widths,
                header=False,
            )

    def _table_row(
        self, cells: tuple[str, ...], widths: tuple[float, ...], *, header: bool
    ) -> None:
        self.set_font("Noto", size=9)
        height = 7
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()
        if header:
            self.set_fill_color(245, 242, 237)
            self.set_text_color(28, 25, 23)
        else:
            self.set_fill_color(255, 255, 255)
            self.set_text_color(40, 40, 40)
        for text, width in zip(cells, widths, strict=True):
            self.cell(
                width,
                height,
                _fit(text),
                border=1,
                fill=header,
                new_x="RIGHT",
                new_y="TOP",
            )
        self.ln(height)

    def evidence(self, item: EvidenceItem) -> None:
        self.ln(1)
        when = _stamp(item.created_at)
        label = ITEM_LABEL.get(item.item_type, "题目")
        score = "暂无参考分" if item.overall is None else f"参考分 {item.overall}"
        self.body(f"{when} / {label} / {score}")
        if item.item_text:
            self.body(f"题目：{item.item_text}")
        self.body(f"作答编号：{item.attempt_id}")
        self.body("请在 App 中打开这条作答。")

    def feedback(self, item: EvidenceItem) -> None:
        self.ln(1)
        label = ITEM_LABEL.get(item.item_type, "题目")
        self.body(f"{_stamp(item.created_at)} / {label}")
        if item.teacher_review_tags:
            self.body("标签：" + "、".join(item.teacher_review_tags))
        if item.teacher_feedback:
            self.body(f"建议：{item.teacher_feedback}")
        self.body(f"作答编号：{item.attempt_id}")
        self.body("请在 App 中打开这条作答。")


def _overview_question(
    session: Session,
    *,
    classroom: Classroom,
    student_id: uuid.UUID,
    start: datetime,
    end: datetime,
    exercise_id: uuid.UUID | None,
    locked: set[uuid.UUID],
) -> tuple[float | None, PercentileView]:
    """概览里的问答参考分，以及可选的班级位置。开关关闭时不读取其他同学的分数。"""
    if not classroom.show_report_percentile:
        own = _question_averages(
            session,
            classroom_id=classroom.id,
            start=start,
            end=end,
            exercise_id=exercise_id,
            locked=locked,
            only_student_id=student_id,
        )
        return own.get(student_id), PercentileView("hidden")
    avgs = _question_averages(
        session,
        classroom_id=classroom.id,
        start=start,
        end=end,
        exercise_id=exercise_id,
        locked=locked,
        only_student_id=None,
    )
    mine = avgs.get(student_id)
    below = (
        sum(1 for sid, avg in avgs.items() if sid != student_id and avg < mine)
        if mine is not None
        else 0
    )
    return mine, percentile_view(
        enabled=True,
        mine=mine,
        sample_size=len(avgs),
        below_others=below,
    )


def _question_averages(
    session: Session,
    *,
    classroom_id: uuid.UUID,
    start: datetime,
    end: datetime,
    exercise_id: uuid.UUID | None,
    locked: set[uuid.UUID],
    only_student_id: uuid.UUID | None,
) -> dict[uuid.UUID, float]:
    """每个学生：窗口内情景问答、已出分、每个题位最新一次 overall 的均值。

    只选出分数列。开关关闭时调用方不会走到全班这条路径。
    """
    # sqlmodel.select 的重载只覆盖到较少列；这里只要分数相关列，避免整行 JSON。
    stmt = (
        select(  # ty: ignore[no-matching-overload]
            Attempt.student_id,
            Attempt.session_id,
            Attempt.item_id,
            Attempt.overall,
            Attempt.created_at,
            Attempt.id,
        )
        .join(PracticeSession, col(Attempt.session_id) == PracticeSession.id)
        .join(Student, col(Attempt.student_id) == Student.id)
        .where(
            Student.classroom_id == classroom_id,
            PracticeSession.classroom_id == classroom_id,
            Attempt.item_type == AttemptItemType.QUESTION,
            Attempt.status == AttemptStatus.DONE,
            col(Attempt.created_at) >= start,
            col(Attempt.created_at) <= end,
            col(Attempt.overall).is_not(None),
        )
    )
    if only_student_id is not None:
        stmt = stmt.where(Attempt.student_id == only_student_id)
    if exercise_id is not None:
        stmt = stmt.where(PracticeSession.assignment_id == exercise_id)
    if locked:
        stmt = stmt.where(col(Attempt.session_id).not_in(locked))
    latest: dict[
        tuple[uuid.UUID, uuid.UUID, uuid.UUID], tuple[datetime, uuid.UUID, int]
    ] = {}
    for (
        student_id,
        session_id,
        item_id,
        overall,
        created_at,
        attempt_id,
    ) in session.exec(stmt).all():
        if (
            student_id is None
            or session_id is None
            or created_at is None
            or attempt_id is None
            or not isinstance(overall, int)
        ):
            continue
        key = (student_id, session_id, item_id)
        previous = latest.get(key)
        if previous is None or (created_at, attempt_id) >= (previous[0], previous[1]):
            latest[key] = (created_at, attempt_id, overall)
    buckets: dict[uuid.UUID, list[int]] = defaultdict(list)
    for (student_id, _session_id, _item_id), (
        _created,
        _attempt_id,
        overall,
    ) in latest.items():
        buckets[student_id].append(overall)
    return {
        student_id: round(sum(values) / len(values), 1)
        for student_id, values in buckets.items()
        if values
    }


def _locked_exam_session_ids(
    session: Session,
    classroom_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> set[uuid.UUID]:
    rows = session.exec(
        select(PracticeSession, ClassroomExercise)
        .join(
            ClassroomExercise,
            col(PracticeSession.assignment_id) == ClassroomExercise.id,
        )
        .where(
            PracticeSession.classroom_id == classroom_id,
            col(ClassroomExercise.is_exam).is_(True),
            PracticeSession.session_date >= start_date,
            PracticeSession.session_date <= end_date,
        )
    ).all()
    started = [practice.id for practice, _exercise in rows if practice.exam_started_at]
    first = exam_service.first_submitted_by_session(session, started)
    locked: set[uuid.UUID] = set()
    for practice, exercise in rows:
        if exam_service.exam_feedback_locked(
            session,
            practice,
            exercise,
            first_submitted=first.get(practice.id, {}),
        ):
            locked.add(practice.id)
    return locked


def _average(rows: list[Attempt], types: tuple[str, ...]) -> float | None:
    scores = [
        row.overall
        for row in rows
        if row.item_type in types and row.overall is not None
    ]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


def _trend(rows: list[Attempt]) -> list[TrendRow]:
    tz = ZoneInfo(settings.PRACTICE_TZ)
    question: dict[str, list[int]] = defaultdict(list)
    repeat: dict[str, list[int]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for row in rows:
        if row.created_at is None:
            continue
        day = row.created_at.astimezone(tz).date().isoformat()
        counts[day] += 1
        if row.item_type == AttemptItemType.QUESTION and row.overall is not None:
            question[day].append(row.overall)
        if row.item_type == AttemptItemType.REPEAT and row.completeness is not None:
            repeat[day].append(row.completeness)
    out: list[TrendRow] = []
    for day in sorted(counts):
        q = question.get(day) or []
        r = repeat.get(day) or []
        out.append(
            TrendRow(
                date=day,
                question_avg=round(sum(q) / len(q), 1) if q else None,
                repeat_completeness_avg=round(sum(r) / len(r), 1) if r else None,
                attempt_count=counts[day],
            )
        )
    return out


def _missed(rows: list[Attempt]) -> list[tuple[str, int]]:
    from app.api.routes.class_progress import _accumulate_missed_words

    counter: Counter[str] = Counter()
    for row in rows:
        if row.item_type in (AttemptItemType.PASSAGE, AttemptItemType.REPEAT):
            _accumulate_missed_words(counter, row)
    return counter.most_common(MISSED_WORD_LIMIT)


def _dimension_means(rows: list[Attempt]) -> tuple[dict[str, float], str | None]:
    sums: dict[str, float] = {}
    count = 0
    for row in rows:
        if row.item_type != AttemptItemType.QUESTION or not isinstance(
            row.rubric, dict
        ):
            continue
        values = {
            key: row.rubric.get(key)
            for key in ("fluency", "vocabulary", "grammar", "task")
        }
        if not all(isinstance(value, (int, float)) for value in values.values()):
            continue
        count += 1
        for key, value in values.items():
            if isinstance(value, (int, float)):
                sums[key] = sums.get(key, 0.0) + float(value)
    if not count:
        return {}, None
    means = {key: round(total / count, 1) for key, total in sums.items()}
    weakest = min(
        ("fluency", "vocabulary", "grammar", "task"), key=lambda key: means[key]
    )
    return means, weakest


def _evidence(scored: list[Attempt]) -> list[EvidenceItem]:
    ordered = sorted(
        scored,
        key=lambda row: (row.created_at or datetime.min.replace(tzinfo=UTC), row.id),
        reverse=True,
    )
    return [_item(row) for row in ordered[:EVIDENCE_LIMIT]]


def _feedback(scored: list[Attempt]) -> tuple[list[EvidenceItem], bool]:
    picked = [
        row
        for row in scored
        if (row.teacher_feedback and row.teacher_feedback.strip())
        or row.teacher_review_tags
    ]
    ordered = sorted(
        picked,
        key=lambda row: (row.created_at or datetime.min.replace(tzinfo=UTC), row.id),
        reverse=True,
    )
    return [_item(row) for row in ordered[:FEEDBACK_LIMIT]], len(
        ordered
    ) > FEEDBACK_LIMIT


def _item(row: Attempt) -> EvidenceItem:
    snapshot = row.item_snapshot if isinstance(row.item_snapshot, dict) else {}
    raw = snapshot.get("text") or snapshot.get("title") or ""
    tags = tuple(
        tag for tag in (row.teacher_review_tags or []) if isinstance(tag, str) and tag
    )
    return EvidenceItem(
        attempt_id=row.id,
        item_type=row.item_type,
        item_text=str(raw).strip()[:180],
        overall=row.overall,
        created_at=row.created_at,
        teacher_feedback=(row.teacher_feedback or "").strip()[:800] or None,
        teacher_review_tags=tags,
    )


def _calendar_window(days: int) -> tuple[datetime, datetime]:
    tz = ZoneInfo(settings.PRACTICE_TZ)
    today = datetime.now(tz).date()
    start_day = today - timedelta(days=days - 1)
    start = datetime.combine(start_day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(today, time.max, tzinfo=tz).astimezone(UTC)
    return start, end


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _aware(parsed)


def _as_uuid(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _num(value: float | None) -> str:
    if value is None:
        return "暂无"
    return f"{value:.1f}"


def _stamp(value: datetime | None) -> str:
    if value is None:
        return "时间不详"
    return to_shanghai(value).strftime("%Y-%m-%d %H:%M")


def _public(text: str) -> str:
    return _URL.sub("（链接已省略）", text)


def _glyph_set() -> set[int]:
    global _cmap
    if _cmap is None:
        from fontTools.ttLib import TTFont

        font = TTFont(FONT_PATH)
        table = font.getBestCmap() or {}
        _cmap = set(table)
        font.close()
    return _cmap


def _fit(text: str) -> str:
    cmap = _glyph_set()
    out: list[str] = []
    for ch in text.replace("\r", ""):
        if ch == "\n" or ord(ch) in cmap:
            out.append(ch)
        elif ch == "\t":
            out.append(" ")
        else:
            out.append("□")
    return "".join(out)
