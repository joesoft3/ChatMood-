"""0026_payments — 💳 admin-published payment methods + user payment submissions.

Two tables:

* `payment_methods` — MoMo numbers / bank accounts the admin publishes as
  payment destinations. `active` retires one without deleting it, so historical
  payments keep pointing at something real.
* `payments` — one row per payment attempt (pending → approved | rejected).
  Rows are never deleted: "why does this account have Pro?" must stay
  answerable months later.

Amounts are integer minor units (pesewas), never floats.

Existence-guarded so the migration is re-runnable and safe on deployments whose
tables were created by Base.metadata.create_all.
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_payments"
down_revision = "0025_watermark_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "payment_methods" not in tables:
        op.create_table(
            "payment_methods",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("kind", sa.String(12), server_default="momo"),
            sa.Column("label", sa.String(80), server_default=""),
            sa.Column("network", sa.String(20), server_default=""),
            sa.Column("account_name", sa.String(120), server_default=""),
            sa.Column("account_number", sa.String(60), server_default=""),
            sa.Column("bank_name", sa.String(80), server_default=""),
            sa.Column("instructions", sa.Text, server_default=""),
            sa.Column("currency", sa.String(8), server_default="GHS"),
            sa.Column("active", sa.Boolean, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "payments" not in tables:
        op.create_table(
            "payments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("method_id", sa.String(36), sa.ForeignKey("payment_methods.id", ondelete="SET NULL")),
            sa.Column("provider", sa.String(16), server_default="manual"),
            sa.Column("invoice_code", sa.String(16), server_default=""),
            sa.Column("reference", sa.String(64), server_default=""),
            sa.Column("payer_name", sa.String(120), server_default=""),
            sa.Column("payer_phone", sa.String(40), server_default=""),
            sa.Column("amount_minor", sa.Integer, server_default="0"),
            sa.Column("currency", sa.String(8), server_default="GHS"),
            sa.Column("plan", sa.String(20), server_default="pro"),
            sa.Column("months", sa.Integer, server_default="1"),
            sa.Column("offer_id", sa.String(32), server_default=""),
            sa.Column("status", sa.String(12), server_default="pending"),
            sa.Column("note", sa.Text, server_default=""),
            sa.Column("admin_note", sa.Text, server_default=""),
            sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("reviewed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_payments_user_id", "payments", ["user_id"])
        op.create_index("ix_payments_provider", "payments", ["provider"])
        # the admin queue is "pending, newest first" — index both sort keys
        op.create_index("ix_payments_status", "payments", ["status"])
        op.create_index("ix_payments_created_at", "payments", ["created_at"])
        # duplicate-reference lookups happen on every submission
        op.create_index("ix_payments_reference", "payments", ["reference"])
        op.create_index("ix_payments_invoice_code", "payments", ["invoice_code"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table in ("payments", "payment_methods"):
        if table in tables:
            op.drop_table(table)
