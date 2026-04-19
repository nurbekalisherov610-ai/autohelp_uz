"""
AutoHelp.uz - Staff Model
Represents dispatchers and admins who manage the system.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, String, DateTime, Enum, JSON, func
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class StaffRole(str, enum.Enum):
    """Staff role types."""
    DISPATCHER = "dispatcher"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class Staff(Base):
    """Staff model - dispatchers and admins."""
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    role: Mapped[StaffRole] = mapped_column(
        Enum(StaffRole), default=StaffRole.DISPATCHER, nullable=False
    )
    permissions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Staff(id={self.id}, name={self.full_name}, role={self.role})>"
