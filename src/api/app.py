import uvicorn
from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis
from sqlalchemy import func, select

from src.core.config import get_settings
from src.core.logging import configure_logging
from src.core.startup import wait_for_dependencies
from src.db.enums import OrderStatus
from src.db.init_db import init_db
from src.db.models.order import Order
from src.db.session import AsyncSessionFactory, engine

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(title="AutoHelp API", version="0.1.0")


@app.on_event("startup")
async def on_startup() -> None:
    await wait_for_dependencies(
        redis_dsn=settings.redis_dsn,
        use_redis=settings.use_redis,
        attempts=settings.dependency_wait_attempts,
        delay_seconds=settings.dependency_wait_delay_seconds,
    )
    await init_db()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    async with engine.begin() as conn:
        await conn.execute(select(1))

    if settings.use_redis:
        redis = Redis.from_url(settings.redis_dsn)
        try:
            await redis.ping()
        finally:
            await redis.aclose()

    return {"status": "ready"}


@app.get("/orders/new")
async def get_new_orders(limit: int = 20) -> list[dict[str, object]]:
    safe_limit = max(1, min(limit, 100))

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Order)
            .where(Order.status == OrderStatus.NEW)
            .order_by(Order.created_at.asc())
            .limit(safe_limit)
        )
        orders = result.scalars().all()

    return [
        {
            "id": order.id,
            "status": order.status,
            "issue_type": order.issue_type,
            "issue_label": order.issue_label,
            "phone": order.phone,
            "latitude": order.latitude,
            "longitude": order.longitude,
            "assigned_dispatcher_telegram_id": order.assigned_dispatcher_telegram_id,
            "assigned_master_telegram_id": order.assigned_master_telegram_id,
            "final_amount": float(order.final_amount) if order.final_amount is not None else None,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
        }
        for order in orders
    ]


@app.get("/orders/{order_id}")
async def get_order(order_id: int) -> dict[str, object]:
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "id": order.id,
        "status": order.status,
        "issue_type": order.issue_type,
        "issue_label": order.issue_label,
        "phone": order.phone,
        "latitude": order.latitude,
        "longitude": order.longitude,
        "assigned_dispatcher_telegram_id": order.assigned_dispatcher_telegram_id,
        "assigned_master_telegram_id": order.assigned_master_telegram_id,
        "final_amount": float(order.final_amount) if order.final_amount is not None else None,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }


@app.get("/orders/master/{master_telegram_id}")
async def get_master_orders(master_telegram_id: int, limit: int = 20) -> list[dict[str, object]]:
    safe_limit = max(1, min(limit, 100))

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Order)
            .where(Order.assigned_master_telegram_id == master_telegram_id)
            .order_by(Order.updated_at.desc())
            .limit(safe_limit)
        )
        orders = result.scalars().all()

    return [
        {
            "id": order.id,
            "status": order.status,
            "issue_label": order.issue_label,
            "phone": order.phone,
            "updated_at": order.updated_at.isoformat(),
        }
        for order in orders
    ]


@app.get("/stats/summary")
async def get_summary_stats() -> dict[str, object]:
    async with AsyncSessionFactory() as session:
        total_orders = await session.scalar(select(func.count(Order.id)))
        completed_orders = await session.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.COMPLETED)
        )
        cancelled_orders = await session.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.CANCELLED)
        )
        rejected_orders = await session.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.REJECTED)
        )
        revenue = await session.scalar(
            select(func.coalesce(func.sum(Order.final_amount), 0)).where(
                Order.status == OrderStatus.COMPLETED
            )
        )

    return {
        "total_orders": int(total_orders or 0),
        "completed_orders": int(completed_orders or 0),
        "cancelled_orders": int(cancelled_orders or 0),
        "rejected_orders": int(rejected_orders or 0),
        "revenue": float(revenue or 0),
    }


if __name__ == "__main__":
    uvicorn.run(
        "src.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )
