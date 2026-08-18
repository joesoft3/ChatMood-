"""0030_chatgpt_parity — study_mode, archived, gpt_id, custom_gpts.

Guarded so the migration is re-runnable and safe on deployments whose tables
were created by Base.metadata.create_all (the columns already exist there).
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_chatgpt_parity"
down_revision = "0029_grok_parity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        if "study_mode" not in cols:
            op.add_column(
                "users",
                sa.Column("study_mode", sa.Boolean, server_default=sa.false(), nullable=False),
            )
    if "conversations" in tables:
        cols = {c["name"] for c in insp.get_columns("conversations")}
        if "archived" not in cols:
            op.add_column(
                "conversations",
                sa.Column("archived", sa.Boolean, server_default=sa.false(), nullable=False),
            )
        if "gpt_id" not in cols:
            op.add_column("conversations", sa.Column("gpt_id", sa.String(48), nullable=True))
            op.create_index("ix_conversations_gpt_id", "conversations", ["gpt_id"])
    if "custom_gpts" not in tables:
        op.create_table(
            "custom_gpts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("description", sa.Text, server_default="", nullable=False),
            sa.Column("instructions", sa.Text, server_default="", nullable=False),
            sa.Column("emoji", sa.String(8), server_default="🤖", nullable=False),
            sa.Column("starters", sa.JSON, nullable=True),
            sa.Column("file_ids", sa.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_custom_gpts_user_id", "custom_gpts", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "custom_gpts" in tables:
        op.drop_index("ix_custom_gpts_user_id", table_name="custom_gpts")
        op.drop_table("custom_gpts")
    if "conversations" in tables:
        cols = {c["name"] for c in insp.get_columns("conversations")}
        if "gpt_id" in cols:
            op.drop_index("ix_conversations_gpt_id", table_name="conversations")
            with op.batch_alter_table("conversations") as batch:
                batch.drop_column("gpt_id")
        if "archived" in cols:
            with op.batch_alter_table("conversations") as batch:
                batch.drop_column("archived")
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        if "study_mode" in cols:
            with op.batch_alter_table("users") as batch:
                batch.drop_column("study_mode")
