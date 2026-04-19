"""
AutoHelp.uz - Order Status History Model
Tracks every status change for full audit trail.
"""
from datetime import datetime

from sqlalchemy import (
    Integer, String, DateTime, Enum, ForeignKey, Text, BigInteger, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from models.order import OrderStatus


class OrderStatusHistory(Base):
    """Audit trail for order status changes."""
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), nullable=False, index=True
    )
    old_status: Mapped[OrderStatus | None] = mapped_column(
        Enum(OrderStatus), nullable=True
    )
    new_status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), nullable=False
    )
    changed_by_telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    changed_by_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    order = relationship("Order", back_populates="status_history")

    def __repr__(self) -> str:
        return f"<StatusHistory(order={self.order_id}, {self.old_status}→{self.new_status})>"
