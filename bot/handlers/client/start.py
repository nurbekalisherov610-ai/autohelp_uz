"""
AutoHelp.uz - Client Start & Registration Handler
Handles /start, language selection, and contact sharing.
"""
from html import escape

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.states.client_states import RegistrationStates
from bot.keyboards.client_kb import (
    language_keyboard, share_contact_keyboard, main_menu_keyboard, settings_keyboard
)
from locales.texts import t
from repositories.user_repo import UserRepo
from repositories.order_draft_repo import OrderDraftRepo
from models.user import Language, User

router = Router(name="client_start")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user_role: str = "new",
    user_data=None,
    user_lang: str = "uz",
):
    """Handle /start command."""
    await state.clear()
    draft_repo = OrderDraftRepo(session)
    await draft_repo.clear(message.from_user.id)

    # Existing user — go straight to main menu
    if user_role == "client" and user_data:
        await message.answer(
            t("main_menu", user_lang),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(user_lang),
        )
        return

    # Dispatcher/master/admin — they have their own flows
    if user_role in ("admin", "super_admin"):
        from bot.handlers.admin.stats import admin_start
        return await admin_start(message)
        
    if user_role in ("dispatcher", "master"):
        return

    # New user — start registration
    await message.answer(
        t("welcome", "uz"),
        parse_mode="HTML",
        reply_markup=language_keyboard(),
    )
    await state.set_state(RegistrationStates.waiting_language)


# ── Language selection — works WITH or WITHOUT state ──────────────
# This handles both fresh state and cases where state was lost
@router.callback_query(F.data.startswith("lang:"))
async def process_language_selection(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user_role: str = "new",
    user_data=None,
):
    """Handle language selection — no strict state requirement."""
    lang = callback.data.split(":")[1]
    if lang not in ("uz", "ru"):
        await callback.answer()
        return

    # If user is changing language from settings
    if user_role == "client" and user_data:
        user_repo = UserRepo(session)
        language = Language.UZ if lang == "uz" else Language.RU
        await user_repo.update_language(user_data.telegram_id, language)
        await state.clear()
        await callback.message.edit_text(
            t("lang_selected", lang),
            parse_mode="HTML",
        )
        await callback.message.answer(
            t("main_menu", lang),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(lang),
        )
        await callback.answer()
        return

    # New user — continue registration
    await state.update_data(language=lang)
    await state.set_state(RegistrationStates.waiting_contact)

    await callback.message.edit_text(
        t("lang_selected", lang),
        parse_mode="HTML",
    )
    await callback.message.answer(
        t("share_contact", lang),
        parse_mode="HTML",
        reply_markup=share_contact_keyboard(lang),
    )
    await callback.answer()


# ── Contact sharing ───────────────────────────────────────────────

@router.message(
    RegistrationStates.waiting_contact,
    F.contact,
)
async def process_contact(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    """Handle contact sharing for registration."""
    contact = message.contact
    data = await state.get_data()
    lang = data.get("language", "uz")

    # Extract user info
    full_name = " ".join(
        filter(None, [contact.first_name, contact.last_name])
    ) or message.from_user.full_name
    phone = contact.phone_number

    # Ensure phone starts with +
    if not phone.startswith("+"):
        phone = f"+{phone}"

    # Create user in database
    user_repo = UserRepo(session)
    language = Language.UZ if lang == "uz" else Language.RU

    user, created = await user_repo.get_or_create(
        telegram_id=message.from_user.id,
        full_name=full_name,
        phone=phone,
        language=language,
    )

    if not created:
        await user_repo.update_language(message.from_user.id, language)

    await state.clear()

    safe_name = escape(full_name)
    safe_phone = escape(phone)
    await message.answer(
        t("registration_success", lang, name=safe_name, phone=safe_phone),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(lang),
    )


# ── Settings ──────────────────────────────────────────────────────

@router.message(F.text.in_(["⚙️ Sozlamalar", "⚙️ Настройки"]))
async def show_settings(
    message: Message,
    user_lang: str = "uz",
    user_data=None,
):
    """Show settings menu."""
    if not user_data:
        await message.answer(t("error", user_lang))
        return
    await message.answer(
        "⚙️ <b>Sozlamalar</b>" if user_lang == "uz" else "⚙️ <b>Настройки</b>",
        parse_mode="HTML",
        reply_markup=settings_keyboard(user_lang),
    )


@router.callback_query(F.data == "settings:language")
async def change_language_prompt(
    callback: CallbackQuery,
    state: FSMContext,
):
    """Show language selection from settings."""
    await callback.message.edit_text(
        "🌐 Tilni tanlang / Выберите язык:",
        reply_markup=language_keyboard(),
    )
    await callback.answer()
