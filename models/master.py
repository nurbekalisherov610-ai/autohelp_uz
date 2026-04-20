"""
AutoHelp.uz - Master Model
Represents masters/mechanics who perform roadside repairs.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, String, DateTime, Enum, Float, Integer, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class MasterStatus(str, enum.Enum):
    """Master availability status."""
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"


class Master(Base):
    """Master/Mechanic model - people who fix the vehicles."""
    __tablename__ = "masters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[MasterStatus] = mapped_column(
        Enum(MasterStatus), default=MasterStatus.OFFLINE, nullable=False
    )
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    completed_orders: Mapped[int] = mapped_column(Integer, default=0)
    rejected_orders: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    district_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    orders = relationship("Order", back_populates="master", lazy="noload")
    specializations = relationship(
        "MasterSpecialization",
        back_populates="master",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Master(id={self.id}, name={self.full_name}, status={self.status})>"
