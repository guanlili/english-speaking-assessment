"""班内词汇学习榜域逻辑：设置默认值、参与档案、周界计分与隐私投影。

口径冻结（#517，见 docs/module-notes.md「背单词模块」榜单小节）：

- **计分只读不可变作答记录**：只读 ``VocabularySession`` /
  ``VocabularyAnswer``，不读 XP、农场、PK、等级，不写任何成绩/等级/XP。
- **本周掌握词数**：同一学生同一 ``word_id`` 一周只计 1 次，须同时满足：
  1. 该词在本课堂的**最早一次首答**（``attempt_no=1``）正确；
  2. 本周内至少有一条 ``kind="review_fsrs"`` 轮次的**首答正确**记录
     （已通过一次 FSRS 复习）。普通任务重练、自主练习、农场/PK 不计入。
- **周界**：按 ``PRACTICE_TZ`` 自然周（周一 00:00 到下周一 00:00）；
  历史周由不可变作答记录决定，不随当前 FSRS state 回溯漂移。
- **排名**：分数降序，同分并列（competition ranking：1,1,3）；前
  ``top_n`` 名按 ``rank <= top_n`` 返回，允许第 top_n 名并列导致行数超员；
  零分学生不进 entries。
- **隐私**：未参加学生 200 空榜且看不到人数；匿名时条目只带 alias_no，
  响应不含 student_id / user_id / 邮箱。
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    Student,
    VocabularyAnswer,
    VocabularyLeaderboardEntry,
    VocabularyLeaderboardParticipant,
    VocabularyLeaderboardSetting,
    VocabularyLeaderboardSettings,
    VocabularyLeaderboardSettingsUpdate,
    VocabularyLeaderboardView,
    VocabularyParticipationState,
    VocabularySession,
)
from app.models.base import get_datetime_utc
from app.models.vocabulary.leaderboard import (
    AUDIENCE_TEACHERS,
    LEADERBOARD_TOP_N,
)
from app.services.vocabulary_review import SESSION_KIND_REVIEW_FSRS

# 学生视角不可见的稳定标识（前端按文案分流，不得改措辞）
UNAVAILABLE_DETAIL = "leaderboard_unavailable"


def _practice_tz() -> ZoneInfo:
    return ZoneInfo(settings.PRACTICE_TZ)


def current_week_monday(now: datetime | None = None) -> date:
    """PRACTICE_TZ 当前自然周的周一日期。"""
    now = now or datetime.now(UTC)
    local = now.astimezone(_practice_tz())
    return local.date() - timedelta(days=local.weekday())


def resolve_week_start(raw: date | None, now: datetime | None = None) -> date:
    """解析榜单周：缺省本周一；必须是周一且不得晚于本周一，否则 422。"""
    monday = current_week_monday(now)
    if raw is None:
        return monday
    if raw.weekday() != 0:
        raise HTTPException(status_code=422, detail="week_start 必须是周一")
    if raw > monday:
        raise HTTPException(status_code=422, detail="week_start 不得晚于本周一")
    return raw


def week_bounds(week_start: date) -> tuple[datetime, datetime]:
    """自然周边界（PRACTICE_TZ 周一 00:00 → 下周一 00:00），返回 UTC 时刻。"""
    tz = _practice_tz()
    start_local = datetime.combine(week_start, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=7)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _week_monday_of(moment: datetime | None) -> date | None:
    if moment is None:
        return None
    local = moment.astimezone(_practice_tz())
    return local.date() - timedelta(days=local.weekday())


# ── 设置 ────────────────────────────────────────────────────────────


def get_setting(
    session: Session, classroom_id: uuid.UUID
) -> VocabularyLeaderboardSetting | None:
    return session.exec(
        select(VocabularyLeaderboardSetting).where(
            VocabularyLeaderboardSetting.classroom_id == classroom_id  # type: ignore[arg-type]
        )
    ).first()


def settings_payload(
    row: VocabularyLeaderboardSetting | None,
) -> VocabularyLeaderboardSettings:
    """无库行时由服务层返回默认值（不写种子）。"""
    if row is None:
        return VocabularyLeaderboardSettings(
            enabled=True,
            audience=AUDIENCE_TEACHERS,
            anonymous=True,
            top_n=LEADERBOARD_TOP_N,
        )
    return VocabularyLeaderboardSettings(
        enabled=row.enabled,
        audience=row.audience,
        anonymous=row.anonymous,
        top_n=LEADERBOARD_TOP_N,
    )


def _is_unavailable(setting: VocabularyLeaderboardSettings) -> bool:
    """学生视角不可见：整班关闭，或仍处于仅教师可见范围。"""
    return (not setting.enabled) or setting.audience == AUDIENCE_TEACHERS


def update_setting(
    session: Session,
    classroom_id: uuid.UUID,
    body: VocabularyLeaderboardSettingsUpdate,
    updated_by: uuid.UUID,
) -> VocabularyLeaderboardSetting:
    row = get_setting(session, classroom_id)
    now = get_datetime_utc()
    if row is None:
        row = VocabularyLeaderboardSetting(
            classroom_id=classroom_id,
            enabled=body.enabled,
            audience=body.audience,
            anonymous=body.anonymous,
            updated_by=updated_by,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.enabled = body.enabled
        row.audience = body.audience
        row.anonymous = body.anonymous
        row.updated_by = updated_by
        row.updated_at = now
    session.commit()
    session.refresh(row)
    return row


# ── 参与档案 ─────────────────────────────────────────────────────────


def get_participant(
    session: Session, classroom_id: uuid.UUID, student_id: uuid.UUID
) -> VocabularyLeaderboardParticipant | None:
    return session.exec(
        select(VocabularyLeaderboardParticipant).where(
            VocabularyLeaderboardParticipant.classroom_id == classroom_id,  # type: ignore[arg-type]
            VocabularyLeaderboardParticipant.student_id == student_id,  # type: ignore[arg-type]
        )
    ).first()


def _next_alias(session: Session, classroom_id: uuid.UUID) -> int:
    """班内下一个稳定编号：max(alias_no)+1；并发冲突由唯一索引兜底。"""
    rows = session.exec(
        select(VocabularyLeaderboardParticipant.alias_no).where(
            VocabularyLeaderboardParticipant.classroom_id == classroom_id  # type: ignore[arg-type]
        )
    ).all()
    return (max(rows) if rows else 0) + 1


def set_participation(
    session: Session,
    classroom_id: uuid.UUID,
    student: Student,
    joined: bool,
) -> VocabularyParticipationState:
    """学生加入 / 退出榜单；仅教师可见或整班关闭期间不允许加入。"""
    setting = settings_payload(get_setting(session, classroom_id))
    if joined and _is_unavailable(setting):
        raise HTTPException(status_code=403, detail=UNAVAILABLE_DETAIL)

    row = get_participant(session, classroom_id, student.id)
    now = get_datetime_utc()
    if joined:
        if row is None:
            row = VocabularyLeaderboardParticipant(
                classroom_id=classroom_id,
                student_id=student.id,
                active=True,
                alias_no=_next_alias(session, classroom_id),
                joined_at=now,
                left_at=None,
                updated_at=now,
            )
            session.add(row)
        else:
            row.active = True
            row.left_at = None
            row.updated_at = now
            # 重新加入复用原编号；joined_at 保留首次加入周（历史周口径）
        session.commit()
        session.refresh(row)
        return VocabularyParticipationState(joined=True, alias_no=row.alias_no)

    if row is not None:
        row.active = False
        row.left_at = now
        row.updated_at = now
        session.commit()
        session.refresh(row)
        return VocabularyParticipationState(joined=False, alias_no=None)
    return VocabularyParticipationState(joined=False, alias_no=None)


# ── 计分 ─────────────────────────────────────────────────────────────


def _score_map(
    session: Session,
    classroom_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
    participant_ids: set[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """本周掌握词数：最早首答正确 ∩ 本周 review_fsrs 首答正确，按词去重。"""
    if not participant_ids:
        return {}

    # 条件 1：本课堂最早一次首答（attempt_no=1）必须正确。
    first_rows = session.exec(
        select(
            VocabularySession.student_id,
            VocabularyAnswer.word_id,
            VocabularyAnswer.is_correct,
            VocabularyAnswer.answered_at,
        )
        .join(
            VocabularySession,
            col(VocabularySession.id) == col(VocabularyAnswer.session_id),
        )
        .where(
            VocabularySession.classroom_id == classroom_id,  # type: ignore[arg-type]
            VocabularyAnswer.attempt_no == 1,  # type: ignore[arg-type]
        )
    ).all()
    earliest: dict[tuple[uuid.UUID, uuid.UUID], tuple[datetime, bool]] = {}
    for student_id, word_id, is_correct, answered_at in first_rows:
        if student_id not in participant_ids or answered_at is None:
            continue
        key = (student_id, word_id)
        prev = earliest.get(key)
        if prev is None or answered_at < prev[0]:
            earliest[key] = (answered_at, is_correct)
    first_correct = {key for key, (_ts, ok) in earliest.items() if ok}

    # 条件 2：本周内至少一条 review_fsrs 轮次首答正确记录。
    review_rows = session.exec(
        select(
            VocabularySession.student_id,
            VocabularyAnswer.word_id,
            VocabularyAnswer.is_correct,
        )
        .join(
            VocabularySession,
            col(VocabularySession.id) == col(VocabularyAnswer.session_id),
        )
        .where(
            VocabularySession.classroom_id == classroom_id,  # type: ignore[arg-type]
            VocabularySession.kind == SESSION_KIND_REVIEW_FSRS,  # type: ignore[arg-type]
            VocabularyAnswer.attempt_no == 1,  # type: ignore[arg-type]
            col(VocabularyAnswer.answered_at) >= start_utc,  # type: ignore[union-attr]
            col(VocabularyAnswer.answered_at) < end_utc,  # type: ignore[union-attr]
        )
    ).all()
    reviewed = {
        (student_id, word_id)
        for student_id, word_id, is_correct in review_rows
        if is_correct
    }

    scores: dict[uuid.UUID, set[uuid.UUID]] = {}
    for key in first_correct & reviewed:
        scores.setdefault(key[0], set()).add(key[1])
    return {student_id: len(words) for student_id, words in scores.items()}


def _competition_ranks(
    scores: dict[uuid.UUID, int],
) -> dict[uuid.UUID, int]:
    """并列排名（1,1,3）：同分同名次，下一名次跳过并列占位数。"""
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    ranks: dict[uuid.UUID, int] = {}
    prev_score: int | None = None
    prev_rank = 0
    for index, (_student_id, score) in enumerate(ordered):
        if score != prev_score:
            prev_rank = index + 1
            prev_score = score
        ranks[_student_id] = prev_rank
    return ranks


# ── 榜单组装 ─────────────────────────────────────────────────────────


def build_leaderboard(
    session: Session,
    classroom_id: uuid.UUID,
    viewer: str,
    student: Student | None,
    week_start: date,
) -> VocabularyLeaderboardView:
    """组装榜单视图；viewer ∈ teacher / student。"""
    setting = settings_payload(get_setting(session, classroom_id))
    participants = list(
        session.exec(
            select(VocabularyLeaderboardParticipant).where(
                VocabularyLeaderboardParticipant.classroom_id == classroom_id  # type: ignore[arg-type]
            )
        ).all()
    )
    active_by_student = {p.student_id: p for p in participants if p.active}

    me: VocabularyLeaderboardParticipant | None = None
    if viewer == "student":
        assert student is not None
        if _is_unavailable(setting):
            raise HTTPException(status_code=403, detail=UNAVAILABLE_DETAIL)
        me = active_by_student.get(student.id)
        if me is None:
            # 未参加 / 已退出：200 空榜，看不到其他人与人数
            return VocabularyLeaderboardView(
                week_start=week_start,
                settings=setting,
                entries=[],
                my_entry=None,
                my_rank=None,
                my_score=0,
                participant_count=None,
            )
        # 历史周：不得早于本人首次加入周，避免加入前窥看历史榜
        join_monday = _week_monday_of(me.joined_at)
        if join_monday is not None and week_start < join_monday:
            raise HTTPException(status_code=403, detail=UNAVAILABLE_DETAIL)

    start_utc, end_utc = week_bounds(week_start)
    scores = _score_map(
        session, classroom_id, start_utc, end_utc, set(active_by_student)
    )
    ranks = _competition_ranks(scores)

    student_rows = session.exec(
        select(Student).where(
            col(Student.id).in_(active_by_student.keys())  # type: ignore[operator]
        )
    ).all()
    student_by_id = {s.id: s for s in student_rows}

    def _entry(
        participant: VocabularyLeaderboardParticipant, score: int, rank: int
    ) -> VocabularyLeaderboardEntry:
        stu = student_by_id.get(participant.student_id)
        if setting.anonymous:
            display_name: str | None = None
            suffix: str | None = None
        else:
            display_name = stu.display_name if stu is not None else None
            suffix = stu.suffix if stu is not None else None
        return VocabularyLeaderboardEntry(
            rank=rank,
            score=score,
            alias_no=participant.alias_no,
            display_name=display_name,
            suffix=suffix,
        )

    entries = [
        _entry(active_by_student[student_id], score, ranks[student_id])
        for student_id, score in sorted(
            scores.items(), key=lambda kv: (ranks[kv[0]], kv[0])
        )
        if score > 0 and ranks[student_id] <= LEADERBOARD_TOP_N
    ]

    my_entry = None
    my_rank: int | None = None
    my_score = 0
    if viewer == "student" and me is not None:
        my_score = scores.get(me.student_id, 0)
        if my_score > 0:
            my_rank = ranks.get(me.student_id)
            if my_rank is not None:
                my_entry = _entry(me, my_score, my_rank)

    participant_count = len(active_by_student) if viewer == "teacher" else None
    return VocabularyLeaderboardView(
        week_start=week_start,
        settings=setting,
        entries=entries,
        my_entry=my_entry,
        my_rank=my_rank,
        my_score=my_score,
        participant_count=participant_count,
    )
