"""0022_reel_engagement — 📊 share/save counters + saved-reels table."""

import sqlalchemy as sa
from alembic import op

revision = "0022_reel_engagement"
down_revision = "0021_reels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "reels" in tables:
        cols = {c["name"] for c in insp.get_columns("reels")}
        # Guarded per-column: a deployment may have been created by
        # Base.metadata.create_all (which already has them) rather than alembic.
        if "shares" not in cols:
            op.add_column("reels", sa.Column("shares", sa.Integer, server_default="0"))
        if "saves" not in cols:
            op.add_column("reels", sa.Column("saves", sa.Integer, server_default="0"))

    if "reel_saves" not in tables:
        op.create_table(
            "reel_saves",
            sa.Column("reel_id", sa.String(36), sa.ForeignKey("reels.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        # "my saved reels, newest save first" is the hot query
        op.create_index("ix_reel_saves_user_id", "reel_saves", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()
    if "reel_saves" in tables:
        op.drop_table("reel_saves")
    if "reels" in tables:
        cols = {c["name"] for c in insp.get_columns("reels")}
        with op.batch_alter_table("reels") as batch:
            if "saves" in cols:
                batch.drop_column("saves")
            if "shares" in cols:
                batch.drop_column("shares")
