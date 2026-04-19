"""
AutoHelp.uz - Dispatcher Handler
Handles order management, master assignment, and video confirmations.
"""
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.role_filter import RoleFilter
from bot.states.dispatcher_states import DispatcherOrderStates
from bot.keyboards.dispatcher_kb import (
    dispatcher_main_menu, dispatcher_order_actions,
    master_selection_keyboard, dispatcher_confirm_completion,
)
from locales.texts import t
from models.order import OrderStatus, PROBLEM_LABELS
from models.staff import Staff
from services.order_service import OrderService
from services.notification_service import NotificationService
from repositories.order_repo import OrderRepo
from repositories.master_repo import MasterRepo
from repositories.stats_repo import StatsRepo

router = Router(name="dispatcher")


# ── Dispatcher /start and main menu ──────────────────────────────

@router.message(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.text == "/start",
)
async def dispatcher_start(message: Message):
    """Dispatcher main menu."""
    await message.answer(
        "📋 <b>Dispetcher paneli</b>\n\nAmalni tanlang:",
        parse_mode="HTML",
        reply_markup=dispatcher_main_menu(),
    )


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data == "disp:active_orders",
)
async def show_active_orders(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show all active orders."""
    order_repo = OrderRepo(session)
    orders = await order_repo.get_active_orders()

    if not orders:
        await callback.message.edit_text("✅ Hozircha faol buyurtmalar yo'q.")
        await callback.answer()
        return

    lines = ["📋 <b>Faol buyurtmalar:</b>\n"]
    for order in orders[:20]:
        status_icons = {
            "new": "🆕", "assigned": "👨‍🔧", "accepted": "✅",
            "on_the_way": "🚗", "arrived": "📍", "in_progress": "🔧",
            "awaiting_confirm": "⏳",
        }
        icon = status_icons.get(order.status.value, "❓")
        problem = PROBLEM_LABELS[order.problem_type]["uz"]
        master_name = order.master.full_name if order.master else "—"
        client_name = order.user.full_name if order.user else "—"
        lines.append(
            f"{icon} <code>{order.order_uid}</code>\n"
            f"   👤 {client_name} • 👨‍🔧 {master_name}\n"
            f"   {problem} • {order.created_at.strftime('%H:%M')}\n"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data == "disp:masters_status",
)
async def show_masters_status(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show status of all masters."""
    master_repo = MasterRepo(session)
    masters = await master_repo.get_all_active()

    if not masters:
        await callback.message.edit_text("Hech qanday usta topilmadi.")
        await callback.answer()
        return

    status_icons = {"online": "🟢", "busy": "🟡", "offline": "🔴"}
    lines = ["👨‍🔧 <b>Ustalar holati:</b>\n"]
    for m in masters:
        icon = status_icons.get(m.status.value, "⚪")
        lines.append(
            f"{icon} {m.full_name} • ⭐{m.rating:.1f} • "
            f"✅{m.completed_orders} buyurtma"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data == "disp:today_stats",
)
async def show_today_stats(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show today's statistics for dispatcher."""
    stats_repo = StatsRepo(session)
    stats = await stats_repo.get_dashboard_stats()

    text = (
        f"📊 <b>Bugungi statistika</b>\n\n"
        f"📋 Buyurtmalar: {stats['today_orders']}\n"
        f"✅ Tugallangan: {stats['today_completed']}\n"
        f"💰 Summa: {stats['today_sum']:,.0f} so'm\n"
        f"👨‍🔧 Online ustalar: {stats['online_masters']}\n"
        f"🔄 Faol buyurtmalar: {stats['active_orders']}\n"
    )

    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


# ── Assign master to order ────────────────────────────────────────

@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("dispatch_assign:"),
)
async def start_assign_master(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
):
    """Show available masters for assignment."""
    order_uid = callback.data.split(":")[1]
    master_repo = MasterRepo(session)
    masters = await master_repo.get_all_active()

    if not masters:
        await callback.answer("Hech qanday usta topilmadi!", show_alert=True)
        return

    await state.update_data(assigning_order_uid=order_uid)

    await callback.message.edit_text(
        f"👨‍🔧 Buyurtma <code>{order_uid}</code> uchun usta tanlang:",
        parse_mode="HTML",
        reply_markup=master_selection_keyboard(masters, order_uid),
    )
    await callback.answer()


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("assign:"),
)
async def assign_master_to_order(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    state: FSMContext,
    user_data: Staff | None = None,
):
    """Assign a specific master to an order."""
    parts = callback.data.split(":")
    order_uid = parts[1]
    master_id = int(parts[2])

    order_service = OrderService(session)
    master_repo = MasterRepo(session)
    order_repo = OrderRepo(session)

    try:
        order = await order_service.assign_master(
            order_uid=order_uid,
            master_id=master_id,
            dispatcher_id=user_data.id if user_data else None,
            dispatcher_telegram_id=callback.from_user.id,
        )
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    master = await master_repo.get_by_id(master_id)
    await callback.message.edit_text(
        f"✅ Buyurtma <code>{order_uid}</code> ga usta tayinlandi: "
        f"<b>{master.full_name}</b>",
        parse_mode="HTML",
    )

    # Ask dispatcher for video confirmation
    await callback.message.answer(
        t("dispatcher_video_prompt", "uz"),
        parse_mode="HTML",
    )
    await state.update_data(
        video_order_uid=order_uid,
        assigned_master_id=master_id,
    )
    await state.set_state(DispatcherOrderStates.recording_video)

    # Notify the master
    order = await order_repo.get_by_uid(order_uid)
    if order and master:
        notification = NotificationService(bot, session)
        await notification.notify_master_new_assignment(order, master, order.user)
        await notification.notify_client_status_update(order, "status_assigned")

    await callback.answer()


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("assign_auto:"),
)
async def auto_assign_master(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    state: FSMContext,
    user_data: Staff | None = None,
):
    """Auto-assign the best available master."""
    order_uid = callback.data.split(":")[1]
    master_repo = MasterRepo(session)
    best = await master_repo.get_best_available()

    if not best:
        await callback.answer(
            "Hozirda bo'sh usta yo'q! Qo'lda tanlang.",
            show_alert=True,
        )
        return

    order_service = OrderService(session)
    try:
        order = await order_service.assign_master(
            order_uid=order_uid,
            master_id=best.id,
            dispatcher_id=user_data.id if user_data else None,
            dispatcher_telegram_id=callback.from_user.id,
        )
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.message.edit_text(
        f"🤖 Tizim taklifi qabul qilindi!\n\n"
        f"✅ Buyurtma <code>{order_uid}</code>\n"
        f"👨‍🔧 Usta: <b>{best.full_name}</b> ⭐{best.rating:.1f}",
        parse_mode="HTML",
    )

    # Ask for video
    await callback.message.answer(
        t("dispatcher_video_prompt", "uz"),
        parse_mode="HTML",
    )
    await state.update_data(video_order_uid=order_uid, assigned_master_id=best.id)
    await state.set_state(DispatcherOrderStates.recording_video)

    # Notify
    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)
    if order:
        notification = NotificationService(bot, session)
        await notification.notify_master_new_assignment(order, best, order.user)
        await notification.notify_client_status_update(order, "status_assigned")

    await callback.answer()


# ── Dispatcher video confirmation ─────────────────────────────────

@router.message(
    DispatcherOrderStates.recording_video,
    F.video_note,
)
async def process_dispatcher_video(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    """Handle dispatcher's circle video confirmation."""
    data = await state.get_data()
    order_uid = data.get("video_order_uid")

    if not order_uid:
        await state.clear()
        return

    # Save video file_id
    video_file_id = message.video_note.file_id
    order_repo = OrderRepo(session)
    await order_repo.set_dispatcher_video(order_uid, video_file_id)

    # Forward to client
    order = await order_repo.get_by_uid(order_uid)
    if order:
        notification = NotificationService(bot, session)
        await notification.send_dispatcher_video_to_client(order, video_file_id)

    await state.clear()
    await message.answer(
        f"✅ Video xabar yuborildi!\n"
        f"Mijoz buyurtma <code>{order_uid}</code> uchun "
        f"tasdiqlash videosini oldi.",
        parse_mode="HTML",
    )


@router.message(
    DispatcherOrderStates.recording_video,
    ~F.video_note,
)
async def wrong_video_format(message: Message):
    """Handle non-video_note messages during video recording state."""
    await message.answer(
        "⚠️ Iltimos, <b>dumaloq video</b> (video xabar) yuboring!\n"
        "Telegram kamerasini oching va dumaloq videoni yozib yuboring.",
        parse_mode="HTML",
    )


# ── Confirm completed order ───────────────────────────────────────

@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("dispatch_confirm:"),
)
async def confirm_order_completion(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    """Confirm an order as completed."""
    order_uid = callback.data.split(":")[1]
    order_service = OrderService(session)

    try:
        order = await order_service.update_order_status(
            order_uid=order_uid,
            new_status=OrderStatus.COMPLETED,
            changed_by_telegram_id=callback.from_user.id,
            changed_by_role="dispatcher",
        )
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.message.edit_text(
        f"✅ Buyurtma <code>{order_uid}</code> tasdiqlandi va tugallandi!",
        parse_mode="HTML",
    )

    # Notify client with rating prompt
    if order and order.user:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        notification = NotificationService(bot, session)
        amount = order.payment_amount or 0
        await notification.notify_client_status_update(
            order, "status_completed", amount=f"{amount:,.0f}"
        )
        # Send rating keyboard
        rate_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⭐ Baholash",
                callback_data=f"rate_order:{order_uid}",
            )]
        ])
        await bot.send_message(
            chat_id=order.user.telegram_id,
            text="⭐ Xizmatni baholang:",
            reply_markup=rate_kb,
        )

    await callback.answer()


# ── Cancel order as dispatcher ────────────────────────────────────

@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("dispatch_cancel:"),
)
async def dispatcher_cancel_order(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    """Cancel an order as dispatcher."""
    order_uid = callback.data.split(":")[1]
    order_service = OrderService(session)

    try:
        order = await order_service.cancel_order(
            order_uid=order_uid,
            cancelled_by_telegram_id=callback.from_user.id,
            cancelled_by_role="dispatcher",
        )
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.message.edit_text(
        f"❌ Buyurtma <code>{order_uid}</code> bekor qilindi.",
        parse_mode="HTML",
    )

    # Notify client
    if order and order.user:
        notification = NotificationService(bot, session)
        await notification.notify_client_status_update(
            order, "order_cancelled_by_client"
        )

    await callback.answer()


# ── View on map ───────────────────────────────────────────────────

@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("dispatch_map:"),
)
async def show_order_on_map(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Send order location to dispatcher."""
    order_uid = callback.data.split(":")[1]
    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)

    if not order:
        await callback.answer("Buyurtma topilmadi", show_alert=True)
        return

    await callback.message.answer_location(
        latitude=order.latitude,
        longitude=order.longitude,
    )
    await callback.answer()


# ── Call client ───────────────────────────────────────────────────

@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("dispatch_call:"),
)
async def call_client(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show client's phone number for calling."""
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
