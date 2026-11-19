"""标准音生成（PRD §7.2：语音合成把内容做成标准音，生成一次、存下来）。

两种通道，由 TTS_PROVIDER 选择：
- vei：VEI AI 网关的 OpenAI 兼容 /audio/speech，返回音频二进制；
  网关密钥与方舟 API Key 是两套，需在 console.volcengine.com/vei/aigateway 创建。
- volc_direct：豆包语音 V3 单向流式 HTTP 接口，复用语音 Key，返回 JSON 行
  （每行 data 为 base64 音频分片），资源与音色必须同代匹配。

无 Key/未选音色时生成不可用（503），上传现成音频文件的通道始终可用。
"""

import base64
import hashlib
import json
import logging
import time
import uuid

import httpx

from app.core import metrics
from app.core.config import settings

logger = logging.getLogger(__name__)

_shared_client = httpx.Client(
    # 连接建立失败快速暴露（不再吃满整个 read 预算）；池上限显式化，
    # 默认 keepalive 已够用，这里主要是把取值落到代码而非隐式默认
    timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10),
    limits=httpx.Limits(max_connections=32, max_keepalive_connections=8),
)


class TtsError(Exception):
    """TTS 不可用或生成失败（界面提示改用上传或 speechSynthesis 兜底）。"""


def cache_key(model: str | None, voice: str | None, text: str) -> str:
    """内容寻址缓存键：同 (模型, 音色, 文本) 的合成结果完全一致，命中免二次扣费。

    同文本换音色/换模型是不同的音频，必须全部进键。
    """
    digest = hashlib.sha256(f"{model}|{voice}|{text}".encode()).hexdigest()
    return f"tts-{digest[:40]}"


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
        client = self._client if self._client is not None else _shared_client
        start = time.perf_counter()
        try:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise TtsError(f"TTS 返回 {resp.status_code}: {resp.text[:200]}")
        except Exception:
            metrics.record_call("tts", ok=False, duration_s=time.perf_counter() - start)
            raise
        # TTS 是按字符计费的调用：进运维指标（缓存命中在上层、不经过这里）
        metrics.record_call("tts", ok=True, duration_s=time.perf_counter() - start)
        return resp.content


class VolcDirectTtsProvider:
    """豆包语音 V3 单向流式直连（不经过 VEI 网关）。

    响应是 HTTP Chunked 的 JSON 行：每行 `{"code":0,"data":"<base64>"}`，
    音频分片需要按行累加后 base64 解码。`model` 复用资源 ID，便于上层
    内容缓存键与运维指标区分 1.0/2.0 音色。
    """

    name = "volc_direct"

    def __init__(
        self,
        api_key: str | None = None,
        resource_id: str = "seed-tts-2.0",
        voice: str | None = None,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.resource_id = resource_id
        self.model = resource_id
        self.voice = voice
        self.base_url = base_url or settings.VOLC_TTS_BASE_URL
        self._client = client

    def synthesize(self, text: str) -> bytes:
        if not self.api_key:
            raise TtsError(
                "标准音生成需要配置 VOLC_TTS_API_KEY 或 VOLC_ASR_API_KEY"
                "（豆包语音 Key），也可上传现成音频"
            )
        if not self.voice:
            raise TtsError(
                "标准音生成需要配置 VOLC_TTS_VOICE（2.0 音色以 _uranus_bigtts 结尾），"
                "也可上传现成音频"
            )
        payload = {
            "user": {"uid": "speakup"},
            "req_params": {
                "text": text,
                "speaker": self.voice,
                "audio_params": {"format": "mp3", "sample_rate": 24000},
            },
        }
        headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }
        client = self._client if self._client is not None else _shared_client
        start = time.perf_counter()
        chunks: list[bytes] = []
        try:
            with client.stream(
                "POST", self.base_url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise TtsError(f"TTS 返回 {resp.status_code}: {resp.text[:200]}")
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise TtsError(f"TTS 返回非 JSON 行: {line[:120]}") from exc
                    code = item.get("code")
                    # 0 = 分片，20000000 = 结束/成功（与 ASR 的 X-Api-Status-Code 一致）
                    if code is not None and code not in (0, 20000000):
                        raise TtsError(
                            f"TTS 返回 {code}: {str(item.get('message', ''))[:200]}"
                        )
                    data = item.get("data")
                    if not data:
                        continue
                    try:
                        chunks.append(base64.b64decode(data))
                    except Exception as exc:  # noqa: BLE001 - 上游数据不可信
                        raise TtsError("TTS 返回的音频分片不是合法 base64") from exc
        except Exception:
            metrics.record_call("tts", ok=False, duration_s=time.perf_counter() - start)
            raise
        audio = b"".join(chunks)
        if not audio:
            raise TtsError("TTS 返回空音频，请检查音色与资源版本是否匹配")
        metrics.record_call("tts", ok=True, duration_s=time.perf_counter() - start)
        return audio


def build_tts_provider() -> ArkTtsProvider | VolcDirectTtsProvider:
    if settings.TTS_PROVIDER == "volc_direct":
        return VolcDirectTtsProvider(
            api_key=settings.VOLC_TTS_API_KEY or settings.VOLC_ASR_API_KEY,
            resource_id=settings.VOLC_TTS_RESOURCE_ID,
            voice=settings.VOLC_TTS_VOICE,
        )
    return ArkTtsProvider(
        api_key=settings.ARK_TTS_API_KEY or settings.ARK_API_KEY,
        model=settings.ARK_TTS_MODEL,
        voice=settings.ARK_TTS_VOICE,
    )
