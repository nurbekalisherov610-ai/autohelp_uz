"""
AutoHelp.uz - Dispatcher Handler
Handles order management, master assignment, and video confirmations.
"""
from html import escape

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from loguru import logger
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.role_filter import RoleFilter
from bot.states.dispatcher_states import DispatcherOrderStates
from bot.keyboards.dispatcher_kb import (
    dispatcher_main_menu, dispatcher_order_actions,
    master_selection_keyboard, dispatcher_confirm_completion,
    dispatcher_order_navigation, dispatcher_video_prompt_keyboard,
    dispatcher_active_orders_keyboard,
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
ACTIVE_ORDERS_PAGE_SIZE = 8


def _dispatcher_menu_text() -> str:
    return "📋 <b>Dispetcher paneli</b>\n\nAmalni tanlang:"


def _order_card_text(order) -> str:
    problem = PROBLEM_LABELS[order.problem_type]["uz"]
    client_name = escape(order.user.full_name) if order.user and order.user.full_name else "—"
    client_phone = escape(order.user.phone) if order.user and order.user.phone else "—"
    master_name = escape(order.master.full_name) if order.master and order.master.full_name else "—"
    description = escape(order.description) if order.description else "—"

    return (
        f"📋 <b>Buyurtma kartasi</b>\n\n"
        f"ID: <code>{order.order_uid}</code>\n"
        f"Status: <b>{escape(order.status.value)}</b>\n"
        f"Mijoz: {client_name}\n"
        f"Telefon: <code>{client_phone}</code>\n"
        f"Muammo: {problem}\n"
        f"Izoh: {description}\n"
        f"Usta: {master_name}"
    )


def _order_actions_for_status(order) -> object:
    if order.status == OrderStatus.AWAITING_CONFIRM:
        return dispatcher_confirm_completion(order.order_uid)
    if order.status in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
        return dispatcher_main_menu()
    return dispatcher_order_actions(order.order_uid)


async def _safe_edit_text(
    callback: CallbackQuery,
    text: str,
    *,
    parse_mode: str | None = "HTML",
    reply_markup=None,
    disable_web_page_preview: bool = True,
) -> None:
    """
    Safely edit callback message.
    If edit fails (stale/modified/deleted), send a new message instead of dead-ending UI.
    """
    if not callback.message:
        return

    try:
        await callback.message.edit_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        return
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            try:
                await callback.message.edit_reply_markup(reply_markup=reply_markup)
                return
            except Exception:
                pass
    except Exception:
        pass

    # Fallback to a fresh message so dispatcher never loses controls.
    await callback.message.answer(
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


def _dispatcher_video_prompt_text(order_uid: str) -> str:
    return (
        f"{t('dispatcher_video_prompt', 'uz')}\n\n"
        f"Buyurtma: <code>{order_uid}</code>\n"
        "Agar bosqich yo'qolsa: <code>/video ORDER_UID</code>"
    )


async def _run_post_assignment_flow(
    *,
    session: AsyncSession,
    bot: Bot,
    order_uid: str,
) -> bool:
    """
    After master assignment:
    1) notify assigned master
    2) notify client that master is assigned
    """
    order = await OrderRepo(session).get_by_uid(order_uid)
    if not order or not order.user or not order.master:
        logger.warning(
            f"Post-assignment flow skipped due to missing data for order {order_uid}."
        )
        return False

    notification = NotificationService(bot, session)
    await notification.notify_master_new_assignment(order, order.master, order.user)
    await notification.notify_client_status_update(order, "status_assigned")
    return True


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
        await message.answer(
            "❌ Buyurtma topilmadi. Qaytadan urinib ko'ring.",
            reply_markup=dispatcher_main_menu(),
        )
        return
    if order.status != OrderStatus.ASSIGNED:
        await state.clear()
        await message.answer(
            f"⚠️ Buyurtma <code>{order_uid}</code> endi dispatcher videosini kutmayapti.",
            parse_mode="HTML",
            reply_markup=dispatcher_order_navigation(order_uid),
        )
        return
    if order.dispatcher_video_file_id:
        await state.clear()
        await message.answer(
            f"ℹ️ Buyurtma <code>{order_uid}</code> uchun dispatcher videosi allaqachon yuborilgan.",
            parse_mode="HTML",
            reply_markup=dispatcher_order_navigation(order_uid),
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
        reply_markup=dispatcher_order_actions(order_uid),
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
        await _safe_edit_text(
            callback,
            f"⚠️ Buyurtma <code>{order_uid}</code> uchun usta topilmadi.\n"
            f"Iltimos, ustalarni tekshirib qayta urinib ko'ring.",
            parse_mode="HTML",
            reply_markup=dispatcher_order_navigation(order_uid),
        )
        return

    spec_map = await master_repo.get_specializations_map([m.id for m in masters])
    await state.update_data(assigning_order_uid=order_uid, search_order_uid=order_uid)

    await _safe_edit_text(
        callback,
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
        _dispatcher_menu_text(),
        parse_mode="HTML",
        reply_markup=dispatcher_main_menu(),
    )


@router.message(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.text == "/media_id",
)
async def get_media_id(message: Message):
    """
    Utility: reply with Telegram file_id for a replied video/video_note.
    Usage: reply to media with /media_id
    """
    target = message.reply_to_message
    if not target:
        await message.answer(
            "ℹ️ Avval video xabarga reply qiling, keyin <code>/media_id</code> yuboring.",
            parse_mode="HTML",
        )
        return

    media_kind = None
    media_id = None
    if target.video_note:
        media_kind = "video_note"
        media_id = target.video_note.file_id
    elif target.video:
        media_kind = "video"
        media_id = target.video.file_id

    if not media_id:
        await message.answer(
            "⚠️ Faqat video xabar (video_note) yoki oddiy video uchun file_id olish mumkin."
        )
        return

    await message.answer(
        "✅ Media topildi:\n"
        f"Tur: <code>{media_kind}</code>\n"
        f"ID: <code>{escape(media_id)}</code>",
        parse_mode="HTML",
    )


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data == "disp:menu",
)
async def dispatcher_menu_callback(callback: CallbackQuery):
    """Always-returnable dispatcher dashboard entry point."""
    await _safe_edit_text(
        callback,
        _dispatcher_menu_text(),
        parse_mode="HTML",
        reply_markup=dispatcher_main_menu(),
    )
    await callback.answer()


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("dispatch_view:"),
)
async def dispatcher_view_order_card(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Re-open a single order card with proper action buttons."""
    order_uid = callback.data.split(":", 1)[1]
    order_repo = OrderRepo(session)
    order = await order_repo.get_by_uid(order_uid)
    if not order:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        await _safe_edit_text(
            callback,
            _dispatcher_menu_text(),
            parse_mode="HTML",
            reply_markup=dispatcher_main_menu(),
        )
        return

    await _safe_edit_text(
        callback,
        _order_card_text(order),
        parse_mode="HTML",
        reply_markup=_order_actions_for_status(order),
    )
    await callback.answer()


@router.callback_query(
    RoleFilter("dispatcher", "admin", "super_admin"),
    F.data.startswith("disp:active_orders"),
)
async def show_active_orders(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show active orders with direct card-open actions and paging."""
    await callback.answer("Yuklanmoqda...")

    page = 0
    parts = (callback.data or "").split(":")
    if len(parts) >= 3:
        try:
            page = max(0, int(parts[2]))
        except ValueError:
            page = 0

    order_repo = OrderRepo(session)
    orders = await order_repo.get_active_orders()

    if not orders:
        await _safe_edit_text(
            callback,
            "Hozircha faol buyurtmalar yo'q.",
            reply_markup=dispatcher_main_menu(),
        )
        return

    total = len(orders)
    start = page * ACTIVE_ORDERS_PAGE_SIZE
    if start >= total and total > 0:
        page = 0
        start = 0
    end = start + ACTIVE_ORDERS_PAGE_SIZE
    page_orders = orders[start:end]

    lines = [
        "<b>Faol buyurtmalar:</b>",
        f"Jami: <b>{total}</b> ta",
        f"Sahifa: <b>{page + 1}</b>/{max(1, (total + ACTIVE_ORDERS_PAGE_SIZE - 1) // ACTIVE_ORDERS_PAGE_SIZE)}",
        "",
    ]

    for idx, order in enumerate(page_orders, start=start + 1):
        status_icons = {
            "new": "NEW",
            "assigned": "ASSIGNED",
            "accepted": "ACCEPTED",
            "on_the_way": "ON_THE_WAY",
            "arrived": "ARRIVED",
            "in_progress": "IN_PROGRESS",
            "awaiting_confirm": "AWAITING_CONFIRM",
        }
        icon = status_icons.get(order.status.value, order.status.value)
        problem = PROBLEM_LABELS[order.problem_type]["uz"]
        master_name = escape(order.master.full_name) if order.master else "-"
        client_name = escape(order.user.full_name) if order.user else "-"
        lines.append(
            f"{idx}. <code>{order.order_uid}</code> [{icon}]\n"
            f"   Mijoz: {client_name} | Usta: {master_name}\n"
            f"   {problem} | {order.created_at.strftime('%H:%M')}\n"
        )

    lines.append("Boshqarish uchun pastdagi tugmalardan buyurtmani tanlang.")

    await _safe_edit_text(
        callback,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=dispatcher_active_orders_keyboard(
            [o.order_uid for o in page_orders],
            page=page,
            has_prev=page > 0,
            has_next=end < total,
        ),
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
        await _safe_edit_text(
            callback,
            "Hech qanday usta topilmadi.",
            reply_markup=dispatcher_main_menu(),
        )
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

    await _safe_edit_text(
        callback,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=dispatcher_main_menu(),
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

    await _safe_edit_text(
        callback,
        text,
        parse_mode="HTML",
        reply_markup=dispatcher_main_menu(),
    )


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

    await _safe_edit_text(
        callback,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=dispatcher_main_menu(),
    )


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
        await _safe_edit_text(
            callback,
            _dispatcher_menu_text(),
            parse_mode="HTML",
            reply_markup=dispatcher_main_menu(),
        )
        return

    master_repo = MasterRepo(session)
    masters = await master_repo.get_assignable_masters_for_problem(
        order.problem_type,
        allow_offline_fallback=True,
    )
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
            f"Ismdan tanlang va bir marta bosing."
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
        await _safe_edit_text(
            callback,
            _dispatcher_menu_text(),
            parse_mode="HTML",
            reply_markup=dispatcher_main_menu(),
        )
        return

    selected_spec = normalize_specialization(spec_token)
    if not selected_spec:
        await callback.answer("Filtr topilmadi", show_alert=True)
        return

    master_repo = MasterRepo(session)
    masters = await master_repo.get_assignable_masters_for_problem(
        order.problem_type,
        allow_offline_fallback=True,
    )
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
    await _safe_edit_text(
        callback,
        f"🔎 Usta qidirish\n"
        f"Buyurtma: <code>{order_uid}</code>\n\n"
        f"Ism yoki telefon bo'yicha qidiring.\n"
        f"Masalan: <code>Ali</code> yoki <code>99890</code>",
        parse_mode="HTML",
        reply_markup=dispatcher_order_navigation(order_uid),
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
    masters = await master_repo.get_assignable_masters_for_problem(
        order.problem_type,
        allow_offline_fallback=True,
    )
    spec_map = await master_repo.get_specializations_map([m.id for m in masters])

    matched = []
    for master in masters:
        haystack = " ".join(
            [
                master.full_name or "",
                master.phone or "",
            ]
        ).lower()
        if query in haystack:
            matched.append(master)

    if not matched:
        await message.answer(
            "Hech narsa topilmadi. Boshqa so'z kiriting yoki 'Hammasi' tugmasini bosing.",
            reply_markup=dispatcher_order_navigation(order_uid),
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
        latest_order = await OrderRepo(session).get_by_uid(order_uid)
        if latest_order:
            await _safe_edit_text(
                callback,
                _order_card_text(latest_order),
                parse_mode="HTML",
                reply_markup=_order_actions_for_status(latest_order),
            )
        else:
            await _safe_edit_text(
                callback,
                _dispatcher_menu_text(),
                parse_mode="HTML",
                reply_markup=dispatcher_main_menu(),
            )
        return

    master = await master_repo.get_by_id(master_id)
    safe_master_name = escape(master.full_name or "—") if master else "—"
    await _safe_edit_text(
        callback,
        f"✅ Buyurtma <code>{order_uid}</code> ga usta tayinlandi: "
        f"<b>{safe_master_name}</b>",
        parse_mode="HTML",
        reply_markup=dispatcher_order_actions(order_uid),
    )

    await _run_post_assignment_flow(
        session=session,
        bot=bot,
        order_uid=order_uid,
    )
    await state.clear()
    await callback.message.answer("Usta va mijoz xabardor qilindi.")

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
        await _safe_edit_text(
            callback,
            _dispatcher_menu_text(),
            parse_mode="HTML",
            reply_markup=dispatcher_main_menu(),
        )
        return

    master_repo = MasterRepo(session)
    best = await master_repo.get_best_available(order.problem_type)

    if not best:
        await callback.answer(
            "Hozirda bo'sh usta yo'q! Qo'lda tanlang.",
            show_alert=True,
        )
        await _safe_edit_text(
            callback,
            _order_card_text(order),
            parse_mode="HTML",
            reply_markup=_order_actions_for_status(order),
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
        latest_order = await order_repo.get_by_uid(order_uid)
        if latest_order:
            await _safe_edit_text(
                callback,
                _order_card_text(latest_order),
                parse_mode="HTML",
                reply_markup=_order_actions_for_status(latest_order),
            )
        else:
            await _safe_edit_text(
                callback,
                _dispatcher_menu_text(),
                parse_mode="HTML",
                reply_markup=dispatcher_main_menu(),
            )
        return

    best_specs = await master_repo.get_specializations(best.id)

    await _safe_edit_text(
        callback,
        f"🤖 Tizim taklifi qabul qilindi!\n\n"
        f"✅ Buyurtma <code>{order_uid}</code>\n"
        f"👨‍🔧 Usta: <b>{escape(best.full_name or '—')}</b> "
        f"[{specialization_short_text(best_specs)}] ⭐{best.rating:.1f}",
        parse_mode="HTML",
        reply_markup=dispatcher_order_actions(order_uid),
    )

    await _run_post_assignment_flow(
        session=session,
        bot=bot,
        order_uid=order_uid,
    )
    await state.clear()
    await callback.message.answer("Usta va mijoz xabardor qilindi.")

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
    """Manual dispatcher video mode is deprecated (auto confirmation is enabled)."""
    await state.clear()
    await callback.answer(
        "ℹ️ Endi tasdiqlash videosi avtomatik yuboriladi.",
        show_alert=True,
    )

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
    """Legacy handler: manual video mode is disabled."""
    await state.clear()
    await message.answer(
        "ℹ️ Qo'lda video yuborish rejimi o'chirildi.\n"
        "Buyurtma tasdiq videosi avtomatik yuboriladi.",
        reply_markup=dispatcher_main_menu(),
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
    """Legacy handler: manual video mode is disabled."""
    await state.clear()
    await message.answer(
        "ℹ️ Qo'lda video yuborish rejimi o'chirildi.\n"
        "Buyurtma tasdiq videosi avtomatik yuboriladi.",
        reply_markup=dispatcher_main_menu(),
    )


@router.message(
    DispatcherOrderStates.recording_video,
    ~(F.video_note | F.video),
)
async def wrong_video_format(message: Message, state: FSMContext):
    """Legacy handler: manual video mode is disabled."""
    await state.clear()
    await message.answer(
        "ℹ️ Qo'lda video yuborish rejimi o'chirildi.\n"
        "Buyurtma tasdiq videosi avtomatik yuboriladi.",
        reply_markup=dispatcher_main_menu(),
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
    """Manual video mode disabled: confirmations are automatic now."""
    await state.clear()
    await message.answer(
        "ℹ️ Endi dispatcher tasdiqlash videosi avtomatik yuboriladi.\n"
        "Qo'lda video yuborish rejimi o'chirildi.",
        reply_markup=dispatcher_main_menu(),
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
    """Fallback disabled: manual dispatcher video flow is no longer used."""
    return


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
    """Fallback disabled: manual dispatcher video flow is no longer used."""
    return


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

    await _safe_edit_text(
        callback,
        f"✅ Buyurtma <code>{order_uid}</code> tasdiqlandi va tugallandi!",
        parse_mode="HTML",
        reply_markup=dispatcher_main_menu(),
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

    await _safe_edit_text(
        callback,
        f"✏️ <b>{order_uid}</b> uchun yangi summani kiriting (so'm):\n\n"
        f"Masalan: <code>180000</code>",
        parse_mode="HTML",
        reply_markup=dispatcher_order_navigation(order_uid),
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
        reply_markup=dispatcher_order_navigation(order_uid),
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

    await _safe_edit_text(
        callback,
        f"❌ Buyurtma <code>{order_uid}</code> bekor qilindi.",
        parse_mode="HTML",
        reply_markup=dispatcher_main_menu(),
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
