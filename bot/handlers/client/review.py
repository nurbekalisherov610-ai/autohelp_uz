"""
AutoHelp.uz - Client Review Handler
Handles rating and optional feedback report after order completion.
"""
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.states.client_states import ReviewStates
from bot.keyboards.client_kb import (
    rating_keyboard,
    review_issue_keyboard,
    skip_keyboard,
    main_menu_keyboard,
)
from locales.texts import t
from models.user import User
from services.order_service import OrderService
from services.notification_service import NotificationService

router = Router(name="client_review")


ISSUE_LABELS = {
    "uz": {
        "delay": "Kechikish",
        "quality": "Sifat past",
        "price": "Narx bo'yicha e'tiroz",
        "behavior": "Muomala yomon",
    },
    "ru": {
        "delay": "Опоздание",
        "quality": "Низкое качество",
        "price": "Вопрос по цене",
        "behavior": "Плохое поведение",
    },
}


def _issue_label(issue_code: str | None, lang: str) -> str | None:
    if not issue_code or issue_code == "none":
        return None
    return ISSUE_LABELS.get(lang, ISSUE_LABELS["uz"]).get(issue_code)


def _compose_review_comment(issue_label: str | None, user_comment: str | None) -> str | None:
    comment = (user_comment or "").strip()
    if issue_label and comment:
        return f"Issue: {issue_label}\nComment: {comment}"
    if issue_label:
        return f"Issue: {issue_label}"
    return comment or None


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
    """Handle star rating selection and optional issue picker."""
    rating = int(callback.data.split(":")[1])
    await state.update_data(rating=rating)

    stars = "⭐" * rating
    issue_prompt = {
        "uz": "Agar muammo bo'lgan bo'lsa, bittasini tanlang (ixtiyoriy):",
        "ru": "Если была проблема, выберите один пункт (необязательно):",
    }
    await callback.message.edit_text(
        f"{stars}\n\n{issue_prompt.get(user_lang, issue_prompt['uz'])}",
        reply_markup=review_issue_keyboard(user_lang),
    )

    await state.set_state(ReviewStates.selecting_issue)
    await callback.answer()


@router.callback_query(
    ReviewStates.selecting_issue,
    F.data.startswith("review_issue:"),
)
async def process_issue_selection(
    callback: CallbackQuery,
    state: FSMContext,
    user_lang: str = "uz",
):
    """Store optional issue and move to optional comment step."""
    issue_code = callback.data.split(":", 1)[1]
    await state.update_data(review_issue_code=issue_code)

    await callback.message.edit_text(
        t("leave_comment", user_lang),
        reply_markup=skip_keyboard(user_lang),
    )
    await state.set_state(ReviewStates.entering_comment)
    await callback.answer()


@router.message(ReviewStates.selecting_issue)
async def issue_selection_requires_button(
    message: Message,
    user_lang: str = "uz",
):
    """Keep issue selection on inline buttons to avoid accidental text input loss."""
    prompt = {
        "uz": "Iltimos, pastdagi tugmalardan bittasini tanlang.",
        "ru": "Пожалуйста, выберите один вариант кнопкой ниже.",
    }
    await message.answer(
        prompt.get(user_lang, prompt["uz"]),
        reply_markup=review_issue_keyboard(user_lang),
    )


@router.message(ReviewStates.entering_comment, F.text)
async def process_comment(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Handle review comment text and notify dispatch channel."""
    data = await state.get_data()
    order_uid = data.get("review_order_uid")
    rating = data.get("rating", 5)
    issue_code = data.get("review_issue_code")
    issue_label = _issue_label(issue_code, user_lang)

    comment_to_store = _compose_review_comment(issue_label, message.text)

    order_service = OrderService(session)
    saved = False
    try:
        await order_service.add_review(
            order_uid=order_uid,
            rating=rating,
            comment=comment_to_store,
        )
        saved = True
    except Exception:
        pass

    if saved:
        order = await order_service.order_repo.get_by_uid(order_uid)
        if order:
            notification = NotificationService(bot, session)
            await notification.notify_dispatcher_review_feedback(
                order=order,
                rating=rating,
                issue=issue_label,
                comment=(message.text or "").strip() or None,
            )

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
    bot: Bot,
    user_data: User | None = None,
    user_lang: str = "uz",
):
    """Skip comment and submit review with optional issue only."""
    data = await state.get_data()
    order_uid = data.get("review_order_uid")
    rating = data.get("rating", 5)
    issue_code = data.get("review_issue_code")
    issue_label = _issue_label(issue_code, user_lang)

    order_service = OrderService(session)
    saved = False
    try:
        await order_service.add_review(
            order_uid=order_uid,
            rating=rating,
            comment=_compose_review_comment(issue_label, None),
        )
        saved = True
    except Exception:
        pass

    if saved:
        order = await order_service.order_repo.get_by_uid(order_uid)
        if order:
            notification = NotificationService(bot, session)
            await notification.notify_dispatcher_review_feedback(
                order=order,
                rating=rating,
                issue=issue_label,
                comment=None,
            )

    await state.clear()
    await callback.message.edit_text(t("review_thanks", user_lang))
    await callback.message.answer(
        t("main_menu", user_lang),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(user_lang),
    )
    await callback.answer()
