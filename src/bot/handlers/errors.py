import logging

from aiogram import Router
from aiogram.types import ErrorEvent

router = Router(name="errors")
logger = logging.getLogger(__name__)


@router.errors()
async def global_error_handler(event: ErrorEvent) -> bool:
    """Catch every unhandled exception so the bot never crashes silently.

    Logs the full traceback and sends a user-friendly message when possible.
    """
    logger.exception(
        "Unhandled bot error in update %s",
        event.update.update_id,
        exc_info=event.exception,
    )

    # Try to notify the user about the error
    try:
        if event.update.message:
            await event.update.message.answer(
                "Texnik xatolik yuz berdi. Iltimos, 1-2 daqiqadan keyin qayta urinib ko'ring."
            )
        elif event.update.callback_query:
            cb = event.update.callback_query
            try:
                await cb.answer(
                    "Texnik xatolik yuz berdi.",
                    show_alert=True,
                )
            except Exception:
                pass
    except Exception:
        # If even error-reporting fails, just log it
        logger.exception("Failed to send error notification to user")

    return True
