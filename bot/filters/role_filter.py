"""
AutoHelp.uz - Role-based Access Filter
Filter handlers by user role.
"""
from typing import Union

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery


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
        return user_role in self.allowed_roles
