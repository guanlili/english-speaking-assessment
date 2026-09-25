"""标准音生成（PRD §7.2：语音合成把内容做成标准音，生成一次、存下来）。

火山 TTS 不在方舟域名上（ark .../api/v3/audio/speech 已不存在），走 vei AI 网关的
OpenAI 兼容 /audio/speech 接口：POST {ARK_TTS_BASE_URL}/audio/speech 返回音频二进制。
网关密钥与方舟 API Key 是两套，需在 console.volcengine.com/vei/aigateway 创建。
无网关密钥/未选音色时生成不可用（503），上传现成音频文件的通道始终可用。
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
        self.base_url = (base_url or settings.ARK_TTS_BASE_URL).rstrip("/")
        self._client = client

    def synthesize(self, text: str) -> bytes:
        if not self.api_key:
            raise TtsError(
                "标准音生成需要配置 ARK_TTS_API_KEY（vei AI 网关密钥）"
                "或 ARK_API_KEY（也可上传现成音频）"
            )
        if not self.voice:
            raise TtsError(
                "标准音生成需要配置 ARK_TTS_VOICE（在控制台音色列表选择后填写，"
                "也可上传现成音频）"
            )
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
        api_key=settings.ARK_TTS_API_KEY or settings.ARK_API_KEY,
        model=settings.ARK_TTS_MODEL,
        voice=settings.ARK_TTS_VOICE,
    )
