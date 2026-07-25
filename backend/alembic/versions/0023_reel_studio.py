"""0023_reel_studio — 🎬 duet/repost lineage, effect + caption flags, repost count."""

import sqlalchemy as sa
from alembic import op

revision = "0023_reel_studio"
down_revision = "0022_reel_engagement"
branch_labels = None
depends_on = None

NEW_COLS = (
    ("parent_id", lambda: sa.Column("parent_id", sa.String(36), server_default="")),
    ("parent_author", lambda: sa.Column("parent_author", sa.String(80), server_default="")),
    ("effect", lambda: sa.Column("effect", sa.String(16), server_default="")),
    ("captioned", lambda: sa.Column("captioned", sa.Boolean, server_default=sa.false())),
    ("reposts", lambda: sa.Column("reposts", sa.Integer, server_default="0")),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "reels" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("reels")}
    # Guarded per-column: deployments created by Base.metadata.create_all
    # already carry them, and this migration must stay re-runnable.
    for name, factory in NEW_COLS:
        if name not in cols:
            op.add_column("reels", factory())
    idx = {i["name"] for i in insp.get_indexes("reels")}
    if "ix_reels_parent_id" not in idx and "parent_id" not in cols:
        op.create_index("ix_reels_parent_id", "reels", ["parent_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "reels" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("reels")}
    idx = {i["name"] for i in insp.get_indexes("reels")}
    if "ix_reels_parent_id" in idx:
        op.drop_index("ix_reels_parent_id", table_name="reels")
    with op.batch_alter_table("reels") as batch:
        for name, _ in reversed(NEW_COLS):
            if name in cols:
                batch.drop_column(name)
