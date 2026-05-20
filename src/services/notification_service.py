"""
NotificationService — all outbound bot messages.

IMPORTANT: Order relationships use lazy='raise'. 
This service receives scalar data explicitly (telegram_id, language, etc.)
rather than accessing order.client or order.status_history.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.keyboards.driver import normalize_language
from src.core.config import PLACEHOLDER_CHAT_IDS, Settings
from src.db.enums import OrderStatus
from src.db.models.order import Order

logger = logging.getLogger(__name__)

# ── Client-facing text ────────────────────────────────────────────────────────

_CLIENT_TEXT: dict[str, dict[str, str]] = {
    "assigned": {
        "uz": "📋 Buyurtma #{id}: Usta tayinlandi, tez orada siz bilan bog'lanadi.",
        "ru": "📋 Заявка #{id}: Мастер назначен, скоро свяжется с вами.",
    },
    "accepted": {
        "uz": "🤝 Buyurtma #{id}: Usta qabul qildi — yo'lga chiqqanini kutib turing.",
        "ru": "🤝 Заявка #{id}: Мастер принял заказ — ожидайте выезда.",
    },
    "on_the_way": {
        "uz": "🚗 Buyurtma #{id}: Usta yo'lda!",
        "ru": "🚗 Заявка #{id}: Мастер едет к вам!",
    },
    "arrived": {
        "uz": "📍 Buyurtma #{id}: Usta manzilingizga yetib keldi!",
        "ru": "📍 Заявка #{id}: Мастер прибыл на место!",
    },
    "in_progress": {
        "uz": "🛠 Buyurtma #{id}: Usta yetib keldi va ishni boshladi.",
        "ru": "🛠 Заявка #{id}: Мастер прибыл и приступил к работе.",
    },
    "cancelled": {
        "uz": "🚫 Buyurtma #{id} bekor qilindi.",
        "ru": "🚫 Заявка #{id} отменена.",
    },
    "completed": {
        "uz": "🎉 Buyurtma #{id} yakunlandi! Xizmatga baho bering:",
        "ru": "🎉 Заявка #{id} завершена! Оцените наш сервис:",
    },
}

_STATUS_TO_KEY = {
    OrderStatus.ASSIGNED: "assigned",
    OrderStatus.ACCEPTED: "accepted",
    OrderStatus.ON_THE_WAY: "on_the_way",
    OrderStatus.ARRIVED: "arrived",
    OrderStatus.IN_PROGRESS: "in_progress",
    OrderStatus.CANCELLED: "cancelled",
    OrderStatus.COMPLETED: "completed",
}


class NotificationService:
    """Central service for all bot notifications."""

    _background_tasks: set = set()

    def __init__(self, bot: Bot, settings: Settings):
        self.bot = bot
        self.settings = settings

    # ── Broadcast targets ─────────────────────────────────────────────────────

    def _broadcast_targets(self) -> set[int]:
        targets: set[int] = set()
        main = self.settings.resolved_dispatcher_chat_id
        if main:
            targets.add(main)
        targets.update(self.settings.parsed_dispatcher_ids)
        targets.update(self.settings.parsed_admin_ids)
        return {t for t in targets if t and t not in PLACEHOLDER_CHAT_IDS}

    # ── Video note ────────────────────────────────────────────────────────────

    async def _send_confirmation_video(self, chat_id: int, language: str) -> None:
        """Send language-specific confirmation video note to client."""
        file_id = self.settings.confirmation_video_file_id(language)
        if not file_id:
            logger.debug("No confirmation video configured for lang=%s", language)
            return

        kind = (self.settings.dispatcher_confirm_video_kind or "video_note").strip().lower()
        try:
            if kind in {"video", "regular_video"}:
                await self.bot.send_video(chat_id=chat_id, video=file_id)
            else:
                await self.bot.send_video_note(chat_id=chat_id, video_note=file_id)
            logger.info("Sent confirmation %s to %s", kind, chat_id)
        except Exception as exc:
            logger.warning("Failed %s to %s: %s — trying fallback", kind, chat_id, exc)
            try:
                if kind in {"video", "regular_video"}:
                    await self.bot.send_video_note(chat_id=chat_id, video_note=file_id)
                else:
                    await self.bot.send_video(chat_id=chat_id, video=file_id)
            except Exception as exc2:
                logger.error("Fallback video also failed for %s: %s", chat_id, exc2)

    # ── Client notifications ──────────────────────────────────────────────────

    async def notify_client_order_created(
        self,
        *,
        order_id: int,
        client_telegram_id: int,
        language: str | None,
    ) -> None:
        """
        Immediately send text confirmation, then send video note after 10 seconds
        in a background task (non-blocking).
        """
        lang = normalize_language(language)

        # The text confirmation is handled by the handler's msg.edit_text()
        # We only need to start the delayed video task.

        # Delayed video note — background task, never blocks the handler
        task = asyncio.create_task(
            self._delayed_video(client_telegram_id, lang)
        )
        NotificationService._background_tasks.add(task)
        task.add_done_callback(NotificationService._background_tasks.discard)

    async def _delayed_video(self, chat_id: int, language: str) -> None:
        await asyncio.sleep(10)
        await self._send_confirmation_video(chat_id, language)

    async def notify_client_status_change(
        self,
        *,
        order_id: int,
        client_telegram_id: int,
        client_language: str | None,
        status: OrderStatus,
    ) -> None:
        """
        Notify client of a status change.
        NOTE: Accepts scalar values directly — does NOT touch order.client relationship.
        """
        if not client_telegram_id:
            return

        key = _STATUS_TO_KEY.get(status)
        if not key:
            return

        lang = normalize_language(client_language)
        text = _CLIENT_TEXT[key][lang].format(id=order_id)
        keyboard = None

        if status == OrderStatus.COMPLETED:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⭐ 1", callback_data=f"client_rating:{order_id}:1"
                        ),
                        InlineKeyboardButton(
                            text="⭐⭐ 2", callback_data=f"client_rating:{order_id}:2"
                        ),
                        InlineKeyboardButton(
                            text="⭐⭐⭐ 3", callback_data=f"client_rating:{order_id}:3"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="⭐⭐⭐⭐ 4", callback_data=f"client_rating:{order_id}:4"
                        ),
                        InlineKeyboardButton(
                            text="⭐⭐⭐⭐⭐ 5", callback_data=f"client_rating:{order_id}:5"
                        ),
                    ],
                ]
            )

        try:
            await self.bot.send_message(
                chat_id=client_telegram_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error(
                "Failed to notify client %s of status %s: %s",
                client_telegram_id, status, exc
            )

    # ── Dispatcher notifications ──────────────────────────────────────────────

    async def notify_new_order(
        self,
        *,
        order_id: int,
        client_telegram_id: int,
        phone: str,
        issue: str,
        latitude: float,
        longitude: float,
    ) -> None:
        """Broadcast new order to all dispatcher targets."""
        maps = f"https://maps.google.com/?q={latitude},{longitude}"
        text = (
            "🚨 <b>Yangi buyurtma!</b>\n\n"
            f"🆔 ID: <b>#{order_id}</b>\n"
            f"📞 Telefon: <b>{phone}</b>\n"
            f"🛠 Muammo: <b>{issue}</b>\n"
            f'📍 <a href="{maps}">Google Maps</a>\n\n'
            "Usta biriktirish uchun tugmani bosing:"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"👨‍🔧 Usta biriktirish #{order_id}",
                        callback_data=f"dispatch_assign:{order_id}",
                    )
                ]
            ]
        )

        targets = self._broadcast_targets()
        if not targets:
            logger.warning(
                "No dispatcher targets configured — order #%s not broadcast!", order_id
            )
            return

        for target in targets:
            try:
                await self.bot.send_message(
                    chat_id=target, text=text, reply_markup=keyboard, parse_mode="HTML"
                )
            except Exception as exc:
                logger.error("Broadcast order #%s to %s failed: %s", order_id, target, exc)

    async def notify_master_new_assignment(
        self,
        *,
        order_id: int,
        phone: str,
        issue_label: str,
        latitude: float,
        longitude: float,
        master_telegram_id: int,
    ) -> None:
        """Send order details + Accept/Reject buttons to master."""
        maps = f"https://maps.google.com/?q={latitude},{longitude}"
        text = (
            "📦 <b>Sizga yangi buyurtma!</b>\n\n"
            f"🆔 ID: <b>#{order_id}</b>\n"
            f"🛠 Muammo: <b>{issue_label}</b>\n"
            f"📞 Telefon: <b>{phone}</b>\n"
            f'📍 <a href="{maps}">Lokatsiya</a>\n\n'
            "Qabul qiling yoki rad eting:"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Qabul qilish",
                        callback_data=f"master_accept:{order_id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Rad etish",
                        callback_data=f"master_reject:{order_id}",
                    ),
                ]
            ]
        )
        try:
            await self.bot.send_location(
                chat_id=master_telegram_id,
                latitude=latitude,
                longitude=longitude,
            )
            await self.bot.send_message(
                chat_id=master_telegram_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Failed to notify master %s: %s", master_telegram_id, exc)

    async def notify_dispatcher_order_completed(
        self,
        *,
        order_id: int,
        final_amount: float | None,
        video_file_id: str | None,
        master_name: str,
    ) -> None:
        """Tell dispatchers master finished."""
        amount_str = (
            f"{float(final_amount):,.0f} so'm" if final_amount else "Noma'lum"
        )
        text = (
            f"✅ <b>{master_name}</b> ishni to'liq yakunladi.\n\n"
            f"🆔 Buyurtma: <b>#{order_id}</b>\n"
            f"💰 Summa: <b>{amount_str}</b>\n"
        )

        targets = self._broadcast_targets()
        for target in targets:
            try:
                # Send completion video first if available
                if video_file_id:
                    try:
                        await self.bot.send_video_note(
                            chat_id=target, video_note=video_file_id
                        )
                    except Exception:
                        try:
                            await self.bot.send_video(chat_id=target, video=video_file_id)
                        except Exception as ve:
                            logger.error("Could not send video to %s: %s", target, ve)

                await self.bot.send_message(
                    chat_id=target, text=text, parse_mode="HTML"
                )
            except Exception as exc:
                logger.error(
                    "Failed to notify dispatcher %s of completion #%s: %s",
                    target, order_id, exc
                )

    async def notify_dispatcher_master_action(
        self,
        *,
        order_id: int,
        master_name: str,
        action: str,  # "accepted" or "rejected"
    ) -> None:
        """Tell dispatchers when a master accepts or rejects an assignment."""
        emoji = "✅" if action == "accepted" else "❌"
        action_uz = "qabul qildi" if action == "accepted" else "rad etdi"
        action_ru = "принял заказ" if action == "accepted" else "отклонил заказ"
        
        text = (
            f"{emoji} <b>👨‍🔧 Usta {master_name}</b> buyurtmani {action_uz}!\n"
            f"🆔 Buyurtma ID: <b>#{order_id}</b>\n"
            f"Holat: <b>{action.upper()}</b>"
        )
        
        # If rejected, add a quick assign button
        keyboard = None
        if action == "rejected":
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"👨‍🔧 Boshqa usta biriktirish #{order_id}",
                            callback_data=f"dispatch_assign:{order_id}",
                        )
                    ]
                ]
            )

        targets = self._broadcast_targets()
        for target in targets:
            try:
                await self.bot.send_message(
                    chat_id=target,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as exc:
                logger.error(
                    "Failed to notify dispatcher %s of master action %s on order #%s: %s",
                    target, action, order_id, exc
                )

    async def notify_dispatcher_master_status_change(
        self,
        *,
        order_id: int,
        master_name: str,
        status: OrderStatus,
    ) -> None:
        """Broadcast real-time status update to all dispatchers when master starts moving or arrives."""
        _status_info: dict[OrderStatus, tuple[str, str]] = {
            OrderStatus.ON_THE_WAY: ("🚗", "yo'lga chiqdi"),
            OrderStatus.ARRIVED: ("📍", "yetib keldi"),
            OrderStatus.IN_PROGRESS: ("🛠", "ishni boshladi"),
        }
        emoji, status_uz = _status_info.get(status, ("ℹ️", status.name))
        
        text = (
            f"{emoji} <b>👨‍🔧 Usta {master_name}</b>:\n"
            f"🆔 Buyurtma: <b>#{order_id}</b>\n"
            f"Holat: <b>{status_uz.capitalize()}</b>"
        )
        
        targets = self._broadcast_targets()
        for target in targets:
            try:
                await self.bot.send_message(
                    chat_id=target,
                    text=text,
                    parse_mode="HTML"
                )
            except Exception as exc:
                logger.error(
                    "Failed to notify dispatcher %s of status %s on order #%s: %s",
                    target, status, order_id, exc
                )


