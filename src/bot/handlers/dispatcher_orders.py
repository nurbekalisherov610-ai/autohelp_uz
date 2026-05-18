"""
Dispatcher order management.
Any user in DISPATCHER_IDS / ADMIN_IDS or posting in DISPATCHER_GROUP_ID
can perform dispatcher actions. Permission checked via is_dispatcher().
"""
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
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


def _safe_msg(cb: CallbackQuery) -> Message | None:
    if cb.message is None or isinstance(cb.message, InaccessibleMessage):
        return None
    return cb.message


def _master_label(master_id: int) -> str:
    m = settings.parsed_master_labels_map
    return m.get(master_id, str(master_id))


# ── Commands ──────────────────────────────────────────────────────────────────

@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_dispatcher(uid, message.chat.id):
        return

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Order.status, func.count(Order.id)).group_by(Order.status)
        )
        s = dict(result.all())

    await message.answer(
        "📊 <b>Jonli Statistika</b>\n\n"
        f"🔴 Yangi: <b>{s.get(OrderStatus.NEW, 0)}</b>\n"
        f"🟠 Rad etilgan: <b>{s.get(OrderStatus.REJECTED, 0)}</b>\n"
        f"🔵 Biriktirilgan: <b>{s.get(OrderStatus.ASSIGNED, 0)}</b>\n"
        f"✅ Qabul: <b>{s.get(OrderStatus.ACCEPTED, 0)}</b>\n"
        f"🚗 Yo'lda: <b>{s.get(OrderStatus.ON_THE_WAY, 0)}</b>\n"
        f"📍 Yetdi: <b>{s.get(OrderStatus.ARRIVED, 0)}</b>\n"
        f"🛠 Ishlamoqda: <b>{s.get(OrderStatus.IN_PROGRESS, 0)}</b>\n"
        f"⏳ Tasdiq kutmoqda: <b>{s.get(OrderStatus.AWAITING_CONFIRM, 0)}</b>\n"
        f"🏁 Yakunlangan: <b>{s.get(OrderStatus.COMPLETED, 0)}</b>\n"
        f"🚫 Bekor: <b>{s.get(OrderStatus.CANCELLED, 0)}</b>\n\n"
        "Buyruqlar: /new_orders · /active_orders · /order &lt;id&gt;",
        parse_mode="HTML",
    )


@router.message(Command("new_orders"))
async def cmd_new_orders(message: Message) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_dispatcher(uid, message.chat.id):
        return

    async with AsyncSessionFactory() as session:
        service = OrderService(session)
        orders = await service.list_orders_by_status(
            [OrderStatus.NEW, OrderStatus.REJECTED], limit=10
        )

    if not orders:
        await message.answer("Yangi buyurtmalar yo'q.")
        return

    await message.answer(f"📦 <b>{len(orders)} ta buyurtma:</b>", parse_mode="HTML")
    for o in orders:
        maps = f"https://maps.google.com/?q={o.latitude},{o.longitude}"
        await message.answer(
            f"🆔 <b>#{o.id}</b> | {o.status.name}\n"
            f"📞 {o.phone} | 🛠 {o.issue_label}\n"
            f'📍 <a href="{maps}">Lokatsiya</a>',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=f"👨‍🔧 Usta biriktirish #{o.id}",
                    callback_data=f"dispatch_assign:{o.id}",
                )
            ]]),
            parse_mode="HTML",
        )


@router.message(Command("active_orders"))
async def cmd_active_orders(message: Message) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_dispatcher(uid, message.chat.id):
        return

    async with AsyncSessionFactory() as session:
        service = OrderService(session)
        orders = await service.list_orders_by_status(
            list(MASTER_ACTIVE_STATUSES), limit=20
        )

    if not orders:
        await message.answer("Faol buyurtmalar yo'q.")
        return

    for o in orders:
        buttons: list[list[InlineKeyboardButton]] = []
        if o.status == OrderStatus.AWAITING_CONFIRM:
            buttons.append([
                InlineKeyboardButton(
                    text="💰 Tasdiqlash", callback_data=f"dispatch_complete:{o.id}"
                )
            ])
        buttons.append([
            InlineKeyboardButton(
                text="📋 Tafsilot", callback_data=f"dispatch_detail:{o.id}"
            )
        ])
        await message.answer(
            f"#{o.id} | <b>{o.status.name}</b> | {o.issue_label}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML",
        )


@router.message(Command("order"))
async def cmd_order_detail(message: Message) -> None:
    uid = message.from_user.id if message.from_user else None
    if not is_dispatcher(uid, message.chat.id):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Format: /order &lt;id&gt;", parse_mode="HTML")
        return

    try:
        order_id = int(parts[1])
    except ValueError:
        await message.answer("ID raqam bo'lishi kerak.")
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            master_name = "—"
            if order.assigned_master_telegram_id:
                master_user = await session.scalar(
                    select(User).where(User.telegram_id == order.assigned_master_telegram_id)
                )
                master_name = (master_user.full_name if master_user else None) or \
                              _master_label(order.assigned_master_telegram_id)
    except Exception as exc:
        await message.answer(f"Xatolik: {exc}")
        return

    amount_str = f"{float(order.final_amount):,.0f} so'm" if order.final_amount else "—"
    buttons = []
    if order.status in (OrderStatus.NEW, OrderStatus.REJECTED):
        buttons.append([
            InlineKeyboardButton(text="📝 Usta biriktirish", callback_data=f"dispatch_assign:{order.id}")
        ])
    if order.status == OrderStatus.AWAITING_CONFIRM:
        buttons.append([
            InlineKeyboardButton(text="💰 Tasdiqlash", callback_data=f"dispatch_complete:{order.id}")
        ])
    if order.status not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        buttons.append([
            InlineKeyboardButton(text="🚫 Bekor", callback_data=f"dispatch_cancel:{order.id}")
        ])

    await message.answer(
        f"📋 <b>Buyurtma #{order.id}</b>\n"
        f"Status: <b>{order.status.name}</b>\n"
        f"Muammo: {order.issue_label}\n"
        f"Telefon: <b>{order.phone}</b>\n"
        f"Usta: {master_name}\n"
        f"Summa: {amount_str}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
        parse_mode="HTML",
    )


# ── Assign order → show master list ──────────────────────────────────────────

@router.callback_query(F.data.startswith("dispatch_assign:"))
async def cb_assign_order(callback: CallbackQuery) -> None:
    uid = callback.from_user.id if callback.from_user else None
    cid = callback.message.chat.id if callback.message else None
    if not is_dispatcher(uid, cid):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)

            if order.status not in (OrderStatus.NEW, OrderStatus.REJECTED):
                await callback.answer(
                    f"Buyurtma allaqachon {order.status.name} holatida.",
                    show_alert=True,
                )
                return

            # Get all masters: from DB + from env config
            db_masters = list(await session.scalars(
                select(User).where(User.is_master == True)  # noqa: E712
            ))
            master_by_id: dict[int, User] = {m.telegram_id: m for m in db_masters}

            for mid in settings.parsed_master_ids:
                if mid not in master_by_id:
                    label = _master_label(mid)
                    master_by_id[mid] = User(
                        telegram_id=mid, full_name=label, is_master=True
                    )

            # Workload count
            counts = await session.execute(
                select(Order.assigned_master_telegram_id, func.count(Order.id))
                .where(Order.status.in_(MASTER_ACTIVE_STATUSES))
                .group_by(Order.assigned_master_telegram_id)
            )
            workload = dict(counts.all())

    except Exception as exc:
        logger.exception("cb_assign_order error: %s", exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    masters = list(master_by_id.values())
    if not masters:
        await callback.answer("Tizimda usta yo'q.", show_alert=True)
        return

    keyboard: list[list[InlineKeyboardButton]] = []
    for m in masters:
        name = m.full_name or f"ID:{m.telegram_id}"
        active = workload.get(m.telegram_id, 0)
        badge = "🟢 Bo'sh" if active == 0 else f"🟡 {active} ish"
        keyboard.append([
            InlineKeyboardButton(
                text=f"👨‍🔧 {name} ({badge})",
                callback_data=f"select_master:{order_id}:{m.telegram_id}",
            )
        ])

    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"Buyurtma <b>#{order_id}</b> uchun Usta tanlang:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer()


# ── Select master → assign ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("select_master:"))
async def cb_select_master(callback: CallbackQuery) -> None:
    uid = callback.from_user.id if callback.from_user else None
    cid = callback.message.chat.id if callback.message else None
    if not is_dispatcher(uid, cid):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        parts = (callback.data or "").split(":")
        order_id = int(parts[1])
        master_id = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)

            # ASSIGNED + record master
            order = await service.assign_order(
                order_id, dispatcher_telegram_id=callback.from_user.id
            )
            order = await service.assign_master(
                order_id=order.id,
                dispatcher_telegram_id=callback.from_user.id,
                master_telegram_id=master_id,
            )

            # Get client info for notification
            client = await session.scalar(
                select(User).where(User.id == order.client_id)
            )
            client_telegram_id = client.telegram_id if client else None
            client_language = client.language if client else None

            # Get master name
            master_user = await session.scalar(
                select(User).where(User.telegram_id == master_id)
            )
            master_name = (
                (master_user.full_name if master_user else None) or _master_label(master_id)
            )

            # Capture scalars before session closes
            _order_id = order.id
            _phone = order.phone
            _issue = order.issue_label
            _lat = order.latitude
            _lon = order.longitude

        ns = NotificationService(bot=callback.bot, settings=settings)

        # Notify client
        if client_telegram_id:
            await ns.notify_client_status_change(
                order_id=_order_id,
                client_telegram_id=client_telegram_id,
                client_language=client_language,
                status=OrderStatus.ASSIGNED,
            )

        # Notify master
        await ns.notify_master_new_assignment(
            order_id=_order_id,
            phone=_phone,
            issue_label=_issue,
            latitude=_lat,
            longitude=_lon,
            master_telegram_id=master_id,
        )

    except Exception as exc:
        logger.exception("cb_select_master error for order #%s: %s", order_id, exc)
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"✅ Buyurtma <b>#{order_id}</b> → 👨‍🔧 <b>{master_name}</b> ga biriktirildi.",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer(f"✅ {master_name} ga biriktirildi!")


# ── Complete order (dispatcher confirms payment) ───────────────────────────────

@router.callback_query(F.data.startswith("dispatch_complete:"))
async def cb_complete_order(callback: CallbackQuery) -> None:
    uid = callback.from_user.id if callback.from_user else None
    cid = callback.message.chat.id if callback.message else None
    if not is_dispatcher(uid, cid):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.dispatcher_transition(
                order_id=order_id,
                dispatcher_telegram_id=callback.from_user.id,
                to_status=OrderStatus.COMPLETED,
            )
            # Get client info
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
                status=OrderStatus.COMPLETED,
            )

    except Exception as exc:
        logger.exception("cb_complete_order error for #%s: %s", order_id, exc)
        await callback.answer(f"Xatolik: {exc}", show_alert=True)
        return

    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"✅ Buyurtma <b>#{order_id}</b> tasdiqlandi va yakunlandi!",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer("✅ Tasdiqlandi!")


# ── Cancel order ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("dispatch_cancel:"))
async def cb_cancel_order(callback: CallbackQuery) -> None:
    uid = callback.from_user.id if callback.from_user else None
    cid = callback.message.chat.id if callback.message else None
    if not is_dispatcher(uid, cid):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.dispatcher_cancel_order(order_id)
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
                status=OrderStatus.CANCELLED,
            )
    except Exception as exc:
        logger.exception("cb_cancel_order error for #%s: %s", order_id, exc)
        await callback.answer(f"Xatolik: {exc}", show_alert=True)
        return

    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"🚫 Buyurtma <b>#{order_id}</b> bekor qilindi.", parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass
    await callback.answer("Bekor qilindi.")


# ── Order detail inline ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("dispatch_detail:"))
async def cb_order_detail(callback: CallbackQuery) -> None:
    uid = callback.from_user.id if callback.from_user else None
    cid = callback.message.chat.id if callback.message else None
    if not is_dispatcher(uid, cid):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    try:
        order_id = int((callback.data or "").split(":")[1])
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            master_name = "—"
            if order.assigned_master_telegram_id:
                mu = await session.scalar(
                    select(User).where(User.telegram_id == order.assigned_master_telegram_id)
                )
                master_name = (mu.full_name if mu else None) or \
                              _master_label(order.assigned_master_telegram_id)
    except Exception as exc:
        await callback.answer(str(exc)[:200], show_alert=True)
        return

    buttons = []
    if order.status == OrderStatus.AWAITING_CONFIRM:
        buttons.append([
            InlineKeyboardButton(text="💰 Tasdiqlash", callback_data=f"dispatch_complete:{order.id}")
        ])
    if order.status not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
        buttons.append([
            InlineKeyboardButton(text="🚫 Bekor", callback_data=f"dispatch_cancel:{order.id}")
        ])

    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"📋 <b>#{order.id}</b> | {order.status.name}\n"
                f"Usta: {master_name}\n"
                f"Summa: {float(order.final_amount):,.0f} so'm" if order.final_amount else
                f"📋 <b>#{order.id}</b> | {order.status.name}\nUsta: {master_name}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None,
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass
    await callback.answer()
