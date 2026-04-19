"""
AutoHelp.uz - Order Draft Model
Tracks unfinished client order flows for reminder nudges.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, String, DateTime, Boolean, ForeignKey, func
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class OrderDraft(Base):
    """Unfinished order flow tracking per Telegram user."""
    __tablename__ = "order_drafts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    language: Mapped[str] = mapped_column(String(2), default="uz", nullable=False)
    fsm_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<OrderDraft(tg={self.telegram_id}, state={self.fsm_state}, "
            f"active={self.is_active}, reminded={self.reminder_sent})>"
        )
