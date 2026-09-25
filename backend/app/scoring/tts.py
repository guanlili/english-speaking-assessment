"""标准音生成（PRD §7.2：豆包语音合成把内容做成标准音，生成一次、存下来）。

方舟 TTS 走 OpenAI 兼容的 /audio/speech 形态：POST 返回音频二进制。
无账号时生成不可用（503），上传现成音频文件的通道始终可用。
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class TtsError(Exception):
    """TTS 不可用或生成失败（界面提示改用上传或 speechSynthesis 兜底）。"""


class ArkTtsProvider:
    name = "ark"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.base_url = (base_url or settings.ARK_BASE_URL).rstrip("/")
        self._client = client

    def synthesize(self, text: str) -> bytes:
        if not self.api_key:
            raise TtsError("标准音生成需要配置 ARK_API_KEY（也可上传现成音频）")
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "mp3",
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/audio/speech"
        if self._client is not None:
            resp = self._client.post(url, json=payload, headers=headers)
        else:
            with httpx.Client(timeout=120) as client:
                resp = client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise TtsError(f"TTS 返回 {resp.status_code}: {resp.text[:200]}")
        return resp.content


def build_tts_provider() -> ArkTtsProvider:
    return ArkTtsProvider(
        api_key=settings.ARK_API_KEY,
        model=settings.ARK_TTS_MODEL,
        voice=settings.ARK_TTS_VOICE,
    )
