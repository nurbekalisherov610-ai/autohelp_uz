import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from src.bot.states.master import MasterCompletionState
from src.core.config import get_settings
from src.db.enums import OrderStatus
from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService
from src.services.order_service import (
    OrderService,
)

router = Router(name="master_orders")
logger = logging.getLogger(__name__)

MASTER_STATUS_ALIASES: dict[str, OrderStatus] = {
    "on_the_way": OrderStatus.ON_THE_WAY,
    "arrived": OrderStatus.ARRIVED,
    "in_progress": OrderStatus.IN_PROGRESS,
    "awaiting_confirm": OrderStatus.AWAITING_CONFIRM,
}


def _safe_message(callback: CallbackQuery) -> Message | None:
    """Return the real Message object or None if the message is inaccessible."""
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return None
    return msg


def _get_next_status_kb(order_id: int, current_status: OrderStatus) -> InlineKeyboardMarkup | None:
    buttons = []
    if current_status == OrderStatus.ACCEPTED:
        buttons.append([InlineKeyboardButton(text="📍 Yo'lga chiqdim", callback_data=f"master_status:{order_id}:on_the_way")])
    elif current_status == OrderStatus.ON_THE_WAY:
        buttons.append([InlineKeyboardButton(text="🏁 Yetib keldim", callback_data=f"master_status:{order_id}:arrived")])
    elif current_status == OrderStatus.ARRIVED:
        buttons.append([InlineKeyboardButton(text="🛠 Ishni boshladim", callback_data=f"master_status:{order_id}:in_progress")])
    elif current_status == OrderStatus.IN_PROGRESS:
        buttons.append([InlineKeyboardButton(text="✅ Ishni tugatdim (Kutish)", callback_data=f"master_status:{order_id}:awaiting_confirm")])

    if buttons:
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    return None


def _cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _parse_parts(message: Message) -> list[str]:
    text = (message.text or "").strip()
    return [part for part in text.split() if part]


@router.message(Command("master_help"))
async def master_help(message: Message) -> None:
    await message.answer(
        "Master buyruqlari:\n"
        "/my_jobs - Menga biriktirilgan faol buyurtmalar\n"
        "Yoki buyurtma xabaridagi tugmalardan foydalaning!"
    )


@router.message(Command("register_master"))
async def register_master(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Foydalanuvchi aniqlanmadi.")
        return

    from src.core.config import get_settings as _get_settings
    _settings = _get_settings()

    # Determine valid secrets: master_secret env var, or fallback "master123"
    valid_secret = getattr(_settings, "master_secret", None) or "master123"

    # 1. Check if user is in MASTER_IDS list (auto-pass)
    if _settings.master_ids:
        m_ids = {int(x.strip()) for x in _settings.master_ids.split(",") if x.strip().lstrip("-").isdigit()}
        if message.from_user.id in m_ids:
            # Skip secret check
            pass
        else:
            # 2. Otherwise check secret code
            args = message.text.split() if message.text else []
            if len(args) < 2 or args[1] != valid_secret:
                await message.answer("Maxfiy kod xato. Format: /register_master <maxfiykod>")
                return
    else:
        # 2. Check secret code if no MASTER_IDS configured
        args = message.text.split() if message.text else []
        if len(args) < 2 or args[1] != valid_secret:
            await message.answer("Maxfiy kod xato. Format: /register_master <maxfiykod>")
            return

    from sqlalchemy import select

    from src.db.models.user import User

    async with AsyncSessionFactory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if user:
            user.is_master = True
            if message.from_user.full_name:
                user.full_name = message.from_user.full_name
            await session.commit()
            await message.answer("✅ Siz muvaffaqiyatli Master sifatida ro'yxatdan o'tdingiz!")
        else:
            # Auto-create user if not registered yet
            new_user = User(
                telegram_id=message.from_user.id,
                full_name=message.from_user.full_name,
                is_master=True,
            )
            session.add(new_user)
            await session.commit()
            await message.answer("✅ Profil yaratildi va Master sifatida ro'yxatdan o'tdingiz!")


@router.message(Command("my_jobs"))
async def my_jobs(message: Message) -> None:
    if message.from_user is None:
        return

    master_telegram_id = message.from_user.id
    async with AsyncSessionFactory() as session:
        service = OrderService(session)
        orders = await service.list_master_active_orders(master_telegram_id=master_telegram_id, limit=10)

    if not orders:
        await message.answer("Sizga hozircha faol buyurtma biriktirilmagan.")
        return

    await message.answer("Faol buyurtmalar:")
    for order in orders:
        text = f"#{order.id} | {order.status.name} | {order.issue_label} | {order.phone}"
        await message.answer(text, reply_markup=_get_next_status_kb(order.id, order.status))


@router.callback_query(F.data.startswith("master_accept:"))
async def cb_accept_order(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri buyurtma ID.", show_alert=True)
        return
    master_telegram_id = callback.from_user.id

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=master_telegram_id,
                to_status=OrderStatus.ACCEPTED,
            )
            ns = NotificationService(bot=callback.bot, settings=get_settings())
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Master accept failed for order #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(
                f"✅ Buyurtma #{order.id} qabul qilindi.\nStatus: ACCEPTED",
                reply_markup=_get_next_status_kb(order.id, OrderStatus.ACCEPTED)
            )
        except TelegramBadRequest:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("master_reject:"))
async def cb_reject_order(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri buyurtma ID.", show_alert=True)
        return
    master_telegram_id = callback.from_user.id

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=master_telegram_id,
                to_status=OrderStatus.REJECTED,
            )
            ns = NotificationService(bot=callback.bot, settings=get_settings())
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Master reject failed for order #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(f"❌ Buyurtma #{order.id} rad etildi.")
        except TelegramBadRequest:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("master_status:"))
async def cb_master_status(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    try:
        parts = callback.data.split(":")
        order_id = int(parts[1])
        alias = parts[2]
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri status so'rovi.", show_alert=True)
        return
    master_telegram_id = callback.from_user.id

    to_status = MASTER_STATUS_ALIASES.get(alias)
    if not to_status:
        await callback.answer("Noto'g'ri status", show_alert=True)
        return

    # Trigger Video and Amount Collection FSM instead of updating right away
    if to_status == OrderStatus.AWAITING_CONFIRM:
        await state.update_data(master_order_id=order_id)
        await state.set_state(MasterCompletionState.waiting_for_video)
        msg = _safe_message(callback)
        if msg is not None:
            try:
                await msg.edit_text(
                    f"Buyurtma #{order_id} bo'yicha ish yakunlandi.\n"
                    "Iltimos, isbot sifatida xizmat jarayonidan qisqa video xabar (video note) yuboring:"
                )
            except TelegramBadRequest:
                pass
            await msg.answer("Yoki jarayonni bekor qilish uchun tugmani bosing:", reply_markup=_cancel_kb())
        await callback.answer()
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=master_telegram_id,
                to_status=to_status,
            )
            ns = NotificationService(bot=callback.bot, settings=get_settings())
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Master status transition failed for order #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    new_kb = _get_next_status_kb(order.id, order.status)
    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(
                f"Buyurtma #{order.id}\nStatus yangilandi: {order.status.name}",
                reply_markup=new_kb
            )
        except TelegramBadRequest:
            pass
    await callback.answer()


@router.message(MasterCompletionState.waiting_for_video, F.text == "❌ Bekor qilish")
@router.message(MasterCompletionState.waiting_for_amount, F.text == "❌ Bekor qilish")
async def cancel_master_fsm(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Jarayon bekor qilindi.", reply_markup=ReplyKeyboardRemove())


@router.message(MasterCompletionState.waiting_for_video, F.video_note | F.video)
async def process_master_video(message: Message, state: FSMContext) -> None:
    video_id = message.video_note.file_id if message.video_note else message.video.file_id
    await state.update_data(video_file_id=video_id)
    await state.set_state(MasterCompletionState.waiting_for_amount)
    await message.answer("Video qabul qilindi. Endi xizmat summasini raqamlarda kiriting (masalan: 50000):", reply_markup=_cancel_kb())


@router.message(MasterCompletionState.waiting_for_video)
async def invalid_master_video(message: Message) -> None:
    await message.answer("Iltimos, faqat video xabar (video note) yoki oddiy video yuboring.")


@router.message(MasterCompletionState.waiting_for_amount)
async def process_master_amount(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        await message.answer("Foydalanuvchi aniqlanmadi.")
        return

    try:
        amount = float((message.text or "").strip())
    except ValueError:
        await message.answer("Iltimos, summani raqamda kiriting (masalan: 50000).")
        return

    data = await state.get_data()
    order_id = data.get("master_order_id")
    video_file_id = data.get("video_file_id")
    master_telegram_id = message.from_user.id

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=master_telegram_id,
                to_status=OrderStatus.AWAITING_CONFIRM,
                video_file_id=video_file_id,
                final_amount=amount,
            )
            ns = NotificationService(bot=message.bot, settings=get_settings())
            await ns.notify_client_status_change(order, order.status)
            master_name = message.from_user.full_name or str(master_telegram_id)
            await ns.notify_dispatcher_completion_review(order, master_name)
    except Exception as exc:
        logger.exception("Master completion failed for order #%s: %s", order_id, exc)
        await message.answer(f"Xatolik yuz berdi: {exc}")
        return

    await state.clear()
    await message.answer(f"✅ Buyurtma #{order_id} yakunlandi. Ma'lumotlar dispecherga yuborildi. Tasdiqlanishi kutilmoqda.", reply_markup=ReplyKeyboardRemove())
