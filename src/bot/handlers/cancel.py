from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

router = Router(name="cancel")


@router.message(Command("cancel"))
@router.message(F.text.lower() == "bekor qilish")
async def cancel_handler(message: Message, state: FSMContext) -> None:
    """
    Allow user to cancel any action unconditionally.
    """
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Bekor qilinadigan amal yo'q.", reply_markup=ReplyKeyboardRemove())
        return

    await state.clear()
    await message.answer(
        "Amal bekor qilindi.",
        reply_markup=ReplyKeyboardRemove(),
    )
