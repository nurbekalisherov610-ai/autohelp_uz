"""
AutoHelp.uz - Fast Response Middleware
Immediately answers all callback queries before any DB work.
This eliminates the "button stuck/loading" visual lag on Telegram.
"""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, CallbackQuery


class FastResponseMiddleware(BaseMiddleware):
    """
    Instantly answers every CallbackQuery before handlers run.
    
    Without this: user taps button → waits 3-7 seconds → button unfreezes
    With this:    user taps button → instant visual response → DB loads quietly
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Immediately acknowledge the tap — removes the loading spinner
        if isinstance(event, CallbackQuery):
            try:
                await event.answer()
            except Exception:
                pass  # Already answered or timed out — no problem

        return await handler(event, data)
