"""0027_reel_live_premium — 🔴 Go Live broadcasts + ⭐ reel watermark flag.

A live broadcast is a `reels` row with `kind='live'`: it occupies the feed while
streaming and becomes a normal replay when the creator ends it, so viewers keep
the post they were already watching instead of it vanishing.

Guarded per column so the migration is re-runnable and safe on deployments whose
tables were created by Base.metadata.create_all.
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_reel_live_premium"
down_revision = "0026_payments"
branch_labels = None
depends_on = None

NEW_COLS = (
    ("kind", lambda: sa.Column("kind", sa.String(10), server_default="clip")),
    ("live_state", lambda: sa.Column("live_state", sa.String(12), server_default="")),
    ("live_provider", lambda: sa.Column("live_provider", sa.String(16), server_default="")),
    ("live_stream_id", lambda: sa.Column("live_stream_id", sa.String(80), server_default="")),
    ("live_playback_url", lambda: sa.Column("live_playback_url", sa.String(600), server_default="")),
    ("live_viewers", lambda: sa.Column("live_viewers", sa.Integer, server_default="0")),
    ("live_peak_viewers", lambda: sa.Column("live_peak_viewers", sa.Integer, server_default="0")),
    ("live_started_at", lambda: sa.Column("live_started_at", sa.DateTime(timezone=True))),
    ("live_ended_at", lambda: sa.Column("live_ended_at", sa.DateTime(timezone=True))),
    ("watermarked", lambda: sa.Column("watermarked", sa.Boolean, server_default=sa.false())),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "reels" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("reels")}
    for name, factory in NEW_COLS:
        if name not in cols:
            op.add_column("reels", factory())
    # The feed filters live broadcasts to the top on every load — index the key.
    idx = {i["name"] for i in insp.get_indexes("reels")}
    if "ix_reels_kind" not in idx and "kind" not in cols:
        op.create_index("ix_reels_kind", "reels", ["kind"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "reels" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("reels")}
    idx = {i["name"] for i in insp.get_indexes("reels")}
    if "ix_reels_kind" in idx:
        op.drop_index("ix_reels_kind", table_name="reels")
    with op.batch_alter_table("reels") as batch:
        for name, _ in reversed(NEW_COLS):
            if name in cols:
                batch.drop_column(name)
