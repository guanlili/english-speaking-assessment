"""粗分档自适应小测（placement）接口。

路径前缀 `/classes/{code}/vocabulary/placement`。

权限口径：
- 开始 / 作答 / 本人历史：仅本班学生（学生档案解析 404 先于模块 403）；
- 结果列表：本班主教师 / 共管教师 / 本校管理员只读；跨班按不存在 404 处理；
- 本测是 vocabulary 子能力，不单独开关，模块闸门沿用 ``vocabulary``。

边界：placement 作答不触发 FSRS 调度、不推进农场 XP、不计入任务/自主练习
统计；结果只作教学参考，不是定级或考试分数。
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep, StudentUserDep
from app.api.routes.classes import (
    _get_classroom,
    _require_classroom_teacher,
    _student_profile_of,
)
from app.models import (
    PLACEMENT_KIND,
    PlacementAnswerRequest,
    PlacementAnswerResponse,
    PlacementHistoryResponse,
    PlacementResultPublic,
    PlacementStartResponse,
    VocabularySession,
)
from app.services import vocab_placement

router = APIRouter()


def _student_context(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
    *,
    read_only: bool = False,
):
    classroom = _get_classroom(session, code)
    student = _student_profile_of(
        session, classroom, current_user, "vocabulary", read_only=read_only
    )
    return classroom, student


@router.post(
    "/classes/{code}/vocabulary/placement/start",
    response_model=PlacementStartResponse,
)
def start_placement(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
) -> Any:
    """开始 / 续做一次粗分档小测；已有进行中轮次直接续做。"""
    _classroom, student = _student_context(session, code, current_user)
    return vocab_placement.start_or_resume(session, _classroom.id, student)


@router.post(
    "/classes/{code}/vocabulary/placement/sessions/{session_id}/answer",
    response_model=PlacementAnswerResponse,
)
def answer_placement(
    session: SessionDep,
    code: str,
    session_id: uuid.UUID,
    body: PlacementAnswerRequest,
    current_user: StudentUserDep,
) -> Any:
    """提交首答（每题一次）：返回正误 + 下一题或最终建议。"""
    _classroom, student = _student_context(session, code, current_user)
    vocab_session = session.get(VocabularySession, session_id)
    if (
        vocab_session is None
        or vocab_session.classroom_id != _classroom.id
        or vocab_session.student_id != student.id
        or vocab_session.kind != PLACEMENT_KIND
    ):
        raise HTTPException(status_code=404, detail="placement_session_not_found")
    return vocab_placement.submit_answer(
        session,
        vocab_session,
        item_index=body.item_index,
        answer_raw=body.answer,
        idempotency_key=body.idempotency_key,
    )


@router.get(
    "/classes/{code}/vocabulary/placement/history",
    response_model=PlacementHistoryResponse,
)
def placement_history(
    session: SessionDep,
    code: str,
    current_user: StudentUserDep,
) -> Any:
    """本人全部测次（重测保留历史，按时间倒序）。"""
    _classroom, student = _student_context(session, code, current_user, read_only=True)
    items = vocab_placement.student_history_public(session, student)
    return PlacementHistoryResponse(items=items)


@router.get(
    "/classes/{code}/vocabulary/placement/results",
    response_model=list[PlacementResultPublic],
)
def placement_results(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
) -> Any:
    """教师 / 管理员只读：本班学生最近一次测次，仅作教学参考。"""
    classroom = _get_classroom(session, code)
    _require_classroom_teacher(classroom, current_user, "vocabulary", read_only=True)
    return vocab_placement.teacher_results(session, classroom.id)
