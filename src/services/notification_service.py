import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.keyboards.driver import normalize_language
from src.core.config import PLACEHOLDER_CHAT_IDS, Settings
from src.db.enums import OrderStatus
from src.db.models.order import Order

logger = logging.getLogger(__name__)

# ── Client-facing text ──────────────────────────────────────────────────────

CLIENT_TEXT: dict[str, dict[str, str]] = {
    "created": {
        "uz": "✅ Buyurtmangiz qabul qilindi. Dispecher #{order_id} raqamli buyurtmangizni ko'rib chiqmoqda.",
        "ru": "✅ Ваша заявка #{order_id} принята. Диспетчер уже проверяет её.",
    },
    "assigned": {
        "uz": "📋 Buyurtma #{order_id}: Usta tayinlandi, tez orada siz bilan bog'lanadi.",
        "ru": "📋 Заявка #{order_id}: Мастер назначен, скоро свяжется с вами.",
    },
    "accepted": {
        "uz": "🤝 Buyurtma #{order_id}: Usta tayyor — yo'lga chiqqanini kutib turing.",
        "ru": "🤝 Заявка #{order_id}: Мастер принял заказ — ожидайте выезда.",
    },
    "on_the_way": {
        "uz": "🚗 Buyurtma #{order_id}: Usta yo'lda! Yaqin orada yetib keladi.",
        "ru": "🚗 Заявка #{order_id}: Мастер едет! Ожидайте скорого прибытия.",
    },
    "arrived": {
        "uz": "📍 Buyurtma #{order_id}: Usta manzilingizga yetib keldi!",
        "ru": "📍 Заявка #{order_id}: Мастер прибыл на место!",
    },
    "in_progress": {
        "uz": "🛠 Buyurtma #{order_id}: Usta ta'mirlashni boshladi.",
        "ru": "🛠 Заявка #{order_id}: Мастер приступил к работе.",
    },
    "cancelled": {
        "uz": "🚫 Buyurtma #{order_id} bekor qilindi. Savol bo'lsa, bog'laning.",
        "ru": "🚫 Заявка #{order_id} отменена. Если есть вопросы — свяжитесь с нами.",
    },
    "completed": {
        "uz": "🎉 Buyurtma #{order_id} muvaffaqiyatli yakunlandi! Xizmatimizdan mamnunmisiz? Iltimos, baho bering:",
        "ru": "🎉 Заявка #{order_id} успешно завершена! Как вам наш сервис? Пожалуйста, оцените:",
    },
}


def _client_text(order: Order, key: str) -> str:
    language = normalize_language(order.client.language if order.client else None)
    return CLIENT_TEXT[key][language].format(order_id=order.id)


class NotificationService:
    """Central service for all bot notifications."""

    _background_tasks: set = set()

    def __init__(self, bot: Bot, settings: Settings):
        self.bot = bot
        self.settings = settings

    # ── Video note ──────────────────────────────────────────────────────────

    async def _send_confirmation_video(self, chat_id: int, language: str | None) -> None:
        """Send the configured confirmation video/note to the client."""
        file_id = self.settings.confirmation_video_file_id(language)
        if not file_id:
            logger.debug("No confirmation video configured for lang=%s, skipping.", language)
            return

        kind = (self.settings.dispatcher_confirm_video_kind or "video_note").strip().lower()
        try:
            if kind in {"video", "regular_video"}:
                await self.bot.send_video(chat_id=chat_id, video=file_id)
            else:
                await self.bot.send_video_note(chat_id=chat_id, video_note=file_id)
            logger.info("Sent confirmation video (kind=%s) to %s", kind, chat_id)
        except Exception as exc:
            logger.warning(
                "Failed to send %s to %s: %s — trying fallback.", kind, chat_id, exc
            )
            try:
                # Absolute fallback: try the other type
                if kind in {"video", "regular_video"}:
                    await self.bot.send_video_note(chat_id=chat_id, video_note=file_id)
                else:
                    await self.bot.send_video(chat_id=chat_id, video=file_id)
            except Exception as exc2:
                logger.error("Final video send failure for %s: %s", chat_id, exc2)

    # ── Broadcast targets ───────────────────────────────────────────────────

    def _broadcast_targets(self) -> set[int]:
        """Collect all relevant chat IDs for dispatcher/admin notifications."""
        targets: set[int] = set()

        # 1. Resolved dispatcher group/chat
        main = self.settings.resolved_dispatcher_chat_id
        if main:
            targets.add(main)

        # 2. Individual dispatcher IDs
        targets.update(self.settings.parsed_dispatcher_ids)

        # 3. Individual admin IDs (superadmins see everything)
        targets.update(self.settings.parsed_admin_ids)

        # Remove any placeholder or zero values
        return {t for t in targets if t and t not in PLACEHOLDER_CHAT_IDS}

    # ── Client notifications ────────────────────────────────────────────────

    async def notify_client_order_created(
        self, order_id: int, client_telegram_id: int, language: str | None
    ) -> None:
        """
        1. Send immediate text confirmation to client.
        2. Schedule a delayed video note (10 seconds later) as a background task.
        """
        language = normalize_language(language)

        # Immediate text
        try:
            text = CLIENT_TEXT["created"][language].format(order_id=order_id)
            await self.bot.send_message(chat_id=client_telegram_id, text=text)
        except Exception as exc:
            logger.error("Failed to send text confirmation to %s: %s", client_telegram_id, exc)

        # Delayed video in background (non-blocking)
        task = asyncio.create_task(
            self._delayed_video(client_telegram_id, language)
        )
        NotificationService._background_tasks.add(task)
        task.add_done_callback(NotificationService._background_tasks.discard)

    async def _delayed_video(self, chat_id: int, language: str) -> None:
        """Wait 10 s then send the pre-configured confirmation video note."""
        await asyncio.sleep(10)
        try:
            await self._send_confirmation_video(chat_id, language)
        except Exception as exc:
            logger.error("Delayed video failed for %s: %s", chat_id, exc)

    async def notify_client_status_change(self, order: Order, status: OrderStatus) -> None:
        """Notify client of any order status change (except NEW → creation handled separately)."""
        if not order.client or not order.client.telegram_id:
            logger.warning(
                "Order #%s has no client telegram_id, skipping status notification.",
                order.id,
            )
            return

        client_id = order.client.telegram_id
        text = ""
        keyboard = None

        if status == OrderStatus.ASSIGNED:
            text = _client_text(order, "assigned")
        elif status == OrderStatus.ACCEPTED:
            text = _client_text(order, "accepted")
        elif status == OrderStatus.ON_THE_WAY:
            text = _client_text(order, "on_the_way")
        elif status == OrderStatus.ARRIVED:
            text = _client_text(order, "arrived")
        elif status == OrderStatus.IN_PROGRESS:
            text = _client_text(order, "in_progress")
        elif status == OrderStatus.CANCELLED:
            text = _client_text(order, "cancelled")
        elif status == OrderStatus.COMPLETED:
            text = _client_text(order, "completed")
            # Rating buttons: 1–5 stars
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="⭐ 1", callback_data=f"client_rating:{order.id}:1"),
                        InlineKeyboardButton(text="⭐⭐ 2", callback_data=f"client_rating:{order.id}:2"),
                        InlineKeyboardButton(text="⭐⭐⭐ 3", callback_data=f"client_rating:{order.id}:3"),
                    ],
                    [
                        InlineKeyboardButton(text="⭐⭐⭐⭐ 4", callback_data=f"client_rating:{order.id}:4"),
                        InlineKeyboardButton(text="⭐⭐⭐⭐⭐ 5", callback_data=f"client_rating:{order.id}:5"),
                    ],
                ]
            )

        if not text:
            return

        try:
            await self.bot.send_message(chat_id=client_id, text=text, reply_markup=keyboard)
        except Exception as exc:
            logger.exception("Failed to send client notification to %s: %s", client_id, exc)

    # ── Dispatcher notifications ────────────────────────────────────────────

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
        """Broadcast new order notification to all dispatcher targets."""
        maps_link = f"https://maps.google.com/?q={latitude},{longitude}"
        text = (
            "🚨 <b>Yangi buyurtma!</b>\n\n"
            f"🆔 ID: <b>#{order_id}</b>\n"
            f"👤 Mijoz ID: <code>{client_telegram_id}</code>\n"
            f"📞 Telefon: <b>{phone}</b>\n"
            f"🛠 Muammo: <b>{issue}</b>\n"
            f'📍 <a href="{maps_link}">Google Maps da ko\'rish</a>\n\n'
            "⚠️ Ustani biriktirish uchun quyidagi tugmani bosing."
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
                "No dispatcher/admin targets configured — new order #%s will not be notified!",
                order_id,
            )

        for target_id in targets:
            try:
                await self.bot.send_message(
                    chat_id=target_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except Exception as exc:
                logger.error("Failed to broadcast new order #%s to %s: %s", order_id, target_id, exc)

    async def notify_master_new_assignment(self, order: Order, master_telegram_id: int) -> None:
        """Send order details + Accept/Reject buttons to the assigned master."""
        maps_link = f"https://maps.google.com/?q={order.latitude},{order.longitude}"
        text = (
            "📦 <b>Sizga yangi buyurtma biriktirildi!</b>\n\n"
            f"🆔 ID: <b>#{order.id}</b>\n"
            f"🛠 Muammo: <b>{order.issue_label}</b>\n"
            f"📞 Telefon: <b>{order.phone}</b>\n"
            f'📍 <a href="{maps_link}">Lokatsiyani ko\'rish</a>\n\n'
            "✅ Qabul qiling yoki ❌ rad eting:"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Qabul qilish", callback_data=f"master_accept:{order.id}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Rad etish", callback_data=f"master_reject:{order.id}"
                    ),
                ]
            ]
        )
        try:
            # Send location first so master can navigate easily
            await self.bot.send_location(
                chat_id=master_telegram_id,
                latitude=order.latitude,
                longitude=order.longitude,
            )
            await self.bot.send_message(
                chat_id=master_telegram_id, text=text, reply_markup=keyboard, parse_mode="HTML"
            )
        except Exception as exc:
            logger.exception("Failed to notify master %s: %s", master_telegram_id, exc)

    async def notify_dispatcher_completion_review(
        self, order: Order, master_name: str
    ) -> None:
        """
        Tell dispatcher/admin that master has finished and submitted video + amount.
        Includes a 'Confirm Payment' button.
        """
        amount_str = f"{float(order.final_amount):,.0f} so'm" if order.final_amount else "Noma'lum"
        text = (
            f"✅ <b>{master_name}</b> ishni yakunladi.\n\n"
            f"🆔 Buyurtma: <b>#{order.id}</b>\n"
            f"💰 Summa: <b>{amount_str}</b>\n"
            "🎬 Video isbot quyida yuborildi. To'lovni tasdiqlang:"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💰 To'lovni tasdiqlash",
                        callback_data=f"dispatch_complete:{order.id}",
                    )
                ]
            ]
        )

        targets = self._broadcast_targets()
        for target_id in targets:
            try:
                # Send completion video if available
                if order.video_file_id:
                    try:
                        await self.bot.send_video_note(
                            chat_id=target_id, video_note=order.video_file_id
                        )
                    except Exception:
                        try:
                            await self.bot.send_video(
                                chat_id=target_id, video=order.video_file_id
                            )
                        except Exception as ve:
                            logger.error(
                                "Could not send completion video to %s: %s", target_id, ve
                            )

                await self.bot.send_message(
                    chat_id=target_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except Exception as exc:
                logger.error(
                    "Failed to broadcast completion review #%s to %s: %s",
                    order.id,
                    target_id,
                    exc,
                )
