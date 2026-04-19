"""
AutoHelp.uz - Order Draft Repository
Database operations for unfinished order-flow reminders.
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.order_draft import OrderDraft


class OrderDraftRepo:
    """Repository for order draft reminder tracking."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def touch(
        self,
        telegram_id: int,
        user_id: int | None,
        language: str,
        fsm_state: str | None,
    ) -> OrderDraft:
        """
        Upsert/refresh an active draft record.
        Any activity resets reminder_sent so future inactivity can be nudged again.
        """
        draft = await self.session.scalar(
            select(OrderDraft).where(OrderDraft.telegram_id == telegram_id)
        )
        now = datetime.utcnow()

        if draft:
            draft.user_id = user_id
            draft.language = (language or "uz")[:2]
            draft.fsm_state = fsm_state
            draft.is_active = True
            draft.reminder_sent = False
            draft.last_activity_at = now
            return draft

        draft = OrderDraft(
            telegram_id=telegram_id,
            user_id=user_id,
            language=(language or "uz")[:2],
            fsm_state=fsm_state,
            is_active=True,
            reminder_sent=False,
            started_at=now,
            last_activity_at=now,
        )
        self.session.add(draft)
        await self.session.flush()
        return draft

    async def clear(self, telegram_id: int) -> None:
        """Mark draft as inactive (flow finished/cancelled)."""
        draft = await self.session.scalar(
            select(OrderDraft).where(OrderDraft.telegram_id == telegram_id)
        )
        if not draft:
            return
        draft.is_active = False
        draft.reminder_sent = False
        draft.fsm_state = None
        draft.reminded_at = None

    async def get_due_reminders(
        self,
        inactive_minutes: int,
        limit: int = 200,
    ) -> list[OrderDraft]:
        """Get active drafts that are inactive longer than threshold and not yet reminded."""
        cutoff = datetime.utcnow() - timedelta(minutes=inactive_minutes)
        result = await self.session.scalars(
            select(OrderDraft)
            .where(
                OrderDraft.is_active == True,
                OrderDraft.reminder_sent == False,
                OrderDraft.last_activity_at <= cutoff,
            )
            .order_by(OrderDraft.last_activity_at.asc())
            .limit(limit)
        )
        return list(result.all())

    async def mark_reminded(self, draft_id: int) -> None:
        """Mark reminder as sent so the same inactivity window is not spammed."""
        draft = await self.session.scalar(
            select(OrderDraft).where(OrderDraft.id == draft_id)
        )
        if not draft:
            return
        draft.reminder_sent = True
        draft.reminded_at = datetime.utcnow()
