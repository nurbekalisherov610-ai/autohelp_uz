from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.db.session import AsyncSessionFactory
from src.services.order_service import OrderService

router = Router(name="client_feedback")

@router.callback_query(F.data.startswith("client_rating:"))
async def cb_client_rating(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    try:
        parts = callback.data.split(":")
        order_id = int(parts[1])
        rating = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("Noto'g'ri baho so'rovi.", show_alert=True)
        return
    if rating < 1 or rating > 5:
        await callback.answer("Baho 1 dan 5 gacha bo'lishi kerak.", show_alert=True)
        return
    
    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
            if order.client is None or callback.from_user is None:
                await callback.answer("Baho berib bo'lmadi.", show_alert=True)
                return
            if order.client.telegram_id != callback.from_user.id:
                await callback.answer("Siz bu buyurtmaga baho bera olmaysiz.", show_alert=True)
                return
            order.rating = rating
            await session.commit()
    except Exception as exc:
        await callback.answer(f"Xatolik yuz berdi: {exc}", show_alert=True)
        return
        
    try:
        await callback.message.edit_text(f"Sizning bahoingiz: {'⭐' * rating}\nFikr-mulohazangiz uchun rahmat!")
    except Exception:
        pass
    await callback.answer()
