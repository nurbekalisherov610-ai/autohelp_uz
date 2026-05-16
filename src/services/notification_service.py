import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.keyboards.driver import normalize_language
from src.core.config import Settings
from src.db.enums import OrderStatus
from src.db.models.order import Order

logger = logging.getLogger(__name__)

CLIENT_TEXT: dict[str, dict[str, str]] = {
    "created": {
        "uz": "Buyurtmangiz qabul qilindi. Dispecher buyurtmani ko'rib chiqmoqda.",
        "ru": "Ваша заявка принята. Диспетчер уже проверяет заказ.",
    },
    "assigned": {
        "uz": "Sizning #{order_id} raqamli buyurtmangizga usta biriktirildi.",
        "ru": "К вашей заявке #{order_id} назначен мастер.",
    },
    "accepted": {
        "uz": "Usta sizning #{order_id} raqamli buyurtmangizni qabul qildi.",
        "ru": "Мастер принял вашу заявку #{order_id}.",
    },
    "on_the_way": {
        "uz": "Sizning #{order_id} raqamli buyurtmangiz bo'yicha usta yo'lga chiqdi.",
        "ru": "Мастер выехал по вашей заявке #{order_id}.",
    },
    "arrived": {
        "uz": "Usta manzilingizga yetib keldi. Buyurtma: #{order_id}",
        "ru": "Мастер прибыл на место. Заявка: #{order_id}",
    },
    "in_progress": {
        "uz": "Usta ta'mirlashni boshladi. Buyurtma: #{order_id}",
        "ru": "Мастер начал работу. Заявка: #{order_id}",
    },
    "cancelled": {
        "uz": "Sizning #{order_id} raqamli buyurtmangiz bekor qilindi. Biz bilan bog'laning.",
        "ru": "Ваша заявка #{order_id} отменена. Свяжитесь с нами.",
    },
    "completed": {
        "uz": "Buyurtmangiz (#{order_id}) muvaffaqiyatli yakunlandi. Xizmatimizdan mamnunmisiz? Iltimos, baho bering:",
        "ru": "Ваша заявка #{order_id} успешно завершена. Оцените, пожалуйста, работу сервиса:",
    },
}


def _client_text(order: Order, key: str) -> str:
    language = normalize_language(order.client.language if order.client else None)
    return CLIENT_TEXT[key][language].format(order_id=order.id)


class NotificationService:
    def __init__(self, bot: Bot, settings: Settings):
        self.bot = bot
        self.settings = settings

    async def _send_configured_confirmation_video(self, chat_id: int, language: str | None) -> None:
        file_id = self.settings.confirmation_video_file_id(language)
        if not file_id:
            return

        kind = (self.settings.dispatcher_confirm_video_kind or "video_note").strip().lower()
        try:
            if kind in {"video", "regular_video"}:
                await self.bot.send_video(chat_id=chat_id, video=file_id)
            else:
                await self.bot.send_video_note(chat_id=chat_id, video_note=file_id)
        except Exception as exc:
            logger.exception("Failed to send configured confirmation video to %s: %s", chat_id, exc)

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
        if self.settings.resolved_dispatcher_chat_id is None:
            return

        maps_link = f"https://maps.google.com/?q={latitude},{longitude}"
        text = (
            "Yangi buyurtma (NEW)\n"
            f"Buyurtma ID: #{order_id}\n"
            f"Mijoz ID: {client_telegram_id}\n"
            f"Telefon: {phone}\n"
            f"Muammo: {issue}\n"
            f"Lokatsiya: {maps_link}\n"
            "Status: NEW"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"Qabul qilish #{order_id}",
                        callback_data=f"dispatch_assign:{order_id}",
                    )
                ]
            ]
        )

        try:
            await self.bot.send_message(
                chat_id=self.settings.resolved_dispatcher_chat_id,
                text=text,
                reply_markup=keyboard,
            )
        except Exception as exc:
            logger.exception("Failed to send new order notification: %s", exc)

    async def notify_client_order_created(self, order: Order) -> None:
        if not order.client or not order.client.telegram_id:
            return

        client_id = order.client.telegram_id
        try:
            await self._send_configured_confirmation_video(client_id, order.client.language)
        except Exception as exc:
            logger.exception("Failed to send order-created notification to %s: %s", client_id, exc)

    async def notify_master_new_assignment(self, order: Order, master_telegram_id: int) -> None:
        text = (
            "Sizga yangi buyurtma biriktirildi!\n\n"
            f"Buyurtma ID: #{order.id}\n"
            f"Muammo: {order.issue_label}\n"
            f"Telefon: {order.phone}\n"
            f"Lokatsiya: https://maps.google.com/?q={order.latitude},{order.longitude}"
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"master_accept:{order.id}"),
                    InlineKeyboardButton(text="❌ Rad etish", callback_data=f"master_reject:{order.id}"),
                ]
            ]
        )
        try:
            await self.bot.send_location(
                chat_id=master_telegram_id,
                latitude=order.latitude,
                longitude=order.longitude,
            )
            await self.bot.send_message(chat_id=master_telegram_id, text=text, reply_markup=keyboard)
        except Exception as exc:
            logger.exception("Failed to notify master %s: %s", master_telegram_id, exc)

    async def notify_client_status_change(self, order: Order, status: OrderStatus) -> None:
        if not order.client or not order.client.telegram_id:
            logger.warning("Order #%s has no client telegram_id, skipping notification.", order.id)
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
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="⭐", callback_data=f"client_rating:{order.id}:1"),
                        InlineKeyboardButton(text="⭐⭐", callback_data=f"client_rating:{order.id}:2"),
                        InlineKeyboardButton(text="⭐⭐⭐", callback_data=f"client_rating:{order.id}:3"),
                    ],
                    [
                        InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data=f"client_rating:{order.id}:4"),
                        InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data=f"client_rating:{order.id}:5"),
                    ],
                ]
            )

        if not text:
            return

        try:
            await self.bot.send_message(chat_id=client_id, text=text, reply_markup=keyboard)
            if status == OrderStatus.ASSIGNED:
                await self._send_configured_confirmation_video(client_id, order.client.language)
        except Exception as exc:
            logger.exception("Failed to send client notification to %s: %s", client_id, exc)

    async def notify_dispatcher_completion_review(self, order: Order, master_name: str) -> None:
        if self.settings.resolved_dispatcher_chat_id is None:
            return

        text = (
            f"👨‍🔧 {master_name} ishni tugatdi.\n"
            f"Buyurtma: #{order.id}\n"
            f"Summa: {order.final_amount} so'm"
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💰 Tasdiqlash",
                        callback_data=f"dispatch_complete:{order.id}",
                    )
                ]
            ]
        )

        try:
            if order.video_file_id:
                try:
                    await self.bot.send_video_note(
                        chat_id=self.settings.resolved_dispatcher_chat_id,
                        video_note=order.video_file_id,
                    )
                except Exception:
                    await self.bot.send_video(
                        chat_id=self.settings.resolved_dispatcher_chat_id,
                        video=order.video_file_id,
                    )
            await self.bot.send_message(
                chat_id=self.settings.resolved_dispatcher_chat_id,
                text=text,
                reply_markup=keyboard,
            )
        except Exception as exc:
            logger.exception("Failed to send dispatcher completion review: %s", exc)
