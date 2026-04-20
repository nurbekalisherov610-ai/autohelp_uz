"""
AutoHelp.uz - Master Handler
Handles master availability, order acceptance, status updates,
payment entry, and video confirmation.
"""
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.role_filter import RoleFilter
from bot.states.master_states import MasterOrderStates
from bot.keyboards.master_kb import (
    master_main_menu, master_order_response,
    master_status_update_keyboard,
)
from locales.texts import t
from models.master import Master, MasterStatus
from models.order import OrderStatus
from services.order_service import OrderService
from services.notification_service import NotificationService
from repositories.order_repo import OrderRepo
from repositories.master_repo import MasterRepo
from repositories.stats_repo import StatsRepo

router = Router(name="master")


# ── Master /start ─────────────────────────────────────────────────

@router.message(RoleFilter("master"), F.text == "/start")
async def master_start(
    message: Message,
    user_data: Master | None = None,
):
    """Master main menu."""
    is_online = user_data.status == MasterStatus.ONLINE if user_data else False
    await message.answer(
        f"👨‍🔧 <b>Usta paneli</b>\n\n"
        f"Holat: {'🟢 Online' if is_online else '🔴 Offline'}",
        parse_mode="HTML",
        reply_markup=master_main_menu(is_online),
    )


# ── Toggle availability ──────────────────────────────────────────

@router.message(
    RoleFilter("master"),
    F.text.in_(["🟢 Online bo'lish", "🔴 Offline bo'lish"]),
)
async def toggle_availability(
    message: Message,
    session: AsyncSession,
    user_data: Master | None = None,
):
    """Toggle master online/offline status."""
    if not user_data:
        return

    master_repo = MasterRepo(session)
    new_status = await master_repo.toggle_status(message.from_user.id)

    is_online = new_status == MasterStatus.ONLINE
    status_text = t("master_toggle_online" if is_online else "master_toggle_offline", "uz")

    await message.answer(
        status_text,
        reply_markup=master_main_menu(is_online),
    )


# ── Statistics ────────────────────────────────────────────────────

@router.message(RoleFilter("master"), F.text == "📊 Statistika")
async def master_stats(
    message: Message,
    session: AsyncSession,
    user_data: Master | None = None,
):
    """Show master's personal statistics."""
    if not user_data:
        return

    from datetime import datetime, timedelta
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    master_repo = MasterRepo(session)
    today_stats = await master_repo.get_master_stats(user_data.id, since=today)
    weekly_stats = await master_repo.get_master_stats(user_data.id, since=week_start)
    monthly_stats = await master_repo.get_master_stats(user_data.id, since=month_start)

    await message.answer(
        t(
            "master_stats", "uz",
            today=today_stats["completed_orders"],
            weekly=weekly_stats["completed_orders"],
            monthly=monthly_stats["completed_orders"],
            monthly_sum=f"{monthly_stats['total_sum']:,.0f}",
            rating=f"{user_data.rating:.1f}",
        ),
        parse_mode="HTML",
    )


@router.message(RoleFilter("master"), F.text == "⭐ Reytingim")
async def master_rating(
    message: Message,
    user_data: Master | None = None,
):
    """Show master's rating."""
    if not user_data:
        return

    stars = "⭐" * round(user_data.rating)
    await message.answer(
        f"⭐ <b>Sizning reytingingiz:</b> {user_data.rating:.1f}/5.0\n"
        f"{stars}\n\n"
        f"✅ Bajarilgan buyurtmalar: {user_data.completed_orders}\n"
        f"❌ Rad etilgan: {user_data.rejected_orders}",
        parse_mode="HTML",
    )


# ── Accept/Reject order ──────────────────────────────────────────

@router.callback_query(
    RoleFilter("master"),
    F.data.startswith("master_accept:"),
)
async def accept_order(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    user_data: Master | None = None,
):
    """Master accepts an order."""
    order_uid = callback.data.split(":")[1]
    order_service = OrderService(session)

    try:
        order = await order_service.update_order_status(
            order_uid=order_uid,
            new_status=OrderStatus.ACCEPTED,
            changed_by_telegram_id=callback.from_user.id,
            changed_by_role="master",
        )
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    # Set master as busy
    master_repo = MasterRepo(session)
    await master_repo.set_status(callback.from_user.id, MasterStatus.BUSY)

    await callback.message.edit_text(
        f"✅ Buyurtma <code>{order_uid}</code> qabul qilindi!\n\n"
        f"Keyingi qadam: status yangilang 👇",
        parse_mode="HTML",
        reply_markup=master_status_update_keyboard(order_uid, "accepted"),
    )

    # Notify client
    if order:
        notification = NotificationService(bot, session)
        await notification.notify_client_status_update(order, "status_accepted")

    await callback.answer()


@router.callback_query(
    RoleFilter("master"),
    F.data.startswith("master_reject:"),
)
async def reject_order(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    user_data: Master | None = None,
):
    """Master rejects an order."""
    order_uid = callback.data.split(":")[1]
    order_service = OrderService(session)

    try:
        order = await order_service.update_order_status(
            order_uid=order_uid,
            new_status=OrderStatus.REJECTED,
            changed_by_telegram_id=callback.from_user.id,
            changed_by_role="master",
        )
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.message.edit_text(
        f"❌ Buyurtma <code>{order_uid}</code> rad etildi.",
        parse_mode="HTML",
    )

    # Notify dispatcher to reassign
    if order and user_data:
        notification = NotificationService(bot, session)
        await notification.notify_dispatcher_order_rejected(order, user_data)

    await callback.answer()


# ── Status updates (on_the_way → arrived → in_progress → done) ───

@router.callback_query(
    RoleFilter("master"),
    F.data.startswith("master_status:"),
)
async def update_order_status(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    state: FSMContext,
    user_data: Master | None = None,
):
    """Handle progressive status updates from master."""
    parts = callback.data.split(":")
    order_uid = parts[1]
    new_status_str = parts[2]

    status_map = {
        "on_the_way": OrderStatus.ON_THE_WAY,
        "arrived": OrderStatus.ARRIVED,
        "in_progress": OrderStatus.IN_PROGRESS,
        "awaiting_confirm": OrderStatus.AWAITING_CONFIRM,
    }
    new_status = status_map.get(new_status_str)
    if not new_status:
        await callback.answer("Xatolik", show_alert=True)
        return

    order_service = OrderService(session)

    # Special flow for "completed" — need amount + video
    if new_status == OrderStatus.AWAITING_CONFIRM:
        await state.update_data(completing_order_uid=order_uid)
        await state.set_state(MasterOrderStates.entering_amount)
        await callback.message.edit_text(
            t("master_enter_amount", "uz"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    try:
        order = await order_service.update_order_status(
            order_uid=order_uid,
            new_status=new_status,
            changed_by_telegram_id=callback.from_user.id,
            changed_by_role="master",
        )
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    status_labels = {
        "on_the_way": "🚗 Yo'lga chiqdingiz!",
        "arrived": "📍 Yetib keldingiz!",
        "in_progress": "🔧 Ish boshlandi!",
    }
    label = status_labels.get(new_status_str, "✅ Status yangilandi")

    await callback.message.edit_text(
        f"{label}\n\nBuyurtma: <code>{order_uid}</code>",
        parse_mode="HTML",
        reply_markup=master_status_update_keyboard(order_uid, new_status_str),
    )

    # Notify client
    if order:
        notification = NotificationService(bot, session)
        status_key = f"status_{new_status_str}"
        await notification.notify_client_status_update(order, status_key)

    await callback.answer()


# ── Enter payment amount ──────────────────────────────────────────

@router.message(MasterOrderStates.entering_amount, F.text)
async def process_payment_amount(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    """Handle payment amount entry."""
    try:
        # Clean input: remove spaces, commas
        clean = message.text.replace(" ", "").replace(",", "").replace(".", "")
        amount = float(clean)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(
            "⚠️ Iltimos, to'g'ri summa kiriting (faqat raqam).\n"
            "Masalan: 150000"
        )
        return

    await state.update_data(payment_amount=amount)

    await message.answer(
        t("master_video_prompt", "uz"),
        parse_mode="HTML",
    )
    await state.set_state(MasterOrderStates.recording_video)


@router.callback_query(
    RoleFilter("master"),
    F.data.startswith("master_amount:"),
)
async def request_amount_from_button(
    callback: CallbackQuery,
    state: FSMContext,
):
    """
    Legacy/compatibility handler:
    Some keyboards still emit master_amount:<order_uid>.
    """
    order_uid = callback.data.split(":")[1]
    await state.update_data(completing_order_uid=order_uid)
    await state.set_state(MasterOrderStates.entering_amount)
    await callback.message.edit_text(
        t("master_enter_amount", "uz"),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Master video confirmation ─────────────────────────────────────

@router.message(MasterOrderStates.recording_video, F.video_note)
async def process_master_video(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user_data: Master | None = None,
):
    """Handle master's completion video."""
    duration = int(getattr(message.video_note, "duration", 0) or 0)
    if duration > 15:
        await message.answer(
            "⚠️ Iltimos, yakunlash videosi 15 soniyadan oshmasin.\n"
            "Qisqa (0-15 soniya) dumaloq video yuboring.",
        )
        return

    data = await state.get_data()
    order_uid = data.get("completing_order_uid")
    amount = data.get("payment_amount", 0)

    if not order_uid:
        await state.clear()
        return

    video_file_id = message.video_note.file_id

    # Complete order
    order_service = OrderService(session)
    try:
        order = await order_service.complete_order(
            order_uid=order_uid,
            amount=amount,
            master_telegram_id=message.from_user.id,
            video_file_id=video_file_id,
        )
    except ValueError as e:
        await message.answer(f"⚠️ Xatolik: {e}")
        await state.clear()
        return

    # Set master back to online
    master_repo = MasterRepo(session)
    await master_repo.set_status(message.from_user.id, MasterStatus.ONLINE)

    await state.clear()

    await message.answer(
        f"✅ <b>Buyurtma yakunlandi!</b>\n\n"
        f"📋 ID: <code>{order_uid}</code>\n"
        f"💰 Summa: {amount:,.0f} so'm\n\n"
        f"Dispetcher tasdiqlanishini kutamiz...",
        parse_mode="HTML",
        reply_markup=master_main_menu(True),
    )

    # Post video to channel
    if order and user_data:
        notification = NotificationService(bot, session)
        await notification.send_master_video_to_channel(
            order, user_data, video_file_id, amount
        )
        # Notify dispatcher to confirm
        await notification.notify_dispatcher_awaiting_confirm(order, amount)


@router.message(MasterOrderStates.recording_video, ~F.video_note)
async def master_wrong_video_format(message: Message):
    """Handle non-video_note in video state."""
    await message.answer(
        "⚠️ Iltimos, <b>dumaloq video</b> (video xabar) yuboring!\n"
        "Telegram kamerasini oching va dumaloq videoni yozib yuboring.",
        parse_mode="HTML",
    )


# ── Call client ───────────────────────────────────────────────────

@router.callback_query(
    RoleFilter("master"),
    F.data.startswith("master_call:"),
)
async def master_call_client(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show client phone for master to call."""
    order_uid = callback.data.split(":")[1]
    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)

    if not order or not order.user:
        await callback.answer("Ma'lumot topilmadi", show_alert=True)
        return

    await callback.message.answer(
        f"📞 Mijoz telefoni: <code>{order.user.phone}</code>",
        parse_mode="HTML",
    )
    await callback.answer()
