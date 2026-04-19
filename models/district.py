"""
AutoHelp.uz - District Model
Service area districts for geographic order routing.
"""
from datetime import datetime

from sqlalchemy import (
    Integer, String, DateTime, Text, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class District(Base):
    """Service area district for geographic routing."""
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name_uz: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    polygon: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="GeoJSON polygon for district boundaries"
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    orders = relationship("Order", back_populates="district", lazy="selectin")

    def __repr__(self) -> str:
        return f"<District(id={self.id}, name={self.name_uz})>"
