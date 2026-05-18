"""
Client feedback handler.

After an order is COMPLETED, the client receives a rating keyboard (1–5 stars).
After rating, they can optionally provide text feedback and report shortcomings.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.bot.states.feedback import ClientFeedbackState
from src.db.session import AsyncSessionFactory
from src.services.order_service import OrderService

router = Router(name="client_feedback")
logger = logging.getLogger(__name__)

SKIP_BUTTON_TEXT = "O'tkazib yuborish / Пропустить"


def _safe_message(callback: CallbackQuery) -> Message | None:
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return None
    return msg


def _skip_kb(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=SKIP_BUTTON_TEXT, callback_data=callback_data)]
        ]
    )


# ── Rating ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("client_rating:"))
async def cb_client_rating(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    try:
        parts = callback.data.split(":")
        order_id = int(parts[1])
        rating = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri baho so'rovi.", show_alert=True)
        return

    if rating < 1 or rating > 5:
        await callback.answer("Baho 1 dan 5 gacha bo'lishi kerak.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)

            if order.client is None or callback.from_user is None:
                await callback.answer("Baho berib bo'lmadi.", show_alert=True)
                return

            # Only the order's client can rate
            if order.client.telegram_id != callback.from_user.id:
                await callback.answer("Siz bu buyurtmaga baho bera olmaysiz.", show_alert=True)
                return

            await service.save_feedback(order_id, rating=rating)

    except Exception as exc:
        logger.exception("Rating failed for order #%s: %s", order_id, exc)
        await callback.answer(f"Xatolik: {exc}"[:200], show_alert=True)
        return

    # Ask for text feedback next
    stars = "⭐" * rating
    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(
                f"Bahoyingiz: <b>{stars} ({rating}/5)</b>\n\n"
                "Xizmat haqida qo'shimcha fikrlaringiz bo'lsa yozib qoldiring "
                "(yoki o'tkazib yuboring):",
                reply_markup=_skip_kb(f"skip_feedback:{order_id}"),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await state.update_data(feedback_order_id=order_id)
    await state.set_state(ClientFeedbackState.waiting_for_text)
    await callback.answer()


# ── Skip feedback text ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("skip_feedback:"))
async def cb_skip_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(
                "Bahoyingiz uchun rahmat! / Спасибо за вашу оценку! 🙏"
            )
        except Exception:
            pass
    await callback.answer()


# ── Skip shortcomings ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("skip_shortcomings:"))
async def cb_skip_shortcomings(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(
                "Fikr-mulohazangiz uchun rahmat! / Спасибо за ваш отзыв! 🙏"
            )
        except Exception:
            pass
    await callback.answer()


# ── Feedback text ─────────────────────────────────────────────────────────────

@router.message(ClientFeedbackState.waiting_for_text)
async def process_feedback_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("feedback_order_id")
    if not order_id:
        await state.clear()
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            await service.save_feedback(order_id, feedback_text=message.text)
    except Exception as exc:
        logger.exception("Feedback text save failed for order #%s: %s", order_id, exc)

    await message.answer(
        "Kamchiliklar yoki shikoyatlaringiz bo'lsa, ularni ham yozib qoldiring:",
        reply_markup=_skip_kb(f"skip_shortcomings:{order_id}"),
    )
    await state.set_state(ClientFeedbackState.waiting_for_shortcomings)


# ── Shortcomings ──────────────────────────────────────────────────────────────

@router.message(ClientFeedbackState.waiting_for_shortcomings)
async def process_feedback_shortcomings(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("feedback_order_id")
    if not order_id:
        await state.clear()
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            await service.save_feedback(order_id, shortcomings=message.text)
    except Exception as exc:
        logger.exception("Shortcomings save failed for order #%s: %s", order_id, exc)

    await state.clear()
    await message.answer(
        "✅ Barchasi qabul qilindi. Fikr-mulohazangiz uchun rahmat!\n"
        "Спасибо за ваш отзыв! 🙏"
    )
