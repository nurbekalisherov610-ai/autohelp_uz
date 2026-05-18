import logging
import traceback

from aiogram import Router
from aiogram.types import ErrorEvent

from src.core.config import get_settings

router = Router(name="errors")
logger = logging.getLogger(__name__)
settings = get_settings()


@router.errors()
async def global_error_handler(event: ErrorEvent) -> bool:
    """Catch every unhandled exception so the bot never crashes silently."""
    exc = event.exception
    update = event.update
    
    # 1. Log the error with full traceback
    logger.exception(
        "CRITICAL: Unhandled bot error in update %s: %s",
        update.update_id,
        exc,
    )

    # 2. Notify the user with a simple, clean message
    try:
        if update.message:
            await update.message.answer(
                "Texnik xatolik yuz berdi. Iltimos, 1-2 daqiqadan keyin qayta urinib ko'ring."
            )
        elif update.callback_query:
            await update.callback_query.answer(
                "Texnik xatolik yuz berdi. Qayta urinib ko'ring.",
                show_alert=True,
            )
    except Exception:
        pass

    # 3. Notify Admins if configured
    try:
        admin_ids = settings.parsed_admin_ids
        if admin_ids:
            bot = update.get_bot()
            if bot:
                tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                error_report = (
                    f"🚨 UNHANDLED BOT ERROR\n\n"
                    f"Update ID: {update.update_id}\n"
                    f"Error: {exc}\n\n"
                    f"Traceback:\n{tb[:3000]}"
                )
                await bot.send_message(
                    chat_id=admin_ids[0],
                    text=error_report,
                )
    except Exception as notify_exc:
        logger.error("Failed to notify admins about error: %s", notify_exc)

    return True
