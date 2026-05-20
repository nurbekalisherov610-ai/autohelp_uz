from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.db.enums import IssueType, OrderStatus


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    issue_type: Mapped[IssueType] = mapped_column(
        Enum(IssueType, name="issue_type_enum", native_enum=False),
        nullable=False,
    )
    issue_label: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    latitude: Mapped[float] = mapped_column(nullable=False)
    longitude: Mapped[float] = mapped_column(nullable=False)

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status_enum", native_enum=False),
        default=OrderStatus.NEW,
        nullable=False,
        index=True,
    )

    assigned_dispatcher_telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    assigned_master_telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    final_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    video_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating: Mapped[int | None] = mapped_column(nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    shortcomings: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # FIX: Use lazy="raise" to prevent accidental sync lazy-loading in async context.
    # All data needed from relations must be explicitly loaded via joinedload/selectinload
    # in the query, or accessed as plain columns (telegram_id, etc.) on the Order itself.
    client: Mapped["User"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "User", back_populates="orders", lazy="raise"
    )
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(
        "OrderStatusHistory",
        back_populates="order",
        lazy="raise",
        cascade="all, delete-orphan",
    )


class OrderStatusHistory(Base, TimestampMixin):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[OrderStatus | None] = mapped_column(
        Enum(OrderStatus, name="order_status_enum", native_enum=False),
        nullable=True,
    )
    to_status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status_enum", native_enum=False),
        nullable=False,
    )
    actor_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    order: Mapped["Order"] = relationship("Order", back_populates="status_history", lazy="raise")


Index(
    "ix_order_status_history_order_id_id",
    OrderStatusHistory.order_id,
    OrderStatusHistory.id,
)
