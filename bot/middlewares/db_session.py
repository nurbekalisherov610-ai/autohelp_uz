"""
AutoHelp.uz - Database Session Middleware
Injects an async database session into every handler.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from core.database import async_session


class DbSessionMiddleware(BaseMiddleware):
    """
    Middleware that provides a database session to every handler.
    The session is automatically committed on success and rolled back on error.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with async_session() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
