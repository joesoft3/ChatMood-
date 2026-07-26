"""0025_watermark_flags — 🏷 record whether a render carries the free-tier badge.

Two boolean columns, both defaulting to false:

* `designs.watermarked`  — the badge is baked into both the web and print tiers.
* `films.watermarked`    — captured at CREATE time so the resume path re-applies
  the same decision after a restart, instead of re-deriving entitlement and
  half-badging a film whose owner upgraded mid-render.

Existing rows default to false, which is the correct history: they were rendered
before watermarking existed, so they genuinely carry no badge.
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_watermark_flags"
down_revision = "0024_projects_tasks_keys"
branch_labels = None
depends_on = None

TARGETS = ("designs", "films")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table in TARGETS:
        if table not in tables:
            continue
        # Guarded per-column: deployments created by Base.metadata.create_all
        # already carry it, and this migration must stay re-runnable.
        cols = {c["name"] for c in insp.get_columns(table)}
        if "watermarked" not in cols:
            op.add_column(
                table,
                sa.Column("watermarked", sa.Boolean, nullable=False, server_default=sa.false()),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table in reversed(TARGETS):
        if table not in tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if "watermarked" in cols:
            with op.batch_alter_table(table) as batch:
                batch.drop_column("watermarked")
