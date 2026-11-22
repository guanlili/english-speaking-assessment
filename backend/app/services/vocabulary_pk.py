"""课堂实时 PK 域逻辑：大厅、配对、题单固化、判分、结算与断线恢复。

边界（设计稿 `docs/vocabulary-pk-farm-design-20261122.md` §2/§3）：

- 班内自愿：仅本课堂成员与本班教师可读；学生显式加入，未参与不影响任务。
- 口径分离：作答只落 ``vocab_pk_answer``，不写 ``VocabularyAnswer``、不改
  任务首答统计、不动发布快照；教师结果页不混入 PK。
- 题单固化：开大厅时把词条内容与题型载荷深拷贝进 ``snapshot_items``，
  对局双方题面/选项/挖空/语素块完全一致；之后改词库不影响进行中对局。
- 服务端时钟：当前题截止点 ``current_deadline_at`` 由服务端计算，前端
  倒计时只做展示；超时由服务端惰性结算，未答题记 0。
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.crud import classroom_teacher_allowed
from app.models import (
    MAX_ACTIVE_MATCHES,
    MAX_QUESTION_COUNT,
    MAX_QUEUE_PLAYERS,
    PK_ANSWER_BASE,
    PK_SPEED_BONUS_MAX,
    Classroom,
    PkAnswerResult,
    PkChoice,
    PkLobbyView,
    PkMatchItem,
    PkMatchResult,
    PkMatchView,
    PkMorphSegment,
    PkPlayerSummary,
    Student,
    User,
    VocabPkAnswer,
    VocabPkLobby,
    VocabPkMatch,
    VocabPkPlayer,
)
from app.services import vocabulary as vocab_service
from app.services import vocabulary_prompt_types as prompt_types_mod

# 大厅可演示默认值（设计稿 §5.3：首版口径，后续可在 #517 调整）
DEFAULT_PK_PROMPT_TYPES = ["meaning", "en_zh", "zh_en"]

ACTIVE_PLAYER_STATUSES = ("waiting", "active")


def _now() -> datetime:
    return datetime.now(UTC)


# ── 权限解析 ───────────────────────────────────────────────────────


def resolve_viewer(
    session: Session, classroom: Classroom, user: User
) -> tuple[str, Student | None]:
    """解析访问者在本课堂的身份：teacher / student；都不是 → 404。

    跨班访问不泄露存在性：学生不在本班、也不是本班教师一律 404。
    """
    if classroom_teacher_allowed(classroom, user, session):
        return "teacher", None
    student = session.exec(
        select(Student).where(
            Student.classroom_id == classroom.id,  # type: ignore[arg-type]
            Student.user_id == user.id,  # type: ignore[arg-type]
        )
    ).first()
    if student is not None:
        return "student", student
    raise HTTPException(status_code=404, detail="课堂不存在或您不在本课堂")


def _require_teacher(classroom: Classroom, user: User, session: Session) -> None:
    if not classroom_teacher_allowed(classroom, user, session):
        raise HTTPException(
            status_code=403, detail="没有权限：仅本班教师可以操作 PK 大厅"
        )


# ── 题单固化 ────────────────────────────────────────────────────────


def _build_snapshot_items(
    session: Session,
    viewer: User,
    book_id: uuid.UUID,
    prompt_types: list[str],
    question_count: int,
) -> list[dict[str, object]]:
    """按词库构建固化题单（复用四题型与快照构建，与任务发布同口径）。"""
    words = vocab_service.resolve_publish_words(session, book_id, None, viewer)
    prompt_types = vocab_service.validate_prompt_types(prompt_types)
    prompt_types_mod.validate_content_availability(words, prompt_types)
    per_item = prompt_types_mod.plan_item_prompt_types(words, prompt_types)
    snapshots = [
        vocab_service.build_word_snapshot(word, types)
        for word, types in zip(words, per_item, strict=True)
    ]
    prompt_types_mod.attach_prompt_payloads(snapshots, words)
    if len(snapshots) < question_count:
        raise HTTPException(
            status_code=422,
            detail=f"可用题目只有 {len(snapshots)} 个，少于要求的 {question_count} 题",
        )
    return snapshots[:question_count]


# ── 大厅 ────────────────────────────────────────────────────────────


def get_lobby(
    session: Session, classroom_id: uuid.UUID, *, open_only: bool = False
) -> VocabPkLobby | None:
    """取课堂大厅：开放大厅优先；否则取最近一次大厅。"""
    if open_only:
        return session.exec(
            select(VocabPkLobby).where(
                VocabPkLobby.classroom_id == classroom_id,  # type: ignore[arg-type]
                VocabPkLobby.status == "open",
            )
        ).first()
    return session.exec(
        select(VocabPkLobby)
        .where(VocabPkLobby.classroom_id == classroom_id)  # type: ignore[arg-type]
        .order_by(col(VocabPkLobby.created_at).desc())
    ).first()


def open_lobby(
    session: Session,
    classroom: Classroom,
    teacher: User,
    *,
    book_id: uuid.UUID,
    question_count: int | None,
    per_question_seconds: int | None,
    prompt_types: list[str] | None,
) -> VocabPkLobby:
    """教师开大厅：固化题单；同一课堂旧开放大厅自动收口。"""
    _require_teacher(classroom, teacher, session)
    q_count = question_count or 8
    q_count = max(1, min(q_count, MAX_QUESTION_COUNT))
    pq_seconds = per_question_seconds or 20
    types = prompt_types or DEFAULT_PK_PROMPT_TYPES

    snapshot_items = _build_snapshot_items(session, teacher, book_id, types, q_count)

    # 锁课堂行：并发开大厅不会留下两个开放大厅（部分唯一索引兜底）
    session.exec(
        select(Classroom).where(Classroom.id == classroom.id).with_for_update()
    ).first()

    existing = get_lobby(session, classroom.id, open_only=True)
    if existing is not None:
        existing.status = "closed"
        existing.closed_at = _now()
        session.add(existing)

    lobby = VocabPkLobby(
        classroom_id=classroom.id,
        created_by=teacher.id,
        book_id=book_id,
        prompt_types=types,
        question_count=len(snapshot_items),
        per_question_seconds=pq_seconds,
        status="open",
        snapshot_items=snapshot_items,
    )
    session.add(lobby)
    session.commit()
    session.refresh(lobby)
    return lobby


def close_lobby(session: Session, classroom: Classroom, teacher: User) -> VocabPkLobby:
    _require_teacher(classroom, teacher, session)
    lobby = get_lobby(session, classroom.id, open_only=True)
    if lobby is None:
        raise HTTPException(status_code=404, detail="当前没有开放的 PK 大厅")
    lobby.status = "closed"
    lobby.closed_at = _now()
    session.add(lobby)
    session.commit()
    session.refresh(lobby)
    return lobby


def _players_of_lobby(session: Session, lobby_id: uuid.UUID) -> list[VocabPkPlayer]:
    return list(
        session.exec(
            select(VocabPkPlayer).where(VocabPkPlayer.lobby_id == lobby_id)  # type: ignore[arg-type]
        ).all()
    )


def _player_summary(player: VocabPkPlayer, display_name: str | None) -> PkPlayerSummary:
    return PkPlayerSummary(
        student_id=player.student_id,
        display_name=display_name,
        side=player.side,
        status=player.status,
        score=player.score,
        answered_count=player.answered_count,
        correct_count=player.correct_count,
        total_seconds=player.total_seconds,
        match_id=player.match_id,
    )


def lobby_view(
    session: Session,
    classroom: Classroom,
    student: Student | None,
) -> PkLobbyView:
    lobby = get_lobby(session, classroom.id)
    if lobby is None:
        return PkLobbyView(queue_count=0, active_match_count=0)

    players = _players_of_lobby(session, lobby.id)
    active = [p for p in players if p.status in ACTIVE_PLAYER_STATUSES]
    active_matches = session.exec(
        select(VocabPkMatch).where(
            VocabPkMatch.lobby_id == lobby.id,  # type: ignore[arg-type]
            VocabPkMatch.status == "active",
        )
    ).all()

    my_status: str | None = None
    my_match_id: uuid.UUID | None = None
    summaries: list[PkPlayerSummary] = []
    for player in players:
        display_name = _student_display_name(session, player.student_id)
        summaries.append(_player_summary(player, display_name))
        if student is not None and player.student_id == student.id:
            my_status = player.status
            my_match_id = player.match_id

    return PkLobbyView(
        lobby_id=lobby.id,
        status=lobby.status,
        book_id=lobby.book_id,
        question_count=lobby.question_count,
        per_question_seconds=lobby.per_question_seconds,
        prompt_types=list(lobby.prompt_types or []),
        queue_count=len(active),
        active_match_count=len(active_matches),
        my_status=my_status,
        my_match_id=my_match_id,
        players=summaries,
        created_at=lobby.created_at,
        closed_at=lobby.closed_at,
    )


def _student_display_name(session: Session, student_id: uuid.UUID) -> str | None:
    student = session.get(Student, student_id)
    return student.display_name if student is not None else None


# ── 排队与配对 ──────────────────────────────────────────────────────


def join_lobby(
    session: Session, classroom: Classroom, student: Student
) -> tuple[VocabPkPlayer, VocabPkMatch | None]:
    """学生自愿加入排队；满 2 人自动配对 1v1。返回玩家与新对局（若刚配对）。"""
    lobby = get_lobby(session, classroom.id, open_only=True)
    if lobby is None:
        raise HTTPException(status_code=404, detail="当前没有开放的 PK 大厅")

    existing = session.exec(
        select(VocabPkPlayer).where(
            VocabPkPlayer.lobby_id == lobby.id,  # type: ignore[arg-type]
            VocabPkPlayer.student_id == student.id,  # type: ignore[arg-type]
        )
    ).first()

    active_players = [
        p
        for p in _players_of_lobby(session, lobby.id)
        if p.status in ACTIVE_PLAYER_STATUSES
    ]
    active_matches = session.exec(
        select(VocabPkMatch).where(
            VocabPkMatch.lobby_id == lobby.id,  # type: ignore[arg-type]
            VocabPkMatch.status == "active",
        )
    ).all()

    if existing is not None and existing.status in ACTIVE_PLAYER_STATUSES:
        match = (
            session.get(VocabPkMatch, existing.match_id) if existing.match_id else None
        )
        return existing, match

    if len(active_players) >= MAX_QUEUE_PLAYERS:
        raise HTTPException(status_code=422, detail="当前 PK 人数已满，请稍后再来")
    if len(active_matches) >= MAX_ACTIVE_MATCHES:
        raise HTTPException(status_code=422, detail="当前对局场数已满，请稍后再来")

    if existing is not None:
        existing.status = "waiting"
        existing.left_at = None
        session.add(existing)
        player = existing
    else:
        player = VocabPkPlayer(
            lobby_id=lobby.id,
            classroom_id=classroom.id,
            student_id=student.id,
            status="waiting",
        )
        session.add(player)
    session.flush()

    # 配对：另一名等待中的玩家；锁大厅行避免两人同时被配到多场
    session.exec(
        select(VocabPkLobby).where(VocabPkLobby.id == lobby.id).with_for_update()
    ).first()
    partner = session.exec(
        select(VocabPkPlayer).where(
            VocabPkPlayer.lobby_id == lobby.id,  # type: ignore[arg-type]
            VocabPkPlayer.status == "waiting",
            VocabPkPlayer.student_id != student.id,  # type: ignore[arg-type]
        )
    ).first()

    match: VocabPkMatch | None = None
    if partner is not None:
        match = _start_match(session, lobby, player, partner)
    session.commit()
    session.refresh(player)
    if match is not None:
        session.refresh(match)
    return player, match


def leave_lobby(session: Session, classroom: Classroom, student: Student) -> None:
    """离开大厅：排队中直接退出；对局中标记离场，由结算收口。"""
    lobby = get_lobby(session, classroom.id, open_only=True)
    if lobby is None:
        return
    player = session.exec(
        select(VocabPkPlayer).where(
            VocabPkPlayer.lobby_id == lobby.id,  # type: ignore[arg-type]
            VocabPkPlayer.student_id == student.id,  # type: ignore[arg-type]
        )
    ).first()
    if player is None:
        return
    if player.status == "active" and player.match_id is not None:
        player.status = "left"
        player.left_at = _now()
        session.add(player)
        _settle_if_over(session, session.get(VocabPkMatch, player.match_id))
    else:
        player.status = "left"
        player.left_at = _now()
        session.add(player)
    session.commit()


def _start_match(
    session: Session,
    lobby: VocabPkLobby,
    first: VocabPkPlayer,
    second: VocabPkPlayer,
) -> VocabPkMatch:
    now = _now()
    deadline = now + timedelta(seconds=lobby.per_question_seconds)
    match = VocabPkMatch(
        lobby_id=lobby.id,
        classroom_id=lobby.classroom_id,
        snapshot_items=list(lobby.snapshot_items),
        question_count=lobby.question_count,
        per_question_seconds=lobby.per_question_seconds,
        status="active",
        current_item_index=0,
        current_deadline_at=deadline,
        started_at=now,
    )
    session.add(match)
    session.flush()

    first.side = "left"
    second.side = "right"
    first.status = "active"
    second.status = "active"
    first.match_id = match.id
    second.match_id = match.id
    session.add(first)
    session.add(second)
    return match


# ── 作答与判分 ──────────────────────────────────────────────────────


def _replay_answer(
    session: Session,
    match: VocabPkMatch,
    player: VocabPkPlayer,
    *,
    item_index: int,
    prompt_type: str,
    answer_raw: str,
    idempotency_key: str | None,
) -> VocabPkAnswer | None:
    """幂等重放：同键且同对局/玩家/题/规范化答案 → 返回首次作答；冲突 422。"""
    if not idempotency_key:
        return None
    normalized = vocab_service.normalize_spelling(answer_raw)
    existing = session.exec(
        select(VocabPkAnswer).where(
            VocabPkAnswer.idempotency_key == idempotency_key  # type: ignore[arg-type]
        )
    ).first()
    if existing is None:
        return None
    if existing.tenant_id != match.tenant_id:
        return None
    same = (
        existing.match_id == match.id
        and existing.player_id == player.id
        and existing.item_index == item_index
        and existing.prompt_type == prompt_type
        and existing.answer_normalized == normalized
    )
    if not same:
        raise HTTPException(
            status_code=422, detail="幂等键已用于其他作答，请刷新后重新提交"
        )
    return existing


def _judge(prompt_type: str, answer_raw: str, snapshot_item: dict[str, object]) -> bool:
    if prompt_type in prompt_types_mod.CHOICE_PROMPT_TYPES:
        return prompt_types_mod.choice_answer_matches(answer_raw, snapshot_item)
    return vocab_service.check_spelling(answer_raw, snapshot_item)


def submit_answer(
    session: Session,
    match: VocabPkMatch,
    player: VocabPkPlayer,
    *,
    item_index: int,
    prompt_type: str,
    answer_raw: str,
    idempotency_key: str | None,
) -> PkAnswerResult:
    """判分落库：每题只计首次有效提交；幂等重放不二次计分。"""
    _settle_due(session, match)
    if match.status != "active":
        raise HTTPException(status_code=422, detail="对局已结束，不能继续作答")
    if player.status not in ("active",):
        raise HTTPException(status_code=422, detail="您已离开本局")

    replay = _replay_answer(
        session,
        match,
        player,
        item_index=item_index,
        prompt_type=prompt_type,
        answer_raw=answer_raw,
        idempotency_key=idempotency_key,
    )

    snapshots = match.snapshot_items
    if not 0 <= item_index < len(snapshots):
        raise HTTPException(status_code=422, detail="题目序号不在本局范围内")
    snapshot_item = snapshots[item_index]
    available_types = snapshot_item.get("prompt_types")
    if isinstance(available_types, list) and prompt_type not in available_types:
        raise HTTPException(status_code=422, detail="该题不支持这种出题方式")

    normalized = vocab_service.normalize_spelling(answer_raw)
    if not normalized:
        raise HTTPException(status_code=422, detail="作答内容不能为空白")
    if len(normalized) > 255:
        raise HTTPException(status_code=422, detail="作答内容过长，请缩短后提交")

    # 对局行锁：提交/超时结算共享，锁内重校验状态与服务端时间
    session.refresh(match, with_for_update=True)
    replay = replay or _replay_answer(
        session,
        match,
        player,
        item_index=item_index,
        prompt_type=prompt_type,
        answer_raw=answer_raw,
        idempotency_key=idempotency_key,
    )
    if replay is not None:
        return _answer_result(match, player, replay, replayed=True)

    existing_slot = session.exec(
        select(VocabPkAnswer).where(
            VocabPkAnswer.player_id == player.id,  # type: ignore[arg-type]
            VocabPkAnswer.item_index == item_index,
        )
    ).first()
    if existing_slot is not None:
        raise HTTPException(status_code=422, detail="本题已经作答，不能修改答案")

    is_correct = _judge(prompt_type, answer_raw, snapshot_item)

    now = _now()
    deadline = match.current_deadline_at or now
    question_start = deadline.timestamp() - match.per_question_seconds
    latency_seconds = max(
        0.0, min(now.timestamp() - question_start, float(match.per_question_seconds))
    )
    latency_ms = int(round(latency_seconds * 1000))

    if is_correct:
        ratio = latency_seconds / match.per_question_seconds
        bonus = int(round(PK_SPEED_BONUS_MAX * max(0.0, 1.0 - ratio)))
        bonus = max(0, min(bonus, PK_SPEED_BONUS_MAX))
        base = PK_ANSWER_BASE
        score = base + bonus
    else:
        bonus = 0
        base = 0
        score = 0

    answer = VocabPkAnswer(
        match_id=match.id,
        player_id=player.id,
        student_id=player.student_id,
        item_index=item_index,
        prompt_type=prompt_type,
        answer_raw=answer_raw[:255],
        answer_normalized=normalized[:255],
        is_correct=is_correct,
        base_score=base,
        speed_bonus=bonus,
        score=score,
        latency_ms=latency_ms,
        idempotency_key=idempotency_key,
    )
    session.add(answer)

    player.score += score
    player.answered_count += 1
    player.correct_count += 1 if is_correct else 0
    player.total_seconds += latency_seconds
    session.add(player)

    _advance_if_both_ready(session, match)
    _settle_if_over(session, match)
    session.commit()
    session.refresh(answer)
    return _answer_result(match, player, answer, replayed=False)


def _answer_result(
    match: VocabPkMatch,
    player: VocabPkPlayer,
    answer: VocabPkAnswer,
    *,
    replayed: bool,
) -> PkAnswerResult:
    remaining = _remaining_seconds(match)
    return PkAnswerResult(
        item_index=answer.item_index,
        is_correct=answer.is_correct,
        base_score=answer.base_score,
        speed_bonus=answer.speed_bonus,
        score=answer.score,
        answered_count=player.answered_count,
        correct_count=player.correct_count,
        my_score=player.score,
        match_status=match.status,
        remaining_seconds=remaining,
        replayed=replayed,
    )


def _remaining_seconds(match: VocabPkMatch) -> int | None:
    if match.status != "active" or match.current_deadline_at is None:
        return None
    return max(0, int((match.current_deadline_at - _now()).total_seconds()))


# ── 推进与结算 ──────────────────────────────────────────────────────


def _match_players(session: Session, match: VocabPkMatch) -> list[VocabPkPlayer]:
    return list(
        session.exec(
            select(VocabPkPlayer).where(VocabPkPlayer.match_id == match.id)  # type: ignore[arg-type]
        ).all()
    )


def _answered_slots(session: Session, player: VocabPkPlayer) -> set[int]:
    rows = session.exec(
        select(VocabPkAnswer.item_index).where(
            VocabPkAnswer.player_id == player.id  # type: ignore[arg-type]
        )
    ).all()
    return set(rows)


def _advance_if_both_ready(session: Session, match: VocabPkMatch) -> None:
    """双方都已答当前题 → 推进到下一题，重置服务端截止点。"""
    if match.status != "active":
        return
    players = _match_players(session, match)
    if len(players) < 2:
        return
    slots = [_answered_slots(session, p) for p in players]
    idx = match.current_item_index
    while idx < match.question_count and all(idx in s for s in slots):
        idx += 1
    if idx != match.current_item_index:
        match.current_item_index = idx
        if idx < match.question_count:
            match.current_deadline_at = _now() + timedelta(
                seconds=match.per_question_seconds
            )
        match.state_version += 1
        session.add(match)


def _settle_due(session: Session, match: VocabPkMatch) -> None:
    """惰性超时收口：当前题到时，未答者记 0 并推进；玩家答满即终结。"""
    if match.status != "active":
        return
    now = _now()
    players = _match_players(session, match)
    progressed = False
    while match.status == "active" and match.current_deadline_at is not None:
        if now <= match.current_deadline_at:
            break
        idx = match.current_item_index
        if idx >= match.question_count:
            break
        # 超时未答的空位记为已过（不建作答行），推进到下一题
        for player in players:
            slots = _answered_slots(session, player)
            if idx not in slots and player.status == "active":
                player.answered_count += 1
                session.add(player)
        match.current_item_index = idx + 1
        progressed = True
        if match.current_item_index < match.question_count:
            match.current_deadline_at = now + timedelta(
                seconds=match.per_question_seconds
            )
        else:
            match.current_deadline_at = None
    if progressed:
        match.state_version += 1
        session.add(match)
    _settle_if_over(session, match)


def _settle_if_over(session: Session, match: VocabPkMatch | None) -> None:
    """双方终结（答满/离场）→ 结算胜负；结算幂等。"""
    if match is None or match.status != "active":
        return
    players = _match_players(session, match)
    if len(players) < 2:
        return
    finished = [p for p in players if p.answered_count >= match.question_count]
    left = [p for p in players if p.status == "left"]
    if len(finished) < 2 and not (left and len(left) == 2):
        return

    match.status = "finished"
    match.finished_at = _now()
    match.state_version += 1

    if len(left) == 2:
        match.end_reason = "abandoned"
        match.winner_student_id = None
    else:
        active_players = [p for p in players if p.status != "left"]
        if len(active_players) == 1:
            winner = active_players[0]
            match.winner_student_id = winner.student_id
            match.end_reason = "walkover"
        else:
            first, second = players[0], players[1]
            winner = _decide_winner(first, second)
            match.winner_student_id = winner.student_id if winner is not None else None
            match.end_reason = "completion"
    for player in players:
        if player.status != "left":
            player.status = "finished"
            player.finished_at = match.finished_at
        session.add(player)
    session.add(match)


def _decide_winner(first: VocabPkPlayer, second: VocabPkPlayer) -> VocabPkPlayer | None:
    """总分高者胜；同分比总用时（少者胜）；再平为平局。"""
    if first.score > second.score:
        return first
    if second.score > first.score:
        return second
    if first.total_seconds < second.total_seconds:
        return first
    if second.total_seconds < first.total_seconds:
        return second
    return None


# ── 对局视图 ─────────────────────────────────────────────────────────


def get_match_for_player(
    session: Session, match_id: uuid.UUID, student: Student
) -> tuple[VocabPkMatch, VocabPkPlayer, VocabPkPlayer | None]:
    match = session.get(VocabPkMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="对局不存在")
    players = _match_players(session, match)
    me = next((p for p in players if p.student_id == student.id), None)
    if me is None:
        raise HTTPException(status_code=404, detail="对局不存在")
    opponent = next((p for p in players if p.id != me.id), None)
    return match, me, opponent


def match_view(
    session: Session,
    match: VocabPkMatch,
    me: VocabPkPlayer,
    opponent: VocabPkPlayer | None,
) -> PkMatchView:
    _settle_due(session, match)
    my_answers = {
        a.item_index: a
        for a in session.exec(
            select(VocabPkAnswer).where(VocabPkAnswer.player_id == me.id)  # type: ignore[arg-type]
        ).all()
    }
    items = [
        _item_view(idx, snapshot, my_answers.get(idx))
        for idx, snapshot in enumerate(match.snapshot_items)
    ]

    my_next_index = next(
        (i for i in range(match.question_count) if i not in my_answers),
        match.question_count,
    )

    result: PkMatchResult | None = None
    if match.status == "finished":
        drew = match.winner_student_id is None
        result = PkMatchResult(
            status=match.status,
            end_reason=match.end_reason,
            winner_student_id=match.winner_student_id,
            drew=drew,
        )

    me_summary = _player_summary(me, _student_display_name(session, me.student_id))
    opponent_summary = (
        _player_summary(opponent, _student_display_name(session, opponent.student_id))
        if opponent is not None
        else None
    )
    return PkMatchView(
        match_id=match.id,
        lobby_id=match.lobby_id,
        status=match.status,
        state_version=match.state_version,
        question_count=match.question_count,
        current_item_index=my_next_index,
        remaining_seconds=_remaining_seconds(match),
        per_question_seconds=match.per_question_seconds,
        me=me_summary,
        opponent=opponent_summary,
        items=items,
        result=result,
        started_at=match.started_at,
        finished_at=match.finished_at,
    )


def _item_view(
    index: int, snapshot: dict[str, object], answer: VocabPkAnswer | None
) -> PkMatchItem:
    snapshot_typed: dict[str, Any] = snapshot
    prompt_type = prompt_types_mod._single_prompt_type(snapshot)
    choices: list[PkChoice] = []
    raw_choices = snapshot_typed.get("choices")
    if isinstance(raw_choices, list):
        for choice in raw_choices:
            choice_dict = dict(choice)
            choices.append(
                PkChoice(
                    word_id=uuid.UUID(str(choice_dict["word_id"])),
                    headword=str(choice_dict.get("headword") or ""),
                    meaning_zh=str(choice_dict.get("meaning_zh") or ""),
                    part_of_speech=choice_dict.get("part_of_speech"),
                    is_answer=bool(answer and answer.is_correct)
                    and str(choice_dict["word_id"]) == str(snapshot_typed["word_id"]),
                )
            )
    segments: list[PkMorphSegment] = []
    raw_segments = snapshot_typed.get("morph_segments")
    if isinstance(raw_segments, list):
        for seg in raw_segments:
            seg_dict = dict(seg)
            segments.append(
                PkMorphSegment(
                    text=str(seg_dict.get("text") or ""),
                    gloss=str(seg_dict.get("gloss") or ""),
                    kind=str(seg_dict.get("kind") or "root"),
                )
            )

    first_choice_id: uuid.UUID | None = None
    if answer is not None and prompt_type in prompt_types_mod.CHOICE_PROMPT_TYPES:
        first_choice_id = prompt_types_mod.chosen_word_id(answer.answer_raw)

    return PkMatchItem(
        item_index=index,
        prompt_type=prompt_type,
        part_of_speech=snapshot_typed.get("part_of_speech"),
        meaning_zh=str(snapshot_typed.get("meaning_zh") or ""),
        meaning_en=snapshot_typed.get("meaning_en"),
        audio_url=snapshot_typed.get("audio_url"),
        choices=choices,
        cloze_sentence=snapshot_typed.get("cloze_sentence"),
        morph_segments=segments,
        headword=str(snapshot_typed["headword"]) if answer is not None else None,
        answered=answer is not None,
        is_correct=answer.is_correct if answer is not None else None,
        first_choice_word_id=first_choice_id,
        score=answer.score if answer is not None else None,
    )


def match_state_snapshot(
    session: Session, match: VocabPkMatch, me: VocabPkPlayer
) -> dict[str, Any]:
    """SSE / 轮询共用的状态快照（同一读路径，行为一致）。"""
    view = match_view(session, match, me, _opponent(session, me))
    return view.model_dump(mode="json")


def _opponent(session: Session, me: VocabPkPlayer) -> VocabPkPlayer | None:
    if me.match_id is None:
        return None
    match = session.get(VocabPkMatch, me.match_id)
    if match is None:
        return None
    players = _match_players(session, match)
    return next((p for p in players if p.id != me.id), None)
