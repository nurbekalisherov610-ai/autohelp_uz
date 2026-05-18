"""
Dispatcher order management handlers.

Any user listed in DISPATCHER_IDS or ADMIN_IDS (or posting in DISPATCHER_GROUP_ID)
can perform dispatcher actions. Permission is checked at the handler level using
is_dispatcher() — the service layer no longer enforces dispatcher identity.
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
    Message,
)
from sqlalchemy import func, select

from src.bot.utils.permissions import is_dispatcher
from src.core.config import get_settings
from src.db.enums import OrderStatus
from src.db.models.order import Order
from src.db.models.user import User
from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService
from src.services.order_service import MASTER_ACTIVE_STATUSES, OrderService

logger = logging.getLogger(__name__)
router = Router(name="dispatcher_orders")
settings = get_settings()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _configured_master_label(master_id: int) -> str:
    ids = settings.parsed_master_ids
    labels = settings.parsed_master_labels
    try:
        index = ids.index(master_id)
        if index < len(labels) and labels[index]:
            return labels[index]
    except ValueError:
        pass
    return str(master_id)


def _safe_message(callback: CallbackQuery) -> Message | None:
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return None
    return msg


def _order_card(order: Order) -> str:
    maps = f"https://maps.google.com/?q={order.latitude},{order.longitude}"
    return (
        f"📋 <b>Buyurtma #{order.id}</b>\n"
        f"📞 Telefon: <b>{order.phone}</b>\n"
        f"🛠 Muammo: {order.issue_label}\n"
        f'📍 <a href="{maps}">Lokatsiya</a>\n'
        f"Status: <b>{order.status.name}</b>"
    )


def _assign_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"👨‍🔧 Usta biriktirish #{order_id}",
                    callback_data=f"dispatch_assign:{order_id}",
                )
            ]
        ]
    )


# ── Commands ─────────────────────────────────────────────────────────────────

@router.message(Command("new_orders"))
async def list_new_orders(message: Message) -> None:
    if not is_dispatcher(
        message.from_user.id if message.from_user else None, message.chat.id
    ):
        return

    async with AsyncSessionFactory() as session:
        service = OrderService(session)
        orders = await service.list_orders_by_status(
            [OrderStatus.NEW, OrderStatus.REJECTED], limit=10
        )

    if not orders:
        await message.answer("Hozircha yangi yoki rad etilgan buyurtmalar yo'q.")
        return

    await message.answer(f"📦 {len(orders)} ta buyurtma kutilmoqda:")
    for order in orders:
        await message.answer(
            _order_card(order),
            reply_markup=_assign_kb(order.id),
            parse_mode="HTML",
        )


@router.message(Command("active_orders"))
async def cmd_active_orders(message: Message) -> None:
    if not is_dispatcher(
        message.from_user.id if message.from_user else None, message.chat.id
    ):
        return

    async with AsyncSessionFactory() as session:
        service = OrderService(session)
        orders = await service.list_orders_by_status(
            [
                OrderStatus.ASSIGNED,
                OrderStatus.ACCEPTED,
                OrderStatus.ON_THE_WAY,
                OrderStatus.ARRIVED,
                OrderStatus.IN_PROGRESS,
                OrderStatus.AWAITING_CONFIRM,
            ],
            limit=20,
        )

    if not orders:
        await message.answer("Faol buyurtmalar yo'q.")
        return

    for o in orders:
        buttons = []
        if o.status == OrderStatus.AWAITING_CONFIRM:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="💰 Tasdiqlash", callback_data=f"dispatch_complete:{o.id}"
                    )
                ]
            )
        buttons.append(
            [InlineKeyboardButton(text="📋 Tafsilot", callback_data=f"dispatch_detail:{o.id}")]
        )
        await message.answer(
            f"#{o.id} | {o.status.name} | {o.issue_label} | {o.phone}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message) -> None:
    if not is_dispatcher(
        message.from_user.id if message.from_user else None, message.chat.id
    ):
        return

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Order.status, func.count(Order.id)).group_by(Order.status)
        )
        s = dict(result.all())

    text = (
        "📊 <b>Jonli Statistika</b>\n\n"
        f"🔴 Yangi: <b>{s.get(OrderStatus.NEW, 0)}</b>\n"
        f"🟠 Rad etilgan: <b>{s.get(OrderStatus.REJECTED, 0)}</b>\n"
        f"🔵 Biriktirilgan: <b>{s.get(OrderStatus.ASSIGNED, 0)}</b>\n"
        f"✅ Qabul qilingan: <b>{s.get(OrderStatus.ACCEPTED, 0)}</b>\n"
        f"🚗 Yo'lda: <b>{s.get(OrderStatus.ON_THE_WAY, 0)}</b>\n"
        f"📍 Yetib keldi: <b>{s.get(OrderStatus.ARRIVED, 0)}</b>\n"
        f"🛠 Ishlayapti: <b>{s.get(OrderStatus.IN_PROGRESS, 0)}</b>\n"
        f"⏳ Tasdiq kutmoqda: <b>{s.get(OrderStatus.AWAITING_CONFIRM, 0)}</b>\n"
        f"🏁 Yakunlangan: <b>{s.get(OrderStatus.COMPLETED, 0)}</b>\n"
        f"🚫 Bekor qilingan: <b>{s.get(OrderStatus.CANCELLED, 0)}</b>\n\n"
        "Buyruqlar: /new_orders · /active_orders · /order &lt;id&gt;"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("order"))
async def cmd_order_detail(message: Message) -> None:
    if not is_dispatcher(
        message.from_user.id if message.from_user else None, message.chat.id
    ):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Format: /order &lt;id&gt;", parse_mode="HTML")
        return

    try:
        order_id = int(parts[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            master_name = "—"
            if order.assigned_master_telegram_id:
                master_user = await session.scalar(
                    select(User).where(User.telegram_id == order.assigned_master_telegram_id)
                )
                if master_user:
                    master_name = master_user.full_name or str(master_user.telegram_id)
    except Exception as exc:
        await message.answer(f"Xatolik: {exc}")
        return

    amount_str = f"{float(order.final_amount):,.0f} so'm" if order.final_amount else "—"
    text = (
        f"📋 <b>Buyurtma #{order.id}</b>\n\n"
        f"Status: <b>{order.status.name}</b>\n"
        f"Muammo: {order.issue_label}\n"
        f"Telefon: <b>{order.phone}</b>\n"
        f"Usta: {master_name}\n"
        f"Summa: {amount_str}\n"
    )

    buttons = []
    if order.status in (OrderStatus.NEW, OrderStatus.REJECTED):
        buttons.append(
            [InlineKeyboardButton(text="📝 Usta biriktirish", callback_data=f"dispatch_assign:{order.id}")]
        )
    if order.status == OrderStatus.AWAITING_CONFIRM:
        buttons.append(
            [InlineKeyboardButton(text="💰 Tasdiqlash", callback_data=f"dispatch_complete:{order.id}")]
        )
    if order.status not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        buttons.append(
            [InlineKeyboardButton(text="🚫 Bekor qilish", callback_data=f"dispatch_cancel:{order.id}")]
        )

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
        parse_mode="HTML",
    )


# ── Callback handlers ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("dispatch_assign:"))
async def cb_assign_order(callback: CallbackQuery, state: FSMContext) -> None:
    """Show list of masters so dispatcher can pick one."""
    user_id = callback.from_user.id if callback.from_user else None
    chat_id = callback.message.chat.id if callback.message else None

    if not is_dispatcher(user_id, chat_id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    msg = _safe_message(callback)
    if msg is None:
        await callback.answer("Xabar eskirgan. Qayta harakat qiling.", show_alert=True)
        return

    try:
        order_id = int(callback.data.split(":")[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)

            if order.status not in (OrderStatus.NEW, OrderStatus.REJECTED):
                await callback.answer(
                    f"Buyurtma #{order_id} allaqachon qabul qilingan ({order.status.name}).",
                    show_alert=True,
                )
                return

            # Collect masters from DB
            db_masters = list(
                (await session.scalars(select(User).where(User.is_master == True))).all()  # noqa: E712
            )
            master_by_id: dict[int, User] = {m.telegram_id: m for m in db_masters}

            # Merge with env-configured masters (they may not have registered yet)
            for configured_id in settings.parsed_master_ids:
                if configured_id not in master_by_id:
                    label = _configured_master_label(configured_id)
                    master_by_id[configured_id] = User(
                        telegram_id=configured_id,
                        full_name=label,
                        is_master=True,
                    )

            masters = list(master_by_id.values())

            # Count active jobs per master
            counts_res = await session.execute(
                select(Order.assigned_master_telegram_id, func.count(Order.id))
                .where(Order.status.in_(MASTER_ACTIVE_STATUSES))
                .group_by(Order.assigned_master_telegram_id)
            )
            master_workload = dict(counts_res.all())

    except Exception as exc:
        logger.exception("Error in cb_assign_order: %s", exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    if not masters:
        await callback.answer("Tizimda birorta ham Usta yo'q.", show_alert=True)
        return

    keyboard: list[list[InlineKeyboardButton]] = []
    for m in masters:
        name = m.full_name or f"ID:{m.telegram_id}"
        active_jobs = master_workload.get(m.telegram_id, 0)
        badge = "🟢 Bo'sh" if active_jobs == 0 else f"🟡 {active_jobs} ish"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"👨‍🔧 {name} ({badge})",
                    callback_data=f"select_master:{order_id}:{m.telegram_id}",
                )
            ]
        )

    try:
        await msg.edit_text(
            f"Buyurtma <b>#{order_id}</b> uchun Usta tanlang:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("select_master:"))
async def cb_select_master(callback: CallbackQuery) -> None:
    """Assign the selected master to the order."""
    user_id = callback.from_user.id if callback.from_user else None
    chat_id = callback.message.chat.id if callback.message else None

    if not is_dispatcher(user_id, chat_id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        parts = callback.data.split(":")
        order_id = int(parts[1])
        master_telegram_id = int(parts[2])

        async with AsyncSessionFactory() as session:
            service = OrderService(session)

            # 1. Mark order as ASSIGNED (set dispatcher)
            order = await service.assign_order(
                order_id, dispatcher_telegram_id=callback.from_user.id
            )

            # 2. Record master on the order
            order = await service.assign_master(
                order_id=order.id,
                dispatcher_telegram_id=callback.from_user.id,
                master_telegram_id=master_telegram_id,
            )

            # Resolve master display name
            master_user = await session.scalar(
                select(User).where(User.telegram_id == master_telegram_id)
            )
            master_name = (
                master_user.full_name
                if master_user and master_user.full_name
                else _configured_master_label(master_telegram_id)
            )

            ns = NotificationService(bot=callback.bot, settings=settings)
            # Notify client that a master has been assigned
            await ns.notify_client_status_change(order, order.status)
            # Notify master with order details + Accept/Reject buttons
            await ns.notify_master_new_assignment(order, master_telegram_id)

    except Exception as exc:
        logger.exception("Failed to assign master for order #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_message(callback)
    if msg:
        try:
            await msg.edit_text(
                f"✅ Buyurtma <b>#{order_id}</b> → 👨‍🔧 <b>{master_name}</b> ga biriktirildi.",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer(f"✅ {master_name} ga biriktirildi!")


@router.callback_query(F.data.startswith("dispatch_complete:"))
async def cb_complete_order(callback: CallbackQuery) -> None:
    """Dispatcher confirms master completion → order becomes COMPLETED."""
    user_id = callback.from_user.id if callback.from_user else None
    chat_id = callback.message.chat.id if callback.message else None

    if not is_dispatcher(user_id, chat_id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        order_id = int(callback.data.split(":")[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            # dispatcher_transition no longer enforces dispatcher identity —
            # any authorized dispatcher/admin can complete the order.
            order = await service.dispatcher_transition(
                order_id=order_id,
                dispatcher_telegram_id=callback.from_user.id,
                to_status=OrderStatus.COMPLETED,
            )
            ns = NotificationService(bot=callback.bot, settings=settings)
            # Send completion notification + rating buttons to client
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Failed to complete order #%s: %s", order_id, exc)
        await callback.answer(f"Xatolik: {exc}", show_alert=True)
        return

    msg = _safe_message(callback)
    if msg:
        try:
            await msg.edit_text(
                f"✅ Buyurtma <b>#{order_id}</b> muvaffaqiyatli tasdiqlandi va yakunlandi!",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer("✅ Tasdiqlandi!")


@router.callback_query(F.data.startswith("dispatch_cancel:"))
async def cb_cancel_order(callback: CallbackQuery) -> None:
    """Dispatcher manually cancels an order."""
    user_id = callback.from_user.id if callback.from_user else None
    chat_id = callback.message.chat.id if callback.message else None

    if not is_dispatcher(user_id, chat_id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        order_id = int(callback.data.split(":")[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.dispatcher_cancel_order(order_id)
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Failed to cancel order #%s: %s", order_id, exc)
        await callback.answer(f"Xatolik: {exc}", show_alert=True)
        return

    msg = _safe_message(callback)
    if msg:
        try:
            await msg.edit_text(
                f"🚫 Buyurtma <b>#{order_id}</b> bekor qilindi.", parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass
    await callback.answer("Bekor qilindi.")


@router.callback_query(F.data.startswith("dispatch_detail:"))
async def cb_order_detail_inline(callback: CallbackQuery) -> None:
    """Show order detail card inline."""
    user_id = callback.from_user.id if callback.from_user else None
    chat_id = callback.message.chat.id if callback.message else None

    if not is_dispatcher(user_id, chat_id):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        order_id = int(callback.data.split(":")[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            master_name = "—"
            if order.assigned_master_telegram_id:
                master_user = await session.scalar(
                    select(User).where(User.telegram_id == order.assigned_master_telegram_id)
                )
                if master_user:
                    master_name = master_user.full_name or str(master_user.telegram_id)
    except Exception as exc:
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    text = (
        f"📋 <b>Buyurtma #{order.id}</b>\n"
        f"Status: <b>{order.status.name}</b>\n"
        f"Muammo: {order.issue_label}\n"
        f"Usta: {master_name}"
    )
    buttons = []
    if order.status == OrderStatus.AWAITING_CONFIRM:
        buttons.append(
            [InlineKeyboardButton(text="💰 Tasdiqlash", callback_data=f"dispatch_complete:{order_id}")]
        )
    if order.status not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        buttons.append(
            [InlineKeyboardButton(text="🚫 Bekor qilish", callback_data=f"dispatch_cancel:{order_id}")]
        )

    msg = _safe_message(callback)
    if msg:
        try:
            await msg.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer()
