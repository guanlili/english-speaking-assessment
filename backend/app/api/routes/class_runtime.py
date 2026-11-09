"""练习运行时：模考开始/切屏上报、复述听音计数、题目说明确认。"""

import logging
import uuid
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, select

from app.api.deps import (
    SessionDep,
    StudentUserDep,
)
from app.api.routes.class_shared import (
    _get_classroom,
    _snapshot_item_by_id,
    _student_profile_of,
    router,
)
from app.models import (
    Attempt,
    AttemptItemType,
    Classroom,
    ClassroomExercise,
    ExamStatus,
    InstructionAck,
    PracticeSession,
    RepeatSentence,
    Student,
    get_datetime_utc,
)
from app.services import exam as exam_service
from app.services import exam_flow

logger = logging.getLogger(__name__)


class ListenRequest(SQLModel):
    session_id: uuid.UUID
    item_id: uuid.UUID


class ListenResult(SQLModel):
    listen_used: int
    replay_limit: int  # 0 = 不限


class AckRequest(SQLModel):
    """题目说明「继续」确认请求。"""

    session_id: uuid.UUID
    item_id: uuid.UUID


class AckResult(SQLModel):
    acked: bool
    acked_at: str


class ExamStartRequest(SQLModel):
    session_id: uuid.UUID


class ExamViolationRequest(SQLModel):
    session_id: uuid.UUID
    # 切回（visible 相位）携带本次离屏秒数；缺省 = 离开（hidden 相位）计数
    away_seconds: int | None = None


class ExamViolationResult(SQLModel):
    tab_switch_count: int
    tab_switch_seconds: int = 0


def _exam_session_of(
    session: SessionDep,
    classroom: Classroom,
    student: Student,
    exam_session_id: uuid.UUID,
) -> tuple[PracticeSession, ClassroomExercise]:
    """定位本人绑定当前发布的考试会话；不存在/非模考一律 4xx。"""
    practice_session = session.get(PracticeSession, exam_session_id)
    if (
        practice_session is None
        or practice_session.student_id != student.id
        or practice_session.classroom_id != classroom.id
    ):
        raise HTTPException(status_code=404, detail="Session not found")
    if practice_session.assignment_id is None:
        raise HTTPException(status_code=422, detail="该练习不是模考")
    exercise = session.get(ClassroomExercise, practice_session.assignment_id)
    if exercise is None or not exercise.is_exam:
        raise HTTPException(status_code=422, detail="该练习不是模考")
    return practice_session, exercise


class ExamRuntimeState(SQLModel):
    session_id: uuid.UUID
    exam: ExamStatus
    submitted_item_ids: list[uuid.UUID]


@router.get("/{code}/exam/state", response_model=ExamRuntimeState)
def read_exam_state(
    session: SessionDep,
    code: str,
    session_id: uuid.UUID,
    current_user: StudentUserDep,
) -> ExamRuntimeState:
    """考试轮询只返回阶段/时钟与已提交题 ID，题目始终来自初次加载的发布快照。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    ps, exercise = _exam_session_of(session, classroom, student, session_id)
    exam_service.finalize_if_expired(session, ps, exercise)
    submitted = session.exec(
        select(Attempt.item_id).where(Attempt.session_id == ps.id).distinct()
    ).all()
    return ExamRuntimeState(
        session_id=ps.id,
        exam=exam_service.exam_status_payload(session, ps, exercise),
        submitted_item_ids=list(submitted),
    )


@router.post("/{code}/exam/start", response_model=ExamStatus)
def start_exam(
    session: SessionDep,
    code: str,
    body: ExamStartRequest,
    current_user: StudentUserDep,
) -> Any:
    """开考确认页显式开考：落开始时间并返回考试状态（幂等，重复调用不重置计时）。

    仅本人考试会话有效；到时后再调用返回已结束状态。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    practice_session, exercise = _exam_session_of(
        session, classroom, student, body.session_id
    )
    exam_service.ensure_exam_started(session, practice_session, exercise)
    exam_service.finalize_if_expired(session, practice_session, exercise)
    return exam_service.exam_status_payload(session, practice_session, exercise)


@router.post("/{code}/exam/violation", response_model=ExamViolationResult)
def report_exam_violation(
    session: SessionDep,
    code: str,
    body: ExamViolationRequest,
    current_user: StudentUserDep,
) -> Any:
    """防切屏上报：hidden 相位计数 +1；visible 相位带 away_seconds 累计离屏时长。

    仅本人考试会话有效；未开考/考试结束后拒绝（不再累计）。
    """
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    practice_session, exercise = _exam_session_of(
        session, classroom, student, body.session_id
    )
    if body.away_seconds is None:
        count = exam_service.record_tab_switch(session, practice_session, exercise)
        return ExamViolationResult(
            tab_switch_count=count,
            tab_switch_seconds=practice_session.tab_switch_seconds,
        )
    count, seconds = exam_service.record_tab_return(
        session, practice_session, exercise, body.away_seconds
    )
    return ExamViolationResult(tab_switch_count=count, tab_switch_seconds=seconds)


def _listen_session_and_sentence(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    body: ListenRequest,
) -> tuple[PracticeSession, RepeatSentence, Student]:
    """取本人会话与本句；任一对不上或句子不属于本租户一律 404。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    practice_session = session.get(PracticeSession, body.session_id)
    if practice_session is None or practice_session.student_id != student.id:
        raise HTTPException(status_code=404, detail="Session not found")
    sentence = session.get(RepeatSentence, body.item_id)
    if sentence is None or sentence.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Sentence not found")
    return practice_session, sentence, student


def _listen_replay_limit(
    session: SessionDep, practice_session: PracticeSession, sentence: RepeatSentence
) -> int:
    """可重听次数：有作业发布时以快照为准，否则以篇目归属为准；缺设置 422。"""
    replay_limit: int | None = sentence.replay_limit
    if practice_session.assignment_id is not None:
        exercise = session.get(ClassroomExercise, practice_session.assignment_id)
        snapshot = _snapshot_item_by_id(
            exercise.snapshot_items if exercise is not None else None,
            AttemptItemType.REPEAT,
            sentence.id,
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
    return replay_limit


def _listen_params(
    practice_session: PracticeSession, student: Student, sentence: RepeatSentence
) -> dict:
    """UPSERT 参数；每次调用新生成主键，便于冲突时走 ON CONFLICT 分支。"""
    return {
        "iid": uuid.uuid4(),
        "tid": practice_session.tenant_id,  # C2：作用域含租户（随会话行）
        "sid": student.id,
        "sess": practice_session.id,
        "item": sentence.id,
    }


def _listen_unlimited(session: SessionDep, params: dict) -> int:
    """不限次：直接原子自增（原生 UPSERT，并发安全）。"""
    used = session.execute(  # ty: ignore[deprecated]
        text(
            "INSERT INTO item_listen"
            " (tenant_id, id, student_id, session_id, item_id, count)"
            " VALUES (:tid, :iid, :sid, :sess, :item, 1)"
            " ON CONFLICT ON CONSTRAINT uq_item_listen_scope"
            " DO UPDATE SET count = item_listen.count + 1"
            " RETURNING count"
        ),
        params,
    ).scalar_one()
    session.commit()
    return used


def _listen_limited(session: SessionDep, params: dict, replay_limit: int) -> int:
    """有限次：原子自增 + WHERE 上限保护；到上限时 UPDATE 不执行、无返回行。"""
    result = session.execute(  # ty: ignore[deprecated]
        text(
            "INSERT INTO item_listen"
            " (tenant_id, id, student_id, session_id, item_id, count)"
            " VALUES (:tid, :iid, :sid, :sess, :item, 1)"
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
        logger.warning(
            "listen replay limit reached (or insert returned no row) "
            "student=%s session=%s item=%s",
            params["sid"],
            params["sess"],
            params["item"],
        )
        raise HTTPException(
            status_code=422,
            detail=f"可重听次数已用完（{replay_limit} 次）",
        )
    session.commit()
    return result


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
    practice_session, sentence, student = _listen_session_and_sentence(
        session, code, current_user, body
    )
    replay_limit = _listen_replay_limit(session, practice_session, sentence)
    params = _listen_params(practice_session, student, sentence)
    if replay_limit == 0:
        used = _listen_unlimited(session, params)
        return ListenResult(listen_used=used, replay_limit=0)
    used = _listen_limited(session, params, replay_limit)
    return ListenResult(listen_used=used, replay_limit=replay_limit)


def _ack_session_and_snapshot(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    body: AckRequest,
) -> tuple[PracticeSession, ClassroomExercise | None, Student]:
    """取本人会话与说明快照；说明只随按题发布进卷子，不在快照里一律 422。"""
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    practice_session = session.get(PracticeSession, body.session_id)
    if practice_session is None or practice_session.student_id != student.id:
        raise HTTPException(status_code=404, detail="Session not found")
    # 说明只随按题发布进卷子：必须在会话绑定的发布快照里
    if practice_session.assignment_id is None:
        raise HTTPException(status_code=422, detail="题目说明不在本轮练习内")
    exercise = session.get(ClassroomExercise, practice_session.assignment_id)
    snapshot = _snapshot_item_by_id(
        exercise.snapshot_items if exercise is not None else None,
        AttemptItemType.INSTRUCTION,
        body.item_id,
    )
    if snapshot is None:
        raise HTTPException(status_code=422, detail="题目说明不在本轮练习内")
    return practice_session, exercise, student


def _find_instruction_ack(
    session: SessionDep,
    student: Student,
    practice_session: PracticeSession,
    item_id: uuid.UUID,
) -> InstructionAck | None:
    """按 学生×本轮×题目 取已确认记录（唯一约束保证至多一条）。"""
    return session.exec(
        select(InstructionAck).where(
            InstructionAck.student_id == student.id,  # type: ignore[arg-type]
            InstructionAck.session_id == practice_session.id,  # type: ignore[arg-type]
            InstructionAck.item_id == item_id,  # type: ignore[arg-type]
        )
    ).first()


def _ack_result(ack: InstructionAck | None) -> AckResult:
    """已确认结果；事件行缺失或 created_at 为空时用当前时间兜底。"""
    acked_at = (ack.created_at if ack is not None and ack.created_at else None) or (
        get_datetime_utc()
    )
    return AckResult(acked=True, acked_at=acked_at.isoformat())


@router.post("/{code}/acks", response_model=AckResult)
def record_instruction_ack(
    session: SessionDep,
    current_user: StudentUserDep,
    code: str,
    body: AckRequest,
) -> Any:
    """题目说明「继续」确认：幂等记录已读；模考下校验说明窗口已开（防跳读）。"""
    practice_session, exercise, student = _ack_session_and_snapshot(
        session, code, current_user, body
    )
    existing = _find_instruction_ack(session, student, practice_session, body.item_id)
    if existing is not None:
        # 幂等：已确认过的说明直接返回（不再过模考窗口门禁）
        return _ack_result(existing)

    if exercise is not None and exercise.is_exam:
        exam_service.require_instruction_current(
            session, practice_session, exercise, body.item_id
        )

    ack = InstructionAck(
        student_id=student.id,
        session_id=practice_session.id,
        item_id=body.item_id,
    )
    session.add(ack)
    try:
        session.commit()
    except IntegrityError:
        # 并发双击：唯一约束兜底，按已确认处理
        session.rollback()
    else:
        session.refresh(ack)
        return _ack_result(ack)
    return _ack_result(
        _find_instruction_ack(session, student, practice_session, body.item_id)
    )


class ExamFlowEvent(SQLModel):
    session_id: uuid.UUID
    item_id: uuid.UUID
    event: Literal["audio-ended", "next"]


@router.post("/{code}/exam/flow", response_model=ExamStatus)
def advance_exam_flow(
    session: SessionDep, code: str, body: ExamFlowEvent, current_user: StudentUserDep
) -> Any:
    classroom = _get_classroom(session, code)
    student = _student_profile_of(session, classroom, current_user)
    ps, exercise = _exam_session_of(session, classroom, student, body.session_id)
    if not exam_flow.enabled(exercise):
        raise HTTPException(
            status_code=422, detail="Automated exam flow is not enabled"
        )
    exam_flow.apply_event(
        session, ps, exercise, body.item_id, body.event, exam_service._now()
    )
    return exam_service.exam_status_payload(session, ps, exercise)
