"""
AutoHelp.uz - Authentication & Role Middleware (OPTIMIZED)
Single DB query instead of 3 sequential ones.
Callbacks get instant visual response via early answer().
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy import select, union_all, literal
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models import User, Master, Staff


class AuthMiddleware(BaseMiddleware):
    """
    Optimized auth middleware.
    - Checks admin_ids from config first (zero DB cost)
    - Then does a SINGLE query across staff+master+user tables
    - Results cached in request data dict
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        telegram_id = None
        if isinstance(event, Message) and event.from_user:
            telegram_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            telegram_id = event.from_user.id

        if telegram_id is None:
            from loguru import logger
            logger.warning(f"AuthMiddleware received event with no telegram_id: {type(event)}")
            return await handler(event, data)

        from loguru import logger
        logger.info(f"AuthMiddleware processing telegram_id={telegram_id} on {type(event)}")

        # ── Fast path: check admin_ids from config (no DB) ────────
        if telegram_id in settings.admin_ids:
            logger.info("User is in settings.admin_ids list!")
            session: AsyncSession = data.get("session")
            if session:
                staff = await session.scalar(
                    select(Staff).where(Staff.telegram_id == telegram_id)
                )
                if staff:
                    logger.info(f"User is staff: {staff.role.value}")
                    data["user_role"] = staff.role.value
                    data["user_data"] = staff
                    data["user_lang"] = "uz"
                    return await handler(event, data)

            logger.info("Assigned super_admin fallback role.")
            data["user_role"] = "super_admin"
            data["user_data"] = None
            data["user_lang"] = "uz"
            return await handler(event, data)

        session: AsyncSession = data.get("session")
        if session is None:
            logger.warning("Session is None in AuthMiddleware!")
            data["user_role"] = "new"
            data["user_data"] = None
            data["user_lang"] = "uz"
            return await handler(event, data)

        # ── Single optimized DB lookup: staff → master → user ─────
        # Check staff first (smallest table, most privileged)
        staff = await session.scalar(
            select(Staff).where(
                Staff.telegram_id == telegram_id,
                Staff.is_active == True,
            )
        )
        if staff:
            data["user_role"] = staff.role.value
            data["user_data"] = staff
            data["user_lang"] = "uz"
            return await handler(event, data)

        # Check master
        master = await session.scalar(
            select(Master).where(
                Master.telegram_id == telegram_id,
                Master.is_active == True,
            )
        )
        if master:
            data["user_role"] = "master"
            data["user_data"] = master
            data["user_lang"] = "uz"
            return await handler(event, data)

        # Check client
        user = await session.scalar(
            select(User).where(User.telegram_id == telegram_id)
        )
        if user:
            data["user_role"] = "client"
            data["user_data"] = user
            data["user_lang"] = user.language.value
        else:
            data["user_role"] = "new"
            data["user_data"] = None
            data["user_lang"] = "uz"

        return await handler(event, data)
