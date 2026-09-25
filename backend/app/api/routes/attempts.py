"""通用作答接口：上传录音立即返回 queued，轮询获取反馈。

POST /attempts      上传音频（multipart），任何题型（PRD 附录 A）
GET  /attempts/{id} 轮询转写与分数
"""

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.deps import ScoringSubmitter, SessionDep
from app.core.config import settings
from app.core.storage import save_audio_file
from app.crud import create_attempt, get_attempt, get_student
from app.models import (
    Attempt,
    AttemptItemType,
    AttemptPublic,
    Passage,
    PracticeSession,
    RepeatSentence,
    ScenarioQuestion,
)

router = APIRouter(tags=["attempts"])

# PRD US-02：短于 1 秒不打分，提示再录
MIN_DURATION_S = 1.0


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
) -> Any:
    """
    上传一条作答。立即返回 queued，分数通过轮询获取（PRD 不可协商 #4）。
    """
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

    if duration_s < MIN_DURATION_S:
        raise HTTPException(status_code=422, detail="录音太短（不足 1 秒），请再录一次")

    data = audio.file.read()
    if not data:
        raise HTTPException(status_code=422, detail="音频为空，请再录一次")
    if len(data) > settings.MAX_AUDIO_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"音频超过 {settings.MAX_AUDIO_MB}MB 上限"
        )

    audio_path = save_audio_file(data, audio.content_type or "audio/webm")
    attempt = Attempt(
        item_type=item_type,
        item_id=item_id,
        student_id=student_id,
        session_id=session_id,
        audio_path=str(audio_path),
        audio_mime=audio.content_type or "audio/webm",
        duration_s=duration_s,
        engine=settings.SCORING_PROVIDER,
    )
    attempt = create_attempt(session=session, attempt_in=attempt)

    submitter(attempt.id)
    # 评分可能已在另一会话完成（同步覆写/线程池跑得快），刷新取最新状态；
    # 异步场景下仍是 queued，由前端轮询获取
    session.refresh(attempt)
    return attempt


@router.get("/attempts/{attempt_id}", response_model=AttemptPublic)
def read_attempt(session: SessionDep, attempt_id: uuid.UUID) -> Any:
    """轮询作答状态与反馈。done 返回转写和分数，failed 返回 error。"""
    attempt = get_attempt(session=session, attempt_id=attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt


@router.get("/attempts/{attempt_id}/audio")
def read_attempt_audio(session: SessionDep, attempt_id: uuid.UUID) -> FileResponse:
    """回放一条作答的音频（老师表用）。

    路径不可猜：attempt id 是随机 UUID（PRD §8.5：音频链接猜不到）。
    """
    attempt = get_attempt(session=session, attempt_id=attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    path = Path(attempt.audio_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type=attempt.audio_mime)
