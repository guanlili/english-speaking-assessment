"""音频格式适配：浏览器 MediaRecorder 的 webm/opus → 方舟支持的 wav。

方舟 responses API 的 input_audio 仅收 mp3/wav/aac/flac/m4a/amr；
教室浏览器录音几乎都是 webm/opus（PRD §7.4 也预见了「必要时转码」）。
用 ffmpeg 转 16kHz 单声道 wav（ASR 足够，体积可控）。
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 方舟 input_audio 支持的格式
ARK_SUPPORTED_SUFFIXES = {".mp3", ".wav", ".aac", ".flac", ".m4a", ".amr"}
# 需要转码的浏览器录音格式
BROWSER_SUFFIXES = {".webm", ".ogg", ".oga"}


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def convert_to_wav(data: bytes, source_suffix: str) -> tuple[bytes, str]:
    """ffmpeg 转 16kHz 单声道 wav；失败时抛 RuntimeError（作答落 failed 保留音频）。"""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"src{source_suffix}"
        dst = Path(tmp) / "out.wav"
        src.write_bytes(data)
        result = subprocess.run(  # noqa: S603 - 参数固定，无用户输入
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src),
                "-ar",
                "16000",
                "-ac",
                "1",
                str(dst),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0 or not dst.is_file():
            raise RuntimeError(
                f"音频转码失败: {result.stderr.decode(errors='replace')[:200]}"
            )
        return dst.read_bytes(), "audio/wav"


def ensure_ark_supported(data: bytes, mime_type: str) -> tuple[bytes, str]:
    """按 mime 判断是否需要转码；已支持的格式原样返回。"""
    suffix_by_mime = {
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
    base_mime = mime_type.split(";")[0].strip().lower()
    suffix = suffix_by_mime.get(base_mime, ".webm")
    if suffix not in BROWSER_SUFFIXES:
        return data, base_mime
    if not ffmpeg_available():
        # 无 ffmpeg 也不静默丢格式信息——让云端报原始错误更可诊断
        logger.warning("ffmpeg 不可用，webm 音频将原样发送（可能被拒）")
        return data, base_mime
    return convert_to_wav(data, suffix)
