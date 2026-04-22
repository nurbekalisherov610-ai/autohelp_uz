"""
AutoHelp.uz - Dispatcher Auto Video Task
Automatically sends a predefined dispatcher confirmation video to the client
shortly after a new order is created.
"""
from datetime import datetime, timedelta

from loguru import logger

from core.config import settings
from core.database import async_session
from repositories.order_repo import OrderRepo


def _resolve_auto_video_file_id(lang: str) -> str:
    """Pick configured auto-confirmation video by client language."""
    if lang == "ru":
        return (
            settings.dispatcher_confirm_video_ru
            or settings.dispatcher_confirm_video_uz
        )
    return (
        settings.dispatcher_confirm_video_uz
        or settings.dispatcher_confirm_video_ru
    )


async def _send_auto_video(bot, chat_id: int, file_id: str) -> bool:
    """Send configured media with fallback between video_note and video."""
    preferred_kind = settings.dispatcher_confirm_video_kind
    try:
        if preferred_kind == "video":
            await bot.send_video(chat_id=chat_id, video=file_id)
        else:
            await bot.send_video_note(chat_id=chat_id, video_note=file_id)
        return True
    except Exception as first_error:
        fallback_kind = "video_note" if preferred_kind == "video" else "video"
        try:
            if fallback_kind == "video":
                await bot.send_video(chat_id=chat_id, video=file_id)
            else:
                await bot.send_video_note(chat_id=chat_id, video_note=file_id)
            return True
        except Exception as fallback_error:
            logger.error(
                "Auto dispatcher video send failed "
                f"(preferred={preferred_kind}, fallback={fallback_kind}): "
                f"{first_error}; {fallback_error}"
            )
            return False


async def send_auto_dispatcher_confirmation_videos(bot) -> None:
    """
    Send configured auto-confirmation videos to eligible orders:
    - created at least N seconds ago
    - not terminal
    - no previous dispatcher video marker
    """
    if not settings.dispatcher_confirm_video_uz and not settings.dispatcher_confirm_video_ru:
        return

    delay_seconds = max(5, int(settings.dispatcher_auto_video_delay_seconds or 25))
    ready_before = datetime.utcnow() - timedelta(seconds=delay_seconds)

    try:
        async with async_session() as session:
            order_repo = OrderRepo(session)
            orders = await order_repo.get_pending_auto_dispatcher_videos(
                ready_before=ready_before,
                limit=100,
            )
            if not orders:
                return

            sent_count = 0
            for order in orders:
                if not order.user:
                    continue
                lang = getattr(order.user.language, "value", "uz")
                file_id = _resolve_auto_video_file_id(lang)
                if not file_id:
                    continue

                sent = await _send_auto_video(
                    bot=bot,
                    chat_id=order.user.telegram_id,
                    file_id=file_id,
                )
                if not sent:
                    continue

                await order_repo.set_dispatcher_video(order.order_uid, file_id)
                sent_count += 1

            await session.commit()
            if sent_count:
                logger.info(
                    f"Auto dispatcher confirmation video sent for {sent_count} order(s)."
                )
    except Exception as e:
        logger.error(f"Auto dispatcher video task error: {e}")

