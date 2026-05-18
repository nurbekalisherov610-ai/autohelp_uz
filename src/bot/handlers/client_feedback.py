import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from src.db.session import AsyncSessionFactory
from src.services.order_service import OrderService

router = Router(name="client_feedback")
logger = logging.getLogger(__name__)


def _safe_message(callback: CallbackQuery) -> Message | None:
    """Return the real Message object or None if the message is inaccessible."""
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return None
    return msg


from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.states.feedback import ClientFeedbackState

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
            if order.client.telegram_id != callback.from_user.id:
                await callback.answer("Siz bu buyurtmaga baho bera olmaysiz.", show_alert=True)
                return
            order.rating = rating
            await session.commit()
    except Exception as exc:
        logger.exception("Rating failed for order #%s: %s", order_id, exc)
        await callback.answer(f"Xatolik yuz berdi: {exc}"[:200], show_alert=True)
        return

    msg = _safe_message(callback)
    if msg is not None:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="O'tkazib yuborish / Пропустить", callback_data=f"skip_feedback:{order_id}")]])
            await msg.edit_text(f"Sizning bahoingiz: {'⭐' * rating}\n\nXizmat haqida qo'shimcha fikrlaringiz bo'lsa yozib qoldiring (yoki o'tkazib yuboring):", reply_markup=kb)
        except Exception:
            pass
    await state.update_data(feedback_order_id=order_id)
    await state.set_state(ClientFeedbackState.waiting_for_text)
    await callback.answer()

@router.callback_query(F.data.startswith("skip_feedback:"))
async def cb_skip_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        order_id = None
    
    await state.clear()
    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text("Fikr-mulohazangiz uchun rahmat! / Спасибо за ваш отзыв!")
        except Exception:
            pass
    await callback.answer()

@router.callback_query(F.data.startswith("skip_shortcomings:"))
async def cb_skip_shortcomings(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text("Fikr-mulohazangiz uchun rahmat! / Спасибо за ваш отзыв!")
        except Exception:
            pass
    await callback.answer()

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
            order = await service.get_order(order_id)
            order.feedback_text = message.text
            await session.commit()
    except Exception as exc:
        logger.exception("Feedback text save failed for order #%s: %s", order_id, exc)

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="O'tkazib yuborish / Пропустить", callback_data=f"skip_shortcomings:{order_id}")]])
    await message.answer("Kamchiliklar yoki shikoyatlaringiz bo'lsa, ularni ham yozib qoldiring:", reply_markup=kb)
    await state.set_state(ClientFeedbackState.waiting_for_shortcomings)

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
            order = await service.get_order(order_id)
            order.shortcomings = message.text
            await session.commit()
    except Exception as exc:
        logger.exception("Feedback shortcomings save failed for order #%s: %s", order_id, exc)

    await state.clear()
    await message.answer("Barchasi qabul qilindi. Fikr-mulohazangiz uchun rahmat! / Спасибо за ваш отзыв!")

