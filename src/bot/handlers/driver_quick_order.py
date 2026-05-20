"""
Client order flow. Steps:
  /start → language → main menu
  → "Tez yordam" → issue → phone → location → confirm → ORDER CREATED
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from src.bot.keyboards.driver import (
    BUTTONS,
    CANCEL_BUTTONS,
    button,
    confirm_keyboard,
    issue_keyboard,
    issue_options,
    language_keyboard,
    normalize_language,
    request_location_keyboard,
    request_phone_keyboard,
    start_keyboard,
    admin_keyboard,
    dispatcher_keyboard,
    master_keyboard,
)
from src.bot.states.driver_order import DriverQuickOrderState
from src.bot.utils.permissions import is_admin, is_dispatcher, is_master
from src.core.config import get_settings
from src.db.models.user import User
from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService
from src.services.order_service import DriverOrderPayload, OrderService
from src.db.enums import OrderStatus

logger = logging.getLogger(__name__)
router = Router(name="driver_quick_order")
settings = get_settings()

# ── Localised text ────────────────────────────────────────────────────────────

_T: dict[str, dict[str, str]] = {
    "welcome": {
        "uz": "👋 <b>AutoHelp.uz</b> ga xush kelibsiz!\n\nYo'lda muammo bo'ldimi? 24/7 yordamga tayyormiz.",
        "ru": "👋 Добро пожаловать в <b>AutoHelp.uz</b>!\n\nПроблемы в дороге? Мы готовы 24/7.",
    },
    "main_menu": {"uz": "Asosiy menyu:", "ru": "Главное меню:"},
    "ask_issue": {"uz": "🛠 Qanday muammo yuz berdi?", "ru": "🛠 Что случилось с автомобилем?"},
    "invalid_issue": {
        "uz": "Iltimos, ro'yxatdan muammo turini tanlang.",
        "ru": "Пожалуйста, выберите проблему из списка.",
    },
    "ask_phone": {
        "uz": "📞 Telefon raqamingizni yuboring:",
        "ru": "📞 Отправьте ваш номер телефона:",
    },
    "wrong_phone": {
        "uz": "Iltimos, faqat o'z raqamingizni yuboring.",
        "ru": "Пожалуйста, отправьте свой номер телефона.",
    },
    "phone_hint": {
        "uz": "📞 Pastdagi tugmani bosib raqam yuboring.",
        "ru": "📞 Нажмите кнопку ниже чтобы отправить номер.",
    },
    "ask_location": {
        "uz": "📍 Hozirgi joylashuvingizni yuboring:",
        "ru": "📍 Отправьте вашу текущую геолокацию:",
    },
    "location_hint": {
        "uz": "📍 Pastdagi tugmani bosib lokatsiya yuboring.",
        "ru": "📍 Нажмите кнопку ниже чтобы отправить локацию.",
    },
    "confirm_summary": {
        "uz": (
            "📋 <b>Buyurtma ma'lumotlari:</b>\n\n"
            "🛠 Muammo: <b>{issue}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n"
            '📍 <a href="{maps}">Lokatsiyani ko\'rish</a>\n\n'
            "Tasdiqlaysizmi?"
        ),
        "ru": (
            "📋 <b>Данные заявки:</b>\n\n"
            "🛠 Проблема: <b>{issue}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n"
            '📍 <a href="{maps}">Посмотреть на карте</a>\n\n'
            "Подтверждаете?"
        ),
    },
    "order_cancelled": {
        "uz": "❌ Buyurtma bekor qilindi.",
        "ru": "❌ Заявка отменена.",
    },
    "cancelled": {
        "uz": "Bekor qilindi.",
        "ru": "Отменено.",
    },
    "incomplete": {
        "uz": "Ma'lumotlar to'liq emas. /start bilan qayta boshlang.",
        "ru": "Данные неполные. Начните заново с /start.",
    },
    "about": {
        "uz": (
            "🚀 <b>AutoHelp.uz</b> — Yo'ldagi tezkor yordam.\n\n"
            "• 🛠 Zavod bo'lmaydi\n"
            "• 🔋 Akkumulyator quvvati\n"
            "• 🎈 Balon almashtirish\n"
            "• 🔍 Diagnostika\n\n"
            "24/7 ishlaydi!"
        ),
        "ru": (
            "🚀 <b>AutoHelp.uz</b> — Быстрая помощь на дороге.\n\n"
            "• 🛠 Машина не заводится\n"
            "• 🔋 Зарядка аккумулятора\n"
            "• 🎈 Замена колеса\n"
            "• 🔍 Диагностика\n\n"
            "Работаем 24/7!"
        ),
    },
    "no_orders": {
        "uz": "Sizda hozircha buyurtmalar yo'q.",
        "ru": "У вас пока нет заказов.",
    },
    "orders_header": {
        "uz": "📋 <b>So'nggi buyurtmalar:</b>\n",
        "ru": "📋 <b>Последние заказы:</b>\n",
    },
}


def _t(lang: str | None, key: str, **kw) -> str:
    return _T[key][normalize_language(lang)].format(**kw)


def _msg_safe(cb: CallbackQuery) -> Message | None:
    if cb.message is None or isinstance(cb.message, InaccessibleMessage):
        return None
    return cb.message


async def _get_lang(state: FSMContext, user_id: int) -> str:
    data = await state.get_data()
    if lang := data.get("language"):
        return normalize_language(lang)
    async with AsyncSessionFactory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        return normalize_language(user.language if user else None)


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    uid = message.from_user.id if message.from_user else None
    
    # Check if the user is registered as master in database
    is_db_master = False
    try:
        async with AsyncSessionFactory() as session:
            user = await session.scalar(select(User).where(User.telegram_id == uid))
            if user and user.is_master:
                is_db_master = True
    except Exception as exc:
        logger.error("DB check failed in start: %s", exc)

    if is_admin(uid):
        await message.answer(
            "👑 <b>Admin boshqaruv paneli</b>\n\n"
            "Siz tizimda <b>Admin</b> roliga egasiz. Quyidagi tugmalar orqali botni boshqarishingiz va hisobotlarni olishingiz mumkin:",
            reply_markup=admin_keyboard(),
            parse_mode="HTML",
        )
        return

    if is_dispatcher(uid):
        await message.answer(
            "📞 <b>Dispetcher boshqaruv paneli</b>\n\n"
            "Siz tizimda <b>Dispetcher</b> roliga egasiz. Quyidagi tugmalar orqali buyurtmalarni ko'rishingiz va taqsimlashingiz mumkin:",
            reply_markup=dispatcher_keyboard(),
            parse_mode="HTML",
        )
        return

    if is_master(uid) or is_db_master:
        await message.answer(
            "👨‍🔧 <b>Master boshqaruv paneli</b>\n\n"
            "Siz tizimda <b>Master</b> roliga egasiz. Quyidagi tugma orqali sizga biriktirilgan buyurtmalarni boshqarishingiz mumkin:",
            reply_markup=master_keyboard(),
            parse_mode="HTML",
        )
        return

    # Normal driver client flow
    await state.set_state(DriverQuickOrderState.language)
    await message.answer(
        "🌐 Tilni tanlang / Выберите язык:",
        reply_markup=language_keyboard(),
    )


# ── Language selection ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("language:"))
async def cb_choose_language(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()  # Dismiss button spinner immediately
    lang = normalize_language((callback.data or "").split(":")[-1])

    # Persist language to DB
    try:
        async with AsyncSessionFactory() as session:
            user = await session.scalar(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            if user:
                user.language = lang
                if callback.from_user.full_name:
                    user.full_name = callback.from_user.full_name
            else:
                session.add(User(
                    telegram_id=callback.from_user.id,
                    full_name=callback.from_user.full_name,
                    language=lang,
                ))
            await session.commit()
    except Exception as exc:
        logger.error("Language save error for %s: %s", callback.from_user.id, exc)

    await state.clear()
    await state.update_data(language=lang)

    msg = _msg_safe(callback)
    if msg:
        try:
            await msg.edit_text(_t(lang, "welcome"), parse_mode="HTML")
        except Exception:
            pass
        await msg.answer(_t(lang, "main_menu"), reply_markup=start_keyboard(lang))


# ── Cancel ────────────────────────────────────────────────────────────────────

@router.message(F.text.in_(CANCEL_BUTTONS))
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    lang = await _get_lang(state, message.from_user.id)
    await state.clear()
    await state.update_data(language=lang)
    await message.answer(_t(lang, "cancelled"), reply_markup=start_keyboard(lang))


# ── Change language ───────────────────────────────────────────────────────────

@router.message(F.text.in_(set(BUTTONS["change_lang"].values())))
async def cmd_change_lang(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DriverQuickOrderState.language)
    await message.answer("🌐 Tilni tanlang / Выберите язык:", reply_markup=language_keyboard())


# ── About ─────────────────────────────────────────────────────────────────────

@router.message(F.text.in_(set(BUTTONS["about"].values())))
async def cmd_about(message: Message, state: FSMContext) -> None:
    lang = await _get_lang(state, message.from_user.id)
    await message.answer(_t(lang, "about"), parse_mode="HTML")


# ── Order status ──────────────────────────────────────────────────────────────

@router.message(F.text.in_(set(BUTTONS["order_status"].values())))
async def cmd_my_orders(message: Message, state: FSMContext) -> None:
    from src.db.models.order import Order as OrderModel
    lang = await _get_lang(state, message.from_user.id)
    async with AsyncSessionFactory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if not user:
            await message.answer(_t(lang, "no_orders"))
            return
        orders = list(await session.scalars(
            select(OrderModel)
            .where(OrderModel.client_id == user.id)
            .order_by(OrderModel.created_at.desc())
            .limit(5)
        ))

    if not orders:
        await message.answer(_t(lang, "no_orders"))
        return

    active_statuses = {
        OrderStatus.NEW, OrderStatus.ASSIGNED, OrderStatus.ACCEPTED,
        OrderStatus.ON_THE_WAY, OrderStatus.ARRIVED, OrderStatus.IN_PROGRESS
    }

    history_lines = [_t(lang, "orders_header")]
    has_history = False

    for o in orders:
        text = f"• #{o.id} — <b>{o.status.name}</b> — {o.issue_label} — {o.created_at.strftime('%H:%M %d.%m')}"
        if o.status in active_statuses:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"client_cancel:{o.id}")
            ]])
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
        else:
            history_lines.append(text)
            has_history = True

    if has_history:
        await message.answer("\n".join(history_lines), parse_mode="HTML")

@router.callback_query(F.data.startswith("client_cancel:"))
async def cb_client_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    # 1. Answer immediately to stop spinner
    await callback.answer()

    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            # Get assigned master before cancelling
            order = await service.get_order(order_id)
            master_id = order.assigned_master_telegram_id
            
            await service.client_cancel_order(order_id, callback.from_user.id)

        # Edit the original message
        msg = _msg_safe(callback)
        if msg:
            try:
                await msg.edit_text(
                    f"❌ Buyurtma #{order_id} bekor qilindi.",
                    reply_markup=None
                )
            except Exception:
                pass
            
        # Notify dispatcher
        if settings.resolved_dispatcher_chat_id:
            try:
                await callback.bot.send_message(
                    chat_id=settings.resolved_dispatcher_chat_id,
                    text=f"⚠️ <b>Mijoz buyurtmani bekor qildi:</b> #{order_id}",
                    parse_mode="HTML"
                )
            except Exception as exc:
                logger.warning("Failed to notify dispatcher of client cancel: %s", exc)
                
        # Notify master if assigned
        if master_id:
            try:
                await callback.bot.send_message(
                    chat_id=master_id,
                    text=f"⚠️ <b>Mijoz buyurtmani bekor qildi:</b> #{order_id}\nBoshqa buyurtmalarni kutishingiz mumkin.",
                    parse_mode="HTML"
                )
            except Exception as exc:
                logger.warning("Failed to notify master of client cancel: %s", exc)
                
    except Exception as exc:
        logger.error("Client cancel error: %s", exc)
        await callback.answer("Xatolik yuz berdi. Balki buyurtma allaqachon yopilgan.", show_alert=True)



# ── Start order ───────────────────────────────────────────────────────────────

@router.message(F.text.in_(set(BUTTONS["start_order"].values())))
@router.message(Command("new_order"))
async def start_quick_order(message: Message, state: FSMContext) -> None:
    lang = await _get_lang(state, message.from_user.id)
    await state.clear()
    await state.update_data(language=lang)
    await state.set_state(DriverQuickOrderState.issue)
    await message.answer(_t(lang, "ask_issue"), reply_markup=issue_keyboard(lang))


# ── Issue ─────────────────────────────────────────────────────────────────────

@router.message(DriverQuickOrderState.issue)
async def collect_issue(message: Message, state: FSMContext) -> None:
    lang = await _get_lang(state, message.from_user.id)
    issue = (message.text or "").strip()

    # Check if they clicked cancel or a menu command/button
    if issue in CANCEL_BUTTONS or issue == "/cancel":
        await state.clear()
        await state.update_data(language=lang)
        await message.answer(_t(lang, "cancelled"), reply_markup=start_keyboard(lang))
        return

    if issue == "/start":
        await cmd_start(message, state)
        return

    # If they typed/clicked something that matches other menu items, reset state and process it
    for key, values in BUTTONS.items():
        if issue in values.values():
            await state.clear()
            await state.update_data(language=lang)
            if key == "start_order":
                await start_quick_order(message, state)
            elif key == "order_status":
                await cmd_my_orders(message, state)
            elif key == "about":
                await cmd_about(message, state)
            elif key == "change_lang":
                await cmd_change_lang(message, state)
            return

    # If the issue is not in options, we accept it as a custom issue instead of rejecting!
    if len(issue) > 100:
        issue = issue[:97] + "..."

    await state.update_data(issue=issue)
    await state.set_state(DriverQuickOrderState.phone)
    await message.answer(_t(lang, "ask_phone"), reply_markup=request_phone_keyboard(lang))


# ── Phone ─────────────────────────────────────────────────────────────────────

@router.message(DriverQuickOrderState.phone, F.contact)
async def collect_phone(message: Message, state: FSMContext) -> None:
    lang = await _get_lang(state, message.from_user.id)
    contact = message.contact
    if not contact or (contact.user_id and contact.user_id != message.from_user.id):
        await message.answer(_t(lang, "wrong_phone"), reply_markup=request_phone_keyboard(lang))
        return
    await state.update_data(phone=contact.phone_number)
    await state.set_state(DriverQuickOrderState.location)
    await message.answer(_t(lang, "ask_location"), reply_markup=request_location_keyboard(lang))


@router.message(DriverQuickOrderState.phone)
async def phone_hint(message: Message, state: FSMContext) -> None:
    lang = await _get_lang(state, message.from_user.id)
    text = (message.text or "").strip()

    if text in CANCEL_BUTTONS or text == "/cancel":
        await state.clear()
        await state.update_data(language=lang)
        await message.answer(_t(lang, "cancelled"), reply_markup=start_keyboard(lang))
        return

    if text == "/start":
        await cmd_start(message, state)
        return

    # If they typed/clicked something that matches other menu items, reset state and process it
    for key, values in BUTTONS.items():
        if text in values.values():
            await state.clear()
            await state.update_data(language=lang)
            if key == "start_order":
                await start_quick_order(message, state)
            elif key == "order_status":
                await cmd_my_orders(message, state)
            elif key == "about":
                await cmd_about(message, state)
            elif key == "change_lang":
                await cmd_change_lang(message, state)
            return

    await message.answer(_t(lang, "phone_hint"), reply_markup=request_phone_keyboard(lang))


# ── Location ──────────────────────────────────────────────────────────────────

@router.message(DriverQuickOrderState.location, F.location)
async def collect_location(message: Message, state: FSMContext) -> None:
    lang = await _get_lang(state, message.from_user.id)
    await state.update_data(
        latitude=message.location.latitude,
        longitude=message.location.longitude,
    )
    data = await state.get_data()
    maps = f"https://maps.google.com/?q={data['latitude']},{data['longitude']}"
    await state.set_state(DriverQuickOrderState.confirm)
    await message.answer(
        _t(lang, "confirm_summary", issue=data["issue"], phone=data["phone"], maps=maps),
        reply_markup=confirm_keyboard(lang),
        parse_mode="HTML",
    )


@router.message(DriverQuickOrderState.location)
async def location_hint(message: Message, state: FSMContext) -> None:
    lang = await _get_lang(state, message.from_user.id)
    text = (message.text or "").strip()

    if text in CANCEL_BUTTONS or text == "/cancel":
        await state.clear()
        await state.update_data(language=lang)
        await message.answer(_t(lang, "cancelled"), reply_markup=start_keyboard(lang))
        return

    if text == "/start":
        await cmd_start(message, state)
        return

    # If they typed/clicked something that matches other menu items, reset state and process it
    for key, values in BUTTONS.items():
        if text in values.values():
            await state.clear()
            await state.update_data(language=lang)
            if key == "start_order":
                await start_quick_order(message, state)
            elif key == "order_status":
                await cmd_my_orders(message, state)
            elif key == "about":
                await cmd_about(message, state)
            elif key == "change_lang":
                await cmd_change_lang(message, state)
            return

    await message.answer(_t(lang, "location_hint"), reply_markup=request_location_keyboard(lang))


# ── Confirm callbacks ─────────────────────────────────────────────────────────

@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_cancel")
async def cb_cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await _get_lang(state, callback.from_user.id)
    await state.clear()
    await state.update_data(language=lang)
    msg = _msg_safe(callback)
    if msg:
        try:
            await msg.edit_text(_t(lang, "order_cancelled"))
        except Exception:
            pass
        await msg.answer(_t(lang, "main_menu"), reply_markup=start_keyboard(lang))
    await callback.answer()


@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_confirm")
async def cb_confirm_order(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await _get_lang(state, callback.from_user.id)
    data = await state.get_data()

    # Debounce check
    if data.get("submitting"):
        await callback.answer()
        return

    # Validate all required data is present
    for key in ("phone", "issue", "latitude", "longitude"):
        if key not in data:
            await callback.answer(_t(lang, "incomplete"), show_alert=True)
            return

    # Set submitting lock
    await state.update_data(submitting=True)
    await callback.answer()  # Dismiss button spinner immediately

    msg = _msg_safe(callback)
    if msg:
        try:
            await msg.edit_text("⏳ Buyurtma yuborilmoqda…" if lang == "uz" else "⏳ Отправляем заявку…")
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
            order_id = order.id  # capture before session closes

        ns = NotificationService(bot=callback.bot, settings=settings)

        # 1. Notify all dispatchers
        await ns.notify_new_order(
            order_id=order_id,
            client_telegram_id=callback.from_user.id,
            phone=data["phone"],
            issue=data["issue"],
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
        )

        # 2. Confirm to client (text immediately + video after 10s)
        await ns.notify_client_order_created(
            order_id=order_id,
            client_telegram_id=callback.from_user.id,
            language=lang,
        )

        # Clear FSM, keep language
        await state.clear()
        await state.update_data(language=lang)

        if msg:
            try:
                await msg.edit_text(
                    (
                        f"✅ <b>Buyurtma #{order_id} qabul qilindi!</b>\n\n"
                        "Dispecher tez orada siz bilan bog'lanadi. 🙏"
                        if lang == "uz"
                        else
                        f"✅ <b>Заявка #{order_id} принята!</b>\n\n"
                        "Диспетчер скоро свяжется с вами. 🙏"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
            await msg.answer(_t(lang, "main_menu"), reply_markup=start_keyboard(lang))

    except Exception as exc:
        logger.exception("Order creation failed for user %s: %s", callback.from_user.id, exc)
        # Release the submitting lock so they can retry, but keep FSM state intact!
        await state.update_data(submitting=False)
        if msg:
            try:
                await msg.edit_text(
                    (
                        "❌ <b>Texnik xatolik yuz berdi.</b>\n\nIltimos, tasdiqlash tugmasini qayta bosing."
                        if lang == "uz"
                        else
                        "❌ <b>Произошла техническая ошибка.</b>\n\nПожалуйста, нажмите кнопку подтверждения снова."
                    ),
                    reply_markup=confirm_keyboard(lang),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return


@router.message(DriverQuickOrderState.confirm)
async def confirm_text_handler(message: Message, state: FSMContext) -> None:
    lang = await _get_lang(state, message.from_user.id)
    text = (message.text or "").strip()

    if text in CANCEL_BUTTONS or text == "/cancel":
        await state.clear()
        await state.update_data(language=lang)
        await message.answer(_t(lang, "cancelled"), reply_markup=start_keyboard(lang))
        return

    if text == "/start":
        await cmd_start(message, state)
        return

    # If they typed/clicked something that matches other menu items, reset state and process it
    for key, values in BUTTONS.items():
        if text in values.values():
            await state.clear()
            await state.update_data(language=lang)
            if key == "start_order":
                await start_quick_order(message, state)
            elif key == "order_status":
                await cmd_my_orders(message, state)
            elif key == "about":
                await cmd_about(message, state)
            elif key == "change_lang":
                await cmd_change_lang(message, state)
            return

    # Guide them politely to use the inline buttons
    guide = (
        "⚠️ Buyurtmani tasdiqlash uchun, iltimos, pastdagi <b>✅ Tasdiqlash</b> yoki <b>❌ Bekor qilish</b> tugmalaridan birini bosing."
        if lang == "uz"
        else
        "⚠️ Для подтверждения заказа, пожалуйста, нажмите кнопку <b>✅ Подтвердить</b> или <b>❌ Отменить</b> ниже."
    )
    await message.answer(guide, parse_mode="HTML")


@router.message(F.text)
async def default_message_fallback(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is not None:
        # If they are in another state, we let other handlers process it
        return

    # If the text is a command (starts with /), let the command handlers catch it
    text = (message.text or "").strip()
    if text.startswith("/"):
        return

    # If it matches any of the main menu buttons, let those handlers catch it
    for values in BUTTONS.values():
        if text in values.values():
            return

    # Treat this text as the issue description and start order flow instantly!
    lang = await _get_lang(state, message.from_user.id)
    
    # Save the issue
    if len(text) > 100:
        text = text[:97] + "..."
        
    await state.clear()
    await state.update_data(language=lang, issue=text)
    await state.set_state(DriverQuickOrderState.phone)
    
    # Send quick confirmation and ask for phone
    await message.answer(
        f"🛠 <b>Muammo qabul qilindi:</b> {text}\n\n" + _t(lang, "ask_phone")
        if lang == "uz"
        else
        f"🛠 <b>Проблема принята:</b> {text}\n\n" + _t(lang, "ask_phone"),
        reply_markup=request_phone_keyboard(lang),
        parse_mode="HTML"
    )


