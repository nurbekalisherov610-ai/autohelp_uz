"""
AutoHelp.uz - Review Model
Client ratings and feedback for completed orders.
"""
from datetime import datetime

from sqlalchemy import (
    Integer, String, DateTime, ForeignKey, Text, SmallInteger, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Review(Base):
    """Client review for a completed order."""
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), unique=True, nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    master_id: Mapped[int] = mapped_column(
        ForeignKey("masters.id"), nullable=False, index=True
    )
    rating: Mapped[int] = mapped_column(
        SmallInteger, nullable=False,
        comment="Rating from 1 to 5 stars"
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    order = relationship("Order", back_populates="review")
    user = relationship("User", back_populates="reviews")

    def __repr__(self) -> str:
        return f"<Review(order={self.order_id}, rating={self.rating})>"
