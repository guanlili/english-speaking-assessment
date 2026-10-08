"""Keep reading sentences under their article; retain legacy IDs and snapshots.

Revision ID: 60b66752e050
Revises: a6b1c3d5e7f9
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "60b66752e050"
down_revision = "a6b1c3d5e7f9"
branch_labels = None
depends_on = None


def _legacy_segments(text: str) -> list[str]:
    # Freeze the previous split algorithm: migration must not follow future changes.
    segments: list[str] = []
    for paragraph in [p.strip() for p in re.split(r"\n+", text) if p.strip()]:
        if len(paragraph.split()) <= 90:
            segments.append(paragraph)
            continue
        buf: list[str] = []
        words = 0
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            count = len(sentence.split())
            if buf and words + count > 90:
                segments.append(" ".join(buf))
                buf, words = [], 0
            buf.append(sentence)
            words += count
        if buf:
            segments.append(" ".join(buf))
    return segments


def upgrade():
    op.add_column(
        "passage",
        sa.Column(
            "reading_split", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column("passage", sa.Column("parent_passage_id", sa.Uuid(), nullable=True))
    op.create_index("ix_passage_parent_passage_id", "passage", ["parent_passage_id"])
    op.create_foreign_key(
        "passage_parent_passage_id_fkey",
        "passage",
        "passage",
        ["parent_passage_id"],
        ["id"],
        ondelete="CASCADE",
    )
    connection = op.get_bind()
    rows = list(
        connection.execute(
            sa.text(
                "SELECT id, title, text, topic, cefr_band, unit_id, is_active, created_at FROM passage"
            )
        ).mappings()
    )
    # Only complete, unambiguous matches to the old generated titles AND text are adopted.
    proposals: list[tuple[object, list[object]]] = []
    nums = "一二三四五六七八九十"
    for parent in rows:
        if parent["is_active"]:
            continue
        paragraphs = _legacy_segments(parent["text"])
        sentences = [
            part.strip()
            for part in re.split(r"\n+|(?<=[.!?])\s+", parent["text"])
            if part.strip()
        ]
        modes = [paragraphs] if paragraphs == sentences else [paragraphs, sentences]
        for segments in modes:
            if len(segments) < 2:
                continue
            base_title = (
                re.sub(r"（[一二三四五六七八九十\d]+）$", "", parent["title"]).strip()
                or parent["title"]
            )
            children: list[object] = []
            for index, segment in enumerate(segments):
                num = nums[index] if index < 10 else str(index + 1)
                matches = [
                    row
                    for row in rows
                    if row["id"] != parent["id"]
                    and row["title"] == f"{base_title}（{num}）"
                    and row["text"] == segment
                    and row["topic"] == parent["topic"]
                    and row["cefr_band"] == parent["cefr_band"]
                    and row["unit_id"] == parent["unit_id"]
                    and row["is_active"]
                    and row["created_at"] is not None
                    and parent["created_at"] is not None
                    and row["created_at"] >= parent["created_at"]
                ]
                if len(matches) != 1:
                    break
                children.append(matches[0]["id"])
            if len(children) == len(segments):
                proposals.append((parent["id"], children))
    # Shared candidates mean ambiguous provenance: leave both possible families alone.
    counts: dict[object, int] = {}
    for _, children in proposals:
        for child in children:
            counts[child] = counts.get(child, 0) + 1
    for parent_id, children in proposals:
        if any(counts[child] != 1 for child in children):
            continue
        connection.execute(
            sa.text(
                "UPDATE passage SET reading_split = true, is_active = true WHERE id = :id"
            ),
            {"id": parent_id},
        )
        for child in children:
            connection.execute(
                sa.text(
                    "UPDATE passage SET parent_passage_id = :parent, is_active = false WHERE id = :id"
                ),
                {"parent": parent_id, "id": child},
            )
    op.alter_column("passage", "reading_split", server_default=None)


def downgrade():
    op.execute(
        "UPDATE passage SET is_active = false WHERE id IN (SELECT DISTINCT parent_passage_id FROM passage WHERE parent_passage_id IS NOT NULL)"
    )
    op.execute(
        "UPDATE passage SET is_active = true WHERE parent_passage_id IS NOT NULL"
    )
    op.drop_constraint("passage_parent_passage_id_fkey", "passage", type_="foreignkey")
    op.drop_index("ix_passage_parent_passage_id", table_name="passage")
    op.drop_column("passage", "parent_passage_id")
    op.drop_column("passage", "reading_split")
