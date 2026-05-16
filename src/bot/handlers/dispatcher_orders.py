import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from src.bot.utils.permissions import is_dispatcher
from src.core.config import get_settings
from src.db.enums import OrderStatus
from src.db.models.order import Order
from src.db.models.user import User
from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService
from src.services.order_service import (
    MASTER_ACTIVE_STATUSES,
    OrderService,
)

logger = logging.getLogger(__name__)
router = Router(name="dispatcher_orders")
settings = get_settings()


def _configured_master_label(master_id: int) -> str:
    ids = settings.parsed_master_ids
    labels = settings.parsed_master_labels
    try:
        index = ids.index(master_id)
    except ValueError:
        return str(master_id)
    if index < len(labels) and labels[index]:
        return labels[index]
    return str(master_id)


def _safe_message(callback: CallbackQuery) -> Message | None:
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return None
    return msg


def _order_card_text(order_id: int, phone: str, issue_label: str, latitude: float, longitude: float, status_name: str) -> str:
    return (
        f"Buyurtma: #{order_id}\n"
        f"Telefon: {phone}\n"
        f"Muammo: {issue_label}\n"
        f"Lokatsiya: https://maps.google.com/?q={latitude},{longitude}\n"
        f"Status: {status_name}"
    )


def _assign_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Qabul qilish #{order_id}",
                    callback_data=f"dispatch_assign:{order_id}",
                )
            ]
        ]
    )


@router.message(Command("new_orders"))
async def list_new_orders(message: Message) -> None:
    if not is_dispatcher(message.from_user.id if message.from_user else None, message.chat.id):
        return

    async with AsyncSessionFactory() as session:
        service = OrderService(session)
        orders = await service.list_orders_by_status([OrderStatus.NEW, OrderStatus.REJECTED], limit=10)

    if not orders:
        await message.answer("Hozircha NEW yoki REJECTED buyurtmalar yo'q.")
        return

    await message.answer(f"Topildi: {len(orders)} ta buyurtma kutilmoqda")
    for order in orders:
        await message.answer(
            _order_card_text(
                order_id=order.id,
                phone=order.phone,
                issue_label=order.issue_label,
                latitude=order.latitude,
                longitude=order.longitude,
                status_name=order.status.name,
            ),
            reply_markup=_assign_kb(order.id),
        )


@router.callback_query(F.data.startswith("dispatch_assign:"))
async def cb_assign_order(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_dispatcher(callback.from_user.id if callback.from_user else None, callback.message.chat.id if callback.message else None):
        await callback.answer("Ruxsat yo'q", show_alert=True)
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
                await callback.answer(f"Buyurtma #{order_id} allaqachon qabul qilingan.", show_alert=True)
                return

            db_masters = list((await session.scalars(select(User).where(User.is_master))).all())
            master_by_id = {master.telegram_id: master for master in db_masters}
            for configured_id in settings.parsed_master_ids:
                if configured_id not in master_by_id:
                    master_by_id[configured_id] = User(
                        telegram_id=configured_id,
                        full_name=_configured_master_label(configured_id),
                        is_master=True,
                    )
            masters = list(master_by_id.values())

            counts_res = await session.execute(
                select(Order.assigned_master_telegram_id, func.count(Order.id))
                .where(Order.status.in_(MASTER_ACTIVE_STATUSES))
                .group_by(Order.assigned_master_telegram_id)
            )
            master_workload = dict(counts_res.all())
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    if not masters:
        await callback.answer("Tizimda birorta ham Master yo'q.", show_alert=True)
        return

    keyboard = []
    for m in masters:
        name = m.full_name or f"ID:{m.telegram_id}"
        active_jobs = master_workload.get(m.telegram_id, 0)
        badge = "🟢" if active_jobs == 0 else f"🟡{active_jobs}"
        keyboard.append([InlineKeyboardButton(text=f"👨‍🔧 {name} ({badge})", callback_data=f"select_master:{order_id}:{m.telegram_id}")])

    try:
        await msg.edit_text(f"Buyurtma #{order_id} ga Master tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    except TelegramBadRequest: pass
    await callback.answer()


@router.callback_query(F.data.startswith("select_master:"))
async def cb_select_master(callback: CallbackQuery) -> None:
    if not is_dispatcher(callback.from_user.id if callback.from_user else None, callback.message.chat.id if callback.message else None):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    try:
        parts = callback.data.split(":")
        order_id, master_telegram_id = int(parts[1]), int(parts[2])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            master_user = await session.scalar(select(User).where(User.telegram_id == master_telegram_id))
            master_name = master_user.full_name if master_user and master_user.full_name else str(master_telegram_id)
            
            order = await service.assign_order(order_id, dispatcher_telegram_id=callback.from_user.id)
            order = await service.assign_master(order_id=order.id, dispatcher_telegram_id=callback.from_user.id, master_telegram_id=master_telegram_id)
            
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
            await ns.notify_master_new_assignment(order, master_telegram_id)
    except Exception as exc:
        logger.exception("Failed to assign master: %s", exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_message(callback)
    if msg:
        try: await msg.edit_text(f"✅ Buyurtma #{order_id} 👨‍🔧 {master_name} ga biriktirildi.")
        except TelegramBadRequest: pass
    await callback.answer()


@router.callback_query(F.data.startswith("dispatch_complete:"))
async def cb_complete_order(callback: CallbackQuery) -> None:
    if not is_dispatcher(callback.from_user.id if callback.from_user else None, callback.message.chat.id if callback.message else None):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    try:
        order_id = int(callback.data.split(":")[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            actual_dispatcher = order.assigned_dispatcher_telegram_id or callback.from_user.id
            order = await service.dispatcher_transition(order_id=order_id, dispatcher_telegram_id=actual_dispatcher, to_status=OrderStatus.COMPLETED)
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        await callback.answer(f"Xatolik: {exc}", show_alert=True)
        return

    msg = _safe_message(callback)
    if msg:
        try: await msg.edit_text(f"✅ Buyurtma #{order_id} muvaffaqiyatli tasdiqlandi.")
        except TelegramBadRequest: pass
    await callback.answer()


@router.callback_query(F.data.startswith("dispatch_cancel:"))
async def cb_cancel_order(callback: CallbackQuery) -> None:
    if not is_dispatcher(callback.from_user.id if callback.from_user else None, callback.message.chat.id if callback.message else None):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    try:
        order_id = int(callback.data.split(":")[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.dispatcher_cancel_order(order_id)
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        await callback.answer(f"Xatolik: {exc}", show_alert=True)
        return

    msg = _safe_message(callback)
    if msg:
        try: await msg.edit_text(f"🚫 Buyurtma #{order_id} bekor qilindi.")
        except TelegramBadRequest: pass
    await callback.answer()


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message) -> None:
    if not is_dispatcher(message.from_user.id if message.from_user else None, message.chat.id):
        return

    async with AsyncSessionFactory() as session:
        query = select(Order.status, func.count(Order.id)).group_by(Order.status)
        result = await session.execute(query)
        s = dict(result.all())

    text = (
        "📊 Jonli Statistika\n\n"
        f"🔴 Kutilayotgan: {s.get(OrderStatus.NEW, 0)} ta\n"
        f"🟠 Rad etilgan: {s.get(OrderStatus.REJECTED, 0)} ta\n"
        f"🔵 Biriktirilgan: {s.get(OrderStatus.ASSIGNED, 0)} ta\n"
        f"✅ Qabul qilingan: {s.get(OrderStatus.ACCEPTED, 0)} ta\n"
        f"🟡 Yo'lda: {s.get(OrderStatus.ON_THE_WAY, 0)} ta\n"
        f"⏳ Tasdiq kutmoqda: {s.get(OrderStatus.AWAITING_CONFIRM, 0)} ta\n"
        f"🏁 Yakunlangan: {s.get(OrderStatus.COMPLETED, 0)} ta\n\n"
        "Buyruqlar: /new_orders, /active_orders, /order <id>"
    )
    await message.answer(text)


@router.message(Command("order"))
async def cmd_order_detail(message: Message) -> None:
    if not is_dispatcher(message.from_user.id if message.from_user else None, message.chat.id):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Format: /order <id>")
        return

    try:
        order_id = int(parts[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            master_name = "—"
            if order.assigned_master_telegram_id:
                master_user = await session.scalar(select(User).where(User.telegram_id == order.assigned_master_telegram_id))
                if master_user: master_name = master_user.full_name or str(master_user.telegram_id)
    except Exception as exc:
        await message.answer(f"Xatolik: {exc}")
        return

    text = (
        f"📋 Buyurtma #{order.id}\n\n"
        f"Status: {order.status.name}\n"
        f"Muammo: {order.issue_label}\n"
        f"Telefon: {order.phone}\n"
        f"Master: {master_name}\n"
        f"Summa: {float(order.final_amount or 0):,.0f} so'm\n"
    )

    buttons = []
    if order.status in (OrderStatus.NEW, OrderStatus.REJECTED):
        buttons.append([InlineKeyboardButton(text="📝 Master biriktirish", callback_data=f"dispatch_assign:{order.id}")])
    if order.status == OrderStatus.AWAITING_CONFIRM:
        buttons.append([InlineKeyboardButton(text="💰 Tasdiqlash", callback_data=f"dispatch_complete:{order.id}")])
    if order.status not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        buttons.append([InlineKeyboardButton(text="🚫 Bekor qilish", callback_data=f"dispatch_cancel:{order.id}")])

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None)


@router.message(Command("active_orders"))
async def cmd_active_orders(message: Message) -> None:
    if not is_dispatcher(message.from_user.id if message.from_user else None, message.chat.id):
        return

    async with AsyncSessionFactory() as session:
        service = OrderService(session)
        orders = await service.list_orders_by_status([OrderStatus.ASSIGNED, OrderStatus.ACCEPTED, OrderStatus.ON_THE_WAY, OrderStatus.ARRIVED, OrderStatus.IN_PROGRESS, OrderStatus.AWAITING_CONFIRM], limit=20)

    if not orders:
        await message.answer("Faol buyurtmalar yo'q.")
        return

    for o in orders:
        buttons = [[InlineKeyboardButton(text="📋 Tafsilot", callback_data=f"dispatch_detail:{o.id}")]]
        if o.status == OrderStatus.AWAITING_CONFIRM:
            buttons.insert(0, [InlineKeyboardButton(text="💰 Tasdiqlash", callback_data=f"dispatch_complete:{o.id}")])
        await message.answer(f"#{o.id} | {o.status.name} | {o.issue_label} | {o.phone}", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("dispatch_detail:"))
async def cb_order_detail_inline(callback: CallbackQuery) -> None:
    if not is_dispatcher(callback.from_user.id if callback.from_user else None, callback.message.chat.id if callback.message else None):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    try:
        order_id = int(callback.data.split(":")[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            master_name = "—"
            if order.assigned_master_telegram_id:
                master_user = await session.scalar(select(User).where(User.telegram_id == order.assigned_master_telegram_id))
                if master_user: master_name = master_user.full_name or str(master_user.telegram_id)
    except Exception as exc:
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    text = f"📋 Buyurtma #{order.id}\nStatus: {order.status.name}\nMuammo: {order.issue_label}\nMaster: {master_name}"
    buttons = []
    if order.status == OrderStatus.AWAITING_CONFIRM:
        buttons.append([InlineKeyboardButton(text="💰 Tasdiqlash", callback_data=f"dispatch_complete:{order_id}")])
    buttons.append([InlineKeyboardButton(text="🚫 Bekor qilish", callback_data=f"dispatch_cancel:{order_id}")])

    msg = _safe_message(callback)
    if msg:
        try: await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        except TelegramBadRequest: pass
    await callback.answer()
