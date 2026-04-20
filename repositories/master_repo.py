"""
AutoHelp.uz - Master Repository
Database operations for masters and specialization-based assignment.
"""
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.master import Master, MasterStatus
from models.master_specialization import (
    MasterSpecialization,
    MasterSpecializationType,
    problem_specialization_priority,
)
from models.order import Order, OrderStatus, ProblemType
from models.review import Review


class MasterRepo:
    """Repository for master/mechanic database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> Master | None:
        """Get master by Telegram ID."""
        return await self.session.scalar(
            select(Master).where(Master.telegram_id == telegram_id)
        )

    async def get_by_id(self, master_id: int) -> Master | None:
        """Get master by internal ID."""
        return await self.session.scalar(
            select(Master).where(Master.id == master_id)
        )

    async def get_specializations(self, master_id: int) -> list[MasterSpecializationType]:
        """Get specialization tags for a specific master."""
        result = await self.session.scalars(
            select(MasterSpecialization.specialization)
            .where(MasterSpecialization.master_id == master_id)
            .order_by(MasterSpecialization.specialization)
        )
        specs = list(result.all())
        return specs or [MasterSpecializationType.UNIVERSAL]

    async def get_specializations_map(
        self,
        master_ids: list[int] | None = None,
    ) -> dict[int, list[MasterSpecializationType]]:
        """Get a mapping of master_id to specialization tags."""
        query = select(
            MasterSpecialization.master_id,
            MasterSpecialization.specialization,
        )
        if master_ids is not None:
            if not master_ids:
                return {}
            query = query.where(MasterSpecialization.master_id.in_(master_ids))

        result = await self.session.execute(query.order_by(MasterSpecialization.master_id))

        spec_map: dict[int, list[MasterSpecializationType]] = {}
        for master_id, specialization in result.all():
            spec_map.setdefault(master_id, []).append(specialization)

        return spec_map

    async def set_specializations(
        self,
        master_id: int,
        specializations: list[MasterSpecializationType] | None,
    ) -> None:
        """Replace specialization tags for a master."""
        normalized = list(dict.fromkeys(specializations or [MasterSpecializationType.UNIVERSAL]))

        await self.session.execute(
            delete(MasterSpecialization).where(MasterSpecialization.master_id == master_id)
        )

        for specialization in normalized:
            self.session.add(
                MasterSpecialization(
                    master_id=master_id,
                    specialization=specialization,
                )
            )

        await self.session.flush()

    async def _get_busy_master_ids(self) -> set[int]:
        """Get master IDs that currently have active orders."""
        result = await self.session.scalars(
            select(Order.master_id).where(
                Order.master_id.is_not(None),
                Order.status.in_(
                    [
                        OrderStatus.ASSIGNED,
                        OrderStatus.ACCEPTED,
                        OrderStatus.ON_THE_WAY,
                        OrderStatus.ARRIVED,
                        OrderStatus.IN_PROGRESS,
                        OrderStatus.AWAITING_CONFIRM,
                    ]
                ),
            )
        )
        return {int(master_id) for master_id in result.all() if master_id is not None}

    async def get_available_masters(self) -> list[Master]:
        """Get online masters that do not hold active orders."""
        result = await self.session.scalars(
            select(Master)
            .where(
                Master.status == MasterStatus.ONLINE,
                Master.is_active == True,
            )
            .order_by(Master.rating.desc(), Master.completed_orders.desc(), Master.full_name)
        )
        masters = list(result.all())
        if not masters:
            return []

        busy_ids = await self._get_busy_master_ids()
        return [m for m in masters if m.id not in busy_ids]

    async def get_available_masters_for_problem(
        self,
        problem_type: ProblemType | str | None,
    ) -> list[Master]:
        """
        Get available masters sorted by specialization relevance, then rating.
        Keeps fallback masters (e.g., universal) at the end.
        """
        masters = await self.get_available_masters()
        if not masters:
            return []

        problem_value = problem_type.value if isinstance(problem_type, ProblemType) else str(problem_type or "other")
        priority = problem_specialization_priority(problem_value)
        priority_index = {spec: idx for idx, spec in enumerate(priority)}

        spec_map = await self.get_specializations_map([m.id for m in masters])

        def master_rank(master: Master) -> tuple[int, float, int, str]:
            specs = spec_map.get(master.id) or [MasterSpecializationType.UNIVERSAL]
            best_match = min(priority_index.get(spec, len(priority) + 1) for spec in specs)
            return (best_match, -float(master.rating or 0.0), -int(master.completed_orders or 0), master.full_name)

        masters.sort(key=master_rank)
        return masters

    async def get_all_active(self) -> list[Master]:
        """Get all active masters (any status)."""
        result = await self.session.scalars(
            select(Master)
            .where(Master.is_active == True)
            .order_by(Master.full_name)
        )
        return list(result.all())

    async def set_status(
        self, telegram_id: int, status: MasterStatus
    ) -> None:
        """Update master's availability status."""
        await self.session.execute(
            update(Master)
            .where(Master.telegram_id == telegram_id)
            .values(status=status)
        )

    async def toggle_status(self, telegram_id: int) -> MasterStatus:
        """Toggle master between online and offline. Returns new status."""
        master = await self.get_by_telegram_id(telegram_id)
        if not master:
            return MasterStatus.OFFLINE

        new_status = (
            MasterStatus.OFFLINE
            if master.status == MasterStatus.ONLINE
            else MasterStatus.ONLINE
        )
        master.status = new_status
        await self.session.flush()
        return new_status

    async def increment_stats(
        self,
        master_id: int,
        completed: bool = False,
        rejected: bool = False,
    ) -> None:
        """Increment master's order statistics."""
        master = await self.get_by_id(master_id)
        if not master:
            return

        master.total_orders += 1
        if completed:
            master.completed_orders += 1
        if rejected:
            master.rejected_orders += 1

        await self.session.flush()

    async def update_rating(self, master_id: int) -> float:
        """Recalculate master's average rating from reviews."""
        avg = await self.session.scalar(
            select(func.avg(Review.rating)).where(
                Review.master_id == master_id
            )
        )
        new_rating = float(avg) if avg else 0.0

        await self.session.execute(
            update(Master)
            .where(Master.id == master_id)
            .values(rating=round(new_rating, 2))
        )
        return new_rating

    async def get_best_available(
        self,
        problem_type: ProblemType | str | None = None,
    ) -> Master | None:
        """Get the best currently available master for the problem type."""
        masters = await self.get_available_masters_for_problem(problem_type)
        return masters[0] if masters else None

    async def count_online(self) -> int:
        """Count currently online masters."""
        result = await self.session.scalar(
            select(func.count(Master.id)).where(
                Master.status == MasterStatus.ONLINE,
                Master.is_active == True,
            )
        )
        return result or 0

    async def get_master_stats(
        self, master_id: int, since: datetime | None = None,
    ) -> dict:
        """Get statistics for a specific master."""
        total_q = select(func.count(Order.id)).where(
            Order.master_id == master_id
        )
        if since:
            total_q = total_q.where(Order.created_at >= since)
        total = (await self.session.scalar(total_q)) or 0

        completed_q = select(func.count(Order.id)).where(
            Order.master_id == master_id,
            Order.status == OrderStatus.COMPLETED,
        )
        if since:
            completed_q = completed_q.where(Order.completed_at >= since)
        completed = (await self.session.scalar(completed_q)) or 0

        sum_q = select(
            func.coalesce(func.sum(Order.payment_amount), 0.0)
        ).where(
            Order.master_id == master_id,
            Order.status == OrderStatus.COMPLETED,
        )
        if since:
            sum_q = sum_q.where(Order.completed_at >= since)
        total_sum = float(await self.session.scalar(sum_q))

        master = await self.get_by_id(master_id)
        return {
            "total_orders": total,
            "completed_orders": completed,
            "total_sum": total_sum,
            "rating": master.rating if master else 0.0,
        }
