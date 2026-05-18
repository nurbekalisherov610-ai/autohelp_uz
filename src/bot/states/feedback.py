from aiogram.fsm.state import State, StatesGroup

class ClientFeedbackState(StatesGroup):
    waiting_for_text = State()
    waiting_for_shortcomings = State()
