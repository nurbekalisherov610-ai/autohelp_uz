from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender


class TypingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            bot = data.get("bot")
            if bot:
                async with ChatActionSender.typing(bot=bot, chat_id=event.chat.id):
                    return await handler(event, data)
        return await handler(event, data)
