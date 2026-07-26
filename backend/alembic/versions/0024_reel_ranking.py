"""0024_reel_ranking — 🏆 For You ranking signals, follow graph, comments, watch telemetry.

Adds what a chronological feed doesn't need and a ranked one can't work without:

  * `reels.comments` / `watch_ms` / `completion_sum` / `completion_n` /
    `duration_s` / `hot_score` / `ranked_at` — denormalized ranking inputs, so
    scoring a page is one indexed scan rather than N subqueries.
  * `reel_follows` — the follow graph, previously a `localStorage` set in the
    browser (so it never influenced the feed and vanished across devices).
  * `reel_comments` — the conversation layer.
  * `reel_watches` — per-(reel, viewer) watch time and completion, the signal
    the ranker actually leans on.

Every step is guarded/idempotent in the same style as 0022/0023: deployments
created by `Base.metadata.create_all` already carry the columns, and this
migration must stay re-runnable.
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_reel_ranking"
down_revision = "0023_reel_studio"
branch_labels = None
depends_on = None

NEW_COLS = (
    ("comments", lambda: sa.Column("comments", sa.Integer, server_default="0")),
    ("watch_ms", lambda: sa.Column("watch_ms", sa.Integer, server_default="0")),
    ("completion_sum", lambda: sa.Column("completion_sum", sa.Float, server_default="0")),
    ("completion_n", lambda: sa.Column("completion_n", sa.Integer, server_default="0")),
    ("duration_s", lambda: sa.Column("duration_s", sa.Float, server_default="0")),
    ("hot_score", lambda: sa.Column("hot_score", sa.Float, server_default="0")),
    ("ranked_at", lambda: sa.Column("ranked_at", sa.DateTime(timezone=True), nullable=True)),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "reels" in tables:
        cols = {c["name"] for c in insp.get_columns("reels")}
        for name, factory in NEW_COLS:
            if name not in cols:
                op.add_column("reels", factory())
        idx = {i["name"] for i in insp.get_indexes("reels")}
        # The ranked feed orders by score; without this it's a full sort.
        if "ix_reels_hot_score" not in idx and "hot_score" not in cols:
            op.create_index("ix_reels_hot_score", "reels", ["hot_score"])

    if "reel_follows" not in tables:
        op.create_table(
            "reel_follows",
            sa.Column("follower_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        # "who do I follow" (feed build) and "who follows X" (profile count).
        op.create_index("ix_reel_follows_follower_id", "reel_follows", ["follower_id"])
        op.create_index("ix_reel_follows_author_id", "reel_follows", ["author_id"])

    if "reel_comments" not in tables:
        op.create_table(
            "reel_comments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("reel_id", sa.String(36), sa.ForeignKey("reels.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_name", sa.String(80), server_default=""),
            sa.Column("body", sa.Text, server_default=""),
            sa.Column("likes", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_reel_comments_reel_id", "reel_comments", ["reel_id"])
        op.create_index("ix_reel_comments_user_id", "reel_comments", ["user_id"])
        op.create_index("ix_reel_comments_created_at", "reel_comments", ["created_at"])

    if "reel_watches" not in tables:
        op.create_table(
            "reel_watches",
            sa.Column("reel_id", sa.String(36), sa.ForeignKey("reels.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("watched_ms", sa.Integer, server_default="0"),
            sa.Column("completion", sa.Float, server_default="0"),
            sa.Column("replays", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_reel_watches_reel_id", "reel_watches", ["reel_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    for t in ("reel_watches", "reel_comments", "reel_follows"):
        if t in tables:
            op.drop_table(t)

    if "reels" in tables:
        cols = {c["name"] for c in insp.get_columns("reels")}
        idx = {i["name"] for i in insp.get_indexes("reels")}
        # Drop the index BEFORE the column it covers. `batch_alter_table` on
        # SQLite rebuilds the table by copy-and-move and faithfully re-creates
        # every index it found — including one over a column being dropped in
        # the same batch, which then fails with "no such column: hot_score".
        if "ix_reels_hot_score" in idx:
            op.drop_index("ix_reels_hot_score", table_name="reels")
        with op.batch_alter_table("reels") as batch:
            for name, _ in reversed(NEW_COLS):
                if name in cols:
                    batch.drop_column(name)
