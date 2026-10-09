"""词汇限时测验域逻辑：准入、个人计时、到时结算、一次作答、判分、补考、公布。

时间口径全部以服务器为准（学生端倒计时只是展示，改客户端时间无效）：
- 计时起点 = 学生在规则页明确点「开始测验」的时刻（落 quiz_started_at，
  只落一次；刷新/多端进入续做同一份答卷，不重置计时）；
- 个人截止 = min(开始时刻 + 时长, 任务截止时间)；
- 到时采用惰性结算——任何触碰（学生作答/查看、教师看结果）发现超时即
  落 status=submitted + end_reason=timeout（submitted_at=截止时刻），
  此后拒绝继续作答。结算不依赖学生页面在线：教师侧触碰同样完成结算。

判分口径：未答题按零分计入必答题分母（score = 首答正确 / 总题数），
但与答错分列（correct / wrong / unanswered 三个计数）。默认一次参与，
教师可单独授权一次补考；补考产生新答卷、保留原答卷，有效成绩默认取
最好成绩并明确标注。
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.models import (
    VocabularyAnswer,
    VocabularyAssignment,
    VocabularyAssignmentTarget,
    VocabularySession,
)

QUIZ_MIN_MINUTES = 5
QUIZ_MAX_MINUTES = 240
DEFAULT_PASS_LINE = 60
# 一个学生一份任务答卷最多轮数 = 首考 1 + 补考 1
QUIZ_MAX_ATTEMPTS = 2


def _now() -> datetime:
    return datetime.now(UTC)


def validate_quiz_publish(
    *,
    duration_minutes: int | None,
    pass_line: int,
    opens_at: datetime | None,
    due_at: datetime | None,
    prompt_types: list[str],
    words_have_audio: bool,
) -> None:
    """发布测验前的参数校验（路由层调用，422 拒绝）。

    - 时长必填且 5–240 分钟；及格线 0–100（schema 已限）；
    - 开放时间必须早于截止时间；截止时间必须晚于现在；
    - 听音题型要求全部词条有稳定标准音——浏览器合成语音不得作为测验题源。
    """
    if duration_minutes is None or not (
        QUIZ_MIN_MINUTES <= duration_minutes <= QUIZ_MAX_MINUTES
    ):
        raise HTTPException(
            status_code=422,
            detail=f"测验需要 {QUIZ_MIN_MINUTES}–{QUIZ_MAX_MINUTES} 分钟的考试时长",
        )
    if opens_at is not None and due_at is not None and opens_at >= due_at:
        raise HTTPException(status_code=422, detail="开放时间必须早于截止时间")
    if not 0 <= pass_line <= 100:
        raise HTTPException(status_code=422, detail="及格线必须是 0–100 的整数")
    if "audio" in prompt_types and not words_have_audio:
        raise HTTPException(
            status_code=422,
            detail="听音测验要求每个词都有稳定标准音（浏览器合成语音不能作为测验题源）；"
            "请先上传音频，或只使用看义拼词",
        )


def quiz_deadline(
    vocab_session: VocabularySession, assignment: VocabularyAssignment
) -> datetime | None:
    """个人截止：min(明确开始 + 时长, 任务截止)。未开始返回 None。"""
    if vocab_session.quiz_started_at is None:
        return None
    deadline: datetime | None = None
    if assignment.duration_minutes is not None:
        deadline = vocab_session.quiz_started_at + timedelta(
            minutes=assignment.duration_minutes
        )
    if assignment.due_at is not None:
        deadline = min(deadline, assignment.due_at) if deadline else assignment.due_at
    return deadline


def attempts_used(
    session: Session, assignment_id: uuid.UUID, student_id: uuid.UUID
) -> int:
    """已产生的答卷数（一次明确开始 = 一份答卷）。"""
    return len(
        session.exec(
            select(VocabularySession.id).where(
                VocabularySession.assignment_id == assignment_id,  # type: ignore[arg-type]
                VocabularySession.student_id == student_id,  # type: ignore[arg-type]
                col(VocabularySession.quiz_started_at).is_not(None),  # type: ignore[union-attr]
            )
        ).all()
    )


def retake_granted(
    session: Session, assignment_id: uuid.UUID, student_id: uuid.UUID
) -> bool:
    target = session.exec(
        select(VocabularyAssignmentTarget).where(
            VocabularyAssignmentTarget.assignment_id == assignment_id,  # type: ignore[arg-type]
            VocabularyAssignmentTarget.student_id == student_id,  # type: ignore[arg-type]
        )
    ).first()
    return target is not None and target.retake_granted_at is not None


def attempts_allowed(
    session: Session, assignment_id: uuid.UUID, student_id: uuid.UUID
) -> int:
    return 2 if retake_granted(session, assignment_id, student_id) else 1


def settle_due_sessions(session: Session, assignment: VocabularyAssignment) -> int:
    """到时惰性结算：终结全部超过个人截止的进行中答卷，返回终结数。

    submitted_at 取个人截止时刻（而非结算触碰时刻）——成绩按截止时的
    作答计算，与「学生页面是否在线」无关；教师侧触碰同样完成结算。

    并发约定：与学生提交/手动交卷共享 VocabularySession 行锁。逐行加锁后
    重校验状态与时间（锁外快照可能已被其他触碰终结），按 id 稳定顺序加锁，
    不会与学生只锁自己一行的路径形成锁环。
    """
    rounds = session.exec(
        select(VocabularySession)
        .where(
            VocabularySession.assignment_id == assignment.id,  # type: ignore[arg-type]
            VocabularySession.status == "in_progress",  # type: ignore[arg-type]
            col(VocabularySession.quiz_started_at).is_not(None),  # type: ignore[union-attr]
        )
        .order_by(col(VocabularySession.id))
    ).all()
    settled = 0
    for vocab_session in rounds:
        deadline = quiz_deadline(vocab_session, assignment)
        if deadline is None or _now() <= deadline:
            continue
        # 行锁 + 重读：锁外快照可能已被其他触碰（交卷/作答锁内终结）改写
        session.refresh(vocab_session, with_for_update=True)
        if vocab_session.status != "in_progress":
            continue
        locked_deadline = quiz_deadline(vocab_session, assignment)
        if locked_deadline is None or _now() <= locked_deadline:
            continue
        vocab_session.status = "submitted"
        vocab_session.end_reason = "timeout"
        vocab_session.submitted_at = locked_deadline
        session.add(vocab_session)
        settled += 1
    if settled:
        session.commit()
    return settled


def ensure_quiz_answerable(
    session: Session, vocab_session: VocabularySession, assignment: VocabularyAssignment
) -> None:
    """作答前门禁：结算到时答卷；已终结（交卷/超时）一律拒绝继续作答。"""
    settle_due_sessions(session, assignment)
    session.refresh(vocab_session)
    if vocab_session.status != "in_progress":
        if vocab_session.end_reason == "timeout":
            raise HTTPException(status_code=422, detail="测验时间已到，已自动交卷")
        raise HTTPException(status_code=422, detail="测验已交卷，不能再作答")


def start_quiz_session(
    session: Session,
    *,
    classroom_id: uuid.UUID,
    student_id: uuid.UUID,
    assignment: VocabularyAssignment,
) -> VocabularySession:
    """明确开始测验（规则页点击开始）：落个人计时起点，返回答卷。

    - 未到开放时间 / 已过截止：422（准入以服务器时间为准）；
    - 已有进行中答卷：直接续做（刷新/多端进入不重置计时、不产生新答卷）；
    - 参与次数：默认 1 次；教师授权补考后共 2 次，用完即 422；
    - 并发开始由 (assignment_id, student_id, round_no) 唯一索引兜底，
      撞索引时回滚重查返回赢家答卷。
    """
    _now_ts = _now()
    if assignment.status != "published":
        raise HTTPException(status_code=422, detail="该测验已结束，不能开始")
    if assignment.opens_at is not None and _now_ts < assignment.opens_at:
        raise HTTPException(status_code=422, detail="测验尚未开放，不能开始")
    if assignment.due_at is not None and _now_ts >= assignment.due_at:
        raise HTTPException(status_code=422, detail="测验已过截止时间，不能开始")

    existing = session.exec(
        select(VocabularySession)
        .where(
            VocabularySession.assignment_id == assignment.id,  # type: ignore[arg-type]
            VocabularySession.student_id == student_id,  # type: ignore[arg-type]
        )
        .order_by(col(VocabularySession.round_no).desc())
    ).all()
    unfinished = next((r for r in existing if r.status == "in_progress"), None)
    if unfinished is not None:
        return unfinished  # 续做：不重置 quiz_started_at
    used = attempts_used(session, assignment.id, student_id)
    allowed = attempts_allowed(session, assignment.id, student_id)
    if used >= allowed:
        raise HTTPException(
            status_code=422,
            detail="你已经参加过这次测验"
            + ("，补考次数也已用完" if allowed > 1 else "；如需补考请联系老师授权"),
        )

    vocab_session = VocabularySession(
        classroom_id=classroom_id,
        student_id=student_id,
        assignment_id=assignment.id,
        kind="task",
        mode="quiz",
        round_no=used + 1,
        quiz_started_at=_now_ts,
    )
    session.add(vocab_session)
    try:
        session.commit()
    except Exception:
        # 并发开始撞唯一索引：回滚后重查，返回赢家答卷（不重置其计时）
        session.rollback()
        again = session.exec(
            select(VocabularySession)
            .where(
                VocabularySession.assignment_id == assignment.id,  # type: ignore[arg-type]
                VocabularySession.student_id == student_id,  # type: ignore[arg-type]
            )
            .order_by(col(VocabularySession.round_no).desc())
        ).all()
        winner = next((r for r in again if r.status == "in_progress"), None)
        if winner is not None:
            return winner
        raise
    session.refresh(vocab_session)
    return vocab_session


def submit_quiz_session(
    session: Session, vocab_session: VocabularySession, assignment: VocabularyAssignment
) -> VocabularySession:
    """主动交卷：终结答卷（幂等；已终结返回原状态，不重复改写）。

    会话行锁内重校验状态——交卷与作答提交、到时结算共享同一把锁，
    交卷生效后（锁释放前落库 submitted）并发作答在锁内看到终态被拒。
    """
    settle_due_sessions(session, assignment)
    # 行锁 + 重读：交卷与作答提交、到时结算共享同一把锁，锁内终态判定
    session.refresh(vocab_session, with_for_update=True)
    if vocab_session.status != "in_progress":
        return vocab_session
    vocab_session.status = "submitted"
    vocab_session.end_reason = "manual"
    vocab_session.submitted_at = _now()
    session.add(vocab_session)
    session.commit()
    session.refresh(vocab_session)
    return vocab_session


def record_tab_switch(
    session: Session, vocab_session: VocabularySession, assignment: VocabularyAssignment
) -> int:
    """切屏上报：仅计数供教师参考，不做任何作弊认定（封顶防刷）。"""
    ensure_quiz_answerable(session, vocab_session, assignment)
    vocab_session.tab_switch_count = min(999, vocab_session.tab_switch_count + 1)
    session.add(vocab_session)
    session.commit()
    return vocab_session.tab_switch_count


def quiz_round_stats_from_firsts(
    firsts: dict[int, VocabularyAnswer], total: int
) -> dict[str, object]:
    """单份答卷成绩（纯聚合）：首答正确 / 答错 / 未答分列，未答按零分计入分母。

    输入是已批量读取的首答映射（item_index → answer），不再查库——
    class_results 等聚合入口复用同一份预取数据，查询数不随学生数增长。
    """
    answered = len(firsts)
    correct = sum(1 for a in firsts.values() if a.is_correct)
    wrong = answered - correct
    unanswered = max(0, total - answered)
    # 未答按零分计入必答题分母；半分四舍五入（整数百分制）
    score = int(correct * 100 / total + 0.5) if total > 0 else 0
    return {
        "answered": answered,
        "correct": correct,
        "wrong": wrong,
        "unanswered": unanswered,
        "score": score,
    }


def quiz_attempt_stats(
    session: Session, vocab_session: VocabularySession, total: int
) -> dict[str, object]:
    """单份答卷成绩（查库版）：等价于 quiz_round_stats_from_firsts。"""
    firsts = session.exec(
        select(VocabularyAnswer).where(
            VocabularyAnswer.session_id == vocab_session.id,  # type: ignore[arg-type]
            VocabularyAnswer.attempt_no == 1,
        )
    ).all()
    return quiz_round_stats_from_firsts({a.item_index: a for a in firsts}, total)


def effective_quiz_grade_from_rounds(
    rounds: list[VocabularySession],
    firsts_by_session: dict[uuid.UUID, dict[int, VocabularyAnswer]],
    total: int,
    pass_line: int,
) -> tuple[int | None, bool | None, list[dict[str, object]], VocabularySession | None]:
    """有效成绩（纯聚合）：最好整份已终结答卷，同分取较早轮（round_no 升序传入）。

    口径统一（批次05）：成绩、答对/答错/未答必须来自同一份答卷——跨轮
    逐题择优会出现「成绩 50 但 2/2 对」的自相矛盾。进行中答卷只作进度，
    不参与有效成绩，不能篡改已终结成绩。返回
    (最好成绩, 是否及格, 各份答卷明细, 有效答卷)；无终结答卷为
    (None, None, [], None)。
    """
    attempts = [
        quiz_round_stats_from_firsts(firsts_by_session.get(r.id, {}) or {}, total)
        for r in rounds
    ]
    best_index: int | None = None
    best_score: int | None = None
    for index, attempt in enumerate(attempts):
        score = attempt["score"]
        if isinstance(score, int) and (best_score is None or score > best_score):
            best_score = score
            best_index = index
    passed: bool | None = best_score >= pass_line if best_score is not None else None
    effective = rounds[best_index] if best_index is not None else None
    return best_score, passed, attempts, effective


def effective_quiz_grade(
    session: Session, assignment: VocabularyAssignment, student_id: uuid.UUID
) -> tuple[int | None, bool | None, list[dict[str, object]]]:
    """有效成绩（查库版，学生端单学生视图用）：委托纯聚合。

    与 effective_quiz_grade_from_rounds 同口径：仅已终结答卷参与有效成绩。
    返回 (最好成绩, 是否及格, 各次答卷明细)；从未开考为 (None, None, [])。
    """
    total = len(assignment.snapshot_items)
    rounds = list(
        session.exec(
            select(VocabularySession)
            .where(
                VocabularySession.assignment_id == assignment.id,  # type: ignore[arg-type]
                VocabularySession.student_id == student_id,  # type: ignore[arg-type]
                col(VocabularySession.quiz_started_at).is_not(None),  # type: ignore[union-attr]
                VocabularySession.status == "submitted",  # type: ignore[arg-type]
            )
            .order_by(col(VocabularySession.round_no))
        ).all()
    )
    firsts_by_session: dict[uuid.UUID, dict[int, VocabularyAnswer]] = {}
    if rounds:
        from app.services.vocabulary import first_answers_by_session

        firsts_by_session = first_answers_by_session(session, [r.id for r in rounds])
    best_score, passed, attempts, _effective = effective_quiz_grade_from_rounds(
        rounds, firsts_by_session, total, assignment.pass_line
    )
    return best_score, passed, attempts
