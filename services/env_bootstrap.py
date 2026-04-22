"""
AutoHelp.uz - Environment Role Bootstrap
Creates/updates masters and staff from environment variables on startup.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import async_session
from models.master import Master, MasterStatus
from models.master_specialization import (
    MasterSpecialization,
    MasterSpecializationType,
    parse_specializations_csv,
)
from models.staff import Staff, StaffRole
from repositories.master_repo import MasterRepo


_ROLE_PRIORITY = {
    StaffRole.DISPATCHER: 1,
    StaffRole.ADMIN: 2,
    StaffRole.SUPER_ADMIN: 3,
}


def _unique_ids(*groups: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for group in groups:
        for value in group:
            try:
                tid = int(value)
            except (TypeError, ValueError):
                continue
            if tid in seen:
                continue
            seen.add(tid)
            out.append(tid)
    return out


def _parse_master_roles(raw: str) -> dict[int, list[MasterSpecializationType]]:
    """
    Parse MASTER_ROLES from env.

    Supported formats:
    - JSON object:
      {"8562893513":"battery,electrical","962386916":["tire"]}
    - key/value string:
      8562893513=battery,electrical;962386916=tire
    """
    raw = (raw or "").strip()
    if not raw:
        return {}

    role_map: dict[int, list[MasterSpecializationType]] = {}

    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    try:
                        tid = int(str(key).strip())
                    except (TypeError, ValueError):
                        continue

                    if isinstance(value, list):
                        csv_value = ",".join(str(x) for x in value)
                    else:
                        csv_value = str(value)
                    role_map[tid] = parse_specializations_csv(csv_value)
                return role_map
        except Exception:
            pass

    parts = [p.strip() for p in re.split(r"[;\n]+", raw) if p.strip()]
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        try:
            tid = int(key.strip())
        except ValueError:
            continue
        role_map[tid] = parse_specializations_csv(value.strip())

    return role_map


def _parse_master_labels(raw: str) -> dict[int, str]:
    """
    Parse MASTER_LABELS from env.

    Supported formats:
    - JSON object:
      {"8562893513":"Ali Usta","962386916":"@usta_aziz"}
    - key/value string:
      8562893513=Ali Usta;962386916=@usta_aziz
    """
    raw = (raw or "").strip()
    if not raw:
        return {}

    label_map: dict[int, str] = {}

    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    try:
                        tid = int(str(key).strip())
                    except (TypeError, ValueError):
                        continue
                    label = str(value or "").strip()
                    if label:
                        label_map[tid] = label
                return label_map
        except Exception:
            pass

    parts = [p.strip() for p in re.split(r"[;\n]+", raw) if p.strip()]
    for part in parts:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        try:
            tid = int(key.strip())
        except ValueError:
            continue
        label = value.strip()
        if label:
            label_map[tid] = label

    return label_map


async def _upsert_staff(session: AsyncSession, telegram_id: int, target_role: StaffRole) -> str:
    staff = await session.scalar(
        select(Staff).where(Staff.telegram_id == telegram_id)
    )
    action = "updated"
    if not staff:
        staff = Staff(
            telegram_id=telegram_id,
            full_name=f"Staff {telegram_id}",
            phone=None,
            role=target_role,
            is_active=True,
        )
        session.add(staff)
        action = "created"
    else:
        staff.is_active = True
        if not (staff.full_name or "").strip():
            staff.full_name = f"Staff {telegram_id}"

        current_priority = _ROLE_PRIORITY.get(staff.role, 0)
        target_priority = _ROLE_PRIORITY.get(target_role, 0)
        if target_priority > current_priority:
            staff.role = target_role

    return action


async def sync_roles_from_env() -> dict[str, int]:
    """
    Sync environment-defined roles into DB.
    Safe/idempotent:
    - creates missing entities
    - re-activates existing entities
    - never downgrades staff roles
    """
    summary = {
        "super_admin_created": 0,
        "super_admin_updated": 0,
        "admin_created": 0,
        "admin_updated": 0,
        "dispatcher_created": 0,
        "dispatcher_updated": 0,
        "master_created": 0,
        "master_updated": 0,
        "master_roles_applied": 0,
        "master_labels_applied": 0,
    }

    if not settings.env_bootstrap_enabled:
        logger.info("Env role bootstrap disabled (ENV_BOOTSTRAP_ENABLED=false).")
        return summary

    super_admin_ids = _unique_ids(settings.admin_ids)
    admin_ids = _unique_ids(settings.admin_staff_ids)
    dispatcher_ids = _unique_ids(settings.dispatcher_ids)
    master_ids = _unique_ids(settings.master_ids)
    master_roles = _parse_master_roles(settings.master_roles)
    master_labels = _parse_master_labels(settings.master_labels)

    async with async_session() as session:
        for tid in super_admin_ids:
            action = await _upsert_staff(session, tid, StaffRole.SUPER_ADMIN)
            summary[f"super_admin_{action}"] += 1

        for tid in admin_ids:
            action = await _upsert_staff(session, tid, StaffRole.ADMIN)
            summary[f"admin_{action}"] += 1

        for tid in dispatcher_ids:
            action = await _upsert_staff(session, tid, StaffRole.DISPATCHER)
            summary[f"dispatcher_{action}"] += 1

        if not master_ids and not master_roles and not master_labels:
            await session.commit()
            logger.info(f"Env role bootstrap summary: {summary}")
            return summary

        master_repo = MasterRepo(session)
        ids_to_process = _unique_ids(master_ids, master_roles.keys(), master_labels.keys())

        for tid in ids_to_process:
            master = await session.scalar(
                select(Master).where(Master.telegram_id == tid)
            )
            created = False
            if not master:
                label = master_labels.get(tid)
                master = Master(
                    telegram_id=tid,
                    full_name=label or f"Master {tid}",
                    phone="not_set",
                    status=MasterStatus.OFFLINE,
                    is_active=True,
                )
                session.add(master)
                await session.flush()
                created = True
                summary["master_created"] += 1
                if label:
                    summary["master_labels_applied"] += 1
            else:
                label = master_labels.get(tid)
                master.is_active = True
                if label:
                    master.full_name = label
                    summary["master_labels_applied"] += 1
                elif not (master.full_name or "").strip():
                    master.full_name = f"Master {tid}"
                if not (master.phone or "").strip():
                    master.phone = "not_set"
                summary["master_updated"] += 1

            specs = master_roles.get(tid)
            if specs:
                await master_repo.set_specializations(master.id, specs)
                summary["master_roles_applied"] += 1
                continue

            if created:
                await master_repo.set_specializations(
                    master.id,
                    [MasterSpecializationType.UNIVERSAL],
                )
                continue

            has_spec = await session.scalar(
                select(MasterSpecialization.id)
                .where(MasterSpecialization.master_id == master.id)
                .limit(1)
            )
            if not has_spec:
                await master_repo.set_specializations(
                    master.id,
                    [MasterSpecializationType.UNIVERSAL],
                )

        await session.commit()

    logger.info(f"Env role bootstrap summary: {summary}")
    return summary
