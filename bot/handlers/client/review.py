"""
AutoHelp.uz - Client Review Handler
Handles rating and review after order completion.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.states.client_states import ReviewStates
from bot.keyboards.client_kb import rating_keyboard, skip_keyboard, main_menu_keyboard
from locales.texts import t
from models.user import User
from services.order_service import OrderService

router = Router(name="client_review")


@router.callback_query(F.data.startswith("rate_order:"))
async def prompt_rating(
    callback: CallbackQuery,
    state: FSMContext,
    user_lang: str = "uz",
):
    """Start the rating flow for a completed order."""
    order_uid = callback.data.split(":")[1]
    await state.update_data(review_order_uid=order_uid)

    await callback.message.edit_text(
        t("rate_service", user_lang),
        reply_markup=rating_keyboard(),
    )
    await state.set_state(ReviewStates.selecting_rating)
    await callback.answer()


@router.callback_query(
    ReviewStates.selecting_rating,
    F.data.startswith("rate:"),
)
async def process_rating(
    callback: CallbackQuery,
    state: FSMContext,
    user_lang: str = "uz",
):
    """Handle star rating selection."""
    rating = int(callback.data.split(":")[1])
    await state.update_data(rating=rating)

    stars = "⭐" * rating
    await callback.message.edit_text(f"{stars}\n\n" + t("leave_comment", user_lang))

    await callback.message.answer(
        "👇",
        reply_markup=skip_keyboard(user_lang),
    )
    await state.set_state(ReviewStates.entering_comment)
    await callback.answer()


@router.message(ReviewStates.entering_comment, F.text)
async def process_comment(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Handle review comment text."""
    data = await state.get_data()
    order_uid = data.get("review_order_uid")
    rating = data.get("rating", 5)

    order_service = OrderService(session)
    try:
        await order_service.add_review(
            order_uid=order_uid,
            rating=rating,
            comment=message.text,
        )
    except Exception:
        pass

    await state.clear()
    await message.answer(
        t("review_thanks", user_lang),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(user_lang),
    )


@router.callback_query(
    ReviewStates.entering_comment,
    F.data == "skip",
)
async def skip_comment(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Skip comment and submit review."""
    data = await state.get_data()
    order_uid = data.get("review_order_uid")
    rating = data.get("rating", 5)

    order_service = OrderService(session)
    try:
        await order_service.add_review(
            order_uid=order_uid,
            rating=rating,
        )
    except Exception:
        pass

    await state.clear()
    await callback.message.edit_text(t("review_thanks", user_lang))
    await callback.message.answer(
        t("main_menu", user_lang),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(user_lang),
    )
    await callback.answer()
