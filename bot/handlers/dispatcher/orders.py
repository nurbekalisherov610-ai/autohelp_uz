"""
AutoHelp.uz - Dispatcher Handler
Handles order management, master assignment, and video confirmations.
"""
from html import escape

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.role_filter import RoleFilter
from bot.states.dispatcher_states import DispatcherOrderStates
from bot.keyboards.dispatcher_kb import (
    dispatcher_main_menu, dispatcher_order_actions,
    master_selection_keyboard, dispatcher_confirm_completion,
)
from locales.texts import t
from core.config import settings
from models.order import OrderStatus, PROBLEM_LABELS
from models.master_specialization import (
    MasterSpecializationType,
    normalize_specialization,
    problem_specialization_priority,
    specialization_short_text,
)
from models.staff import Staff
from services.order_service import OrderService
from services.notification_service import NotificationService
from repositories.order_repo import OrderRepo
from repositories.master_repo import MasterRepo
from repositories.stats_repo import StatsRepo

router = Router(name="dispatcher")


def _dispatcher_video_prompt_text(order_uid: str) -> str:
    return (
        f"{t('dispatcher_video_prompt', 'uz')}\n\n"
        f"Buyurtma: <code>{order_uid}</code>\n"
        "Agar bosqich yo'qolsa: <code>/video ORDER_UID</code>"
    )


async def _complete_dispatcher_video_step(
    *,
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    order_uid: str,
    video_file_id: str,
    video_kind: str = "video_note",
) -> None:
    """Finalize dispatcher video confirmation and downstream notifications."""
    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)
    if not order:
        await state.clear()
        await message.answer("❌ Buyurtma topilmadi. Qaytadan urinib ko'ring.")
        return
    if order.status != OrderStatus.ASSIGNED:
        await state.clear()
        await message.answer(
            f"⚠️ Buyurtma <code>{order_uid}</code> endi dispatcher videosini kutmayapti.",
            parse_mode="HTML",
        )
        return
    if order.dispatcher_video_file_id:
        await state.clear()
        await message.answer(
            f"ℹ️ Buyurtma <code>{order_uid}</code> uchun dispatcher videosi allaqachon yuborilgan.",
            parse_mode="HTML",
        )
        return

    await order_repo.set_dispatcher_video(order_uid, video_file_id)

    notification = NotificationService(bot, session)
    await notification.send_dispatcher_video_to_client(
        order=order,
        video_file_id=video_file_id,
        video_kind=video_kind,
    )

    master_notified = False
    if order.master and order.user:
        await notification.notify_master_new_assignment(order, order.master, order.user)
        await notification.notify_client_status_update(order, "status_assigned")
        master_notified = True

    await state.clear()
    await message.answer(
        f"✅ Video xabar yuborildi!\n"
        f"Mijoz buyurtma <code>{order_uid}</code> uchun tasdiqlash videosini oldi.\n"
        f"{'Usta ham xabardor qilindi.' if master_notified else 'Ustani xabardor qilib bo&#39;lmadi.'}",
        parse_mode="HTML",
    )


async def _render_master_picker(
    callback: CallbackQuery,
    state: FSMContext,
    order_uid: str,
    masters: list,
    master_repo: MasterRepo,
    preferred: list[MasterSpecializationType] | None = None,
    title: str | None = None,
):
    """Render assignment keyboard with specialization hints."""
    if not masters:
        await callback.message.edit_text(
            f"⚠️ Buyurtma <code>{order_uid}</code> uchun mos usta topilmadi.\n"
            f"Filtrni o'zgartiring yoki qayta urinib ko'ring.",
            parse_mode="HTML",
        )
        return

    spec_map = await master_repo.get_specializations_map([m.id for m in masters])
    await state.update_data(assigning_order_uid=order_uid, search_order_uid=order_uid)

    await callback.message.edit_text(
        title or f"👨‍🔧 Buyurtma <code>{order_uid}</code> uchun usta tanlang:",
        parse_mode="HTML",
        reply_markup=master_selection_keyboard(
            masters,
            order_uid,
            specialization_map=spec_map,
            preferred_specializations=preferred or [],
        ),
    )


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
    await callback.answer("📋 Yuklanmoqda...")

    order_repo = OrderRepo(session)
    orders = await order_repo.get_active_orders()

    if not orders:
        await callback.message.edit_text("✅ Hozircha faol buyurtmalar yo'q.")
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
        master_name = escape(order.master.full_name) if order.master else "—"
        client_name = escape(order.user.full_name) if order.user else "—"
        lines.append(
            f"{icon} <code>{order.order_uid}</code>\n"
            f"   👤 {client_name} • 👨‍🔧 {master_name}\n"
            f"   {problem} • {order.created_at.strftime('%H:%M')}\n"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
    )


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data == "disp:masters_status",
)
async def show_masters_status(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show status of all masters."""
    await callback.answer("👨‍🔧 Yuklanmoqda...")

    master_repo = MasterRepo(session)
    masters = await master_repo.get_all_active()
    spec_map = await master_repo.get_specializations_map([m.id for m in masters])

    if not masters:
        await callback.message.edit_text("Hech qanday usta topilmadi.")
        return

    status_icons = {"online": "🟢", "busy": "🟡", "offline": "🔴"}
    lines = ["👨‍🔧 <b>Ustalar holati:</b>\n"]
    for m in masters:
        icon = status_icons.get(m.status.value, "⚪")
        spec_tag = specialization_short_text(
            spec_map.get(m.id, [])
        )
        safe_name = escape(m.full_name or "—")
        lines.append(
            f"{icon} {safe_name} [{spec_tag}] • ⭐{m.rating:.1f} • "
            f"✅{m.completed_orders} buyurtma"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
    )


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data == "disp:today_stats",
)
async def show_today_stats(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show today's statistics for dispatcher."""
    await callback.answer("📊 Yuklanmoqda...")

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


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data == "disp:sla_alerts",
)
async def show_sla_alerts(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show current SLA breach counters and recent breached orders."""
    await callback.answer("⚠️ SLA holati yuklanmoqda...")

    order_repo = OrderRepo(session)
    assign_violations = await order_repo.get_sla_violations(
        status=OrderStatus.ASSIGNED,
        timeout_minutes=settings.sla_assign_timeout,
    )
    on_the_way_violations = await order_repo.get_sla_violations(
        status=OrderStatus.ON_THE_WAY,
        timeout_minutes=settings.sla_on_the_way_timeout,
    )
    confirm_violations = await order_repo.get_sla_violations(
        status=OrderStatus.AWAITING_CONFIRM,
        timeout_minutes=settings.sla_confirm_timeout,
    )

    total = (
        len(assign_violations)
        + len(on_the_way_violations)
        + len(confirm_violations)
    )

    lines = [
        "⚠️ <b>SLA ogohlantirishlar</b>\n",
        f"• ASSIGNED > {settings.sla_assign_timeout} daqiqa: <b>{len(assign_violations)}</b>",
        f"• ON_THE_WAY > {settings.sla_on_the_way_timeout} daqiqa: <b>{len(on_the_way_violations)}</b>",
        f"• AWAITING_CONFIRM > {settings.sla_confirm_timeout} daqiqa: <b>{len(confirm_violations)}</b>",
    ]

    if total:
        lines.append("\n<b>So'nggi muammoli buyurtmalar:</b>")
        merged = (
            [("ASSIGNED", o) for o in assign_violations[:3]]
            + [("ON_THE_WAY", o) for o in on_the_way_violations[:3]]
            + [("AWAITING_CONFIRM", o) for o in confirm_violations[:3]]
        )[:8]
        for label, order in merged:
            lines.append(f"• <code>{order.order_uid}</code> — {label}")
    else:
        lines.append("\n✅ Hozircha SLA buzilishlari yo'q.")

    await callback.message.edit_text("\n".join(lines), parse_mode="HTML")


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
    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)
    if not order:
        await callback.answer("Buyurtma topilmadi!", show_alert=True)
        return

    master_repo = MasterRepo(session)
    masters = await master_repo.get_available_masters_for_problem(order.problem_type)
    preferred = problem_specialization_priority(order.problem_type.value)

    await _render_master_picker(
        callback=callback,
        state=state,
        order_uid=order_uid,
        masters=masters,
        master_repo=master_repo,
        preferred=preferred,
        title=(
            f"👨‍🔧 Buyurtma <code>{order_uid}</code> uchun usta tanlang:\n"
            f"Filtr yoki qidiruvdan foydalaning."
        ),
    )
    await callback.answer()


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("dispatch_filter:"),
)
async def filter_masters_for_order(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
):
    """Quick-filter masters by specialization tag."""
    _, order_uid, spec_token = callback.data.split(":", 2)

    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)
    if not order:
        await callback.answer("Buyurtma topilmadi!", show_alert=True)
        return

    selected_spec = normalize_specialization(spec_token)
    if not selected_spec:
        await callback.answer("Filtr topilmadi", show_alert=True)
        return

    master_repo = MasterRepo(session)
    masters = await master_repo.get_available_masters_for_problem(order.problem_type)
    spec_map = await master_repo.get_specializations_map([m.id for m in masters])

    filtered = []
    for master in masters:
        specs = spec_map.get(master.id, [MasterSpecializationType.UNIVERSAL])
        if selected_spec == MasterSpecializationType.UNIVERSAL:
            if MasterSpecializationType.UNIVERSAL in specs:
                filtered.append(master)
        elif (
            selected_spec in specs
            or MasterSpecializationType.UNIVERSAL in specs
        ):
            filtered.append(master)

    preferred = (
        [MasterSpecializationType.UNIVERSAL]
        if selected_spec == MasterSpecializationType.UNIVERSAL
        else [selected_spec, MasterSpecializationType.UNIVERSAL]
    )

    await _render_master_picker(
        callback=callback,
        state=state,
        order_uid=order_uid,
        masters=filtered,
        master_repo=master_repo,
        preferred=preferred,
        title=(
            f"🧩 Filtr: <b>{selected_spec.value.upper()}</b>\n"
            f"Buyurtma <code>{order_uid}</code> uchun mos usta:"
        ),
    )
    await callback.answer()


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("dispatch_search_master:"),
)
async def start_master_search(
    callback: CallbackQuery,
    state: FSMContext,
):
    """Ask dispatcher to enter search text for master lookup."""
    order_uid = callback.data.split(":")[1]
    await state.update_data(search_order_uid=order_uid, assigning_order_uid=order_uid)
    await state.set_state(DispatcherOrderStates.searching_master)
    await callback.message.edit_text(
        f"🔎 Usta qidirish\n"
        f"Buyurtma: <code>{order_uid}</code>\n\n"
        f"Ism, telefon yoki Telegram ID yuboring.\n"
        f"Masalan: <code>Ali</code> yoki <code>99890</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(
    RoleFilter("dispatcher", "admin", "super_admin"),
    DispatcherOrderStates.searching_master,
    F.text,
)
async def process_master_search(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    """Filter master list by text query and render assignment keyboard."""
    data = await state.get_data()
    order_uid = data.get("search_order_uid")
    if not order_uid:
        await state.clear()
        await message.answer("Buyurtma aniqlanmadi. Qaytadan urinib ko'ring.")
        return

    query = (message.text or "").strip().lower()
    if not query:
        await message.answer("Qidiruv matnini yuboring.")
        return

    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)
    if not order:
        await state.clear()
        await message.answer("Buyurtma topilmadi.")
        return

    master_repo = MasterRepo(session)
    masters = await master_repo.get_available_masters_for_problem(order.problem_type)
    spec_map = await master_repo.get_specializations_map([m.id for m in masters])

    matched = []
    for master in masters:
        haystack = " ".join(
            [
                master.full_name or "",
                master.phone or "",
                str(master.telegram_id),
            ]
        ).lower()
        if query in haystack:
            matched.append(master)

    if not matched:
        await message.answer(
            "Hech narsa topilmadi. Boshqa so'z kiriting yoki 'Hammasi' tugmasini bosing."
        )
        return

    await state.clear()
    preferred = problem_specialization_priority(order.problem_type.value)
    await message.answer(
        f"🔎 Topildi: <b>{len(matched)}</b> ta usta\n"
        f"Buyurtma <code>{order_uid}</code> uchun tanlang:",
        parse_mode="HTML",
        reply_markup=master_selection_keyboard(
            matched,
            order_uid,
            specialization_map=spec_map,
            preferred_specializations=preferred,
        ),
    )


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

    try:
        await order_service.assign_master(
            order_uid=order_uid,
            master_id=master_id,
            dispatcher_id=user_data.id if user_data else None,
            dispatcher_telegram_id=callback.from_user.id,
        )
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    master = await master_repo.get_by_id(master_id)
    safe_master_name = escape(master.full_name or "—") if master else "—"
    await callback.message.edit_text(
        f"✅ Buyurtma <code>{order_uid}</code> ga usta tayinlandi: "
        f"<b>{safe_master_name}</b>",
        parse_mode="HTML",
    )

    # Ask dispatcher for video confirmation
    await callback.message.answer(
        _dispatcher_video_prompt_text(order_uid),
        parse_mode="HTML",
    )
    await state.update_data(
        video_order_uid=order_uid,
        assigned_master_id=master_id,
    )
    await state.set_state(DispatcherOrderStates.recording_video)

    await callback.message.answer(
        "Majburiy bosqich: video yuborilgandan keyingina usta xabardor qilinadi.",
    )

    # If assignment happened outside private chat, also prompt in private DM.
    chat = callback.message.chat if callback.message else None
    if chat and chat.id != callback.from_user.id:
        try:
            await bot.send_message(
                callback.from_user.id,
                _dispatcher_video_prompt_text(order_uid),
                parse_mode="HTML",
            )
        except Exception:
            pass

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
    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)
    if not order:
        await callback.answer("Buyurtma topilmadi!", show_alert=True)
        return

    master_repo = MasterRepo(session)
    best = await master_repo.get_best_available(order.problem_type)

    if not best:
        await callback.answer(
            "Hozirda bo'sh usta yo'q! Qo'lda tanlang.",
            show_alert=True,
        )
        return

    order_service = OrderService(session)
    try:
        await order_service.assign_master(
            order_uid=order_uid,
            master_id=best.id,
            dispatcher_id=user_data.id if user_data else None,
            dispatcher_telegram_id=callback.from_user.id,
        )
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    best_specs = await master_repo.get_specializations(best.id)

    await callback.message.edit_text(
        f"🤖 Tizim taklifi qabul qilindi!\n\n"
        f"✅ Buyurtma <code>{order_uid}</code>\n"
        f"👨‍🔧 Usta: <b>{escape(best.full_name or '—')}</b> "
        f"[{specialization_short_text(best_specs)}] ⭐{best.rating:.1f}",
        parse_mode="HTML",
    )

    # Ask for video
    await callback.message.answer(
        _dispatcher_video_prompt_text(order_uid),
        parse_mode="HTML",
    )
    await state.update_data(video_order_uid=order_uid, assigned_master_id=best.id)
    await state.set_state(DispatcherOrderStates.recording_video)

    await callback.message.answer(
        "Majburiy bosqich: video yuborilgandan keyingina usta xabardor qilinadi.",
    )

    # If assignment happened outside private chat, also prompt in private DM.
    chat = callback.message.chat if callback.message else None
    if chat and chat.id != callback.from_user.id:
        try:
            await bot.send_message(
                callback.from_user.id,
                _dispatcher_video_prompt_text(order_uid),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await callback.answer()


# ── Dispatcher video confirmation ─────────────────────────────────

@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("dispatch_video:"),
)
async def start_dispatcher_video_from_card(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    """Start/restore dispatcher video confirmation step from order action card."""
    order_uid = callback.data.split(":")[1]
    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)

    if not order:
        await callback.answer("Buyurtma topilmadi!", show_alert=True)
        return
    if order.status != OrderStatus.ASSIGNED:
        await callback.answer("Avval buyurtmaga usta tayinlang.", show_alert=True)
        return
    if order.dispatcher_video_file_id:
        await callback.answer("Bu buyurtma uchun video allaqachon yuborilgan.", show_alert=True)
        return

    await state.update_data(video_order_uid=order_uid, assigned_master_id=order.master_id)
    await state.set_state(DispatcherOrderStates.recording_video)

    await callback.message.answer(
        _dispatcher_video_prompt_text(order_uid),
        parse_mode="HTML",
    )

    chat = callback.message.chat if callback.message else None
    if chat and chat.id != callback.from_user.id:
        try:
            await bot.send_message(
                callback.from_user.id,
                _dispatcher_video_prompt_text(order_uid),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await callback.answer("Video xabarni yuboring.")

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
        await message.answer("⚠️ Avval buyurtmaga usta tayinlang. Keyin video yuboring.")
        return

    await _complete_dispatcher_video_step(
        message=message,
        state=state,
        session=session,
        bot=bot,
        order_uid=order_uid,
        video_file_id=message.video_note.file_id,
        video_kind="video_note",
    )


@router.message(
    DispatcherOrderStates.recording_video,
    F.video,
)
async def process_dispatcher_video_file(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    """Handle regular dispatcher video as fallback if video_note is unavailable."""
    data = await state.get_data()
    order_uid = data.get("video_order_uid")
    if not order_uid:
        await state.clear()
        await message.answer("⚠️ Avval buyurtmaga usta tayinlang. Keyin video yuboring.")
        return

    duration = int(getattr(message.video, "duration", 0) or 0)
    if duration > 30:
        await message.answer(
            "⚠️ Iltimos, tasdiqlash videosi 30 soniyadan oshmasin.",
        )
        return

    await _complete_dispatcher_video_step(
        message=message,
        state=state,
        session=session,
        bot=bot,
        order_uid=order_uid,
        video_file_id=message.video.file_id,
        video_kind="video",
    )


@router.message(
    DispatcherOrderStates.recording_video,
    ~(F.video_note | F.video),
)
async def wrong_video_format(message: Message):
    """Handle non-video messages during video recording state."""
    await message.answer(
        "⚠️ Iltimos, dumaloq video yoki oddiy video yuboring (30 soniyagacha).\n"
        "Kerak bo'lsa /video ORDER_UID buyrug'ini yuboring.",
        parse_mode="HTML",
    )


# ── Confirm completed order ───────────────────────────────────────

@router.message(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.text.startswith("/video"),
)
async def arm_dispatcher_video_mode(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    """
    Manually arm video confirmation mode.
    Usage:
    - /video            -> auto-pick if one pending
    - /video ORDER_UID  -> target a specific assigned order
    """
    parts = (message.text or "").strip().split(maxsplit=1)
    requested_uid = parts[1].strip() if len(parts) > 1 else None

    order_repo = OrderRepo(session)
    pending = await order_repo.get_pending_dispatcher_video_orders(
        dispatcher_telegram_id=message.from_user.id,
        limit=10,
    )
    if not pending:
        await message.answer(
            "ℹ️ Sizda dispatcher videosi kutilayotgan buyurtma topilmadi."
        )
        return

    target_order = None
    if requested_uid:
        requested_uid_norm = requested_uid.upper()
        for order in pending:
            if (order.order_uid or "").upper() == requested_uid_norm:
                target_order = order
                break
        if not target_order:
            await message.answer(
                f"⚠️ <code>{escape(requested_uid)}</code> topilmadi yoki video allaqachon yuborilgan.",
                parse_mode="HTML",
            )
            return
    elif len(pending) == 1:
        target_order = pending[0]
    else:
        lines = ["🎥 Bir nechta buyurtma video tasdiq kutmoqda:"]
        for order in pending[:5]:
            lines.append(f"• <code>{order.order_uid}</code>")
        lines.append("\nKeraklisini tanlash uchun yuboring:")
        lines.append("<code>/video ORDER_UID</code>")
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    await state.update_data(video_order_uid=target_order.order_uid)
    await state.set_state(DispatcherOrderStates.recording_video)
    await message.answer(
        _dispatcher_video_prompt_text(target_order.order_uid),
        parse_mode="HTML",
    )


@router.message(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.video_note,
)
async def process_dispatcher_video_without_state(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    """Fallback: accept dispatcher video even if FSM state context was lost."""
    if await state.get_state() == DispatcherOrderStates.recording_video.state:
        return

    order_repo = OrderRepo(session)
    pending = await order_repo.get_pending_dispatcher_video_orders(
        dispatcher_telegram_id=message.from_user.id,
        limit=2,
    )
    if not pending:
        return
    if len(pending) > 1:
        await message.answer(
            "🎥 Bir nechta buyurtma kutmoqda. Iltimos, avval <code>/video ORDER_UID</code> yuboring.",
            parse_mode="HTML",
        )
        return

    await _complete_dispatcher_video_step(
        message=message,
        state=state,
        session=session,
        bot=bot,
        order_uid=pending[0].order_uid,
        video_file_id=message.video_note.file_id,
        video_kind="video_note",
    )


@router.message(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.video,
)
async def process_dispatcher_video_file_without_state(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    """Fallback: accept regular dispatcher video when FSM state is lost."""
    if await state.get_state() == DispatcherOrderStates.recording_video.state:
        return

    duration = int(getattr(message.video, "duration", 0) or 0)
    if duration > 30:
        await message.answer("⚠️ Video 30 soniyadan oshmasin.")
        return

    order_repo = OrderRepo(session)
    pending = await order_repo.get_pending_dispatcher_video_orders(
        dispatcher_telegram_id=message.from_user.id,
        limit=2,
    )
    if not pending:
        return
    if len(pending) > 1:
        await message.answer(
            "🎥 Bir nechta buyurtma kutmoqda. Iltimos, avval <code>/video ORDER_UID</code> yuboring.",
            parse_mode="HTML",
        )
        return

    await _complete_dispatcher_video_step(
        message=message,
        state=state,
        session=session,
        bot=bot,
        order_uid=pending[0].order_uid,
        video_file_id=message.video.file_id,
        video_kind="video",
    )


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

    if order:
        from models.payment import Payment
        await session.execute(
            update(Payment)
            .where(Payment.order_id == order.id)
            .values(confirmed_by_dispatcher=True)
        )

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
    F.data.startswith("dispatch_edit_amount:"),
)
async def start_edit_amount(
    callback: CallbackQuery,
    state: FSMContext,
):
    """Start payment amount edit flow for an awaiting confirmation order."""
    order_uid = callback.data.split(":")[1]
    await state.update_data(edit_amount_order_uid=order_uid)
    await state.set_state(DispatcherOrderStates.editing_amount)

    await callback.message.edit_text(
        f"✏️ <b>{order_uid}</b> uchun yangi summani kiriting (so'm):\n\n"
        f"Masalan: <code>180000</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(
    DispatcherOrderStates.editing_amount,
    F.text,
)
async def process_edit_amount(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    """Apply edited amount to both order and payment records."""
    data = await state.get_data()
    order_uid = data.get("edit_amount_order_uid")
    if not order_uid:
        await state.clear()
        await message.answer("❌ Buyurtma topilmadi. Qaytadan urinib ko'ring.")
        return

    try:
        clean = message.text.replace(" ", "").replace(",", "").replace(".", "")
        amount = float(clean)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer(
            "⚠️ Iltimos, summani to'g'ri kiriting (faqat raqam).\n"
            "Masalan: 180000"
        )
        return

    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)
    if not order:
        await state.clear()
        await message.answer("❌ Buyurtma topilmadi.")
        return

    await order_repo.set_payment_amount(order_uid, amount)

    from models.payment import Payment
    await session.execute(
        update(Payment)
        .where(Payment.order_id == order.id)
        .values(amount=amount)
    )

    await state.clear()
    await message.answer(
        f"✅ Buyurtma <code>{order_uid}</code> summasi yangilandi: "
        f"<b>{amount:,.0f} so'm</b>",
        parse_mode="HTML",
    )


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

    safe_phone = escape(order.user.phone or "—")
    await callback.message.answer(
        f"📞 Mijoz telefoni: <code>{safe_phone}</code>",
        parse_mode="HTML",
    )
    await callback.answer()
