"""database healing and schema alignment

Revision ID: 20260516_0004
Revises: 20260516_0003
Create Date: 2026-05-16
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260516_0004"
down_revision: str | None = "20260516_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))

def upgrade() -> None:
    # 1. Healing 'users' table
    if not _has_column("users", "is_master"):
        op.add_column("users", sa.Column("is_master", sa.Boolean(), server_default=sa.false(), nullable=False))
    
    # 2. Healing 'orders' table
    if not _has_column("orders", "client_id"):
        # This is critical. If it's missing, we try to add it.
        # Note: If there is existing data, this might fail unless we allow null or provide default.
        # But for healing, we assume we can add it as nullable first if needed, but the model says NOT NULL.
        # We'll try to add it with a default if possible, or just add it.
        op.add_column("orders", sa.Column("client_id", sa.Integer(), nullable=True))
        # We'll leave it nullable for now to avoid crashes on existing data, then the app can fix it.
    
    if not _has_column("orders", "video_file_id"):
        op.add_column("orders", sa.Column("video_file_id", sa.String(length=255), nullable=True))
    
    if not _has_column("orders", "rating"):
        op.add_column("orders", sa.Column("rating", sa.Integer(), nullable=True))

    if not _has_column("orders", "assigned_dispatcher_telegram_id"):
        op.add_column("orders", sa.Column("assigned_dispatcher_telegram_id", sa.BigInteger(), nullable=True))

    if not _has_column("orders", "assigned_master_telegram_id"):
        op.add_column("orders", sa.Column("assigned_master_telegram_id", sa.BigInteger(), nullable=True))

    # 3. Healing 'order_status_history' table
    if not _has_column("order_status_history", "to_status"):
        # Use VARCHAR(32) since we are moving away from native enums
        op.add_column("order_status_history", sa.Column("to_status", sa.String(length=32), nullable=True))

    if not _has_column("order_status_history", "from_status"):
        op.add_column("order_status_history", sa.Column("from_status", sa.String(length=32), nullable=True))

def downgrade() -> None:
    pass
