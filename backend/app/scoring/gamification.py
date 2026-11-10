"""激励层（多邻国式）：星级、XP、连胜、徽章。

设计口径（与产品决策一致）：
- 只和自己比：无班级排名、无生命值、无任何负面扣减；完成即有 1 星保底
- 星级与练习档解耦：降档不展示、不影响星数（PRD §6）
- 结算幂等：session.stars 已写入即跳过（挂在 /today 聚合里，同 band_change 模式）
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.exc import OperationalError
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


def _lock_for_settlement(
    session: Session, practice_session: PracticeSession, student: Student
) -> tuple[PracticeSession, Student] | None:
    """锁本轮与学生两行；对象不存在、本轮已结算或暂时拿不到锁时返回 None。

    用 NOWAIT 而不是无限等待：/today 是秒级轮询，拿不到锁就跳过本轮，
    下一次轮询再来（结算幂等，stars 只写一次）。死锁的本质是「互相等」，
    取消这一侧的等待就从根上消除了环——worker 侧同样不等待
    （FOR UPDATE SKIP LOCKED），两侧都不阻塞，就不可能成环。
    """
    try:
        locked_session = session.exec(
            select(PracticeSession)
            .where(PracticeSession.id == practice_session.id)
            .with_for_update(nowait=True)
        ).first()
    except OperationalError:
        # 行锁被占（评分写回/别的结算）：放弃本轮，下轮再算
        session.rollback()
        return None
    if locked_session is None:
        return None
    if locked_session.stars is not None:
        return None
    try:
        locked_student = session.exec(
            select(Student).where(Student.id == student.id).with_for_update(nowait=True)
        ).first()
    except OperationalError:
        session.rollback()
        return None
    if locked_student is None:
        return None
    return locked_session, locked_student


def _latest_attempts(
    session: Session, session_id, required_item_ids: set | None
) -> dict:
    """每个题位的最新作答（按创建时间正序覆盖，最后一条即最新）。"""
    attempts = session.exec(
        select(Attempt)
        .where(Attempt.session_id == session_id)
        .order_by(col(Attempt.created_at))
    ).all()
    latest: dict = {}
    for attempt in attempts:
        if required_item_ids is not None and attempt.item_id not in required_item_ids:
            continue
        latest[attempt.item_id] = attempt
    return latest


def _all_items_settled(latest: dict, expected_items: int) -> bool:
    """题数够，且每个必须题位的最新作答都为终态（done/failed）。"""
    if len(latest) < expected_items:
        return False
    return all(
        a.status in (AttemptStatus.DONE, AttemptStatus.FAILED) for a in latest.values()
    )


def _apply_streak(student: Student, today: date) -> None:
    """当日首次结算才推进连胜。"""
    if student.last_practice_date != today:
        student.streak_days = advance_streak(
            student.last_practice_date, student.streak_days, today
        )
        student.last_practice_date = today


def _xp_gain(done_count: int, stars: int, streak_days: int) -> int:
    """XP = 每题 10 + 每星 5 + 连胜 ≥3 天奖励 10。"""
    return (
        done_count * XP_PER_DONE
        + stars * XP_PER_STAR
        + (XP_STREAK_BONUS if streak_days >= STREAK_BONUS_MIN_DAYS else 0)
    )


def _settled_rounds(session: Session, student_id, current: PracticeSession) -> list:
    """已结算轮次：库里已写 stars 的轮次，再补上本轮。

    本轮刚赋 stars 但还没 commit，直接查库查不到，所以手工追加。
    """
    return list(
        session.exec(
            select(PracticeSession).where(
                PracticeSession.student_id == student_id,
                col(PracticeSession.stars).is_not(None),
            )
        ).all()
    ) + [current]


def _owned_badge_keys(session: Session, student_id) -> set:
    """该学生已拥有的徽章 key。"""
    return set(
        session.exec(
            select(StudentBadge.badge_key).where(StudentBadge.student_id == student_id)
        ).all()
    )


def _badge_candidates(student: Student, rounds_count: int) -> dict[str, bool]:
    """五个徽章的命中判定。"""
    return {
        "first_round": rounds_count >= 1,
        "streak_3": student.streak_days >= 3,
        "streak_7": student.streak_days >= 7,
        "ten_rounds": rounds_count >= 10,
        "reached_b2": student.current_band == "B2",
    }


def _award_badges(
    session: Session, student_id, candidates: dict[str, bool], owned: set
) -> None:
    """命中且未拥有的徽章落库。"""
    for key, hit in candidates.items():
        if hit and key not in owned:
            session.add(StudentBadge(student_id=student_id, badge_key=key))


def settle_session(
    session: Session,
    practice_session: PracticeSession,
    student: Student,
    today: date,
    expected_items: int,
    required_item_ids: set | None = None,
) -> None:
    """一轮全部完成后结算星/XP/连胜/徽章。幂等：stars 已写入直接返回。

    判定「全部完成」：
    - expected_items：本轮应做题数（来自 PlanItem 列表，快照/题单口径）
    - required_item_ids：若提供，只检查这些 item_id 的作答；额外换题的作答不顶替必做题
    - 每个必须题位的最新作答均为终态（done/failed）
    """
    locked = _lock_for_settlement(session, practice_session, student)
    if locked is None:
        # 已拿到的行锁必须在这里结束掉：/today 是高频轮询，早退若不收尾，
        # practice_session / student 的 FOR UPDATE 会一直挂到请求结束，
        # 与 worker 的 UPDATE attempt 交叉时形成环形等待。
        session.commit()
        return
    practice_session, student = locked

    latest = _latest_attempts(session, practice_session.id, required_item_ids)
    if not _all_items_settled(latest, expected_items):
        # 同上：本轮还没做完是常态，不能带着行锁走完整个 /today 请求。
        session.commit()
        return  # 题数不足或还有题没评完

    done = [a for a in latest.values() if a.status == AttemptStatus.DONE]
    overalls = [a.overall for a in done if a.overall is not None]
    stars = compute_stars(overalls)

    _apply_streak(student, today)
    student.xp = (student.xp or 0) + _xp_gain(len(done), stars, student.streak_days)
    practice_session.stars = stars

    rounds_count = len(_settled_rounds(session, student.id, practice_session))
    _award_badges(
        session,
        student.id,
        _badge_candidates(student, rounds_count),
        _owned_badge_keys(session, student.id),
    )

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
