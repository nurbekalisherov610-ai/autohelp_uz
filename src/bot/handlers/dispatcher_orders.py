import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

logger = logging.getLogger(__name__)

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

router = Router(name="dispatcher_orders")
settings = get_settings()


def _dispatcher_user_ids() -> set[int]:
    """Return set of user IDs allowed to perform dispatcher actions."""
    ids = set(settings.parsed_dispatcher_ids)
    # Admins also get dispatcher permissions (Superadmins)
    ids.update(settings.parsed_admin_ids)
    
    if settings.dispatcher_chat_id and settings.dispatcher_chat_id > 0:
        ids.add(settings.dispatcher_chat_id)
    if settings.admin_chat_id and settings.admin_chat_id > 0:
        ids.add(settings.admin_chat_id)
        
    return {i for i in ids if i and i not in PLACEHOLDER_CHAT_IDS}


def _dispatcher_chat_ids() -> set[int]:
    return {
        chat_id
        for chat_id in (settings.dispatcher_group_id, settings.dispatcher_chat_id)
        if chat_id is not None
    }


def _is_dispatcher_context(chat_id: int, user_id: int | None) -> bool:
    """Check if the current message/callback comes from an authorized dispatcher context."""
    user_ids = _dispatcher_user_ids()
    chat_ids = _dispatcher_chat_ids()
    
    # If no restrictions configured, allow everyone (dev mode)
    if not user_ids and not chat_ids and settings.resolved_dispatcher_chat_id is None:
        return True
        
    # 1. Check if specific user is an authorized dispatcher/admin
    if user_id is not None and user_id in user_ids:
        return True
        
    # 2. Check if interaction is happening within an authorized group chat
    # (Only if no specific user whitelist is strictly enforced, or if user is unknown)
    if chat_id in chat_ids:
        return True
        
    return False


def _is_dispatcher_message(message: Message) -> bool:
    return _is_dispatcher_context(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else None,
    )


def _is_dispatcher_callback(callback: CallbackQuery) -> bool:
    msg = _safe_message(callback)
    if msg is None:
        # Fallback: if message is inaccessible, check user-only context
        user_id = callback.from_user.id if callback.from_user else None
        if user_id is not None and user_id in _dispatcher_user_ids():
            return True
        return False
    return _is_dispatcher_context(
        chat_id=msg.chat.id,
        user_id=callback.from_user.id if callback.from_user else None,
    )


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
    """Return the real Message object or None if the message is inaccessible."""
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
    if not _is_dispatcher_message(message):
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
    if not _is_dispatcher_callback(callback):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    msg = _safe_message(callback)
    if msg is None:
        await callback.answer("Xabar eskirgan. Qayta harakat qiling.", show_alert=True)
        return

    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri buyurtma ID.", show_alert=True)
        return

    # Verify order still exists and is assignable before showing master list
    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            if order.status not in (OrderStatus.NEW, OrderStatus.REJECTED):
                await callback.answer(
                    f"Buyurtma #{order_id} allaqachon qabul qilingan ({order.status.name}).",
                    show_alert=True,
                )
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

            active_counts_query = (
                select(Order.assigned_master_telegram_id, func.count(Order.id))
                .where(Order.status.in_(MASTER_ACTIVE_STATUSES))
                .where(Order.assigned_master_telegram_id.isnot(None))
                .group_by(Order.assigned_master_telegram_id)
            )
            counts_res = await session.execute(active_counts_query)
            master_workload = dict(counts_res.all())
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    if not masters:
        await callback.answer(
            "Tizimda birorta ham Master yo'q. MASTER_IDS sozlang yoki /register_master orqali qo'shing.",
            show_alert=True,
        )
        return

    keyboard = []
    for m in masters:
        name = m.full_name or f"ID:{m.telegram_id}"
        active_jobs = master_workload.get(m.telegram_id, 0)
        badge = "🟢" if active_jobs == 0 else f"🟡{active_jobs}"
        keyboard.append([
            InlineKeyboardButton(
                text=f"👨‍🔧 {name} ({badge})",
                callback_data=f"select_master:{order_id}:{m.telegram_id}",
            )
        ])

    try:
        await msg.edit_text(
            f"Buyurtma #{order_id} ga biriktirish uchun Masterlardan birini tanlang:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("select_master:"))
async def cb_select_master(callback: CallbackQuery) -> None:
    if not _is_dispatcher_callback(callback):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    try:
        parts = callback.data.split(":")
        order_id = int(parts[1])
        master_telegram_id = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri master tanlovi.", show_alert=True)
        return
    dispatcher_telegram_id = callback.from_user.id

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)

            master_user = await session.scalar(select(User).where(User.telegram_id == master_telegram_id))
            master_name = master_user.full_name if master_user and master_user.full_name else str(master_telegram_id)

            # 1. Assign to dispatcher first (like before)
            order = await service.assign_order(order_id, dispatcher_telegram_id=dispatcher_telegram_id)
            # 2. Then assign master
            order = await service.assign_master(
                order_id=order.id,
                dispatcher_telegram_id=dispatcher_telegram_id,
                master_telegram_id=master_telegram_id,
            )
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
            await ns.notify_master_new_assignment(order, master_telegram_id)
    except Exception as exc:
        logger.exception("Failed to assign master for order #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(f"✅ Buyurtma #{order.id} 👨‍🔧 {master_name} ga muvaffaqiyatli biriktirildi.")
        except TelegramBadRequest:
            pass
    await callback.answer()




@router.callback_query(F.data.startswith("dispatch_complete:"))
async def cb_complete_order(callback: CallbackQuery) -> None:
    if not _is_dispatcher_callback(callback):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri buyurtma ID.", show_alert=True)
        return
    dispatcher_telegram_id = callback.from_user.id

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)

            # In group chats any dispatcher can confirm; use the original assigner
            actual_dispatcher = order.assigned_dispatcher_telegram_id or dispatcher_telegram_id

            order = await service.dispatcher_transition(
                order_id=order_id,
                dispatcher_telegram_id=actual_dispatcher,
                to_status=OrderStatus.COMPLETED,
            )
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Failed to complete order #%s: %s", order_id, exc)
        await callback.answer(f"Xatolik: {exc}"[:200], show_alert=True)
        return

    amount_text = f"{order.final_amount:,.0f}" if order.final_amount else "—"
    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(
                f"✅ Buyurtma #{order.id} muvaffaqiyatli tasdiqlandi.\nSumma: {amount_text} so'm"
            )
        except TelegramBadRequest:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("dispatch_cancel:"))
async def cb_cancel_order(callback: CallbackQuery) -> None:
    if not _is_dispatcher_callback(callback):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri buyurtma ID.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.dispatcher_cancel_order(order_id)
            ns = NotificationService(bot=callback.bot, settings=settings)
            await ns.notify_client_status_change(order, order.status)
    except Exception as exc:
        logger.exception("Failed to cancel order #%s: %s", order_id, exc)
        await callback.answer(f"Xatolik: {exc}"[:200], show_alert=True)
        return

    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(f"🚫 Buyurtma #{order.id} bekor qilindi.")
        except TelegramBadRequest:
            pass
    await callback.answer()


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message) -> None:
    if not _is_dispatcher_message(message):
        return

    async with AsyncSessionFactory() as session:
        query = select(Order.status, func.count(Order.id)).group_by(Order.status)
        result = await session.execute(query)
        status_counts = dict(result.all())

    new = status_counts.get(OrderStatus.NEW, 0)
    rejected = status_counts.get(OrderStatus.REJECTED, 0)
    assigned = status_counts.get(OrderStatus.ASSIGNED, 0)
    accepted = status_counts.get(OrderStatus.ACCEPTED, 0)
    on_way = status_counts.get(OrderStatus.ON_THE_WAY, 0)
    arrived = status_counts.get(OrderStatus.ARRIVED, 0)
    in_prog = status_counts.get(OrderStatus.IN_PROGRESS, 0)
    awaiting = status_counts.get(OrderStatus.AWAITING_CONFIRM, 0)
    completed = status_counts.get(OrderStatus.COMPLETED, 0)

    text = (
        "📊 Dispecher Jonli Statistikasi\n\n"
        f"🔴 Kutilayotgan (NEW): {new} ta\n"
        f"🟠 Rad etilgan (REJECTED): {rejected} ta\n"
        f"🔵 Biriktirilgan (ASSIGNED): {assigned} ta\n"
        f"✅ Qabul qilingan (ACCEPTED): {accepted} ta\n"
        f"🟡 Yo'lda (ON WAY): {on_way} ta\n"
        f"📍 Manzilda (ARRIVED): {arrived} ta\n"
        f"🛠 Ta'mirlanmoqda (IN PROGRESS): {in_prog} ta\n"
        f"⏳ Tasdiq kutmoqda: {awaiting} ta\n"
        f"🏁 Yakunlangan (COMPLETED): {completed} ta\n\n"
        "Buyruqlar:\n"
        "/new_orders — Yangi buyurtmalar\n"
        "/active_orders — Faol buyurtmalar\n"
        "/order <id> — Buyurtma tafsilotlari"
    )
    await message.answer(text)


@router.message(Command("order"))
async def cmd_order_detail(message: Message) -> None:
    if not _is_dispatcher_message(message):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Format: /order <buyurtma_id>\nMasalan: /order 5")
        return

    try:
        order_id = int(parts[1])
    except ValueError:
        await message.answer("Buyurtma ID raqam bo'lishi kerak.")
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
    except Exception as exc:
        await message.answer(f"Xatolik: {exc}")
        return

    master_name = "—"
    if order.assigned_master_telegram_id:
        async with AsyncSessionFactory() as session:
            master_user = await session.scalar(
                select(User).where(User.telegram_id == order.assigned_master_telegram_id)
            )
            if master_user:
                master_name = master_user.full_name or str(master_user.telegram_id)

    amount_text = f"{order.final_amount:,.0f} so'm" if order.final_amount else "—"
    rating_text = f"{'⭐' * order.rating}" if order.rating else "—"

    text = (
        f"📋 Buyurtma #{order.id}\n\n"
        f"Status: {order.status.name}\n"
        f"Muammo: {order.issue_label}\n"
        f"Telefon: {order.phone}\n"
        f"Lokatsiya: https://maps.google.com/?q={order.latitude},{order.longitude}\n"
        f"Master: {master_name}\n"
        f"Summa: {amount_text}\n"
        f"Baho: {rating_text}\n"
        f"Yaratilgan: {order.created_at}\n"
    )

    # Build action buttons based on current status
    buttons = []
    if order.status in (OrderStatus.NEW, OrderStatus.REJECTED):
        buttons.append([InlineKeyboardButton(
            text="📝 Master biriktirish",
            callback_data=f"dispatch_assign:{order.id}",
        )])
    if order.status == OrderStatus.AWAITING_CONFIRM:
        buttons.append([InlineKeyboardButton(
            text="💰 Tasdiqlash",
            callback_data=f"dispatch_complete:{order.id}",
        )])
    if order.status not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        buttons.append([InlineKeyboardButton(
            text="🚫 Bekor qilish",
            callback_data=f"dispatch_cancel:{order.id}",
        )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await message.answer(text, reply_markup=kb)


@router.message(Command("active_orders"))
async def cmd_active_orders(message: Message) -> None:
    if not _is_dispatcher_message(message):
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
        await message.answer("Hozir faol buyurtmalar yo'q.")
        return

    await message.answer(f"Faol buyurtmalar: {len(orders)} ta")
    for order in orders:
        text = (
            f"#{order.id} | {order.status.name} | {order.issue_label} | {order.phone}"
        )
        buttons = []
        if order.status == OrderStatus.AWAITING_CONFIRM:
            buttons.append([InlineKeyboardButton(
                text="💰 Tasdiqlash",
                callback_data=f"dispatch_complete:{order.id}",
            )])
        if order.status not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
            buttons.append([InlineKeyboardButton(
                text="📋 Tafsilot",
                callback_data=f"dispatch_detail:{order.id}",
            )])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("dispatch_detail:"))
async def cb_order_detail_inline(callback: CallbackQuery) -> None:
    if not _is_dispatcher_callback(callback):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri buyurtma ID.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
    except Exception as exc:
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    master_name = "—"
    if order.assigned_master_telegram_id:
        async with AsyncSessionFactory() as session:
            master_user = await session.scalar(
                select(User).where(User.telegram_id == order.assigned_master_telegram_id)
            )
            if master_user:
                master_name = master_user.full_name or str(master_user.telegram_id)

    amount_text = f"{order.final_amount:,.0f} so'm" if order.final_amount else "—"

    text = (
        f"📋 Buyurtma #{order.id}\n"
        f"Status: {order.status.name}\n"
        f"Muammo: {order.issue_label}\n"
        f"Telefon: {order.phone}\n"
        f"Master: {master_name}\n"
        f"Summa: {amount_text}\n"
    )

    buttons = []
    if order.status in (OrderStatus.NEW, OrderStatus.REJECTED):
        buttons.append([InlineKeyboardButton(
            text="📝 Master biriktirish",
            callback_data=f"dispatch_assign:{order.id}",
        )])
    if order.status == OrderStatus.AWAITING_CONFIRM:
        buttons.append([InlineKeyboardButton(
            text="💰 Tasdiqlash",
            callback_data=f"dispatch_complete:{order.id}",
        )])
    if order.status not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        buttons.append([InlineKeyboardButton(
            text="🚫 Bekor qilish",
            callback_data=f"dispatch_cancel:{order.id}",
        )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    msg = _safe_message(callback)
    if msg is not None:
        try:
            await msg.edit_text(text, reply_markup=kb)
        except TelegramBadRequest:
            pass
    await callback.answer()
