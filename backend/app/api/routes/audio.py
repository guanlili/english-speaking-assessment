"""内容标准音回放（公开：文件名随机不可猜，PRD §8.5）。"""

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.storage import content_audio_path

router = APIRouter(prefix="/audio", tags=["audio"])


@router.get("/content/{filename}")
def read_content_audio(filename: str) -> Any:
    path = content_audio_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    suffix = path.suffix.lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
    }
    return FileResponse(
        path, media_type=media_types.get(suffix, "application/octet-stream")
    )
