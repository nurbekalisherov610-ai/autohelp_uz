"""
AutoHelp.uz - Management CLI
Quick commands for managing the bot from command line.
Usage:
    python manage.py add_master <telegram_id> <name> <phone> [specializations_csv]
    python manage.py set_master_roles <telegram_id> <specializations_csv>
    python manage.py add_dispatcher <telegram_id> <name> <phone>
    python manage.py add_admin <telegram_id> <name> <phone>
    python manage.py list_masters
    python manage.py list_staff
    python manage.py stats

Specialization examples:
    universal
    battery,tire
    akb,electrical
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

from core.database import async_session, init_db
from models.staff import Staff, StaffRole
from models.master import Master
from models.master_specialization import (
    MasterSpecialization,
    MasterSpecializationType,
    parse_specializations_csv,
    specialization_short_text,
)
from repositories.master_repo import MasterRepo


async def add_master(
    telegram_id: int,
    name: str,
    phone: str,
    specializations_csv: str | None = None,
):
    """Add a new master to the system."""
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select

        existing = await session.scalar(
            select(Master).where(Master.telegram_id == telegram_id)
        )
        if existing:
            print(f"WARNING: Master with Telegram ID {telegram_id} already exists.")
            print("Use: python manage.py set_master_roles <telegram_id> <specializations_csv>")
            return

        master = Master(
            telegram_id=telegram_id,
            full_name=name,
            phone=phone,
            is_active=True,
        )
        session.add(master)
        await session.flush()

        specs = parse_specializations_csv(specializations_csv)
        repo = MasterRepo(session)
        await repo.set_specializations(master.id, specs)

        await session.commit()
        print(
            f"OK: Master added: {name} (ID: {telegram_id}) "
            f"roles=[{specialization_short_text(specs)}]"
        )


async def set_master_roles(telegram_id: int, specializations_csv: str):
    """Set/replace specialization roles for an existing master."""
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select

        master = await session.scalar(
            select(Master).where(Master.telegram_id == telegram_id)
        )
        if not master:
            print(f"ERROR: Master with Telegram ID {telegram_id} not found.")
            return

        specs = parse_specializations_csv(specializations_csv)
        repo = MasterRepo(session)
        await repo.set_specializations(master.id, specs)

        await session.commit()
        print(
            f"OK: Roles updated for {master.full_name} (ID: {telegram_id}) "
            f"roles=[{specialization_short_text(specs)}]"
        )


async def add_dispatcher(telegram_id: int, name: str, phone: str):
    """Add a new dispatcher to the system."""
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select
        existing = await session.scalar(
            select(Staff).where(Staff.telegram_id == telegram_id)
        )
        if existing:
            print(f"WARNING: Staff with Telegram ID {telegram_id} already exists.")
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
        print(f"OK: Dispatcher added: {name} (ID: {telegram_id})")


async def add_admin(telegram_id: int, name: str, phone: str):
    """Add a new admin to the system."""
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select
        existing = await session.scalar(
            select(Staff).where(Staff.telegram_id == telegram_id)
        )
        if existing:
            existing.role = StaffRole.ADMIN
            existing.is_active = True
            if name:
                existing.full_name = name
            if phone:
                existing.phone = phone
            await session.commit()
            print(f"OK: Existing staff promoted to ADMIN: {existing.full_name} (ID: {telegram_id})")
            return

        staff = Staff(
            telegram_id=telegram_id,
            full_name=name,
            phone=phone,
            role=StaffRole.ADMIN,
            is_active=True,
        )
        session.add(staff)
        await session.commit()
        print(f"OK: Admin added: {name} (ID: {telegram_id})")


async def list_masters():
    """List all masters with specialization roles."""
    await init_db()
    async with async_session() as session:
        from sqlalchemy import select

        result = await session.scalars(select(Master).order_by(Master.id))
        masters = list(result.all())

        if not masters:
            print("No masters found.")
            return

        spec_rows = await session.execute(
            select(
                MasterSpecialization.master_id,
                MasterSpecialization.specialization,
            ).order_by(MasterSpecialization.master_id)
        )

        spec_map: dict[int, list[MasterSpecializationType]] = {}
        for master_id, specialization in spec_rows.all():
            spec_map.setdefault(master_id, []).append(specialization)

        print(
            f"\n{'ID':<5} {'Telegram':<15} {'Name':<25} {'Phone':<15} "
            f"{'Status':<10} {'Rating':<8} {'Roles':<15}"
        )
        print("-" * 108)
        for m in masters:
            roles = specialization_short_text(
                spec_map.get(m.id, [MasterSpecializationType.UNIVERSAL])
            )
            print(
                f"{m.id:<5} {m.telegram_id:<15} {m.full_name:<25} "
                f"{m.phone:<15} {m.status.value:<10} {m.rating:<8.1f} {roles:<15}"
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
        print("-" * 70)
        for s in staff_list:
            print(
                f"{s.id:<5} {s.telegram_id:<15} {s.full_name:<25} "
                f"{s.role.value:<15} {'YES' if s.is_active else 'NO':<8}"
            )


async def show_stats():
    """Show quick statistics."""
    await init_db()
    async with async_session() as session:
        from repositories.stats_repo import StatsRepo
        stats_repo = StatsRepo(session)
        stats = await stats_repo.get_dashboard_stats()

        print("\nAutoHelp.uz Statistics")
        print("-" * 40)
        for key, value in stats.items():
            label = key.replace("_", " ").title()
            print(f"  {label}: {value}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "add_master" and len(sys.argv) in (5, 6):
        roles_csv = sys.argv[5] if len(sys.argv) == 6 else None
        asyncio.run(add_master(int(sys.argv[2]), sys.argv[3], sys.argv[4], roles_csv))
    elif cmd == "set_master_roles" and len(sys.argv) == 4:
        asyncio.run(set_master_roles(int(sys.argv[2]), sys.argv[3]))
    elif cmd == "add_dispatcher" and len(sys.argv) == 5:
        asyncio.run(add_dispatcher(int(sys.argv[2]), sys.argv[3], sys.argv[4]))
    elif cmd == "add_admin" and len(sys.argv) == 5:
        asyncio.run(add_admin(int(sys.argv[2]), sys.argv[3], sys.argv[4]))
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
