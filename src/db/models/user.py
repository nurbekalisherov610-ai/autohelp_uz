from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_master: Mapped[bool] = mapped_column(default=False, server_default="false")
    is_blocked: Mapped[bool] = mapped_column(default=False, server_default="false")

    # FIX: lazy="raise" — never silently load in async context
    orders: Mapped[list["Order"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Order", back_populates="client", lazy="raise"
    )
