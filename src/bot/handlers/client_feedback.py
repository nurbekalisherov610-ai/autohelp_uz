"""Client feedback handler — rating stars + text after order completion."""
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


def _safe_msg(cb: CallbackQuery) -> Message | None:
    if cb.message is None or isinstance(cb.message, InaccessibleMessage):
        return None
    return cb.message


def _skip_kb(data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="O'tkazib yuborish / Пропустить", callback_data=data)
        ]]
    )


@router.callback_query(F.data.startswith("client_rating:"))
async def cb_rating(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        parts = (callback.data or "").split(":")
        order_id = int(parts[1])
        rating = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    if not 1 <= rating <= 5:
        await callback.answer("Baho 1-5 orasida bo'lishi kerak.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            # Only the ordering client can rate — we check client_id
            # (we don't load the relationship — use client_id scalar)
            from sqlalchemy import select
            from src.db.models.user import User
            client = await session.scalar(
                select(User).where(User.id == order.client_id)
            )
            if not client or client.telegram_id != callback.from_user.id:
                await callback.answer("Siz bu buyurtmaga baho bera olmaysiz.", show_alert=True)
                return
            await service.save_feedback(order_id, rating=rating)
    except Exception as exc:
        logger.exception("Rating save failed for #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    stars = "⭐" * rating
    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"Bahoyingiz: <b>{stars} ({rating}/5)</b>\n\n"
                "Qo'shimcha fikr-mulohazalaringiz bo'lsa yozib qoldiring:",
                reply_markup=_skip_kb(f"skip_feedback:{order_id}"),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await state.update_data(feedback_order_id=order_id)
    await state.set_state(ClientFeedbackState.waiting_for_text)
    await callback.answer()


@router.callback_query(F.data.startswith("skip_feedback:"))
async def cb_skip_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
        order_id = 0

    await state.clear()
    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text("Bahoyingiz uchun rahmat! / Спасибо за оценку! 🙏")
        except Exception:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("skip_shortcomings:"))
async def cb_skip_shortcomings(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text("Fikr-mulohazangiz uchun rahmat! / Спасибо за отзыв! 🙏")
        except Exception:
            pass
    await callback.answer()


@router.message(ClientFeedbackState.waiting_for_text)
async def process_feedback_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("feedback_order_id")
    if order_id:
        try:
            async with AsyncSessionFactory() as session:
                await OrderService(session).save_feedback(order_id, feedback_text=message.text)
        except Exception as exc:
            logger.error("Feedback text save error #%s: %s", order_id, exc)

    await message.answer(
        "Kamchiliklar yoki shikoyatlaringiz bo'lsa yozib qoldiring:",
        reply_markup=_skip_kb(f"skip_shortcomings:{order_id or 0}"),
    )
    await state.set_state(ClientFeedbackState.waiting_for_shortcomings)


@router.message(ClientFeedbackState.waiting_for_shortcomings)
async def process_shortcomings(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("feedback_order_id")
    if order_id:
        try:
            async with AsyncSessionFactory() as session:
                await OrderService(session).save_feedback(order_id, shortcomings=message.text)
        except Exception as exc:
            logger.error("Shortcomings save error #%s: %s", order_id, exc)

    await state.clear()
    await message.answer("✅ Barchasi qabul qilindi. Rahmat! / Спасибо! 🙏")
