"""课堂大屏 PK「房间码」接口：开房、凭码入场、作答与主持端大屏快照。

路径前缀 `/classes/{code}/vocabulary/room`。

权限口径：开房/开始/结束/大屏快照仅本班教师；学生凭 6 位码入场后只能读
自己的视图与提交当前题。跨班访问 404，不泄露存在性。

实时口径：不新增 SSE；主持端按 1.5 秒轮询 `board`，学生端按 1 秒轮询 `me`，
两侧读同一套服务端时钟。容量验收（40 人同场 P95）沿用既有探针脚本，另行跑。
"""

import uuid

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.classes import _get_classroom
from app.models import (
    PkRoomAnswerRequest,
    PkRoomAnswerResult,
    PkRoomCreate,
    PkRoomHostView,
    PkRoomJoin,
    PkRoomStudentView,
)
from app.services import vocabulary_pk as pk_service
from app.services import vocabulary_room as room_service

router = APIRouter()


def _viewer(session: SessionDep, code: str, current_user: CurrentUser):
    from app.services import entitlement

    classroom = _get_classroom(session, code)
    role, student = pk_service.resolve_viewer(session, classroom, current_user)
    entitlement.ensure_module_enabled(session, current_user.tenant_id, "vocabulary")
    return classroom, role, student


def _require_teacher_role(role: str) -> None:
    if role != "teacher":
        raise HTTPException(status_code=403, detail="只有本班教师可以主持大屏 PK")


@router.post("/classes/{code}/vocabulary/room", response_model=PkRoomHostView)
def create_pk_room(
    session: SessionDep,
    code: str,
    body: PkRoomCreate,
    current_user: CurrentUser,
):
    classroom, role, _student = _viewer(session, code, current_user)
    _require_teacher_role(role)
    room = room_service.create_room(
        session,
        classroom,
        current_user,
        book_id=body.book_id,
        question_count=body.question_count,
        per_question_seconds=body.per_question_seconds,
        prompt_types=body.prompt_types,
        mode=body.mode,
        team_count=body.team_count,
    )
    return room_service.host_view(session, room)


@router.get(
    "/classes/{code}/vocabulary/room/current",
    response_model=PkRoomHostView | None,
)
def read_current_pk_room(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
):
    classroom, role, _student = _viewer(session, code, current_user)
    _require_teacher_role(role)
    room = room_service.current_room(session, classroom, current_user)
    return None if room is None else room_service.host_view(session, room)


@router.post(
    "/classes/{code}/vocabulary/room/{room_id}/start",
    response_model=PkRoomHostView,
)
def start_pk_room(
    session: SessionDep,
    code: str,
    room_id: uuid.UUID,
    current_user: CurrentUser,
):
    classroom, role, _student = _viewer(session, code, current_user)
    _require_teacher_role(role)
    room = room_service.get_room(session, classroom.id, room_id)
    room_service.start_room(session, classroom, room, current_user)
    return room_service.host_view(session, room)


@router.post(
    "/classes/{code}/vocabulary/room/{room_id}/end",
    response_model=PkRoomHostView,
)
def end_pk_room(
    session: SessionDep,
    code: str,
    room_id: uuid.UUID,
    current_user: CurrentUser,
):
    classroom, role, _student = _viewer(session, code, current_user)
    _require_teacher_role(role)
    room = room_service.get_room(session, classroom.id, room_id)
    room_service.end_room(session, classroom, room, current_user)
    return room_service.host_view(session, room)


@router.get(
    "/classes/{code}/vocabulary/room/{room_id}/board",
    response_model=PkRoomHostView,
)
def read_pk_room_board(
    session: SessionDep,
    code: str,
    room_id: uuid.UUID,
    current_user: CurrentUser,
):
    classroom, role, _student = _viewer(session, code, current_user)
    _require_teacher_role(role)
    room = room_service.get_room(session, classroom.id, room_id)
    return room_service.host_view(session, room)


@router.post("/classes/{code}/vocabulary/room/join", response_model=PkRoomStudentView)
def join_pk_room(
    session: SessionDep,
    code: str,
    body: PkRoomJoin,
    current_user: CurrentUser,
):
    classroom, _role, student = _viewer(session, code, current_user)
    if student is None:
        raise HTTPException(status_code=403, detail="只有本班学生可以入场")
    room = room_service.join_room(session, classroom, student, body.code)
    return room_service.student_view(session, room, student)


@router.get(
    "/classes/{code}/vocabulary/room/{room_id}/me",
    response_model=PkRoomStudentView,
)
def read_pk_room_as_student(
    session: SessionDep,
    code: str,
    room_id: uuid.UUID,
    current_user: CurrentUser,
):
    classroom, _role, student = _viewer(session, code, current_user)
    if student is None:
        raise HTTPException(status_code=403, detail="只有本班学生可以入场")
    room = room_service.get_room(session, classroom.id, room_id)
    return room_service.student_view(session, room, student)


@router.post(
    "/classes/{code}/vocabulary/room/{room_id}/answers",
    response_model=PkRoomAnswerResult,
)
def answer_pk_room(
    session: SessionDep,
    code: str,
    room_id: uuid.UUID,
    body: PkRoomAnswerRequest,
    current_user: CurrentUser,
):
    classroom, _role, student = _viewer(session, code, current_user)
    if student is None:
        raise HTTPException(status_code=403, detail="只有本班学生可以作答")
    room = room_service.get_room(session, classroom.id, room_id)
    return room_service.submit_answer(
        session,
        room,
        student,
        item_index=body.item_index,
        answer=body.answer,
    )
