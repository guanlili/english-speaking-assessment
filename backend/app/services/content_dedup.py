"""题库查重键的单一事实源与预计算维护。

题库批量导入的疑似重复判定（question_bank_io._load_reference）要对
Passage/Unit/Scenario/ScenarioQuestion/RepeatSentence/Instruction 六张表的
文本列做归一化（NFKC + casefold + 空白折叠）比对；原实现把整表原文流式
拉回 Python 归一，题库增长后成为导入确认的线性热点。本模块：

1. 归一化函数只有这一份定义——写入维护（本模块钩子）与读取匹配
   （question_bank_io._matching_ids）共用；在别处复制此逻辑必然漂移。
2. flush 钩子把归一键的 sha256 写进各表的 dedup_*_hash 列，所有 ORM
   写入路径（管理端 CRUD、复制、导入、AI 出题、种子）自动覆盖，读取
   侧即可按索引匹配，不再扫原文。casefold/Unicode 空白在 SQL 里无法
   精确复刻（且函数会演进），故不用数据库生成列。

存量行由迁移回填；若哈希列为 NULL（理论上仅迁移前的行），读取侧回退
流式归一，语义与旧实现完全一致。
"""

import hashlib
import unicodedata
from typing import Any

from sqlalchemy import event
from sqlmodel import Session

from app.models import (
    Instruction,
    Passage,
    RepeatSentence,
    Scenario,
    ScenarioQuestion,
    Unit,
)


def norm_text(raw: str) -> str:
    """查重键规范化：NFKC（全角→半角）+ strip + casefold + 内部空白折叠。"""
    return " ".join(unicodedata.normalize("NFKC", raw).strip().casefold().split())


def hash_norm(norm: str) -> str:
    """已归一键 → sha256 hex（题库量级下碰撞概率为零，仅作索引键）。"""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def hash_text(raw: str) -> str:
    """原文 → 归一键哈希（写入维护用）。"""
    return hash_norm(norm_text(raw))


# 模型 → (原文属性, 哈希属性) 对；改列时这里与 models.py 同步
_DEDUP_FIELDS: dict[type, tuple[tuple[Any, Any], ...]] = {
    Passage: (
        (Passage.title, Passage.dedup_title_hash),
        (Passage.text, Passage.dedup_text_hash),
    ),
    Unit: ((Unit.title, Unit.dedup_title_hash),),
    Scenario: ((Scenario.topic, Scenario.dedup_topic_hash),),
    ScenarioQuestion: ((ScenarioQuestion.text, ScenarioQuestion.dedup_text_hash),),
    RepeatSentence: ((RepeatSentence.text, RepeatSentence.dedup_text_hash),),
    Instruction: ((Instruction.text, Instruction.dedup_text_hash),),
}


def apply_dedup_hashes(obj: object) -> None:
    """按 _DEDUP_FIELDS 重算对象的哈希列（幂等，未登记的模型直接跳过）。"""
    pairs = _DEDUP_FIELDS.get(type(obj))
    if pairs is None:
        return
    for source, target in pairs:
        setattr(obj, target.key, hash_text(str(getattr(obj, source.key) or "")))


def _maintain_dedup_hashes(
    session: Session, _flush_context: Any, _instances: Any
) -> None:
    # 全站每帧 flush 都会经过这里：非题库对象只付一次字典查找的代价
    for obj in session.new:
        apply_dedup_hashes(obj)
    for obj in session.dirty:
        apply_dedup_hashes(obj)


event.listen(Session, "before_flush", _maintain_dedup_hashes)
