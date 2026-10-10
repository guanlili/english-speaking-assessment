"""发布与指派：练习版本列表、版本结果、按题/单元指派、自主练习入口。"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from sqlmodel import SQLModel, col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    StudentUserDep,
)
from app.api.routes.class_shared import (
    _get_classroom,
    _repeat_sentences_of_passages,
    _require_classroom_teacher,
    _scenario_for_topic,
    _student_profile_of,
    _today_in_practice_tz,
    router,
)
from app.crud import (
    get_or_create_today_session,
)
from app.models import (
    AssignmentInfo,
    AssignmentItemIn,
    Attempt,
    AttemptItemType,
    AttemptStatus,
    BoardItem,
    ClassroomExercise,
    ClassroomExercisePublic,
    Passage,
    PracticeSession,
    ScenarioQuestion,
    Student,
    Unit,
)
from app.services import exam as exam_service
from app.services import exercise as exercise_service
from app.services import reading

logger = logging.getLogger(__name__)


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
            is_exam=exercise.is_exam,
            time_limit_minutes=exercise.time_limit_minutes,
        )
        for exercise in exercises
    ]


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
    # 模考模式：整场限时（分钟，5–240）；is_exam=true 时必填
    is_exam: bool = False
    time_limit_minutes: int | None = None


class ExerciseStudentResult(SQLModel):
    """单次练习按学生的结果行（发布历史结果页）。"""

    student_id: uuid.UUID
    display_name: str
    suffix: str | None = None
    done_count: int
    total_count: int
    has_pending: bool
    items: list[BoardItem]
    # 模考监考（非考试发布为 null）
    exam_tab_switches: int | None = None
    exam_tab_switch_seconds: int | None = None
    exam_time_used_seconds: int | None = None
    exam_ended: bool | None = None


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

    # 一次批量预取所有会话的作答（替代逐学生查询的 N+1；按 created_at
    # 顺序遍历让后到的作答覆盖 latest，与原逐生查询语义一致）
    latest_by_session: dict[uuid.UUID, dict[uuid.UUID, Attempt]] = {}
    if sessions_by_student:
        for attempt in session.exec(
            select(Attempt)
            .where(
                col(Attempt.session_id).in_(  # type: ignore[operator]
                    [ps.id for ps in sessions_by_student.values()]
                )
            )
            .order_by(col(Attempt.created_at))
        ).all():
            sid = attempt.session_id
            if sid is None:  # in_ 过滤后理论不可达，类型收窄用
                continue
            latest_by_session.setdefault(sid, {})[attempt.item_id] = attempt

    out: list[ExerciseStudentResult] = []
    for student in students:
        ps = sessions_by_student.get(student.id)
        latest: dict[uuid.UUID, Attempt] = {}
        has_pending = False
        if ps is not None:
            latest = latest_by_session.get(ps.id, {})
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
        exam_switches: int | None = None
        exam_switch_seconds: int | None = None
        exam_used: int | None = None
        exam_ended_flag: bool | None = None
        if exercise.is_exam and ps is not None and ps.exam_started_at is not None:
            exam_service.finalize_if_expired(session, ps, exercise)
            exam_switches = ps.tab_switch_count
            exam_switch_seconds = ps.tab_switch_seconds
            exam_used = exam_service.exam_time_used_seconds(ps)
            exam_ended_flag = ps.exam_ended_at is not None
        out.append(
            ExerciseStudentResult(
                student_id=student.id,
                display_name=student.display_name,
                suffix=student.suffix,
                done_count=done,
                total_count=len(exercise.snapshot_items),
                has_pending=has_pending,
                exam_tab_switches=exam_switches,
                exam_tab_switch_seconds=exam_switch_seconds,
                exam_time_used_seconds=exam_used,
                exam_ended=exam_ended_flag,
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
            exercise_service.validate_assignment_items(session, body.items)
            snapshots: list[dict[str, object]] = []
            for item in body.items:
                if item.type == AttemptItemType.PASSAGE:
                    # 拆句篇目展开成逐句快照（validate 已确认行存在且启用）
                    passage = session.get(Passage, item.id)
                    if passage is None:  # validate 之后并发删除的兜底
                        raise HTTPException(
                            status_code=404, detail="朗读篇目不存在或已停用"
                        )
                    snapshots.extend(reading.expand_reading_items(passage))
                else:
                    snapshots.append(
                        exercise_service.build_snapshot_item(
                            session, item.type, item.id
                        )
                    )
            exercise_service.publish_exercise(
                session=session,
                classroom=classroom,
                created_by=current_user.id,
                snapshots=snapshots,
                title=body.title,
                is_exam=body.is_exam,
                time_limit_minutes=body.time_limit_minutes,
                # 指派镜像只存真实题目 ID（合成句子 ID 只进快照）
                assignment_items=[
                    {"type": str(item.type), "id": str(item.id)} for item in body.items
                ],
            )
            classroom.current_unit_id = None  # 按题模式取代单元指派
            # assigned_items 保留（_publish_exercise 已写入）：读取优先快照，
            # 换题用它排除已指派题目、从情景题库取未做过的新题
            session.commit()
            return None
        exercise_service.archive_current_exercise(session, classroom)
        classroom.assigned_items = None
        classroom.current_unit_id = None
        session.add(classroom)
        session.commit()
        return None

    body_update = body.model_dump(exclude_unset=True)
    if "unit_id" in body_update:
        if body_update["unit_id"] is None:
            classroom.current_unit_id = None
            exercise_service.archive_current_exercise(session, classroom)
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
            for p in passages:
                # 拆句篇目逐句展开，未拆分整篇一条（与按题发布同口径）
                snapshots.extend(reading.expand_reading_items(p))
        if classroom.assign_repeat is not False:
            unit_sentences_by_passage = _repeat_sentences_of_passages(session, passages)
            for passage in passages:
                snapshots.extend(
                    exercise_service.build_snapshot_item(
                        session, AttemptItemType.REPEAT, sentence.id
                    )
                    for sentence in unit_sentences_by_passage.get(passage.id, [])
                )
        if classroom.assign_qa is not False:
            # 主题未配情景时跳过问答快照，朗读/复述照常发布（不阻断发布）
            scenario = _scenario_for_topic(session, passages[0].topic)
            if scenario is not None:
                questions = session.exec(
                    select(ScenarioQuestion)
                    .where(ScenarioQuestion.scenario_id == scenario.id)
                    .order_by(col(ScenarioQuestion.order_index))
                ).all()
                snapshots.extend(
                    exercise_service.build_snapshot_item(
                        session, AttemptItemType.QUESTION, question.id
                    )
                    for question in questions
                )
        exercise_service.publish_exercise(
            session=session,
            classroom=classroom,
            created_by=current_user.id,
            snapshots=snapshots,
            title=body.title,
            is_exam=body.is_exam,
            time_limit_minutes=body.time_limit_minutes,
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
