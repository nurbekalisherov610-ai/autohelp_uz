"""
Master order management handlers.

Masters receive orders via notification and can:
1. Accept or reject the order
2. Update their status: On the Way → Arrived → In Progress
3. Complete the order: submit a completion video + service amount

The dispatcher then confirms the payment to mark the order COMPLETED.
"""
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
from src.services.order_service import OrderService

router = Router(name="master_orders")
logger = logging.getLogger(__name__)
settings = get_settings()

# Map callback alias → OrderStatus
MASTER_STATUS_ALIASES: dict[str, OrderStatus] = {
    "on_the_way": OrderStatus.ON_THE_WAY,
    "arrived": OrderStatus.ARRIVED,
    "in_progress": OrderStatus.IN_PROGRESS,
    "awaiting_confirm": OrderStatus.AWAITING_CONFIRM,
}


def _safe_message(callback: CallbackQuery) -> Message | None:
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return None
    return msg


def _next_status_kb(order_id: int, current_status: OrderStatus) -> InlineKeyboardMarkup | None:
    """Return the next-action button for a master based on current status."""
    NEXT: dict[OrderStatus, tuple[str, str]] = {
        OrderStatus.ACCEPTED: ("📍 Yo'lga chiqdim", "on_the_way"),
        OrderStatus.ON_THE_WAY: ("🏁 Yetib keldim", "arrived"),
        OrderStatus.ARRIVED: ("🛠 Ishni boshladim", "in_progress"),
        OrderStatus.IN_PROGRESS: ("✅ Ishni tugatdim", "awaiting_confirm"),
    }
    entry = NEXT.get(current_status)
    if not entry:
        return None
    text, alias = entry
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=f"master_status:{order_id}:{alias}")]
        ]
    )


def _cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ── Commands ──────────────────────────────────────────────────────────────────

@router.message(Command("master_help"))
async def master_help(message: Message) -> None:
    await message.answer(
        "👨‍🔧 <b>Master buyruqlari:</b>\n\n"
        "/my_jobs — Menga biriktirilgan faol buyurtmalar\n"
        "/register_master — Master sifatida ro'yxatdan o'tish\n\n"
        "Buyurtma kelganda, <b>Qabul qilish</b> tugmasini bosing va "
        "keyingi statuslarni ketma-ket yangilang.",
        parse_mode="HTML",
    )


@router.message(Command("register_master"))
async def register_master(message: Message) -> None:
    if message.from_user is None:
        await message.answer("Foydalanuvchi aniqlanmadi.")
        return

    # Check if in MASTER_IDS (auto-pass) or validate secret
    master_ids = settings.parsed_master_ids
    if master_ids and message.from_user.id in master_ids:
        # Auto-authorized via env config
        pass
    else:
        args = (message.text or "").split()
        valid_secret = settings.master_secret or "master123"
        if len(args) < 2 or args[1] != valid_secret:
            await message.answer(
                "❌ Maxfiy kod xato.\n\nFormat: <code>/register_master &lt;maxfiy_kod&gt;</code>",
                parse_mode="HTML",
            )
            return

    from sqlalchemy import select
    from src.db.models.user import User

    async with AsyncSessionFactory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if user:
            user.is_master = True
            if message.from_user.full_name:
                user.full_name = message.from_user.full_name
            await session.commit()
            await message.answer(
                "✅ Siz muvaffaqiyatli <b>Master</b> sifatida ro'yxatdan o'tdingiz!",
                parse_mode="HTML",
            )
        else:
            new_user = User(
                telegram_id=message.from_user.id,
                full_name=message.from_user.full_name,
                is_master=True,
            )
            session.add(new_user)
            await session.commit()
            await message.answer(
                "✅ Profil yaratildi va <b>Master</b> sifatida ro'yxatdan o'tdingiz!",
                parse_mode="HTML",
            )


@router.message(Command("my_jobs"))
async def my_jobs(message: Message) -> None:
    if message.from_user is None:
        return

    async with AsyncSessionFactory() as session:
        service = OrderService(session)
        orders = await service.list_master_active_orders(
            master_telegram_id=message.from_user.id, limit=10
        )

    if not orders:
        await message.answer("Sizga hozircha faol buyurtma biriktirilmagan.")
        return

    await message.answer(f"📦 <b>{len(orders)} ta faol buyurtma:</b>", parse_mode="HTML")
    for order in orders:
        kb = _next_status_kb(order.id, order.status)
        await message.answer(
            f"#{order.id} | <b>{order.status.name}</b> | {order.issue_label} | {order.phone}",
            reply_markup=kb,
            parse_mode="HTML",
        )


# ── Callbacks — Accept / Reject ───────────────────────────────────────────────

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
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Master accept failed for order #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(
                f"✅ Buyurtma <b>#{order.id}</b> qabul qilindi!\n"
                f"Status: <b>ACCEPTED</b>\n\n"
                "Tayyor bo'lganda yo'lga chiqing:",
                reply_markup=_next_status_kb(order.id, OrderStatus.ACCEPTED),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer("✅ Qabul qilindi!")


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
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Master reject failed for order #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(f"❌ Buyurtma <b>#{order.id}</b> rad etildi.", parse_mode="HTML")
        except TelegramBadRequest:
            pass
    await callback.answer("Rad etildi.")


# ── Callbacks — Status progression ───────────────────────────────────────────

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
        await callback.answer("Noto'g'ri status.", show_alert=True)
        return

    # Completion flow: collect video + amount before transitioning
    if to_status == OrderStatus.AWAITING_CONFIRM:
        await state.update_data(master_order_id=order_id)
        await state.set_state(MasterCompletionState.waiting_for_video)
        msg = _safe_message(callback)
        if msg is not None:
            try:
                await msg.edit_text(
                    f"📹 Buyurtma <b>#{order_id}</b> yakunlash uchun:\n\n"
                    "Iltimos, xizmat jarayonidan qisqa <b>video xabar (video note)</b> yuboring:",
                    parse_mode="HTML",
                )
            except TelegramBadRequest:
                pass
            await msg.answer("Bekor qilish uchun:", reply_markup=_cancel_kb())
        await callback.answer()
        return

    # All other transitions: update immediately
    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=master_telegram_id,
                to_status=to_status,
            )
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Master status transition failed for order #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    new_kb = _next_status_kb(order.id, order.status)
    msg = _safe_message(callback)
    if msg is not None:
        status_labels = {
            OrderStatus.ON_THE_WAY: "🚗 Yo'lda",
            OrderStatus.ARRIVED: "📍 Yetib keldim",
            OrderStatus.IN_PROGRESS: "🛠 Ishlamoqda",
        }
        label = status_labels.get(order.status, order.status.name)
        try:
            await msg.edit_text(
                f"Buyurtma <b>#{order.id}</b>\nStatus: <b>{label}</b>",
                reply_markup=new_kb,
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer(f"Status yangilandi!")


# ── FSM — Completion video + amount ──────────────────────────────────────────

@router.message(MasterCompletionState.waiting_for_video, F.text == "❌ Bekor qilish")
@router.message(MasterCompletionState.waiting_for_amount, F.text == "❌ Bekor qilish")
async def cancel_master_fsm(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Jarayon bekor qilindi.", reply_markup=ReplyKeyboardRemove())


@router.message(MasterCompletionState.waiting_for_video, F.video_note | F.video)
async def process_master_video(message: Message, state: FSMContext) -> None:
    video_id = (
        message.video_note.file_id if message.video_note else message.video.file_id
    )
    await state.update_data(video_file_id=video_id)
    await state.set_state(MasterCompletionState.waiting_for_amount)
    await message.answer(
        "✅ Video qabul qilindi!\n\n"
        "Endi xizmat <b>summasini</b> raqamlarda kiriting (masalan: 50000):",
        reply_markup=_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(MasterCompletionState.waiting_for_video)
async def invalid_master_video(message: Message) -> None:
    await message.answer(
        "⚠️ Iltimos, faqat <b>video xabar (video note)</b> yoki oddiy video yuboring.",
        parse_mode="HTML",
    )


@router.message(MasterCompletionState.waiting_for_amount)
async def process_master_amount(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        await message.answer("Foydalanuvchi aniqlanmadi.")
        return

    raw = (message.text or "").strip().replace(" ", "").replace(",", "")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError("Amount must be positive")
    except ValueError:
        await message.answer(
            "⚠️ Iltimos, summani faqat raqamlarda kiriting (masalan: 50000).",
            reply_markup=_cancel_kb(),
        )
        return

    data = await state.get_data()
    order_id = data.get("master_order_id")
    video_file_id = data.get("video_file_id")
    master_telegram_id = message.from_user.id

    if not order_id:
        await state.clear()
        await message.answer(
            "Xatolik: buyurtma ID topilmadi. Qayta /my_jobs buyrug'ini yuboring.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

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
            ns = NotificationService(bot=message.bot, settings=settings)
            # Notify client
            await ns.notify_client_status_change(order, order.status)
            # Notify dispatcher with video + confirm button
            master_name = message.from_user.full_name or str(master_telegram_id)
            await ns.notify_dispatcher_completion_review(order, master_name)
    except Exception as exc:
        logger.exception("Master completion failed for order #%s: %s", order_id, exc)
        await message.answer(
            f"❌ Xatolik yuz berdi: {exc}\n\nQayta urinib ko'ring yoki dispatcher bilan bog'laning.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await state.clear()
    await message.answer(
        f"✅ <b>Buyurtma #{order_id}</b> yakunlandi!\n\n"
        f"💰 Summa: <b>{amount:,.0f} so'm</b>\n\n"
        "Ma'lumotlar dispecherga yuborildi. Tasdiqlanishi kutilmoqda. 🙏",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
