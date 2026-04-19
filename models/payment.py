"""
AutoHelp.uz - Payment Model
Tracks payments for completed orders.
"""
from datetime import datetime

from sqlalchemy import (
    Integer, Float, String, DateTime, ForeignKey, Text, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Payment(Base):
    """Payment record for a completed order."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), unique=True, nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    video_file_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Telegram file_id of master's completion video"
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by_dispatcher: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    order = relationship("Order", back_populates="payment")

    def __repr__(self) -> str:
        return f"<Payment(order={self.order_id}, amount={self.amount})>"
