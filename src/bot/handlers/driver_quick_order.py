import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, Message
from sqlalchemy import select

logger = logging.getLogger(__name__)

from src.bot.keyboards.driver import (
    BUTTONS,
    CANCEL_BUTTONS,
    START_ORDER_BUTTON,
    button,
    confirm_keyboard,
    issue_keyboard,
    issue_options,
    language_keyboard,
    normalize_language,
    request_location_keyboard,
    request_phone_keyboard,
    start_keyboard,
)
from src.bot.states.driver_order import DriverQuickOrderState
from src.core.config import get_settings
from src.db.models.user import User
from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService
from src.services.order_service import DriverOrderPayload, OrderService

router = Router(name="driver_quick_order")
settings = get_settings()


def _safe_message(callback: CallbackQuery) -> Message | None:
    """Return the real Message object or None if the message is inaccessible."""
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return None
    return msg

TEXT: dict[str, dict[str, str]] = {
    "choose_language": {
        "uz": "Tilni tanlang / Выберите язык:",
        "ru": "Tilni tanlang / Выберите язык:",
    },
    "welcome": {
        "uz": "AutoHelp.uz ga xush kelibsiz. Tez yordam uchun tugmani bosing.",
        "ru": "Добро пожаловать в AutoHelp.uz. Нажмите кнопку, чтобы вызвать помощь.",
    },
    "cancelled": {
        "uz": "Jarayon bekor qilindi.",
        "ru": "Процесс отменен.",
    },
    "main_menu": {
        "uz": "Asosiy menyu",
        "ru": "Главное меню",
    },
    "ask_issue": {
        "uz": "Nima muammo?",
        "ru": "Что случилось?",
    },
    "invalid_issue": {
        "uz": "Iltimos, ro'yxatdan muammo turini tanlang.",
        "ru": "Пожалуйста, выберите проблему из списка.",
    },
    "ask_phone": {
        "uz": "Telefon raqamingizni yuboring.",
        "ru": "Отправьте ваш номер телефона.",
    },
    "ask_own_phone": {
        "uz": "Iltimos, o'zingizning raqamingizni yuboring.",
        "ru": "Пожалуйста, отправьте свой номер телефона.",
    },
    "phone_missing": {
        "uz": "Telefon yuborilmadi. Qaytadan urinib ko'ring.",
        "ru": "Номер не получен. Попробуйте еще раз.",
    },
    "phone_hint": {
        "uz": "Iltimos, `{button}` tugmasi orqali yuboring.",
        "ru": "Пожалуйста, отправьте через кнопку `{button}`.",
    },
    "ask_location": {
        "uz": "Lokatsiyani yuboring.",
        "ru": "Отправьте вашу локацию.",
    },
    "location_missing": {
        "uz": "Lokatsiya yuborilmadi. Qaytadan urinib ko'ring.",
        "ru": "Локация не получена. Попробуйте еще раз.",
    },
    "location_hint": {
        "uz": "Iltimos, `{button}` tugmasi orqali yuboring.",
        "ru": "Пожалуйста, отправьте через кнопку `{button}`.",
    },
    "confirm_summary": {
        "uz": "Buyurtma tasdiqlansinmi?\n\nMuammo: {issue}\nTelefon: {phone}\nLokatsiya: {maps}",
        "ru": "Подтвердить заявку?\n\nПроблема: {issue}\nТелефон: {phone}\nЛокация: {maps}",
    },
    "order_cancelled": {
        "uz": "Buyurtma bekor qilindi.",
        "ru": "Заявка отменена.",
    },
    "user_missing": {
        "uz": "Foydalanuvchi aniqlanmadi.",
        "ru": "Пользователь не найден.",
    },
    "order_created": {
        "uz": "Buyurtmangiz qabul qilindi. ID: #{order_id}. Dispecher tez orada siz bilan bog'lanadi.",
        "ru": "Ваша заявка принята. ID: #{order_id}. Диспетчер скоро свяжется с вами.",
    },
}


def _t(language: str | None, key: str, **kwargs: object) -> str:
    lang = normalize_language(language)
    return TEXT[key][lang].format(**kwargs)


async def _get_saved_language(telegram_id: int | None) -> str:
    if telegram_id is None:
        return "uz"
    async with AsyncSessionFactory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        return normalize_language(user.language if user else None)


async def _state_language(state: FSMContext, user_id: int | None = None) -> str:
    data = await state.get_data()
    if data.get("language"):
        return normalize_language(str(data["language"]))
    return await _get_saved_language(user_id)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DriverQuickOrderState.language)
    await message.answer(TEXT["choose_language"]["uz"], reply_markup=language_keyboard())


@router.callback_query(DriverQuickOrderState.language, F.data.startswith("language:"))
async def choose_language(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    try:
        language = normalize_language(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri til tanlandi.", show_alert=True)
        return

    try:
        # 1. Database work FIRST. If this fails, we show the alert and STOP.
        if callback.from_user is not None:
            async with AsyncSessionFactory() as session:
                user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
                if user is None:
                    user = User(
                        telegram_id=callback.from_user.id,
                        full_name=callback.from_user.full_name,
                        language=language,
                    )
                    session.add(user)
                else:
                    user.language = language
                    if callback.from_user.full_name:
                        user.full_name = callback.from_user.full_name
                await session.commit()

        # 2. State work
        await state.clear()
        await state.update_data(language=language)

        # 3. UI work (only happens if DB was successful)
        msg = _safe_message(callback)
        if msg is not None:
            try:
                await msg.edit_text(_t(language, "welcome"))
            except Exception:
                pass
            await msg.answer(_t(language, "main_menu"), reply_markup=start_keyboard(language))

    except Exception as exc:
        logger.exception("CRITICAL: choose_language DB error: %s", exc)
        # This alert matches the screenshot. It happens if the database is down or tables are missing.
        await callback.answer("Texnik xatolik yuz berdi.", show_alert=True)
        return

    await callback.answer()


@router.message(Command("cancel"))
@router.message(F.text.in_(CANCEL_BUTTONS))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is None:
        return
    language = await _state_language(state, message.from_user.id if message.from_user else None)
    await state.clear()
    await message.answer(_t(language, "cancelled"), reply_markup=start_keyboard(language))


@router.message(Command("new_order"))
@router.message(F.text.in_(set(BUTTONS["start_order"].values()) | {START_ORDER_BUTTON}))
async def start_quick_order(message: Message, state: FSMContext) -> None:
    language = await _state_language(state, message.from_user.id if message.from_user else None)
    await state.clear()
    await state.update_data(language=language)
    await state.set_state(DriverQuickOrderState.issue)
    await message.answer(_t(language, "ask_issue"), reply_markup=issue_keyboard(language))


@router.message(DriverQuickOrderState.issue)
async def collect_issue(message: Message, state: FSMContext) -> None:
    language = await _state_language(state, message.from_user.id if message.from_user else None)
    issue = (message.text or "").strip()
    if issue not in issue_options(language):
        await message.answer(_t(language, "invalid_issue"), reply_markup=issue_keyboard(language))
        return

    await state.update_data(issue=issue, language=language)
    await state.set_state(DriverQuickOrderState.phone)
    await message.answer(
        _t(language, "ask_phone"),
        reply_markup=request_phone_keyboard(language),
    )


@router.message(DriverQuickOrderState.phone, F.contact)
async def collect_phone(message: Message, state: FSMContext) -> None:
    language = await _state_language(state, message.from_user.id if message.from_user else None)
    if message.from_user is None:
        await message.answer(_t(language, "user_missing"))
        return

    contact = message.contact
    if contact is None:
        await message.answer(_t(language, "phone_missing"))
        return

    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer(_t(language, "ask_own_phone"))
        return

    await state.update_data(phone=contact.phone_number, language=language)
    await state.set_state(DriverQuickOrderState.location)
    await message.answer(
        _t(language, "ask_location"),
        reply_markup=request_location_keyboard(language),
    )


@router.message(DriverQuickOrderState.phone)
async def phone_validation_hint(message: Message, state: FSMContext) -> None:
    language = await _state_language(state, message.from_user.id if message.from_user else None)
    await message.answer(
        _t(language, "phone_hint", button=button("phone", language)),
        parse_mode="Markdown",
        reply_markup=request_phone_keyboard(language),
    )


@router.message(DriverQuickOrderState.location, F.location)
async def collect_location(message: Message, state: FSMContext) -> None:
    language = await _state_language(state, message.from_user.id if message.from_user else None)
    location = message.location
    if location is None:
        await message.answer(_t(language, "location_missing"))
        return

    await state.update_data(latitude=location.latitude, longitude=location.longitude, language=language)
    data = await state.get_data()
    maps = f"https://maps.google.com/?q={data['latitude']},{data['longitude']}"
    summary = _t(
        language,
        "confirm_summary",
        issue=data["issue"],
        phone=data["phone"],
        maps=maps,
    )

    await state.set_state(DriverQuickOrderState.confirm)
    await message.answer(summary, reply_markup=confirm_keyboard(language))


@router.message(DriverQuickOrderState.location)
async def location_validation_hint(message: Message, state: FSMContext) -> None:
    language = await _state_language(state, message.from_user.id if message.from_user else None)
    await message.answer(
        _t(language, "location_hint", button=button("location", language)),
        parse_mode="Markdown",
        reply_markup=request_location_keyboard(language),
    )


@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_cancel")
async def cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    language = await _state_language(state, callback.from_user.id if callback.from_user else None)
    await state.clear()
    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(_t(language, "order_cancelled"))
        except Exception:
            pass
        await msg.answer(_t(language, "main_menu"), reply_markup=start_keyboard(language))
    await callback.answer()


@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_confirm")
async def confirm_order(callback: CallbackQuery, state: FSMContext) -> None:
    # 1. Immediate answer to stop the "clock" icon
    await callback.answer("Buyurtma yuborilmoqda... / Заявка отправляется...")
    
    language = await _state_language(state, callback.from_user.id if callback.from_user else None)
    if callback.from_user is None:
        await callback.answer(_t(language, "user_missing"), show_alert=True)
        return

    data = await state.get_data()
    language = normalize_language(str(data.get("language") or language))
    
    # Validation
    required_fields = {"phone", "issue", "latitude", "longitude"}
    if not required_fields.issubset(data):
        await callback.answer("Buyurtma ma'lumotlari to'liq emas. Qayta boshlang.", show_alert=True)
        await state.clear()
        return

    # 2. Provide immediate feedback and prevent double-clicks by updating the UI
    msg = _safe_message(callback)
    original_text = msg.text if msg else ""
    if msg:
        try:
            # We add a bold processing indicator to the top of the message
            await msg.edit_text(f"⏳ **Buyurtma yuborilmoqda...**\n\n{original_text}", parse_mode="Markdown")
        except Exception:
            pass

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            
            # Create the order in the database
            order = await service.create_driver_order(
                DriverOrderPayload(
                    client_telegram_id=callback.from_user.id,
                    full_name=callback.from_user.full_name,
                    language=language,
                    phone=data["phone"],
                    issue_label=data["issue"],
                    latitude=float(data["latitude"]),
                    longitude=float(data["longitude"]),
                )
            )

            # Notifications (each has its own internal try/except for resilience)
            alert_service = NotificationService(bot=callback.bot, settings=settings)
            
            # Notify Dispatcher(s)
            await alert_service.notify_new_order(
                order_id=order.id,
                client_telegram_id=callback.from_user.id,
                phone=data["phone"],
                issue=data["issue"],
                latitude=float(data["latitude"]),
                longitude=float(data["longitude"]),
            )
            
            # Notify Client (Confirmation video + text)
            await alert_service.notify_client_order_created(order)

        # 3. Success! Clear FSM state and update UI
        await state.clear()
        if msg:
            try:
                await msg.edit_text(_t(language, "order_created", order_id=order.id))
            except Exception:
                pass
            await msg.answer(_t(language, "main_menu"), reply_markup=start_keyboard(language))
        
    except Exception as exc:
        logger.exception("CRITICAL: confirm_order failed: %s", exc)
        if msg:
            try:
                # Restore original text with a clear error hint so user knows it failed
                error_hint = "\n\n❌ **Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.**"
                await msg.edit_text(
                    f"{original_text}{error_hint}", 
                    parse_mode="Markdown", 
                    reply_markup=confirm_keyboard(language)
                )
            except Exception:
                await callback.answer("Texnik xatolik yuz berdi. Qayta urinib ko'ring.", show_alert=True)
        return

    await callback.answer()
