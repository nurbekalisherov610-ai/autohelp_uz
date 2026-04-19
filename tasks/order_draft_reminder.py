"""
AutoHelp.uz - Abandoned Order Draft Reminder Task
Sends friendly nudges to clients who left order creation midway.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from core.config import settings
from core.database import async_session
from repositories.order_draft_repo import OrderDraftRepo


def _reminder_text(lang: str) -> str:
    if lang == "ru":
        return (
            "👋 <b>Напоминание</b>\n\n"
            "Вы не завершили заявку.\n"
            "Если хотите, можем продолжить с того же шага."
        )
    return (
        "👋 <b>Eslatma</b>\n\n"
        "Buyurtmangiz oxirigacha to'ldirilmagan.\n"
        "Xohlasangiz, aynan shu bosqichdan davom ettiramiz."
    )


def _reminder_keyboard(lang: str) -> InlineKeyboardMarkup:
    if lang == "ru":
        continue_text = "✅ Продолжить"
        cancel_text = "❌ Отменить"
    else:
        continue_text = "✅ Davom ettirish"
        cancel_text = "❌ Bekor qilish"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=continue_text, callback_data="draft_continue"),
                InlineKeyboardButton(text=cancel_text, callback_data="draft_cancel"),
            ]
        ]
    )


async def send_order_draft_reminders(bot):
    """
    Send a one-time reminder for stale unfinished order flows.
    Runs every minute via APScheduler.
    """
    try:
        async with async_session() as session:
            repo = OrderDraftRepo(session)
            due = await repo.get_due_reminders(
                inactive_minutes=settings.order_draft_reminder_minutes,
                limit=200,
            )

            if not due:
                return

            sent = 0
            for draft in due:
                lang = draft.language if draft.language in ("uz", "ru") else "uz"
                try:
                    await bot.send_message(
                        chat_id=draft.telegram_id,
                        text=_reminder_text(lang),
                        parse_mode="HTML",
                        reply_markup=_reminder_keyboard(lang),
                    )
                    await repo.mark_reminded(draft.id)
                    sent += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to send order-draft reminder to {draft.telegram_id}: {e}"
                    )

            if sent:
                logger.info(f"Order draft reminders sent: {sent}")

            await session.commit()
    except Exception as e:
        logger.error(f"Order draft reminder task failed: {e}")
