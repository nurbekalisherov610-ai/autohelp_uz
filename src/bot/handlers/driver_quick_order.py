import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, Message, InlineKeyboardButton, InlineKeyboardMarkup
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


def _safe_message(callback: CallbackQuery) -> Message | None:
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return None
    return msg

TEXT = {
    "choose_language": {"uz": "Tilni tanlang / Выберите язык:", "ru": "Tilni tanlang / Выберите язык:"},
    "welcome": {"uz": "AutoHelp.uz ga xush kelibsiz. Tez yordam uchun quyidagi tugmalardan birini tanlang.", "ru": "Добро пожаловать в AutoHelp.uz. Выберите одну из кнопок ниже."},
    "cancelled": {"uz": "Jarayon bekor qilindi.", "ru": "Процесс отменен."},
    "main_menu": {"uz": "Asosiy menyu", "ru": "Главное меню"},
    "ask_issue": {"uz": "Nima muammo yuz berdi?", "ru": "Что случилось?"},
    "invalid_issue": {"uz": "Iltimos, ro'yxatdan muammo turini tanlang.", "ru": "Пожалуйста, выберите проблему из списка."},
    "ask_phone": {"uz": "Telefon raqamingizni yuboring (pastdagi tugmani bosing).", "ru": "Отправьте ваш номер телефона (нажмите кнопку ниже)."},
    "ask_own_phone": {"uz": "Iltimos, faqat o'zingizning raqamingizni yuboring.", "ru": "Пожалуйста, отправьте свой номер телефона."},
    "phone_missing": {"uz": "Telefon raqami olinmadi.", "ru": "Номер не получен."},
    "phone_hint": {"uz": "Iltimos, '{button}' tugmasi orqali yuboring.", "ru": "Пожалуйста, используйте кнопку '{button}'."},
    "ask_location": {"uz": "Hozirgi turgan lokatsiyangizni yuboring.", "ru": "Отправьте вашу текущую локацию."},
    "location_missing": {"uz": "Lokatsiya olinmadi.", "ru": "Локация не получена."},
    "location_hint": {"uz": "Iltimos, '{button}' tugmasi orqali yuboring.", "ru": "Пожалуйста, используйте кнопку '{button}'."},
    "confirm_summary": {"uz": "Buyurtma ma'lumotlari:\n\n🛠 Muammo: {issue}\n📞 Tel: {phone}\n📍 Lokatsiya: [Xaritada ko'rish]({maps})", "ru": "Данные заявки:\n\n🛠 Проблема: {issue}\n📞 Тел: {phone}\n📍 Локация: [Посмотреть на карте]({maps})"},
    "order_cancelled": {"uz": "Buyurtma bekor qilindi.", "ru": "Заявка отменена."},
    "user_missing": {"uz": "Foydalanuvchi aniqlanmadi.", "ru": "Пользователь не найден."},
    "order_created": {"uz": "✅ Buyurtmangiz qabul qilindi. ID: #{order_id}\nDispecher tez orada siz bilan bog'lanadi.", "ru": "✅ Ваша заявка принята. ID: #{order_id}\nДиспетчер скоро свяжется с вами."},
    "about_text": {
        "uz": "🚀 **AutoHelp.uz** — Yo'ldagi tezkor yordam xizmati.\n\nBizning xizmatlar:\n• Avtomobil zavod bo'lmaganda yordam\n• Akkumulyator quvvati (perekurka)\n• Balon almashtirish\n• Texnik diagnostika",
        "ru": "🚀 **AutoHelp.uz** — Служба быстрой помощи на дорогах.\n\nНаши услуги:\n• Помощь, если машина не заводится\n• Зарядка аккумулятора (прикуривание)\n• Замена колеса\n• Техническая диагностика"
    },
    "no_active_orders": {"uz": "Sizda hozircha faol buyurtmalar yo'q.", "ru": "У вас пока нет активных заказов."},
    "order_item": {"uz": "#{id} | {status} | {issue} | {date}", "ru": "#{id} | {status} | {issue} | {date}"},
}

def _t(language: str | None, key: str, **kwargs) -> str:
    return TEXT[key][normalize_language(language)].format(**kwargs)

async def _get_user_language(user_id: int) -> str:
    async with AsyncSessionFactory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        return normalize_language(user.language if user else None)

async def _get_current_language(state: FSMContext, user_id: int) -> str:
    data = await state.get_data()
    if "language" in data: return normalize_language(data["language"])
    return await _get_user_language(user_id)

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DriverQuickOrderState.language)
    await message.answer(TEXT["choose_language"]["uz"], reply_markup=language_keyboard())

@router.callback_query(DriverQuickOrderState.language, F.data.startswith("language:"))
@router.callback_query(F.data.startswith("language:")) # Allow global language change
async def choose_language(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None:
        await callback.answer("Foydalanuvchi ma'lumotlari olinmadi.", show_alert=True)
        return

    try:
        language = normalize_language(callback.data.split(":")[1])
        async with AsyncSessionFactory() as session:
            # Check if user exists
            user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
            if not user:
                user = User(
                    telegram_id=callback.from_user.id, 
                    full_name=callback.from_user.full_name, 
                    language=language
                )
                session.add(user)
            else:
                user.language = language
                if callback.from_user.full_name:
                    user.full_name = callback.from_user.full_name
            
            await session.commit()
    except Exception as exc:
        logger.exception("DATABASE ERROR in choose_language for user %s: %s", callback.from_user.id, exc)
        await callback.answer("Texnik xatolik. Iltimos, qayta urinib ko'ring.", show_alert=True)
        return
    
    await state.clear()
    await state.update_data(language=language)
    msg = _safe_message(callback)
    if msg:
        try: await msg.edit_text(_t(language, "welcome"))
        except: pass
        await msg.answer(_t(language, "main_menu"), reply_markup=start_keyboard(language))
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
    await message.answer(TEXT["choose_language"]["uz"], reply_markup=language_keyboard())

@router.message(F.text.in_(set(BUTTONS["about"].values())))
async def cmd_about(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await message.answer(_t(lang, "about_text"), parse_mode="Markdown")

@router.message(F.text.in_(set(BUTTONS["order_status"].values())))
async def cmd_order_status(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    async with AsyncSessionFactory() as session:
        query = select(Order).join(User).where(User.telegram_id == message.from_user.id).order_by(Order.created_at.desc()).limit(5)
        orders = (await session.execute(query)).scalars().all()
    
    if not orders:
        await message.answer(_t(lang, "no_active_orders"))
        return
    
    lines = ["📋 So'nggi buyurtmalar / Последние заказы:\n"]
    for o in orders:
        lines.append(_t(lang, "order_item", id=o.id, status=o.status.name, issue=o.issue_label, date=o.created_at.strftime("%H:%M %d.%m")))
    await message.answer("\n".join(lines))

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
    if not contact or (contact.user_id and contact.user_id != message.from_user.id):
        await message.answer(_t(lang, "ask_own_phone"))
        return
    await state.update_data(phone=contact.phone_number)
    await state.set_state(DriverQuickOrderState.location)
    await message.answer(_t(lang, "ask_location"), reply_markup=request_location_keyboard(lang))

@router.message(DriverQuickOrderState.phone)
async def phone_hint(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await message.answer(_t(lang, "phone_hint", button=button("phone", lang)), reply_markup=request_phone_keyboard(lang))

@router.message(DriverQuickOrderState.location, F.location)
async def collect_location(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await state.update_data(latitude=message.location.latitude, longitude=message.location.longitude)
    data = await state.get_data()
    maps = f"https://maps.google.com/?q={data['latitude']},{data['longitude']}"
    summary = _t(lang, "confirm_summary", issue=data["issue"], phone=data["phone"], maps=maps)
    await state.set_state(DriverQuickOrderState.confirm)
    await message.answer(summary, reply_markup=confirm_keyboard(lang), parse_mode="Markdown")

@router.message(DriverQuickOrderState.location)
async def location_hint(message: Message, state: FSMContext) -> None:
    lang = await _get_current_language(state, message.from_user.id)
    await message.answer(_t(lang, "location_hint", button=button("location", lang)), reply_markup=request_location_keyboard(lang))

@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await _get_current_language(state, callback.from_user.id)
    await state.clear()
    await state.update_data(language=lang)
    msg = _safe_message(callback)
    if msg:
        try: await msg.edit_text(_t(lang, "order_cancelled"))
        except: pass
        await msg.answer(_t(lang, "main_menu"), reply_markup=start_keyboard(lang))
    await callback.answer()

@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_confirm")
async def confirm_order(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await _get_current_language(state, callback.from_user.id)
    data = await state.get_data()
    if not all(k in data for k in ["phone", "issue", "latitude", "longitude"]):
        await callback.answer("Ma'lumotlar to'liq emas.", show_alert=True)
        return

    msg = _safe_message(callback)
    if msg: 
        try: await msg.edit_text(f"⏳ **Yuborilmoqda...**\n\n{msg.text}", parse_mode="Markdown")
        except: pass

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.create_driver_order(DriverOrderPayload(client_telegram_id=callback.from_user.id, full_name=callback.from_user.full_name, language=lang, phone=data["phone"], issue_label=data["issue"], latitude=float(data["latitude"]), longitude=float(data["longitude"])))
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_new_order(order_id=order.id, client_telegram_id=callback.from_user.id, phone=data["phone"], issue=data["issue"], latitude=float(data["latitude"]), longitude=float(data["longitude"]))
            await ns.notify_client_order_created(order_id=order.id, client_telegram_id=callback.from_user.id, language=lang)
        
        await state.clear()
        await state.update_data(language=lang)
        if msg:
            try: await msg.edit_text(_t(lang, "order_created", order_id=order.id))
            except: pass
            await msg.answer(_t(lang, "main_menu"), reply_markup=start_keyboard(lang))
    except Exception as exc:
        logger.exception("Confirm order error: %s", exc)
        await callback.answer("Texnik xatolik. Iltimos, qayta urinib ko'ring.", show_alert=True)
        return
    await callback.answer()
