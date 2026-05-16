"""initial schema

Revision ID: 20260418_0001
Revises:
Create Date: 2026-04-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260418_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

order_status_enum = sa.Enum(
    "NEW",
    "ASSIGNED",
    "ACCEPTED",
    "ON_THE_WAY",
    "ARRIVED",
    "IN_PROGRESS",
    "AWAITING_CONFIRM",
    "COMPLETED",
    "CANCELLED",
    "REJECTED",
    name="order_status_enum",
    native_enum=False,
)

issue_type_enum = sa.Enum(
    "ENGINE_NOT_STARTING",
    "BATTERY_DOWN",
    "FLAT_TIRE",
    "OTHER",
    name="issue_type_enum",
    native_enum=False,
)


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("telegram_id", sa.BigInteger(), nullable=False),
            sa.Column("full_name", sa.String(length=255), nullable=True),
            sa.Column("phone", sa.String(length=32), nullable=True),
            sa.Column("language", sa.String(length=10), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_users"),
            sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        )
    if not _has_index("users", "ix_users_telegram_id"):
        op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=False)

    if not _has_table("orders"):
        op.create_table(
            "orders",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("issue_type", issue_type_enum, nullable=False),
            sa.Column("issue_label", sa.String(length=100), nullable=False),
            sa.Column("phone", sa.String(length=32), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=False),
            sa.Column("longitude", sa.Float(), nullable=False),
            sa.Column("status", order_status_enum, nullable=False),
            sa.Column("assigned_dispatcher_telegram_id", sa.BigInteger(), nullable=True),
            sa.Column("assigned_master_telegram_id", sa.BigInteger(), nullable=True),
            sa.Column("final_amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["client_id"], ["users.id"], name="fk_orders_client_id_users", ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id", name="pk_orders"),
        )
    if not _has_index("orders", "ix_orders_status"):
        op.create_index("ix_orders_status", "orders", ["status"], unique=False)
    if not _has_index("orders", "ix_orders_assigned_master_telegram_id"):
        op.create_index(
            "ix_orders_assigned_master_telegram_id",
            "orders",
            ["assigned_master_telegram_id"],
            unique=False,
        )

    if not _has_table("order_status_history"):
        op.create_table(
            "order_status_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("order_id", sa.Integer(), nullable=False),
            sa.Column("from_status", order_status_enum, nullable=True),
            sa.Column("to_status", order_status_enum, nullable=False),
            sa.Column("actor_telegram_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_order_status_history_order_id_orders", ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_order_status_history"),
        )
    if not _has_index("order_status_history", "ix_order_status_history_order_id_id"):
        op.create_index(
            "ix_order_status_history_order_id_id",
            "order_status_history",
            ["order_id", "id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_order_status_history_order_id_id", table_name="order_status_history")
    op.drop_table("order_status_history")

    op.drop_index("ix_orders_assigned_master_telegram_id", table_name="orders")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
