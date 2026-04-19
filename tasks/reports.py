"""
AutoHelp.uz - Report Generation Tasks
Automated daily and weekly reports sent to admin.
"""
from datetime import datetime, timedelta

from loguru import logger

from core.database import async_session
from core.config import settings
from repositories.stats_repo import StatsRepo
from repositories.order_repo import OrderRepo
from models.order import OrderStatus


async def send_daily_report(bot):
    """
    Send daily statistics report to admin.
    Runs daily at 23:55 via APScheduler.
    """
    async with async_session() as session:
        stats_repo = StatsRepo(session)
        order_repo = OrderRepo(session)

        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        total = await order_repo.count_by_status(since=today_start)
        completed = await order_repo.count_by_status(
            status=OrderStatus.COMPLETED, since=today_start
        )
        cancelled = await order_repo.count_by_status(
            status=OrderStatus.CANCELLED, since=today_start
        )
        revenue = await order_repo.sum_payments(since=today_start)
        avg_rating = await order_repo.avg_rating(since=today_start)

        leaderboard = await stats_repo.get_master_leaderboard(limit=5)
        lb_text = "\n".join(
            f"   {i+1}. {m['name']} — ⭐{m['rating']:.1f} ({m['completed']} ish)"
            for i, m in enumerate(leaderboard)
        ) or "   Ma'lumot yo'q"

        text = (
            f"📊 <b>Kunlik hisobot — {now.strftime('%d.%m.%Y')}</b>\n\n"
            f"📋 Jami buyurtmalar: {total}\n"
            f"✅ Tugallangan: {completed}\n"
            f"❌ Bekor qilingan: {cancelled}\n"
            f"💰 Umumiy summa: {revenue:,.0f} so'm\n"
            f"⭐ O'rtacha reyting: {avg_rating:.1f}\n"
            f"📈 Konversiya: {(completed/total*100) if total else 0:.1f}%\n\n"
            f"🏆 <b>Bugungi top ustalar:</b>\n{lb_text}"
        )

        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed to send daily report to admin {admin_id}: {e}")

        logger.info("Daily report sent to admins")


async def send_weekly_report(bot):
    """
    Send weekly report every Monday morning.
    Runs weekly (Monday 08:00) via APScheduler.
    """
    async with async_session() as session:
        stats_repo = StatsRepo(session)
        order_repo = OrderRepo(session)

        now = datetime.utcnow()
        week_start = now - timedelta(days=7)

        total = await order_repo.count_by_status(since=week_start)
        completed = await order_repo.count_by_status(
            status=OrderStatus.COMPLETED, since=week_start
        )
        cancelled = await order_repo.count_by_status(
            status=OrderStatus.CANCELLED, since=week_start
        )
        revenue = await order_repo.sum_payments(since=week_start)
        avg_rating = await order_repo.avg_rating(since=week_start)

        district_stats = await stats_repo.get_district_stats()
        district_text = "\n".join(
            f"   📍 {d['district']}: {d['total_orders']} buyurtma, "
            f"{d['total_sum']:,.0f} so'm"
            for d in district_stats[:5]
        ) or "   Ma'lumot yo'q"

        leaderboard = await stats_repo.get_master_leaderboard(limit=10)
        lb_text = "\n".join(
            f"   {i+1}. {m['name']} — ⭐{m['rating']:.1f} ({m['completed']} ish)"
            for i, m in enumerate(leaderboard)
        ) or "   Ma'lumot yo'q"

        text = (
            f"📊 <b>Haftalik hisobot</b>\n"
            f"📅 {week_start.strftime('%d.%m')} — {now.strftime('%d.%m.%Y')}\n\n"
            f"📋 Jami buyurtmalar: {total}\n"
            f"✅ Tugallangan: {completed}\n"
            f"❌ Bekor qilingan: {cancelled}\n"
            f"💰 Umumiy summa: {revenue:,.0f} so'm\n"
            f"⭐ O'rtacha reyting: {avg_rating:.1f}\n"
            f"📈 Konversiya: {(completed/total*100) if total else 0:.1f}%\n\n"
            f"🗺 <b>Tumanlar bo'yicha:</b>\n{district_text}\n\n"
            f"🏆 <b>Top 10 ustalar:</b>\n{lb_text}"
        )

        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed to send weekly report to admin {admin_id}: {e}")

        logger.info("Weekly report sent to admins")
