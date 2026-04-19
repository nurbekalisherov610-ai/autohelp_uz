"""
AutoHelp.uz - Audit Log Model
System-wide audit trail for all important actions.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, String, DateTime, Text, JSON, func
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class AuditLog(Base):
    """System audit log for tracking all important operations."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Action type: order_created, master_assigned, etc."
    )
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Entity type: order, master, staff, etc."
    )
    entity_id: Mapped[int | None] = mapped_column(nullable=True)
    performed_by_telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    performed_by_role: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    details: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Additional context as JSON"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<AuditLog(action={self.action}, entity={self.entity_type}:{self.entity_id})>"
