"""成长轨迹：数据库窗口聚合指标，分批读取词汇 JSON，保持单条 SQL 快照。"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlmodel import Session, col

from app.models import Attempt, AttemptItemType, AttemptStatus, TrailSession

VOCAB_BATCH_SIZE = 256


@dataclass
class TrailSummary:
    sessions: list[TrailSession]
    total_minutes: int
    vocab_counts: dict[str, int]
    level_counts: dict[str, int]


def summarize(
    db: Session,
    student_id: uuid.UUID,
    since: datetime,
    timezone: str,
    hidden_sessions: set[uuid.UUID],
    *,
    as_of: datetime | None = None,
) -> TrailSummary:
    # 所有出口共用可见性条件，未结束考试不能从词汇累计泄露反馈。
    conditions = [
        col(Attempt.student_id) == student_id,
        col(Attempt.status) == AttemptStatus.DONE,
        col(Attempt.created_at) >= since,
    ]
    if as_of is not None:
        conditions.append(col(Attempt.created_at) <= as_of)
    if hidden_sessions:
        conditions.append(
            or_(
                col(Attempt.session_id).is_(None),
                col(Attempt.session_id).not_in(hidden_sessions),
            )
        )
    day = func.date(func.timezone(timezone, Attempt.created_at))
    # 一条语句内的统计与 JSON 看到相同快照：分两次查询时，后台刚完成的
    # 作答可能只进入词汇累计而没有进入日计数，甚至出现不存在的日期桶。
    # 窗口函数在数据库算数值，客户端仅持有每日结果与一批 JSON，不建 ORM。
    rows = db.connection().execute(
        select(
            day,
            col(Attempt.item_type),
            col(Attempt.vocab),
            func.count().over(partition_by=day),
            func.avg(Attempt.overall)
            .filter(col(Attempt.item_type) == AttemptItemType.QUESTION)
            .over(partition_by=day),
            func.avg(Attempt.completeness)
            .filter(col(Attempt.item_type) == AttemptItemType.REPEAT)
            .over(partition_by=day),
            func.sum(Attempt.duration_s).over(),
        )
        .where(*conditions)
        .order_by(col(Attempt.created_at), col(Attempt.id))
        .execution_options(yield_per=VOCAB_BATCH_SIZE)
    )
    by_day: dict[str, TrailSession] = {}
    vocab_counts: dict[str, int] = {}
    level_counts: dict[str, int] = {}
    total_seconds = 0.0
    try:
        for date, item_type, vocab, count, speaking, completeness, duration in rows:
            key = date.isoformat()
            if key not in by_day:
                by_day[key] = TrailSession(
                    date=key,
                    attempt_count=count,
                    speaking_avg=round(float(speaking), 1)
                    if speaking is not None
                    else None,
                    repeat_completeness_avg=round(float(completeness), 1)
                    if completeness is not None
                    else None,
                    vocab_cefr=None,
                )
            total_seconds = float(duration or 0)
            # 保留历史词汇 JSON 中无效值的容错语义。
            if not isinstance(vocab, dict):
                continue
            cefr = vocab.get("cefr")
            if item_type == AttemptItemType.QUESTION and isinstance(cefr, str):
                by_day[key].vocab_cefr = cefr
            hits = vocab.get("hits")
            if isinstance(hits, dict):
                for band, words in hits.items():
                    if isinstance(band, str) and isinstance(words, list):
                        vocab_counts[band] = vocab_counts.get(band, 0) + len(words)
            stats = vocab.get("level_stats")
            hits_by_level = (
                stats.get("hits_by_level") if isinstance(stats, dict) else None
            )
            if isinstance(hits_by_level, dict):
                for level, count in hits_by_level.items():
                    if isinstance(level, str) and isinstance(count, int):
                        level_counts[level] = level_counts.get(level, 0) + count
    finally:
        rows.close()
    return TrailSummary(
        sessions=[by_day[key] for key in sorted(by_day)],
        total_minutes=round(total_seconds / 60),
        vocab_counts=vocab_counts,
        level_counts=level_counts,
    )
