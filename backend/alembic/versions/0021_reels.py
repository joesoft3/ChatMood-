"""0021_reels — 📺 Creator Reel: shared public feed of creator videos."""

import sqlalchemy as sa
from alembic import op

revision = "0021_reels"
down_revision = "0020_vector_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()

    if "reels" not in tables:
        op.create_table(
            "reels",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_name", sa.String(80), server_default=""),
            sa.Column("caption", sa.Text, server_default=""),
            sa.Column("source", sa.String(12), server_default="upload"),
            sa.Column("film_id", sa.String(36), server_default=""),
            sa.Column("filename", sa.String(48), server_default=""),
            sa.Column("source_url", sa.String(600), server_default=""),
            sa.Column("poster", sa.String(48), server_default=""),
            sa.Column("status", sa.String(12), server_default="live"),
            sa.Column("views", sa.Integer, server_default="0"),
            sa.Column("likes", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_reels_user_id", "reels", ["user_id"])
        op.create_index("ix_reels_status", "reels", ["status"])
        # the feed is "live posts, newest first" — index the sort key
        op.create_index("ix_reels_created_at", "reels", ["created_at"])

    if "reel_likes" not in tables:
        op.create_table(
            "reel_likes",
            sa.Column("reel_id", sa.String(36), sa.ForeignKey("reels.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "reel_likes" in tables:
        op.drop_table("reel_likes")
    if "reels" in tables:
        op.drop_table("reels")
