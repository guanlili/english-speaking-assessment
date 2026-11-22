"""课堂实时 PK 接口：大厅、排队配对、对局作答、结算、断线恢复与 SSE 推送。

路径前缀 `/classes/{code}/vocabulary/pk`。

权限口径（设计稿 §2）：
- 大厅/对局仅本课堂成员与本班教师可读；跨班访问 404，不泄露存在性。
- 开/关大厅仅本班教师；学生显式「加入 PK」，未参与不影响任务完成度。
- PK 作答独立落库，不写 ``VocabularyAnswer``、不改任务首答统计。

实时通道（设计稿 §1.2）：SSE 推送状态版本变化；SSE 建连失败/断流由前端
切 1.5 秒轮询，轮询与 SSE 读同一套快照接口，行为一致。不引入 Redis。
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.classes import _get_classroom
from app.core import db as _db
from app.models import (
    PkAnswerRequest,
    PkLobbyCreate,
    PkLobbyView,
    PkMatchView,
)
from app.services import vocabulary_pk as pk_service

logger = logging.getLogger(__name__)

router = APIRouter()

# SSE 单连接最长生命期（秒）：到期客户端自动重连（设计稿 §1.2）
SSE_MAX_LIFETIME_SECONDS = 300
SSE_POLL_INTERVAL_SECONDS = 1.0
SSE_HEARTBEAT_SECONDS = 15


def _viewer(session: SessionDep, code: str, current_user: CurrentUser):
    """解析课堂与访问者身份；返回 (classroom, role, student)。"""
    classroom = _get_classroom(session, code)
    role, student = pk_service.resolve_viewer(session, classroom, current_user)
    return classroom, role, student


@router.get("/classes/{code}/vocabulary/pk/lobby", response_model=PkLobbyView)
def read_pk_lobby(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
):
    classroom, _role, student = _viewer(session, code, current_user)
    return pk_service.lobby_view(session, classroom, student)


@router.post("/classes/{code}/vocabulary/pk/lobby", response_model=PkLobbyView)
def open_pk_lobby(
    session: SessionDep,
    code: str,
    body: PkLobbyCreate,
    current_user: CurrentUser,
):
    classroom, role, _student = _viewer(session, code, current_user)
    if role != "teacher":
        raise HTTPException(status_code=403, detail="只有本班教师可以开启 PK 大厅")
    pk_service.open_lobby(
        session,
        classroom,
        current_user,
        book_id=body.book_id,
        question_count=body.question_count,
        per_question_seconds=body.per_question_seconds,
        prompt_types=body.prompt_types,
    )
    return pk_service.lobby_view(session, classroom, None)


@router.patch("/classes/{code}/vocabulary/pk/lobby/close", response_model=PkLobbyView)
def close_pk_lobby(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
):
    classroom, role, _student = _viewer(session, code, current_user)
    if role != "teacher":
        raise HTTPException(status_code=403, detail="只有本班教师可以关闭 PK 大厅")
    pk_service.close_lobby(session, classroom, current_user)
    return pk_service.lobby_view(session, classroom, None)


@router.post("/classes/{code}/vocabulary/pk/lobby/join", response_model=PkLobbyView)
def join_pk_lobby(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
):
    classroom, _role, student = _viewer(session, code, current_user)
    if student is None:
        raise HTTPException(status_code=403, detail="只有本班学生可以加入 PK")
    pk_service.join_lobby(session, classroom, student)
    return pk_service.lobby_view(session, classroom, student)


@router.delete("/classes/{code}/vocabulary/pk/lobby/join", response_model=PkLobbyView)
def leave_pk_lobby(
    session: SessionDep,
    code: str,
    current_user: CurrentUser,
):
    classroom, _role, student = _viewer(session, code, current_user)
    if student is None:
        raise HTTPException(status_code=403, detail="只有本班学生可以离开 PK")
    pk_service.leave_lobby(session, classroom, student)
    return pk_service.lobby_view(session, classroom, student)


def _load_match_for_student(session: SessionDep, match_id: uuid.UUID, student):
    return pk_service.get_match_for_player(session, match_id, student)


@router.get(
    "/classes/{code}/vocabulary/pk/matches/{match_id}",
    response_model=PkMatchView,
)
def read_pk_match(
    session: SessionDep,
    code: str,
    match_id: uuid.UUID,
    current_user: CurrentUser,
):
    classroom, _role, student = _viewer(session, code, current_user)
    if student is None:
        raise HTTPException(status_code=403, detail="只有本局玩家可以查看对局")
    match, me, opponent = _load_match_for_student(session, match_id, student)
    # 跨班兜底：对局所属课堂必须与当前课堂一致
    if match.classroom_id != classroom.id:
        raise HTTPException(status_code=404, detail="对局不存在")
    return pk_service.match_view(session, match, me, opponent)


@router.get(
    "/classes/{code}/vocabulary/pk/matches/{match_id}/state",
    response_model=PkMatchView,
)
def read_pk_match_state(
    session: SessionDep,
    code: str,
    match_id: uuid.UUID,
    current_user: CurrentUser,
):
    """轮询快照：与 SSE 读同一套 match_view（降级路径行为一致）。"""
    return read_pk_match(session, code, match_id, current_user)


@router.post(
    "/classes/{code}/vocabulary/pk/matches/{match_id}/answers",
)
def submit_pk_answer(
    session: SessionDep,
    code: str,
    match_id: uuid.UUID,
    body: PkAnswerRequest,
    current_user: CurrentUser,
):
    classroom, _role, student = _viewer(session, code, current_user)
    if student is None:
        raise HTTPException(status_code=403, detail="只有本局玩家可以作答")
    match, me, _opponent = _load_match_for_student(session, match_id, student)
    if match.classroom_id != classroom.id:
        raise HTTPException(status_code=404, detail="对局不存在")
    return pk_service.submit_answer(
        session,
        match,
        me,
        item_index=body.item_index,
        prompt_type=body.prompt_type,
        answer_raw=body.answer,
        idempotency_key=body.idempotency_key,
    )


@router.get("/classes/{code}/vocabulary/pk/matches/{match_id}/events")
async def pk_match_events(
    session: SessionDep,
    code: str,
    match_id: uuid.UUID,
    current_user: CurrentUser,
):
    """SSE 推送：状态版本变化时下发最新快照；心跳保活；5 分钟到期重连。"""
    classroom, _role, student = _viewer(session, code, current_user)
    if student is None:
        raise HTTPException(status_code=403, detail="只有本局玩家可以订阅对局")
    match, me, _opponent = _load_match_for_student(session, match_id, student)
    if match.classroom_id != classroom.id:
        raise HTTPException(status_code=404, detail="对局不存在")

    def _snapshot_for(player_id: uuid.UUID) -> dict:
        with Session(_db.engine) as fresh:
            fresh_match = fresh.get(type(match), match.id)
            fresh_player = fresh.get(type(me), player_id)
            if fresh_match is None or fresh_player is None:
                raise HTTPException(status_code=404, detail="对局不存在")
            return pk_service.match_state_snapshot(fresh, fresh_match, fresh_player)

    initial = _snapshot_for(me.id)
    last_version = initial.get("state_version")

    async def stream():
        nonlocal last_version
        yield f"event: state\ndata: {json.dumps(initial, ensure_ascii=False)}\n\n"
        deadline = datetime.now(UTC).timestamp() + SSE_MAX_LIFETIME_SECONDS
        last_heartbeat = datetime.now(UTC).timestamp()
        while datetime.now(UTC).timestamp() < deadline:
            await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)
            try:
                snapshot = await asyncio.to_thread(_snapshot_for, me.id)
                if snapshot.get("state_version") != last_version:
                    last_version = snapshot.get("state_version")
                    yield (
                        f"event: state\ndata: "
                        f"{json.dumps(snapshot, ensure_ascii=False)}\n\n"
                    )
            except Exception:  # noqa: BLE001 - 推送异常不断开连接，下一轮重试
                logger.warning("PK SSE snapshot refresh failed", exc_info=True)
            now_ts = datetime.now(UTC).timestamp()
            if now_ts - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
                last_heartbeat = now_ts
                yield ": ping\n\n"

    headers = {
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=headers,
    )
