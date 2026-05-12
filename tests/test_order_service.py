from decimal import Decimal

import pytest
from sqlalchemy import select

from src.db.enums import OrderStatus
from src.db.models.order import OrderStatusHistory
from src.services.order_service import (
    DriverOrderPayload,
    InvalidOrderTransitionError,
    OrderPermissionDeniedError,
    OrderService,
)


@pytest.mark.asyncio
async def test_create_driver_order_creates_user_order_and_history(session):
    service = OrderService(session)

    order = await service.create_driver_order(
        DriverOrderPayload(
            client_telegram_id=111,
            full_name="Ali Valiyev",
            language="uz",
            phone="+998901112233",
            issue_label="Akkumulyator o'tirgan",
            latitude=41.311081,
            longitude=69.240562,
        )
    )

    assert order.id is not None
    assert order.status == OrderStatus.NEW

    histories = await session.execute(
        select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
    )
    history_rows = list(histories.scalars().all())
    assert len(history_rows) == 1
    assert history_rows[0].to_status == OrderStatus.NEW


@pytest.mark.asyncio
async def test_full_lifecycle_happy_path(session):
    service = OrderService(session)

    order = await service.create_driver_order(
        DriverOrderPayload(
            client_telegram_id=222,
            full_name="Driver User",
            language="uz",
            phone="+998900000001",
            issue_label="Zavod bo'lmayapti",
            latitude=41.3,
            longitude=69.2,
        )
    )

    dispatcher_id = 5001
    master_id = 7001

    order = await service.assign_order(order.id, dispatcher_id)
    assert order.status == OrderStatus.ASSIGNED

    order = await service.assign_master(order.id, dispatcher_id, master_id)
    assert order.assigned_master_telegram_id == master_id

    order = await service.master_transition(order.id, master_id, OrderStatus.ACCEPTED)
    assert order.status == OrderStatus.ACCEPTED

    order = await service.master_transition(order.id, master_id, OrderStatus.ON_THE_WAY)
    assert order.status == OrderStatus.ON_THE_WAY

    order = await service.master_transition(order.id, master_id, OrderStatus.ARRIVED)
    assert order.status == OrderStatus.ARRIVED

    order = await service.master_transition(order.id, master_id, OrderStatus.IN_PROGRESS)
    assert order.status == OrderStatus.IN_PROGRESS

    order = await service.master_transition(order.id, master_id, OrderStatus.AWAITING_CONFIRM)
    assert order.status == OrderStatus.AWAITING_CONFIRM

    order = await service.dispatcher_transition(
        order.id,
        dispatcher_id,
        OrderStatus.COMPLETED,
        final_amount=275000,
    )
    assert order.status == OrderStatus.COMPLETED
    assert order.final_amount == Decimal("275000")
    assert order.completed_at is not None


@pytest.mark.asyncio
async def test_invalid_master_transition_raises(session):
    service = OrderService(session)
    order = await service.create_driver_order(
        DriverOrderPayload(
            client_telegram_id=333,
            full_name="Driver",
            language="uz",
            phone="+998900000002",
            issue_label="Balon yorilgan",
            latitude=41.2,
            longitude=69.1,
        )
    )

    dispatcher_id = 5002
    master_id = 7002

    await service.assign_order(order.id, dispatcher_id)
    await service.assign_master(order.id, dispatcher_id, master_id)

    with pytest.raises(InvalidOrderTransitionError):
        await service.master_transition(order.id, master_id, OrderStatus.ON_THE_WAY)


@pytest.mark.asyncio
async def test_master_permission_check(session):
    service = OrderService(session)
    order = await service.create_driver_order(
        DriverOrderPayload(
            client_telegram_id=444,
            full_name="Driver",
            language="uz",
            phone="+998900000003",
            issue_label="Boshqa muammo",
            latitude=41.0,
            longitude=69.0,
        )
    )

    dispatcher_id = 5003
    assigned_master = 7003
    other_master = 7004

    await service.assign_order(order.id, dispatcher_id)
    await service.assign_master(order.id, dispatcher_id, assigned_master)

    with pytest.raises(OrderPermissionDeniedError):
        await service.master_transition(order.id, other_master, OrderStatus.ACCEPTED)


@pytest.mark.asyncio
async def test_dispatcher_complete_requires_amount(session):
    service = OrderService(session)
    order = await service.create_driver_order(
        DriverOrderPayload(
            client_telegram_id=555,
            full_name="Driver",
            language="uz",
            phone="+998900000004",
            issue_label="Akkumulyator o'tirgan",
            latitude=41.4,
            longitude=69.4,
        )
    )

    dispatcher_id = 5004
    master_id = 7005

    await service.assign_order(order.id, dispatcher_id)
    await service.assign_master(order.id, dispatcher_id, master_id)
    await service.master_transition(order.id, master_id, OrderStatus.ACCEPTED)
    await service.master_transition(order.id, master_id, OrderStatus.ON_THE_WAY)
    await service.master_transition(order.id, master_id, OrderStatus.ARRIVED)
    await service.master_transition(order.id, master_id, OrderStatus.IN_PROGRESS)
    await service.master_transition(order.id, master_id, OrderStatus.AWAITING_CONFIRM)

    with pytest.raises(InvalidOrderTransitionError):
        await service.dispatcher_transition(
            order.id,
            dispatcher_id,
            OrderStatus.COMPLETED,
            final_amount=None,
        )
