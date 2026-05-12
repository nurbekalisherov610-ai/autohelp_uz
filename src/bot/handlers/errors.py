import logging

from aiogram import Router
from aiogram.types import ErrorEvent

router = Router(name="errors")
logger = logging.getLogger(__name__)


@router.errors()
async def global_error_handler(event: ErrorEvent) -> bool:
    logger.exception("Unhandled bot error", exc_info=event.exception)

    if event.update.message:
        await event.update.message.answer(
            "Texnik xatolik yuz berdi. Iltimos, 1-2 daqiqadan keyin qayta urinib ko'ring."
        )
    elif event.update.callback_query:
        try:
            await event.update.callback_query.answer(
                "Texnik xatolik yuz berdi.", 
                show_alert=True
            )
        except Exception:
            pass
    return True
