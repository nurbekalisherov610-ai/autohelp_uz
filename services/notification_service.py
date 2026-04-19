"""
AutoHelp.uz - Notification Service
Handles sending notifications to clients, dispatchers, and masters.
"""
from aiogram import Bot
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order import Order, PROBLEM_LABELS
from models.master import Master
from models.staff import Staff, StaffRole
from models.user import User
from locales.texts import t
from bot.keyboards.dispatcher_kb import (
    dispatcher_order_actions, master_selection_keyboard, reassign_order_keyboard,
    dispatcher_confirm_completion,
)
from bot.keyboards.master_kb import master_order_response, master_status_update_keyboard
from core.config import settings


class NotificationService:
    """Handles all notification logic for the bot."""

    def __init__(self, bot: Bot, session: AsyncSession):
        self.bot = bot
        self.session = session

    async def _get_dispatcher_chat_ids(self) -> list[int]:
        """
        Resolve dispatcher notification destinations.
        - Multi-dispatcher mode: use group chat (if configured).
        - Single-dispatcher mode: send direct to dispatcher + admin mirror.
        - If no group configured: direct dispatcher chats.
        """
        result = await self.session.scalars(
            select(Staff.telegram_id).where(
                Staff.role == StaffRole.DISPATCHER,
                Staff.is_active == True,
            )
        )
        dispatcher_ids = [int(x) for x in result.all()]
        dispatcher_ids = list(dict.fromkeys(dispatcher_ids))

        # If no group configured, direct mode only.
        if not settings.dispatcher_group_id:
            return dispatcher_ids

        # One dispatcher: direct handling is faster/reliable, plus admin mirror.
        if len(dispatcher_ids) <= 1:
            admin_mirror_ids = [
                int(admin_id)
                for admin_id in settings.admin_ids
                if int(admin_id) not in dispatcher_ids
            ]
            merged = dispatcher_ids + admin_mirror_ids + [settings.dispatcher_group_id]
            return list(dict.fromkeys(merged))

        # Multiple dispatchers: group mode to avoid duplicate button actions.
        return [settings.dispatcher_group_id]

    async def notify_dispatchers_new_order(
        self, order: Order, user: User
    ) -> None:
        """Notify all dispatchers about a new order."""
        lang = "uz"  # Dispatchers use UZ by default
        problem_label = PROBLEM_LABELS[order.problem_type][lang]

        text = t(
            "new_order_notification",
            lang=lang,
            order_uid=order.order_uid,
            client_name=user.full_name,
            client_phone=user.phone,
            problem=problem_label,
            description=order.description or t("no_description", lang),
            maps_url=order.google_maps_url,
            time=order.created_at.strftime("%H:%M %d.%m.%Y"),
        )

        try:
            chat_ids = await self._get_dispatcher_chat_ids()
        except Exception as e:
            logger.error(f"Failed to resolve dispatcher destinations: {e}")
            return

        if not chat_ids:
            logger.warning(
                f"No dispatcher destination configured; order {order.order_uid} was not broadcast."
            )
            return

        sent = 0
        for chat_id in chat_ids:
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=dispatcher_order_actions(order.order_uid),
                    disable_web_page_preview=True,
                )

                # Also send location
                await self.bot.send_location(
                    chat_id=chat_id,
                    latitude=order.latitude,
                    longitude=order.longitude,
                )
                sent += 1
            except Exception as e:
                logger.error(
                    f"Failed to notify dispatcher destination {chat_id} for order {order.order_uid}: {e}"
                )

        logger.info(
            f"Dispatch notification sent to {sent} destination(s) for order {order.order_uid}"
        )

    async def notify_master_new_assignment(
        self, order: Order, master: Master, user: User
    ) -> None:
        """Notify a master about a new assignment."""
        lang = "uz"
        problem_label = PROBLEM_LABELS[order.problem_type][lang]

        text = t(
            "master_new_order",
            lang=lang,
            order_uid=order.order_uid,
            problem=problem_label,
            description=order.description or "—",
            maps_url=order.google_maps_url,
            client_phone=user.phone,
        )

        try:
            await self.bot.send_message(
                chat_id=master.telegram_id,
                text=text,
                parse_mode="HTML",
                reply_markup=master_order_response(order.order_uid),
                disable_web_page_preview=True,
            )
            # Send location separately
            await self.bot.send_location(
                chat_id=master.telegram_id,
                latitude=order.latitude,
                longitude=order.longitude,
            )
            logger.info(f"Master {master.full_name} notified about order {order.order_uid}")
        except Exception as e:
            logger.error(f"Failed to notify master {master.telegram_id}: {e}")

    async def notify_client_status_update(
        self, order: Order, status_key: str, **kwargs
    ) -> None:
        """Notify client about an order status update."""
        if not order.user:
            return

        lang = order.user.language.value
        text = t(status_key, lang=lang, **kwargs)

        try:
            await self.bot.send_message(
                chat_id=order.user.telegram_id,
                text=text,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Failed to notify client {order.user.telegram_id}: {e}")

    async def send_dispatcher_video_to_client(
        self, order: Order, video_file_id: str
    ) -> None:
        """Forward dispatcher's confirmation video to the client."""
        if not order.user:
            return
        try:
            await self.bot.send_video_note(
                chat_id=order.user.telegram_id,
                video_note=video_file_id,
            )
            lang = order.user.language.value
            await self.bot.send_message(
                chat_id=order.user.telegram_id,
                text="👆 " + (
                    "Dispetcherimizdan tasdiqlash xabari"
                    if lang == "uz"
                    else "Подтверждение от нашего диспетчера"
                ),
            )
        except Exception as e:
            logger.error(f"Failed to send video to client: {e}")

    async def send_master_video_to_channel(
        self, order: Order, master: Master, video_file_id: str, amount: float
    ) -> None:
        """Post master's completion video to the verification channel."""
        if not settings.video_channel_id:
            return

        caption = (
            f"✅ Buyurtma: #{order.order_uid}\n"
            f"👨‍🔧 Usta: {master.full_name}\n"
            f"💰 Summa: {amount:,.0f} so'm\n"
            f"🕐 {order.completed_at.strftime('%H:%M %d.%m.%Y') if order.completed_at else '—'}"
        )

        try:
            await self.bot.send_video_note(
                chat_id=settings.video_channel_id,
                video_note=video_file_id,
            )
            await self.bot.send_message(
                chat_id=settings.video_channel_id,
                text=caption,
            )
            logger.info(f"Completion video posted to channel for order {order.order_uid}")
        except Exception as e:
            logger.error(f"Failed to post video to channel: {e}")

    async def notify_dispatcher_order_rejected(
        self, order: Order, master: Master
    ) -> None:
        """Notify dispatchers that a master rejected an order."""
        text = (
            f"❌ <b>Usta buyurtmani rad etdi!</b>\n\n"
            f"📋 Buyurtma: #{order.order_uid}\n"
            f"👨‍🔧 Usta: {master.full_name}\n\n"
            f"Boshqa usta tayinlang 👇"
        )
        try:
            chat_ids = await self._get_dispatcher_chat_ids()
        except Exception as e:
            logger.error(f"Failed to resolve dispatcher destinations: {e}")
            return

        for chat_id in chat_ids:
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reassign_order_keyboard(order.order_uid),
                )
            except Exception as e:
                logger.error(
                    f"Failed to notify dispatcher destination {chat_id} about rejection: {e}"
                )

    async def notify_dispatcher_awaiting_confirm(
        self, order: Order, amount: float
    ) -> None:
        """Notify dispatchers that an order is awaiting confirmation."""
        text = (
            f"⏳ <b>Tasdiqlash kutilmoqda</b>\n\n"
            f"📋 Buyurtma: #{order.order_uid}\n"
            f"💰 Summa: {amount:,.0f} so'm\n\n"
            f"Tasdiqlang yoki summani o'zgartiring 👇"
        )
        try:
            chat_ids = await self._get_dispatcher_chat_ids()
        except Exception as e:
            logger.error(f"Failed to resolve dispatcher destinations: {e}")
            return

        for chat_id in chat_ids:
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=dispatcher_confirm_completion(order.order_uid),
                )
            except Exception as e:
                logger.error(
                    f"Failed to notify dispatcher destination {chat_id} about completion: {e}"
                )

    async def send_sla_alert(self, order: Order, alert_key: str) -> None:
        """Send SLA violation alert to dispatchers."""
        text = t(alert_key, lang="uz", order_uid=order.order_uid)
        try:
            chat_ids = await self._get_dispatcher_chat_ids()
        except Exception as e:
            logger.error(f"Failed to resolve dispatcher destinations: {e}")
            return

        for chat_id in chat_ids:
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(
                    f"Failed to send SLA alert to dispatcher destination {chat_id}: {e}"
                )
