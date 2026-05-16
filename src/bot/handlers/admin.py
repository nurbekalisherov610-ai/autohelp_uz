"""Admin command handler — accessible only by users listed in ADMIN_IDS or DISPATCHER_IDS."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select

from src.core.config import get_settings
from src.db.enums import OrderStatus
from src.db.models.order import Order
from src.db.models.user import User
from src.db.session import AsyncSessionFactory

router = Router(name="admin")
settings = get_settings()


def _get_admin_ids() -> set[int]:
    """Return the set of telegram IDs that are allowed to use /admin."""
    ids: set[int] = set()
    # ADMIN_IDS env var (comma-separated)
    if settings.admin_ids:
        for x in settings.admin_ids.split(","):
            x = x.strip()
            if x.lstrip("-").isdigit():
                ids.add(int(x))
    # DISPATCHER_IDS also get admin access
    if settings.dispatcher_ids:
        for x in settings.dispatcher_ids.split(","):
            x = x.strip()
            if x.lstrip("-").isdigit():
                ids.add(int(x))
    return ids


def _is_admin(user_id: int) -> bool:
    admins = _get_admin_ids()
    if not admins:
        return True  # dev mode: no restriction
    return user_id in admins


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("⛔ Sizda bu buyruqdan foydalanish huquqi yo'q.")
        return

    async with AsyncSessionFactory() as session:
        # Order stats
        total_orders = await session.scalar(select(func.count(Order.id))) or 0
        completed = await session.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.COMPLETED)
        ) or 0
        cancelled = await session.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.CANCELLED)
        ) or 0
        active = await session.scalar(
            select(func.count(Order.id)).where(
                Order.status.in_([
                    OrderStatus.NEW, OrderStatus.ASSIGNED, OrderStatus.ACCEPTED,
                    OrderStatus.ON_THE_WAY, OrderStatus.ARRIVED,
                    OrderStatus.IN_PROGRESS, OrderStatus.AWAITING_CONFIRM,
                ])
            )
        ) or 0
        revenue = await session.scalar(
            select(func.coalesce(func.sum(Order.final_amount), 0)).where(
                Order.status == OrderStatus.COMPLETED
            )
        ) or 0

        # User stats
        total_users = await session.scalar(select(func.count(User.id))) or 0
        total_masters = await session.scalar(
            select(func.count(User.id)).where(User.is_master == True)  # noqa: E712
        ) or 0

    text = (
        "👑 Admin Paneli\n\n"
        "📦 Buyurtmalar:\n"
        f"  Jami: {total_orders} ta\n"
        f"  ✅ Yakunlangan: {completed} ta\n"
        f"  🚫 Bekor qilingan: {cancelled} ta\n"
        f"  ⏳ Faol: {active} ta\n\n"
        f"💰 Umumiy daromad: {float(revenue):,.0f} so'm\n\n"
        "👥 Foydalanuvchilar:\n"
        f"  Jami mijozlar: {total_users} ta\n"
        f"  👨‍🔧 Masterlar: {total_masters} ta\n\n"
        "Buyruqlar:\n"
        "/dashboard — Dispetcher paneli\n"
        "/new_orders — Yangi buyurtmalar\n"
        "/active_orders — Faol buyurtmalar\n"
        "/order <id> — Buyurtma tafsilotlari\n"
        "/admin_users — Foydalanuvchilar ro'yxati\n"
        "/admin_masters — Masterlar ro'yxati"
    )
    await message.answer(text)


@router.message(Command("admin_users"))
async def cmd_admin_users(message: Message) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("⛔ Sizda bu buyruqdan foydalanish huquqi yo'q.")
        return

    async with AsyncSessionFactory() as session:
        users = (
            await session.scalars(
                select(User).order_by(User.created_at.desc()).limit(20)
            )
        ).all()

    if not users:
        await message.answer("Hozircha foydalanuvchilar yo'q.")
        return

    lines = ["👥 So'nggi 20 foydalanuvchi:\n"]
    for u in users:
        role = "👨‍🔧 Master" if u.is_master else "🚗 Haydovchi"
        lines.append(f"{role} | {u.full_name or 'Nomsiz'} | ID: {u.telegram_id} | {u.phone or '—'}")

    await message.answer("\n".join(lines))


@router.message(Command("admin_masters"))
async def cmd_admin_masters(message: Message) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("⛔ Sizda bu buyruqdan foydalanish huquqi yo'q.")
        return

    async with AsyncSessionFactory() as session:
        masters = (
            await session.scalars(
                select(User).where(User.is_master == True).order_by(User.created_at.desc())  # noqa: E712
            )
        ).all()

        # Count active jobs per master
        active_counts_result = await session.execute(
            select(Order.assigned_master_telegram_id, func.count(Order.id))
            .where(Order.status.in_([
                OrderStatus.ASSIGNED, OrderStatus.ACCEPTED, OrderStatus.ON_THE_WAY,
                OrderStatus.ARRIVED, OrderStatus.IN_PROGRESS, OrderStatus.AWAITING_CONFIRM,
            ]))
            .where(Order.assigned_master_telegram_id.isnot(None))
            .group_by(Order.assigned_master_telegram_id)
        )
        workload = dict(active_counts_result.all())

    if not masters:
        await message.answer(
            "Hozircha masterlar yo'q.\n\n"
            "Master qo'shish uchun master /register_master master123 buyrug'ini yuborsin."
        )
        return

    lines = [f"👨‍🔧 Masterlar ({len(masters)} ta):\n"]
    for m in masters:
        jobs = workload.get(m.telegram_id, 0)
        status = "🟢 Bo'sh" if jobs == 0 else f"🟡 {jobs} ta faol ish"
        lines.append(f"• {m.full_name or 'Nomsiz'} | ID: {m.telegram_id} | {status}")

    await message.answer("\n".join(lines))
