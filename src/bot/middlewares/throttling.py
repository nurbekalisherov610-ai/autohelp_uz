import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 1.0) -> None:
        self.rate_limit = rate_limit
        self.caches: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not hasattr(event, "from_user") or event.from_user is None:
            return await handler(event, data)

        user_id = event.from_user.id
        now = time.time()
        
        last_called = self.caches.get(user_id, 0.0)
        
        if (now - last_called) < self.rate_limit:
            # Drop the event silently to avoid spamming the user
            return None
            
        self.caches[user_id] = now
        return await handler(event, data)
