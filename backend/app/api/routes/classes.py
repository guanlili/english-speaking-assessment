"""课堂与学生练习接口（PRD 附录 A 的 2 周形态，公开、无登录）。

POST /classes                      创建课堂（管理员），返回课堂码
POST /classes/{code}/join          显示名进入，返回 student_id（US-04）
GET  /classes/{code}/today         今天的 3 句复述 + 2 道该档问答（US-05）
GET  /classes/{code}/next-question 同主题同档下一题（US-06 换一题）
GET  /classes/{code}/board         老师名单表（谁交了/每题分数/音频）
"""

import logging
import secrets
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    StudentUserDep,
    TeacherUserDep,
)
from app.core.config import settings
from app.crud import (
    create_classroom,
    get_classroom_by_code,
    get_or_create_today_session,
    get_student,
    join_classroom,
)
from app.models import (
    AssignmentInfo,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    BadgePublic,
    BoardData,
    BoardItem,
    BoardStudent,
    Classroom,
    ClassroomCreate,
    ClassroomExercise,
    ClassroomExercisePublic,
    ClassroomPublic,
    GamificationInfo,
    ItemListen,
    LearningPath,
    NextQuestion,
    Passage,
    PathUnit,
    PlanAttempt,
    PlanItem,
    PracticeSession,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    ScenarioQuestionPublic,
    Student,
    StudentJoin,
    StudentPublic,
    TodayPlan,
    TrailData,
    TrailSession,
    Unit,
    User,
    get_datetime_utc,
)
from app.scoring.bands import BAND_ORDER, adjust_band
from app.scoring.gamification import (
    BADGE_BY_KEY,
    settle_session,
    student_badges,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classes", tags=["classes"])

# 课堂码字母表去掉易混字符（0/O/1/I）
CLASSROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CLASSROOM_CODE_LENGTH = 6
QUESTIONS_PER_ROUND = 2


class _BoardRef:
    """让已发布快照可以复用名单表的题位渲染逻辑。"""

    def __init__(self, item_id: uuid.UUID) -> None:
        self.id = item_id


def _today_in_practice_tz() -> date:
    """练习日按配置时区取日期（教室在中国，UTC 会在早八点切日）。"""
    from datetime import datetime

    return datetime.now(ZoneInfo(settings.PRACTICE_TZ)).date()


def _generate_classroom_code() -> str:
    return "".join(
        secrets.choice(CLASSROOM_CODE_ALPHABET) for _ in range(CLASSROOM_CODE_LENGTH)
    )


def _assignment_unit(session: Any, classroom: Classroom) -> Unit | None:
    """老师指派的当前单元（教学工具定位：全班同步）。"""
    if classroom.current_unit_id is None:
        return None
    unit = session.get(Unit, classroom.current_unit_id)
    if unit is None or not unit.is_active:
        return None
    return unit


def _assigned_active_passages(session: Any, classroom: Classroom) -> list[Passage]:
    """指派单元的全部启用篇目（按创建顺序）：长文可拆多篇，各自成为一道朗读题。

    第一篇是「锚点」：承担会话归属与问答主题（拆分场景下同组各篇同主题）。
    """
    assigned = _assignment_unit(session, classroom)
    if assigned is None:
        return []
    return list(
        session.exec(
            select(Passage)
            .where(Passage.unit_id == assigned.id, Passage.is_active)
            .order_by(col(Passage.created_at))
        ).all()
    )


def _active_passage(session: Any, student: Student | None = None) -> Passage:
    """课堂练习篇目（优先级）：老师指派单元 > 学生路径 > 全局第一篇。"""
    units = session.exec(
        select(Unit).where(Unit.is_active).order_by(col(Unit.order_index))
    ).all()
    if student is not None:
        classroom = session.get(Classroom, student.classroom_id)
        if classroom is not None:
            assigned = _assignment_unit(session, classroom)
            if assigned is not None:
                assigned_passages = _assigned_active_passages(session, classroom)
                if assigned_passages:
                    return assigned_passages[0]
                raise HTTPException(
                    status_code=404,
                    detail=f"指派的单元「{assigned.title}」还没有篇目，请联系老师",
                )
    if not units or student is None:
        passage = session.exec(
            select(Passage)
            .where(Passage.is_active)
            .order_by(col(Passage.created_at))
            .limit(1)
        ).first()
        if passage is None:
            raise HTTPException(status_code=404, detail="No active passage")
        return passage

    classroom = session.get(Classroom, student.classroom_id)
    unlock_all = bool(classroom and classroom.unlock_all)
    # 各单元完成轮数（按 session.passage → unit 聚合已结算轮）
    settled = session.exec(
        select(PracticeSession).where(
            PracticeSession.student_id == student.id,
            col(PracticeSession.stars).is_not(None),
            col(PracticeSession.passage_id).is_not(None),
        )
    ).all()
    passage_ids = {ps.passage_id for ps in settled if ps.passage_id}
    passages = session.exec(select(Passage)).all()
    unit_done: dict = {}
    for passage in passages:
        if passage.unit_id is not None and passage.id in passage_ids:
            unit_done[passage.unit_id] = True

    chosen: Unit | None = None
    if not unlock_all:
        # 第一个未完成的激活单元
        for unit in units:
            if not unit_done.get(unit.id):
                chosen = unit
                break
    if chosen is None:
        chosen = units[-1]  # 全部完成（或全开）→ 复练最后单元

    passage = next(
        (p for p in passages if p.unit_id == chosen.id and p.is_active),
        None,
    )
    if passage is None:
        raise HTTPException(status_code=404, detail="No active passage")
    return passage


def _scenario_for_topic(session: Any, topic: str) -> Scenario:
    scenario = session.exec(select(Scenario).where(Scenario.topic == topic)).first()
    if scenario is None:
        raise HTTPException(status_code=404, detail="No scenario configured")
    return scenario


def _get_classroom(session: SessionDep, code: str) -> Classroom:
    classroom = get_classroom_by_code(session=session, code=code.upper())
    if classroom is None or not classroom.is_active:
        raise HTTPException(status_code=404, detail="Classroom not found")
    return classroom


def _get_student_of_classroom(
    session: SessionDep, classroom: Classroom, student_id: uuid.UUID
) -> Student:
    student = get_student(session=session, student_id=student_id)
    if student is None or student.classroom_id != classroom.id:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def _student_profile_of(
    session: SessionDep, classroom: Classroom, current_user: User
) -> Student:
    """学生登录档案解析：JWT → user → 该课堂的学生档案（未入班 404）。

    404 统一口径：学生档案不存在 = 未加入该课堂，前端引导去加入页。
    """
    student = session.exec(
        select(Student).where(
            Student.classroom_id == classroom.id,  # type: ignore[arg-type]
            Student.user_id == current_user.id,  # type: ignore[arg-type]
        )
    ).first()
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


def _include_type(classroom: Classroom, kind: str) -> bool:
    """本轮是否包含某题型。复述/问答默认包含（NULL/True）；朗读是新题型，默认不含。"""
    if kind == "reading":
        return classroom.assign_reading is True
    if kind == "repeat":
        return classroom.assign_repeat is not False
    return classroom.assign_qa is not False


def _require_classroom_teacher(classroom: Classroom, current_user: User) -> None:
    """教师端点：本人是指派教师或管理员才能访问（课堂码不能当教师凭据）。"""
    if current_user.is_superuser:
        return
    if classroom.owner_id is not None and classroom.owner_id == current_user.id:
        return
    raise HTTPException(
        status_code=403,
        detail="没有权限：您不是该课堂的授权教师，请联系管理员绑定后再查看",
    )


@router.get("", response_model=list[ClassroomPublic])
def list_my_classrooms(session: SessionDep, current_user: CurrentUser) -> Any:
    """课堂列表：管理员看全部，教师看自己名下的（工作台「我的课堂」）。"""
    stmt = select(Classroom).order_by(col(Classroom.created_at).desc())  # type: ignore[union-attr]
    if not current_user.is_superuser:
        stmt = stmt.where(Classroom.owner_id == current_user.id)  # type: ignore[arg-type]
    return session.exec(stmt).all()


@router.delete("/{code}")
def delete_class(
    session: SessionDep, code: str, current_user: CurrentUser
) -> dict[str, str]:
    """删除课堂（本人课堂或管理员）。

    仅允许删除没有任何作答记录的课堂（测试/误建场景）；
    有学生作答的课堂请用管理员后台停用，教学数据必须保留。
    """
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    student_ids = session.exec(
        select(Student.id).where(Student.classroom_id == classroom.id)  # type: ignore[arg-type]
    ).all()
    if student_ids:
        has_attempts = (
            session.exec(
                select(Attempt.id)
                .where(
                    col(Attempt.student_id).in_(student_ids)  # type: ignore[arg-type]
                )
                .limit(1)
            ).first()
            is not None
        )
        if has_attempts:
            raise HTTPException(
                status_code=409,
                detail="课堂内已有学生作答记录，不能删除；如需停用请联系管理员在后台操作",
            )
    session.delete(classroom)  # 学生档案/会话随外键级联清理（无作答即无损失）
    session.commit()
    return {"message": "课堂已删除"}


@router.post("", response_model=ClassroomPublic)
def create_class(
    session: SessionDep,
    current_user: TeacherUserDep,
    class_in: ClassroomCreate,
) -> Any:
    """创建课堂（教师或管理员），创建者即属主，课堂码分发给本班学生。"""
    name = class_in.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="课堂名称不能为空")
    for _ in range(5):
        code = _generate_classroom_code()
        classroom = Classroom(
            code=code,
            name=name,
            grade=class_in.grade.strip() if class_in.grade else None,
            teaching_goal=(
                class_in.teaching_goal.strip() if class_in.teaching_goal else None
            ),
            class_size=class_in.class_size,
            owner_id=current_user.id,
        )
        try:
            return create_classroom(session=session, classroom=classroom)
        except IntegrityError:
            session.rollback()
            continue
    raise HTTPException(status_code=500, detail="无法生成唯一课堂码")


@router.post("/{code}/join", response_model=StudentPublic)
def join_class(
    session: SessionDep,
    current_user: StudentUserDep,
    code: str,
    join_in: StudentJoin,
) -> Any:
    """学生（登录态）凭课堂码加入；显示名缺省用账号姓名，重复入班幂等。"""
    classroom = _get_classroom(session, code)
    return join_classroom(
        session=session,
        classroom=classroom,
        user=current_user,
        display_name=join_in.display_name,
    )


def _latest_done_attempts(
    session: Any, student_id: uuid.UUID, session_id: uuid.UUID
) -> list[Attempt]:
    """本轮内每条题目的最新一次作答（含 queued/failed，供进度恢复）。"""
    attempts = session.exec(
        select(Attempt)
        .where(
            Attempt.student_id == student_id,
            Attempt.session_id == session_id,
        )
        .order_by(col(Attempt.created_at))
    ).all()
    latest: dict[uuid.UUID, Attempt] = {}
    for attempt in attempts:
        latest[attempt.item_id] = attempt
    return list(latest.values())


def _repeat_attempts_of_session(
    session: Any, practice_session: PracticeSession
) -> list[Attempt]:
    attempts = session.exec(
        select(Attempt)
        .where(
            Attempt.session_id == practice_session.id,
            Attempt.item_type == AttemptItemType.REPEAT,
        )
        .order_by(col(Attempt.created_at))
    ).all()
    latest: dict[uuid.UUID, Attempt] = {}
    for attempt in attempts:
        latest[attempt.item_id] = attempt
    return list(latest.values())


def _pick_questions(
    session: Any,
    scenario: Scenario,
    student_id: uuid.UUID,
    limit: int = QUESTIONS_PER_ROUND,
    fill_with_done: bool = True,
) -> tuple[list[ScenarioQuestion], bool]:
    """同主题、未做过的优先，按 order_index 稳定排序（不分级，全班同题）。

    返回 (题目列表, 是否已用尽)。选择是确定性的：刷新不会换题。
    fill_with_done=True 用于 /today：取前 N 道题（按 order_index 固定题单，
    提交 Q1 后不会变成 Q2/Q3）；fill_with_done=False 用于换一题（只取未做过）。
    """
    questions = session.exec(
        select(ScenarioQuestion)
        .where(ScenarioQuestion.scenario_id == scenario.id)
        .order_by(col(ScenarioQuestion.order_index))
    ).all()
    done_ids = set(
        session.exec(
            select(Attempt.item_id).where(
                Attempt.student_id == student_id,
                Attempt.item_type == AttemptItemType.QUESTION,
            )
        ).all()
    )
    undone = [q for q in questions if q.id not in done_ids]
    exhausted = len(undone) == 0
    if fill_with_done:
        # /today：按 order_index 固定取前 N 道，提交后不偏移
        picked = questions[:limit]
    else:
        # 换一题：只取未做过的
        picked = undone[:limit]
    return picked, exhausted


def _question_band_for_session(
    session: Any, practice_session: PracticeSession, student: Student
) -> str:
    """本轮 3 句复述全部 done 后，按平均完整度/流利度调整问答档（US-05）。

    调整同时写回 student.current_band（下一轮沿用）与 session.question_band。
    未完成复述时沿用会话档位。
    """
    if practice_session.question_band is not None:
        return practice_session.question_band

    if practice_session.passage_id is not None:
        passage = session.get(Passage, practice_session.passage_id)
    else:
        passage = _active_passage(session, student)
    if passage is None:
        return practice_session.band
    sentences: list[RepeatSentence] = session.exec(  # type: ignore[assignment]
        select(RepeatSentence)
        .where(RepeatSentence.passage_id == passage.id)
        .order_by(col(RepeatSentence.order_index))
    ).all()
    repeats = _repeat_attempts_of_session(session, practice_session)
    done = [a for a in repeats if a.status == AttemptStatus.DONE]
    if not sentences or len(done) < len(sentences):
        return practice_session.band

    locked_session = session.exec(
        select(PracticeSession)
        .where(PracticeSession.id == practice_session.id)
        .with_for_update()
    ).first()
    locked_student = session.exec(
        select(Student).where(Student.id == student.id).with_for_update()
    ).first()
    if locked_session is None or locked_student is None:
        return practice_session.band
    if locked_session.question_band is not None:
        return locked_session.question_band

    avg_c = sum(a.completeness or 0 for a in done) / len(done)
    avg_f = sum(a.fluency or 0 for a in done) / len(done)
    adjusted = adjust_band(avg_c, avg_f, locked_student.current_band)
    locked_student.current_band = adjusted
    locked_session.question_band = adjusted
    session.add(locked_student)
    session.add(locked_session)
    session.commit()
    return adjusted


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
    # 按题指派（三题型独立）优先于单元指派/个人路径
    item_objects = _assigned_item_objects(session, classroom)
    current_assignment_id = (
        classroom.current_exercise_id if session_id is None else None
    )
    if session_id is not None:
        practice_session = session.get(PracticeSession, session_id)
        if practice_session is None or practice_session.student_id != student.id:
            raise HTTPException(status_code=404, detail="Session not found")
        passage = (
            session.get(Passage, practice_session.passage_id)
            if practice_session.passage_id
            else _active_passage(session, student)
        )
        if passage is None:
            raise HTTPException(status_code=404, detail="No active passage")
    elif item_objects is not None:
        # 按题模式：题目集合即题单，锚点篇（首篇朗读材料，可无）只担会话归属
        item_passages, item_sentences, item_questions = item_objects
        anchor = item_passages[0] if item_passages else None
        practice_session = get_or_create_today_session(
            session=session,
            classroom=classroom,
            student=student,
            today=today,
            passage_id=anchor.id if anchor else None,
            assignment_id=current_assignment_id,
        )
    else:
        passage = _active_passage(session, student)
        practice_session = get_or_create_today_session(
            session=session,
            classroom=classroom,
            student=student,
            today=today,
            passage_id=passage.id,
            assignment_id=current_assignment_id,
        )

    snapshot_items: list[dict[str, object]] | None = None
    if practice_session.assignment_id is not None:
        exercise = session.get(ClassroomExercise, practice_session.assignment_id)
        if exercise is not None:
            snapshot_items = exercise.snapshot_items
    include_reading = _include_type(classroom, "reading")
    include_repeat = _include_type(classroom, "repeat")
    include_qa = _include_type(classroom, "qa")

    if snapshot_items is not None:
        # 已发布练习：始终使用发布时快照，不再读取可能被编辑的题库。
        include_reading = any(
            item.get("type") == AttemptItemType.PASSAGE for item in snapshot_items
        )
        include_repeat = any(
            item.get("type") == AttemptItemType.REPEAT for item in snapshot_items
        )
        include_qa = any(
            item.get("type") == AttemptItemType.QUESTION for item in snapshot_items
        )
        item_passages = item_sentences = item_questions = []
        reading_passages = []
        sentences = []
        questions = []
        exhausted = False
        band = practice_session.question_band or practice_session.band
    elif item_objects is not None and session_id is None:
        # 按题模式：老师选了什么就是什么，题型勾选不再二次裁剪
        include_reading = bool(item_passages)
        include_repeat = bool(item_sentences)
        include_qa = bool(item_questions)
        reading_passages = item_passages
        sentences = item_sentences
        questions = item_questions
        exhausted = False
        band = practice_session.question_band or practice_session.band
    else:
        # 单元指派/个人路径：朗读题=组内全部启用篇目（长文拆段），探索轮单篇
        if session_id is None and _assignment_unit(session, classroom) is not None:
            reading_passages = _assigned_active_passages(session, classroom)
        else:
            reading_passages = [passage]

        sentences = []
        if include_repeat:
            for p in reading_passages:
                sentences.extend(
                    session.exec(
                        select(RepeatSentence)
                        .where(RepeatSentence.passage_id == p.id)
                        .order_by(col(RepeatSentence.order_index))
                    ).all()
                )
            if not sentences:
                raise HTTPException(
                    status_code=404, detail="No repeat sentences configured"
                )

        questions = []
        exhausted = False
        band = practice_session.question_band or practice_session.band
        if include_qa:
            scenario = _scenario_for_topic(session, passage.topic)
            # 档位仅作学生进度展示（升降档），抽题不再按档位过滤：全班同题
            band = _question_band_for_session(session, practice_session, student)
            questions, exhausted = _pick_questions(
                session, scenario, student.id, QUESTIONS_PER_ROUND
            )

    # 复述句的重听计数（学生×本轮×题目）
    listen_counts: dict[uuid.UUID, int] = {}
    snapshot_repeat_ids = [
        uuid.UUID(str(item["id"]))
        for item in snapshot_items or []
        if item.get("type") == AttemptItemType.REPEAT
    ]
    listen_item_ids = snapshot_repeat_ids or [s.id for s in sentences]
    if listen_item_ids:
        listens = session.exec(
            select(ItemListen).where(
                ItemListen.student_id == student.id,  # type: ignore[arg-type]
                ItemListen.session_id == practice_session.id,  # type: ignore[arg-type]
                col(ItemListen.item_id).in_(listen_item_ids),  # type: ignore[operator]
            )
        ).all()
        listen_counts = {ln.item_id: ln.count for ln in listens}

    if snapshot_items is not None:
        items = [
            PlanItem(
                type=str(item["type"]),
                id=uuid.UUID(str(item["id"])),
                text=str(item.get("text") or ""),
                translation=(
                    str(item["translation"])
                    if item.get("translation") is not None
                    else None
                ),
                audio_url=(
                    str(item["audio_url"])
                    if item.get("audio_url") is not None
                    else None
                ),
                suggested_seconds=int(item.get("suggested_seconds") or 20),  # ty: ignore[invalid-argument-type]
                band=(str(item["band"]) if item.get("band") is not None else None),
                replay_limit=(
                    int(item["replay_limit"])  # ty: ignore[invalid-argument-type]
                    if item.get("replay_limit") is not None
                    else None
                ),
                listen_used=(
                    listen_counts.get(uuid.UUID(str(item["id"])), 0)
                    if item.get("type") == AttemptItemType.REPEAT
                    else None
                ),
            )
            for item in snapshot_items
        ]
    else:
        items = []
    if snapshot_items is None and include_reading:
        # 朗读题：组内每篇启用材料一道（长文拆段后分别朗读）
        items += [
            PlanItem(
                type=AttemptItemType.PASSAGE,
                id=p.id,
                text=p.text,
                translation=p.translation,
                audio_url=p.audio_url,
                suggested_seconds=p.suggested_seconds,
            )
            for p in reading_passages
        ]
    if snapshot_items is None:
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
            )
            for s in sentences
        ]
    if snapshot_items is None:
        items += [
            PlanItem(
                type=AttemptItemType.QUESTION,
                id=q.id,
                text=q.text,
                translation=q.translation,
                audio_url=q.audio_url,
                suggested_seconds=q.suggested_seconds,
            )
            for q in questions
        ]

    # 激励结算（幂等）：本轮全部终态时计算星/XP/连胜/徽章
    settle_session(session, practice_session, student, today, len(items))

    attempts = _latest_done_attempts(session, student.id, practice_session.id)
    plan_attempts = [
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

    session.refresh(student)
    session.refresh(practice_session)
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
    exclude_ids: list[uuid.UUID] = Query(default=[]),
) -> Any:
    """换一题：同主题、未做过的问题（US-06）。用尽时 exhausted=true。

    传 session_id 时使用该会话的篇目（主题探索轮），
    不传时使用当日课堂会话。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    # 按题发布时优先走下方的情景题库换题逻辑；快照分支仅用于兼容单元发布。
    if (
        session_id is None
        and classroom.current_exercise_id is not None
        and classroom.assigned_items is None
    ):
        exercise = session.get(ClassroomExercise, classroom.current_exercise_id)
        if exercise is not None:
            question_snapshots = [
                item
                for item in exercise.snapshot_items
                if item.get("type") == AttemptItemType.QUESTION
            ]
            passage_snapshot = next(
                (
                    item
                    for item in exercise.snapshot_items
                    if item.get("type") == AttemptItemType.PASSAGE
                ),
                None,
            )
            practice_session = get_or_create_today_session(
                session=session,
                classroom=classroom,
                student=student,
                today=_today_in_practice_tz(),
                passage_id=(
                    uuid.UUID(str(passage_snapshot["id"]))
                    if passage_snapshot is not None
                    else None
                ),
                assignment_id=exercise.id,
            )
            done_ids = {
                attempt.item_id
                for attempt in session.exec(
                    select(Attempt).where(Attempt.session_id == practice_session.id)
                ).all()
            }
            excluded = set(exclude_ids) | done_ids
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
                    suggested_seconds=int(candidate.get("suggested_seconds") or 20),  # ty: ignore[invalid-argument-type]
                ),
                exhausted=False,
            )
    # 按题指派：换题范围 = 指派问答题所在情景的其余未做题目
    item_objects = _assigned_item_objects(session, classroom)
    if item_objects is not None and session_id is None:
        _, _, item_questions = item_objects
        scenario = (
            session.get(Scenario, item_questions[0].scenario_id)
            if item_questions
            else None
        )
        if scenario is None:
            return NextQuestion(question=None, exhausted=True)
        questions, exhausted = _pick_questions(
            session, scenario, student.id, limit=999, fill_with_done=False
        )
        excluded = set(exclude_ids) | {q.id for q in item_questions}
        candidates = [q for q in questions if q.id not in excluded]
        if not candidates:
            return NextQuestion(question=None, exhausted=exhausted)
        return NextQuestion(
            question=ScenarioQuestionPublic.model_validate(candidates[0]),
            exhausted=False,
        )
    if session_id is not None:
        practice_session = session.get(PracticeSession, session_id)
        if practice_session is None or practice_session.student_id != student.id:
            raise HTTPException(status_code=404, detail="Session not found")
        if practice_session.passage_id is not None:
            passage = session.get(Passage, practice_session.passage_id)
        else:
            passage = _active_passage(session, student)
        if passage is None:
            raise HTTPException(status_code=404, detail="No active passage")
    else:
        passage = _active_passage(session, student)
        practice_session = get_or_create_today_session(
            session=session,
            classroom=classroom,
            student=student,
            today=_today_in_practice_tz(),
            passage_id=passage.id,
            assignment_id=classroom.current_exercise_id,
        )
    scenario = _scenario_for_topic(session, passage.topic)

    # 先取所有未做过的题，再排除当前题单已有的，避免误报题库耗尽
    questions, exhausted = _pick_questions(
        session, scenario, student.id, limit=999, fill_with_done=False
    )
    excluded = set(exclude_ids)
    candidates = [q for q in questions if q.id not in excluded]
    if not candidates:
        return NextQuestion(question=None, exhausted=exhausted)
    return NextQuestion(
        question=ScenarioQuestionPublic.model_validate(candidates[0]),
        exhausted=False,
    )


@router.get("/{code}/board", response_model=BoardData)
def read_class_board(session: SessionDep, code: str, current_user: CurrentUser) -> Any:
    """老师名单表（PRD §8.5 2 周）：谁交了、每题分数、音频；允许先显示评分中。

    需要教师身份：本课指派教师或管理员（课堂码不能当教师凭据）。
    """
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    today = _today_in_practice_tz()

    current_exercise = (
        session.get(ClassroomExercise, classroom.current_exercise_id)
        if classroom.current_exercise_id is not None
        else None
    )
    # 已发布版本优先：名单表也必须按快照渲染，避免题库编辑后题位漂移。
    if current_exercise is not None:
        snapshot_refs: dict[str, list[_BoardRef]] = {
            AttemptItemType.PASSAGE: [],
            AttemptItemType.REPEAT: [],
            AttemptItemType.QUESTION: [],
        }
        for item in current_exercise.snapshot_items:
            item_type = str(item.get("type", ""))
            item_id = item.get("id")
            if item_type not in snapshot_refs or item_id is None:
                continue
            try:
                snapshot_refs[item_type].append(_BoardRef(uuid.UUID(str(item_id))))
            except ValueError:
                logger.warning("invalid exercise snapshot item id: %s", item_id)
        board_item_objects = (
            snapshot_refs[AttemptItemType.PASSAGE],
            snapshot_refs[AttemptItemType.REPEAT],
            snapshot_refs[AttemptItemType.QUESTION],
        )
    else:
        board_item_objects = _assigned_item_objects(session, classroom)
    assigned_unit_board = _assignment_unit(session, classroom)
    include_reading = include_repeat = include_qa = False
    if board_item_objects is not None:
        board_passages, board_sentences, board_questions = board_item_objects
        board_passage = board_passages[0] if board_passages else None
        include_reading = True
        include_repeat = True
        include_qa = True
        skeleton = (
            [
                BoardItem(
                    item_id=p.id,
                    type=AttemptItemType.PASSAGE,
                    status="missing",
                )
                for p in board_passages
            ]
            + [
                BoardItem(
                    item_id=s.id,
                    type=AttemptItemType.REPEAT,
                    status="missing",
                )
                for s in board_sentences
            ]
            + [
                BoardItem(
                    item_id=q.id,
                    type=AttemptItemType.QUESTION,
                    status="missing",
                )
                for q in board_questions
            ]
        )
        # 按题轮的学生行渲染需要这些集合
        board_repeat_sentences = board_sentences
    else:
        # 当前指派单元的篇目（面板和档位计算都用它，不用全局首篇）；
        # 组内多篇各自占一个朗读题位，锚点（第一篇）用于会话匹配
        if assigned_unit_board is not None:
            board_passages = _assigned_active_passages(session, classroom)
        else:
            board_passages = []
        board_passage = board_passages[0] if board_passages else None
        if board_passage is None:
            board_passage = _active_passage(session)
            board_passages = [board_passage]

        # 题目骨架：按指派题型裁剪（复述默认含；朗读勾选后含）
        include_reading = _include_type(classroom, "reading")
        include_repeat = _include_type(classroom, "repeat")
        include_qa = _include_type(classroom, "qa")
        board_questions = []
        board_repeat_sentences = []
        if include_repeat:
            for p in board_passages:
                board_repeat_sentences.extend(
                    session.exec(
                        select(RepeatSentence)
                        .where(RepeatSentence.passage_id == p.id)
                        .order_by(col(RepeatSentence.order_index))
                    ).all()
                )
        skeleton = [
            BoardItem(
                item_id=s.id,
                type=AttemptItemType.REPEAT,
                status="missing",
            )
            for s in board_repeat_sentences
        ]
        if include_reading:
            skeleton = [
                BoardItem(
                    item_id=p.id,
                    type=AttemptItemType.PASSAGE,
                    status="missing",
                )
                for p in board_passages
            ] + skeleton
        include_qa = _include_type(classroom, "qa")
        board_questions = []

    students = session.exec(
        select(Student).where(Student.classroom_id == classroom.id)
    ).all()
    today_sessions = session.exec(
        select(PracticeSession)
        .where(
            PracticeSession.classroom_id == classroom.id,
            PracticeSession.session_date == today,
            PracticeSession.mode == "daily",
        )
        .order_by(col(PracticeSession.created_at))
    ).all()

    # A→B→A 修复：优先匹配当前指派篇目的会话，而非仅按创建时间取最新
    student_sessions: dict[uuid.UUID, list[PracticeSession]] = {}
    for s in today_sessions:
        student_sessions.setdefault(s.student_id, []).append(s)
    session_by_student: dict[uuid.UUID, PracticeSession] = {}
    assigned_passage_id = board_passage.id if board_passage else None
    for sid, sessions in student_sessions.items():
        if current_exercise is not None:
            matching = [s for s in sessions if s.assignment_id == current_exercise.id]
            if matching:
                session_by_student[sid] = matching[-1]
            # 当前发布版本没有开始过，就不要回退到已归档版本的同篇目会话。
            continue
        if assigned_passage_id is not None:
            matching = [s for s in sessions if s.passage_id == assigned_passage_id]
            if matching:
                session_by_student[sid] = matching[-1]
                continue
        session_by_student[sid] = sessions[-1]

    # 7 日未练口径：加入超过 7 天且窗口内无任何作答（US-10 简化实现）
    from datetime import timedelta

    now = datetime.now(ZoneInfo(settings.PRACTICE_TZ))
    week_ago = (now - timedelta(days=7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_ago_utc = week_ago.astimezone(ZoneInfo("UTC"))
    student_ids = [s.id for s in students]
    recent_attempts = session.exec(
        select(Attempt).where(
            Attempt.student_id.in_(student_ids),  # type: ignore
            Attempt.created_at >= week_ago_utc,  # type: ignore
        )
    ).all()
    recent_by_student: dict[uuid.UUID, list[Attempt]] = {}
    for attempt in recent_attempts:
        if attempt.student_id is None:
            continue
        recent_by_student.setdefault(attempt.student_id, []).append(attempt)

    board_students: list[BoardStudent] = []
    submitted_count = 0
    completed_count = 0
    pending_count = 0
    # 预取所有学生的作答（一次查询替代 N+1）
    practice_session_ids = [
        ps.id for ps in session_by_student.values() if ps is not None
    ]
    attempts_map: dict[tuple[uuid.UUID, uuid.UUID], list[Attempt]] = {}
    if practice_session_ids:
        all_attempts = session.exec(
            select(Attempt)
            .where(
                Attempt.student_id.in_(student_ids),  # type: ignore
                Attempt.session_id.in_(practice_session_ids),  # type: ignore
            )
            .order_by(col(Attempt.created_at))
        ).all()
        for attempt in all_attempts:
            if attempt.student_id is None or attempt.session_id is None:
                continue
            key = (attempt.student_id, attempt.session_id)
            if key not in attempts_map:
                attempts_map[key] = []
            attempts_map[key].append(attempt)

    for student in students:
        practice_session = session_by_student.get(student.id)
        items: list[BoardItem] = []
        repeat_scores: list[float] = []
        question_scores: list[float] = []
        has_pending = False
        round_status = "not_started"

        if practice_session is not None:
            attempts = attempts_map.get((student.id, practice_session.id), [])
            latest: dict[uuid.UUID, Attempt] = {}
            for attempt in attempts:
                latest[attempt.item_id] = attempt

            # 朗读题位（勾选指派才有；组内多篇各自占位）
            if include_reading:
                for board_p in board_passages:
                    attempt = latest.get(board_p.id)
                    if attempt is None:
                        items.append(
                            BoardItem(
                                item_id=board_p.id,
                                type=AttemptItemType.PASSAGE,
                                status="missing",
                            )
                        )
                    else:
                        if attempt.status in (
                            AttemptStatus.QUEUED,
                            AttemptStatus.SCORING,
                        ):
                            has_pending = True
                        if (
                            attempt.status == AttemptStatus.DONE
                            and attempt.overall is not None
                        ):
                            repeat_scores.append(attempt.overall)
                        items.append(
                            BoardItem(
                                item_id=board_p.id,
                                type=AttemptItemType.PASSAGE,
                                status=attempt.status,
                                overall=attempt.overall,
                                attempt_id=attempt.id,
                            )
                        )
            # 骨架顺序：复述句
            for s in board_repeat_sentences:
                attempt = latest.get(s.id)
                if attempt is None:
                    items.append(
                        BoardItem(
                            item_id=s.id, type=AttemptItemType.REPEAT, status="missing"
                        )
                    )
                    continue
                if (
                    attempt.status == AttemptStatus.QUEUED
                    or attempt.status == AttemptStatus.SCORING
                ):
                    has_pending = True
                if attempt.status == AttemptStatus.DONE and attempt.overall is not None:
                    repeat_scores.append(attempt.overall)
                items.append(
                    BoardItem(
                        item_id=s.id,
                        type=AttemptItemType.REPEAT,
                        status=attempt.status,
                        overall=attempt.overall,
                        attempt_id=attempt.id,
                    )
                )
            # 问答：按题指派的题位按骨架渲染（含未做），旧作答补充展示
            rendered_qids: set[uuid.UUID] = set()
            for board_q in board_questions:
                rendered_qids.add(board_q.id)
                attempt = latest.get(board_q.id)
                if attempt is None:
                    items.append(
                        BoardItem(
                            item_id=board_q.id,
                            type=AttemptItemType.QUESTION,
                            status="missing",
                        )
                    )
                    continue
                if attempt.status in (
                    AttemptStatus.QUEUED,
                    AttemptStatus.SCORING,
                ):
                    has_pending = True
                if attempt.status == AttemptStatus.DONE and attempt.overall is not None:
                    question_scores.append(attempt.overall)
                items.append(
                    BoardItem(
                        item_id=board_q.id,
                        type=AttemptItemType.QUESTION,
                        status=attempt.status,
                        overall=attempt.overall,
                        attempt_id=attempt.id,
                    )
                )
            # 问答（每个学生的题可能不同；未指派问答时旧作答仅展示不计分）
            for item_id, attempt in latest.items():
                if attempt.item_type != AttemptItemType.QUESTION:
                    continue
                if item_id in rendered_qids:
                    continue
                if not include_qa:
                    items.append(
                        BoardItem(
                            item_id=item_id,
                            type=AttemptItemType.QUESTION,
                            status=attempt.status,
                            overall=attempt.overall,
                            attempt_id=attempt.id,
                        )
                    )
                    continue
                if attempt.status in (AttemptStatus.QUEUED, AttemptStatus.SCORING):
                    has_pending = True
                if attempt.status == AttemptStatus.DONE and attempt.overall is not None:
                    question_scores.append(attempt.overall)
                items.append(
                    BoardItem(
                        item_id=item_id,
                        type=AttemptItemType.QUESTION,
                        status=attempt.status,
                        overall=attempt.overall,
                        attempt_id=attempt.id,
                    )
                )

        # 统一统计口径：not_started / scoring / in_progress / all_done / has_failures
        non_missing = [i for i in items if i.status != "missing"]
        terminal = [
            i for i in items if i.status in (AttemptStatus.DONE, AttemptStatus.FAILED)
        ]
        if not non_missing:
            round_status = "not_started"
        elif has_pending:
            round_status = "scoring"
        elif len(terminal) < len(items):
            round_status = "in_progress"
        elif all(i.status == AttemptStatus.DONE for i in terminal):
            round_status = "all_done"
        else:
            round_status = "has_failures"

        done_count = sum(1 for i in items if i.status == AttemptStatus.DONE)
        if any(i.status != "missing" for i in items):
            submitted_count += 1
        if round_status in ("all_done", "has_failures"):
            completed_count += 1
        if has_pending:
            pending_count += 1
        joined_before_window = (
            student.created_at is not None
            and student.created_at.astimezone(ZoneInfo(settings.PRACTICE_TZ)).date()
            < week_ago.date()
        )
        inactive = joined_before_window and student.id not in recent_by_student
        board_students.append(
            BoardStudent(
                student_id=student.id,
                display_name=student.display_name,
                suffix=student.suffix,
                done_count=done_count,
                total_count=len(items),
                repeat_avg=(
                    round(sum(repeat_scores) / len(repeat_scores), 1)
                    if repeat_scores
                    else None
                ),
                question_avg=(
                    round(sum(question_scores) / len(question_scores), 1)
                    if question_scores
                    else None
                ),
                has_pending=has_pending,
                round_status=round_status,
                inactive_days7=inactive,
                xp=student.xp,
                streak_days=student.streak_days,
                items=items,
            )
        )

    # 交了的在前，其次按完成数降序，再按名字
    board_students.sort(
        key=lambda s: (
            -min(s.done_count, 1),
            -s.done_count,
            s.display_name,
        )
    )

    latest_engine = session.exec(
        select(Attempt.engine)
        .where(Attempt.status == AttemptStatus.DONE)
        .order_by(col(Attempt.created_at).desc())
        .limit(1)
    ).first()

    return BoardData(
        classroom_code=classroom.code,
        classroom_name=classroom.name,
        classroom_grade=classroom.grade,
        teaching_goal=classroom.teaching_goal,
        class_size=classroom.class_size,
        assigned_items=classroom.assigned_items,
        current_exercise=(
            ClassroomExercisePublic(
                id=current_exercise.id,
                classroom_id=current_exercise.classroom_id,
                version_no=current_exercise.version_no,
                title=current_exercise.title,
                status=current_exercise.status,
                item_count=len(current_exercise.snapshot_items),
                created_at=current_exercise.created_at,
                published_at=current_exercise.published_at,
                archived_at=current_exercise.archived_at,
            )
            if current_exercise is not None
            else None
        ),
        engine=latest_engine or "mock",
        assignment=(
            AssignmentInfo(
                unit_id=assigned_unit_board.id, title=assigned_unit_board.title
            )
            if assigned_unit_board
            else None
        ),
        submitted_count=submitted_count,
        completed_count=completed_count,
        pending_count=pending_count,
        students=board_students,
        items=skeleton,
    )


@router.get("/{code}/trail", response_model=TrailData)
def read_student_trail(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
    days: int = Query(default=90, ge=1, le=3650, description="查询最近多少天的轨迹"),
    student_id: uuid.UUID | None = Query(
        default=None, description="教师查看指定学生；学生查看自己时省略"
    ),
) -> Any:
    """学生进步轨迹（PRD US-09）：按练习日聚合口语参考分与词汇档。

    学生账号省略 student_id 看自己；教师/管理员传 student_id（授权范围内）。
    """
    classroom = _get_classroom(session, code)
    if current_user.role == "student" and not current_user.is_superuser:
        student = _student_profile_of(session, classroom, current_user)
    else:
        if student_id is None:
            raise HTTPException(status_code=422, detail="教师查看需传 student_id")
        _require_classroom_teacher(classroom, current_user)
        student = _get_student_of_classroom(session, classroom, student_id)

    tz = ZoneInfo(settings.PRACTICE_TZ)
    now_tz = datetime.now(tz)
    window_start = (now_tz - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    window_start_utc = window_start.astimezone(ZoneInfo("UTC"))

    attempts = session.exec(
        select(Attempt)
        .where(
            Attempt.student_id == student.id,
            Attempt.created_at >= window_start_utc,  # type: ignore
        )
        .order_by(col(Attempt.created_at))
    ).all()
    by_date: dict[str, dict[str, Any]] = {}
    for attempt in attempts:
        day = (
            attempt.created_at.astimezone(tz).date().isoformat()
            if attempt.created_at
            else None
        )
        if day is None or attempt.status != AttemptStatus.DONE:
            continue
        bucket = by_date.setdefault(
            day,
            {
                "speaking": [],
                "completeness": [],
                "vocab": None,
                "count": 0,
            },
        )
        bucket["count"] += 1
        if attempt.item_type == AttemptItemType.QUESTION:
            if attempt.overall is not None:
                bucket["speaking"].append(attempt.overall)
            # 当日最新一次问答的词汇档（按时间顺序覆盖）
            if attempt.vocab and isinstance(attempt.vocab, dict):
                cefr = attempt.vocab.get("cefr")
                if isinstance(cefr, str):
                    bucket["vocab"] = cefr
        elif (
            attempt.item_type == AttemptItemType.REPEAT
            and attempt.completeness is not None
        ):
            bucket["completeness"].append(attempt.completeness)

    sessions = [
        TrailSession(
            date=day,
            speaking_avg=(
                round(sum(v["speaking"]) / len(v["speaking"]), 1)
                if v["speaking"]
                else None
            ),
            repeat_completeness_avg=(
                round(sum(v["completeness"]) / len(v["completeness"]), 1)
                if v["completeness"]
                else None
            ),
            vocab_cefr=v["vocab"],
            attempt_count=v["count"],
        )
        for day, v in sorted(by_date.items())
    ]

    # 最近一轮档位动向（PRD US-10）：对比最近会话的调整后档与开始档。
    # 先幂等触发一次档位计算（作答后学生可能没再打开 /today）
    band_change: str | None = None
    practice_sessions = session.exec(
        select(PracticeSession)
        .where(PracticeSession.student_id == student.id)
        .order_by(col(PracticeSession.created_at).desc())
        .limit(100)
    ).all()
    practice_sessions.reverse()  # type: ignore
    if practice_sessions:
        latest = practice_sessions[-1]
        _question_band_for_session(session, latest, student)
        # question_band 已写入才算完成过一轮调整；复述未完成 → 无建议
        if latest.question_band is not None:
            if latest.question_band == latest.band:
                band_change = "keep"
            elif BAND_ORDER.index(latest.question_band) > BAND_ORDER.index(latest.band):
                band_change = "up"
            else:
                band_change = "down"

    # 累计开口分钟 + 词汇命中按档（与轨迹窗口一致，只统计已完成作答）
    done_attempts = [a for a in attempts if a.status == AttemptStatus.DONE]
    total_minutes = round(sum(a.duration_s for a in done_attempts) / 60)
    vocab_counts: dict[str, int] = {}
    for a in done_attempts:
        vocab = a.vocab if isinstance(a.vocab, dict) else None
        if not vocab:
            continue
        hits = vocab.get("hits")
        if isinstance(hits, dict):
            for band, words in hits.items():
                if not isinstance(band, str) or not isinstance(words, list):
                    continue
                vocab_counts[band] = vocab_counts.get(band, 0) + len(words)

    return TrailData(
        classroom_code=classroom.code,
        student_id=student.id,
        display_name=student.display_name,
        suffix=student.suffix,
        sessions=sessions,
        band_change=band_change,
        total_minutes=total_minutes,
        vocab_counts=vocab_counts,
    )


@router.get("/{code}/path", response_model=LearningPath)
def read_learning_path(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
) -> Any:
    """学习路径：单元有序 + 完成轮数/星级 + 锁定（主题探索与首页消费）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)

    units = session.exec(
        select(Unit).where(Unit.is_active).order_by(col(Unit.order_index))
    ).all()
    passages = session.exec(select(Passage)).all()
    settled = session.exec(
        select(PracticeSession).where(
            PracticeSession.student_id == student.id,
            col(PracticeSession.stars).is_not(None),
            col(PracticeSession.passage_id).is_not(None),
        )
    ).all()
    # unit → {rounds, best_stars}
    stats: dict = {}
    passage_to_unit = {p.id: p.unit_id for p in passages}
    for ps in settled:
        uid = passage_to_unit.get(ps.passage_id)
        if uid is None:
            continue
        bucket = stats.setdefault(uid, {"rounds": 0, "best": 0})
        bucket["rounds"] += 1
        bucket["best"] = max(bucket["best"], ps.stars or 0)

    assigned_unit = _assignment_unit(session, classroom)
    result: list[PathUnit] = []
    prev_done = True  # 第一关始终解锁
    for unit in units:
        unit_passage = next(
            (p for p in passages if p.unit_id == unit.id and p.is_active), None
        )
        done = stats.get(unit.id, {"rounds": 0, "best": 0})
        locked = (
            (not classroom.unlock_all)
            and not prev_done
            and (assigned_unit is None or unit.id != assigned_unit.id)
        )
        result.append(
            PathUnit(
                unit_id=unit.id,
                order_index=unit.order_index,
                title=unit.title,
                topic=unit.topic,
                rounds_done=done["rounds"],
                best_stars=done["best"] if done["rounds"] else None,
                locked=locked,
                passage_id=unit_passage.id if unit_passage else None,
            )
        )
        prev_done = done["rounds"] > 0

    return LearningPath(
        classroom_code=classroom.code,
        unlock_all=classroom.unlock_all,
        assignment=(
            AssignmentInfo(unit_id=assigned_unit.id, title=assigned_unit.title)
            if assigned_unit
            else None
        ),
        units=result,
    )


class AssignmentItemIn(SQLModel):
    """按题指派的单条题目引用：三种题型互相独立，各自成题。"""

    type: str  # passage | repeat | question
    id: uuid.UUID


class AssignmentRequest(SQLModel):
    # 不传 unit_id = 不动当前单元；显式 null = 清除指派回个人路径
    unit_id: uuid.UUID | None = None
    # 题型勾选（不传=不改；朗读默认不含，复述/问答默认含）
    assign_reading: bool | None = None
    assign_repeat: bool | None = None
    assign_qa: bool | None = None
    # 按题指派（三题型独立）：传非空列表则取代单元指派；传空列表=清除回个人路径
    items: list[AssignmentItemIn] | None = None
    # 可选练习标题；不传时使用“课堂练习”
    title: str | None = None


class ListenRequest(SQLModel):
    session_id: uuid.UUID
    item_id: uuid.UUID


class ListenResult(SQLModel):
    listen_used: int
    replay_limit: int  # 0 = 不限


@router.post("/{code}/listens", response_model=ListenResult)
def record_listen(
    session: SessionDep,
    current_user: StudentUserDep,
    code: str,
    body: ListenRequest,
) -> Any:
    """听句复述播放计数：学生每听一次标准音 +1，超过可重听次数返回 422。

    防刷口径：按 学生×本轮×题目 在库计数（前端禁播为体验层，真源在这里）。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    practice_session = session.get(PracticeSession, body.session_id)
    if practice_session is None or practice_session.student_id != student.id:
        raise HTTPException(status_code=404, detail="Session not found")
    sentence = session.get(RepeatSentence, body.item_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    replay_limit: int | None = sentence.replay_limit
    if practice_session.assignment_id is not None:
        exercise = session.get(ClassroomExercise, practice_session.assignment_id)
        snapshot = next(
            (
                item
                for item in (exercise.snapshot_items if exercise is not None else [])
                if item.get("type") == AttemptItemType.REPEAT
                and str(item.get("id")) == str(sentence.id)
            ),
            None,
        )
        if snapshot is None:
            raise HTTPException(status_code=422, detail="该句不在本轮练习内")
        if isinstance(snapshot.get("replay_limit"), (int, float)):
            replay_limit = int(snapshot["replay_limit"])  # ty: ignore[invalid-argument-type]
    elif (
        practice_session.passage_id is None
        or sentence.passage_id != practice_session.passage_id
    ):
        raise HTTPException(status_code=422, detail="该句不在本轮篇目内")
    if replay_limit is None:
        raise HTTPException(status_code=422, detail="复述句缺少播放设置")

    params = {
        "iid": uuid.uuid4(),
        "sid": student.id,
        "sess": practice_session.id,
        "item": sentence.id,
    }
    if replay_limit == 0:
        # 不限次：直接原子自增（原生 UPSERT，并发安全）
        used = session.execute(  # ty: ignore[deprecated]
            text(
                "INSERT INTO item_listen (id, student_id, session_id, item_id, count)"
                " VALUES (:iid, :sid, :sess, :item, 1)"
                " ON CONFLICT ON CONSTRAINT uq_item_listen_scope"
                " DO UPDATE SET count = item_listen.count + 1"
                " RETURNING count"
            ),
            params,
        ).scalar_one()
        session.commit()
        return ListenResult(listen_used=used, replay_limit=0)

    # 有限次：原子自增 + WHERE 上限保护；到上限时 UPDATE 不执行、无返回行
    result = session.execute(  # ty: ignore[deprecated]
        text(
            "INSERT INTO item_listen (id, student_id, session_id, item_id, count)"
            " VALUES (:iid, :sid, :sess, :item, 1)"
            " ON CONFLICT ON CONSTRAINT uq_item_listen_scope"
            " DO UPDATE SET count = item_listen.count + 1"
            " WHERE item_listen.count < :limit"
            " RETURNING count"
        ),
        {**params, "limit": replay_limit},
    ).scalar_one_or_none()
    if result is None:
        # INSERT 走了 ON CONFLICT 但 WHERE 不满足 → 已到上限；或 INSERT 本身因其它原因未返回
        # 回滚未完成的计数操作
        session.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"可重听次数已用完（{replay_limit} 次）",
        )
    used = result
    session.commit()
    return ListenResult(listen_used=used, replay_limit=replay_limit)


@router.get("/{code}/units", response_model=list[AssignmentInfo])
def list_units_for_class(
    session: SessionDep, code: str, current_user: CurrentUser
) -> Any:
    """课堂的单元列表（老师面板指派选择器用；需要教师身份）。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    units = session.exec(
        select(Unit).where(Unit.is_active).order_by(col(Unit.order_index))
    ).all()
    counts = dict(
        session.exec(
            select(Passage.unit_id, func.count())
            .where(
                Passage.is_active,
                Passage.unit_id.is_not(None),  # type: ignore
            )
            .group_by(Passage.unit_id)  # type: ignore
        ).all()
    )
    return [
        AssignmentInfo(
            unit_id=u.id,
            title=u.title,
            passage_count=counts.get(u.id, 0),
            assign_reading=classroom.assign_reading,
            assign_repeat=classroom.assign_repeat,
            assign_qa=classroom.assign_qa,
        )
        for u in units
    ]


@router.get("/{code}/exercises", response_model=list[ClassroomExercisePublic])
def list_classroom_exercises(
    session: SessionDep, code: str, current_user: CurrentUser
) -> Any:
    """课堂练习历史：发布版本只读，供教师回看与后续结果页使用。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    exercises = session.exec(
        select(ClassroomExercise)
        .where(ClassroomExercise.classroom_id == classroom.id)
        .order_by(col(ClassroomExercise.version_no).desc())
    ).all()
    return [
        ClassroomExercisePublic(
            id=exercise.id,
            classroom_id=exercise.classroom_id,
            version_no=exercise.version_no,
            title=exercise.title,
            status=exercise.status,
            item_count=len(exercise.snapshot_items),
            created_at=exercise.created_at,
            published_at=exercise.published_at,
            archived_at=exercise.archived_at,
        )
        for exercise in exercises
    ]


class ExerciseStudentResult(SQLModel):
    """单次练习按学生的结果行（发布历史结果页）。"""

    student_id: uuid.UUID
    display_name: str
    suffix: str | None = None
    done_count: int
    total_count: int
    has_pending: bool
    items: list[BoardItem]


@router.get(
    "/{code}/exercises/{exercise_id}/results",
    response_model=list[ExerciseStudentResult],
)
def read_exercise_results(
    session: SessionDep,
    code: str,
    exercise_id: uuid.UUID,
    current_user: CurrentUser,
) -> Any:
    """按发布快照回看每次练习的学生结果（历史结果页）。

    数据源 = 绑定该快照的学生会话上的作答；未开始的学生按快照题位
    全 missing 展示，老师能看出谁没做。
    """
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    exercise = session.get(ClassroomExercise, exercise_id)
    if exercise is None or exercise.classroom_id != classroom.id:
        raise HTTPException(status_code=404, detail="Exercise not found")

    students = session.exec(
        select(Student)
        .where(Student.classroom_id == classroom.id)
        .order_by(col(Student.display_name))
    ).all()
    sessions_by_student: dict[uuid.UUID, PracticeSession] = {}
    if students:
        for ps in session.exec(
            select(PracticeSession).where(
                PracticeSession.classroom_id == classroom.id,
                PracticeSession.assignment_id == exercise.id,
            )
        ).all():
            # 同学生多轮（跨天重发）取最新
            sessions_by_student[ps.student_id] = ps

    out: list[ExerciseStudentResult] = []
    for student in students:
        ps = sessions_by_student.get(student.id)
        latest: dict[uuid.UUID, Attempt] = {}
        has_pending = False
        if ps is not None:
            for attempt in session.exec(
                select(Attempt)
                .where(
                    Attempt.student_id == student.id,  # type: ignore[arg-type]
                    Attempt.session_id == ps.id,  # type: ignore[arg-type]
                )
                .order_by(col(Attempt.created_at))
            ).all():
                latest[attempt.item_id] = attempt
            has_pending = any(
                a.status in (AttemptStatus.QUEUED, AttemptStatus.SCORING)
                for a in latest.values()
            )
        items: list[BoardItem] = []
        done = 0
        for spec in exercise.snapshot_items:
            item_id = uuid.UUID(str(spec["id"]))
            attempt = latest.get(item_id)
            if attempt is None:
                items.append(
                    BoardItem(
                        item_id=item_id,
                        type=str(spec["type"]),
                        status="missing",
                    )
                )
                continue
            if attempt.status == AttemptStatus.DONE:
                done += 1
            items.append(
                BoardItem(
                    item_id=item_id,
                    type=str(spec["type"]),
                    status=attempt.status,
                    overall=attempt.overall,
                    attempt_id=attempt.id,
                )
            )
        out.append(
            ExerciseStudentResult(
                student_id=student.id,
                display_name=student.display_name,
                suffix=student.suffix,
                done_count=done,
                total_count=len(exercise.snapshot_items),
                has_pending=has_pending,
                items=items,
            )
        )
    return out


@router.put("/{code}/assignment", response_model=AssignmentInfo | None)
def set_assignment(
    session: SessionDep,
    code: str,
    body: AssignmentRequest,
    current_user: CurrentUser,
) -> Any:
    """老师设置/清除今日指派（需要教师身份）。

    两种模式：按题集合（items，三题型独立各自选题）优先；单元指派（unit_id）兼容旧流。
    清除（items=[] 或 unit_id=null）则回退个人路径。
    """
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user)
    # 题型勾选：显式传值才更新（None=不动）
    if body.assign_reading is not None:
        classroom.assign_reading = body.assign_reading
    if body.assign_repeat is not None:
        classroom.assign_repeat = body.assign_repeat
    if body.assign_qa is not None:
        classroom.assign_qa = body.assign_qa

    if body.items is not None:
        if body.items:
            _validate_assignment_items(session, body.items)
            snapshots = [
                _snapshot_item(session, item.type, item.id) for item in body.items
            ]
            _publish_exercise(
                session=session,
                classroom=classroom,
                current_user=current_user,
                snapshots=snapshots,
                title=body.title,
            )
            classroom.current_unit_id = None  # 按题模式取代单元指派
            # assigned_items 保留（_publish_exercise 已写入）：读取优先快照，
            # 换题用它排除已指派题目、从情景题库取未做过的新题
            session.commit()
            return None
        _archive_current_exercise(session, classroom)
        classroom.assigned_items = None
        classroom.current_unit_id = None
        session.add(classroom)
        session.commit()
        return None

    body_update = body.model_dump(exclude_unset=True)
    if "unit_id" in body_update:
        if body_update["unit_id"] is None:
            classroom.current_unit_id = None
            _archive_current_exercise(session, classroom)
            classroom.assigned_items = None
            session.add(classroom)
            session.commit()
            return None
        unit = session.get(Unit, body_update["unit_id"])
        if unit is None or not unit.is_active:
            raise HTTPException(status_code=404, detail="Unit not found")
        passages = list(
            session.exec(
                select(Passage)
                .where(Passage.unit_id == unit.id, Passage.is_active)
                .order_by(col(Passage.created_at))
            ).all()
        )
        if not passages:
            raise HTTPException(status_code=422, detail="该单元没有启用篇目，不能发布")
        snapshots: list[dict[str, object]] = []
        if classroom.assign_reading is True:
            snapshots.extend(
                _snapshot_item(session, AttemptItemType.PASSAGE, p.id) for p in passages
            )
        if classroom.assign_repeat is not False:
            for passage in passages:
                sentences = session.exec(
                    select(RepeatSentence)
                    .where(RepeatSentence.passage_id == passage.id)
                    .order_by(col(RepeatSentence.order_index))
                ).all()
                snapshots.extend(
                    _snapshot_item(session, AttemptItemType.REPEAT, sentence.id)
                    for sentence in sentences
                )
        if classroom.assign_qa is not False:
            scenario = _scenario_for_topic(session, passages[0].topic)
            questions = session.exec(
                select(ScenarioQuestion)
                .where(ScenarioQuestion.scenario_id == scenario.id)
                .order_by(col(ScenarioQuestion.order_index))
            ).all()
            snapshots.extend(
                _snapshot_item(session, AttemptItemType.QUESTION, question.id)
                for question in questions
            )
        _publish_exercise(
            session=session,
            classroom=classroom,
            current_user=current_user,
            snapshots=snapshots,
            title=body.title,
        )
        classroom.current_unit_id = unit.id
        classroom.assigned_items = None  # 单元模式仍保留旧路径标识，快照为真源
        session.add(classroom)
        session.commit()
        return AssignmentInfo(unit_id=unit.id, title=unit.title)
    # 只改题型勾选（未动单元）：返回当前指派单元
    session.add(classroom)
    session.commit()
    if classroom.current_unit_id is None:
        return None
    current = session.get(Unit, classroom.current_unit_id)
    if current is None:
        return None
    return AssignmentInfo(unit_id=current.id, title=current.title)


def _validate_assignment_items(session: Any, items: list[AssignmentItemIn]) -> None:
    """按题指派引用校验：题型合法且对象存在（朗读要求启用）。"""
    if len(items) > 100:
        raise HTTPException(status_code=422, detail="一次发布最多包含 100 道题")
    seen: set[tuple[str, uuid.UUID]] = set()
    for item in items:
        if item.type not in {"passage", "repeat", "question"}:
            raise HTTPException(status_code=422, detail=f"未知题型：{item.type}")
        if (item.type, item.id) in seen:
            raise HTTPException(status_code=422, detail="指派清单内有重复题目")
        seen.add((item.type, item.id))
        if item.type == "passage":
            obj = session.get(Passage, item.id)
            if obj is None or not obj.is_active:
                raise HTTPException(status_code=404, detail="朗读篇目不存在或已停用")
        elif item.type == "repeat":
            if session.get(RepeatSentence, item.id) is None:
                raise HTTPException(status_code=404, detail="复述句不存在")
        else:
            question = session.get(ScenarioQuestion, item.id)
            if question is None:
                raise HTTPException(status_code=404, detail="问答题不存在")
            scenario = session.get(Scenario, question.scenario_id)
            if scenario is None or not scenario.is_active:
                raise HTTPException(status_code=422, detail="问答题所属主题已停用")


def _assigned_item_objects(
    session: Any, classroom: Classroom
) -> tuple[list[Passage], list[RepeatSentence], list[ScenarioQuestion]] | None:
    """解析按题指派：返回（朗读篇目 / 复述句 / 问答题），对象缺失的自动跳过。

    无按题指派时返回 None（走单元指派路径）。
    """
    if not classroom.assigned_items:
        return None
    passages: list[Passage] = []
    sentences: list[RepeatSentence] = []
    questions: list[ScenarioQuestion] = []
    for spec in classroom.assigned_items:
        kind, item_id = spec.get("type"), spec.get("id")
        if kind == "passage":
            obj = session.get(Passage, uuid.UUID(item_id))
            if obj is not None and obj.is_active:
                passages.append(obj)
        elif kind == "repeat":
            obj = session.get(RepeatSentence, uuid.UUID(item_id))
            if obj is not None:
                sentences.append(obj)
        elif kind == "question":
            obj = session.get(ScenarioQuestion, uuid.UUID(item_id))
            if obj is not None:
                questions.append(obj)
    return passages, sentences, questions


def _snapshot_item(
    session: Any, item_type: str, item_id: uuid.UUID
) -> dict[str, object]:
    """把题目当前内容复制进发布快照。题库后续编辑不影响已发布练习。"""
    if item_type == AttemptItemType.PASSAGE:
        item = session.get(Passage, item_id)
        if item is None or not item.is_active:
            raise HTTPException(status_code=404, detail="朗读篇目不存在或已停用")
        return {
            "type": item_type,
            "id": str(item.id),
            "text": item.text,
            "translation": item.translation,
            "audio_url": item.audio_url,
            "suggested_seconds": item.suggested_seconds,
            "title": item.title,
            "topic": item.topic,
        }
    if item_type == AttemptItemType.REPEAT:
        item = session.get(RepeatSentence, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="复述句不存在")
        return {
            "type": item_type,
            "id": str(item.id),
            "text": item.text,
            "translation": item.translation,
            "audio_url": item.audio_url,
            "suggested_seconds": item.suggested_seconds,
            "replay_limit": item.replay_limit,
        }
    item = session.get(ScenarioQuestion, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="问答题不存在")
    return {
        "type": item_type,
        "id": str(item.id),
        "text": item.text,
        "translation": item.translation,
        "audio_url": item.audio_url,
        "suggested_seconds": item.suggested_seconds,
        "band": item.band,
        "scenario_id": str(item.scenario_id),
    }


def _next_exercise_version(session: Any, classroom_id: uuid.UUID) -> int:
    latest = session.exec(
        select(ClassroomExercise.version_no)
        .where(ClassroomExercise.classroom_id == classroom_id)
        .order_by(col(ClassroomExercise.version_no).desc())
    ).first()
    return (latest or 0) + 1


def _publish_exercise(
    session: Any,
    classroom: Classroom,
    current_user: User,
    snapshots: list[dict[str, object]],
    title: str | None = None,
) -> ClassroomExercise:
    if not snapshots:
        raise HTTPException(status_code=422, detail="练习至少需要包含一道题目")
    exercise_title = (title or "课堂练习").strip()
    if len(exercise_title) > 255:
        raise HTTPException(status_code=422, detail="练习名称不能超过 255 个字符")
    # 同一课堂并发发布时锁住课堂行，避免版本号重复或互相覆盖当前版本。
    session.exec(
        select(Classroom).where(Classroom.id == classroom.id).with_for_update()
    ).first()
    exercise = ClassroomExercise(
        classroom_id=classroom.id,
        version_no=_next_exercise_version(session, classroom.id),
        title=exercise_title or "课堂练习",
        status="published",
        snapshot_items=snapshots,
        created_by=current_user.id,
    )
    session.add(exercise)
    session.flush()
    _archive_current_exercise(session, classroom)
    classroom.current_exercise_id = exercise.id
    classroom.assigned_items = [
        {"type": str(item["type"]), "id": str(item["id"])} for item in snapshots
    ]
    session.add(classroom)
    return exercise


def _archive_current_exercise(session: Any, classroom: Classroom) -> None:
    previous_id = classroom.current_exercise_id
    if previous_id is None:
        return
    previous = session.get(ClassroomExercise, previous_id)
    if previous is not None and previous.status == "published":
        previous.status = "archived"
        previous.archived_at = get_datetime_utc()
        session.add(previous)
    classroom.current_exercise_id = None
    # 恢复自主练习时解绑当日已开始的会话：否则学生会一直读到旧快照，
    # "恢复自主"对当天开练的学生不生效。

    from sqlalchemy import and_

    session.execute(
        update(PracticeSession)
        .where(
            and_(
                PracticeSession.classroom_id == classroom.id,  # ty: ignore[invalid-argument-type]
                PracticeSession.session_date == _today_in_practice_tz(),  # ty: ignore[invalid-argument-type]
                PracticeSession.mode == "daily",  # ty: ignore[invalid-argument-type]
                PracticeSession.assignment_id == previous_id,  # ty: ignore[invalid-argument-type]
            )
        )
        .values(assignment_id=None)
    )


class ExploreRequest(SQLModel):
    unit_id: uuid.UUID


class ExploreStarted(SQLModel):
    session_id: uuid.UUID
    unit_title: str


@router.post("/{code}/explore", response_model=ExploreStarted)
def start_explore(
    session: SessionDep,
    current_user: StudentUserDep,
    code: str,
    body: ExploreRequest,
) -> Any:
    """主题探索：学生选择单元开始/继续当日自由练习轮（不计入课堂完成率）。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    unit = session.get(Unit, body.unit_id)
    if unit is None or not unit.is_active:
        raise HTTPException(status_code=404, detail="Unit not found")
    passage = session.exec(
        select(Passage).where(Passage.unit_id == unit.id, Passage.is_active).limit(1)
    ).first()
    if passage is None:
        raise HTTPException(status_code=404, detail=f"单元「{unit.title}」还没有篇目")
    practice_session = get_or_create_today_session(
        session=session,
        classroom=classroom,
        student=student,
        today=_today_in_practice_tz(),
        passage_id=passage.id,
        mode="explore",
    )
    return {"session_id": practice_session.id, "unit_title": unit.title}
