"""音频落盘。文件名随机（uuid），路径不通过 API 暴露（PRD §8.5：音频链接不可猜）。"""

import uuid
from pathlib import Path

from app.core.config import settings

# mime → 后缀的唯一事实源：上传探测（attempts）/落盘（本文件）/回放
# Content-Type（attempts/audio 路由）三处共用。曾经三份映射漂移——探测
# 映射有 flac/amr/video-webm 而落盘映射缺 → 存成 .bin 回放 Content-Type 错
MIME_TO_SUFFIX = {
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

# 回放方向：后缀 → Content-Type（.bin 不在其中，未知后缀回退 octet-stream）
AUDIO_SUFFIX_TO_MIME = {
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".amr": "audio/amr",
}


def mime_to_suffix(mime_type: str) -> str:
    """未知 mime 回退 .webm：与上传探测的回退一致（ffprobe 已按该后缀
    校验过音轨真实有效，落盘后缀与探测后缀保持同一路径）。"""
    return MIME_TO_SUFFIX.get(mime_type.split(";")[0].strip().lower(), ".webm")


def save_audio_file(data: bytes, mime_type: str) -> Path:
    suffix = mime_to_suffix(mime_type)
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


def save_content_audio_named(data: bytes, suffix: str, stem: str) -> Path:
    """内容寻址落盘（TTS 缓存）：同 (模型,音色,文本) 生成结果复用同一文件名，
    命中即免二次合成扣费。stem 必须是调用方传入的安全标识（hex 摘要）。"""
    if suffix not in CONTENT_AUDIO_SUFFIXES:
        raise ValueError(f"不支持的内容音频格式：{suffix}")
    directory = Path(settings.AUDIO_STORAGE_DIR) / "content"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}{suffix}"
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
