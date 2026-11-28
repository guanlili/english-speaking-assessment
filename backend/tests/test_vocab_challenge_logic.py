"""每日挑战组包逻辑（#618）：3 款不同维度 / seed 稳定 / 素材不足降级。

只测纯组包逻辑（不落库、不判分）：把可练词表注入后看选出的维度与公告。
"""

import uuid
from datetime import date
from typing import cast

from sqlmodel import Session

from app.services import vocab_challenge as service

_fake_session = cast("Session", object())


class _Word:
    """最小词条替身：只带判素材需要的字段。"""

    def __init__(self, idx: int, *, example: str | None = None) -> None:
        self.id = idx
        self.headword = f"w{idx:02d}"
        self.meaning_zh = f"词{idx}"
        self.example_en = example
        self.morphology = None
        self.audio_url = None

    def __getattr__(self, name: str) -> None:  # 其它字段一律视为缺失
        return None


def _words(n: int, *, example: bool = False) -> list[_Word]:
    return [
        _Word(i, example=f"Use w{i:02d} here." if example else None)
        for i in range(1, n + 1)
    ]


def test_pack_three_distinct_dimensions(monkeypatch) -> None:
    """素材齐全时出 3 款，且维度、玩法都不重复。"""
    words = _words(20, example=True)
    monkeypatch.setattr(service, "_student_words", lambda *_a, **_k: words)
    pack = service.compose_pack(
        _fake_session, classroom_id=uuid.UUID(int=1), day=date(2026, 11, 28)
    )  # type: ignore[arg-type]

    assert len(pack.blocks) == 3
    assert len({b.dimension for b in pack.blocks}) == 3
    assert len({b.key for b in pack.blocks}) == 3
    assert pack.total_items == 15
    assert pack.degraded is False


def test_pack_is_stable_for_same_class_and_day(monkeypatch) -> None:
    """同班同日两次组包完全一致；换一天重新排（可以不同）。"""
    words = _words(20, example=True)
    monkeypatch.setattr(service, "_student_words", lambda *_a, **_k: words)
    day = date(2026, 11, 28)
    a = service.compose_pack(_fake_session, classroom_id=uuid.UUID(int=7), day=day)  # type: ignore[arg-type]
    b = service.compose_pack(_fake_session, classroom_id=uuid.UUID(int=7), day=day)  # type: ignore[arg-type]
    assert [(x.dimension, x.key, x.word_ids) for x in a.blocks] == [
        (x.dimension, x.key, x.word_ids) for x in b.blocks
    ]
    # 每款恰好 5 词且全局不重复
    deduped = [wid for block in a.blocks for wid in block.word_ids]
    assert len(deduped) == len(set(deduped)) == 15


def test_pack_degrades_with_reasons(monkeypatch) -> None:
    """只有释义：语境/词法维度跳过，给出原因，不硬凑空题。"""
    words = _words(10)
    monkeypatch.setattr(service, "_student_words", lambda *_a, **_k: words)
    pack = service.compose_pack(
        _fake_session, classroom_id=uuid.UUID(int=9), day=date(2026, 11, 28)
    )  # type: ignore[arg-type]

    assert pack.degraded is True
    assert {b.dimension for b in pack.blocks} <= {"spelling", "recognition"}
    assert "context" in pack.skipped and "morphology" in pack.skipped
    assert pack.total_items == 5 * len(pack.blocks)
    for block in pack.blocks:
        assert "context" not in block.key


def test_pack_empty_when_no_words(monkeypatch) -> None:
    """词表为空：0 款 + all 原因，学生端提示先建词库。"""
    monkeypatch.setattr(service, "_student_words", lambda *_a, **_k: [])
    pack = service.compose_pack(
        _fake_session, classroom_id=uuid.UUID(int=11), day=date(2026, 11, 28)
    )  # type: ignore[arg-type]
    assert pack.blocks == []
    assert pack.total_items == 0
    assert "all" in pack.skipped
