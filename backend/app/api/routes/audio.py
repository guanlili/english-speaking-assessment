"""内容标准音回放（公开：文件名随机不可猜，PRD §8.5）。"""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.storage import AUDIO_SUFFIX_TO_MIME, content_audio_path

router = APIRouter(prefix="/audio", tags=["audio"])


@router.get("/content/{filename}")
def read_content_audio(filename: str) -> Any:
    path = content_audio_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    # 后缀集合由 CONTENT_AUDIO_SUFFIXES 白名单限定，映射与上传侧共用一份
    media_type = AUDIO_SUFFIX_TO_MIME.get(
        path.suffix.lower(), "application/octet-stream"
    )
    return FileResponse(path, media_type=media_type)
