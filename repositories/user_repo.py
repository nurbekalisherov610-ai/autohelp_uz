"""
AutoHelp.uz - User Repository
Database operations for the users table.
"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User, Language


class UserRepo:
    """Repository for user/client database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """Get user by Telegram ID."""
        result = await self.session.scalar(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result

    async def create(
        self,
        telegram_id: int,
        full_name: str,
        phone: str,
        language: Language = Language.UZ,
    ) -> User:
        """Create a new user."""
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            phone=phone,
            language=language,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_language(self, telegram_id: int, language: Language) -> None:
        """Update user's language preference."""
        await self.session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(language=language)
        )

    async def get_or_create(
        self,
        telegram_id: int,
        full_name: str,
        phone: str,
        language: Language = Language.UZ,
    ) -> tuple[User, bool]:
        """Get existing user or create new one. Returns (user, created)."""
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            return user, False
        user = await self.create(telegram_id, full_name, phone, language)
        return user, True

    async def count_total(self) -> int:
        """Count total registered users."""
        from sqlalchemy import func
        result = await self.session.scalar(select(func.count(User.id)))
        return result or 0
