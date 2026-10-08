"""文章拆句展开域逻辑：把 reading_split 的篇目展开成逐句朗读题。

拆句语义（2026-10-08 产品决策）：老师拆句就是为了给学生用——整篇对
学生太长，不方便练习和考试。展开发生在快照/题单构建层：句子条目用
确定性合成 ID（uuid5），不建独立篇目行；评分 worker 优先读作答快照，
全链路不按 item_id 反查篇目表，因此合成 ID 无需落库。

涉及调用方：set_assignment 发布快照、/today 非快照题单（单元指派/
自主练习）、attempts 非发布会话兜底。三处必须共用同一算法，保证同一
句子在任何入口拿到同一个 ID。
"""

import re
import uuid

from sqlmodel import Session, col, select

from app.models import Passage

# 合成 ID 命名空间（固定随机值）：uuid5 与篇目表的 uuid4 主键碰撞概率可忽略
_SENTENCE_NS = uuid.UUID("8d1f3a52-9c47-4b6e-b0f8-2a5d61e7c9b3")


def split_reading_sentences(text: str) -> list[str]:
    """按正文顺序拆句，保留句末标点（展示与展开共用同一算法）。"""
    sentences: list[str] = []
    for paragraph in re.split(r"\n+", text):
        sentences.extend(
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", paragraph.strip())
            if sentence.strip()
        )
    return sentences


def sentence_item_id(passage_id: uuid.UUID, index: int) -> uuid.UUID:
    """句子条目的确定性合成 ID：(passage_id, 句序) 唯一且可重复推导。"""
    return uuid.uuid5(_SENTENCE_NS, f"{passage_id}:sentence:{index}")


def _sentence_seconds(text: str) -> int:
    # ~2.5 词/秒朗读 + 2 秒缓冲，沿用 auto_split_sentences 的先例，限 4–30 秒
    return max(4, min(30, round(len(text.split()) / 2.5) + 2))


def _whole_item(passage: Passage) -> dict[str, object]:
    # 与 exercise.build_snapshot_item 的 passage 分支同构
    return {
        "type": "passage",
        "id": str(passage.id),
        "text": passage.text,
        "translation": passage.translation,
        "audio_url": passage.audio_url,
        "suggested_seconds": passage.suggested_seconds,
        "title": passage.title,
        "topic": passage.topic,
    }


def expand_reading_items(passage: Passage) -> list[dict[str, object]]:
    """篇目 → 题单条目：拆分篇目逐句一条，未拆分（或正文只剩单句）整篇一条。

    句子条目 parent_id 指回真实篇目行——会话锚点外键（practice_session.
    passage_id）与指派镜像（classroom.assigned_items）只允许真实 ID。
    """
    if not passage.reading_split:
        return [_whole_item(passage)]
    segments = split_reading_sentences(passage.text or "")
    if len(segments) < 2:
        # 拆分后正文被改成单句：退回整篇，保持题单永远有这道朗读题
        return [_whole_item(passage)]
    total = len(segments)
    return [
        {
            "type": "passage",
            "id": str(sentence_item_id(passage.id, index)),
            "parent_id": str(passage.id),
            "sentence_index": index + 1,
            "sentence_total": total,
            "text": sentence,
            # 整篇中文提示/标准音对单句不对位，不透传
            "translation": None,
            "audio_url": None,
            "suggested_seconds": _sentence_seconds(sentence),
            "title": passage.title,
            "topic": passage.topic,
        }
        for index, sentence in enumerate(segments)
    ]


def find_reading_item_by_id(
    session: Session, item_id: uuid.UUID
) -> dict[str, object] | None:
    """按合成 ID 反查句子条目（仅非发布会话提交兜底用）。

    合成 ID 无法从 uuid5 逆推回篇目，只能对拆分中的活动篇目重做展开匹配。
    篇目表很小（教师题库量级），全扫可接受；正文被中途编辑的窗口期行为
    与现网单元路径一致（提交时按最新内容评分）。
    """
    key = str(item_id)
    for passage in session.exec(
        select(Passage).where(
            col(Passage.is_active) == True,  # noqa: E712
            col(Passage.reading_split) == True,  # noqa: E712
            col(Passage.parent_passage_id).is_(None),
        )
    ).all():
        for item in expand_reading_items(passage):
            if item["id"] == key:
                return item
    return None
