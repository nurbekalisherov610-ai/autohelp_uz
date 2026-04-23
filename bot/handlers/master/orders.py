"""
AutoHelp.uz - Master Handler
Handles master availability, order acceptance, status updates,
payment entry, and video confirmation.
"""
from html import escape

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.role_filter import RoleFilter
from bot.states.master_states import MasterOrderStates
from bot.keyboards.master_kb import (
    master_main_menu, master_order_response,
    master_status_update_keyboard, master_back_keyboard,
)
from locales.texts import t
from models.master import Master, MasterStatus
from models.order import OrderStatus, PROBLEM_LABELS
from services.order_service import OrderService
from services.notification_service import NotificationService
from repositories.order_repo import OrderRepo
from repositories.master_repo import MasterRepo
from repositories.stats_repo import StatsRepo

router = Router(name="master")


def _master_keyboard_status_key(status: OrderStatus | None) -> str | None:
    """Map persisted order status to the keyboard flow key."""
    mapping = {
        OrderStatus.ACCEPTED: "accepted",
        OrderStatus.ON_THE_WAY: "on_the_way",
        OrderStatus.ARRIVED: "arrived",
        OrderStatus.IN_PROGRESS: "in_progress",
    }
    return mapping.get(status)


async def _safe_master_edit_text(
    callback: CallbackQuery,
    text: str,
    *,
    parse_mode: str | None = "HTML",
    reply_markup=None,
    disable_web_page_preview: bool = True,
) -> None:
    """
    Safely edit callback message.
    If edit fails (stale/modified/deleted), send a fresh message so flow never dead-ends.
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

    await callback.message.answer(
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


async def _get_order_for_master(
    *,
    session: AsyncSession,
    order_uid: str,
    master_telegram_id: int,
):
    """Load order and ensure it belongs to the current master."""
    order = await OrderRepo(session).get_by_uid(order_uid)
    if not order:
        return None, "Buyurtma topilmadi."
    if not order.master or order.master.telegram_id != master_telegram_id:
        return None, "Bu buyurtma sizga biriktirilmagan."
    return order, None


async def _complete_master_order_with_video(
    *,
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user_data: Master | None,
    video_file_id: str,
    video_kind: str,
) -> None:
    """Finalize master completion flow with provided video file."""
    data = await state.get_data()
    order_uid = data.get("completing_order_uid")
    amount = data.get("payment_amount", 0)

    if not order_uid:
        await state.clear()
        return

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

    if order and user_data:
        notification = NotificationService(bot, session)
        await notification.send_master_video_to_channel(
            order,
            user_data,
            video_file_id,
            amount,
            video_kind=video_kind,
        )
        await notification.notify_dispatcher_awaiting_confirm(order, amount)


# ── Master dashboard helper ───────────────────────────────────────

def _dashboard_text(user_data: Master | None) -> str:
    is_online = user_data.status == MasterStatus.ONLINE if user_data else False
    status_icon = "🟢" if is_online else "🔴"
    status_text = "Online (Buyurtmaga tayyor)" if is_online else "Offline (Dam olishda)"
    name = escape(user_data.full_name) if user_data else "Usta"
    rating = f"{user_data.rating:.1f}" if user_data else "5.0"
    completed = user_data.completed_orders if user_data else 0
    return (
        f"Assalomu alaykum, <b>{name}</b>! 👋\n\n"
        f"👨‍🔧 <b>Shaxsiy Kabinet</b>\n"
        f"📊 Reytingingiz: ⭐ {rating}\n"
        f"✅ Bajarilgan ishlar: {completed} ta\n"
        f"📡 Holat: {status_icon} <b>{status_text}</b>\n\n"
        f"<i>Quyidagi tugmalardan birini bosing:</i>"
    )


def _order_card(order) -> str:
    problem_label = PROBLEM_LABELS.get(order.problem_type, {}).get("uz", "—")
    client_name = escape(order.user.full_name) if order.user and order.user.full_name else "—"
    client_phone = escape(order.user.phone) if order.user and order.user.phone else "—"
    description = escape(order.description) if order.description else "—"
    return (
        f"📋 <b>Buyurtma</b>: <code>{order.order_uid}</code>\n"
        f"📌 Status: <b>{order.status.value}</b>\n"
        f"👤 Mijoz: {client_name}\n"
        f"📞 Telefon: <code>{client_phone}</code>\n"
        f"🔧 Muammo: {problem_label}\n"
        f"📝 Izoh: {description}"
    )


# ── Master /start (message command) ───────────────────────────────

@router.message(RoleFilter("master"), F.text == "/start")
async def master_start(
    message: Message,
    state: FSMContext,
    user_data: Master | None = None,
):
    """Show master dashboard via /start command."""
    await state.clear()
    is_online = user_data.status == MasterStatus.ONLINE if user_data else False
    await message.answer(
        _dashboard_text(user_data),
        parse_mode="HTML",
        reply_markup=master_main_menu(is_online),
    )


# ── ALL MENU BUTTONS (inline callbacks — immune to FSM/throttle) ──

@router.callback_query(F.data.in_({"master_menu:home", "master_menu:dashboard"}))
async def cb_master_home(
    callback: CallbackQuery,
    state: FSMContext,
    user_data: Master | None = None,
):
    """Return to dashboard from any screen."""
    await state.clear()
    is_online = user_data.status == MasterStatus.ONLINE if user_data else False
    await _safe_master_edit_text(
        callback, _dashboard_text(user_data),
        parse_mode="HTML",
        reply_markup=master_main_menu(is_online),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"master_menu:toggle_online", "master_menu:toggle_offline"}))
async def cb_toggle_availability(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user_data: Master | None = None,
):
    """Toggle master online/offline."""
    if not user_data:
        await callback.answer("Xatolik", show_alert=True)
        return
    await state.clear()
    master_repo = MasterRepo(session)
    new_status = await master_repo.toggle_status(callback.from_user.id)
    is_online = new_status == MasterStatus.ONLINE
    status_msg = "🟢 Siz endi <b>Online</b> — buyurtmalarga tayyorsiz!" if is_online else "🔴 Siz endi <b>Offline</b> — dam olish rejimi."
    await _safe_master_edit_text(
        callback, status_msg,
        parse_mode="HTML",
        reply_markup=master_main_menu(is_online),
    )
    await callback.answer("Online" if is_online else "Offline")


@router.callback_query(F.data == "master_menu:active_order")
async def cb_active_order(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user_data: Master | None = None,
):
    """Show master's active order."""
    await state.clear()
    if not user_data:
        await callback.answer("Sizda faol buyurtma yo'q.", show_alert=True)
        return
    order_repo = OrderRepo(session)
    order = await order_repo.get_active_by_master(user_data.id)
    if not order:
        await callback.answer("Sizda ayni paytda faol buyurtma yo'q.", show_alert=True)
        return
    if not order.user:
        order = await order_repo.get_by_uid(order.order_uid)
    text = _order_card(order)
    if order.status == OrderStatus.AWAITING_CONFIRM:
        amount_str = f"{order.payment_amount:,.0f}" if order.payment_amount else "—"
        await _safe_master_edit_text(
            callback,
            f"{text}\n\n⏳ <b>Tasdiqlash kutilmoqda.</b>\nSumma: {amount_str} so'm",
            parse_mode="HTML",
            reply_markup=master_back_keyboard(),
        )
    elif order.status == OrderStatus.ASSIGNED:
        await _safe_master_edit_text(
            callback, f"Yangi buyurtma:\n\n{text}",
            parse_mode="HTML",
            reply_markup=master_order_response(order.order_uid),
        )
    else:
        await _safe_master_edit_text(
            callback, f"Faol buyurtma:\n\n{text}",
            parse_mode="HTML",
            reply_markup=master_status_update_keyboard(order.order_uid, order.status.value),
        )
    if order.latitude and order.longitude:
        await bot.send_location(
            chat_id=callback.from_user.id,
            latitude=order.latitude, longitude=order.longitude,
        )
    await callback.answer()


@router.callback_query(F.data == "master_menu:stats")
async def cb_master_stats(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user_data: Master | None = None,
):
    """Show statistics."""
    await state.clear()
    if not user_data:
        await callback.answer("Xatolik", show_alert=True)
        return
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    master_repo = MasterRepo(session)
    ts = await master_repo.get_master_stats(user_data.id, since=today)
    ws = await master_repo.get_master_stats(user_data.id, since=week_start)
    ms = await master_repo.get_master_stats(user_data.id, since=month_start)
    await _safe_master_edit_text(
        callback,
        f"📊 <b>{escape(user_data.full_name)}</b>\n"
        f"──────────────────\n"
        f"📅 Bugun: {ts['completed_orders']} ta\n"
        f"📆 Hafta: {ws['completed_orders']} ta\n"
        f"🗓 Oy: {ms['completed_orders']} ta\n"
        f"──────────────────\n"
        f"💰 Oylik: {ms['total_sum']:,.0f} so'm\n"
        f"⭐ Reyting: {user_data.rating:.1f} / 5.0",
        parse_mode="HTML",
        reply_markup=master_back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "master_menu:rating")
async def cb_master_rating(
    callback: CallbackQuery,
    state: FSMContext,
    user_data: Master | None = None,
):
    """Show rating."""
    await state.clear()
    if not user_data:
        await callback.answer("Xatolik", show_alert=True)
        return
    stars = "⭐" * round(user_data.rating)
    empty = "🤍" * (5 - round(user_data.rating))
    await _safe_master_edit_text(
        callback,
        f"🏆 <b>Sizning reytingingiz</b>\n"
        f"──────────────────\n"
        f"Reyting: <b>{user_data.rating:.1f}</b> / 5.0\n"
        f"{stars}{empty}\n\n"
        f"✅ Yakunlangan: <b>{user_data.completed_orders}</b> ta\n"
        f"❌ Rad etilgan: <b>{user_data.rejected_orders}</b> ta",
        parse_mode="HTML",
        reply_markup=master_back_keyboard(),
    )
    await callback.answer()


# ── Accept/Reject order ──────────────────────────────────────────

@router.callback_query(
    F.data.startswith("master_accept:"),
)
async def accept_order(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    user_data: Master | None = None,
):
    """Master accepts an order."""
    parts = (callback.data or "").split(":", 1)
    if len(parts) < 2 or not parts[1]:
        await callback.answer("Xatolik: noto'g'ri buyruq.", show_alert=True)
        return
    order_uid = parts[1]
    order, validation_error = await _get_order_for_master(
        session=session,
        order_uid=order_uid,
        master_telegram_id=callback.from_user.id,
    )
    if validation_error:
        await callback.answer(validation_error, show_alert=True)
        return

    status_key = _master_keyboard_status_key(order.status) if order else None
    if order and order.status != OrderStatus.ASSIGNED:
        if status_key:
            await _safe_master_edit_text(
                callback,
                f"ℹ️ Buyurtma allaqachon <b>{order.status.value}</b> holatida.\n\n"
                "Davom etish uchun keyingi bosqichni bosing.",
                parse_mode="HTML",
                reply_markup=master_status_update_keyboard(order_uid, status_key),
            )
            await callback.answer("Buyurtma holati yangilandi.")
            return
        await callback.answer(
            f"Bu buyurtma hozir {order.status.value} holatida.",
            show_alert=True,
        )
        return

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

    await _safe_master_edit_text(
        callback,
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
    F.data.startswith("master_reject:"),
)
async def reject_order(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
    user_data: Master | None = None,
):
    """Master rejects an order."""
    parts = (callback.data or "").split(":", 1)
    if len(parts) < 2 or not parts[1]:
        await callback.answer("Xatolik: noto'g'ri buyruq.", show_alert=True)
        return
    order_uid = parts[1]
    order, validation_error = await _get_order_for_master(
        session=session,
        order_uid=order_uid,
        master_telegram_id=callback.from_user.id,
    )
    if validation_error:
        await callback.answer(validation_error, show_alert=True)
        return

    status_key = _master_keyboard_status_key(order.status) if order else None
    if order and order.status != OrderStatus.ASSIGNED:
        if status_key:
            await _safe_master_edit_text(
                callback,
                f"ℹ️ Buyurtma allaqachon <b>{order.status.value}</b> bosqichida.\n\n"
                "Rad etish endi mumkin emas, keyingi bosqich tugmasidan foydalaning.",
                parse_mode="HTML",
                reply_markup=master_status_update_keyboard(order_uid, status_key),
            )
            await callback.answer("Buyurtma holati yangilandi.")
            return
        await callback.answer(
            f"Bu buyurtma hozir {order.status.value} holatida.",
            show_alert=True,
        )
        return

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

    await _safe_master_edit_text(
        callback,
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
    if len(parts) < 3:
        await callback.answer("Xatolik: noto'g'ri buyruq.", show_alert=True)
        return
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

    order, validation_error = await _get_order_for_master(
        session=session,
        order_uid=order_uid,
        master_telegram_id=callback.from_user.id,
    )
    if validation_error:
        await callback.answer(validation_error, show_alert=True)
        return

    order_service = OrderService(session)

    # Special flow for "completed" — need amount + video
    if new_status == OrderStatus.AWAITING_CONFIRM:
        if order.status != OrderStatus.IN_PROGRESS:
            status_key = _master_keyboard_status_key(order.status)
            if status_key:
                await _safe_master_edit_text(
                    callback,
                    f"ℹ️ Buyurtma holati: <b>{order.status.value}</b>\n\n"
                    "Iltimos, navbatdagi to'g'ri bosqichni bosing.",
                    parse_mode="HTML",
                    reply_markup=master_status_update_keyboard(order_uid, status_key),
                )
                await callback.answer("Status yangilandi, keyingi bosqichni bosing.")
                return

            await callback.answer(
                f"Buyurtma hozir {order.status.value} holatida. Avval IN_PROGRESS bo'lishi kerak.",
                show_alert=True,
            )
            return

        await state.update_data(completing_order_uid=order_uid)
        await state.set_state(MasterOrderStates.recording_video)
        await _safe_master_edit_text(
            callback,
            t("master_video_prompt", "uz"),
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
        fresh_order = await OrderRepo(session).get_by_uid(order_uid)
        status_key = _master_keyboard_status_key(fresh_order.status) if fresh_order else None
        if status_key:
            await _safe_master_edit_text(
                callback,
                f"ℹ️ Buyurtma holati yangilanibdi: <b>{fresh_order.status.value}</b>\n\n"
                "Iltimos, navbatdagi bosqichni davom ettiring.",
                parse_mode="HTML",
                reply_markup=master_status_update_keyboard(order_uid, status_key),
            )
            await callback.answer("Holat yangilandi, keyingi tugma ko'rsatildi.")
            return

        await callback.answer(str(e), show_alert=True)
        return

    status_labels = {
        "on_the_way": "🚗 Yo'lga chiqdingiz!",
        "arrived": "📍 Yetib keldingiz!",
        "in_progress": "🔧 Ish boshlandi!",
    }
    label = status_labels.get(new_status_str, "✅ Status yangilandi")

    await _safe_master_edit_text(
        callback,
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
    bot: Bot,
    user_data: Master | None = None,
):
    """Handle payment amount entry and finalize order."""
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

    data = await state.get_data()
    video_file_id = data.get("video_file_id")
    video_kind = data.get("video_kind", "video_note")

    await state.update_data(payment_amount=amount)
    
    await _complete_master_order_with_video(
        message=message,
        state=state,
        session=session,
        bot=bot,
        user_data=user_data,
        video_file_id=video_file_id,
        video_kind=video_kind,
    )


@router.callback_query(
    F.data.startswith("master_amount:"),
)
async def request_amount_from_button(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """
    Legacy/compatibility handler:
    Some keyboards still emit master_amount:<order_uid>.
    """
    parts = (callback.data or "").split(":", 1)
    if len(parts) < 2 or not parts[1]:
        await callback.answer("Xatolik: noto'g'ri buyruq.", show_alert=True)
        return
    order_uid = parts[1]
    order, validation_error = await _get_order_for_master(
        session=session,
        order_uid=order_uid,
        master_telegram_id=callback.from_user.id,
    )
    if validation_error:
        await callback.answer(validation_error, show_alert=True)
        return

    if order.status != OrderStatus.IN_PROGRESS:
        await callback.answer(
            f"Bu tugma hozir ishlamaydi. Joriy holat: {order.status.value}",
            show_alert=True,
        )
        return

    await state.update_data(completing_order_uid=order_uid)
    await state.set_state(MasterOrderStates.recording_video)
    await _safe_master_edit_text(
        callback,
        t("master_video_prompt", "uz"),
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

    await state.update_data(video_file_id=message.video_note.file_id, video_kind="video_note")
    await state.set_state(MasterOrderStates.entering_amount)
    await message.answer(
        t("master_enter_amount", "uz"),
        parse_mode="HTML",
    )


@router.message(MasterOrderStates.recording_video, F.video)
async def process_master_video_file(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
    user_data: Master | None = None,
):
    """Handle regular video completion proof as fallback."""
    duration = int(getattr(message.video, "duration", 0) or 0)
    if duration > 15:
        await message.answer(
            "⚠️ Iltimos, yakunlash videosi 15 soniyadan oshmasin.\n"
            "Qisqa (0-15 soniya) video yuboring.",
        )
        return

    await state.update_data(video_file_id=message.video.file_id, video_kind="video")
    await state.set_state(MasterOrderStates.entering_amount)
    await message.answer(
        t("master_enter_amount", "uz"),
        parse_mode="HTML",
    )


@router.message(MasterOrderStates.recording_video, ~(F.video_note | F.video))
async def master_wrong_video_format(message: Message):
    """Handle non-video messages in video state (but let menu buttons through)."""
    await message.answer(
        "⚠️ Iltimos, <b>dumaloq video</b> yoki oddiy <b>video</b> yuboring (15 soniyagacha).\n\n"
        "<i>Bekor qilish uchun /start bosing.</i>",
        parse_mode="HTML",
    )


@router.message(MasterOrderStates.entering_amount, ~F.text)
async def master_wrong_amount_format(message: Message):
    """Handle non-text in amount state."""
    await message.answer(
        "⚠️ Iltimos, faqat <b>raqam</b> yuboring.\n"
        "Masalan: <code>150000</code>\n\n"
        "<i>Bekor qilish uchun /start bosing.</i>",
        parse_mode="HTML",
    )


# ── Call client ───────────────────────────────────────────────────

@router.callback_query(
    F.data.startswith("master_call:"),
)
async def master_call_client(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Show client phone for master to call."""
    parts = (callback.data or "").split(":", 1)
    if len(parts) < 2 or not parts[1]:
        await callback.answer("Xatolik: noto'g'ri buyruq.", show_alert=True)
        return
    order_uid = parts[1]
    order, validation_error = await _get_order_for_master(
        session=session,
        order_uid=order_uid,
        master_telegram_id=callback.from_user.id,
    )
    if validation_error:
        await callback.answer(validation_error, show_alert=True)
        return

    if not order or not order.user:
        await callback.answer("Ma'lumot topilmadi", show_alert=True)
        return

    safe_phone = escape(order.user.phone or "—")
    clean_phone = "".join(filter(str.isdigit, order.user.phone or ""))
    if clean_phone and not clean_phone.startswith("+"):
        clean_phone = f"+{clean_phone}"

    kb = None
    if clean_phone:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📲 Mijozga qo'ng'iroq qilish", url=f"tel:{clean_phone}")
        ]])

    await callback.message.answer(
        f"📞 Mijoz telefoni: <code>{safe_phone}</code>",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()
