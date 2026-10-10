"""学生练习计划：today 题单与逐题推进（next-question）。"""

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, Query
from sqlmodel import col, select

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
    _latest_done_attempts,
    _parse_snapshot_plan_items,
    _pick_questions,
    _plan_item_from_snapshot,
    _question_band_for_session,
    _repeat_attempts_from_snapshot,
    _repeat_sentences_of_passages,
    _resolve_active_daily_session,
    _scenario_for_topic,
    _snapshot_int,
    _snapshot_items_of,
    _snapshot_optional_int,
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
    Scenario,
    ScenarioQuestionPublic,
    SentenceFrame,
    SentenceFramePublic,
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


@router.get("/{code}/today", response_model=TodayPlan)
def read_today_plan(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    session_id: uuid.UUID | None = Query(default=None),
) -> Any:
    """今天的练习计划：3 句听后复述 + 2 道该档情景问答（US-05）。

    传 session_id 时返回该会话的计划（主题探索的自由练习轮）。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    today = _today_in_practice_tz()

    if session_id is not None:
        practice_session = session.get(PracticeSession, session_id)
        if practice_session is None or practice_session.student_id != student.id:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        # daily 当前轮：today / next-question / board 都用同一定位逻辑
        practice_session = _resolve_active_daily_session(
            session, classroom, student, today
        )

    # 快照优先：发布会话绑定的 exercise 始终作为题单来源（删题也从快照读）
    snapshot_items: list[dict[str, object]] | None = None
    bound_exercise: ClassroomExercise | None = None
    if practice_session.assignment_id is not None:
        bound_exercise = session.get(ClassroomExercise, practice_session.assignment_id)
        if bound_exercise is not None:
            snapshot_items = bound_exercise.snapshot_items

    # 模考生命周期：开考由学生在确认页显式触发（POST /exam/start），
    # today 只做到时惰性终结与状态透出（未开考不计时）
    exam_info = None
    if bound_exercise is not None and bound_exercise.is_exam:
        exam_service.finalize_if_expired(session, practice_session, bound_exercise)
        exam_info = exam_service.exam_status_payload(
            session, practice_session, bound_exercise
        )

    items: list[PlanItem] = []
    expected_items = 0
    exhausted = False
    band = practice_session.question_band or practice_session.band

    if snapshot_items is not None:
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
    else:
        # 非发布路径：单元指派或自主练习
        item_objects = exercise_service.resolve_assigned_items(session, classroom)
        if item_objects is not None and practice_session.mode == "daily":
            # 按题指派但未走快照（兼容旧路径，或尚未发布快照的旧课堂）
            item_passages, item_sentences, item_questions = item_objects
            reading_passages = item_passages
            sentences = item_sentences
            questions = item_questions
            # 按题指派时，题单由 assigned_items 决定，不再按题型勾选裁剪
            include_reading_build = bool(reading_passages)
        else:
            if (
                practice_session.mode == "explore"
                and practice_session.passage_id is not None
            ):
                passage = session.get(Passage, practice_session.passage_id)
                if passage is None:
                    raise HTTPException(status_code=404, detail="Passage not found")
                reading_passages = [passage]
            elif _assignment_unit(session, classroom) is not None:
                reading_passages = _assigned_active_passages(session, classroom)
                if practice_session.passage_id is None or not reading_passages:
                    raise HTTPException(
                        status_code=404,
                        detail="指派的单元还没有篇目，请联系老师",
                    )
            elif practice_session.passage_id is not None:
                passage = session.get(Passage, practice_session.passage_id)
                if passage is None:
                    raise HTTPException(status_code=404, detail="Passage not found")
                reading_passages = [passage]
            else:
                passage = _active_passage(session, student)
                reading_passages = [passage]

            include_reading = _include_type(classroom, "reading")
            include_repeat = _include_type(classroom, "repeat")
            include_qa = _include_type(classroom, "qa")
            sentences = []
            if include_repeat:
                sentences_by_passage = _repeat_sentences_of_passages(
                    session, reading_passages
                )
                for p in reading_passages:
                    sentences.extend(sentences_by_passage.get(p.id, []))
            questions = []
            exhausted = False
            if include_qa:
                # 用锚点篇目确定 topic 取情景题；主题未配情景时降级为无问答，
                # 不让整轮题单 404（朗读/复述照常）
                anchor = reading_passages[0]
                scenario = _scenario_for_topic(session, anchor.topic)
                band = _question_band_for_session(session, practice_session, student)
                if scenario is None:
                    exhausted = True
                else:
                    questions, exhausted = _pick_questions(
                        session, scenario, student.id, QUESTIONS_PER_ROUND
                    )
            include_reading_build = include_reading

        # 重听计数
        listen_counts: dict[uuid.UUID, int] = {}
        if sentences:
            listens = session.exec(
                select(ItemListen).where(
                    ItemListen.student_id == student.id,  # type: ignore[arg-type]
                    ItemListen.session_id == practice_session.id,  # type: ignore[arg-type]
                    col(ItemListen.item_id).in_([s.id for s in sentences]),
                )
            ).all()
            listen_counts = {ln.item_id: ln.count for ln in listens}

        if include_reading_build:
            # 拆句的篇目展开成逐句条目（与发布快照同一算法），未拆分保持整篇
            for p in reading_passages:
                for snapshot in reading.expand_reading_items(p):
                    item = _plan_item_from_snapshot(snapshot)
                    if item is not None:
                        items.append(item)
        items += [
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
        items += [
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
        expected_items = len(items)

    # 激励结算（幂等）：本轮全部终态时计算星/XP/连胜/徽章
    # expected_items 严格按本轮题单，额外换题/问答题不顶替必做题；
    # 题目说明无作答，不进必做集合
    required_ids = {it.id for it in items if it.type != AttemptItemType.INSTRUCTION}
    settle_session(
        session,
        practice_session,
        student,
        today,
        expected_items,
        required_item_ids=required_ids,
    )

    # 结算可能已写入 stars/xp 并 commit；刷新对象确保返回最新
    session.refresh(student)
    session.refresh(practice_session)

    attempts = _latest_done_attempts(session, student.id, practice_session.id)

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

    # 模考反馈遮罩（服务端口径）：考试终结前学生只能拿到作答状态回执，
    # 分数/转写/建议等反馈字段一律不下发——前端不显示不构成安全边界
    feedback_locked = exam_service.exam_feedback_locked(
        session, practice_session, bound_exercise
    )
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
            rubric=a.rubric if isinstance(a.rubric, dict) else None,
            error=a.error,
        )
        for a in attempts
    ]
    plan_attempts = [
        exam_service.masked_plan_attempt(pa) if feedback_locked else pa
        for pa in full_attempts
    ]

    badges = [
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
        for b in student_badges(session, student.id)
    ]

    assigned_unit = _assignment_unit(session, classroom)
    exercise = (
        session.get(ClassroomExercise, practice_session.assignment_id)
        if practice_session.assignment_id is not None
        else None
    )
    # 兼容旧版“课堂练习”默认标题：学生端继续看到单元/老师指派语义，
    # 教师显式填写的练习名称则优先展示。
    assigned_title = (
        exercise.title
        if exercise is not None and exercise.title != "课堂练习"
        else assigned_unit.title
        if assigned_unit
        else "老师指派"
        if (
            practice_session.assignment_id is not None
            or (item_objects is not None and session_id is None)
        )
        else None
    )
    return TodayPlan(
        session_id=practice_session.id,
        classroom_code=classroom.code,
        band=band,
        assigned_unit_title=assigned_title,
        items=items,
        attempts=plan_attempts,
        questions_exhausted=exhausted,
        exam=exam_info,
        gamification=GamificationInfo(
            xp=student.xp,
            streak_days=student.streak_days,
            session_stars=practice_session.stars,
            badges=badges,
        ),
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

    if session_id is not None:
        practice_session = session.get(PracticeSession, session_id)
        if practice_session is None or practice_session.student_id != student.id:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        practice_session = _resolve_active_daily_session(
            session, classroom, student, today
        )

    # 模考不允许换题（题单以发布快照为准）
    if practice_session.assignment_id is not None:
        bound = session.get(ClassroomExercise, practice_session.assignment_id)
        if bound is not None and bound.is_exam:
            raise HTTPException(status_code=422, detail="考试中不能换题")

    # 按题指派：换题语义 = 追加一道**计划外新题**（学生可再答，结算仍按原
    # 题单；换来的题经 attempt.item_snapshot 进结果页）。assigned_items 与
    # 发布快照同步：从指派问答题所在情景的题库取未做题，排掉已指派 + 本轮
    # 已做 + 前端传来的全部计划题（含发布全情景题时即用尽）。
    # 不再限制 session_id 为空：旧会话（已作答过的轮）同样换题，
    # ScenarioQuestionPublic 透传考试字段（题型/级别/话题卡/准备时间）。
    # 入口与排除集均以**旧会话绑定的练习**为准——老师清除指派后旧会话仍
    # 可换题；重新指派其他题也不会把旧会话的候选错误排除。情景口径同样
    # 优先绑定练习：重发另一主题后旧会话不漂移；绑定情景缺失/停用则明确
    # 禁止换题；仅绑定练习本身缺失（历史数据）才回退当前指派。
    if practice_session.assignment_id is not None or classroom.assigned_items:
        scenario = None
        assigned_question_ids: set[uuid.UUID] = set()
        bound_exercise = (
            session.get(ClassroomExercise, practice_session.assignment_id)
            if practice_session.assignment_id is not None
            else None
        )
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
            # 授权快照：换题返回的同时把该题**完整快照**（发布时刻内容，含
            # 考试字段）绑定到会话——提交与结果页读这份内容，老师此后改
            # 题干/话题卡或删题均不影响学生已看到的题目
            snapshot = exercise_service.build_snapshot_item(
                session, AttemptItemType.QUESTION, chosen.id
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

    # 快照优先：发布会话的换题列表来自快照（不需要活题；已指派题被排除后取快照剩余）
    if practice_session.assignment_id is not None:
        exercise = session.get(ClassroomExercise, practice_session.assignment_id)
        if exercise is not None:
            question_snapshots = _snapshot_items_of(
                exercise.snapshot_items, AttemptItemType.QUESTION
            )
            done_ids = {
                attempt.item_id
                for attempt in session.exec(
                    select(Attempt).where(
                        Attempt.session_id == practice_session.id,
                        Attempt.item_type == AttemptItemType.QUESTION,
                    )
                ).all()
            }
            excluded = set(exclude_ids or []) | done_ids
            # 换题优先换到「快照内其他未做题」（分级题型训练：老师选的题都
            # 是有效题，轮内换题不跳过其他未做题）；快照内取完再 exhausted，
            # 上层 assigned_items 回退分支会继续从情景题库补新题
            candidate = next(
                (
                    item
                    for item in question_snapshots
                    if uuid.UUID(str(item["id"])) not in excluded
                ),
                None,
            )
            if candidate is None:
                return NextQuestion(question=None, exhausted=True)
            cue_bullets = candidate.get("cue_card_bullets")
            return NextQuestion(
                question=ScenarioQuestionPublic(
                    id=uuid.UUID(str(candidate["id"])),
                    band=str(candidate.get("band") or "B1"),
                    text=str(candidate.get("text") or ""),
                    audio_url=(
                        str(candidate["audio_url"])
                        if candidate.get("audio_url") is not None
                        else None
                    ),
                    suggested_seconds=_snapshot_int(
                        candidate.get("suggested_seconds"), 20
                    ),
                    # 分级题型训练：换一题同样透传（话题卡/准备时间不丢）
                    exam_kind=(
                        str(candidate["exam_kind"])
                        if candidate.get("exam_kind") is not None
                        else None
                    ),
                    exam_level=(
                        str(candidate["exam_level"])
                        if candidate.get("exam_level") is not None
                        else None
                    ),
                    cue_card_bullets=(
                        [str(b) for b in cue_bullets]
                        if isinstance(cue_bullets, list) and cue_bullets
                        else None
                    ),
                    prep_seconds=_snapshot_optional_int(candidate.get("prep_seconds")),
                ),
                exhausted=False,
            )

    # 非发布会话：用锚点篇目确定情景，从题库取未做题
    if practice_session.passage_id is not None:
        passage = session.get(Passage, practice_session.passage_id)
    else:
        passage = _active_passage(session, student)
    if passage is None:
        return NextQuestion(question=None, exhausted=True)

    scenario = _scenario_for_topic(session, passage.topic)
    if scenario is None:
        # 主题未配情景：与「题库为空」同口径，优雅返回无题而非 404
        return NextQuestion(question=None, exhausted=True)
    questions, exhausted = _pick_questions(
        session, scenario, student.id, limit=999, fill_with_done=False
    )
    excluded = set(exclude_ids or [])
    candidates = [q for q in questions if q.id not in excluded]
    if not candidates:
        return NextQuestion(question=None, exhausted=exhausted)
    return NextQuestion(
        question=ScenarioQuestionPublic.model_validate(candidates[0]),
        exhausted=False,
    )
