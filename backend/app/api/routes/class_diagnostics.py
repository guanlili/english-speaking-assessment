"""课堂异常：设备端自报 + 当前发布最新作答的服务端状态。"""

import uuid
from datetime import datetime, timedelta
from typing import Literal, cast

from fastapi import HTTPException
from sqlalchemy import select as sa_select
from sqlmodel import SQLModel, col, select

from app.api.deps import CurrentUser, SessionDep, StudentUserDep
from app.api.routes.class_shared import (
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
    _today_in_practice_tz,
    router,
)
from app.models import Attempt, PracticeSession, Student, get_datetime_utc

IssueKind = Literal["device", "audio", "upload"]
ISSUE_TTL_SECONDS = 300
SCORING_SLOW_SECONDS = 120


class RuntimeIssueIn(SQLModel):
    session_id: uuid.UUID
    issue: IssueKind | None


class ClassroomIssue(SQLModel):
    student_id: uuid.UUID
    display_name: str
    kind: Literal["device", "audio", "upload", "scoring_slow", "scoring_failed"]
    observed_at: datetime
    attempt_id: uuid.UUID | None = None


class ClassroomDiagnostics(SQLModel):
    checked_at: datetime
    issues: list[ClassroomIssue]


@router.put("/{code}/runtime-issue", response_model=None)
def report_runtime_issue(
    session: SessionDep, code: str, body: RuntimeIssueIn, current_user: StudentUserDep
) -> None:
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    ps = session.get(PracticeSession, body.session_id)
    if ps is None or ps.classroom_id != classroom.id or ps.student_id != student.id:
        raise HTTPException(404, detail="Session not found")
    ps.runtime_issue = body.issue
    ps.runtime_issue_at = get_datetime_utc()
    session.add(ps)
    session.commit()


@router.get("/{code}/diagnostics", response_model=ClassroomDiagnostics)
def read_classroom_diagnostics(
    session: SessionDep, code: str, current_user: CurrentUser
) -> ClassroomDiagnostics:
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    now = get_datetime_utc()
    sessions = session.exec(
        select(PracticeSession, Student)
        .join(Student, col(Student.id) == col(PracticeSession.student_id))
        .where(
            PracticeSession.classroom_id == classroom.id,
            Student.classroom_id == classroom.id,
            PracticeSession.assignment_id == classroom.current_exercise_id,
            PracticeSession.session_date == _today_in_practice_tz(),
            PracticeSession.mode == "daily",
        )
        .order_by(col(PracticeSession.created_at))
    ).all()
    # 当前学生当前轮；避免旧会话故障混入新的练习。
    latest = {student.id: (ps, student) for ps, student in sessions}
    by_session = {ps.id: student for ps, student in latest.values()}
    issues: list[ClassroomIssue] = []
    for ps, student in latest.values():
        if (
            ps.runtime_issue in ("device", "audio", "upload")
            and ps.runtime_issue_at is not None
            and ps.runtime_issue_at > now - timedelta(seconds=ISSUE_TTL_SECONDS)
        ):
            issues.append(
                ClassroomIssue(
                    student_id=student.id,
                    display_name=student.display_name,
                    kind=cast(IssueKind, ps.runtime_issue),
                    observed_at=ps.runtime_issue_at,
                )
            )
    if by_session:
        rows = (
            session.connection()
            .execute(
                sa_select(
                    col(Attempt.session_id),
                    col(Attempt.item_id),
                    col(Attempt.id),
                    col(Attempt.status),
                    col(Attempt.created_at),
                    col(Attempt.claimed_at),
                )
                .where(col(Attempt.session_id).in_(by_session))
                .distinct(col(Attempt.session_id), col(Attempt.item_id))
                .order_by(
                    col(Attempt.session_id),
                    col(Attempt.item_id),
                    col(Attempt.created_at).desc(),
                    col(Attempt.id).desc(),
                )
            )
            .all()
        )
        latest_attempts = {(row.session_id, row.item_id): row for row in rows}
        for row in latest_attempts.values():
            start = row.claimed_at or row.created_at
            if start is None:
                continue
            kind = (
                "scoring_failed"
                if row.status == "failed"
                else "scoring_slow"
                if row.status in ("queued", "scoring")
                and start < now - timedelta(seconds=SCORING_SLOW_SECONDS)
                else None
            )
            if kind is not None:
                student = by_session[row.session_id]
                issues.append(
                    ClassroomIssue(
                        student_id=student.id,
                        display_name=student.display_name,
                        kind=kind,
                        observed_at=start,
                        attempt_id=row.id,
                    )
                )
    return ClassroomDiagnostics(checked_at=now, issues=issues)
