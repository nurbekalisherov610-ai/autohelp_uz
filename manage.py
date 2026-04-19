"""
AutoHelp.uz - Management CLI
Quick commands for managing the bot from the command line.
Usage:
    python manage.py add_master <telegram_id> <name> <phone>
    python manage.py add_dispatcher <telegram_id> <name> <phone>
    python manage.py list_masters
    python manage.py list_staff
    python manage.py stats
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Import ALL models so tables are registered
import models  # noqa: F401

from core.database import async_session, init_db, close_db
from models.staff import Staff, StaffRole
from models.master import Master


async def add_master(telegram_id: int, name: str, phone: str):
    """Add a new master to the system."""
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select
        existing = await session.scalar(
            select(Master).where(Master.telegram_id == telegram_id)
        )
        if existing:
            print(f"⚠️  Master with Telegram ID {telegram_id} already exists.")
            return

        master = Master(
            telegram_id=telegram_id,
            full_name=name,
            phone=phone,
            is_active=True,
        )
        session.add(master)
        await session.commit()
        print(f"✅ Master added: {name} (ID: {telegram_id})")


async def add_dispatcher(telegram_id: int, name: str, phone: str):
    """Add a new dispatcher to the system."""
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select
        existing = await session.scalar(
            select(Staff).where(Staff.telegram_id == telegram_id)
        )
        if existing:
            print(f"⚠️  Staff with Telegram ID {telegram_id} already exists.")
            return

        staff = Staff(
            telegram_id=telegram_id,
            full_name=name,
            phone=phone,
            role=StaffRole.DISPATCHER,
            is_active=True,
        )
        session.add(staff)
        await session.commit()
        print(f"✅ Dispatcher added: {name} (ID: {telegram_id})")


async def list_masters():
    """List all masters."""
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.scalars(select(Master).order_by(Master.id))
        masters = list(result.all())

        if not masters:
            print("No masters found.")
            return

        print(f"\n{'ID':<5} {'Telegram':<15} {'Name':<25} {'Phone':<15} {'Status':<10} {'Rating':<8}")
        print("─" * 80)
        for m in masters:
            print(
                f"{m.id:<5} {m.telegram_id:<15} {m.full_name:<25} "
                f"{m.phone:<15} {m.status.value:<10} {m.rating:<8.1f}"
            )


async def list_staff():
    """List all staff members."""
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.scalars(select(Staff).order_by(Staff.id))
        staff_list = list(result.all())

        if not staff_list:
            print("No staff found.")
            return

        print(f"\n{'ID':<5} {'Telegram':<15} {'Name':<25} {'Role':<15} {'Active':<8}")
        print("─" * 70)
        for s in staff_list:
            print(
                f"{s.id:<5} {s.telegram_id:<15} {s.full_name:<25} "
                f"{s.role.value:<15} {'✅' if s.is_active else '❌':<8}"
            )


async def show_stats():
    """Show quick statistics."""
    await init_db()
    async with async_session() as session:
        from repositories.stats_repo import StatsRepo
        stats_repo = StatsRepo(session)
        stats = await stats_repo.get_dashboard_stats()

        print(f"\n📊 AutoHelp.uz Statistics")
        print("─" * 40)
        for key, value in stats.items():
            label = key.replace("_", " ").title()
            print(f"  {label}: {value}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "add_master" and len(sys.argv) == 5:
        asyncio.run(add_master(int(sys.argv[2]), sys.argv[3], sys.argv[4]))
    elif cmd == "add_dispatcher" and len(sys.argv) == 5:
        asyncio.run(add_dispatcher(int(sys.argv[2]), sys.argv[3], sys.argv[4]))
    elif cmd == "list_masters":
        asyncio.run(list_masters())
    elif cmd == "list_staff":
        asyncio.run(list_staff())
    elif cmd == "stats":
        asyncio.run(show_stats())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
