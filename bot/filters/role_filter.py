"""
AutoHelp.uz - Role-based Access Filter
Filter handlers by user role.
"""
import json
import os
import re
from typing import Union

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from core.config import settings


def _get_admin_ids() -> set[int]:
    """
    Resolve admin IDs from settings + raw environment robustly.
    Supports JSON list, CSV, single ID, or noisy strings.
    """
    ids: set[int] = set()

    for item in settings.admin_ids:
        try:
            ids.add(int(item))
        except (TypeError, ValueError):
            pass

    raw = os.getenv("ADMIN_IDS", "")
    if not raw:
        return ids

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

    for token in re.findall(r"-?\d+", raw):
        try:
            ids.add(int(token))
        except ValueError:
            pass

    return ids


class RoleFilter(BaseFilter):
    """
    Filter that checks if the user has one of the allowed roles.

    Usage:
        @router.message(RoleFilter("admin", "dispatcher"))
        async def admin_only_handler(message: Message, ...):
            ...
    """

    def __init__(self, *allowed_roles: str):
        self.allowed_roles = set(allowed_roles)

    async def __call__(
        self,
        event: Union[Message, CallbackQuery],
        user_role: str = "new",
        **kwargs,
    ) -> bool:
        if user_role in self.allowed_roles:
            return True

        # Admin fallback by Telegram ID (independent of middleware role assignment)
        from_user = getattr(event, "from_user", None)
        telegram_id = getattr(from_user, "id", None)
        if telegram_id is not None:
            admin_roles = {"admin", "super_admin", "dispatcher"}
            if self.allowed_roles.intersection(admin_roles) and telegram_id in _get_admin_ids():
                return True

        return False
