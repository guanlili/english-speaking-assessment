"""Seekable playback copies for browser-produced streaming containers."""

import logging
import os
import tempfile
from pathlib import Path
from subprocess import TimeoutExpired

from app.scoring.audio_convert import convert_to_wav, ffmpeg_available

logger = logging.getLogger(__name__)


def playback_cache_path(source: Path) -> Path:
    return source.with_name(source.name + ".playback.wav")


def playback_path(source: Path) -> Path:
    if source.suffix.lower() not in {".webm", ".ogg", ".oga", ".mp4", ".m4a"}:
        return source
    cached = playback_cache_path(source)
    if cached.is_file() and cached.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return cached
    if not ffmpeg_available():
        return source
    temporary: str | None = None
    try:
        audio, _ = convert_to_wav(source.read_bytes(), source.suffix)
        # Atomic replacement: parallel listeners never see a partially written WAV.
        with tempfile.NamedTemporaryFile(dir=source.parent, delete=False) as output:
            temporary = output.name
            output.write(audio)
        os.replace(temporary, cached)
        return cached
    except OSError, RuntimeError, TimeoutError, TimeoutExpired:
        logger.warning("Could not prepare playback copy", exc_info=True)
        return source
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
