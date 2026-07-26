"""0024_projects_tasks_keys — 🗂 Projects · ⏰ Scheduled Tasks · 🔑 Developer API keys.

Three independent Grok-parity surfaces land together because they share one
seam: a project can own a task, a task writes into a conversation, and an API
key bills through the same UsageEvent meter. Every step is existence-guarded so
the migration is re-runnable and safe on deployments whose tables were created
by Base.metadata.create_all.
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_projects_tasks_keys"
down_revision = "0023_reel_studio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "projects" not in tables:
        op.create_table(
            "projects",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="SET NULL")),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("description", sa.Text, server_default=""),
            sa.Column("instructions", sa.Text, server_default=""),
            sa.Column("emoji", sa.String(8), server_default="🗂"),
            sa.Column("accent", sa.String(9)),
            sa.Column("archived", sa.Boolean, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_projects_user_id", "projects", ["user_id"])
        op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"])

    if "project_files" not in tables:
        op.create_table(
            "project_files",
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("file_id", sa.String(36), sa.ForeignKey("files.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "scheduled_tasks" not in tables:
        op.create_table(
            "scheduled_tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL")),
            sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("prompt", sa.Text, nullable=False),
            sa.Column("mode", sa.String(16), server_default="chat"),
            sa.Column("search", sa.Boolean, server_default=sa.true()),
            sa.Column("schedule_kind", sa.String(12), server_default="daily"),
            sa.Column("hour_utc", sa.Integer, server_default="8"),
            sa.Column("minute_utc", sa.Integer, server_default="0"),
            sa.Column("weekdays", sa.String(20), server_default=""),
            sa.Column("enabled", sa.Boolean, server_default=sa.true()),
            sa.Column("notify", sa.Boolean, server_default=sa.true()),
            sa.Column("next_run_at", sa.DateTime(timezone=True)),
            sa.Column("last_run_at", sa.DateTime(timezone=True)),
            sa.Column("last_status", sa.String(16), server_default=""),
            sa.Column("last_error", sa.Text, server_default=""),
            sa.Column("run_count", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_scheduled_tasks_user_id", "scheduled_tasks", ["user_id"])
        op.create_index("ix_scheduled_tasks_project_id", "scheduled_tasks", ["project_id"])
        # the scheduler's hot query is "enabled tasks whose next_run_at is due"
        op.create_index("ix_scheduled_tasks_next_run_at", "scheduled_tasks", ["next_run_at"])

    if "task_runs" not in tables:
        op.create_table(
            "task_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("task_id", sa.String(36), sa.ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(16), server_default="ok"),
            sa.Column("summary", sa.Text, server_default=""),
            sa.Column("error", sa.Text, server_default=""),
            sa.Column("tokens_in", sa.Integer, server_default="0"),
            sa.Column("tokens_out", sa.Integer, server_default="0"),
            sa.Column("duration_ms", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_task_runs_task_id", "task_runs", ["task_id"])
        op.create_index("ix_task_runs_user_id", "task_runs", ["user_id"])
        op.create_index("ix_task_runs_created_at", "task_runs", ["created_at"])

    if "api_keys" not in tables:
        op.create_table(
            "api_keys",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(80), server_default="API key"),
            sa.Column("prefix", sa.String(16), nullable=False),
            # UNIQUE is declared inline rather than as a follow-up
            # create_unique_constraint: sqlite cannot ALTER constraints, and a
            # column-level constraint is portable across every backend we support.
            sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("scopes", sa.String(200), server_default="chat"),
            sa.Column("last_used_at", sa.DateTime(timezone=True)),
            sa.Column("calls", sa.Integer, server_default="0"),
            sa.Column("revoked", sa.Boolean, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
        op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])

    # conversations.project_id — files a chat under a project
    if "conversations" in tables:
        cols = {c["name"] for c in insp.get_columns("conversations")}
        if "project_id" not in cols:
            op.add_column("conversations", sa.Column("project_id", sa.String(36)))
            op.create_index("ix_conversations_project_id", "conversations", ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "conversations" in tables:
        cols = {c["name"] for c in insp.get_columns("conversations")}
        idx = {i["name"] for i in insp.get_indexes("conversations")}
        if "ix_conversations_project_id" in idx:
            op.drop_index("ix_conversations_project_id", table_name="conversations")
        if "project_id" in cols:
            with op.batch_alter_table("conversations") as batch:
                batch.drop_column("project_id")

    for table in ("api_keys", "task_runs", "scheduled_tasks", "project_files", "projects"):
        if table in tables:
            op.drop_table(table)
