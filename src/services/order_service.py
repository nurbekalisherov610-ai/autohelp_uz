"""
OrderService — all business logic for order lifecycle.

IMPORTANT: Since all ORM relationships use lazy='raise', this service
MUST explicitly load any relationship it needs via joinedload/selectinload
in the SELECT query. Never access .client or .status_history without loading them first.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.db.enums import IssueType, OrderStatus
from src.db.models.order import Order, OrderStatusHistory
from src.db.models.user import User

# ── Issue label → type mapping ────────────────────────────────────────────────

ISSUE_LABEL_TO_TYPE: dict[str, IssueType] = {
    "🛠 Zavod bo'lmayapti": IssueType.ENGINE_NOT_STARTING,
    "🛠 Не заводится": IssueType.ENGINE_NOT_STARTING,
    "🔋 Akkumulyator o'tirgan": IssueType.BATTERY_DOWN,
    "🔋 Сел аккумулятор": IssueType.BATTERY_DOWN,
    "🎈 Balon yorilgan": IssueType.FLAT_TIRE,
    "🎈 Пробито колесо": IssueType.FLAT_TIRE,
    "❓ Boshqa muammo": IssueType.OTHER,
    "❓ Другая проблема": IssueType.OTHER,
    # Without emojis (fallback)
    "Zavod bo'lmayapti": IssueType.ENGINE_NOT_STARTING,
    "Не заводится": IssueType.ENGINE_NOT_STARTING,
    "Akkumulyator o'tirgan": IssueType.BATTERY_DOWN,
    "Сел аккумулятор": IssueType.BATTERY_DOWN,
    "Balon yorilgan": IssueType.FLAT_TIRE,
    "Пробито колесо": IssueType.FLAT_TIRE,
    "Boshqa muammo": IssueType.OTHER,
    "Другая проблема": IssueType.OTHER,
}

MASTER_ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.ASSIGNED: {OrderStatus.ACCEPTED, OrderStatus.REJECTED},
    OrderStatus.ACCEPTED: {OrderStatus.ON_THE_WAY, OrderStatus.CANCELLED},
    OrderStatus.ON_THE_WAY: {OrderStatus.ARRIVED, OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.ARRIVED: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
}

DISPATCHER_ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.AWAITING_CONFIRM: {OrderStatus.COMPLETED},
    OrderStatus.IN_PROGRESS: {OrderStatus.COMPLETED},
}

MASTER_ACTIVE_STATUSES = {
    OrderStatus.ASSIGNED,
    OrderStatus.ACCEPTED,
    OrderStatus.ON_THE_WAY,
    OrderStatus.ARRIVED,
    OrderStatus.IN_PROGRESS,
    OrderStatus.AWAITING_CONFIRM, # keeping for backwards compatibility if any old orders have this
}


# ── Exceptions ─────────────────────────────────────────────────────────────────

class OrderServiceError(Exception):
    pass


class OrderNotFoundError(OrderServiceError):
    pass


class InvalidOrderTransitionError(OrderServiceError):
    pass


class OrderPermissionDeniedError(OrderServiceError):
    pass


# ── Payload ───────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class DriverOrderPayload:
    client_telegram_id: int
    full_name: str | None
    language: str | None
    phone: str
    issue_label: str
    latitude: float
    longitude: float


# ── Service ───────────────────────────────────────────────────────────────────

class OrderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_driver_order(self, payload: DriverOrderPayload) -> Order:
        """
        Create a new order for a client.
        Returns the saved Order with client_id set.
        Does NOT load any relationships — callers only need scalar fields.
        """
        user = await self._get_or_create_user(
            telegram_id=payload.client_telegram_id,
            full_name=payload.full_name,
            language=payload.language,
            phone=payload.phone,
        )

        issue_type = ISSUE_LABEL_TO_TYPE.get(payload.issue_label, IssueType.OTHER)

        order = Order(
            client_id=user.id,
            issue_type=issue_type,
            issue_label=payload.issue_label,
            phone=payload.phone,
            latitude=payload.latitude,
            longitude=payload.longitude,
            status=OrderStatus.NEW,
        )
        self.session.add(order)
        await self.session.flush()  # get order.id

        self.session.add(
            OrderStatusHistory(
                order_id=order.id,
                from_status=None,
                to_status=OrderStatus.NEW,
                actor_telegram_id=payload.client_telegram_id,
            )
        )

        await self.session.commit()
        # Refresh ONLY the Order scalar columns — do not load relationships
        await self.session.refresh(order)
        return order

    async def get_order(self, order_id: int) -> Order:
        """Fetch order by ID. Relationships are NOT loaded — access scalar columns only."""
        order = await self.session.scalar(
            select(Order).where(Order.id == order_id)
        )
        if order is None:
            raise OrderNotFoundError(f"Order #{order_id} not found")
        return order

    async def get_order_with_client(self, order_id: int) -> Order:
        """Fetch order with .client relationship eagerly loaded."""
        order = await self.session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(joinedload(Order.client))
        )
        if order is None:
            raise OrderNotFoundError(f"Order #{order_id} not found")
        return order

    async def list_orders_by_status(
        self, statuses: list[OrderStatus], limit: int = 10
    ) -> list[Order]:
        """List orders filtered by status. No relationships loaded."""
        rows = await self.session.scalars(
            select(Order)
            .where(Order.status.in_(statuses))
            .order_by(Order.created_at.asc())
            .limit(limit)
        )
        return list(rows.all())

    async def list_master_active_orders(
        self, master_telegram_id: int, limit: int = 10
    ) -> list[Order]:
        """List active orders assigned to a specific master."""
        rows = await self.session.scalars(
            select(Order)
            .where(Order.assigned_master_telegram_id == master_telegram_id)
            .where(Order.status.in_(MASTER_ACTIVE_STATUSES))
            .order_by(Order.updated_at.asc())
            .limit(limit)
        )
        return list(rows.all())

    async def assign_order(
        self, order_id: int, dispatcher_telegram_id: int
    ) -> Order:
        """Transition order NEW → ASSIGNED, record dispatcher."""
        order = await self.get_order(order_id)

        if order.status not in (OrderStatus.NEW, OrderStatus.REJECTED):
            raise InvalidOrderTransitionError(
                f"Order #{order_id} is {order.status}, expected NEW or REJECTED"
            )

        return await self._change_status(
            order,
            to_status=OrderStatus.ASSIGNED,
            actor_telegram_id=dispatcher_telegram_id,
            assigned_dispatcher_telegram_id=dispatcher_telegram_id,
        )

    async def assign_master(
        self,
        order_id: int,
        dispatcher_telegram_id: int,
        master_telegram_id: int,
    ) -> Order:
        """Record master assignment on an ASSIGNED order (no status change)."""
        order = await self.get_order(order_id)

        if order.status != OrderStatus.ASSIGNED:
            raise InvalidOrderTransitionError(
                f"Order #{order_id} is {order.status}, expected ASSIGNED"
            )

        order.assigned_master_telegram_id = master_telegram_id
        order.assigned_dispatcher_telegram_id = dispatcher_telegram_id

        self.session.add(
            OrderStatusHistory(
                order_id=order.id,
                from_status=OrderStatus.ASSIGNED,
                to_status=OrderStatus.ASSIGNED,
                actor_telegram_id=dispatcher_telegram_id,
            )
        )

        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def master_transition(
        self,
        order_id: int,
        master_telegram_id: int,
        to_status: OrderStatus,
        *,
        video_file_id: str | None = None,
        final_amount: float | None = None,
    ) -> Order:
        """Master updates their order status."""
        order = await self.get_order(order_id)

        if order.assigned_master_telegram_id != master_telegram_id:
            raise OrderPermissionDeniedError(
                f"Order #{order_id} is not assigned to master {master_telegram_id}"
            )

        allowed_next = MASTER_ALLOWED_TRANSITIONS.get(order.status, set())
        if to_status not in allowed_next:
            raise InvalidOrderTransitionError(
                f"Transition {order.status} → {to_status} is not allowed for master"
            )

        if to_status == OrderStatus.COMPLETED:
            if video_file_id:
                order.video_file_id = video_file_id
            if final_amount is not None:
                order.final_amount = Decimal(str(final_amount))
            order.completed_at = datetime.now(timezone.utc)

        return await self._change_status(
            order, to_status=to_status, actor_telegram_id=master_telegram_id
        )

    async def dispatcher_transition(
        self,
        order_id: int,
        dispatcher_telegram_id: int,
        to_status: OrderStatus,
        *,
        final_amount: float | None = None,
    ) -> Order:
        """
        Dispatcher/admin finalizes an order.
        NOTE: No identity check — any authorized dispatcher can complete any order.
        Permission is checked at handler level via is_dispatcher().
        """
        order = await self.get_order(order_id)

        allowed_next = DISPATCHER_ALLOWED_TRANSITIONS.get(order.status, set())
        if to_status not in allowed_next:
            raise InvalidOrderTransitionError(
                f"Cannot transition order #{order_id} from {order.status} to {to_status}. "
                f"Order must be in IN_PROGRESS or AWAITING_CONFIRM status."
            )

        if to_status == OrderStatus.COMPLETED:
            if final_amount is not None:
                order.final_amount = Decimal(str(final_amount))
            if order.final_amount is None:
                raise InvalidOrderTransitionError(
                    "Cannot complete: final_amount not set. Master must submit amount first."
                )
            order.completed_at = datetime.now(timezone.utc)

        return await self._change_status(
            order, to_status=to_status, actor_telegram_id=dispatcher_telegram_id
        )

    async def dispatcher_cancel_order(self, order_id: int) -> Order:
        """Cancel any non-terminal order."""
        order = await self.get_order(order_id)

        if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
            raise InvalidOrderTransitionError(
                f"Order #{order_id} is already {order.status.name}"
            )

        return await self._change_status(
            order,
            to_status=OrderStatus.CANCELLED,
            actor_telegram_id=order.assigned_dispatcher_telegram_id or 0,
        )
    async def client_cancel_order(self, order_id: int, client_telegram_id: int) -> Order:
        """Client cancels their own order."""
        order = await self.get_order(order_id)
        if order.client_id != (await self.session.scalar(select(User.id).where(User.telegram_id == client_telegram_id))):
            raise OrderPermissionDeniedError(f"Client {client_telegram_id} cannot cancel order #{order_id}")
        
        if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
            raise InvalidOrderTransitionError(f"Order #{order_id} is already {order.status.name}")
            
        return await self._change_status(
            order,
            to_status=OrderStatus.CANCELLED,
            actor_telegram_id=client_telegram_id,
        )

    async def master_drop_order(self, order_id: int, master_telegram_id: int) -> Order:
        """Master drops an order due to emergency, reverts to NEW."""
        order = await self.get_order(order_id)
        if order.assigned_master_telegram_id != master_telegram_id:
            raise OrderPermissionDeniedError(f"Master {master_telegram_id} cannot drop order #{order_id}")
            
        if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
            raise InvalidOrderTransitionError(f"Order #{order_id} is already {order.status.name}")
            
        # Revert back to NEW, clear the assigned master but keep dispatcher who assigned it (or clear both)
        order.assigned_master_telegram_id = None
        
        return await self._change_status(
            order,
            to_status=OrderStatus.NEW,
            actor_telegram_id=master_telegram_id,
        )

    async def save_feedback(
        self,
        order_id: int,
        *,
        rating: int | None = None,
        feedback_text: str | None = None,
        shortcomings: str | None = None,
    ) -> Order:
        """Save client feedback fields on a completed order."""
        order = await self.get_order(order_id)
        if rating is not None:
            order.rating = rating
        if feedback_text is not None:
            order.feedback_text = feedback_text
        if shortcomings is not None:
            order.shortcomings = shortcomings
        await self.session.commit()
        await self.session.refresh(order)
        return order

    # ── Internals ──────────────────────────────────────────────────────────────

    async def _change_status(
        self,
        order: Order,
        *,
        to_status: OrderStatus,
        actor_telegram_id: int,
        assigned_dispatcher_telegram_id: int | None = None,
    ) -> Order:
        old_status = order.status
        order.status = to_status
        if assigned_dispatcher_telegram_id is not None:
            order.assigned_dispatcher_telegram_id = assigned_dispatcher_telegram_id

        self.session.add(
            OrderStatusHistory(
                order_id=order.id,
                from_status=old_status,
                to_status=to_status,
                actor_telegram_id=actor_telegram_id,
            )
        )

        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def _get_or_create_user(
        self,
        *,
        telegram_id: int,
        full_name: str | None,
        language: str | None,
        phone: str,
    ) -> User:
        user = await self.session.scalar(
            select(User).where(User.telegram_id == telegram_id)
        )
        if user is None:
            user = User(
                telegram_id=telegram_id,
                full_name=full_name,
                language=language,
                phone=phone,
            )
            self.session.add(user)
            await self.session.flush()
        else:
            user.phone = phone
            if full_name:
                user.full_name = full_name
            if language:
                user.language = language
            await self.session.flush()
        return user
