"""火山方舟 chat/completions 公共客户端 + JSON 容错解析。

rubric 评分与 AI 出题共用；转写（responses API）与语音合成（speech API）
形态不同，保持独立实现。
"""

import json
import re

import httpx

from app.core.config import settings


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
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}/chat/completions"
        if self._client is not None:
            resp = self._client.post(url, json=payload, headers=headers)
        else:
            with httpx.Client(timeout=60) as client:
                resp = client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise ArkChatError(f"Ark chat 返回 {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ArkChatError("Ark chat 响应结构异常") from exc


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
