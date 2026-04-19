"""
AutoHelp.uz - Seed Script (Samarkand)
Populates the database: Samarkand districts + admin accounts.
Safe to run multiple times.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import models  # noqa — registers all models
from core.config import settings
from core.database import async_session, init_db, close_db
from models.staff import Staff, StaffRole
from models.master import Master
from models.district import District


SAMARKAND_DISTRICTS = [
    ("Samarqand shahri", "г. Самарканд"),
    ("Urgut tumani", "Ургутский район"),
    ("Kattaqo'rg'on shahri", "г. Каттакурган"),
    ("Ishtixon tumani", "Иштиханский район"),
    ("Jomboy tumani", "Джамбайский район"),
    ("Payariq tumani", "Пайарыкский район"),
    ("Pastdarg'om tumani", "Пастдаргомский район"),
    ("Qo'shrabot tumani", "Кушрабатский район"),
    ("Narpay tumani", "Нарпайский район"),
    ("Nurabad tumani", "Нурабадский район"),
    ("Oqdaryo tumani", "Акдарьинский район"),
    ("Toyloq tumani", "Тайлякский район"),
    ("Bulungur tumani", "Булунгурский район"),
]


async def seed():
    await init_db()
    print("Tables ready.\n")

    async with async_session() as session:
        from sqlalchemy import select, func, delete

        # ── Replace all districts with Samarkand ones ────────────
        existing_count = await session.scalar(select(func.count(District.id)))
        if existing_count:
            await session.execute(delete(District))
            await session.flush()
            print(f"Removed {existing_count} old district(s)")

        for name_uz, name_ru in SAMARKAND_DISTRICTS:
            session.add(District(name_uz=name_uz, name_ru=name_ru, is_active=True))
        print(f"Added {len(SAMARKAND_DISTRICTS)} Samarkand district(s)")

        # ── Admin accounts ───────────────────────────────────────
        for admin_id in settings.admin_ids:
            existing = await session.scalar(
                select(Staff).where(Staff.telegram_id == admin_id)
            )
            if not existing:
                session.add(Staff(
                    telegram_id=admin_id,
                    full_name="Admin",
                    role=StaffRole.SUPER_ADMIN,
                    is_active=True,
                ))
                print(f"Added admin: {admin_id}")
            else:
                print(f"Admin {admin_id} already exists")

        await session.commit()

    # Summary
    async with async_session() as session:
        from sqlalchemy import select, func
        staff_count = await session.scalar(select(func.count(Staff.id)))
        district_count = await session.scalar(select(func.count(District.id)))
        master_count = await session.scalar(select(func.count(Master.id)))

    print(f"\n{'='*35}")
    print(f"  Database summary — AutoHelp.uz")
    print(f"  Region: Samarqand viloyati")
    print(f"{'='*35}")
    print(f"  Staff (admin/dispatcher): {staff_count}")
    print(f"  Masters: {master_count}")
    print(f"  Districts: {district_count}")
    print(f"{'='*35}")
    print(f"\nDone!")

    await close_db()


if __name__ == "__main__":
    asyncio.run(seed())
