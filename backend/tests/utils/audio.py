"""合法音频字节：测试上传用真实 WAV（ffprobe 校验，客户端上报值不作准）。

只用标准库生成，避免测试依赖 ffmpeg 编码能力。
"""

from __future__ import annotations

import math
import struct
import wave


def wav_bytes(duration_s: float = 5.0, rate: int = 8000, freq: int = 440) -> bytes:
    """生成一段指定时长的 16bit 单声道正弦波 WAV。"""
    frames = max(1, int(rate * duration_s))
    buf = bytearray()
    for i in range(frames):
        value = int(12000 * math.sin(2 * math.pi * freq * i / rate))
        buf += struct.pack("<h", value)
    import io

    with io.BytesIO() as bio:
        with wave.open(bio, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(buf))
        return bio.getvalue()


def wav_upload(duration_s: float = 5.0) -> tuple[str, bytes, str]:
    """multipart 上传三元组 (文件名, 字节, content_type)。"""
    return ("a.wav", wav_bytes(duration_s), "audio/wav")
