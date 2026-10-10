"""火山方舟 chat/completions 公共客户端 + JSON 容错解析。

rubric 评分与 AI 出题共用；转写（responses API）与语音合成（speech API）
形态不同，保持独立实现。
"""

import json
import logging
import re
import time

import httpx

from app.core import metrics
from app.core.config import settings

logger = logging.getLogger(__name__)

_shared_client = httpx.Client(timeout=60)


# Seed Lite 家族前缀：API 调用名带日期后缀（-260428 等），按前缀匹配才能
# 覆盖未来升级的快照名——精确匹配旧模型串时，换模型即静默失去
# max_tokens/thinking 抑制这两道费用护栏
_SEED_LITE_PREFIX = "doubao-seed-2-0-lite-"


def fast_chat_options(model: str | None) -> dict[str, object]:
    """已验证的 Seed Lite 快速模式；其他模型不发送专有参数。"""
    if model and model.startswith(_SEED_LITE_PREFIX):
        return {"thinking": {"type": "disabled"}, "max_tokens": 2048}
    return {}


class ArkChatError(Exception):
    """chat 调用失败（未配置、HTTP 错误、无 JSON 输出）。"""


class ArkChatClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or settings.ARK_BASE_URL).rstrip("/")
        self._client = client

    def chat(
        self,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> str:
        if not self.api_key:
            raise ArkChatError("未配置 ARK_API_KEY")
        payload = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            **fast_chat_options(model or self.model),
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/chat/completions"
        client = self._client if self._client is not None else _shared_client
        start = time.perf_counter()
        try:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise ArkChatError(
                    f"Ark chat 返回 {resp.status_code}: {resp.text[:200]}"
                )
            try:
                content = resp.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ArkChatError("Ark chat 响应结构异常") from exc
        except Exception:
            metrics.record_call("llm", ok=False, duration_s=time.perf_counter() - start)
            raise
        metrics.record_call("llm", ok=True, duration_s=time.perf_counter() - start)
        return content


def parse_json_payload(content: str) -> dict:
    """容错解析 LLM 输出的 JSON 对象：剥 markdown 栅栏、截取首尾大括号。"""
    cleaned = re.sub(
        r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE
    ).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match is None:
        raise ValueError("LLM 输出中没有 JSON 对象")
    return json.loads(match.group(0))


def parse_json_list(content: str) -> list:
    """容错解析 LLM 输出的 JSON 数组（AI 出题用）。"""
    cleaned = re.sub(
        r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE
    ).strip()
    match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
    if match is None:
        raise ValueError("LLM 输出中没有 JSON 数组")
    return json.loads(match.group(0))
