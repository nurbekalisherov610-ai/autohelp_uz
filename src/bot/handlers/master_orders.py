"""
Master order management handlers.
Masters: accept/reject → on the way → arrived → in progress → submit video+amount.
Dispatcher then confirms payment to mark COMPLETED.
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
from sqlalchemy import select

from src.bot.states.master import MasterCompletionState
from src.core.config import get_settings
from src.db.enums import OrderStatus
from src.db.models.user import User
from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService
from src.services.order_service import OrderService

router = Router(name="master_orders")
logger = logging.getLogger(__name__)
settings = get_settings()

MASTER_STATUS_ALIASES: dict[str, OrderStatus] = {
    "on_the_way": OrderStatus.ON_THE_WAY,
    "arrived": OrderStatus.ARRIVED,
    "in_progress": OrderStatus.IN_PROGRESS,
    "awaiting_confirm": OrderStatus.AWAITING_CONFIRM,
}


def _safe_msg(cb: CallbackQuery) -> Message | None:
    if cb.message is None or isinstance(cb.message, InaccessibleMessage):
        return None
    return cb.message


def _next_kb(order_id: int, status: OrderStatus) -> InlineKeyboardMarkup | None:
    NEXT: dict[OrderStatus, tuple[str, str]] = {
        OrderStatus.ACCEPTED: ("🚗 Yo'lga chiqdim", "on_the_way"),
        OrderStatus.ON_THE_WAY: ("📍 Yetib keldim", "arrived"),
        OrderStatus.ARRIVED: ("🛠 Ishni boshladim", "in_progress"),
        OrderStatus.IN_PROGRESS: ("✅ Ishni tugatdim", "awaiting_confirm"),
    }
    entry = NEXT.get(status)
    if not entry:
        return None
    label, alias = entry
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=label, callback_data=f"master_status:{order_id}:{alias}"
            )
        ]]
    )


def _cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ── Commands ──────────────────────────────────────────────────────────────────

@router.message(Command("my_jobs"))
async def cmd_my_jobs(message: Message) -> None:
    if not message.from_user:
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
    for o in orders:
        kb = _next_kb(o.id, o.status)
        await message.answer(
            f"<b>#{o.id}</b> | {o.status.name} | {o.issue_label} | {o.phone}",
            reply_markup=kb,
            parse_mode="HTML",
        )


@router.message(Command("register_master"))
async def cmd_register_master(message: Message) -> None:
    if not message.from_user:
        return

    # Auto-authorized if in MASTER_IDS env var
    if message.from_user.id in settings.parsed_master_ids:
        pass  # allowed
    else:
        args = (message.text or "").split()
        secret = settings.master_secret or "master123"
        if len(args) < 2 or args[1] != secret:
            await message.answer(
                "❌ Format: <code>/register_master &lt;maxfiy_kod&gt;</code>",
                parse_mode="HTML",
            )
            return

    async with AsyncSessionFactory() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if user:
            user.is_master = True
            if message.from_user.full_name:
                user.full_name = message.from_user.full_name
            await session.commit()
        else:
            session.add(User(
                telegram_id=message.from_user.id,
                full_name=message.from_user.full_name,
                is_master=True,
            ))
            await session.commit()

    await message.answer("✅ Siz <b>Master</b> sifatida ro'yxatdan o'tdingiz!", parse_mode="HTML")


# ── Accept / Reject ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("master_accept:"))
async def cb_accept(callback: CallbackQuery) -> None:
    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=callback.from_user.id,
                to_status=OrderStatus.ACCEPTED,
            )
            client = await session.scalar(
                select(User).where(User.id == order.client_id)
            )
            client_telegram_id = client.telegram_id if client else None
            client_language = client.language if client else None
            _order_id = order.id

        ns = NotificationService(bot=callback.bot, settings=settings)
        if client_telegram_id:
            await ns.notify_client_status_change(
                order_id=_order_id,
                client_telegram_id=client_telegram_id,
                client_language=client_language,
                status=OrderStatus.ACCEPTED,
            )
    except Exception as exc:
        logger.exception("master_accept error for #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"✅ Buyurtma <b>#{_order_id}</b> qabul qilindi!\n\n"
                "Tayyor bo'lganda yo'lga chiqing:",
                reply_markup=_next_kb(_order_id, OrderStatus.ACCEPTED),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer("✅ Qabul qilindi!")


@router.callback_query(F.data.startswith("master_reject:"))
async def cb_reject(callback: CallbackQuery) -> None:
    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=callback.from_user.id,
                to_status=OrderStatus.REJECTED,
            )
            client = await session.scalar(select(User).where(User.id == order.client_id))
            client_telegram_id = client.telegram_id if client else None
            client_language = client.language if client else None
            _order_id = order.id

        ns = NotificationService(bot=callback.bot, settings=settings)
        if client_telegram_id:
            await ns.notify_client_status_change(
                order_id=_order_id,
                client_telegram_id=client_telegram_id,
                client_language=client_language,
                status=OrderStatus.REJECTED,
            )
    except Exception as exc:
        logger.exception("master_reject error for #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"❌ Buyurtma <b>#{_order_id}</b> rad etildi.", parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass
    await callback.answer("Rad etildi.")


# ── Status progression ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("master_status:"))
async def cb_master_status(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        parts = (callback.data or "").split(":")
        order_id = int(parts[1])
        alias = parts[2]
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    to_status = MASTER_STATUS_ALIASES.get(alias)
    if not to_status:
        await callback.answer("Noto'g'ri status.", show_alert=True)
        return

    # Completion: collect video + amount via FSM first
    if to_status == OrderStatus.AWAITING_CONFIRM:
        await state.update_data(master_order_id=order_id)
        await state.set_state(MasterCompletionState.waiting_for_video)
        msg = _safe_msg(callback)
        if msg:
            try:
                await msg.edit_text(
                    f"📹 Buyurtma <b>#{order_id}</b> yakunlash:\n\n"
                    "Xizmat jarayonidan qisqa <b>video xabar</b> yuboring:",
                    parse_mode="HTML",
                )
            except TelegramBadRequest:
                pass
            await msg.answer("Bekor qilish:", reply_markup=_cancel_kb())
        await callback.answer()
        return

    # All other transitions: immediate
    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=callback.from_user.id,
                to_status=to_status,
            )
            client = await session.scalar(select(User).where(User.id == order.client_id))
            client_telegram_id = client.telegram_id if client else None
            client_language = client.language if client else None
            _order_id = order.id
            _status = order.status

        ns = NotificationService(bot=callback.bot, settings=settings)
        if client_telegram_id:
            await ns.notify_client_status_change(
                order_id=_order_id,
                client_telegram_id=client_telegram_id,
                client_language=client_language,
                status=_status,
            )
    except Exception as exc:
        logger.exception("master_status error #%s %s: %s", order_id, alias, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    labels = {
        OrderStatus.ON_THE_WAY: "🚗 Yo'lda",
        OrderStatus.ARRIVED: "📍 Yetib keldim",
        OrderStatus.IN_PROGRESS: "🛠 Ishlamoqda",
    }
    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"Buyurtma <b>#{_order_id}</b>\nStatus: <b>{labels.get(_status, _status.name)}</b>",
                reply_markup=_next_kb(_order_id, _status),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer("Status yangilandi!")


# ── FSM: video submission ─────────────────────────────────────────────────────

@router.message(MasterCompletionState.waiting_for_video, F.text == "❌ Bekor qilish")
@router.message(MasterCompletionState.waiting_for_amount, F.text == "❌ Bekor qilish")
async def cancel_completion(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())


@router.message(MasterCompletionState.waiting_for_video, F.video_note | F.video)
async def process_video(message: Message, state: FSMContext) -> None:
    vid = message.video_note.file_id if message.video_note else message.video.file_id
    await state.update_data(video_file_id=vid)
    await state.set_state(MasterCompletionState.waiting_for_amount)
    await message.answer(
        "✅ Video qabul qilindi!\n\n💰 Xizmat <b>summasini</b> raqamlarda kiriting (masalan: 50000):",
        reply_markup=_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(MasterCompletionState.waiting_for_video)
async def invalid_video(message: Message) -> None:
    await message.answer(
        "⚠️ Iltimos, <b>video xabar</b> yoki video yuboring.",
        parse_mode="HTML",
    )


# ── FSM: amount submission → complete ─────────────────────────────────────────

@router.message(MasterCompletionState.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    raw = (message.text or "").strip().replace(" ", "").replace(",", "")
    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "⚠️ Summani faqat raqamlarda kiriting (masalan: 50000).",
            reply_markup=_cancel_kb(),
        )
        return

    data = await state.get_data()
    order_id = data.get("master_order_id")
    video_file_id = data.get("video_file_id")

    if not order_id:
        await state.clear()
        await message.answer(
            "Xatolik: buyurtma ID topilmadi. /my_jobs bilan qayta boshlang.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    master_name = message.from_user.full_name or str(message.from_user.id)

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=message.from_user.id,
                to_status=OrderStatus.AWAITING_CONFIRM,
                video_file_id=video_file_id,
                final_amount=amount,
            )
            client = await session.scalar(select(User).where(User.id == order.client_id))
            client_telegram_id = client.telegram_id if client else None
            client_language = client.language if client else None
            _order_id = order.id
            _video = order.video_file_id
            _amount = order.final_amount

        ns = NotificationService(bot=message.bot, settings=settings)

        # Notify client
        if client_telegram_id:
            await ns.notify_client_status_change(
                order_id=_order_id,
                client_telegram_id=client_telegram_id,
                client_language=client_language,
                status=OrderStatus.AWAITING_CONFIRM,
            )

        # Notify dispatcher with video + confirm button
        await ns.notify_dispatcher_completion_review(
            order_id=_order_id,
            final_amount=float(_amount) if _amount else amount,
            video_file_id=_video,
            master_name=master_name,
        )

    except Exception as exc:
        logger.exception("process_amount error for #%s: %s", order_id, exc)
        await message.answer(
            f"❌ Xatolik: {exc}\n\nQayta urinib ko'ring.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await state.clear()
    await message.answer(
        f"✅ <b>Buyurtma #{order_id}</b> yakunlandi!\n\n"
        f"💰 Summa: <b>{amount:,.0f} so'm</b>\n\n"
        "Dispetcherga yuborildi. Tasdiq kutilmoqda. 🙏",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
