"""音频落盘。文件名随机（uuid），路径不通过 API 暴露（PRD §8.5：音频链接不可猜）。"""

import uuid
from pathlib import Path

from app.core.config import settings

_MIME_SUFFIX = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/aac": ".aac",
}


def save_audio_file(data: bytes, mime_type: str) -> Path:
    suffix = _MIME_SUFFIX.get(mime_type.split(";")[0].strip(), ".bin")
    directory = Path(settings.AUDIO_STORAGE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4()}{suffix}"
    path.write_bytes(data)
    return path


# 内容标准音（篇目/复述句/问法）：文件名随机不可猜，路径可回放到前端
CONTENT_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".webm"}
CONTENT_AUDIO_URL_PREFIX = "/api/v1/audio/content"


def save_content_audio(data: bytes, suffix: str) -> Path:
    """内容音频存独立子目录，返回落盘路径。suffix 已含点号。"""
    if suffix not in CONTENT_AUDIO_SUFFIXES:
        raise ValueError(f"不支持的内容音频格式：{suffix}")
    directory = Path(settings.AUDIO_STORAGE_DIR) / "content"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4()}{suffix}"
    path.write_bytes(data)
    return path


def content_audio_url(filename: str) -> str:
    return f"{CONTENT_AUDIO_URL_PREFIX}/{filename}"


def content_audio_path(filename: str) -> Path | None:
    """按文件名取回内容音频路径；名字不合法或文件不存在返回 None。"""
    from pathlib import PurePosixPath

    name = PurePosixPath(filename).name  # 防目录穿越
    if PurePosixPath(name).suffix not in CONTENT_AUDIO_SUFFIXES:
        return None
    path = Path(settings.AUDIO_STORAGE_DIR) / "content" / name
    return path if path.is_file() else None
