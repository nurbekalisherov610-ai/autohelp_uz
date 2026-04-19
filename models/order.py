"""
AutoHelp.uz - Order Model
The core model representing a roadside assistance request.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, String, DateTime, Enum, Float, Integer,
    Text, ForeignKey, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class OrderStatus(str, enum.Enum):
    """Order lifecycle statuses."""
    NEW = "new"
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    ON_THE_WAY = "on_the_way"
    ARRIVED = "arrived"
    IN_PROGRESS = "in_progress"
    AWAITING_CONFIRM = "awaiting_confirm"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ProblemType(str, enum.Enum):
    """Types of vehicle problems."""
    ENGINE_NO_START = "engine_no_start"       # 🔋 Zavod bo'lmayapti
    BATTERY_DEAD = "battery_dead"             # 🔌 Akkumulyator o'tirgan
    TIRE_BURST = "tire_burst"                 # 🛞 Balon yorilgan
    ENGINE_PROBLEM = "engine_problem"         # 🔧 Dvigatel muammosi
    BRAKE_PROBLEM = "brake_problem"           # 🛑 Tormoz muammosi
    ELECTRICAL = "electrical"                 # ⚡ Elektr muammosi
    OTHER = "other"                           # ❓ Boshqa muammo


# Human-readable labels
PROBLEM_LABELS = {
    ProblemType.ENGINE_NO_START: {"uz": "🔋 Zavod bo'lmayapti", "ru": "🔋 Не заводится"},
    ProblemType.BATTERY_DEAD: {"uz": "🔌 Akkumulyator o'tirgan", "ru": "🔌 Сел аккумулятор"},
    ProblemType.TIRE_BURST: {"uz": "🛞 Balon yorilgan", "ru": "🛞 Лопнуло колесо"},
    ProblemType.ENGINE_PROBLEM: {"uz": "🔧 Dvigatel muammosi", "ru": "🔧 Проблема с двигателем"},
    ProblemType.BRAKE_PROBLEM: {"uz": "🛑 Tormoz muammosi", "ru": "🛑 Проблема с тормозами"},
    ProblemType.ELECTRICAL: {"uz": "⚡ Elektr muammosi", "ru": "⚡ Электрическая проблема"},
    ProblemType.OTHER: {"uz": "❓ Boshqa muammo", "ru": "❓ Другая проблема"},
}


class Order(Base):
    """
    Order model - represents a single roadside assistance request.
    Tracks the full lifecycle from creation to completion.
    """
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_uid: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )

    # ── Client ────────────────────────────────────────────────────
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # ── Master (assigned later) ───────────────────────────────────
    master_id: Mapped[int | None] = mapped_column(
        ForeignKey("masters.id"), nullable=True, index=True
    )

    # ── Dispatcher who handled this order ─────────────────────────
    dispatcher_id: Mapped[int | None] = mapped_column(
        ForeignKey("staff.id"), nullable=True
    )

    # ── Problem Details ───────────────────────────────────────────
    problem_type: Mapped[ProblemType] = mapped_column(
        Enum(ProblemType), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Location ──────────────────────────────────────────────────
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    district_id: Mapped[int | None] = mapped_column(
        ForeignKey("districts.id"), nullable=True
    )

    # ── Status ────────────────────────────────────────────────────
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.NEW, nullable=False, index=True
    )

    # ── Video Confirmations ───────────────────────────────────────
    dispatcher_video_file_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    master_video_file_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # ── Payment ───────────────────────────────────────────────────
    payment_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    on_the_way_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    arrived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relationships ─────────────────────────────────────────────
    user = relationship("User", back_populates="orders")
    master = relationship("Master", back_populates="orders")
    district = relationship("District", back_populates="orders")
    status_history = relationship(
        "OrderStatusHistory", back_populates="order",
        lazy="selectin", order_by="OrderStatusHistory.created_at"
    )
    payment = relationship(
        "Payment", back_populates="order", uselist=False, lazy="selectin"
    )
    review = relationship(
        "Review", back_populates="order", uselist=False, lazy="selectin"
    )

    @property
    def google_maps_url(self) -> str:
        """Generate Google Maps link for the order location."""
        return f"https://www.google.com/maps?q={self.latitude},{self.longitude}"

    def __repr__(self) -> str:
        return f"<Order(uid={self.order_uid}, status={self.status}, problem={self.problem_type})>"
