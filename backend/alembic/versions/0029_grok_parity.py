"""0029_grok_parity — 😄 fun_mode on users, 👻 temporary on conversations.

Guarded so the migration is re-runnable and safe on deployments whose tables
were created by Base.metadata.create_all (the columns already exist there).
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_grok_parity"
down_revision = "0028_conversation_pins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        if "fun_mode" not in cols:
            op.add_column(
                "users",
                sa.Column("fun_mode", sa.Boolean, server_default=sa.false(), nullable=False),
            )
    if "conversations" in tables:
        cols = {c["name"] for c in insp.get_columns("conversations")}
        if "temporary" not in cols:
            op.add_column(
                "conversations",
                sa.Column("temporary", sa.Boolean, server_default=sa.false(), nullable=False),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        if "fun_mode" in cols:
            with op.batch_alter_table("users") as batch:
                batch.drop_column("fun_mode")
    if "conversations" in tables:
        cols = {c["name"] for c in insp.get_columns("conversations")}
        if "temporary" in cols:
            with op.batch_alter_table("conversations") as batch:
                batch.drop_column("temporary")
