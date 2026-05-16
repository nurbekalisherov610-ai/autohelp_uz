from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.enums import IssueType, OrderStatus
from src.db.models.order import Order, OrderStatusHistory
from src.db.models.user import User

ISSUE_LABEL_TO_TYPE: dict[str, IssueType] = {
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
    OrderStatus.ACCEPTED: {OrderStatus.ON_THE_WAY},
    OrderStatus.ON_THE_WAY: {OrderStatus.ARRIVED},
    OrderStatus.ARRIVED: {OrderStatus.IN_PROGRESS},
    OrderStatus.IN_PROGRESS: {OrderStatus.AWAITING_CONFIRM},
}

DISPATCHER_ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.AWAITING_CONFIRM: {OrderStatus.COMPLETED}
}

MASTER_ACTIVE_STATUSES = {
    OrderStatus.ASSIGNED,
    OrderStatus.ACCEPTED,
    OrderStatus.ON_THE_WAY,
    OrderStatus.ARRIVED,
    OrderStatus.IN_PROGRESS,
    OrderStatus.AWAITING_CONFIRM,
}


class OrderServiceError(Exception):
    pass


class OrderNotFoundError(OrderServiceError):
    pass


class InvalidOrderTransitionError(OrderServiceError):
    pass


class OrderPermissionDeniedError(OrderServiceError):
    pass


@dataclass(slots=True)
class DriverOrderPayload:
    client_telegram_id: int
    full_name: str | None
    language: str | None
    phone: str
    issue_label: str
    latitude: float
    longitude: float


class OrderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_driver_order(self, payload: DriverOrderPayload) -> Order:
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
        await self.session.flush()

        self.session.add(
            OrderStatusHistory(
                order_id=order.id,
                from_status=None,
                to_status=OrderStatus.NEW,
                actor_telegram_id=payload.client_telegram_id,
            )
        )

        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def get_order(self, order_id: int) -> Order:
        query: Select[tuple[Order]] = select(Order).where(Order.id == order_id)
        row = await self.session.execute(query)
        order = row.scalar_one_or_none()
        if order is None:
            raise OrderNotFoundError(f"Order #{order_id} not found")
        return order

    async def list_orders_by_status(self, statuses: list[OrderStatus], limit: int = 10) -> list[Order]:
        query: Select[tuple[Order]] = (
            select(Order)
            .where(Order.status.in_(statuses))
            .order_by(Order.created_at.asc())
            .limit(limit)
        )
        rows = await self.session.execute(query)
        return list(rows.scalars().all())

    async def list_master_active_orders(self, master_telegram_id: int, limit: int = 10) -> list[Order]:
        query: Select[tuple[Order]] = (
            select(Order)
            .where(Order.assigned_master_telegram_id == master_telegram_id)
            .where(Order.status.in_(MASTER_ACTIVE_STATUSES))
            .order_by(Order.updated_at.asc())
            .limit(limit)
        )
        rows = await self.session.execute(query)
        return list(rows.scalars().all())

    async def assign_order(self, order_id: int, dispatcher_telegram_id: int) -> Order:
        order = await self._get_order_for_update(order_id)

        if order.status not in (OrderStatus.NEW, OrderStatus.REJECTED):
            raise InvalidOrderTransitionError(
                f"Order #{order_id} is {order.status}, expected NEW or REJECTED"
            )

        await self._change_status(
            order,
            to_status=OrderStatus.ASSIGNED,
            actor_telegram_id=dispatcher_telegram_id,
            assigned_dispatcher_telegram_id=dispatcher_telegram_id,
        )
        return order

    async def assign_master(
        self,
        order_id: int,
        dispatcher_telegram_id: int,
        master_telegram_id: int,
    ) -> Order:
        order = await self._get_order_for_update(order_id)

        if order.status != OrderStatus.ASSIGNED:
            raise InvalidOrderTransitionError(
                f"Order #{order_id} is {order.status}, expected {OrderStatus.ASSIGNED}"
            )

        if order.assigned_dispatcher_telegram_id not in (None, dispatcher_telegram_id):
            raise OrderPermissionDeniedError(
                f"Order #{order_id} is managed by another dispatcher"
            )

        order.assigned_dispatcher_telegram_id = dispatcher_telegram_id
        order.assigned_master_telegram_id = master_telegram_id

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
        order = await self._get_order_for_update(order_id)

        if order.assigned_master_telegram_id != master_telegram_id:
            raise OrderPermissionDeniedError(
                f"Order #{order_id} is not assigned to master {master_telegram_id}"
            )

        allowed_next = MASTER_ALLOWED_TRANSITIONS.get(order.status, set())
        if to_status not in allowed_next:
            raise InvalidOrderTransitionError(
                f"Transition {order.status} -> {to_status} is not allowed for master"
            )

        if to_status == OrderStatus.AWAITING_CONFIRM:
            if video_file_id:
                order.video_file_id = video_file_id
            if final_amount is not None:
                order.final_amount = Decimal(str(final_amount))

        await self._change_status(order, to_status=to_status, actor_telegram_id=master_telegram_id)
        return order

    async def dispatcher_transition(
        self,
        order_id: int,
        dispatcher_telegram_id: int,
        to_status: OrderStatus,
        *,
        final_amount: float | None = None,
    ) -> Order:
        order = await self._get_order_for_update(order_id)

        if order.assigned_dispatcher_telegram_id != dispatcher_telegram_id:
            raise OrderPermissionDeniedError(
                f"Order #{order_id} is not assigned to dispatcher {dispatcher_telegram_id}"
            )

        allowed_next = DISPATCHER_ALLOWED_TRANSITIONS.get(order.status, set())
        if to_status not in allowed_next:
            raise InvalidOrderTransitionError(
                f"Transition {order.status} -> {to_status} is not allowed for dispatcher"
            )

        if to_status == OrderStatus.COMPLETED:
            if final_amount is not None:
                order.final_amount = Decimal(str(final_amount))
            elif order.final_amount is None:
                raise InvalidOrderTransitionError("final_amount is required for COMPLETED")
            order.completed_at = datetime.now(UTC)

        await self._change_status(order, to_status=to_status, actor_telegram_id=dispatcher_telegram_id)
        return order

    async def dispatcher_cancel_order(self, order_id: int) -> Order:
        """Cancel any non-completed order. Used for manual dispatcher override."""
        order = await self._get_order_for_update(order_id)

        if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
            raise InvalidOrderTransitionError(
                f"Order #{order_id} is already {order.status.name}, cannot cancel"
            )

        await self._change_status(
            order,
            to_status=OrderStatus.CANCELLED,
            actor_telegram_id=order.assigned_dispatcher_telegram_id or 0,
        )
        return order

    async def _change_status(
        self,
        order: Order,
        *,
        to_status: OrderStatus,
        actor_telegram_id: int,
        assigned_dispatcher_telegram_id: int | None = None,
    ) -> None:
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

    async def _get_order_for_update(self, order_id: int) -> Order:
        query: Select[tuple[Order]] = select(Order).where(Order.id == order_id).with_for_update()
        row = await self.session.execute(query)
        order = row.scalar_one_or_none()
        if order is None:
            raise OrderNotFoundError(f"Order #{order_id} not found")
        return order

    async def _get_or_create_user(
        self,
        *,
        telegram_id: int,
        full_name: str | None,
        language: str | None,
        phone: str,
    ) -> User:
        query: Select[tuple[User]] = select(User).where(User.telegram_id == telegram_id)
        row = await self.session.execute(query)
        user = row.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=telegram_id,
                full_name=full_name,
                language=language,
                phone=phone,
            )
            self.session.add(user)
            await self.session.flush()
            return user

        user.phone = phone
        if full_name:
            user.full_name = full_name
        if language:
            user.language = language
        await self.session.flush()
        return user
