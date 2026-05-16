import time
from collections.abc import Awaitable, Callable
from typing import Any, Union

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message


class ThrottlingMiddleware(BaseMiddleware):
    """Rate-limiter for messages and callback queries.

    Messages use the full ``rate_limit``; callback queries (button presses)
    use a much shorter cooldown so that inline-keyboard interactions feel
    responsive and never get silently swallowed.
    """

    def __init__(self, rate_limit: float = 1.0) -> None:
        self.rate_limit = rate_limit
        self._msg_cache: dict[int, float] = {}
        self._cb_cache: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: dict[str, Any],
    ) -> Any:
        # Determine the user behind this event
        from_user = getattr(event, "from_user", None)
        if from_user is None:
            return await handler(event, data)

        user_id = from_user.id
        now = time.time()

        if isinstance(event, CallbackQuery):
            # Very short cooldown for button taps (0.3 s) – just enough to
            # prevent accidental double-taps but never block normal usage.
            last = self._cb_cache.get(user_id, 0.0)
            if (now - last) < 0.3:
                return None
            self._cb_cache[user_id] = now
        else:
            last = self._msg_cache.get(user_id, 0.0)
            if (now - last) < self.rate_limit:
                return None
            self._msg_cache[user_id] = now

        return await handler(event, data)
