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

# 需要转码的浏览器录音格式（方舟只收 mp3/wav/aac/flac/m4a/amr，见 ensure_ark_supported）
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


class AudioProbeResult:
    """ffprobe 探测结果：时长、音轨数、声道数、采样率。"""

    __slots__ = ("duration_s", "has_audio", "channels", "sample_rate")

    def __init__(
        self,
        duration_s: float | None,
        has_audio: bool,
        channels: int | None,
        sample_rate: int | None,
    ) -> None:
        self.duration_s = duration_s
        self.has_audio = has_audio
        self.channels = channels
        self.sample_rate = sample_rate


def _wav_duration(data: bytes) -> float | None:
    """从 WAV 头解析时长（byte_rate × data 块）；解析不了返回 None。"""
    if len(data) < 44:
        return None
    byte_rate: int | None = None
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        body = offset + 8
        if chunk_id == b"fmt " and body + 16 <= len(data):
            byte_rate = int.from_bytes(data[body + 8 : body + 12], "little")
        elif chunk_id == b"data" and byte_rate:
            return chunk_size / byte_rate if byte_rate else None
        offset = body + chunk_size + (chunk_size % 2)
    return None


def _sniff_fallback(data: bytes) -> AudioProbeResult | None:
    """ffprobe 不可用时的最小校验：识别常见音频容器魔数，WAV 顺带算时长。

    有 ffprobe 时以它为准；这里只保证“明显不是音频”的文件不会进评分。
    """
    if not data:
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return AudioProbeResult(_wav_duration(data), True, None, None)
    if data[:4] in (b"OggS", b"fLaC", b"ID3\x00", b"ID3", b"\x1a\x45\xdf\xa3"):
        return AudioProbeResult(None, True, None, None)
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return AudioProbeResult(None, True, None, None)
    return None


def probe_audio(data: bytes, suffix: str) -> AudioProbeResult | None:
    """用 ffprobe 探测真实音频属性；探测失败（损坏/非音频）返回 None。

    不相信客户端上报的格式/时长：上传校验、转码前都用它。
    没装 ffprobe 时降级为魔数识别（WAV 仍能算出时长）。
    """
    if not shutil.which("ffprobe"):
        return _sniff_fallback(data)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"src{suffix}"
        src.write_bytes(data)
        result = subprocess.run(  # noqa: S603 - 参数固定，无用户输入
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(src),
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            return None
        import json as _json

        try:
            info = _json.loads(result.stdout.decode(errors="replace"))
        except ValueError:
            return None
        audio_streams = [
            s for s in info.get("streams", []) if s.get("codec_type") == "audio"
        ]
        if not audio_streams:
            return AudioProbeResult(
                None, has_audio=False, channels=None, sample_rate=None
            )
        stream = audio_streams[0]
        duration_s: float | None = None
        if "duration" in stream:
            try:
                duration_s = float(stream["duration"])
            except (TypeError, ValueError):  # fmt: skip
                duration_s = None
        if duration_s is None and "duration" in info.get("format", {}):
            try:
                duration_s = float(info["format"]["duration"])
            except (TypeError, ValueError):  # fmt: skip
                duration_s = None
        channels: int | None = None
        try:
            channels = int(stream["channels"])
        except (KeyError, TypeError, ValueError):  # fmt: skip
            channels = None
        sample_rate: int | None = None
        try:
            sample_rate = int(stream["sample_rate"])
        except (KeyError, TypeError, ValueError):  # fmt: skip
            sample_rate = None
        return AudioProbeResult(
            duration_s=duration_s,
            has_audio=True,
            channels=channels,
            sample_rate=sample_rate,
        )
