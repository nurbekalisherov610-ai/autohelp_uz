"""
AutoHelp.uz - Authentication & Role Middleware (optimized)
Resolves role for each event and injects:
- user_role
- user_data
- user_lang
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models import Master, Staff, User


class AuthMiddleware(BaseMiddleware):
    """
    Optimized auth middleware.
    - Checks admin_ids from config first (zero DB cost)
    - Then checks staff -> master -> user
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
            return await handler(event, data)

        # Fast path: config-defined admins (works even before staff row exists)
        if telegram_id in settings.admin_ids:
            session: AsyncSession = data.get("session")
            if session:
                staff = await session.scalar(
                    select(Staff).where(Staff.telegram_id == telegram_id)
                )
                if staff:
                    data["user_role"] = staff.role.value
                    data["user_data"] = staff
                    data["user_lang"] = "uz"
                    return await handler(event, data)

            data["user_role"] = "super_admin"
            data["user_data"] = None
            data["user_lang"] = "uz"
            return await handler(event, data)

        session: AsyncSession = data.get("session")
        if session is None:
            data["user_role"] = "new"
            data["user_data"] = None
            data["user_lang"] = "uz"
            return await handler(event, data)

        # Staff first (most privileged / smallest table)
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

        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user:
            data["user_role"] = "client"
            data["user_data"] = user
            data["user_lang"] = user.language.value
        else:
            data["user_role"] = "new"
            data["user_data"] = None
            data["user_lang"] = "uz"

        return await handler(event, data)

