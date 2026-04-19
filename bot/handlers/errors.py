"""
AutoHelp.uz - Global Error Handler
Catches unhandled exceptions gracefully, prevents bot from crashing silently,
and sends a detailed traceback directly to the admins.
"""
import traceback
from aiogram import Router
from aiogram.types import ErrorEvent
from loguru import logger

from core.config import settings

router = Router(name="error_handler")


@router.error()
async def global_error_handler(event: ErrorEvent, bot):
    """
    Catch any unhandled exception during an update.
    1. Log securely.
    2. Notify Admins with traceback snippet so fixes can be immediate.
    3. Notify the user gracefully (if possible).
    """
    exception = event.exception
    
    # Standard string traceback
    tb_str = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    
    # We only take the last 2000 chars so it fits in one Telegram message easily
    short_tb = tb_str[-2500:] if len(tb_str) > 2500 else tb_str
    
    logger.exception(f"Unhandled exception in bot: {exception}")

    # Build an admin alert
    alert_text = (
        f"🚨 <b>CRITICAL SYSTEM ERROR</b> 🚨\n\n"
        f"<b>Type:</b> <code>{type(exception).__name__}</code>\n"
        f"<b>Error:</b> <code>{str(exception)[:200]}</code>\n\n"
        f"<b>Traceback:</b>\n"
        f"<pre language='python'>{short_tb}</pre>"
    )

    # 1. Alert the admins
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=alert_text,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to send error alert to admin {admin_id}: {e}")

    # 2. Try to inform the user that something went wrong
    update = event.update
    try:
        user_msg = (
            "⚠️ <b>Kechirasiz, tizimda nosozlik yuz berdi.</b>\n"
            "Mutaxassislarimizga xabar yuborildi va tez orada buni tuzatamiz.\n"
            "Iltimos, sal turib qaytadan urinib ko'ring: /start"
        )
        if update.message:
            await update.message.answer(user_msg, parse_mode="HTML")
        elif update.callback_query:
            await update.callback_query.message.answer(user_msg, parse_mode="HTML")
            await update.callback_query.answer()
    except Exception:
        pass  # If we can't even send to the user, just let it fail silently at this point.
    
    return True  # Mark error as handled so aiogram doesn't crash the worker
