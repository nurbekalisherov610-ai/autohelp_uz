"""
AutoHelp.uz - Throttling Middleware
Rate limiting to prevent bot abuse (clients only).
Masters and dispatchers are never throttled.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from redis.asyncio import Redis

from core.redis import get_redis


class ThrottlingMiddleware(BaseMiddleware):
    """
    Simple rate limiting middleware using Redis.
    Only throttles client users. Masters/dispatchers/admins are exempt
    so their operational buttons always respond instantly.
    """

    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Never throttle staff — their buttons must always respond
        user_role = data.get("user_role", "new")
        if user_role in ("master", "dispatcher", "admin", "super_admin"):
            return await handler(event, data)

        # Extract user_id for clients
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is None:
            return await handler(event, data)

        redis: Redis = await get_redis()
        key = f"throttle:{user_id}"

        if await redis.exists(key):
            return None

        await redis.set(key, "1", ex=max(int(self.rate_limit), 1))

        return await handler(event, data)
