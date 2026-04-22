"""
AutoHelp.uz - Authentication & Role Middleware (optimized)
Resolves role for each event and injects:
- user_role
- user_data
- user_lang
"""
import json
import os
import re
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models import Master, Staff, User


class AuthMiddleware(BaseMiddleware):
    """
    Optimized auth middleware.
    - Checks admin_ids from config first (zero DB cost)
    - Then checks staff -> master -> user
    """

    @staticmethod
    def _load_env_admin_ids() -> set[int]:
        """
        Parse ADMIN_IDS from environment very defensively.
        Supports:
        - JSON list: [123, "456"]
        - CSV: 123,456
        - Any noisy string containing digits
        """
        ids = set()

        # Include already parsed config values
        for item in settings.admin_ids:
            try:
                ids.add(int(item))
            except (TypeError, ValueError):
                pass

        raw = os.getenv("ADMIN_IDS", "")
        if not raw:
            return ids

        # Try JSON first
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    try:
                        ids.add(int(item))
                    except (TypeError, ValueError):
                        pass
            else:
                ids.add(int(parsed))
            return ids
        except Exception:
            pass

        # Fallback: CSV / noisy string
        for token in re.findall(r"-?\d+", raw):
            try:
                ids.add(int(token))
            except ValueError:
                pass

        return ids

    @staticmethod
    def _is_placeholder_master_name(value: str | None) -> bool:
        if not value:
            return True
        raw = value.strip().lower()
        return bool(re.fullmatch(r"master\s+\d+", raw))

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        telegram_id = None
        if isinstance(event, Message) and event.from_user:
            telegram_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            telegram_id = event.from_user.id

        if telegram_id is None:
            return await handler(event, data)

        # Fast path: env-configured admins should always keep admin privileges.
        admin_ids = self._load_env_admin_ids()
        if telegram_id in admin_ids:
            session: AsyncSession = data.get("session")
            staff = None
            if session:
                staff = await session.scalar(
                    select(Staff).where(Staff.telegram_id == telegram_id)
                )
            data["user_role"] = "super_admin"
            data["user_data"] = staff
            data["user_lang"] = "uz"
            return await handler(event, data)

        session: AsyncSession = data.get("session")
        if session is None:
            data["user_role"] = "new"
            data["user_data"] = None
            data["user_lang"] = "uz"
            return await handler(event, data)

        # Staff first (most privileged / smallest table)
        staff = await session.scalar(
            select(Staff).where(
                Staff.telegram_id == telegram_id,
                Staff.is_active == True,
            )
        )
        if staff:
            data["user_role"] = staff.role.value
            data["user_data"] = staff
            data["user_lang"] = "uz"
            return await handler(event, data)

        master = await session.scalar(
            select(Master).where(
                Master.telegram_id == telegram_id,
                Master.is_active == True,
            )
        )
        if master:
            from_user = getattr(event, "from_user", None)
            if from_user:
                first = (from_user.first_name or "").strip()
                last = (from_user.last_name or "").strip()
                username = (from_user.username or "").strip()
                base_name = " ".join(part for part in [first, last] if part).strip()
                if username:
                    profile_name = f"{base_name} (@{username})" if base_name else f"@{username}"
                else:
                    profile_name = base_name

                if profile_name and self._is_placeholder_master_name(master.full_name):
                    master.full_name = profile_name
                    await session.flush()

            data["user_role"] = "master"
            data["user_data"] = master
            data["user_lang"] = "uz"
            return await handler(event, data)

        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user:
            data["user_role"] = "client"
            data["user_data"] = user
            data["user_lang"] = user.language.value
        else:
            data["user_role"] = "new"
            data["user_data"] = None
            data["user_lang"] = "uz"

        return await handler(event, data)
