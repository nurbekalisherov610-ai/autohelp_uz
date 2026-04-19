"""
AutoHelp.uz - Order Repository
Database operations for orders, status history, payments, and reviews.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.order import Order, OrderStatus, ProblemType
from models.order_history import OrderStatusHistory
from models.payment import Payment
from models.review import Review


def generate_order_uid() -> str:
    """Generate a short, human-readable order UID."""
    return f"AH-{uuid.uuid4().hex[:8].upper()}"


class OrderRepo:
    """Repository for order database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Create ────────────────────────────────────────────────────

    async def create(
        self,
        user_id: int,
        problem_type: ProblemType,
        latitude: float,
        longitude: float,
        description: str | None = None,
        district_id: int | None = None,
    ) -> Order:
        """Create a new order."""
        order = Order(
            order_uid=generate_order_uid(),
            user_id=user_id,
            problem_type=problem_type,
            latitude=latitude,
            longitude=longitude,
            description=description,
            district_id=district_id,
            status=OrderStatus.NEW,
        )
        self.session.add(order)
        await self.session.flush()

        # Record initial status
        await self._record_status_change(
            order_id=order.id,
            old_status=None,
            new_status=OrderStatus.NEW,
            note="Order created by client",
        )
        return order

    # ── Read ──────────────────────────────────────────────────────

    async def get_by_uid(self, order_uid: str) -> Order | None:
        """Get order by its unique ID."""
        return await self.session.scalar(
            select(Order)
            .where(Order.order_uid == order_uid)
            .options(
                selectinload(Order.user),
                selectinload(Order.master),
                selectinload(Order.status_history),
            )
        )

    async def get_by_id(self, order_id: int) -> Order | None:
        """Get order by internal ID."""
        return await self.session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.user),
                selectinload(Order.master),
            )
        )

    async def get_active_by_user(self, user_id: int) -> list[Order]:
        """Get all active orders for a user."""
        result = await self.session.scalars(
            select(Order).where(
                Order.user_id == user_id,
                Order.status.notin_([
                    OrderStatus.COMPLETED,
                    OrderStatus.CANCELLED,
                ]),
            ).order_by(Order.created_at.desc())
        )
        return list(result.all())

    async def get_user_history(self, user_id: int, limit: int = 20) -> list[Order]:
        """Get order history for a user."""
        result = await self.session.scalars(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return list(result.all())

    async def get_active_by_master(self, master_id: int) -> Order | None:
        """Get the currently active order for a master (only one at a time)."""
        return await self.session.scalar(
            select(Order).where(
                Order.master_id == master_id,
                Order.status.in_([
                    OrderStatus.ACCEPTED,
                    OrderStatus.ON_THE_WAY,
                    OrderStatus.ARRIVED,
                    OrderStatus.IN_PROGRESS,
                    OrderStatus.AWAITING_CONFIRM,
                ]),
            )
        )

    async def get_new_orders(self) -> list[Order]:
        """Get all new (unassigned) orders."""
        result = await self.session.scalars(
            select(Order)
            .where(Order.status == OrderStatus.NEW)
            .options(selectinload(Order.user))
            .order_by(Order.created_at.asc())
        )
        return list(result.all())

    async def get_active_orders(self) -> list[Order]:
        """Get all active (non-terminal) orders."""
        result = await self.session.scalars(
            select(Order)
            .where(Order.status.notin_([
                OrderStatus.COMPLETED,
                OrderStatus.CANCELLED,
            ]))
            .options(
                selectinload(Order.user),
                selectinload(Order.master),
            )
            .order_by(Order.created_at.desc())
        )
        return list(result.all())

    # ── Update Status ─────────────────────────────────────────────

    async def update_status(
        self,
        order_uid: str,
        new_status: OrderStatus,
        changed_by_telegram_id: int | None = None,
        changed_by_role: str | None = None,
        note: str | None = None,
    ) -> Order | None:
        """Update order status with full audit trail."""
        order = await self.get_by_uid(order_uid)
        if not order:
            return None

        old_status = order.status
        order.status = new_status

        # Update relevant timestamps
        now = datetime.utcnow()
        timestamp_map = {
            OrderStatus.ASSIGNED: "assigned_at",
            OrderStatus.ACCEPTED: "accepted_at",
            OrderStatus.ON_THE_WAY: "on_the_way_at",
            OrderStatus.ARRIVED: "arrived_at",
            OrderStatus.IN_PROGRESS: "started_at",
            OrderStatus.COMPLETED: "completed_at",
            OrderStatus.CANCELLED: "cancelled_at",
        }
        if new_status in timestamp_map:
            setattr(order, timestamp_map[new_status], now)

        # Record status change
        await self._record_status_change(
            order_id=order.id,
            old_status=old_status,
            new_status=new_status,
            changed_by_telegram_id=changed_by_telegram_id,
            changed_by_role=changed_by_role,
            note=note,
        )

        await self.session.flush()
        return order

    async def assign_master(
        self,
        order_uid: str,
        master_id: int,
        dispatcher_id: int | None = None,
        dispatcher_telegram_id: int | None = None,
    ) -> Order | None:
        """Assign a master to an order."""
        order = await self.get_by_uid(order_uid)
        if not order:
            return None

        order.master_id = master_id
        order.dispatcher_id = dispatcher_id
        order.status = OrderStatus.ASSIGNED
        order.assigned_at = datetime.utcnow()

        await self._record_status_change(
            order_id=order.id,
            old_status=OrderStatus.NEW,
            new_status=OrderStatus.ASSIGNED,
            changed_by_telegram_id=dispatcher_telegram_id,
            changed_by_role="dispatcher",
            note=f"Master ID {master_id} assigned",
        )

        await self.session.flush()
        return order

    async def set_dispatcher_video(
        self, order_uid: str, file_id: str
    ) -> None:
        """Store dispatcher's confirmation video file_id."""
        await self.session.execute(
            update(Order)
            .where(Order.order_uid == order_uid)
            .values(dispatcher_video_file_id=file_id)
        )

    async def set_master_video(
        self, order_uid: str, file_id: str
    ) -> None:
        """Store master's completion video file_id."""
        await self.session.execute(
            update(Order)
            .where(Order.order_uid == order_uid)
            .values(master_video_file_id=file_id)
        )

    async def set_payment_amount(
        self, order_uid: str, amount: float
    ) -> None:
        """Set payment amount on the order."""
        await self.session.execute(
            update(Order)
            .where(Order.order_uid == order_uid)
            .values(payment_amount=amount)
        )

    # ── Payment ───────────────────────────────────────────────────

    async def create_payment(
        self,
        order_id: int,
        amount: float,
        video_file_id: str | None = None,
        note: str | None = None,
    ) -> Payment:
        """Create a payment record for an order."""
        payment = Payment(
            order_id=order_id,
            amount=amount,
            video_file_id=video_file_id,
            note=note,
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    # ── Review ────────────────────────────────────────────────────

    async def create_review(
        self,
        order_id: int,
        user_id: int,
        master_id: int,
        rating: int,
        comment: str | None = None,
    ) -> Review:
        """Create a review for a completed order."""
        review = Review(
            order_id=order_id,
            user_id=user_id,
            master_id=master_id,
            rating=rating,
            comment=comment,
        )
        self.session.add(review)
        await self.session.flush()
        return review

    # ── SLA Queries ───────────────────────────────────────────────

    async def get_sla_violations(
        self,
        status: OrderStatus,
        timeout_minutes: int,
    ) -> list[Order]:
        """Get orders that have exceeded SLA timeout for a given status."""
        cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)

        # Determine which timestamp to check
        timestamp_col = {
            OrderStatus.ASSIGNED: Order.assigned_at,
            OrderStatus.ON_THE_WAY: Order.on_the_way_at,
            OrderStatus.AWAITING_CONFIRM: Order.completed_at,
        }.get(status, Order.updated_at)

        result = await self.session.scalars(
            select(Order)
            .where(
                Order.status == status,
                timestamp_col < cutoff,
            )
            .options(selectinload(Order.user))
        )
        return list(result.all())

    # ── Statistics ────────────────────────────────────────────────

    async def count_by_status(
        self,
        status: OrderStatus | None = None,
        since: datetime | None = None,
    ) -> int:
        """Count orders, optionally filtered by status and time."""
        query = select(func.count(Order.id))
        if status:
            query = query.where(Order.status == status)
        if since:
            query = query.where(Order.created_at >= since)
        return (await self.session.scalar(query)) or 0

    async def sum_payments(self, since: datetime | None = None) -> float:
        """Sum all payment amounts, optionally since a date."""
        query = select(func.coalesce(func.sum(Order.payment_amount), 0.0)).where(
            Order.status == OrderStatus.COMPLETED
        )
        if since:
            query = query.where(Order.completed_at >= since)
        return float(await self.session.scalar(query))

    async def avg_rating(self, since: datetime | None = None) -> float:
        """Average review rating."""
        query = select(func.coalesce(func.avg(Review.rating), 0.0))
        if since:
            query = query.where(Review.created_at >= since)
        return float(await self.session.scalar(query))

    # ── Internal ──────────────────────────────────────────────────

    async def _record_status_change(
        self,
        order_id: int,
        old_status: OrderStatus | None,
        new_status: OrderStatus,
        changed_by_telegram_id: int | None = None,
        changed_by_role: str | None = None,
        note: str | None = None,
    ) -> None:
        """Record a status change in the history table."""
        history = OrderStatusHistory(
            order_id=order_id,
            old_status=old_status,
            new_status=new_status,
            changed_by_telegram_id=changed_by_telegram_id,
            changed_by_role=changed_by_role,
            note=note,
        )
        self.session.add(history)
