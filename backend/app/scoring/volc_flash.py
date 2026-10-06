"""豆包语音录音文件极速版；与方舟 Responses 使用独立凭证。"""

import base64
import uuid

import httpx

from app.scoring.base import ScoringError

FLASH_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
_client = httpx.Client(timeout=60)


class VolcFlashAsr:
    name = "volc_flash"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.client = client if client is not None else _client

    def transcribe(self, audio: bytes, mime_type: str) -> str:
        if not self.api_key:
            raise ScoringError("未配置 VOLC_ASR_API_KEY，请开通录音文件识别极速版")
        if mime_type not in {"audio/wav", "audio/mpeg", "audio/mp3", "audio/ogg"}:
            raise ScoringError("极速转写音频格式不支持，请先转换为 WAV")
        if not audio or len(audio) > 100 * 1024 * 1024:
            raise ScoringError("极速转写音频为空或超过 100MB")
        try:
            response = self.client.post(
                FLASH_URL,
                headers={
                    "X-Api-Key": self.api_key,
                    "X-Api-Resource-Id": "volc.bigasr.auc_turbo",
                    "X-Api-Request-Id": str(uuid.uuid4()),
                    "X-Api-Sequence": "-1",
                },
                json={
                    "user": {"uid": "charcoal"},
                    "audio": {"data": base64.b64encode(audio).decode()},
                    # 不删口头词/重复，不做数字规范化，保留学生实际表达。
                    "request": {
                        "model_name": "bigmodel",
                        "enable_itn": False,
                        "enable_punc": True,
                        "enable_ddc": False,
                    },
                },
            )
        except httpx.HTTPError as exc:
            raise ScoringError("极速转写网络请求失败") from exc
        code = response.headers.get("X-Api-Status-Code")
        if response.status_code != 200:
            raise ScoringError(f"极速转写 HTTP {response.status_code}")
        if code == "20000003":
            return ""
        if code != "20000000":
            raise ScoringError(f"极速转写失败，状态码 {code or '缺失'}")
        try:
            data = response.json()
            result = data.get("result")
            text = result.get("text") if isinstance(result, dict) else None
            if not isinstance(text, str):
                raise ValueError("missing transcript")
            return text.strip()
        except (ValueError, AttributeError) as exc:
            raise ScoringError("极速转写返回格式无效") from exc
