"""make user fields nullable and align orders schema

Revision ID: 20260516_0005
Revises: 20260516_0004
Create Date: 2026-05-16
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260516_0005"
down_revision: str | None = "20260516_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))

def upgrade() -> None:
    # 1. Fix NOT NULL violation on 'users' table
    # Many legacy databases have 'phone' or 'full_name' as NOT NULL, 
    # but we need to create users before we have their phone.
    op.execute("ALTER TABLE users ALTER COLUMN phone DROP NOT NULL")
    op.execute("ALTER TABLE users ALTER COLUMN full_name DROP NOT NULL")
    op.execute("ALTER TABLE users ALTER COLUMN language DROP NOT NULL")

    # 2. Heal 'orders' table for missing columns reported in preflight
    if not _has_column("orders", "issue_label"):
        op.add_column("orders", sa.Column("issue_label", sa.String(length=100), nullable=True))
    
    if not _has_column("orders", "phone"):
        op.add_column("orders", sa.Column("phone", sa.String(length=32), nullable=True))
    
    if not _has_column("orders", "latitude"):
        op.add_column("orders", sa.Column("latitude", sa.Float(), nullable=True))

    if not _has_column("orders", "longitude"):
        op.add_column("orders", sa.Column("longitude", sa.Float(), nullable=True))

def downgrade() -> None:
    pass
