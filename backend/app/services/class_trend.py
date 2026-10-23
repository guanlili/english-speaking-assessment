"""班级趋势：全班已完成作答的日聚合（教师端看均分与活跃度走势）。"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlmodel import Session, col

from app.models import Attempt, AttemptItemType, AttemptStatus, ClassTrendDay


def summarize(
    db: Session,
    student_ids: list[uuid.UUID],
    since: datetime,
    timezone: str,
) -> list[ClassTrendDay]:
    """按练习日聚合班级 DONE 作答：活跃学生数、问答均分、跟读完整度。

    单条窗口聚合查询，不整行拉回（attempts 行含大 JSON 列）；按配置时区
    切练习日，与 board/trail 同口径。均分只算 DONE 作答（模考作答
    评分完成即 DONE，同样计入）。
    """
    if not student_ids:
        return []
    day = func.date(func.timezone(timezone, Attempt.created_at))
    rows = db.connection().execute(
        select(
            day,
            func.count(func.distinct(Attempt.student_id)),
            func.count()
            .filter(col(Attempt.item_type) == AttemptItemType.QUESTION)
            .label("question_attempts"),
            func.avg(Attempt.overall)
            .filter(col(Attempt.item_type) == AttemptItemType.QUESTION)
            .label("question_avg"),
            func.avg(Attempt.completeness)
            .filter(col(Attempt.item_type) == AttemptItemType.REPEAT)
            .label("repeat_avg"),
        )
        .where(
            col(Attempt.student_id).in_(student_ids),
            col(Attempt.status) == AttemptStatus.DONE,
            col(Attempt.created_at) >= since,
        )
        .group_by(day)
        .order_by(day)
    )
    try:
        return [
            ClassTrendDay(
                date=date.isoformat(),
                active_students=active,
                question_attempts=question_attempts,
                question_avg=round(float(question_avg), 1)
                if question_avg is not None
                else None,
                repeat_completeness_avg=round(float(repeat_avg), 1)
                if repeat_avg is not None
                else None,
            )
            for date, active, question_attempts, question_avg, repeat_avg in rows
        ]
    finally:
        rows.close()
