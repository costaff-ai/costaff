"""Add notification_outbox — durable retry queue for failed channel pushes.

A task result stored only as a TaskComment is invisible to the user when
its channel push fails. dispatch_notification now enqueues failed pushes
here and a background loop retries with exponential backoff.

Guarded on table existence: ``0001_baseline`` runs ``create_all`` from the
live models, so a fresh database already has this table when 0003 runs.
Only databases stamped at an earlier revision need the CREATE.
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_notification_outbox"
down_revision = "0002_regular_work_channels"
branch_labels = None
depends_on = None


def _has_table() -> bool:
    inspector = sa.inspect(op.get_bind())
    return "notification_outbox" in inspector.get_table_names()


def upgrade() -> None:
    if _has_table():
        return
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("recipient", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_notification_outbox_status", "notification_outbox", ["status"])
    op.create_index("ix_notification_outbox_next_attempt_at", "notification_outbox", ["next_attempt_at"])


def downgrade() -> None:
    if _has_table():
        op.drop_table("notification_outbox")
