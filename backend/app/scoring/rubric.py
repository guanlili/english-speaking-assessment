"""开放问答 rubric 评分（PRD US-08，第 3 周）。

按国际口语 rubric 四维打 0-4（流利/词汇/语法/任务完成），映射成 0-9 模拟分。
建议最多 3 条且必须引用学生原句；升级表达最多 2 条对应学生刚说过的意思。
模型失败时调用方应显示「建议暂缺」，绝不出 0 分（PRD US-08）。

实现 A/B：
- mock 引擎：不出 rubric（界面不显示模拟分，不造假分）
- ark 引擎：豆包/DeepSeek chat 接口按 rubric 出 JSON
"""

import json
import logging
import math
import re
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.scoring.ark_client import fast_chat_options

logger = logging.getLogger(__name__)

MAX_ADVICE = 3
MAX_UPGRADES = 2
DIMENSION_MAX = 4
_shared_client = httpx.Client(timeout=60)

# rubric 四维之和（0-16）→ 0-9 模拟分（PRD：映射表放在配置中）
RUBRIC_TO_SCORE: list[float] = [
    0,
    0.5,
    1,
    1.5,
    2,
    2.5,
    3,
    3.5,
    4,
    4.5,
    5,
    5.5,
    6,
    6.5,
    7,
    8,
    9,
]

RUBRIC_SYSTEM_PROMPT = (
    "You are a strict but encouraging English speaking examiner for a Chinese "
    "secondary school student. You will receive a speaking question, the "
    "student's CEFR band, and an automatic transcription of their answer "
    "(transcription may contain errors — judge the student, not the "
    "transcriber). Respond with ONLY a JSON object, no markdown, in this "
    "exact shape: "
    '{"fluency": <0-4>, "vocabulary": <0-4>, "grammar": <0-4>, '
    '"task": <0-4>, "advice": [<up to 3 short pieces of advice in Chinese; '
    "each MUST quote the student's exact words as evidence>], "
    '"upgrades": [<up to 2 higher-level rewrites of what the student just '
    'said, in the format "original phrase → better phrase">]}'
)


@dataclass
class RubricScores:
    fluency: int
    vocabulary: int
    grammar: int
    task: int
    mock_score: float
    advice: list[str] = field(default_factory=list)
    upgrades: list[str] = field(default_factory=list)


def map_to_mock_score(total: int) -> float:
    """四维总和（0-16）→ 0-9 模拟分（查表，越界截断）。"""
    index = max(0, min(len(RUBRIC_TO_SCORE) - 1, total))
    return RUBRIC_TO_SCORE[index]


DIMENSION_KEYS = ("fluency", "vocabulary", "grammar", "task")


class RubricParseError(ValueError):
    """模型输出缺维度/结构坏。调用方必须降级为 unavailable，不得出 0 分。"""


def _parse_dim(key: str, value: object) -> int:
    """维度必须存在且可解析为有限数；缺失/None/布尔/非有限数一律拒绝。

    合法有限数越界截断到 0-4、数字字符串兼容是既有测试约定的行为，保留。
    """
    if value is None or isinstance(value, bool):
        raise RubricParseError(f"评分维度 {key} 缺失或为 null/布尔值")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError as exc:
            raise RubricParseError(f"评分维度 {key} 不是数字：{value!r}") from exc
    else:
        raise RubricParseError(f"评分维度 {key} 类型错误：{type(value).__name__}")
    if not math.isfinite(number):
        raise RubricParseError(f"评分维度 {key} 非有限数：{value!r}")
    return max(0, min(DIMENSION_MAX, int(number)))


def _parse_text_list(key: str, value: object, max_items: int) -> list[str]:
    """advice/upgrades：缺省为空；必须是字符串列表（字符串会被逐字符拆开，拒绝）。

    空白元素丢弃（不影响评分）；非字符串元素属结构错误，整份拒绝。
    """
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, list):
        raise RubricParseError(f"{key} 必须是字符串列表，实际是 {type(value).__name__}")
    items: list[str] = []
    for element in value:
        if not isinstance(element, str):
            raise RubricParseError(f"{key} 含非字符串元素：{element!r}")
        if element.strip():
            items.append(element)
    return items[:max_items]


def build_rubric_user_prompt(prompt: str, band: str, transcript: str) -> str:
    return (
        f"Question ({band}): {prompt}\n"
        f"Student transcript: {transcript}\n"
        "Score the four dimensions and give advice/upgrades as instructed."
    )


def parse_rubric_response(content: str) -> RubricScores:
    """容错解析 LLM 输出：剥掉 markdown 代码栅栏，截断超量建议/升级。

    四个评分维度是必需字段：缺失/类型错/非有限数的输出整体拒绝
    （RubricParseError），由 worker 降级 unavailable——绝不能当真实 0 分
    （PRD US-08：模型失败显示「建议暂缺」，不出假分）。
    """
    cleaned = re.sub(
        r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE
    ).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match is None:
        raise RubricParseError("LLM 输出中没有 JSON 对象")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise RubricParseError(f"LLM 输出不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise RubricParseError(
            f"LLM 输出 JSON 必须是对象，实际是 {type(data).__name__}"
        )

    dims = {key: _parse_dim(key, data.get(key)) for key in DIMENSION_KEYS}
    advice = _parse_text_list("advice", data.get("advice"), MAX_ADVICE)
    upgrades = _parse_text_list("upgrades", data.get("upgrades"), MAX_UPGRADES)

    return RubricScores(
        fluency=dims["fluency"],
        vocabulary=dims["vocabulary"],
        grammar=dims["grammar"],
        task=dims["task"],
        mock_score=map_to_mock_score(sum(dims.values())),
        advice=advice,
        upgrades=upgrades,
    )


class ArkRubricScorer:
    """火山方舟 chat 接口按 rubric 出分（豆包/DeepSeek 均可，模型可配）。"""

    name = "ark"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or settings.ARK_BASE_URL).rstrip("/")
        self._client = client

    def score(self, prompt: str, band: str, transcript: str) -> RubricScores:
        if not self.api_key:
            raise ValueError("未配置 ARK_API_KEY")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": RUBRIC_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_rubric_user_prompt(prompt, band, transcript),
                },
            ],
            "temperature": 0.2,
            **fast_chat_options(self.model),
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        client = self._client if self._client is not None else _shared_client
        resp = client.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers
        )
        if resp.status_code != 200:
            raise ValueError(f"Ark chat 返回 {resp.status_code}: {resp.text[:200]}")
        content = resp.json()["choices"][0]["message"]["content"]
        return parse_rubric_response(content)
