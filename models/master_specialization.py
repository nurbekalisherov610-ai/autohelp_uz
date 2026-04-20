"""
AutoHelp.uz - Master Specialization Model
Stores per-master specialization tags for skill-based assignment.
"""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class MasterSpecializationType(str, enum.Enum):
    """Supported master specialization tags."""
    UNIVERSAL = "universal"
    BATTERY = "battery"
    TIRE = "tire"
    ENGINE = "engine"
    BRAKE = "brake"
    ELECTRICAL = "electrical"


SPECIALIZATION_LABELS = {
    MasterSpecializationType.UNIVERSAL: {"uz": "Universal", "ru": "Universal"},
    MasterSpecializationType.BATTERY: {"uz": "Akkumulyator", "ru": "Accumulator"},
    MasterSpecializationType.TIRE: {"uz": "Balon", "ru": "Tire"},
    MasterSpecializationType.ENGINE: {"uz": "Dvigatel", "ru": "Engine"},
    MasterSpecializationType.BRAKE: {"uz": "Tormoz", "ru": "Brake"},
    MasterSpecializationType.ELECTRICAL: {"uz": "Elektr", "ru": "Electrical"},
}


SPECIALIZATION_SHORT = {
    MasterSpecializationType.UNIVERSAL: "ALL",
    MasterSpecializationType.BATTERY: "AKB",
    MasterSpecializationType.TIRE: "TIRE",
    MasterSpecializationType.ENGINE: "ENG",
    MasterSpecializationType.BRAKE: "BRK",
    MasterSpecializationType.ELECTRICAL: "ELEC",
}


_ALIASES = {
    "universal": MasterSpecializationType.UNIVERSAL,
    "all": MasterSpecializationType.UNIVERSAL,
    "any": MasterSpecializationType.UNIVERSAL,
    "general": MasterSpecializationType.UNIVERSAL,
    "boshqa": MasterSpecializationType.UNIVERSAL,
    "battery": MasterSpecializationType.BATTERY,
    "accumulator": MasterSpecializationType.BATTERY,
    "akkumulyator": MasterSpecializationType.BATTERY,
    "akku": MasterSpecializationType.BATTERY,
    "akb": MasterSpecializationType.BATTERY,
    "tire": MasterSpecializationType.TIRE,
    "tyre": MasterSpecializationType.TIRE,
    "balon": MasterSpecializationType.TIRE,
    "wheel": MasterSpecializationType.TIRE,
    "engine": MasterSpecializationType.ENGINE,
    "motor": MasterSpecializationType.ENGINE,
    "dvigatel": MasterSpecializationType.ENGINE,
    "brake": MasterSpecializationType.BRAKE,
    "tormoz": MasterSpecializationType.BRAKE,
    "electrical": MasterSpecializationType.ELECTRICAL,
    "electric": MasterSpecializationType.ELECTRICAL,
    "elektr": MasterSpecializationType.ELECTRICAL,
}


def normalize_specialization(value: str | MasterSpecializationType) -> MasterSpecializationType | None:
    """Normalize CLI/input value to MasterSpecializationType."""
    if isinstance(value, MasterSpecializationType):
        return value
    if value is None:
        return None

    raw = value.strip().lower()
    if not raw:
        return None
    if raw in _ALIASES:
        return _ALIASES[raw]

    try:
        return MasterSpecializationType(raw)
    except ValueError:
        return None


def parse_specializations_csv(value: str | None) -> list[MasterSpecializationType]:
    """Parse comma-separated specialization values."""
    if not value:
        return [MasterSpecializationType.UNIVERSAL]

    out: list[MasterSpecializationType] = []
    for token in value.split(","):
        spec = normalize_specialization(token)
        if spec and spec not in out:
            out.append(spec)

    return out or [MasterSpecializationType.UNIVERSAL]


def specialization_text(specs: list[MasterSpecializationType], lang: str = "uz") -> str:
    """Human-readable specialization list."""
    if not specs:
        return SPECIALIZATION_LABELS[MasterSpecializationType.UNIVERSAL][lang]
    return ", ".join(SPECIALIZATION_LABELS[s][lang] for s in specs)


def specialization_short_text(specs: list[MasterSpecializationType]) -> str:
    """Short tag list used in compact UIs and CLI output."""
    if not specs:
        return SPECIALIZATION_SHORT[MasterSpecializationType.UNIVERSAL]
    return "/".join(SPECIALIZATION_SHORT[s] for s in specs)


def problem_specialization_priority(problem_type_value: str) -> list[MasterSpecializationType]:
    """
    Return specialization priority for a given order problem type value.
    Falls back to universal if unknown.
    """
    mapping = {
        "engine_no_start": [
            MasterSpecializationType.BATTERY,
            MasterSpecializationType.ENGINE,
            MasterSpecializationType.ELECTRICAL,
            MasterSpecializationType.UNIVERSAL,
        ],
        "battery_dead": [
            MasterSpecializationType.BATTERY,
            MasterSpecializationType.ELECTRICAL,
            MasterSpecializationType.UNIVERSAL,
        ],
        "tire_burst": [
            MasterSpecializationType.TIRE,
            MasterSpecializationType.UNIVERSAL,
        ],
        "engine_problem": [
            MasterSpecializationType.ENGINE,
            MasterSpecializationType.UNIVERSAL,
        ],
        "brake_problem": [
            MasterSpecializationType.BRAKE,
            MasterSpecializationType.UNIVERSAL,
        ],
        "electrical": [
            MasterSpecializationType.ELECTRICAL,
            MasterSpecializationType.BATTERY,
            MasterSpecializationType.UNIVERSAL,
        ],
        "other": [
            MasterSpecializationType.UNIVERSAL,
        ],
    }
    return mapping.get(problem_type_value, [MasterSpecializationType.UNIVERSAL])


class MasterSpecialization(Base):
    """Master specialization mapping table."""
    __tablename__ = "master_specializations"
    __table_args__ = (
        UniqueConstraint("master_id", "specialization", name="uq_master_specialization"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    master_id: Mapped[int] = mapped_column(
        ForeignKey("masters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    specialization: Mapped[MasterSpecializationType] = mapped_column(
        Enum(MasterSpecializationType), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    master = relationship("Master", back_populates="specializations", lazy="joined")

    def __repr__(self) -> str:
        return f"<MasterSpecialization(master={self.master_id}, spec={self.specialization})>"
