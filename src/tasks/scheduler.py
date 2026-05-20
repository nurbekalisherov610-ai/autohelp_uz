import asyncio
import logging
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import Select, func, select

from src.core.config import get_settings
from src.core.logging import configure_logging
from src.core.startup import wait_for_dependencies
from src.db.enums import OrderStatus
from src.db.init_db import init_db
from src.db.models.order import Order
from src.db.session import AsyncSessionFactory

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


async def _fetch_stale_orders(status: OrderStatus, threshold_minutes: int) -> list[Order]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)
    query: Select[tuple[Order]] = (
        select(Order)
        .where(Order.status == status)
        .where(Order.updated_at <= cutoff)
        .order_by(Order.updated_at.asc())
        .limit(20)
    )

    async with AsyncSessionFactory() as session:
        rows = await session.execute(query)
        return list(rows.scalars().all())


async def _send_dispatcher_alert(bot: Bot | None, text: str) -> None:
    if bot is None or settings.resolved_dispatcher_chat_id is None:
        logger.warning("Dispatcher alert skipped: bot token or dispatcher chat id not configured")
        return

    try:
        await bot.send_message(chat_id=settings.resolved_dispatcher_chat_id, text=text)
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to send dispatcher alert: %s", exc)


async def sla_watchdog(bot: Bot | None) -> None:
    try:
        assigned_stale = await _fetch_stale_orders(OrderStatus.ASSIGNED, threshold_minutes=5)
        on_the_way_stale = await _fetch_stale_orders(OrderStatus.ON_THE_WAY, threshold_minutes=60)

        if not (assigned_stale or on_the_way_stale):
            return

        lines = ["SLA ogohlantirish:"]
        if assigned_stale:
            lines.append("ASSIGNED > 5 min:")
            lines.extend(f" - #{order.id}" for order in assigned_stale)

        if on_the_way_stale:
            lines.append("ON_THE_WAY > 60 min:")
            lines.extend(f" - #{order.id}" for order in on_the_way_stale)

        await _send_dispatcher_alert(bot, "\n".join(lines))
    except Exception as exc:
        logger.exception("SLA watchdog failed: %s", exc)


async def daily_backup_report() -> None:
    logger.info("Backup monitor tick")


async def stats_report_tick(bot: Bot | None) -> None:
    if bot is None or settings.resolved_dispatcher_chat_id is None:
        return
        
    try:
        now_local = datetime.now(ZoneInfo(settings.timezone))
        today_start_local = datetime.combine(now_local.date(), dt_time.min).replace(tzinfo=ZoneInfo(settings.timezone))
        today_start_utc = today_start_local.astimezone(timezone.utc)
        
        query = (
            select(
                func.count(Order.id),
                func.sum(Order.final_amount),
                func.avg(Order.rating)
            )
            .where(Order.status == OrderStatus.COMPLETED)
            .where(Order.completed_at >= today_start_utc)
        )
        
        async with AsyncSessionFactory() as session:
            result = await session.execute(query)
            row = result.fetchone()
            
        if not row:
            return

        count = row[0] or 0
        total = row[1] or 0
        avg_rating = row[2] or 0.0
        
        text = (
            f"📊 Kunlik Hisobot ({now_local.date()})\n\n"
            f"✅ Tugatilgan buyurtmalar: {count} ta\n"
            f"💰 Umumiy daromad: {total:,.0f} so'm\n"
            f"⭐️ O'rtacha baho: {avg_rating:.1f} / 5.0\n"
        )
        
        await bot.send_message(chat_id=settings.resolved_dispatcher_chat_id, text=text)
    except Exception as exc:
        logger.exception("Failed to send daily report: %s", exc)


async def run_scheduler() -> None:
    await wait_for_dependencies(
        redis_dsn=settings.redis_dsn,
        use_redis=settings.use_redis,
        attempts=settings.dependency_wait_attempts,
        delay_seconds=settings.dependency_wait_delay_seconds,
    )
    await init_db()

    bot: Bot | None = None
    if settings.bot_token:
        bot = Bot(token=settings.bot_token)

    scheduler = AsyncIOScheduler(
        timezone=settings.timezone,
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    scheduler.add_job(sla_watchdog, "interval", minutes=1, kwargs={"bot": bot}, id="sla_watchdog")
    scheduler.add_job(daily_backup_report, "interval", hours=24, id="backup_monitor")
    scheduler.add_job(stats_report_tick, "cron", hour=23, minute=59, kwargs={"bot": bot}, id="stats_report")
    scheduler.start()

    logger.info("Scheduler started")

    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)
        if bot is not None:
            await bot.session.close()


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(run_scheduler())
        except Exception as exc:  # pragma: no cover
            logger.exception("Scheduler crashed, restarting: %s", exc)
            time.sleep(5)
