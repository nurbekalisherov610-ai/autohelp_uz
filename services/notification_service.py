"""
AutoHelp.uz - Notification Service
Handles sending notifications to clients, dispatchers, and masters.
"""
import asyncio
import time
from html import escape

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
    dispatcher_order_actions, reassign_order_keyboard,
    dispatcher_confirm_completion,
)
from bot.keyboards.master_kb import master_order_response, master_status_update_keyboard
from core.config import settings
from core.redis import get_redis


class NotificationService:
    """Handles all notification logic for the bot."""
    _sla_alert_local_cache: dict[str, float] = {}
    _sla_alert_local_counts: dict[str, int] = {}

    def __init__(self, bot: Bot, session: AsyncSession):
        self.bot = bot
        self.session = session

    async def _should_send_sla_alert(
        self,
        order_uid: str,
        alert_key: str,
    ) -> bool:
        """
        Throttle repeated SLA alerts for the same order and alert type.
        Redis is primary storage; in-memory fallback is used if Redis fails.
        """
        cooldown_seconds = max(60, settings.sla_alert_cooldown_minutes * 60)
        max_alerts = max(1, int(settings.sla_alert_max_per_order_stage))
        cache_key = f"sla_alert:{alert_key}:{order_uid}"
        count_key = f"{cache_key}:count"

        if settings.use_redis:
            try:
                redis = await get_redis()
                count_raw = await redis.get(count_key)
                sent_count = int(count_raw) if count_raw else 0
                if sent_count >= max_alerts:
                    return False

                was_set = await redis.set(
                    cache_key,
                    "1",
                    ex=cooldown_seconds,
                    nx=True,
                )
                return bool(was_set)
            except Exception as e:
                logger.warning(
                    f"SLA alert redis throttle failed, using memory fallback for {order_uid}: {e}"
                )

        now = time.monotonic()
        sent_count = int(self._sla_alert_local_counts.get(count_key, 0))
        if sent_count >= max_alerts:
            return False
        expires_at = self._sla_alert_local_cache.get(cache_key, 0.0)
        if expires_at > now:
            return False

        self._sla_alert_local_cache[cache_key] = now + cooldown_seconds

        # Keep memory fallback map bounded.
        if len(self._sla_alert_local_cache) > 2000:
            stale_keys = [
                key
                for key, value in self._sla_alert_local_cache.items()
                if value <= now
            ]
            for key in stale_keys:
                self._sla_alert_local_cache.pop(key, None)

        return True

    async def _mark_sla_alert_sent(
        self,
        order_uid: str,
        alert_key: str,
    ) -> None:
        """Persist SLA alert delivery count for hard cap enforcement."""
        cooldown_seconds = max(60, settings.sla_alert_cooldown_minutes * 60)
        cache_key = f"sla_alert:{alert_key}:{order_uid}"
        count_key = f"{cache_key}:count"

        if settings.use_redis:
            try:
                redis = await get_redis()
                new_count = await redis.incr(count_key)
                # Keep count for a long enough period to avoid re-spam during the same stuck stage.
                if int(new_count) == 1:
                    await redis.expire(count_key, max(cooldown_seconds * 10, 86400))
            except Exception as e:
                logger.warning(
                    f"SLA alert redis count update failed, using memory fallback for {order_uid}: {e}"
                )

        current = int(self._sla_alert_local_counts.get(count_key, 0))
        self._sla_alert_local_counts[count_key] = current + 1

        if len(self._sla_alert_local_counts) > 2000:
            # Keep only currently known keys from cooldown cache when map grows too much.
            active_prefixes = set(self._sla_alert_local_cache.keys())
            stale_count_keys = [
                key for key in self._sla_alert_local_counts.keys()
                if key.removesuffix(":count") not in active_prefixes
            ]
            for key in stale_count_keys[:500]:
                self._sla_alert_local_counts.pop(key, None)

    async def _send_order_notification_packet(
        self,
        chat_id: int,
        text: str,
        order: Order,
        reply_markup=None,
    ) -> bool:
        """Send order notification + location packet to one chat destination."""
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            await self.bot.send_location(
                chat_id=chat_id,
                latitude=order.latitude,
                longitude=order.longitude,
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to notify dispatcher destination {chat_id} for order {order.order_uid}: {e}"
            )
            return False

    async def _send_html_message(
        self,
        chat_id: int,
        text: str,
        reply_markup=None,
        disable_web_page_preview: bool = False,
    ) -> bool:
        """Send one HTML-formatted message safely."""
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to send HTML message to destination {chat_id}: {e}"
            )
            return False

    async def _get_dispatcher_user_ids(self) -> list[int]:
        """Resolve active dispatcher Telegram user IDs."""
        result = await self.session.scalars(
            select(Staff.telegram_id).where(
                Staff.role == StaffRole.DISPATCHER,
                Staff.is_active == True,
            )
        )
        return list(dict.fromkeys(int(x) for x in result.all()))

    @staticmethod
    def _admin_mirror_ids(dispatcher_ids: list[int]) -> list[int]:
        """Admins can receive mirrored operational notifications."""
        return [
            int(admin_id)
            for admin_id in settings.admin_ids
            if int(admin_id) not in dispatcher_ids
        ]

    async def _get_dispatcher_action_chat_ids(self) -> list[int]:
        """
        Destinations for interactive dispatch actions (buttons).
        Modes:
        - bot_only: dispatchers + admin mirrors (private chats)
        - hybrid: dispatchers + admin mirrors (private chats)
        - group_only: group chat only
        """
        dispatcher_ids = await self._get_dispatcher_user_ids()
        admin_mirror_ids = self._admin_mirror_ids(dispatcher_ids)

        if settings.dispatch_mode == "group_only":
            if settings.dispatcher_group_id:
                return [settings.dispatcher_group_id]
            # Safe fallback if group is not configured.
            return list(dict.fromkeys(dispatcher_ids + admin_mirror_ids))

        # bot_only and hybrid keep action buttons in direct chats.
        action_ids = list(dict.fromkeys(dispatcher_ids + admin_mirror_ids))

        # Safety fallback: only hybrid may fall back to group for actions.
        if (
            settings.dispatch_mode == "hybrid"
            and not action_ids
            and settings.dispatcher_group_id
        ):
            return [settings.dispatcher_group_id]
        return action_ids

    async def _get_dispatcher_mirror_chat_ids(self) -> list[int]:
        """
        Optional non-interactive mirror destinations.
        - hybrid: mirror to group if configured
        - bot_only: keep group as archive/backup mirror if configured
        - group_only: no extra mirror (group is action destination already)
        """
        if (
            settings.dispatch_mode in {"hybrid", "bot_only"}
            and settings.dispatcher_group_id
        ):
            return [settings.dispatcher_group_id]
        return []

    async def notify_dispatchers_new_order(
        self, order: Order, user: User
    ) -> None:
        """Notify all dispatchers about a new order."""
        lang = "uz"  # Dispatchers use UZ by default
        problem_label = escape(PROBLEM_LABELS[order.problem_type][lang])
        client_name = escape(user.full_name or "—")
        client_phone = escape(user.phone or "—")
        description = (
            escape(order.description)
            if order.description
            else t("no_description", lang)
        )
        maps_url = escape(order.google_maps_url)

        text = t(
            "new_order_notification",
            lang=lang,
            order_uid=order.order_uid,
            client_name=client_name,
            client_phone=client_phone,
            problem=problem_label,
            description=description,
            maps_url=maps_url,
            time=order.created_at.strftime("%H:%M %d.%m.%Y"),
        )

        try:
            action_chat_ids = await self._get_dispatcher_action_chat_ids()
            mirror_chat_ids = await self._get_dispatcher_mirror_chat_ids()
        except Exception as e:
            logger.error(f"Failed to resolve dispatcher destinations: {e}")
            return

        if not action_chat_ids and not mirror_chat_ids:
            logger.warning(
                f"No dispatcher destination configured; order {order.order_uid} was not broadcast."
            )
            return

        action_tasks = [
            self._send_order_notification_packet(
                chat_id=chat_id,
                text=text,
                order=order,
                reply_markup=dispatcher_order_actions(order.order_uid),
            )
            for chat_id in action_chat_ids
        ]
        mirror_tasks = [
            self._send_order_notification_packet(
                chat_id=chat_id,
                text=text,
                order=order,
                reply_markup=None,
            )
            for chat_id in mirror_chat_ids
        ]
        results = await asyncio.gather(*action_tasks, *mirror_tasks, return_exceptions=False)
        sent = sum(1 for x in results if x)

        logger.info(
            f"Dispatch notification sent to {sent} destination(s) for order {order.order_uid} "
            f"(mode={settings.dispatch_mode})"
        )

    async def notify_master_new_assignment(
        self, order: Order, master: Master, user: User
    ) -> None:
        """Notify a master about a new assignment."""
        lang = "uz"
        problem_label = escape(PROBLEM_LABELS[order.problem_type][lang])
        description = escape(order.description) if order.description else "—"
        maps_url = escape(order.google_maps_url)
        client_phone = escape(user.phone or "—")

        text = t(
            "master_new_order",
            lang=lang,
            order_uid=order.order_uid,
            problem=problem_label,
            description=description,
            maps_url=maps_url,
            client_phone=client_phone,
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
        self, order: Order, video_file_id: str, video_kind: str = "video_note"
    ) -> None:
        """Forward dispatcher's confirmation video to the client."""
        if not order.user:
            return
        try:
            if video_kind == "video":
                await self.bot.send_video(
                    chat_id=order.user.telegram_id,
                    video=video_file_id,
                    caption="🎥",
                )
            else:
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
        self,
        order: Order,
        master: Master,
        video_file_id: str,
        amount: float,
        video_kind: str = "video_note",
    ) -> None:
        """Post master's completion video to the verification channel."""
        if not settings.video_channel_id:
            return
        safe_master_name = escape(master.full_name or "—")

        caption = (
            f"✅ Buyurtma: #{order.order_uid}\n"
            f"👨‍🔧 Usta: {safe_master_name}\n"
            f"💰 Summa: {amount:,.0f} so'm\n"
            f"🕐 {order.completed_at.strftime('%H:%M %d.%m.%Y') if order.completed_at else '—'}"
        )

        try:
            if video_kind == "video":
                await self.bot.send_video(
                    chat_id=settings.video_channel_id,
                    video=video_file_id,
                )
            else:
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
        safe_master_name = escape(master.full_name or "—")
        text = (
            f"❌ <b>Usta buyurtmani rad etdi!</b>\n\n"
            f"📋 Buyurtma: #{order.order_uid}\n"
            f"👨‍🔧 Usta: {safe_master_name}\n\n"
            f"Boshqa usta tayinlang 👇"
        )
        try:
            action_chat_ids = await self._get_dispatcher_action_chat_ids()
            mirror_chat_ids = await self._get_dispatcher_mirror_chat_ids()
        except Exception as e:
            logger.error(f"Failed to resolve dispatcher destinations: {e}")
            return

        if not action_chat_ids and not mirror_chat_ids:
            logger.warning(
                f"No dispatcher destination configured for rejection alert on order {order.order_uid}."
            )
            return

        action_tasks = [
            self._send_html_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reassign_order_keyboard(order.order_uid),
            )
            for chat_id in action_chat_ids
        ]
        mirror_tasks = [
            self._send_html_message(chat_id=chat_id, text=text)
            for chat_id in mirror_chat_ids
        ]
        results = await asyncio.gather(*action_tasks, *mirror_tasks, return_exceptions=False)
        sent = sum(1 for x in results if x)
        logger.info(
            f"Rejection alert sent to {sent} destination(s) for order {order.order_uid}."
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
            action_chat_ids = await self._get_dispatcher_action_chat_ids()
            mirror_chat_ids = await self._get_dispatcher_mirror_chat_ids()
        except Exception as e:
            logger.error(f"Failed to resolve dispatcher destinations: {e}")
            return

        if not action_chat_ids and not mirror_chat_ids:
            logger.warning(
                f"No dispatcher destination configured for awaiting-confirm alert on order {order.order_uid}."
            )
            return

        action_tasks = [
            self._send_html_message(
                chat_id=chat_id,
                text=text,
                reply_markup=dispatcher_confirm_completion(order.order_uid),
            )
            for chat_id in action_chat_ids
        ]
        mirror_tasks = [
            self._send_html_message(chat_id=chat_id, text=text)
            for chat_id in mirror_chat_ids
        ]
        results = await asyncio.gather(*action_tasks, *mirror_tasks, return_exceptions=False)
        sent = sum(1 for x in results if x)
        logger.info(
            f"Awaiting-confirm alert sent to {sent} destination(s) for order {order.order_uid}."
        )

    async def send_sla_alert(self, order: Order, alert_key: str) -> bool:
        """Send SLA violation alert to dispatchers."""
        try:
            action_chat_ids = await self._get_dispatcher_action_chat_ids()
            mirror_chat_ids = await self._get_dispatcher_mirror_chat_ids()
        except Exception as e:
            logger.error(f"Failed to resolve dispatcher destinations: {e}")
            return False

        destination_ids = list(dict.fromkeys(action_chat_ids + mirror_chat_ids))
        if not destination_ids:
            logger.warning(
                f"No dispatcher destination configured for SLA alert on order {order.order_uid}."
            )
            return False

        should_send = await self._should_send_sla_alert(
            order_uid=order.order_uid,
            alert_key=alert_key,
        )
        if not should_send:
            logger.debug(
                f"SLA alert suppressed by cooldown for {order.order_uid} ({alert_key})."
            )
            return False

        text = t(alert_key, lang="uz", order_uid=order.order_uid)
        tasks = [
            self._send_html_message(chat_id=chat_id, text=text)
            for chat_id in destination_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        sent = sum(1 for x in results if x)
        if sent > 0:
            await self._mark_sla_alert_sent(order_uid=order.order_uid, alert_key=alert_key)
        logger.info(
            f"SLA alert sent to {sent} destination(s) for order {order.order_uid}."
        )
        return sent > 0

    async def notify_dispatcher_review_feedback(
        self,
        order: Order,
        rating: int,
        issue: str | None = None,
        comment: str | None = None,
    ) -> None:
        """
        Notify dispatcher/admin destinations about client feedback.
        Includes optional issue and optional comment.
        """
        user_name = escape(order.user.full_name) if order.user else "Unknown"
        master_name = escape(order.master.full_name) if order.master else "Unknown"
        stars = "⭐" * max(1, min(int(rating), 5))
        issue_line = f"\n⚠️ Muammo: {escape(issue)}" if issue else ""
        comment_line = f"\n💬 Izoh: {escape(comment)}" if comment else ""

        text = (
            f"📝 <b>Yangi mijoz fikri</b>\n\n"
            f"📋 Buyurtma: <code>{order.order_uid}</code>\n"
            f"👤 Mijoz: {user_name}\n"
            f"👨‍🔧 Usta: {master_name}\n"
            f"⭐ Baho: <b>{stars}</b> ({rating}/5)"
            f"{issue_line}"
            f"{comment_line}"
        )

        try:
            action_chat_ids = await self._get_dispatcher_action_chat_ids()
            mirror_chat_ids = await self._get_dispatcher_mirror_chat_ids()
        except Exception as e:
            logger.error(f"Failed to resolve dispatcher destinations: {e}")
            return

        destination_ids = action_chat_ids + mirror_chat_ids
        if not destination_ids:
            logger.warning(
                f"No dispatcher destination configured for review feedback on order {order.order_uid}."
            )
            return

        tasks = [
            self._send_html_message(chat_id=chat_id, text=text)
            for chat_id in destination_ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        sent = sum(1 for x in results if x)
        logger.info(
            f"Review feedback sent to {sent} destination(s) for order {order.order_uid}."
        )
