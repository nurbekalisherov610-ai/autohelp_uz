"""
AutoHelp.uz - SLA Monitor Task
Checks for SLA violations every minute and alerts dispatchers.
"""
from loguru import logger

from core.database import async_session
from core.config import settings
from models.order import OrderStatus
from repositories.order_repo import OrderRepo


async def check_sla_violations(bot):
    """
    Check for SLA violations and send alerts.
    Runs every 60 seconds via APScheduler.
    """
    from services.notification_service import NotificationService

    try:
        async with async_session() as session:
            order_repo = OrderRepo(session)
            notification = NotificationService(bot, session)

            # 1. ASSIGNED orders not accepted within 5 minutes
            try:
                violations = await order_repo.get_sla_violations(
                    status=OrderStatus.ASSIGNED,
                    timeout_minutes=settings.sla_assign_timeout,
                )
                for order in violations:
                    was_sent = await notification.send_sla_alert(order, "sla_alert_assign")
                    if was_sent:
                        logger.warning(
                            f"SLA violation: Order {order.order_uid} ASSIGNED "
                            f"for >{settings.sla_assign_timeout} min"
                        )
            except Exception as e:
                logger.error(f"SLA check ASSIGNED failed: {e}")

            # 2. ON_THE_WAY orders — master hasn't arrived in 60 minutes
            try:
                violations = await order_repo.get_sla_violations(
                    status=OrderStatus.ON_THE_WAY,
                    timeout_minutes=settings.sla_on_the_way_timeout,
                )
                for order in violations:
                    was_sent = await notification.send_sla_alert(order, "sla_alert_on_the_way")
                    if was_sent:
                        logger.warning(
                            f"SLA violation: Order {order.order_uid} ON_THE_WAY "
                            f"for >{settings.sla_on_the_way_timeout} min"
                        )
            except Exception as e:
                logger.error(f"SLA check ON_THE_WAY failed: {e}")

            # 3. AWAITING_CONFIRM orders — not confirmed in 15 minutes
            try:
                violations = await order_repo.get_sla_violations(
                    status=OrderStatus.AWAITING_CONFIRM,
                    timeout_minutes=settings.sla_confirm_timeout,
                )
                for order in violations:
                    was_sent = await notification.send_sla_alert(order, "sla_alert_confirm")
                    if was_sent:
                        logger.warning(
                            f"SLA violation: Order {order.order_uid} AWAITING_CONFIRM "
                            f"for >{settings.sla_confirm_timeout} min"
                        )
            except Exception as e:
                logger.error(f"SLA check AWAITING_CONFIRM failed: {e}")

            await session.commit()

    except Exception as e:
        logger.error(f"SLA monitor error: {e}")
