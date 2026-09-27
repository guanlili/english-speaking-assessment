"""通用作答接口：上传录音立即返回 queued，轮询获取反馈。

POST /attempts      上传音频（multipart），任何题型（PRD 附录 A）
GET  /attempts/{id} 轮询转写与分数
"""

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import OptionalCurrentUser, ScoringSubmitter, SessionDep
from app.core.config import settings
from app.core.security import verify_student_token
from app.core.storage import save_audio_file
from app.crud import create_attempt, get_attempt, get_student
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptPublic,
    AttemptStatus,
    Classroom,
    Passage,
    PracticeSession,
    RepeatSentence,
    ScenarioQuestion,
    User,
)
from app.scoring.audio_convert import probe_audio

router = APIRouter(tags=["attempts"])

# PRD US-02：短于 1 秒不打分，提示再录
MIN_DURATION_S = 1.0
# 队列容量上限：超过时前端保留录音并提示稍后重试
MAX_QUEUE_SIZE = 200
# 分段读取的块大小（限量读取，避免整文件无上限进内存）
_CHUNK_SIZE = 64 * 1024
# 时长容差：客户端上报时长与探测时长偏差超过该值视为不可信
DURATION_TOLERANCE_S = 3.0


def _validate_item(session: Session, item_type: str, item_id: uuid.UUID) -> None:
    if item_type == AttemptItemType.PASSAGE:
        exists = session.get(Passage, item_id) is not None
    elif item_type == AttemptItemType.REPEAT:
        exists = session.get(RepeatSentence, item_id) is not None
    elif item_type == AttemptItemType.QUESTION:
        exists = session.get(ScenarioQuestion, item_id) is not None
    else:
        raise HTTPException(status_code=422, detail="item_type 无效")
    if not exists:
        raise HTTPException(status_code=404, detail="题目不存在")


def _require_student_submitter(student_id: uuid.UUID | None, token: str | None) -> None:
    """上传作答：提交学生必须凭入班凭证证明本人身份（匿名演示作答除外）。

    student_id 为空 = 旧版整篇跟读演示，不校验；有 student_id 时必须带有效凭证。
    """
    if student_id is None:
        return
    if not token:
        raise HTTPException(
            status_code=401,
            detail="缺少学生凭证，请重新进入课堂",
            headers={"WWW-Authenticate": "StudentCredential"},
        )
    try:
        sid, _, _ = verify_student_token(token)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="学生凭证无效或已过期，请重新进入课堂",
            headers={"WWW-Authenticate": "StudentCredential"},
        ) from None
    if sid != student_id:
        raise HTTPException(status_code=403, detail="没有权限：凭证与该学生不符")


def _require_attempt_access(
    session: Session,
    attempt: Attempt,
    student_token: str | None,
    current_user: User | None,
) -> None:
    """音频/作答访问：本人学生或授权教师（管理员）可访问，不靠 UUID 难猜。

    带了学生凭证就走学生通道（浏览器里可能残留教师 JWT，不能反过来
    抢身份）；没带凭证才按登录教师（管理员）放行。
    """
    if attempt.student_id is None:
        # 匿名演示作答（公开练习页）：没有归属主体可保护，按随机 UUID 回放
        return
    if student_token:
        try:
            sid, _, _ = verify_student_token(student_token)
        except ValueError:
            raise HTTPException(
                status_code=401,
                detail="凭证无效或已过期，请重新进入课堂",
                headers={"WWW-Authenticate": "StudentCredential"},
            ) from None
        if attempt.student_id == sid:
            return
        raise HTTPException(status_code=403, detail="没有权限：该作答不属于你本人")
    if current_user is not None:
        # 教师/管理员通道
        if current_user.is_superuser:
            return
        if attempt.session_id is not None:
            practice_session = session.get(PracticeSession, attempt.session_id)
            if practice_session is not None:
                classroom = session.get(Classroom, practice_session.classroom_id)
                if classroom is not None and classroom.owner_id == current_user.id:
                    return
        raise HTTPException(
            status_code=403, detail="没有权限：您不是该作答所属课堂的授权教师"
        )
    raise HTTPException(
        status_code=401,
        detail="缺少凭证",
        headers={"WWW-Authenticate": "StudentCredential"},
    )


@router.post("/attempts", response_model=AttemptPublic)
def create_attempt_upload(
    session: SessionDep,
    submitter: ScoringSubmitter,
    audio: UploadFile = File(..., description="浏览器 MediaRecorder 录制的音频"),
    item_type: str = Form(...),
    item_id: uuid.UUID = Form(...),
    duration_s: float = Form(..., gt=0, description="录音时长（秒）"),
    student_id: uuid.UUID | None = Form(default=None),
    session_id: uuid.UUID | None = Form(default=None),
    idempotency_key: str | None = Form(
        default=None, description="幂等键：重传不重复创建"
    ),
    token: str | None = Form(default=None, description="入班时发放的学生轻量凭证"),
) -> Any:
    """
    上传一条作答。立即返回 queued，分数通过轮询获取（PRD 不可协商 #4）。

    传 idempotency_key 时：已有同键作答直接返回（重传/断网重试不重复扣费）。
    队列繁忙时返回 503，前端保留录音提示稍后重试。
    音频真实格式/音轨/时长用 ffprobe 校验，不信客户端上报值。
    """
    # 幂等检查：同键已有作答直接返回
    if idempotency_key:
        existing = session.exec(
            select(Attempt).where(Attempt.idempotency_key == idempotency_key)
        ).first()
        if existing is not None:
            session.refresh(existing)
            return existing

    _validate_item(session, item_type, item_id)

    if student_id is not None:
        student = get_student(session=session, student_id=student_id)
        if student is None:
            raise HTTPException(status_code=404, detail="Student not found")
    if session_id is not None:
        practice_session = session.get(PracticeSession, session_id)
        if practice_session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if student_id is None or practice_session.student_id != student_id:
            raise HTTPException(status_code=422, detail="会话不属于该学生")

    # 提交学生必须凭入班凭证校验本人身份
    _require_student_submitter(student_id, token)

    if duration_s < MIN_DURATION_S:
        raise HTTPException(status_code=422, detail="录音太短（不足 1 秒），请再录一次")

    # 限量读取：分段读入并即时检查大小上限
    max_bytes = settings.MAX_AUDIO_MB * 1024 * 1024
    data = b""
    while True:
        chunk = audio.file.read(_CHUNK_SIZE)
        if not chunk:
            break
        data += chunk
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"音频超过 {settings.MAX_AUDIO_MB}MB 上限"
            )
    if not data:
        raise HTTPException(status_code=422, detail="音频为空，请再录一次")

    # 真实格式/音轨/时长校验：ffprobe，不信客户端上报值
    mime_type = audio.content_type or "audio/webm"
    base_mime = mime_type.split(";")[0].strip().lower()
    suffix = _mime_to_suffix(base_mime)
    probe = probe_audio(data, suffix)
    if probe is None:
        raise HTTPException(status_code=422, detail="音频文件无效或损坏，请重新录音")
    if not probe.has_audio:
        raise HTTPException(status_code=422, detail="文件中没有音频音轨，请重新录音")
    if probe.channels is not None and probe.channels > 2:
        raise HTTPException(status_code=422, detail="音轨数异常，请重新录音")
    actual_duration = probe.duration_s
    if actual_duration is not None:
        if actual_duration < MIN_DURATION_S:
            raise HTTPException(
                status_code=422, detail="录音太短（不足 1 秒），请再录一次"
            )
        if abs(actual_duration - duration_s) > DURATION_TOLERANCE_S:
            # 时长明显不符：以探测值为准重算，避免被恶意上报值利用
            duration_s = actual_duration

    # 队列容量检查：繁忙时拒绝，前端保留录音提示稍后重试
    queued_count = session.exec(
        select(func.count(Attempt.id)).where(  # type: ignore
            Attempt.status == AttemptStatus.QUEUED
        )
    ).one()
    if queued_count >= MAX_QUEUE_SIZE:
        raise HTTPException(
            status_code=503,
            detail="评分队列繁忙，请稍后重试",
        )

    audio_path = save_audio_file(data, mime_type)
    attempt = Attempt(
        item_type=item_type,
        item_id=item_id,
        student_id=student_id,
        session_id=session_id,
        idempotency_key=idempotency_key,
        audio_path=str(audio_path),
        audio_mime=mime_type,
        duration_s=duration_s,
        engine=settings.SCORING_PROVIDER,
    )
    try:
        attempt = create_attempt(session=session, attempt_in=attempt)
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key and "idempotency_key" in str(exc.orig):
            existing = session.exec(
                select(Attempt).where(Attempt.idempotency_key == idempotency_key)
            ).first()
            if existing is not None:
                return existing
        raise

    submitter(attempt.id)
    session.refresh(attempt)
    return attempt


def _mime_to_suffix(base_mime: str) -> str:
    mapping = {
        "audio/webm": ".webm",
        "video/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/aac": ".aac",
        "audio/flac": ".flac",
        "audio/amr": ".amr",
    }
    return mapping.get(base_mime, ".webm")


@router.get("/attempts/{attempt_id}", response_model=AttemptPublic)
def read_attempt(
    session: SessionDep,
    attempt_id: uuid.UUID,
    token: str | None = None,
    current_user: OptionalCurrentUser = None,
) -> Any:
    """轮询作答状态与反馈。done 返回转写和分数，failed 返回 error。

    需要本人学生凭证或授权教师身份。
    """
    attempt = get_attempt(session=session, attempt_id=attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    _require_attempt_access(session, attempt, token, current_user)
    return attempt


@router.get("/attempts/{attempt_id}/audio")
def read_attempt_audio(
    session: SessionDep,
    attempt_id: uuid.UUID,
    token: str | None = None,
    current_user: OptionalCurrentUser = None,
) -> FileResponse:
    """回放一条作答的音频。本人学生或授权教师可访问，不靠 UUID 难猜。"""
    attempt = get_attempt(session=session, attempt_id=attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    _require_attempt_access(session, attempt, token, current_user)
    path = Path(attempt.audio_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type=attempt.audio_mime)
