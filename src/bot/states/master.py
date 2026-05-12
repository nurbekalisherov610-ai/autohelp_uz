from aiogram.fsm.state import State, StatesGroup


class MasterCompletionState(StatesGroup):
    waiting_for_video = State()
    waiting_for_amount = State()
