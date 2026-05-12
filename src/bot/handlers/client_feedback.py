from aiogram import F, Router
from aiogram.types import CallbackQuery

from src.db.session import AsyncSessionFactory
from src.services.order_service import OrderService

router = Router(name="client_feedback")

@router.callback_query(F.data.startswith("client_rating:"))
async def cb_client_rating(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    order_id = int(parts[1])
    rating = int(parts[2])
    
    try:
        async with AsyncSessionFactory() as session:
            service = OrderService(session)
            order = await service.get_order(order_id)
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
