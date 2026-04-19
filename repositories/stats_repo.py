"""
AutoHelp.uz - Statistics Repository
Aggregated statistics queries for admin dashboard and reports.
"""
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.order import Order, OrderStatus
from models.review import Review
from models.master import Master, MasterStatus
from models.user import User


class StatsRepo:
    """Repository for aggregated statistics queries."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_dashboard_stats(self) -> dict:
        """Get comprehensive dashboard statistics."""
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

        return {
            "today_orders": await self._count_orders(since=today_start),
            "weekly_orders": await self._count_orders(since=week_start),
            "monthly_orders": await self._count_orders(since=month_start),
            "today_completed": await self._count_orders(
                since=today_start, status=OrderStatus.COMPLETED
            ),
            "today_sum": await self._sum_payments(since=today_start),
            "monthly_sum": await self._sum_payments(since=month_start),
            "avg_rating": await self._avg_rating(),
            "online_masters": await self._count_online_masters(),
            "total_users": await self._count_users(),
            "active_orders": await self._count_orders(
                exclude_statuses=[OrderStatus.COMPLETED, OrderStatus.CANCELLED]
            ),
            "cancelled_rate": await self._cancellation_rate(since=month_start),
        }

    async def get_master_leaderboard(self, limit: int = 10) -> list[dict]:
        """Get top masters by rating and completed orders."""
        result = await self.session.execute(
            select(
                Master.id,
                Master.full_name,
                Master.rating,
                Master.completed_orders,
                Master.status,
            )
            .where(Master.is_active == True)
            .order_by(Master.rating.desc())
            .limit(limit)
        )
        return [
            {
                "id": row.id,
                "name": row.full_name,
                "rating": row.rating,
                "completed": row.completed_orders,
                "status": row.status.value,
            }
            for row in result.all()
        ]

    async def get_district_stats(self) -> list[dict]:
        """Get order statistics by district."""
        from models.district import District

        result = await self.session.execute(
            select(
                District.name_uz,
                func.count(Order.id).label("total_orders"),
                func.count(
                    func.nullif(Order.status != OrderStatus.COMPLETED, True)
                ).label("completed"),
                func.coalesce(func.sum(Order.payment_amount), 0).label("total_sum"),
            )
            .outerjoin(Order, Order.district_id == District.id)
            .group_by(District.id, District.name_uz)
            .order_by(func.count(Order.id).desc())
        )
        return [
            {
                "district": row.name_uz,
                "total_orders": row.total_orders,
                "completed": row.completed,
                "total_sum": float(row.total_sum),
            }
            for row in result.all()
        ]

    # ── Private helpers ───────────────────────────────────────────

    async def _count_orders(
        self,
        since: datetime | None = None,
        status: OrderStatus | None = None,
        exclude_statuses: list[OrderStatus] | None = None,
    ) -> int:
        query = select(func.count(Order.id))
        if since:
            query = query.where(Order.created_at >= since)
        if status:
            query = query.where(Order.status == status)
        if exclude_statuses:
            query = query.where(Order.status.notin_(exclude_statuses))
        return (await self.session.scalar(query)) or 0

    async def _sum_payments(self, since: datetime | None = None) -> float:
        query = select(func.coalesce(func.sum(Order.payment_amount), 0.0)).where(
            Order.status == OrderStatus.COMPLETED
        )
        if since:
            query = query.where(Order.completed_at >= since)
        return float(await self.session.scalar(query))

    async def _avg_rating(self) -> float:
        result = await self.session.scalar(
            select(func.coalesce(func.avg(Review.rating), 0.0))
        )
        return round(float(result), 2)

    async def _count_online_masters(self) -> int:
        result = await self.session.scalar(
            select(func.count(Master.id)).where(
                Master.status == MasterStatus.ONLINE,
                Master.is_active == True,
            )
        )
        return result or 0

    async def _count_users(self) -> int:
        result = await self.session.scalar(select(func.count(User.id)))
        return result or 0

    async def _cancellation_rate(self, since: datetime | None = None) -> float:
        total = await self._count_orders(since=since)
        if total == 0:
            return 0.0
        cancelled = await self._count_orders(since=since, status=OrderStatus.CANCELLED)
        return round((cancelled / total) * 100, 1)
