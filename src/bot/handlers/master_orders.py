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
    "completed": OrderStatus.COMPLETED,
}


def _safe_msg(cb: CallbackQuery) -> Message | None:
    if cb.message is None or isinstance(cb.message, InaccessibleMessage):
        return None
    return cb.message


def _next_kb(order_id: int, status: OrderStatus) -> InlineKeyboardMarkup | None:
    NEXT: dict[OrderStatus, tuple[str, str]] = {
        OrderStatus.ACCEPTED: ("🚗 Yo'lga chiqdim", "on_the_way"),
        OrderStatus.ON_THE_WAY: ("📍 Yetib keldim va ishni boshladim", "in_progress"),
        OrderStatus.IN_PROGRESS: ("✅ Ishni tugatdim", "completed"),
    }
    entry = NEXT.get(status)
    if not entry:
        return None
    label, alias = entry
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"master_status:{order_id}:{alias}")],
            [InlineKeyboardButton(text="⚠️ Muammo (Rad etish)", callback_data=f"master_cancel:{order_id}")]
        ]
    )


def _cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def parse_uzbek_amount(text: str) -> float | None:
    """
    Intelligently parses Uzbek sum values from text.
    Handles space/period/comma thousands separators.
    Handles 'k', 'ming', 'тыс' (thousands) and 'mln', 'млн' (millions) suffixes.
    Example:
      "150 000" -> 150000.0
      "150k" -> 150000.0
      "150 ming" -> 150000.0
      "1.5 mln" -> 1500000.0
    """
    text = text.lower().strip()
    
    # Remove common currency tags
    for cur in ["so'm", "som", "сум", "сўм", "y", "у.е.", "usd", "$"]:
        text = text.replace(cur, "")
    text = text.strip()
    
    if not text:
        return None

    # Check million
    is_million = False
    for suffix in ["mln", "миллион", "млн"]:
        if suffix in text:
            is_million = True
            text = text.replace(suffix, "").strip()
            break

    # Check thousand
    is_thousand = False
    for suffix in ["ming", "тыс", "тысяч", "k", "к"]:
        if suffix in text:
            is_thousand = True
            text = text.replace(suffix, "").strip()
            break

    # Standardize thousands separator or decimals
    if is_million or is_thousand:
        text = text.replace(",", ".")
    else:
        text = text.replace(" ", "").replace(",", "").replace(".", "")

    text = text.replace(" ", "")

    try:
        cleaned = "".join(c for c in text if c.isdigit() or c == ".")
        if not cleaned:
            return None
        val = float(cleaned)
        if is_million:
            val *= 1_000_000
        elif is_thousand:
            val *= 1_000
        return val
    except ValueError:
        return None


# ── Commands ──────────────────────────────────────────────────────────────────

@router.message(Command("my_jobs"))
@router.message(F.text == "📦 Mening buyurtmalarim")
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
    # 1. Answer immediately to stop spinner
    await callback.answer()

    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
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
        
        master_name = settings.parsed_master_labels_map.get(callback.from_user.id) or callback.from_user.full_name or str(callback.from_user.id)
        await ns.notify_dispatcher_master_action(
            order_id=_order_id,
            master_name=master_name,
            action="accepted",
        )
    except Exception as exc:
        # Graceful double-tap check
        try:
            async with AsyncSessionFactory() as session:
                order = await session.scalar(select(Order).where(Order.id == order_id))
                if order and order.status == OrderStatus.ACCEPTED and order.assigned_master_telegram_id == callback.from_user.id:
                    _order_id = order.id
                    logger.info("cb_accept: order %s already accepted by master %s, ignoring error", order_id, callback.from_user.id)
                else:
                    raise exc
        except Exception:
            logger.exception("master_accept error for #%s: %s", order_id, exc)
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


@router.callback_query(F.data.startswith("master_reject:"))
async def cb_reject(callback: CallbackQuery) -> None:
    # 1. Answer immediately to stop spinner
    await callback.answer()

    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
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

        master_name = settings.parsed_master_labels_map.get(callback.from_user.id) or callback.from_user.full_name or str(callback.from_user.id)
        await ns.notify_dispatcher_master_action(
            order_id=_order_id,
            master_name=master_name,
            action="rejected",
        )
    except Exception as exc:
        # Graceful double-tap check
        try:
            async with AsyncSessionFactory() as session:
                order = await session.scalar(select(Order).where(Order.id == order_id))
                if order and order.status == OrderStatus.REJECTED:
                    _order_id = order.id
                    logger.info("cb_reject: order %s already rejected, ignoring error", order_id)
                else:
                    raise exc
        except Exception:
            logger.exception("master_reject error for #%s: %s", order_id, exc)
            return

    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"❌ Buyurtma <b>#{_order_id}</b> rad etildi.", parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass


@router.callback_query(F.data.startswith("master_cancel:"))
async def cb_cancel(callback: CallbackQuery) -> None:
    # 1. Answer immediately to stop spinner
    await callback.answer()

    try:
        order_id = int((callback.data or "").split(":")[1])
    except (IndexError, ValueError):
        return

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_drop_order(
                order_id=order_id,
                master_telegram_id=callback.from_user.id,
            )
            client = await session.scalar(select(User).where(User.id == order.client_id))
            client_telegram_id = client.telegram_id if client else None
            _order_id = order.id
            master_name = callback.from_user.full_name or callback.from_user.first_name

        ns = NotificationService(bot=callback.bot, settings=settings)
        # Notify dispatchers that master dropped the order
        if settings.resolved_dispatcher_chat_id:
            await callback.bot.send_message(
                chat_id=settings.resolved_dispatcher_chat_id,
                text=f"⚠️ <b>Usta {master_name}</b> buyurtmani oxiriga yetkaza olmadi!\nID: #{_order_id}\nIltimos, boshqa usta biriktiring.",
                parse_mode="HTML"
            )
            
        # Notify client that searching for another master
        if client_telegram_id:
            await callback.bot.send_message(
                chat_id=client_telegram_id,
                text="⚠️ Usta yetib kela olmadi. Boshqa usta qidirilmoqda...",
                parse_mode="HTML"
            )
    except Exception as exc:
        # Graceful double-tap check
        try:
            async with AsyncSessionFactory() as session:
                order = await session.scalar(select(Order).where(Order.id == order_id))
                if order and order.status == OrderStatus.NEW:
                    _order_id = order.id
                    logger.info("cb_cancel: order %s already dropped, ignoring error", order_id)
                else:
                    raise exc
        except Exception:
            logger.exception("master_cancel error for #%s: %s", order_id, exc)
            return

    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"❌ Buyurtma <b>#{_order_id}</b> bekor qilindi.", parse_mode="HTML"
            )
        except TelegramBadRequest:
            pass


# ── Status progression ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("master_status:"))
async def cb_master_status(callback: CallbackQuery, state: FSMContext) -> None:
    # 1. Answer immediately to stop spinner
    await callback.answer()

    try:
        parts = (callback.data or "").split(":")
        order_id = int(parts[1])
        alias = parts[2]
    except (IndexError, ValueError):
        return

    to_status = MASTER_STATUS_ALIASES.get(alias)
    if not to_status:
        return

    # Completion: collect video + amount via FSM first
    if to_status == OrderStatus.COMPLETED:
        await state.update_data(master_order_id=order_id)
        await state.set_state(MasterCompletionState.waiting_for_video)
        msg = _safe_msg(callback)
        if msg:
            try:
                await msg.answer(
                    f"📹 Buyurtma <b>#{order_id}</b> yakunlash:\n\n"
                    "Xizmat jarayonidan qisqa <b>video xabar</b> yuboring:",
                    parse_mode="HTML",
                    reply_markup=_cancel_kb()
                )
            except Exception:
                pass
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
        
        master_name = settings.parsed_master_labels_map.get(callback.from_user.id) or callback.from_user.full_name or str(callback.from_user.id)
        await ns.notify_dispatcher_master_status_change(
            order_id=_order_id,
            master_name=master_name,
            status=_status,
        )
    except Exception as exc:
        # Graceful double-tap check
        try:
            async with AsyncSessionFactory() as session:
                order = await session.scalar(select(Order).where(Order.id == order_id))
                if order and order.status == to_status:
                    _order_id = order.id
                    _status = order.status
                    logger.info("cb_master_status: order %s already transitioned to status %s, ignoring error", order_id, to_status)
                else:
                    raise exc
        except Exception:
            logger.exception("master_status error #%s %s: %s", order_id, alias, exc)
            return

    labels = {
        OrderStatus.ON_THE_WAY: "🚗 Yo'lda",
        OrderStatus.ARRIVED: "📍 Yetib keldim",
        OrderStatus.IN_PROGRESS: "🛠 Ishlamoqda",
    }
    
    # If there is a next status, show the keyboard. Otherwise just text.
    kb = _next_kb(_order_id, _status)
    msg = _safe_msg(callback)
    if msg:
        try:
            await msg.edit_text(
                f"Buyurtma <b>#{_order_id}</b>\nStatus: <b>{labels.get(_status, _status.name)}</b>",
                reply_markup=kb,
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass


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
async def invalid_video(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        return
    if text == "/start":
        await state.clear()
        from src.bot.handlers.driver_quick_order import cmd_start
        await cmd_start(message, state)
        return
    if text in ("/my_jobs", "📦 Mening buyurtmalarim"):
        await state.clear()
        await cmd_my_jobs(message)
        return

    await message.answer(
        "⚠️ Iltimos, <b>video xabar</b> yoki video yuboring.",
        parse_mode="HTML",
    )


# ── FSM: amount submission → complete ─────────────────────────────────────────

@router.message(MasterCompletionState.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return

    text = (message.text or "").strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        return
    if text == "/start":
        await state.clear()
        from src.bot.handlers.driver_quick_order import cmd_start
        await cmd_start(message, state)
        return
    if text in ("/my_jobs", "📦 Mening buyurtmalarim"):
        await state.clear()
        await cmd_my_jobs(message)
        return

    amount = parse_uzbek_amount(text)
    if amount is None or amount <= 0:
        await message.answer(
            "⚠️ Summani to'g'ri formatda kiriting (masalan: 150 000, 150k, 1.5 mln yoki 150 ming so'm).",
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

    master_name = settings.parsed_master_labels_map.get(message.from_user.id) or message.from_user.full_name or str(message.from_user.id)

    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.master_transition(
                order_id=order_id,
                master_telegram_id=message.from_user.id,
                to_status=OrderStatus.COMPLETED,
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
                status=OrderStatus.COMPLETED,
            )

        # Notify dispatcher that it is completed
        await ns.notify_dispatcher_order_completed(
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
        f"✅ <b>Buyurtma #{order_id}</b> to'liq yakunlandi!\n\n"
        f"💰 Summa: <b>{amount:,.0f} so'm</b>\n\n"
        "Xizmat uchun rahmat! 🙏",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
