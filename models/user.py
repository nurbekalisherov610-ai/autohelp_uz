"""
AutoHelp.uz - User Model
Represents clients/drivers who request roadside assistance.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, String, DateTime, Enum, func, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Language(str, enum.Enum):
    """Supported languages."""
    UZ = "uz"
    RU = "ru"


class User(Base):
    """Client/Driver model - people who request emergency help."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[Language] = mapped_column(
        Enum(Language), default=Language.UZ, nullable=False
    )
    is_blocked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships (lazy=noload — load explicitly when needed)
    orders = relationship("Order", back_populates="user", lazy="noload")
    reviews = relationship("Review", back_populates="user", lazy="noload")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, name={self.full_name}, tg={self.telegram_id})>"
