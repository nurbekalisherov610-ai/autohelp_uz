"""
Client order flow handler (was: driver_quick_order).

Flow:
  /start → choose language → main menu
       → [Tez yordam chaqirish] → select issue → share phone → share location → confirm → ORDER CREATED
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    Message,
)
from sqlalchemy import select

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
from src.db.models.order import Order
from src.db.models.user import User
from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService
from src.services.order_service import DriverOrderPayload, OrderService

logger = logging.getLogger(__name__)
router = Router(name="driver_quick_order")
settings = get_settings()

# ── Localised UI text ─────────────────────────────────────────────────────────

TEXT: dict[str, dict[str, str]] = {
    "choose_language": {
        "uz": "🌐 Tilni tanlang:",
        "ru": "🌐 Выберите язык:",
    },
    "welcome": {
        "uz": (
            "👋 AutoHelp.uz ga xush kelibsiz!\n\n"
            "Yo'lda muammo yuz berdimi? Biz 24/7 yordamga tayyormiz. "
            "Quyidagi tugmalardan birini tanlang:"
        ),
        "ru": (
            "👋 Добро пожаловать в AutoHelp.uz!\n\n"
            "Возникли проблемы в дороге? Мы готовы помочь 24/7. "
            "Выберите один из вариантов ниже:"
        ),
    },
    "main_menu": {"uz": "Asosiy menyu", "ru": "Главное меню"},
    "ask_issue": {"uz": "🛠 Qanday muammo yuz berdi?", "ru": "🛠 Что случилось?"},
    "invalid_issue": {
        "uz": "Iltimos, ro'yxatdan muammo turini tanlang.",
        "ru": "Пожалуйста, выберите проблему из списка.",
    },
    "ask_phone": {
        "uz": "📞 Telefon raqamingizni yuboring (pastdagi tugmani bosing).",
        "ru": "📞 Отправьте ваш номер телефона (нажмите кнопку ниже).",
    },
    "ask_own_phone": {
        "uz": "Iltimos, faqat o'z raqamingizni yuboring.",
        "ru": "Пожалуйста, отправьте свой номер телефона.",
    },
    "phone_hint": {
        "uz": "📞 Raqam yuborish uchun '{button}' tugmasini bosing.",
        "ru": "📞 Нажмите кнопку '{button}' чтобы отправить номер.",
    },
    "ask_location": {
        "uz": "📍 Hozirgi joylashuvingizni yuboring.",
        "ru": "📍 Отправьте вашу текущую локацию.",
    },
    "location_hint": {
        "uz": "📍 Lokatsiya yuborish uchun '{button}' tugmasini bosing.",
        "ru": "📍 Нажмите кнопку '{button}' чтобы отправить локацию.",
    },
    "confirm_summary": {
        "uz": (
            "📋 <b>Buyurtma ma'lumotlari:</b>\n\n"
            "🛠 Muammo: <b>{issue}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n"
            '📍 <a href="{maps}">Lokatsiyani ko\'rish</a>\n\n'
            "✅ Tasdiqlaysizmi?"
        ),
        "ru": (
            "📋 <b>Данные заявки:</b>\n\n"
            "🛠 Проблема: <b>{issue}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n"
            '📍 <a href="{maps}">Посмотреть на карте</a>\n\n'
            "✅ Подтверждаете?"
        ),
    },
    "order_cancelled": {
        "uz": "❌ Buyurtma bekor qilindi.",
        "ru": "❌ Заявка отменена.",
    },
    "order_created": {
        "uz": (
            "✅ <b>Buyurtma #{order_id} qabul qilindi!</b>\n\n"
            "Dispecher tez orada siz bilan bog'lanadi. "
            "Ozgina sabr qiling. 🙏"
        ),
        "ru": (
            "✅ <b>Заявка #{order_id} принята!</b>\n\n"
            "Диспетчер скоро свяжется с вами. "
            "Пожалуйста, ожидайте. 🙏"
        ),
    },
    "cancelled": {
        "uz": "✅ Bekor qilindi. Asosiy menyuga qaytdingiz.",
        "ru": "✅ Отменено. Вы вернулись в главное меню.",
    },
    "about_text": {
        "uz": (
            "🚀 <b>AutoHelp.uz</b> — Yo'ldagi tezkor yordam xizmati.\n\n"
            "<b>Xizmatlarimiz:</b>\n"
            "• 🛠 Zavod bo'lmaydigan avtomobilga yordam\n"
            "• 🔋 Akkumulyator quvvati (perekurka)\n"
            "• 🎈 Balon almashtirish\n"
            "• 🔍 Texnik diagnostika\n\n"
            "24/7 ishlaydi. Joyingizdan chiqmang — usta siz bor joyga keladi!"
        ),
        "ru": (
            "🚀 <b>AutoHelp.uz</b> — Служба быстрой помощи на дорогах.\n\n"
            "<b>Наши услуги:</b>\n"
            "• 🛠 Помощь, если машина не заводится\n"
            "• 🔋 Зарядка аккумулятора (прикуривание)\n"
            "• 🎈 Замена колеса\n"
            "• 🔍 Техническая диагностика\n\n"
            "Работаем 24/7. Мастер приедет к вам!"
        ),
    },
    "no_active_orders": {
        "uz": "Sizda hozircha buyurtmalar yo'q.",
        "ru": "У вас пока нет заказов.",
    },
    "data_incomplete": {
        "uz": "Ma'lumotlar to'liq emas. Iltimos, qaytadan boshlang.",
        "ru": "Данные не полные. Пожалуйста, начните заново.",
    },
}


def _t(language: str | None, key: str, **kwargs) -> str:
    return TEXT[key][normalize_language(language)].format(**kwargs)


def _safe_message(callback: CallbackQuery) -> Message | None:
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return None
    return msg


async def _get_current_language(state: FSMContext, user_id: int) -> str:
    data = await state.get_data()
    if "language" in data:
        return normalize_language(data["language"])
    # Fall back to DB-stored language
    async with AsyncSessionFactory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        return normalize_language(user.language if user else None)


# ── Handlers ──────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DriverQuickOrderState.language)
    await message.answer(
        "🌐 Tilni tanlang / Выберите язык:",
        reply_markup=language_keyboard(),
    )


@router.callback_query(F.data.startswith("language:"))
async def choose_language(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None:
        await callback.answer("Foydalanuvchi ma'lumotlari olinmadi.", show_alert=True)
        return

    try:
        language = normalize_language(callback.data.split(":")[1])

        async with AsyncSessionFactory() as session:
            user = await session.scalar(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            if not user:
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
    except Exception as exc:
        logger.exception(
            "DB error in choose_language for user %s: %s", callback.from_user.id, exc
        )
        await callback.answer("Texnik xatolik. Qayta urinib ko'ring.", show_alert=True)
        return

    await state.clear()
    await state.update_data(language=language)

    msg = _safe_message(callback)
    if msg:
        try:
            await msg.edit_text(_t(language, "welcome"), parse_mode="HTML")
        except Exception:
            pass
        await msg.answer(
            _t(language, "main_menu"), reply_markup=start_keyboard(language)
        )
    await callback.answer()


@router.message(F.text.in_(CANCEL_BUTTONS))
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await state.clear()
    await state.update_data(language=lang)
    await message.answer(_t(lang, "cancelled"), reply_markup=start_keyboard(lang))


@router.message(F.text.in_(set(BUTTONS["change_lang"].values())))
async def cmd_change_lang(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DriverQuickOrderState.language)
    await message.answer("🌐 Tilni tanlang / Выберите язык:", reply_markup=language_keyboard())


@router.message(F.text.in_(set(BUTTONS["about"].values())))
async def cmd_about(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await message.answer(_t(lang, "about_text"), parse_mode="HTML")


@router.message(F.text.in_(set(BUTTONS["order_status"].values())))
async def cmd_order_status(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    async with AsyncSessionFactory() as session:
        rows = await session.execute(
            select(Order)
            .join(User)
            .where(User.telegram_id == message.from_user.id)
            .order_by(Order.created_at.desc())
            .limit(5)
        )
        orders = rows.scalars().all()

    if not orders:
        await message.answer(_t(lang, "no_active_orders"))
        return

    lines = ["📋 <b>So'nggi buyurtmalar:</b>\n"]
    for o in orders:
        lines.append(
            f"• #{o.id} — <b>{o.status.name}</b> — {o.issue_label} — {o.created_at.strftime('%H:%M %d.%m')}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text.in_(set(BUTTONS["start_order"].values()) | {START_ORDER_BUTTON}))
@router.message(Command("new_order"))
async def start_quick_order(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await state.clear()
    await state.update_data(language=lang)
    await state.set_state(DriverQuickOrderState.issue)
    await message.answer(_t(lang, "ask_issue"), reply_markup=issue_keyboard(lang))


@router.message(DriverQuickOrderState.issue)
async def collect_issue(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    issue = (message.text or "").strip()
    if issue not in issue_options(lang):
        await message.answer(_t(lang, "invalid_issue"), reply_markup=issue_keyboard(lang))
        return
    await state.update_data(issue=issue)
    await state.set_state(DriverQuickOrderState.phone)
    await message.answer(_t(lang, "ask_phone"), reply_markup=request_phone_keyboard(lang))


@router.message(DriverQuickOrderState.phone, F.contact)
async def collect_phone(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    contact = message.contact
    # Ensure the contact belongs to the sender (not someone else's number)
    if not contact or (contact.user_id and contact.user_id != message.from_user.id):
        await message.answer(
            _t(lang, "ask_own_phone"), reply_markup=request_phone_keyboard(lang)
        )
        return
    await state.update_data(phone=contact.phone_number)
    await state.set_state(DriverQuickOrderState.location)
    await message.answer(_t(lang, "ask_location"), reply_markup=request_location_keyboard(lang))


@router.message(DriverQuickOrderState.phone)
async def phone_hint(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await message.answer(
        _t(lang, "phone_hint", button=button("phone", lang)),
        reply_markup=request_phone_keyboard(lang),
    )


@router.message(DriverQuickOrderState.location, F.location)
async def collect_location(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await state.update_data(
        latitude=message.location.latitude,
        longitude=message.location.longitude,
    )
    data = await state.get_data()
    maps = f"https://maps.google.com/?q={data['latitude']},{data['longitude']}"
    summary = _t(
        lang,
        "confirm_summary",
        issue=data["issue"],
        phone=data["phone"],
        maps=maps,
    )
    await state.set_state(DriverQuickOrderState.confirm)
    await message.answer(summary, reply_markup=confirm_keyboard(lang), parse_mode="HTML")


@router.message(DriverQuickOrderState.location)
async def location_hint(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await message.answer(
        _t(lang, "location_hint", button=button("location", lang)),
        reply_markup=request_location_keyboard(lang),
    )


@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await _get_current_language(state, callback.from_user.id)
    await state.clear()
    await state.update_data(language=lang)

    msg = _safe_message(callback)
    if msg:
        try:
            await msg.edit_text(_t(lang, "order_cancelled"), parse_mode="HTML")
        except Exception:
            pass
        await msg.answer(_t(lang, "main_menu"), reply_markup=start_keyboard(lang))
    await callback.answer()


@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_confirm")
async def confirm_order(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await _get_current_language(state, callback.from_user.id)
    data = await state.get_data()

    required_keys = ["phone", "issue", "latitude", "longitude"]
    if not all(k in data for k in required_keys):
        await callback.answer(_t(lang, "data_incomplete"), show_alert=True)
        return

    msg = _safe_message(callback)
    # Show a "sending…" indicator by editing the message
    if msg:
        try:
            await msg.edit_text("⏳ Buyurtma yuborilmoqda…")
        except Exception:
            pass

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.create_driver_order(
                DriverOrderPayload(
                    client_telegram_id=callback.from_user.id,
                    full_name=callback.from_user.full_name,
                    language=lang,
                    phone=data["phone"],
                    issue_label=data["issue"],
                    latitude=float(data["latitude"]),
                    longitude=float(data["longitude"]),
                )
            )

            ns = NotificationService(bot=callback.bot, settings=settings)

            # 1. Broadcast new order to all dispatcher targets
            await ns.notify_new_order(
                order_id=order.id,
                client_telegram_id=callback.from_user.id,
                phone=data["phone"],
                issue=data["issue"],
                latitude=float(data["latitude"]),
                longitude=float(data["longitude"]),
            )

            # 2. Confirm to client (text + delayed video note)
            await ns.notify_client_order_created(
                order_id=order.id,
                client_telegram_id=callback.from_user.id,
                language=lang,
            )

        # Clear FSM state but keep language for future use
        await state.clear()
        await state.update_data(language=lang)

        if msg:
            try:
                await msg.edit_text(
                    _t(lang, "order_created", order_id=order.id), parse_mode="HTML"
                )
            except Exception:
                pass
            await msg.answer(_t(lang, "main_menu"), reply_markup=start_keyboard(lang))

    except Exception as exc:
        logger.exception("confirm_order failed for user %s: %s", callback.from_user.id, exc)
        await callback.answer(
            "Texnik xatolik yuz berdi. Iltimos, 1-2 daqiqadan keyin qayta urinib ko'ring.",
            show_alert=True,
        )
        return

    await callback.answer()
