from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards.driver import (
    CANCEL_BUTTON,
    ISSUE_OPTIONS,
    LOCATION_BUTTON,
    PHONE_BUTTON,
    START_ORDER_BUTTON,
    confirm_keyboard,
    issue_keyboard,
    request_location_keyboard,
    request_phone_keyboard,
    start_keyboard,
)
from src.bot.states.driver_order import DriverQuickOrderState
from src.core.config import get_settings
from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService
from src.services.order_service import DriverOrderPayload, OrderService

router = Router(name="driver_quick_order")
settings = get_settings()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "AutoHelp.uz ga xush kelibsiz. Tez yordam uchun tugmani bosing.",
        reply_markup=start_keyboard(),
    )


@router.message(Command("cancel"))
@router.message(F.text == CANCEL_BUTTON)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("Jarayon bekor qilindi.", reply_markup=start_keyboard())


@router.message(Command("new_order"))
@router.message(F.text == START_ORDER_BUTTON)
async def start_quick_order(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DriverQuickOrderState.issue)
    await message.answer("Nima muammo?", reply_markup=issue_keyboard())


@router.message(DriverQuickOrderState.issue)
async def collect_issue(message: Message, state: FSMContext) -> None:
    issue = (message.text or "").strip()
    if issue not in ISSUE_OPTIONS:
        await message.answer("Iltimos, ro'yxatdan muammo turini tanlang.", reply_markup=issue_keyboard())
        return

    await state.update_data(issue=issue)
    await state.set_state(DriverQuickOrderState.phone)
    await message.answer(
        "Telefon raqamingizni yuboring.",
        reply_markup=request_phone_keyboard(),
    )


@router.message(DriverQuickOrderState.phone, F.contact)
async def collect_phone(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        await message.answer("Foydalanuvchi aniqlanmadi.")
        return

    contact = message.contact
    if contact is None:
        await message.answer("Telefon yuborilmadi. Qaytadan urinib ko'ring.")
        return

    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer("Iltimos, o'zingizning raqamingizni yuboring.")
        return

    await state.update_data(phone=contact.phone_number)
    await state.set_state(DriverQuickOrderState.location)
    await message.answer(
        "Lokatsiyani yuboring.",
        reply_markup=request_location_keyboard(),
    )


@router.message(DriverQuickOrderState.phone)
async def phone_validation_hint(message: Message) -> None:
    await message.answer(
        f"Iltimos, `{PHONE_BUTTON}` tugmasi orqali yuboring.",
        parse_mode="Markdown",
        reply_markup=request_phone_keyboard(),
    )


@router.message(DriverQuickOrderState.location, F.location)
async def collect_location(message: Message, state: FSMContext) -> None:
    location = message.location
    if location is None:
        await message.answer("Lokatsiya yuborilmadi. Qaytadan urinib ko'ring.")
        return

    await state.update_data(latitude=location.latitude, longitude=location.longitude)
    data = await state.get_data()

    summary = (
        "Buyurtma tasdiqlansinmi?\n\n"
        f"Muammo: {data['issue']}\n"
        f"Telefon: {data['phone']}\n"
        f"Lokatsiya: https://maps.google.com/?q={data['latitude']},{data['longitude']}"
    )

    await state.set_state(DriverQuickOrderState.confirm)
    await message.answer(summary, reply_markup=confirm_keyboard())


@router.message(DriverQuickOrderState.location)
async def location_validation_hint(message: Message) -> None:
    await message.answer(
        f"Iltimos, `{LOCATION_BUTTON}` tugmasi orqali yuboring.",
        parse_mode="Markdown",
        reply_markup=request_location_keyboard(),
    )


@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_cancel")
async def cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Buyurtma bekor qilindi.")
    await callback.message.answer("Asosiy menyu", reply_markup=start_keyboard())
    await callback.answer()


@router.callback_query(DriverQuickOrderState.confirm, F.data == "order_confirm")
async def confirm_order(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None:
        await callback.answer("Foydalanuvchi aniqlanmadi", show_alert=True)
        return

    data = await state.get_data()

    full_name = None
    language = None
    if callback.from_user is not None:
        full_name = callback.from_user.full_name
        language = callback.from_user.language_code

    async with AsyncSessionFactory() as session:
        order_service = OrderService(session)
        order = await order_service.create_driver_order(
            DriverOrderPayload(
                client_telegram_id=callback.from_user.id,
                full_name=full_name,
                language=language,
                phone=data["phone"],
                issue_label=data["issue"],
                latitude=float(data["latitude"]),
                longitude=float(data["longitude"]),
            )
        )

    alert_service = NotificationService(bot=callback.bot, settings=settings)
    await alert_service.notify_new_order(
        order_id=order.id,
        client_telegram_id=callback.from_user.id,
        phone=data["phone"],
        issue=data["issue"],
        latitude=float(data["latitude"]),
        longitude=float(data["longitude"]),
    )

    await state.clear()
    await callback.message.edit_text(
        f"Buyurtmangiz qabul qilindi. ID: #{order.id}. Dispecher tez orada siz bilan bog'lanadi."
    )
    await callback.message.answer(
        "Asosiy menyu",
        reply_markup=start_keyboard(),
    )
    await callback.answer()
