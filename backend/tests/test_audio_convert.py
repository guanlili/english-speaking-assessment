"""音频适配：转码、格式判定、ffprobe 探测与无二进制时的降级。

单测环境（本机 / CI）通常没装 ffmpeg、ffprobe，真实转码路径跑不到，
这里用替身把成功、失败、超时、缺输出、降级各分支都走一遍，
不依赖外部二进制。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.scoring import audio_convert


def _completed(*, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> Any:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _wav_bytes(byte_rate: int, data_size: int) -> bytes:
    """构造最小合法 WAV 头（fmt + data），data 区只放 8 字节占位。"""
    fmt = (
        b"fmt "
        + (16).to_bytes(4, "little")
        + b"\x01\x00"
        + (1).to_bytes(2, "little")
        + (16000).to_bytes(4, "little")
        + byte_rate.to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
    )
    data = b"data" + data_size.to_bytes(4, "little") + b"\x00" * 8
    return b"RIFF" + (0).to_bytes(4, "little") + b"WAVE" + fmt + data


def test_ffmpeg_available_uses_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert audio_convert.ffmpeg_available() is True
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: None)
    assert audio_convert.ffmpeg_available() is False


def test_convert_to_wav_requests_16k_mono(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        Path(cmd[-1]).write_bytes(b"RIFF-wav")
        return _completed()

    monkeypatch.setattr(audio_convert.subprocess, "run", fake_run)
    data, mime = audio_convert.convert_to_wav(b"webm-bytes", ".webm")

    assert data == b"RIFF-wav"
    assert mime == "audio/wav"
    cmd = seen["cmd"]
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-ar") + 1] == "16000"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert seen["kwargs"]["timeout"] == 30
    assert seen["kwargs"]["check"] is False


def test_convert_to_wav_raises_on_ffmpeg_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audio_convert.subprocess,
        "run",
        lambda *a, **k: _completed(returncode=1, stderr=b"unable to decode stream"),
    )
    with pytest.raises(RuntimeError, match="unable to decode stream"):
        audio_convert.convert_to_wav(b"broken", ".webm")


def test_convert_to_wav_raises_when_output_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ffmpeg 返回 0 却没产出文件（容器裁剪/磁盘满）：不能当成功
    monkeypatch.setattr(audio_convert.subprocess, "run", lambda *a, **k: _completed())
    with pytest.raises(RuntimeError, match="音频转码失败"):
        audio_convert.convert_to_wav(b"payload", ".webm")


def test_convert_to_wav_propagates_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=30)

    monkeypatch.setattr(audio_convert.subprocess, "run", boom)
    with pytest.raises(subprocess.TimeoutExpired):
        audio_convert.convert_to_wav(b"slow", ".webm")


@pytest.mark.parametrize(
    "mime",
    ["audio/mpeg", "audio/wav;codecs=1", "audio/x-m4a", "audio/aac"],
)
def test_native_formats_pass_through(
    monkeypatch: pytest.MonkeyPatch, mime: str
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("方舟原生支持的格式不该转码")

    monkeypatch.setattr(audio_convert, "convert_to_wav", unexpected)
    data, effective = audio_convert.ensure_ark_supported(b"raw-bytes", mime)
    assert data == b"raw-bytes"
    assert effective == mime.split(";")[0].strip().lower()


def test_browser_format_converts_when_ffmpeg_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert, "ffmpeg_available", lambda: True)
    suffixes: list[str] = []

    def fake_convert(data: bytes, suffix: str) -> tuple[bytes, str]:
        suffixes.append(suffix)
        return b"wav-bytes", "audio/wav"

    monkeypatch.setattr(audio_convert, "convert_to_wav", fake_convert)
    data, effective = audio_convert.ensure_ark_supported(
        b"webm", "audio/webm;codecs=opus"
    )
    assert (data, effective) == (b"wav-bytes", "audio/wav")
    assert suffixes == [".webm"]


def test_browser_format_kept_when_ffmpeg_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # 无 ffmpeg 时不静默改写格式：原样送云端，让上游报可诊断的错误
    monkeypatch.setattr(audio_convert, "ffmpeg_available", lambda: False)
    with caplog.at_level("WARNING"):
        data, effective = audio_convert.ensure_ark_supported(b"webm", "video/webm")
    assert (data, effective) == (b"webm", "video/webm")
    assert "ffmpeg" in caplog.text


def test_unknown_mime_defaults_to_webm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert, "ffmpeg_available", lambda: True)
    suffixes: list[str] = []

    def fake_convert(data: bytes, suffix: str) -> tuple[bytes, str]:
        suffixes.append(suffix)
        return b"wav", "audio/wav"

    monkeypatch.setattr(audio_convert, "convert_to_wav", fake_convert)
    audio_convert.ensure_ark_supported(b"x", "application/octet-stream")
    assert suffixes == [".webm"]


def test_probe_without_ffprobe_falls_back_to_magic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: None)
    result = audio_convert.probe_audio(b"OggS\x00\x02payload", ".ogg")
    assert result is not None
    assert result.has_audio is True
    # 无 ffprobe 时拿不到声道/采样率，只能确认"是音频"
    assert result.channels is None
    assert result.sample_rate is None


def test_probe_reads_stream_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffprobe")
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "duration": "12.5",
                "channels": 1,
                "sample_rate": "16000",
            }
        ],
        "format": {},
    }
    monkeypatch.setattr(
        audio_convert.subprocess,
        "run",
        lambda *a, **k: _completed(stdout=json.dumps(payload).encode()),
    )
    result = audio_convert.probe_audio(b"bytes", ".webm")
    assert result is not None
    assert result.has_audio is True
    assert result.duration_s == 12.5
    assert result.channels == 1
    assert result.sample_rate == 16000


def test_probe_falls_back_to_format_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffprobe")
    payload = {
        "streams": [{"codec_type": "audio"}],
        "format": {"duration": "7.25"},
    }
    monkeypatch.setattr(
        audio_convert.subprocess,
        "run",
        lambda *a, **k: _completed(stdout=json.dumps(payload).encode()),
    )
    result = audio_convert.probe_audio(b"bytes", ".webm")
    assert result is not None
    assert result.duration_s == 7.25
    # stream 里没有 channels / sample_rate，解析失败要给 None 而不是抛
    assert result.channels is None
    assert result.sample_rate is None


def test_probe_bad_numeric_values_yield_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffprobe")
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "duration": "N/A",
                "channels": "stereo",
                "sample_rate": {},
            }
        ],
        "format": {"duration": "N/A"},
    }
    monkeypatch.setattr(
        audio_convert.subprocess,
        "run",
        lambda *a, **k: _completed(stdout=json.dumps(payload).encode()),
    )
    result = audio_convert.probe_audio(b"bytes", ".webm")
    assert result is not None
    assert result.has_audio is True
    assert result.duration_s is None
    assert result.channels is None
    assert result.sample_rate is None


def test_probe_without_audio_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffprobe")
    payload = {"streams": [{"codec_type": "video"}], "format": {}}
    monkeypatch.setattr(
        audio_convert.subprocess,
        "run",
        lambda *a, **k: _completed(stdout=json.dumps(payload).encode()),
    )
    result = audio_convert.probe_audio(b"bytes", ".mp4")
    assert result is not None
    assert result.has_audio is False


def test_probe_nonzero_exit_rejects_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        audio_convert.subprocess,
        "run",
        lambda *a, **k: _completed(returncode=1, stderr=b"Invalid data found"),
    )
    assert audio_convert.probe_audio(b"broken", ".webm") is None


def test_probe_malformed_json_rejects_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr(
        audio_convert.subprocess,
        "run",
        lambda *a, **k: _completed(stdout=b"{not json"),
    )
    assert audio_convert.probe_audio(b"broken", ".webm") is None


def test_probe_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # 精心构造的容器能让 ffprobe 挂满 15 秒：超时按无效音频处理，不冒 500
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffprobe")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=15)

    monkeypatch.setattr(audio_convert.subprocess, "run", boom)
    assert audio_convert.probe_audio(b"crafted", ".webm") is None


def test_probe_oserror_degrades_to_magic(monkeypatch: pytest.MonkeyPatch) -> None:
    # which 之后二进制仍可能消失/不可执行：降级识别而不是把异常抛给调用方
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: "/usr/bin/ffprobe")

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("exec format error")

    monkeypatch.setattr(audio_convert.subprocess, "run", boom)
    result = audio_convert.probe_audio(b"ID3\x00payload", ".mp3")
    assert result is not None
    assert result.has_audio is True


def test_wav_duration_computed_from_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: None)
    wav = _wav_bytes(byte_rate=32000, data_size=64000)  # 2 秒
    result = audio_convert.probe_audio(wav, ".wav")
    assert result is not None
    assert result.has_audio is True
    assert result.duration_s == 2.0


def test_wav_truncated_header_has_no_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: None)
    # 只有 12 字节的 RIFF/WAVE 头：能确认是音频，但算不出时长
    result = audio_convert.probe_audio(b"RIFF\x00\x00\x00\x00WAVE", ".wav")
    assert result is not None
    assert result.has_audio is True
    assert result.duration_s is None


def test_wav_without_data_chunk_has_no_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # fmt 头完整但缺少 data 块：走到遍历结束的兜底 return None
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: None)
    fmt_only = _wav_bytes(byte_rate=32000, data_size=0)[:-16] + b"\x00" * 8
    result = audio_convert.probe_audio(fmt_only, ".wav")
    assert result is not None
    assert result.has_audio is True
    assert result.duration_s is None


@pytest.mark.parametrize(
    "magic",
    [
        b"fLaC\x00\x00",
        b"ID3\x00\x00",
        b"\x1a\x45\xdf\xa3",
        b"\xff\xe0\x00\x00",  # MP3 帧同步
    ],
)
def test_sniff_recognizes_common_audio_containers(
    monkeypatch: pytest.MonkeyPatch, magic: bytes
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: None)
    result = audio_convert.probe_audio(magic, ".bin")
    assert result is not None
    assert result.has_audio is True


def test_sniff_rejects_empty_and_non_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio_convert.shutil, "which", lambda name: None)
    assert audio_convert.probe_audio(b"", ".webm") is None
    assert audio_convert.probe_audio(b"plain text, not audio", ".webm") is None
