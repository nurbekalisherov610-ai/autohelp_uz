"""
AutoHelp.uz - Order Service
Business logic for order lifecycle management.
"""
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from models.order import OrderStatus, ProblemType
from models.audit import AuditLog
from repositories.order_repo import OrderRepo
from repositories.master_repo import MasterRepo


class OrderService:
    """Business logic for order management."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.order_repo = OrderRepo(session)
        self.master_repo = MasterRepo(session)

    async def create_order(
        self,
        user_id: int,
        problem_type: ProblemType,
        latitude: float,
        longitude: float,
        description: str | None = None,
    ):
        """Create a new order and log the action."""
        order = await self.order_repo.create(
            user_id=user_id,
            problem_type=problem_type,
            latitude=latitude,
            longitude=longitude,
            description=description,
        )

        # Audit log
        self.session.add(AuditLog(
            action="order_created",
            entity_type="order",
            entity_id=order.id,
            details={
                "order_uid": order.order_uid,
                "problem_type": problem_type.value,
            },
        ))

        logger.info(f"Order {order.order_uid} created by user {user_id}")
        return order

    async def assign_master(
        self,
        order_uid: str,
        master_id: int,
        dispatcher_id: int | None = None,
        dispatcher_telegram_id: int | None = None,
    ):
        """Assign or reassign a master to an active order."""
        # Check if master is available
        master = await self.master_repo.get_by_id(master_id)
        if not master:
            raise ValueError("Master not found")

        order_before = await self.order_repo.get_by_uid(order_uid)
        if not order_before:
            raise ValueError(f"Order {order_uid} not found")

        allowed_reassign_statuses = {
            OrderStatus.NEW,
            OrderStatus.ASSIGNED,
            OrderStatus.ACCEPTED,
            OrderStatus.ON_THE_WAY,
            OrderStatus.ARRIVED,
            OrderStatus.REJECTED,
        }
        if order_before.status not in allowed_reassign_statuses:
            raise ValueError(
                f"Order status {order_before.status.value} cannot be reassigned now"
            )

        active_order = await self.order_repo.get_active_by_master(master_id)
        if active_order and active_order.order_uid != order_uid:
            raise ValueError("Master already has an active order")

        if (
            order_before.master_id == master_id
            and order_before.status == OrderStatus.ASSIGNED
        ):
            raise ValueError("This master is already assigned to the order")

        order = await self.order_repo.assign_master(
            order_uid=order_uid,
            master_id=master_id,
            dispatcher_id=dispatcher_id,
            dispatcher_telegram_id=dispatcher_telegram_id,
        )
        if not order:
            raise ValueError(f"Order {order_uid} not found")

        action = (
            "master_reassigned"
            if order_before.master_id and order_before.master_id != master_id
            else "master_assigned"
        )
        # Audit log
        self.session.add(AuditLog(
            action=action,
            entity_type="order",
            entity_id=order.id,
            performed_by_telegram_id=dispatcher_telegram_id,
            performed_by_role="dispatcher",
            details={
                "order_uid": order_uid,
                "previous_master_id": order_before.master_id,
                "master_id": master_id,
                "master_name": master.full_name,
                "from_status": order_before.status.value,
            },
        ))

        logger.info(
            f"Order {order_uid} assigned to master {master.full_name} "
            f"by dispatcher {dispatcher_telegram_id}"
        )
        return order

    async def update_order_status(
        self,
        order_uid: str,
        new_status: OrderStatus,
        changed_by_telegram_id: int | None = None,
        changed_by_role: str | None = None,
    ):
        """Update order status with validation."""
        order = await self.order_repo.get_by_uid(order_uid)
        if not order:
            raise ValueError(f"Order {order_uid} not found")
        old_status = order.status

        # Validate status transition
        valid_transitions = {
            OrderStatus.NEW: [OrderStatus.ASSIGNED, OrderStatus.CANCELLED],
            OrderStatus.ASSIGNED: [
                OrderStatus.ACCEPTED, OrderStatus.REJECTED, OrderStatus.CANCELLED
            ],
            OrderStatus.ACCEPTED: [OrderStatus.ON_THE_WAY, OrderStatus.CANCELLED],
            OrderStatus.ON_THE_WAY: [OrderStatus.ARRIVED, OrderStatus.CANCELLED],
            OrderStatus.ARRIVED: [OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED],
            OrderStatus.IN_PROGRESS: [OrderStatus.COMPLETED, OrderStatus.AWAITING_CONFIRM, OrderStatus.CANCELLED],
            OrderStatus.AWAITING_CONFIRM: [OrderStatus.COMPLETED, OrderStatus.CANCELLED],
            OrderStatus.REJECTED: [OrderStatus.ASSIGNED, OrderStatus.CANCELLED],
        }

        allowed = valid_transitions.get(order.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Invalid status transition: {order.status} -> {new_status}"
            )

        updated = await self.order_repo.update_status(
            order_uid=order_uid,
            new_status=new_status,
            changed_by_telegram_id=changed_by_telegram_id,
            changed_by_role=changed_by_role,
        )

        # If master completes, update stats
        if new_status == OrderStatus.COMPLETED and order.master_id:
            await self.master_repo.increment_stats(order.master_id, completed=True)

        if new_status == OrderStatus.REJECTED and order.master_id:
            await self.master_repo.increment_stats(order.master_id, rejected=True)

        logger.info(
            f"Order {order_uid} status: {old_status} -> {new_status} "
            f"by {changed_by_role} ({changed_by_telegram_id})"
        )
        return updated

    async def complete_order(
        self,
        order_uid: str,
        amount: float,
        master_telegram_id: int,
        video_file_id: str | None = None,
    ):
        """Complete an order with payment and video confirmation."""
        order = await self.order_repo.get_by_uid(order_uid)
        if not order:
            raise ValueError(f"Order {order_uid} not found")
        if order.status != OrderStatus.IN_PROGRESS:
            raise ValueError("Order must be IN_PROGRESS before completion flow")
        if order.payment:
            raise ValueError("Payment already exists for this order")

        # Set payment amount
        await self.order_repo.set_payment_amount(order_uid, amount)

        # Store master video
        if video_file_id:
            await self.order_repo.set_master_video(order_uid, video_file_id)

        # Create payment record
        await self.order_repo.create_payment(
            order_id=order.id,
            amount=amount,
            video_file_id=video_file_id,
        )

        # Auto-complete: no dispatcher confirmation needed
        await self.order_repo.update_status(
            order_uid=order_uid,
            new_status=OrderStatus.COMPLETED,
            changed_by_telegram_id=master_telegram_id,
            changed_by_role="master",
            note=f"Amount: {amount} so'm",
        )

        # Update master stats
        if order.master_id:
            await self.master_repo.increment_stats(order.master_id, completed=True)

        logger.info(f"Order {order_uid} completed, amount: {amount}")
        return order

    async def cancel_order(
        self,
        order_uid: str,
        cancelled_by_telegram_id: int,
        cancelled_by_role: str = "client",
    ):
        """Cancel an order."""
        order = await self.order_repo.update_status(
            order_uid=order_uid,
            new_status=OrderStatus.CANCELLED,
            changed_by_telegram_id=cancelled_by_telegram_id,
            changed_by_role=cancelled_by_role,
            note="Cancelled",
        )

        self.session.add(AuditLog(
            action="order_cancelled",
            entity_type="order",
            entity_id=order.id if order else None,
            performed_by_telegram_id=cancelled_by_telegram_id,
            performed_by_role=cancelled_by_role,
        ))

        logger.info(f"Order {order_uid} cancelled by {cancelled_by_role}")
        return order

    async def add_review(
        self,
        order_uid: str,
        rating: int,
        comment: str | None = None,
    ):
        """Add a client review for a completed order."""
        order = await self.order_repo.get_by_uid(order_uid)
        if not order:
            raise ValueError(f"Order {order_uid} not found")

        if order.status != OrderStatus.COMPLETED:
            raise ValueError("Can only review completed orders")

        review = await self.order_repo.create_review(
            order_id=order.id,
            user_id=order.user_id,
            master_id=order.master_id,
            rating=rating,
            comment=comment,
        )

        # Update master's average rating
        if order.master_id:
            await self.master_repo.update_rating(order.master_id)

        logger.info(f"Review added for order {order_uid}: {rating} stars")
        return review

