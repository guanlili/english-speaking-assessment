"""学生练习计划：today 题单与逐题推进（next-question）。"""

import hashlib
import json
import logging
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, Query
from sqlmodel import Session, SQLModel, col, select

from app.api.deps import (
    SessionDep,
    StudentUserDep,
)
from app.api.routes.class_shared import (
    QUESTIONS_PER_ROUND,
    _active_passage,
    _assigned_active_passages,
    _assignment_unit,
    _get_classroom,
    _include_type,
    _latest_attempts_with_previous,
    _parse_snapshot_plan_items,
    _pick_questions,
    _plan_item_from_snapshot,
    _question_band_for_session,
    _repeat_attempts_from_snapshot,
    _repeat_sentences_of_passages,
    _resolve_active_daily_session,
    _resolve_homework_session,
    _scenario_for_topic,
    _snapshot_items_of,
    _student_profile_of,
    _today_in_practice_tz,
    router,
)
from app.models import (
    Attempt,
    AttemptItemType,
    BadgePublic,
    ClassroomExercise,
    GamificationInfo,
    InstructionAck,
    ItemListen,
    NextQuestion,
    Passage,
    PlanAttempt,
    PlanItem,
    PracticeSession,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    ScenarioQuestionPublic,
    SentenceFrame,
    SentenceFramePublic,
    Student,
    StudentFrameFavorite,
    TodayPlan,
)
from app.scoring.gamification import (
    BADGE_BY_KEY,
    settle_session,
    student_badges,
)
from app.services import exam as exam_service
from app.services import exercise as exercise_service
from app.services import reading

logger = logging.getLogger(__name__)


def _exercise_by_id(
    session: Session, exercise_id: uuid.UUID | None
) -> ClassroomExercise | None:
    """按 id 取练习；id 为空直接返回 None（session.get 不接受 None）。"""
    return (
        session.get(ClassroomExercise, exercise_id) if exercise_id is not None else None
    )


def _attempt_item_text(attempt: Attempt) -> str | None:
    """作答提交时的参考文本。自主练习回看不能改用后来编辑过的题库正文。"""
    snapshot = attempt.item_snapshot
    if isinstance(snapshot, dict):
        text = snapshot.get("text")
        if isinstance(text, str):
            return text
    return None


class ClassroomRevision(SQLModel):
    revision: str


@router.get("/{code}/revision", response_model=ClassroomRevision)
def read_classroom_revision(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
) -> ClassroomRevision:
    """只检查发布版本，不创建会话、不加载题目或返回考试反馈。"""
    classroom = _get_classroom(session, code)
    _student_profile_of(session, classroom, current_user)
    content = json.dumps(
        {
            "date": str(_today_in_practice_tz()),
            "exercise": str(classroom.current_exercise_id),
            "homework": str(classroom.homework_exercise_id),
            "unit": str(classroom.current_unit_id),
            "items": classroom.assigned_items,
            "types": [
                classroom.assign_reading,
                classroom.assign_repeat,
                classroom.assign_qa,
            ],
        },
        sort_keys=True,
    )
    return ClassroomRevision(revision=hashlib.sha256(content.encode()).hexdigest())


def _append_switched_items(
    items: list[PlanItem],
    attempts: list[Attempt],
    listen_counts: dict[uuid.UUID, int],
) -> None:
    """题单外的已作答项（换来的题）补进题单，保证刷新后仍可见。"""
    # 追加换题作答：题单外的已作答项（换来的题）补进题单，保证刷新后仍可见、
    # 结果页能展示（来源 attempt.item_snapshot，不依赖活题库）。
    # 不纳入结算必做（required_ids 已在 settle 前固定）。
    plan_item_ids = {item.id for item in items}
    for a in attempts:
        if a.item_id in plan_item_ids:
            continue
        snapshot_item = a.item_snapshot if isinstance(a.item_snapshot, dict) else None
        extra = (
            _plan_item_from_snapshot(snapshot_item, listen_counts)
            if snapshot_item is not None
            else None
        )
        if extra is not None:
            items.append(extra)
            plan_item_ids.add(a.item_id)


def _inject_exam_frames(
    session: Session,
    student: Student,
    items: list[PlanItem],
) -> None:
    """分级题型训练：为考试题按难度/题型注入可替换句型（仅展示层）。"""
    # 分级题型训练：为考试题注入可替换句型（按题目实际难度与题型匹配；
    # 通用句型 exam_kind 为空也推荐）。仅展示层注入，不进作答快照。
    exam_plan_items = [item for item in items if item.exam_kind]
    if exam_plan_items:
        all_frames = session.exec(
            select(SentenceFrame).where(SentenceFrame.status == "active")
        ).all()
        favorite_ids = set(
            session.exec(
                select(StudentFrameFavorite.frame_id).where(
                    StudentFrameFavorite.student_id == student.id  # type: ignore[arg-type]
                )
            ).all()
        )
        for item in exam_plan_items:
            matched = [
                frame
                for frame in all_frames
                if frame.level == item.exam_level
                and frame.exam_kind in (None, item.exam_kind)
            ]
            item.frames = [
                SentenceFramePublic(
                    id=frame.id,
                    level=frame.level,
                    purpose=frame.purpose,
                    exam_kind=frame.exam_kind,
                    text_en=frame.text_en,
                    text_zh=frame.text_zh,
                    favorited=frame.id in favorite_ids,
                )
                for frame in matched[:6]
            ]


def _build_plan_attempts(
    attempts: list[Attempt],
    previous_map: dict[uuid.UUID, Any],
    feedback_locked: bool,
) -> list[PlanAttempt]:
    """作答行 → 计划返回体；考试反馈遮罩期间只回执状态。"""
    # 模考反馈遮罩（服务端口径）：考试终结前学生只能拿到作答状态回执，
    # 分数/转写/建议等反馈字段一律不下发——前端不显示不构成安全边界
    full_attempts = [
        PlanAttempt(
            item_id=a.item_id,
            attempt_id=a.id,
            status=a.status,
            overall=a.overall,
            completeness=a.completeness,
            fluency=a.fluency,
            transcript=a.transcript,
            advice=a.advice,
            vocab=a.vocab if isinstance(a.vocab, dict) else None,
            word_alignment=(
                a.word_alignment if isinstance(a.word_alignment, dict) else None
            ),
            rubric=a.rubric if isinstance(a.rubric, dict) else None,
            error=a.error,
            item_text=_attempt_item_text(a),
            teacher_review_tags=a.teacher_review_tags,
            previous=previous_map.get(a.item_id),
            teacher_feedback=a.teacher_feedback,
            teacher_focus=a.teacher_focus,
            teacher_feedback_author=a.teacher_feedback_author,
            teacher_feedback_at=a.teacher_feedback_at,
        )
        for a in attempts
    ]
    return [
        exam_service.masked_plan_attempt(pa) if feedback_locked else pa
        for pa in full_attempts
    ]


def _plan_items_from_snapshot(
    session: Session,
    student: Student,
    practice_session: PracticeSession,
    snapshot_items: list[dict[str, object]],
    band: str,
) -> tuple[list[PlanItem], int, str, dict[uuid.UUID, int]]:
    """发布快照路径：题单、档位升降、重听与说明确认都按快照里的 ID 查。

    返回 (题单, 结算必做数, 档位, 重听计数)。
    """
    snap_passages, snap_repeats, snap_questions = _parse_snapshot_plan_items(
        snapshot_items
    )
    snapshot_repeat_ids = [uuid.UUID(str(r["id"])) for r in snap_repeats]

    # 重听计数（按快照中的复述句 ID 查）
    listen_counts: dict[uuid.UUID, int] = {}
    if snapshot_repeat_ids:
        listens = session.exec(
            select(ItemListen).where(
                ItemListen.student_id == student.id,  # type: ignore[arg-type]
                ItemListen.session_id == practice_session.id,  # type: ignore[arg-type]
                col(ItemListen.item_id).in_(snapshot_repeat_ids),  # type: ignore[operator]
            )
        ).all()
        listen_counts = {ln.item_id: ln.count for ln in listens}

    # 升降档：用快照中复述句的作答判断，不要求复述句仍存在
    if snap_repeats and practice_session.question_band is None:
        done_repeats = _repeat_attempts_from_snapshot(
            session, practice_session, snapshot_repeat_ids
        )
        band = _question_band_for_session(
            session,
            practice_session,
            student,
            repeat_count_override=len(snap_repeats),
            done_repeat_override=done_repeats,
        )

    # 题目说明的「继续」确认时间（按快照中的说明 ID 查本会话 ack）
    instruction_ids = [
        uuid.UUID(str(it["id"]))
        for it in snapshot_items
        if str(it.get("type", "")) == AttemptItemType.INSTRUCTION and it.get("id")
    ]
    ack_times: dict[uuid.UUID, datetime] = {}
    if instruction_ids:
        acks = session.exec(
            select(InstructionAck).where(
                InstructionAck.student_id == student.id,  # type: ignore[arg-type]
                InstructionAck.session_id == practice_session.id,  # type: ignore[arg-type]
                col(InstructionAck.item_id).in_(instruction_ids),  # type: ignore[operator]
            )
        ).all()
        ack_times = {ack.item_id: ack.created_at for ack in acks if ack.created_at}

    items = [
        item
        for item in (
            _plan_item_from_snapshot(snapshot_item, listen_counts, ack_times)
            for snapshot_item in snapshot_items
        )
        if item is not None
    ]
    # 结算必做数 = 实际可用题单（快照条目可能因缺 id/文本被过滤）；
    # 题目说明无作答，不进结算分母
    expected_items = len(
        [item for item in items if item.type != AttemptItemType.INSTRUCTION]
    )
    return items, expected_items, band, listen_counts


def _plan_items_dynamic(
    session: Session,
    classroom: Any,
    student: Student,
    practice_session: PracticeSession,
    band: str,
) -> tuple[list[PlanItem], int, bool, str, dict[uuid.UUID, int], Any]:
    """非发布路径：单元指派或自主练习重建题单。

    返回 (题单, 结算必做数, 是否无题可练, 档位, 重听计数, 指派题目)。
    """
    # 非快照分支才有指派题目对象
    item_objects = exercise_service.resolve_assigned_items(session, classroom)
    if item_objects is not None and practice_session.mode == "daily":
        # 按题指派但未走快照（兼容旧路径，或尚未发布快照的旧课堂）
        reading_passages, sentences, questions = item_objects
        # 按题指派时，题单由 assigned_items 决定，不再按题型勾选裁剪
        include_reading = bool(reading_passages)
        exhausted = False
    else:
        reading_passages, sentences, questions, band, exhausted = (
            _rebuild_dynamic_sources(
                session, classroom, student, practice_session, band
            )
        )
        include_reading = _include_type(classroom, "reading")

    listen_counts = _dynamic_listen_counts(
        session, student, practice_session, sentences
    )

    items: list[PlanItem] = []
    if include_reading:
        items.extend(_reading_plan_items(reading_passages))
    items.extend(_repeat_plan_items(sentences, listen_counts))
    items.extend(_question_plan_items(questions))
    return items, len(items), exhausted, band, listen_counts, item_objects


def _get_passage_or_404(session: Session, passage_id: uuid.UUID) -> Passage:
    passage = session.get(Passage, passage_id)
    if passage is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    return passage


def _dynamic_reading_passages(
    session: Session,
    classroom: Any,
    student: Student,
    practice_session: PracticeSession,
) -> list[Passage]:
    """自主练习 / 单元指派路径下本轮要读的篇目。"""
    if practice_session.mode == "explore" and practice_session.passage_id is not None:
        return [_get_passage_or_404(session, practice_session.passage_id)]
    if _assignment_unit(session, classroom) is not None:
        reading_passages = _assigned_active_passages(session, classroom)
        if practice_session.passage_id is None or not reading_passages:
            raise HTTPException(
                status_code=404,
                detail="指派的单元还没有篇目，请联系老师",
            )
        return reading_passages
    if practice_session.passage_id is not None:
        return [_get_passage_or_404(session, practice_session.passage_id)]
    return [_active_passage(session, student)]


def _dynamic_repeat_sentences(
    session: Session, classroom: Any, reading_passages: list[Passage]
) -> list[RepeatSentence]:
    """按「复述」勾选取这些篇目的复述句，按篇目顺序拼接。"""
    if not _include_type(classroom, "repeat"):
        return []
    sentences_by_passage = _repeat_sentences_of_passages(session, reading_passages)
    sentences: list[RepeatSentence] = []
    for p in reading_passages:
        sentences.extend(sentences_by_passage.get(p.id, []))
    return sentences


def _dynamic_questions(
    session: Session,
    classroom: Any,
    student: Student,
    practice_session: PracticeSession,
    reading_passages: list[Passage],
    band: str,
) -> tuple[list[ScenarioQuestion], str, bool]:
    """按「问答」勾选取情景题；主题未配情景时降级为无问答并标记无题可练。"""
    if not _include_type(classroom, "qa"):
        return [], band, False
    # 用锚点篇目确定 topic 取情景题；主题未配情景时降级为无问答，
    # 不让整轮题单 404（朗读/复述照常）
    anchor = reading_passages[0]
    scenario = _scenario_for_topic(session, anchor.topic, anchor.tenant_id)
    band = _question_band_for_session(session, practice_session, student)
    if scenario is None:
        return [], band, True
    questions, exhausted = _pick_questions(
        session, scenario, student.id, QUESTIONS_PER_ROUND
    )
    return questions, band, exhausted


def _rebuild_dynamic_sources(
    session: Session,
    classroom: Any,
    student: Student,
    practice_session: PracticeSession,
    band: str,
) -> tuple[list[Passage], list[RepeatSentence], list[ScenarioQuestion], str, bool]:
    """单元指派 / 自主练习：重建篇目、复述句、情景题，并回传可能升降的档位。"""
    reading_passages = _dynamic_reading_passages(
        session, classroom, student, practice_session
    )
    sentences = _dynamic_repeat_sentences(session, classroom, reading_passages)
    questions, band, exhausted = _dynamic_questions(
        session, classroom, student, practice_session, reading_passages, band
    )
    return reading_passages, sentences, questions, band, exhausted


def _dynamic_listen_counts(
    session: Session,
    student: Student,
    practice_session: PracticeSession,
    sentences: list[RepeatSentence],
) -> dict[uuid.UUID, int]:
    """本轮这些复述句的重听次数（无复述句时不发查询）。"""
    if not sentences:
        return {}
    listens = session.exec(
        select(ItemListen).where(
            ItemListen.student_id == student.id,  # type: ignore[arg-type]
            ItemListen.session_id == practice_session.id,  # type: ignore[arg-type]
            col(ItemListen.item_id).in_([s.id for s in sentences]),
        )
    ).all()
    return {ln.item_id: ln.count for ln in listens}


def _reading_plan_items(reading_passages: list[Passage]) -> list[PlanItem]:
    """拆句的篇目展开成逐句条目（与发布快照同一算法），未拆分保持整篇。"""
    items: list[PlanItem] = []
    for p in reading_passages:
        for snapshot in reading.expand_reading_items(p):
            item = _plan_item_from_snapshot(snapshot)
            if item is not None:
                items.append(item)
    return items


def _repeat_plan_items(
    sentences: list[RepeatSentence], listen_counts: dict[uuid.UUID, int]
) -> list[PlanItem]:
    return [
        PlanItem(
            type=AttemptItemType.REPEAT,
            id=s.id,
            text=s.text,
            translation=s.translation,
            audio_url=s.audio_url,
            suggested_seconds=s.suggested_seconds,
            replay_limit=s.replay_limit,
            listen_used=listen_counts.get(s.id, 0),
            exam_kind=s.exam_kind,
            exam_level=s.exam_level,
        )
        for s in sentences
    ]


def _question_plan_items(questions: list[ScenarioQuestion]) -> list[PlanItem]:
    return [
        PlanItem(
            type=AttemptItemType.QUESTION,
            id=q.id,
            text=q.text,
            translation=q.translation,
            audio_url=q.audio_url,
            suggested_seconds=q.suggested_seconds,
            exam_kind=q.exam_kind,
            exam_level=q.exam_level,
            cue_card_bullets=q.cue_card_bullets,
            prep_seconds=q.prep_seconds,
        )
        for q in questions
    ]


def _resolve_plan_items(
    session: Session,
    classroom: Any,
    student: Student,
    practice_session: PracticeSession,
    snapshot_items: list[dict[str, object]] | None,
) -> tuple[list[PlanItem], int, bool, str, dict[uuid.UUID, int], Any]:
    """解析本轮题单：发布快照优先，其次按题指派，最后单元/自主路径。

    返回 (题单, 结算必做数, 是否无题可练, 档位, 重听计数, 指派题目)。
    """
    band = practice_session.question_band or practice_session.band
    if snapshot_items is not None:
        items, expected_items, band, listen_counts = _plan_items_from_snapshot(
            session, student, practice_session, snapshot_items, band
        )
        return items, expected_items, False, band, listen_counts, None
    return _plan_items_dynamic(session, classroom, student, practice_session, band)


def _open_practice_session(
    session: Session,
    classroom: Any,
    student: Student,
    today: Any,
    session_id: uuid.UUID | None,
    *,
    slot: str = "class",
) -> PracticeSession:
    """定位会话：显式 session_id 优先，其次作业槽，最后当日活动 daily 轮。"""
    if session_id is not None:
        practice_session = session.get(PracticeSession, session_id)
        if practice_session is None or practice_session.student_id != student.id:
            raise HTTPException(status_code=404, detail="Session not found")
        return practice_session
    if slot == "homework":
        return _resolve_homework_session(session, classroom, student, today)
    # daily 当前轮：today / next-question / board 都用同一定位逻辑
    return _resolve_active_daily_session(session, classroom, student, today)


def _load_plan_snapshot(
    session: Session, practice_session: PracticeSession
) -> tuple[list[dict[str, object]] | None, ClassroomExercise | None]:
    """快照优先：发布会话绑定的 exercise 始终作为题单来源（删题也从快照读）。"""
    bound_exercise: ClassroomExercise | None = None
    snapshot_items: list[dict[str, object]] | None = None
    if practice_session.assignment_id is not None:
        bound_exercise = session.get(ClassroomExercise, practice_session.assignment_id)
        if bound_exercise is not None:
            snapshot_items = bound_exercise.snapshot_items
    return snapshot_items, bound_exercise


def _exam_lifecycle_info(
    session: Session,
    practice_session: PracticeSession,
    bound_exercise: ClassroomExercise | None,
) -> Any:
    """模考生命周期：开考由学生显式触发，today 只做到时惰性终结与状态透出。"""
    if bound_exercise is None or not bound_exercise.is_exam:
        return None
    exam_service.finalize_if_expired(session, practice_session, bound_exercise)
    return exam_service.exam_status_payload(session, practice_session, bound_exercise)


def _badge_publics(rows: Any) -> list[BadgePublic]:
    """徽章行 → 对外结构（未知 key 直接透出原始 key）。"""
    return [
        BadgePublic(
            key=b.badge_key,
            label=BADGE_BY_KEY[b.badge_key].label
            if b.badge_key in BADGE_BY_KEY
            else b.badge_key,
            description=BADGE_BY_KEY[b.badge_key].description
            if b.badge_key in BADGE_BY_KEY
            else "",
            awarded_at=b.awarded_at,
        )
        for b in rows
    ]


def _assigned_title(
    exercise: ClassroomExercise | None,
    assigned_unit: Any,
    practice_session: PracticeSession,
    item_objects: Any,
    session_id: uuid.UUID | None,
) -> str | None:
    """标题口径：教师显式命名的练习 > 单元名 > 老师指派 > 无。

    兼容旧版“课堂练习”默认标题：学生端继续看到单元/老师指派语义，
    教师显式填写的练习名称则优先展示。
    """
    if exercise is not None and exercise.title != "课堂练习":
        return exercise.title
    if assigned_unit:
        return assigned_unit.title
    if practice_session.assignment_id is not None or (
        item_objects is not None and session_id is None
    ):
        return "老师指派"
    return None


def _open_todays_session(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    session_id: uuid.UUID | None,
    slot: str,
) -> tuple[Any, Student, date, PracticeSession]:
    """定位今天的练习会话：显式 session_id 优先，其次作业槽，最后当日 daily 轮。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    today = _today_in_practice_tz()
    practice_session = _open_practice_session(
        session, classroom, student, today, session_id, slot=slot
    )
    return classroom, student, today, practice_session


def _plan_assignment_meta(
    session: SessionDep,
    classroom: Any,
    practice_session: PracticeSession,
    item_objects: Any,
    session_id: uuid.UUID | None,
) -> tuple[str | None, ClassroomExercise | None]:
    """作业相关元信息：本轮指派标题 + 班级作业练习（未设作业时为 None）。"""
    exercise = _exercise_by_id(session, practice_session.assignment_id)
    assigned_title = _assigned_title(
        exercise,
        _assignment_unit(session, classroom),
        practice_session,
        item_objects,
        session_id,
    )
    homework = _exercise_by_id(session, classroom.homework_exercise_id)
    return assigned_title, homework


def _resolve_and_settle(
    session: SessionDep,
    classroom: Any,
    student: Student,
    practice_session: PracticeSession,
    snapshot_items: list[dict[str, object]] | None,
    today: date,
    feedback_locked: bool,
) -> tuple[list[PlanItem], int, bool, str, dict[uuid.UUID, int], Any]:
    """解析本轮题单，并在考试反馈可见时结算星/XP/连胜/徽章。

    结算幂等：本轮全部终态才落库。考试反馈遮罩期间跳过——结算产物
    （stars/XP）会绕过 attempts 遮罩提前泄露分数档；考试终结后下一次
    /today 自然补结算。expected_items 严格按本轮题单，额外换题/问答题
    不顶替必做题；题目说明无作答，不进必做集合。
    """
    items, expected_items, exhausted, band, listen_counts, item_objects = (
        _resolve_plan_items(
            session, classroom, student, practice_session, snapshot_items
        )
    )
    required_ids = {it.id for it in items if it.type != AttemptItemType.INSTRUCTION}
    if not feedback_locked:
        settle_session(
            session,
            practice_session,
            student,
            today,
            expected_items,
            required_item_ids=required_ids,
        )
    return items, expected_items, exhausted, band, listen_counts, item_objects


def _plan_progress_view(
    session: SessionDep,
    student: Student,
    practice_session: PracticeSession,
    items: list[PlanItem],
    listen_counts: dict[uuid.UUID, int],
    feedback_locked: bool,
) -> tuple[list[PlanAttempt], list[BadgePublic]]:
    """结算后刷新对象，组装本轮作答视图（含换题追加与模考帧）与徽章。"""
    # 结算可能已写入 stars/xp 并 commit；刷新对象确保返回最新
    session.refresh(student)
    session.refresh(practice_session)
    attempts, previous_map = _latest_attempts_with_previous(
        session, student.id, practice_session.id
    )
    _append_switched_items(items, attempts, listen_counts)
    _inject_exam_frames(session, student, items)
    plan_attempts = _build_plan_attempts(attempts, previous_map, feedback_locked)
    badges = _badge_publics(student_badges(session, student.id))
    return plan_attempts, badges


def _today_plan_response(
    *,
    practice_session: PracticeSession,
    classroom: Any,
    band: str,
    assigned_title: str | None,
    items: list[PlanItem],
    plan_attempts: list[PlanAttempt],
    exhausted: bool,
    exam_info: Any,
    homework: ClassroomExercise | None,
    feedback_locked: bool,
    student: Student,
    badges: list[BadgePublic],
) -> TodayPlan:
    """today 响应装配：字段顺序与 TodayPlan 声明一致。"""
    return TodayPlan(
        session_id=practice_session.id,
        classroom_code=classroom.code,
        band=band,
        assigned_unit_title=assigned_title,
        items=items,
        attempts=plan_attempts,
        questions_exhausted=exhausted or practice_session.mode == "followup",
        exam=exam_info,
        homework_title=homework.title if homework is not None else None,
        homework_exercise_id=homework.id if homework is not None else None,
        gamification=GamificationInfo(
            xp=student.xp,
            streak_days=student.streak_days,
            # 纵深防御：结算已按 feedback_locked 跳过，这里再遮一层——
            # 任何路径提前写下的 stars 都不得在考试终结前下发分数档
            session_stars=(None if feedback_locked else practice_session.stars),
            badges=badges,
        ),
    )


@router.get("/{code}/today", response_model=TodayPlan)
def read_today_plan(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    session_id: uuid.UUID | None = Query(default=None),
    slot: str = Query(default="class"),
) -> Any:
    """今天的练习计划：3 句听后复述 + 2 道该档情景问答（US-05）。

    传 session_id 时返回该会话的计划（主题探索的自由练习轮）。
    """
    classroom, student, today, practice_session = _open_todays_session(
        session, code, current_user, session_id, slot
    )
    snapshot_items, bound_exercise = _load_plan_snapshot(session, practice_session)
    exam_info = _exam_lifecycle_info(session, practice_session, bound_exercise)
    # 反馈遮罩判定提前：考试终结前跳过激励结算——settle 会按分数落
    # stars/XP，GamificationInfo 直出 practice_session.stars 会把分数档
    # （≥85→3 星）提前泄露给考生本人，XP 同步跳变（2026-10-12 评审）
    feedback_locked = exam_service.exam_feedback_locked(
        session, practice_session, bound_exercise
    )

    (
        items,
        expected_items,
        exhausted,
        band,
        listen_counts,
        item_objects,
    ) = _resolve_and_settle(
        session,
        classroom,
        student,
        practice_session,
        snapshot_items,
        today,
        feedback_locked,
    )

    plan_attempts, badges = _plan_progress_view(
        session, student, practice_session, items, listen_counts, feedback_locked
    )

    assigned_title, homework = _plan_assignment_meta(
        session, classroom, practice_session, item_objects, session_id
    )
    return _today_plan_response(
        practice_session=practice_session,
        classroom=classroom,
        band=band,
        assigned_title=assigned_title,
        items=items,
        plan_attempts=plan_attempts,
        exhausted=exhausted,
        exam_info=exam_info,
        homework=homework,
        feedback_locked=feedback_locked,
        student=student,
        badges=badges,
    )


def _next_question_from_assigned(
    session: Session,
    classroom: Any,
    student: Student,
    practice_session: PracticeSession,
    exclude_id_set: set[uuid.UUID],
) -> NextQuestion:
    """按题指派/已指派集合：追加一道计划外新题；无候选则返回用尽。

    换题语义 = 追加一道**计划外新题**（学生可再答，结算仍按原题单；
    换来的题经 attempt.item_snapshot 进结果页）。assigned_items 与发布快照
    同步：从指派问答题所在情景的题库取未做题，排掉已指派 + 本轮已做 +
    前端传来的全部计划题（含发布全情景题时即用尽）。
    """
    scenario = None
    assigned_question_ids: set[uuid.UUID] = set()
    bound_exercise = _exercise_by_id(session, practice_session.assignment_id)
    if bound_exercise is not None:
        for item in _snapshot_items_of(
            bound_exercise.snapshot_items, AttemptItemType.QUESTION
        ):
            assigned_question_ids.add(uuid.UUID(str(item.get("id"))))
            if scenario is None:
                scenario = session.get(
                    Scenario, uuid.UUID(str(item.get("scenario_id")))
                )
    # 绑定练习存在：情景缺失（被删）或停用都明确禁止换题——不漂移到
    # 重发后的新主题
    if scenario is None or not scenario.is_active:
        if bound_exercise is not None:
            return NextQuestion(question=None, exhausted=True)
        item_objects = exercise_service.resolve_assigned_items(session, classroom)
        if item_objects is not None:
            _, _, item_questions = item_objects
            for q in item_questions:
                assigned_question_ids.add(q.id)
                if scenario is None:
                    scenario = session.get(Scenario, q.scenario_id)
            if scenario is None or not scenario.is_active:
                return NextQuestion(question=None, exhausted=True)
    assert scenario is not None  # 上方两个分支已保证非空

    done_ids = {
        attempt.item_id
        for attempt in session.exec(
            select(Attempt).where(
                Attempt.session_id == practice_session.id,
                Attempt.item_type == AttemptItemType.QUESTION,
            )
        ).all()
    }
    questions, exhausted = _pick_questions(
        session,
        scenario,
        student.id,
        limit=999,
        fill_with_done=False,
    )
    excluded = exclude_id_set | done_ids | assigned_question_ids
    candidates = [q for q in questions if q.id not in excluded]
    if candidates:
        chosen = candidates[0]
        # 授权快照：换题返回的同时把该题**完整快照**（发布时刻内容，含考试
        # 字段）绑定到会话——提交与结果页读这份内容，老师此后改题干/话题卡
        # 或删题均不影响学生已看到的题目
        snapshot = exercise_service.build_snapshot_item(
            session, AttemptItemType.QUESTION, chosen.id, student.tenant_id
        )
        # 行级锁后追加：并发连点换一题不会互相覆盖丢授权
        locked_session = session.exec(
            select(PracticeSession)
            .where(PracticeSession.id == practice_session.id)
            .with_for_update()
        ).one()
        exchanged = list(locked_session.exchanged_items or [])
        if not any(item.get("id") == snapshot["id"] for item in exchanged):
            locked_session.exchanged_items = exchanged + [snapshot]
            session.add(locked_session)
            session.commit()
        return NextQuestion(
            question=ScenarioQuestionPublic.model_validate(chosen),
            exhausted=False,
        )
    return NextQuestion(question=None, exhausted=exhausted)


def _next_question_from_passage(
    session: Session,
    student: Student,
    practice_session: PracticeSession,
    exclude_id_set: set[uuid.UUID],
) -> NextQuestion:
    """非发布会话：用锚点篇目确定情景，从题库取未做题。"""
    if practice_session.passage_id is not None:
        passage = session.get(Passage, practice_session.passage_id)
    else:
        passage = _active_passage(session, student)
    if passage is None:
        return NextQuestion(question=None, exhausted=True)

    scenario = _scenario_for_topic(session, passage.topic, passage.tenant_id)
    if scenario is None:
        # 主题未配情景：与「题库为空」同口径，优雅返回无题而非 404
        return NextQuestion(question=None, exhausted=True)
    questions, exhausted = _pick_questions(
        session, scenario, student.id, limit=999, fill_with_done=False
    )
    candidates = [q for q in questions if q.id not in exclude_id_set]
    if not candidates:
        return NextQuestion(question=None, exhausted=exhausted)
    return NextQuestion(
        question=ScenarioQuestionPublic.model_validate(candidates[0]),
        exhausted=False,
    )


@router.get("/{code}/next-question", response_model=NextQuestion)
def read_next_question(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    session_id: uuid.UUID | None = Query(default=None),
    exclude_ids: list[uuid.UUID] | None = Query(default=None),
) -> Any:
    """换一题：同主题、未做过的问题（US-06）。用尽时 exhausted=true。

    传 session_id 时使用该会话（explore / 回看旧轮）；否则用当日当前活动会话。
    """
    exclude_id_set = set(exclude_ids or [])
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    today = _today_in_practice_tz()
    practice_session = _open_practice_session(
        session, classroom, student, today, session_id
    )

    # 模考不允许换题（题单以发布快照为准）
    if practice_session.assignment_id is not None:
        bound = session.get(ClassroomExercise, practice_session.assignment_id)
        if bound is not None and bound.is_exam:
            raise HTTPException(status_code=422, detail="考试中不能换题")

    if practice_session.mode == "followup":
        raise HTTPException(422, detail="Followup question exchange not allowed")
    # 不再限制 session_id 为空：旧会话（已作答过的轮）同样换题，
    # ScenarioQuestionPublic 透传考试字段（题型/级别/话题卡/准备时间）。
    # 入口与排除集均以**旧会话绑定的练习**为准——老师清除指派后旧会话仍
    # 可换题；重新指派其他题也不会把旧会话的候选错误排除。情景口径同样
    # 优先绑定练习：重发另一主题后旧会话不漂移；绑定情景缺失/停用则明确
    # 禁止换题；仅绑定练习本身缺失（历史数据）才回退当前指派。
    if practice_session.assignment_id is not None or classroom.assigned_items:
        return _next_question_from_assigned(
            session, classroom, student, practice_session, exclude_id_set
        )
    # 非发布会话：用锚点篇目确定情景，从题库取未做题
    return _next_question_from_passage(
        session, student, practice_session, exclude_id_set
    )
