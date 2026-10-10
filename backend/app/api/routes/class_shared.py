"""课堂共享底座：router、常量、共享助手与课堂本体 CRUD（建/删/加入）。"""

import logging
import secrets
import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only
from sqlmodel import col, delete, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    StudentUserDep,
    TeacherUserDep,
)
from app.core.config import settings
from app.crud import (
    ClassroomFullError,
    create_classroom,
    get_classroom_by_code,
    get_or_create_today_session,
    get_student,
    join_classroom,
)
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptStatus,
    Classroom,
    ClassroomCreate,
    ClassroomExercise,
    ClassroomPublic,
    Passage,
    PlanItem,
    PracticeSession,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    Student,
    StudentJoin,
    StudentPublic,
    Unit,
    User,
    VocabularyAnswer,
    VocabularySession,
)
from app.scoring.bands import adjust_band

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


def _repeat_sentences_of_passages(
    session: Any, passages: list[Passage]
) -> dict[uuid.UUID, list[RepeatSentence]]:
    """按篇目批量取复述句（单条 in_ 查询替代逐篇 N+1；句序保持 order_index）。

    调用方按自己的篇目顺序消费分组结果（today 题单/board 骨架/发布快照
    都在学生端或教师发布热路径上）。
    """
    if not passages:
        return {}
    rows = session.exec(
        select(RepeatSentence)
        .where(col(RepeatSentence.passage_id).in_([p.id for p in passages]))
        .order_by(col(RepeatSentence.passage_id), col(RepeatSentence.order_index))
    ).all()
    grouped: dict[uuid.UUID, list[RepeatSentence]] = {}
    for sentence in rows:
        if sentence.passage_id is not None:
            grouped.setdefault(sentence.passage_id, []).append(sentence)
    return grouped


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
    # 全表扫描只为算「单元完成度」与选中篇目：load_only 裁掉正文等大列，
    # 选中后 refresh 补全整行（调用方还要用 text/title 组题单）
    passages = session.exec(
        select(Passage).options(
            load_only(
                Passage.id,  # ty: ignore[invalid-argument-type]
                Passage.unit_id,  # ty: ignore[invalid-argument-type]
                Passage.is_active,  # ty: ignore[invalid-argument-type]
            )
        )
    ).all()
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
    session.refresh(passage)
    return passage


def _scenario_for_topic(session: Any, topic: str) -> Scenario | None:
    """按主题取情景；主题未配置情景时返回 None（调用方降级，不阻断练习）。"""
    return session.exec(select(Scenario).where(Scenario.topic == topic)).first()


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
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
    delete_history: bool = False,
) -> dict[str, str]:
    """删除课堂（本人课堂或管理员）。

    默认保留有作答的课堂；确认清理历史后可删除测试/冗余课堂。
    移出学生的历史仍属于本课堂，账号及其他课堂的数据不受影响。
    """
    classroom = get_classroom_by_code(session=session, code=code.upper())
    if classroom is None:
        raise HTTPException(status_code=404, detail="Classroom not found")
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
        has_vocabulary_answers = (
            session.exec(
                select(VocabularyAnswer.id)
                .join(
                    VocabularySession,
                    col(VocabularyAnswer.session_id) == col(VocabularySession.id),
                )
                .where(VocabularySession.classroom_id == classroom.id)
                .limit(1)
            ).first()
            is not None
        )
        if (has_attempts or has_vocabulary_answers) and not delete_history:
            raise HTTPException(
                status_code=409,
                detail="课堂内已有学生作答记录，不能删除；如需停用请联系管理员在后台操作",
            )
        pending = session.exec(
            select(Attempt.id)
            .where(
                col(Attempt.student_id).in_(student_ids),
                col(Attempt.status).in_([AttemptStatus.QUEUED, AttemptStatus.SCORING]),
            )
            .limit(1)
        ).first()
        if pending is not None:
            raise HTTPException(
                status_code=409, detail="有正在评分中的作答，请稍后再删除"
            )
    # 先删会话，避免级联删除发布时 SET NULL 触发会话唯一键冲突。
    session.exec(
        delete(PracticeSession).where(col(PracticeSession.classroom_id) == classroom.id)
    )  # type: ignore[call-overload]
    session.exec(
        delete(VocabularySession).where(
            col(VocabularySession.classroom_id) == classroom.id
        )
    )  # type: ignore[call-overload]
    classroom.current_exercise_id = None
    session.add(classroom)
    session.flush()
    session.delete(classroom)
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
    """学生（登录态）凭课堂码加入；显示名缺省用账号姓名，重复入班幂等。

    班内档案数达到课堂容量（class_size）→ 409。
    """
    classroom = _get_classroom(session, code)
    try:
        return join_classroom(
            session=session,
            classroom=classroom,
            user=current_user,
            display_name=join_in.display_name,
        )
    except ClassroomFullError:
        raise HTTPException(
            status_code=409,
            detail="班级人数已满，请联系老师调整课堂容量",
        ) from None


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


def _resolve_active_daily_session(
    session: Any,
    classroom: Classroom,
    student: Student,
    today: date,
    passage_id_for_self_practice: uuid.UUID | None = None,
) -> PracticeSession:
    """统一定位当日当前活动会话（today / next-question / board 共用）。

    优先级：
    1. 有 current_exercise_id → 找/建 assignment_id 匹配的会话（按发布快照）
    2. 没有发布 → 找/建 assignment_id IS NULL 的自主练习轮
       - 若无指派单元：用传入的 passage_id（全局首篇）
       - 有指派单元：会话的 passage_id 保持最初锚点，不随单元切换而变
    """
    if classroom.current_exercise_id is not None:
        exercise = session.get(ClassroomExercise, classroom.current_exercise_id)
        anchor_id = None
        if exercise is not None:
            for item in exercise.snapshot_items:
                if item.get("type") == AttemptItemType.PASSAGE:
                    try:
                        # 逐句条目是合成 ID：锚点外键必须落回真实篇目行
                        anchor_id = uuid.UUID(str(item.get("parent_id") or item["id"]))
                    # fmt: skip：括号必须保留——ruff 对 py314 会把括号格式化掉，
                    # 而 PEP 758 裸逗号写法 ≤3.13 的工具链（含系统 python3）无法解析
                    except (KeyError, ValueError):  # fmt: skip
                        pass
                    break
        return get_or_create_today_session(
            session=session,
            classroom=classroom,
            student=student,
            today=today,
            passage_id=anchor_id,
            assignment_id=classroom.current_exercise_id,
        )
    # 自主练习：passage_id 用调用方计算的锚点，或按单元/全局取首篇
    if passage_id_for_self_practice is None:
        passage_id_for_self_practice = _active_passage(session, student).id
    return get_or_create_today_session(
        session=session,
        classroom=classroom,
        student=student,
        today=today,
        passage_id=passage_id_for_self_practice,
        assignment_id=None,
    )


def _parse_snapshot_plan_items(
    snapshot_items: list[dict[str, object]],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    """把快照拆分为 (passage, repeat, question) 三份；不依赖题库是否还存在。"""
    ps, rs, qs = [], [], []
    for item in snapshot_items:
        t = str(item.get("type", ""))
        if t == AttemptItemType.PASSAGE:
            ps.append(item)
        elif t == AttemptItemType.REPEAT:
            rs.append(item)
        elif t == AttemptItemType.QUESTION:
            qs.append(item)
    return ps, rs, qs


def _snapshot_int(value: object | None, default: int) -> int:
    """快照数值字段转 int：缺失/非法/0 用 default 兜底。"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value or default
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                return int(stripped)
            except ValueError:
                pass
    return default


def _snapshot_optional_int(value: object | None) -> int | None:
    """快照可空数值字段转 int：None → None，其余转 int。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                return int(stripped)
            except ValueError:
                pass
    return None


def _snapshot_uuid(value: object | None) -> uuid.UUID | None:
    """快照可空 UUID 字段：None/非法 → None（逐句条目的 parent_id 用）。"""
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    # fmt: skip：括号必须保留——ruff 对 py314 会把括号格式化掉，
    # 而 PEP 758 裸逗号写法 ≤3.13 的工具链（含系统 python3）无法解析
    except (ValueError, TypeError):  # fmt: skip
        return None


def _snapshot_items_of(
    snapshot_items: list[dict[str, object]] | None,
    item_type: str,
) -> list[dict[str, object]]:
    """按题型取快照条目（散布在 today/board/runtime 的 type 过滤统一入口）。"""
    return [item for item in (snapshot_items or []) if item.get("type") == item_type]


def _snapshot_item_by_id(
    snapshot_items: list[dict[str, object]] | None,
    item_type: str,
    item_id: uuid.UUID | str,
) -> dict[str, object] | None:
    """按题型 + id 找单条快照（id 走 str 比较，兼容 UUID/字符串两种来源）。"""
    return next(
        (
            item
            for item in (snapshot_items or [])
            if item.get("type") == item_type and str(item.get("id")) == str(item_id)
        ),
        None,
    )


def _plan_item_from_snapshot(
    item: dict[str, object],
    listen_counts: dict[uuid.UUID, int] | None = None,
    ack_times: dict[uuid.UUID, datetime] | None = None,
) -> PlanItem | None:
    """把快照条目 / 作答题目快照转成 PlanItem，不依赖活题库。

    换来的题（题单外已作答项）也从 attempt.item_snapshot 重建，
    保证刷新后仍在题单中、结果页能展示。
    """
    t = str(item.get("type", ""))
    if t not in {
        AttemptItemType.PASSAGE,
        AttemptItemType.REPEAT,
        AttemptItemType.QUESTION,
        AttemptItemType.INSTRUCTION,
    }:
        return None
    try:
        item_id = uuid.UUID(str(item.get("id", "")))
    # fmt: skip：同上，括号保留兼容 ≤3.13 工具链
    except (ValueError, TypeError):  # fmt: skip
        return None
    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    cue_bullets = item.get("cue_card_bullets")
    prep = _snapshot_optional_int(item.get("prep_seconds"))
    acked_at = (ack_times or {}).get(item_id)
    return PlanItem(
        type=t,
        id=item_id,
        text=text,
        title=(
            str(item["title"])
            if t == AttemptItemType.INSTRUCTION and item.get("title") is not None
            else None
        ),
        translation=(
            str(item["translation"]) if item.get("translation") is not None else None
        ),
        audio_url=(
            str(item["audio_url"]) if item.get("audio_url") is not None else None
        ),
        suggested_seconds=_snapshot_int(item.get("suggested_seconds"), 20),
        band=(str(item["band"]) if item.get("band") is not None else None),
        replay_limit=_snapshot_optional_int(item.get("replay_limit")),
        listen_used=(
            (listen_counts or {}).get(item_id, 0)
            if t == AttemptItemType.REPEAT
            else None
        ),
        # 题目说明的「继续」确认时间（null=未读）
        acked_at=(
            acked_at.isoformat()
            if t == AttemptItemType.INSTRUCTION and acked_at is not None
            else None
        ),
        # 分级题型训练（可空=普通课堂内容）
        exam_kind=(
            str(item["exam_kind"]) if item.get("exam_kind") is not None else None
        ),
        exam_level=(
            str(item["exam_level"]) if item.get("exam_level") is not None else None
        ),
        cue_card_bullets=(
            [str(b) for b in cue_bullets]
            if isinstance(cue_bullets, list) and cue_bullets
            else None
        ),
        prep_seconds=prep,
        # 逐句朗读条目（文章拆句展开）：真实篇目 ID 与句序
        parent_id=_snapshot_uuid(item.get("parent_id")),
        sentence_index=_snapshot_optional_int(item.get("sentence_index")),
        sentence_total=_snapshot_optional_int(item.get("sentence_total")),
    )


def _repeat_attempts_from_snapshot(
    session: Any,
    practice_session: PracticeSession,
    repeat_snapshot_ids: list[uuid.UUID],
) -> list[Attempt]:
    """基于快照中的复述句 ID 集合取最新作答（用于升降档计算，不要求句子还存在）。"""
    if not repeat_snapshot_ids:
        return []
    attempts = session.exec(
        select(Attempt)
        .where(
            Attempt.session_id == practice_session.id,
            Attempt.item_type == AttemptItemType.REPEAT,
            col(Attempt.item_id).in_(repeat_snapshot_ids),
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
    session: Any,
    practice_session: PracticeSession,
    student: Student,
    repeat_count_override: int | None = None,
    done_repeat_override: list[Attempt] | None = None,
) -> str:
    """本轮复述句全部 done 后，按平均完整度/流利度调整问答档（US-05）。

    调整同时写回 student.current_band（下一轮沿用）与 session.question_band。
    未完成复述时沿用会话档位。

    repeat_count_override / done_repeat_override：
    发布会话使用快照中的复述句数量/作答（不要求复述句/篇目仍在题库中）。
    """
    if practice_session.question_band is not None:
        return practice_session.question_band

    if repeat_count_override is not None and done_repeat_override is not None:
        expected_repeats = repeat_count_override
        repeats = done_repeat_override
    else:
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
        expected_repeats = len(sentences)
        repeats = _repeat_attempts_of_session(session, practice_session)

    done = [a for a in repeats if a.status == AttemptStatus.DONE]
    if expected_repeats == 0 or len(done) < expected_repeats:
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
