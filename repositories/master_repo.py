"""
AutoHelp.uz - Master Repository
Database operations for the masters table.
"""
from datetime import datetime

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.master import Master, MasterStatus
from models.order import Order, OrderStatus
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

    async def get_available_masters(self) -> list[Master]:
        """Get all online masters."""
        result = await self.session.scalars(
            select(Master).where(
                Master.status == MasterStatus.ONLINE,
                Master.is_active == True,
            ).order_by(Master.rating.desc())
        )
        return list(result.all())

    async def get_all_active(self) -> list[Master]:
        """Get all active masters (any status)."""
        result = await self.session.scalars(
            select(Master).where(Master.is_active == True)
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

    async def get_best_available(self) -> Master | None:
        """
        Get the best available master based on:
        1. Online status
        2. Highest rating
        3. Least active orders
        """
        # All online masters
        masters = await self.get_available_masters()
        if not masters:
            return None

        # Filter out masters with active orders
        available = []
        for m in masters:
            active_order = await self.session.scalar(
                select(Order).where(
                    Order.master_id == m.id,
                    Order.status.in_([
                        OrderStatus.ACCEPTED,
                        OrderStatus.ON_THE_WAY,
                        OrderStatus.ARRIVED,
                        OrderStatus.IN_PROGRESS,
                    ]),
                )
            )
            if not active_order:
                available.append(m)

        if not available:
            return None

        # Sort by rating (descending)
        available.sort(key=lambda m: m.rating, reverse=True)
        return available[0]

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
        # Total orders
        total_q = select(func.count(Order.id)).where(
            Order.master_id == master_id
        )
        if since:
            total_q = total_q.where(Order.created_at >= since)
        total = (await self.session.scalar(total_q)) or 0

        # Completed orders (fresh query, not chained)
        completed_q = select(func.count(Order.id)).where(
            Order.master_id == master_id,
            Order.status == OrderStatus.COMPLETED,
        )
        if since:
            completed_q = completed_q.where(Order.completed_at >= since)
        completed = (await self.session.scalar(completed_q)) or 0

        # Revenue
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
