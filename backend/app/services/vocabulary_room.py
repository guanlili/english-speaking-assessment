"""课堂大屏 PK「房间码」域逻辑：开房、凭码入场、服务端时钟、团队计分与结算。

形态（手册 §06 对齐、口径按本单定稿）：

- 教师开房 → 6 位房间码；学生凭码入场，不再走 1v1 自动配对。
- 全班同题序：题单开房时固化，题目推进由 ``started_at + 题序 × 单题秒数``
  推导，无后台任务；断线重连按服务端时间回到当前题与剩余秒数。
- 两种赛制：``solo`` 个人计分 / ``team`` 按入场顺序均分到 1..team_count 组，
  队伍分为成员得分之和。
- 隔离：作答只落 ``vocab_pk_room_answer``，不写 ``VocabularyAnswer``、不改
  任务首答成绩/完成率、不写错词本、不进 FSRS；结算只在主持端只读展示。
"""

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.crud import classroom_teacher_allowed
from app.models import (
    DEFAULT_ROOM_QUESTION_COUNT,
    DEFAULT_ROOM_SECONDS,
    MAX_QUESTION_COUNT,
    MAX_ROOM_PLAYERS,
    MAX_TEAM_COUNT,
    MIN_TEAM_COUNT,
    PK_ANSWER_BASE,
    PK_SPEED_BONUS_MAX,
    ROOM_CODE_LENGTH,
    ROOM_ENDED,
    ROOM_LIVE,
    ROOM_MODE_SOLO,
    ROOM_MODE_TEAM,
    ROOM_WAITING,
    Classroom,
    PkRoomAnswerResult,
    PkRoomHostView,
    PkRoomItem,
    PkRoomPlayerSummary,
    PkRoomQuestionStats,
    PkRoomResult,
    PkRoomResultRow,
    PkRoomStudentView,
    PkRoomTeamSummary,
    Student,
    User,
    VocabPkRoom,
    VocabPkRoomAnswer,
    VocabPkRoomPlayer,
)
from app.models.vocabulary.pk import (
    MAX_PER_QUESTION_SECONDS,
    MIN_PER_QUESTION_SECONDS,
)
from app.services import vocabulary_pk as pk_service
from app.services import vocabulary_prompt_types as prompt_types_mod

DEFAULT_ROOM_PROMPT_TYPES = ["meaning", "en_zh", "zh_en"]


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _require_teacher(classroom: Classroom, user: User, session: Session) -> None:
    if not classroom_teacher_allowed(classroom, user, session):
        raise HTTPException(
            status_code=403, detail="没有权限：仅本班教师可以主持大屏 PK"
        )


# ── 时钟 ────────────────────────────────────────────────────────────


def clock(room: VocabPkRoom, now: datetime | None = None) -> tuple[int, int]:
    """返回 (当前题序, 剩余秒数)。

    未开赛为 (0, 单题秒数)；进行中按服务端时间推导，最后一题结束即题序等于
    题量、剩余 0（视图把它读作已结束，不依赖后台任务）。
    """
    if room.started_at is None:
        return 0, room.per_question_seconds
    started = _as_utc(room.started_at) or _now()
    now = now or _now()
    elapsed = max(0.0, (now - started).total_seconds())
    index = int(elapsed // room.per_question_seconds)
    if index >= room.question_count:
        return room.question_count, 0
    remaining = room.per_question_seconds - int(elapsed % room.per_question_seconds)
    return index, max(1, remaining)


def effective_status(room: VocabPkRoom) -> str:
    if room.status == ROOM_LIVE:
        index, _ = clock(room)
        if index >= room.question_count:
            return ROOM_ENDED
    return room.status


def finalize_if_due(session: Session, room: VocabPkRoom) -> None:
    """把已跑完题量的房间落库为 ended（幂等；由读/写路径惰性触发）。"""
    if room.status != ROOM_LIVE:
        return
    index, _ = clock(room)
    if index < room.question_count:
        return
    started = _as_utc(room.started_at) or _now()
    room.status = ROOM_ENDED
    room.ended_at = started + timedelta(
        seconds=room.per_question_seconds * room.question_count
    )
    session.add(room)
    session.commit()
    session.refresh(room)


# ── 开房 ────────────────────────────────────────────────────────────


def _generate_code(session: Session) -> str:
    for _ in range(30):
        code = "".join(random.choices("0123456789", k=ROOM_CODE_LENGTH))
        exists = session.exec(
            select(VocabPkRoom).where(VocabPkRoom.room_code == code)
        ).first()
        if exists is None:
            return code
    raise HTTPException(status_code=503, detail="房间码分配失败，请稍后重试")


def _active_room(session: Session, classroom_id: uuid.UUID) -> VocabPkRoom | None:
    return session.exec(
        select(VocabPkRoom)
        .where(
            VocabPkRoom.classroom_id == classroom_id,
            col(VocabPkRoom.status).in_([ROOM_WAITING, ROOM_LIVE]),
        )
        .order_by(col(VocabPkRoom.created_at).desc())
    ).first()


def create_room(
    session: Session,
    classroom: Classroom,
    teacher: User,
    *,
    book_id: uuid.UUID,
    question_count: int | None,
    per_question_seconds: int | None,
    prompt_types: list[str] | None,
    mode: str,
    team_count: int | None,
) -> VocabPkRoom:
    """教师开房：固化题单、生成 6 位码；同课堂旧房间自动收口。"""
    _require_teacher(classroom, teacher, session)
    if mode not in (ROOM_MODE_SOLO, ROOM_MODE_TEAM):
        raise HTTPException(status_code=422, detail="赛制只能是 solo 或 team")
    q_count = min(
        max(question_count or DEFAULT_ROOM_QUESTION_COUNT, 1), MAX_QUESTION_COUNT
    )
    seconds = min(
        max(per_question_seconds or DEFAULT_ROOM_SECONDS, MIN_PER_QUESTION_SECONDS),
        MAX_PER_QUESTION_SECONDS,
    )
    types = prompt_types or DEFAULT_ROOM_PROMPT_TYPES
    teams = 0
    if mode == ROOM_MODE_TEAM:
        teams = min(max(team_count or 4, MIN_TEAM_COUNT), MAX_TEAM_COUNT)

    snapshot_items = pk_service._build_snapshot_items(
        session, teacher, book_id, types, q_count
    )

    previous = _active_room(session, classroom.id)
    if previous is not None:
        previous.status = ROOM_ENDED
        previous.ended_at = _now()
        session.add(previous)

    room = VocabPkRoom(
        classroom_id=classroom.id,
        created_by=teacher.id,
        book_id=book_id,
        room_code=_generate_code(session),
        mode=mode,
        team_count=teams,
        prompt_types=list(types),
        question_count=len(snapshot_items),
        per_question_seconds=seconds,
        status=ROOM_WAITING,
        snapshot_items=snapshot_items,
    )
    session.add(room)
    try:
        session.commit()
    except IntegrityError as exc:  # 房间码撞车（极小概率）：换码重试一次
        session.rollback()
        room.room_code = _generate_code(session)
        session.add(room)
        session.commit()
        _ = exc
    session.refresh(room)
    return room


def get_room(
    session: Session, classroom_id: uuid.UUID, room_id: uuid.UUID
) -> VocabPkRoom:
    room = session.get(VocabPkRoom, room_id)
    if room is None or room.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="房间不存在或已结束")
    return room


def current_room(
    session: Session, classroom: Classroom, teacher: User
) -> VocabPkRoom | None:
    _require_teacher(classroom, teacher, session)
    room = _active_room(session, classroom.id)
    if room is None:
        return None
    finalize_if_due(session, room)
    return None if room.status == ROOM_ENDED else room


def start_room(
    session: Session, classroom: Classroom, room: VocabPkRoom, teacher: User
) -> VocabPkRoom:
    _require_teacher(classroom, teacher, session)
    if room.status != ROOM_WAITING:
        raise HTTPException(status_code=409, detail="房间已经开始或已结束")
    room.status = ROOM_LIVE
    room.started_at = _now()
    session.add(room)
    session.commit()
    session.refresh(room)
    return room


def end_room(
    session: Session, classroom: Classroom, room: VocabPkRoom, teacher: User
) -> VocabPkRoom:
    _require_teacher(classroom, teacher, session)
    if room.status != ROOM_ENDED:
        room.status = ROOM_ENDED
        room.ended_at = _now()
        session.add(room)
        session.commit()
        session.refresh(room)
    return room


# ── 入场 ────────────────────────────────────────────────────────────


def join_room(
    session: Session, classroom: Classroom, student: Student, code: str
) -> VocabPkRoom:
    room = session.exec(
        select(VocabPkRoom).where(
            VocabPkRoom.classroom_id == classroom.id,
            VocabPkRoom.room_code == code.strip(),
        )
    ).first()
    if room is None:
        raise HTTPException(status_code=404, detail="房间码不正确，或房间不属于本班")
    if effective_status(room) == ROOM_ENDED:
        raise HTTPException(status_code=409, detail="本轮已经结束")

    existing = session.exec(
        select(VocabPkRoomPlayer).where(
            VocabPkRoomPlayer.room_id == room.id,
            VocabPkRoomPlayer.student_id == student.id,
        )
    ).first()
    if existing is not None:
        return room

    players = session.exec(
        select(VocabPkRoomPlayer).where(VocabPkRoomPlayer.room_id == room.id)
    ).all()
    if len(players) >= MAX_ROOM_PLAYERS:
        raise HTTPException(status_code=409, detail="房间人数已满")

    team_index = 0
    if room.mode == ROOM_MODE_TEAM and room.team_count:
        team_index = len(players) % room.team_count + 1
    player = VocabPkRoomPlayer(
        room_id=room.id,
        classroom_id=classroom.id,
        student_id=student.id,
        team_index=team_index,
    )
    session.add(player)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
    return room


# ── 作答 ────────────────────────────────────────────────────────────


def _player_of(
    session: Session, room_id: uuid.UUID, student_id: uuid.UUID
) -> VocabPkRoomPlayer:
    player = session.exec(
        select(VocabPkRoomPlayer).where(
            VocabPkRoomPlayer.room_id == room_id,
            VocabPkRoomPlayer.student_id == student_id,
        )
    ).first()
    if player is None:
        raise HTTPException(status_code=404, detail="还没有入场，请先输入房间码")
    return player


def submit_answer(
    session: Session,
    room: VocabPkRoom,
    student: Student,
    *,
    item_index: int,
    answer: str,
) -> PkRoomAnswerResult:
    player = _player_of(session, room.id, student.id)
    finalize_if_due(session, room)
    if room.status != ROOM_LIVE:
        raise HTTPException(status_code=409, detail="本轮尚未开始或已经结束")
    index, _remaining = clock(room)
    if index >= room.question_count:
        raise HTTPException(status_code=409, detail="本轮已经结束")
    if item_index != index:
        raise HTTPException(status_code=409, detail="这道题已经翻页，请看当前题")

    existing = session.exec(
        select(VocabPkRoomAnswer).where(
            VocabPkRoomAnswer.player_id == player.id,
            VocabPkRoomAnswer.item_index == index,
        )
    ).first()
    if existing is not None:
        return PkRoomAnswerResult(
            item_index=index,
            is_correct=existing.is_correct,
            score=existing.score,
            base_score=existing.base_score,
            speed_bonus=existing.speed_bonus,
            headword=_headword(room.snapshot_items[index]),
            my_score=player.score,
            rank=_rank_of(session, room, player),
        )

    snapshot = room.snapshot_items[index]
    prompt_type = prompt_types_mod._single_prompt_type(snapshot)
    is_correct = pk_service._judge(prompt_type, answer, snapshot)
    remaining_seconds = _remaining
    base = PK_ANSWER_BASE if is_correct else 0
    bonus = 0
    if is_correct:
        bonus = round(
            PK_SPEED_BONUS_MAX * remaining_seconds / room.per_question_seconds
        )
    total = base + bonus
    latency_ms = max(
        0,
        int((_now() - (_as_utc(room.started_at) or _now())).total_seconds() * 1000)
        - index * room.per_question_seconds * 1000,
    )

    record = VocabPkRoomAnswer(
        room_id=room.id,
        player_id=player.id,
        student_id=student.id,
        item_index=index,
        prompt_type=prompt_type,
        answer_raw=answer,
        is_correct=is_correct,
        base_score=base,
        speed_bonus=bonus,
        score=total,
        latency_ms=latency_ms,
    )
    player.score += total
    player.answered_count += 1
    player.correct_count += 1 if is_correct else 0
    player.total_seconds += latency_ms / 1000
    session.add(record)
    session.add(player)
    try:
        session.commit()
    except IntegrityError:  # 并发重复提交：沿用首次结果
        session.rollback()
        existing = session.exec(
            select(VocabPkRoomAnswer).where(
                VocabPkRoomAnswer.player_id == player.id,
                VocabPkRoomAnswer.item_index == index,
            )
        ).first()
        if existing is None:
            raise
        return PkRoomAnswerResult(
            item_index=index,
            is_correct=existing.is_correct,
            score=existing.score,
            base_score=existing.base_score,
            speed_bonus=existing.speed_bonus,
            headword=_headword(room.snapshot_items[index]),
            my_score=player.score,
            rank=None,
        )

    return PkRoomAnswerResult(
        item_index=index,
        is_correct=is_correct,
        score=total,
        base_score=base,
        speed_bonus=bonus,
        headword=_headword(snapshot),
        my_score=player.score,
        rank=_rank_of(session, room, player),
    )


# ── 视图 ────────────────────────────────────────────────────────────


def _headword(snapshot: dict[str, object]) -> str | None:
    value = snapshot.get("headword")
    return str(value) if value else None


def _display_name(session: Session, student_id: uuid.UUID) -> str | None:
    student = session.get(Student, student_id)
    return student.display_name if student is not None else None


def _players(session: Session, room_id: uuid.UUID) -> list[VocabPkRoomPlayer]:
    return list(
        session.exec(
            select(VocabPkRoomPlayer).where(VocabPkRoomPlayer.room_id == room_id)
        )
    )


def _ranking(players: list[VocabPkRoomPlayer]) -> list[VocabPkRoomPlayer]:
    # 同分比总用时（小者前），再按入场先后
    return sorted(
        players,
        key=lambda p: (-p.score, p.total_seconds, p.joined_at or _now()),
    )


def _rank_of(
    session: Session, room: VocabPkRoom, player: VocabPkRoomPlayer
) -> int | None:
    ids = [p.id for p in _ranking(_players(session, room.id))]
    return ids.index(player.id) + 1 if player.id in ids else None


def _answers(session: Session, room_id: uuid.UUID) -> list[VocabPkRoomAnswer]:
    return list(
        session.exec(
            select(VocabPkRoomAnswer).where(VocabPkRoomAnswer.room_id == room_id)
        )
    )


def _question_stats(
    room: VocabPkRoom,
    answers: list[VocabPkRoomAnswer],
    *,
    reveal_through: int,
) -> list[PkRoomQuestionStats]:
    stats: list[PkRoomQuestionStats] = []
    for index, snapshot in enumerate(room.snapshot_items):
        item_answers = [a for a in answers if a.item_index == index]
        answered = len(item_answers)
        correct = sum(1 for a in item_answers if a.is_correct)
        stats.append(
            PkRoomQuestionStats(
                item_index=index,
                prompt_type=prompt_types_mod._single_prompt_type(snapshot),
                answered_count=answered,
                correct_count=correct,
                accuracy=(correct / answered) if answered else None,
                # 只在翻页之后揭晓词形（大屏不提前泄题）
                headword=_headword(snapshot) if index < reveal_through else None,
                meaning_zh=str(snapshot.get("meaning_zh") or "") or None,
            )
        )
    return stats


def _team_summaries(
    room: VocabPkRoom, players: list[VocabPkRoomPlayer]
) -> list[PkRoomTeamSummary]:
    if room.mode != ROOM_MODE_TEAM or not room.team_count:
        return []
    teams: list[PkRoomTeamSummary] = []
    for index in range(1, room.team_count + 1):
        members = [p for p in players if p.team_index == index]
        teams.append(
            PkRoomTeamSummary(
                team_index=index,
                label=f"第 {index} 组",
                score=sum(p.score for p in members),
                member_count=len(members),
                answered_count=sum(p.answered_count for p in members),
                correct_count=sum(p.correct_count for p in members),
            )
        )
    return teams


def _player_summaries(
    session: Session,
    players: list[VocabPkRoomPlayer],
    current_index: int,
    answers: list[VocabPkRoomAnswer],
) -> list[PkRoomPlayerSummary]:
    ranked = _ranking(players)
    answered_current = {a.player_id for a in answers if a.item_index == current_index}
    return [
        PkRoomPlayerSummary(
            student_id=p.student_id,
            display_name=_display_name(session, p.student_id),
            team_index=p.team_index,
            score=p.score,
            answered_count=p.answered_count,
            correct_count=p.correct_count,
            total_seconds=p.total_seconds,
            rank=position,
            answered_current=p.id in answered_current,
        )
        for position, p in enumerate(ranked, start=1)
    ]


def _result(
    session: Session,
    room: VocabPkRoom,
    players: list[VocabPkRoomPlayer],
    answers: list[VocabPkRoomAnswer],
) -> PkRoomResult:
    teams = _team_summaries(room, players)
    rows: list[PkRoomResultRow] = []
    for rank, team in enumerate(
        sorted(teams, key=lambda t: (-t.score, t.team_index)), start=1
    ):
        rows.append(
            PkRoomResultRow(
                team_index=team.team_index,
                label=team.label,
                score=team.score,
                rank=rank,
                member_count=team.member_count,
            )
        )
    questions = _question_stats(room, answers, reveal_through=room.question_count)
    wrong_words = [
        q.headword
        for q in questions
        if q.headword and q.answered_count > q.correct_count
    ]
    return PkRoomResult(
        teams=rows,
        players=_player_summaries(session, players, room.question_count, answers),
        questions=questions,
        wrong_words=list(dict.fromkeys(wrong_words)),
    )


def host_view(session: Session, room: VocabPkRoom) -> PkRoomHostView:
    finalize_if_due(session, room)
    status = effective_status(room)
    index, remaining = clock(room)
    players = _players(session, room.id)
    answers = _answers(session, room.id)
    current_answers = [a for a in answers if a.item_index == index]
    correct = sum(1 for a in current_answers if a.is_correct)
    accuracy = (correct / len(current_answers)) if current_answers else None

    reveal_through = room.question_count if status == ROOM_ENDED else index
    questions = _question_stats(room, answers, reveal_through=reveal_through)

    current_item = None
    if index < room.question_count:
        stat = questions[index]
        current_item = PkRoomQuestionStats(
            item_index=index,
            prompt_type=stat.prompt_type,
            answered_count=len(current_answers),
            correct_count=correct,
            accuracy=accuracy,
            headword=None,
            meaning_zh=stat.meaning_zh,
        )

    result = _result(session, room, players, answers) if status == ROOM_ENDED else None
    return PkRoomHostView(
        room_id=room.id,
        room_code=room.room_code,
        classroom_id=room.classroom_id,
        book_id=room.book_id,
        status=status,
        mode=room.mode,
        team_count=room.team_count,
        question_count=room.question_count,
        per_question_seconds=room.per_question_seconds,
        prompt_types=list(room.prompt_types),
        current_item_index=index,
        remaining_seconds=remaining,
        participant_count=len(players),
        current_answered_count=len(current_answers),
        current_correct_count=correct,
        current_accuracy=accuracy,
        current_item=current_item,
        players=_player_summaries(session, players, index, answers),
        teams=_team_summaries(room, players),
        questions=questions,
        started_at=room.started_at,
        ended_at=room.ended_at,
        result=result,
    )


def _room_item(
    index: int,
    snapshot: dict[str, object],
    answer: VocabPkRoomAnswer | None,
    *,
    reveal: bool,
) -> PkRoomItem:
    data: dict[str, Any] = snapshot
    prompt_type = prompt_types_mod._single_prompt_type(snapshot)
    choices: list[dict[str, object]] = []
    raw_choices = data.get("choices")
    if isinstance(raw_choices, list):
        for choice in raw_choices:
            item = dict(choice)
            item["is_answer"] = bool(answer and answer.is_correct) and str(
                item.get("word_id")
            ) == str(data.get("word_id"))
            choices.append(item)
    segments: list[dict[str, object]] = []
    raw_segments = data.get("morph_segments")
    if isinstance(raw_segments, list):
        segments = [dict(seg) for seg in raw_segments]

    revealed = reveal or answer is not None
    return PkRoomItem(
        item_index=index,
        prompt_type=prompt_type,
        part_of_speech=data.get("part_of_speech"),
        meaning_zh=str(data.get("meaning_zh") or ""),
        meaning_en=data.get("meaning_en"),
        choices=choices,
        cloze_sentence=data.get("cloze_sentence"),
        morph_segments=segments,
        headword=_headword(snapshot) if revealed else None,
        answered=answer is not None,
        is_correct=answer.is_correct if answer is not None else None,
        score=answer.score if answer is not None else None,
    )


def student_view(
    session: Session, room: VocabPkRoom, student: Student
) -> PkRoomStudentView:
    finalize_if_due(session, room)
    status = effective_status(room)
    index, remaining = clock(room)
    players = _players(session, room.id)
    answers = _answers(session, room.id)
    me = next((p for p in players if p.student_id == student.id), None)

    item = None
    if status == ROOM_LIVE and index < room.question_count:
        my_answer = None
        if me is not None:
            my_answer = next(
                (a for a in answers if a.player_id == me.id and a.item_index == index),
                None,
            )
        item = _room_item(index, room.snapshot_items[index], my_answer, reveal=False)

    me_summary = None
    if me is not None:
        me_summary = next(
            s
            for s in _player_summaries(session, players, index, answers)
            if s.student_id == student.id
        )

    return PkRoomStudentView(
        room_id=room.id,
        room_code=room.room_code,
        status=status,
        mode=room.mode,
        team_count=room.team_count,
        question_count=room.question_count,
        per_question_seconds=room.per_question_seconds,
        current_item_index=index,
        remaining_seconds=remaining,
        item=item,
        me=me_summary,
        participants=len(players),
        teams=_team_summaries(room, players),
        result=_result(session, room, players, answers)
        if status == ROOM_ENDED
        else None,
    )
