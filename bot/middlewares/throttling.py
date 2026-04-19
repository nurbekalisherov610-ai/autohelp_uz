"""
AutoHelp.uz - Throttling Middleware
Rate limiting to prevent bot abuse.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from redis.asyncio import Redis

from core.redis import get_redis


class ThrottlingMiddleware(BaseMiddleware):
    """
    Simple rate limiting middleware using Redis.
    Limits each user to a certain number of messages per time window.
    """

    def __init__(self, rate_limit: float = 0.5):
        """
        Args:
            rate_limit: Minimum seconds between messages from same user.
        """
        self.rate_limit = rate_limit

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Extract user_id
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is None:
            return await handler(event, data)

        redis: Redis = await get_redis()
        key = f"throttle:{user_id}"

        # Check if user is throttled
        if await redis.exists(key):
            # User is sending too fast, silently ignore
            return None

        # Set throttle key with expiration
        await redis.set(key, "1", ex=int(self.rate_limit) or 1)

        return await handler(event, data)
