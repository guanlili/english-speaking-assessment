"""vocab student self practice sessions

Revision ID: e7a528475a53
Revises: ff23287ceb31
Create Date: 2026-10-05 22:11:25.103402

词汇自主练习：vocabulary_session 增加 kind / source_book_id /
snapshot_items / mix_wrong。存量行 kind 默认 'task'，含义不变；
自主/复习轮的题单固化在会话自身 snapshot_items（可空 JSON）。

回退限制：downgrade 会丢掉 kind 与 snapshot_items——存在自主/复习轮
数据时回退是有损的（这些轮会变成没有任务绑定、没有题单的哑行），
因此检测到此类数据时直接拒绝执行，不做静默删数（与 ff23287ceb31
的回退限制同口径）。
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "e7a528475a53"
down_revision = "ff23287ceb31"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vocabulary_session",
        sa.Column(
            "kind",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            server_default="task",
            nullable=False,
        ),
    )
    op.add_column(
        "vocabulary_session", sa.Column("source_book_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "vocabulary_session", sa.Column("snapshot_items", sa.JSON(), nullable=True)
    )
    op.add_column(
        "vocabulary_session",
        sa.Column("mix_wrong", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_foreign_key(
        "fk_vocab_session_source_book",
        "vocabulary_session",
        "vocabulary_book",
        ["source_book_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    # 存在自主/复习轮数据时回退会丢失其固化题单（有损），直接拒绝；
    # 确认放弃这些练习记录后按提示手动清理再回退。
    count = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM vocabulary_session WHERE kind IN ('self', 'review')"
        )
    ).scalar()
    if count:
        raise RuntimeError(
            f"vocabulary_session 存在 {count} 条自主/复习轮数据，回退将丢失其固化题单（有损），已拒绝执行。"
            "如确认放弃这些练习记录，请先手动执行："
            "DELETE FROM vocabulary_answer WHERE session_id IN "
            "(SELECT id FROM vocabulary_session WHERE kind IN ('self','review')); "
            "DELETE FROM vocabulary_session WHERE kind IN ('self','review'); "
            "然后再运行 alembic downgrade。"
        )
    # 约束名为 upgrade 里显式创建的名字（autogen 匿名约束无法可靠回滚）
    op.drop_constraint(
        "fk_vocab_session_source_book", "vocabulary_session", type_="foreignkey"
    )
    op.drop_column("vocabulary_session", "mix_wrong")
    op.drop_column("vocabulary_session", "snapshot_items")
    op.drop_column("vocabulary_session", "source_book_id")
    op.drop_column("vocabulary_session", "kind")
