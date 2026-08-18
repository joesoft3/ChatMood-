"""0028_conversation_pins — 📌 pin a chat to the top of the sidebar.

Guarded so the migration is re-runnable and safe on deployments whose tables
were created by Base.metadata.create_all (the column already exists there).
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_conversation_pins"
down_revision = "0027_reel_live_premium"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "conversations" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "pinned" not in cols:
        op.add_column(
            "conversations",
            sa.Column("pinned", sa.Boolean, server_default=sa.false(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "conversations" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "pinned" in cols:
        with op.batch_alter_table("conversations") as batch:
            batch.drop_column("pinned")
