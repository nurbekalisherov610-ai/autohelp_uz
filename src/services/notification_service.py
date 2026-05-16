import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.core.config import Settings
from src.db.enums import OrderStatus
from src.db.models.order import Order

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, bot: Bot, settings: Settings):
        self.bot = bot
        self.settings = settings

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

    async def notify_master_new_assignment(self, order: Order, master_telegram_id: int) -> None:
        text = (
            f"Sizga yangi buyurtma biriktirildi!\n\n"
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

        if status == OrderStatus.ASSIGNED:
            text = f"Sizning #{order.id} raqamli buyurtmangizga usta biriktirildi. Usta hozir yo'lga chiqadi."
        elif status == OrderStatus.ACCEPTED:
            text = f"Usta sizning #{order.id} raqamli buyurtmangizni qabul qildi."
        elif status == OrderStatus.ON_THE_WAY:
            text = f"Sizning #{order.id} raqamli buyurtmangiz bo'yicha usta yo'lga chiqdi. Kuting."
        elif status == OrderStatus.ARRIVED:
            text = f"Usta manzilingizga yetib keldi. Buyurtma: #{order.id}"
        elif status == OrderStatus.IN_PROGRESS:
            text = f"Usta ta'mirlashni boshladi. Buyurtma: #{order.id}"
        elif status == OrderStatus.CANCELLED:
            text = f"Sizning #{order.id} raqamli buyurtmangiz bekor qilindi. Biz bilan bog'laning."
        keyboard = None
        if status == OrderStatus.COMPLETED:
            text = f"Buyurtmangiz (#{order.id}) muvaffaqiyatli yakunlandi. Xizmatimizdan mamnunmisiz? Iltimos, baho bering:"
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
                    ]
                ]
            )

        if not text:
            return

        try:
            await self.bot.send_message(chat_id=client_id, text=text, reply_markup=keyboard)
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
                        callback_data=f"dispatch_complete:{order.id}"
                    )
                ]
            ]
        )
        
        try:
            if order.video_file_id:
                try:
                    await self.bot.send_video_note(
                        chat_id=self.settings.resolved_dispatcher_chat_id, 
                        video_note=order.video_file_id
                    )
                except Exception:
                    await self.bot.send_video(
                        chat_id=self.settings.resolved_dispatcher_chat_id,
                        video=order.video_file_id
                    )
            await self.bot.send_message(chat_id=self.settings.resolved_dispatcher_chat_id, text=text, reply_markup=keyboard)
        except Exception as exc:
            logger.exception("Failed to send dispatcher completion review: %s", exc)
