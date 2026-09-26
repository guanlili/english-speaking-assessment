"""激励层（多邻国式）：星级、XP、连胜、徽章。

设计口径（与产品决策一致）：
- 只和自己比：无班级排名、无生命值、无任何负面扣减；完成即有 1 星保底
- 星级与练习档解耦：降档不展示、不影响星数（PRD §6）
- 结算幂等：session.stars 已写入即跳过（挂在 /today 聚合里，同 band_change 模式）
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, col, select

from app.models import (
    Attempt,
    AttemptStatus,
    PracticeSession,
    Student,
    StudentBadge,
)

# 星级分档：平均总评 ≥85 → 3 星；≥70 → 2 星；完成即 1 星
STARS_3_THRESHOLD = 85
STARS_2_THRESHOLD = 70

# XP：每题 10 + 每星 5 + 连胜 ≥3 天奖励 10
XP_PER_DONE = 10
XP_PER_STAR = 5
XP_STREAK_BONUS = 10
STREAK_BONUS_MIN_DAYS = 3


@dataclass(frozen=True)
class BadgeDef:
    key: str
    label: str
    description: str


BADGES: list[BadgeDef] = [
    BadgeDef("first_round", "初次开口", "完成第一轮练习"),
    BadgeDef("streak_3", "三连胜", "连续 3 天完成练习"),
    BadgeDef("streak_7", "一周坚持", "连续 7 天完成练习"),
    BadgeDef("ten_rounds", "十轮达人", "累计完成 10 轮练习"),
    BadgeDef("reached_b2", "登上高档", "练习档位升到 B2"),
]
BADGE_BY_KEY = {b.key: b for b in BADGES}


def compute_stars(overalls: list[int]) -> int:
    """平均总评分档；无有效分但有完成（如全部 failed）时保底 1 星。"""
    if not overalls:
        return 1
    avg = sum(overalls) / len(overalls)
    if avg >= STARS_3_THRESHOLD:
        return 3
    if avg >= STARS_2_THRESHOLD:
        return 2
    return 1


def advance_streak(last: date | None, streak: int, today: date) -> int:
    """当日首次结算时的连胜推进：昨天练过 +1，断档/首次 → 1。"""
    if last == today:
        return streak
    if last == today - timedelta(days=1):
        return streak + 1
    return 1


def _round_done_attempts(
    session: Session, practice_session: PracticeSession
) -> list[Attempt]:
    attempts = session.exec(
        select(Attempt).where(Attempt.session_id == practice_session.id)
    ).all()
    latest: dict = {}
    for attempt in attempts:
        latest[attempt.item_id] = attempt
    return [a for a in latest.values() if a.status == AttemptStatus.DONE]


def settle_session(
    session: Session,
    practice_session: PracticeSession,
    student: Student,
    today: date,
    expected_items: int,
) -> None:
    """一轮全部完成后结算星/XP/连胜/徽章。幂等：stars 已写入直接返回。

    判定「全部完成」：有作答的题目数达到本轮应做题数（expected_items，
    换题追加的作答数多于应做数也视为完成），且每题最新作答均为终态。
    """
    if practice_session.stars is not None:
        return

    attempts = session.exec(
        select(Attempt).where(Attempt.session_id == practice_session.id)
    ).all()
    latest: dict = {}
    for attempt in attempts:
        latest[attempt.item_id] = attempt
    if len(latest) < expected_items or any(
        a.status not in (AttemptStatus.DONE, AttemptStatus.FAILED)
        for a in latest.values()
    ):
        return  # 题数不足或还有题没评完

    done = [a for a in latest.values() if a.status == AttemptStatus.DONE]
    overalls = [a.overall for a in done if a.overall is not None]
    stars = compute_stars(overalls)

    # 连胜：当日首次结算才推进
    if student.last_practice_date != today:
        student.streak_days = advance_streak(
            student.last_practice_date, student.streak_days, today
        )
        student.last_practice_date = today

    xp_gain = (
        len(done) * XP_PER_DONE
        + stars * XP_PER_STAR
        + (XP_STREAK_BONUS if student.streak_days >= STREAK_BONUS_MIN_DAYS else 0)
    )
    student.xp = (student.xp or 0) + xp_gain
    practice_session.stars = stars

    # 徽章判定
    settled_rounds = list(
        session.exec(
            select(PracticeSession).where(
                PracticeSession.student_id == student.id,
                col(PracticeSession.stars).is_not(None),
            )
        ).all()
    ) + [practice_session]  # 本轮计入
    owned = set(
        session.exec(
            select(StudentBadge.badge_key).where(StudentBadge.student_id == student.id)
        ).all()
    )
    rounds_count = len(settled_rounds)
    new_keys: list[str] = []
    candidates = {
        "first_round": rounds_count >= 1,
        "streak_3": student.streak_days >= 3,
        "streak_7": student.streak_days >= 7,
        "ten_rounds": rounds_count >= 10,
        "reached_b2": student.current_band == "B2",
    }
    for key, hit in candidates.items():
        if hit and key not in owned:
            new_keys.append(key)
            session.add(StudentBadge(student_id=student.id, badge_key=key))

    session.add(student)
    session.add(practice_session)
    session.commit()


def student_badges(session: Session, student_id) -> list[StudentBadge]:
    return list(
        session.exec(
            select(StudentBadge)
            .where(StudentBadge.student_id == student_id)
            .order_by(col(StudentBadge.awarded_at))
        ).all()
    )
