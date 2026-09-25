"""评分引擎抽象（PRD §7.2）。

调用方（路由/worker）只依赖这里的协议，不感知具体引擎：
换讯飞 / Azure / Speechace 时新增实现类 + 配置切换，页面与接口不变。

PRD 要求的三个 scorer 中，MVP（2 天演示）只实现跟读：
    ReadAloudScorer = ASR 转写 + heuristic 打分
开放问答（OpenResponseScorer）与词表（LexiconScorer）在第 2/3 周阶段加入。
"""

from dataclasses import dataclass
from typing import Protocol


class ScoringError(Exception):
    """评分失败（引擎不可用、音频无法识别等）。作答保留，学生可重录。"""


class AsrProvider(Protocol):
    """语音转文字提供方。返回纯文本；无语音时返回空字符串。"""

    name: str

    def transcribe(self, audio: bytes, mime_type: str) -> str: ...


@dataclass
class ReadAloudScores:
    """跟读三维分 + 建议（PRD US-03：完整度/流利度/总评 + 不超过两句建议）。"""

    transcript: str
    completeness: int  # 0-100，与参考文本的词命中率
    fluency: int  # 0-100，语速与停顿的启发式
    accuracy: int  # 0-100，启发式阶段与完整度同源，接发音引擎后独立
    overall: int  # 0-100，加权总评
    advice: list[str]  # 最多两条，须引用学生具体表现


@dataclass
class OpenResponseScores:
    """开放问答反馈（PRD §4：2 周只展示总评和一句建议；rubric 四维是第 3 周）。"""

    transcript: str
    fluency: int  # 0-100，语速启发式
    overall: int  # 0-100，内容量与流利度加权
    advice: list[str]  # 最多一条
