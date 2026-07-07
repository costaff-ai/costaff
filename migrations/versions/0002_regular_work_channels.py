"""Add regular_works.channels — JSON list of {channel, recipient} targets.

Regular works can now deliver to multiple channels per run. The legacy
``channel`` / ``recipient`` columns are kept and mirror the first target
so older readers keep working.

Guarded on column existence: ``0001_baseline`` runs ``create_all`` from the
live models, so a fresh database already has this column when 0002 runs.
Only databases stamped at 0001 before this column existed need the ALTER.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_regular_work_channels"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return "channels" in {c["name"] for c in inspector.get_columns("regular_works")}


def upgrade() -> None:
    if not _has_column():
        op.add_column("regular_works", sa.Column("channels", sa.String(), nullable=True))


def downgrade() -> None:
    if _has_column():
        op.drop_column("regular_works", "channels")
