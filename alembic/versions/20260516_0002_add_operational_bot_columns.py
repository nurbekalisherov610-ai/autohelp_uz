"""add operational bot columns

Revision ID: 20260516_0002
Revises: 20260418_0001
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260516_0002"
down_revision: str | None = "20260418_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if not _has_column("users", "is_master"):
        op.add_column(
            "users",
            sa.Column("is_master", sa.Boolean(), server_default=sa.false(), nullable=False),
        )

    if not _has_column("orders", "video_file_id"):
        op.add_column("orders", sa.Column("video_file_id", sa.String(length=255), nullable=True))

    if not _has_column("orders", "rating"):
        op.add_column("orders", sa.Column("rating", sa.Integer(), nullable=True))


def downgrade() -> None:
    if _has_column("orders", "rating"):
        op.drop_column("orders", "rating")

    if _has_column("orders", "video_file_id"):
        op.drop_column("orders", "video_file_id")

    if _has_column("users", "is_master"):
        op.drop_column("users", "is_master")
