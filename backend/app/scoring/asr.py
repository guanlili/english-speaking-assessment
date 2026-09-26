"""ASR 提供方实现。

- MockAsr：离线、确定性，用于测试与无云账号的演示（引擎标注 mock）。
- ArkResponsesAsr：火山方舟 Responses API，音频以 base64 data URL 内联
  （≤25MB）。请求形态与 arkcli `+understand asr` 一致：
      POST {base}/responses
      {"model": ..., "instructions": ...,
       "input": [{"role": "user", "content": [
           {"type": "input_audio", "audio_url": "data:<mime>;base64,..."}]}]}
  响应取 output[].content[] 中 type=output_text 的 text 拼接。
"""

import base64
import logging
from typing import Any

import httpx

from app.scoring.base import ScoringError

logger = logging.getLogger(__name__)

ASR_INSTRUCTIONS = (
    "Transcribe the English speech in the audio verbatim. "
    "Output ONLY the transcript text - no explanations, no markdown. "
    "If the audio is unclear or contains no speech, output an empty string."
)

_MAX_AUDIO_BYTES = 25 * 1024 * 1024


class MockAsr:
    name = "mock"

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        # 固定的半段参考文本，让演示闭环有中等的完整度/流利度分数
        return (
            "many students in our class have pets at home "
            "i prefer dogs because they are friendly and loyal"
        )


def build_ark_payload(model: str, audio: bytes, mime_type: str) -> dict[str, Any]:
    data_url = f"data:{mime_type};base64,{base64.b64encode(audio).decode()}"
    return {
        "model": model,
        "instructions": ASR_INSTRUCTIONS,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_audio", "audio_url": data_url}],
            }
        ],
    }


def parse_ark_response(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "".join(parts).strip()


class ArkResponsesAsr:
    name = "ark"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = client

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        if not self.api_key:
            raise ScoringError("未配置 ARK_API_KEY")
        if len(audio) > _MAX_AUDIO_BYTES:
            raise ScoringError("音频超过 25MB 上限")

        payload = build_ark_payload(self.model, audio, mime_type)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            if self._client is not None:
                resp = self._client.post(
                    f"{self.base_url}/responses", json=payload, headers=headers
                )
            else:
                with httpx.Client(timeout=60) as client:
                    resp = client.post(
                        f"{self.base_url}/responses", json=payload, headers=headers
                    )
        except httpx.HTTPError as exc:
            raise ScoringError(f"Ark 请求失败: {exc}") from exc
        if resp.status_code != 200:
            # 常见 404: 模型未对当前账号开通（model_not_found）
            raise ScoringError(f"Ark 返回 {resp.status_code}: {resp.text[:200]}")
        return parse_ark_response(resp.json())
