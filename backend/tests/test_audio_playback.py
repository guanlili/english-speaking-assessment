"""Playback conversion is cached, atomic and preserves original audio."""

from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import Mock

import pytest

from app.services import audio_playback


def test_playback_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "recording.webm"
    source.write_bytes(b"original")
    convert = Mock(return_value=(b"wav recording", "audio/wav"))
    monkeypatch.setattr(audio_playback, "convert_to_wav", convert)
    monkeypatch.setattr(audio_playback, "ffmpeg_available", lambda: True)
    result = audio_playback.playback_path(source)
    assert result.read_bytes() == b"wav recording"
    assert source.read_bytes() == b"original"
    assert audio_playback.playback_path(source) == result
    assert convert.call_count == 1
    assert set(tmp_path.iterdir()) == {source, result}


@pytest.mark.parametrize(
    "error", [RuntimeError("invalid"), TimeoutExpired("ffmpeg", 30)]
)
def test_failed_conversion_keeps_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    source = tmp_path / "recording.mp4"
    source.write_bytes(b"original")
    monkeypatch.setattr(audio_playback, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(audio_playback, "convert_to_wav", Mock(side_effect=error))
    assert audio_playback.playback_path(source) == source
    assert list(tmp_path.iterdir()) == [source]


def test_real_chunked_webm_has_complete_seekable_playback(tmp_path: Path) -> None:
    import io
    import subprocess
    import wave

    if not audio_playback.ffmpeg_available():
        pytest.skip("ffmpeg is unavailable")
    source = tmp_path / "recording.webm"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:a",
            "libopus",
            "-f",
            "webm",
            "-cluster_time_limit",
            "250",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    result = audio_playback.playback_path(source)
    assert result != source
    with wave.open(io.BytesIO(result.read_bytes())) as audio:
        assert audio.getnframes() / audio.getframerate() == pytest.approx(2, abs=0.1)
        assert audio.getnchannels() == 1
        assert any(audio.readframes(audio.getnframes()))
