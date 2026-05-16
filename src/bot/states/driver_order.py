from aiogram.fsm.state import State, StatesGroup


class DriverQuickOrderState(StatesGroup):
    language = State()
    issue = State()
    phone = State()
    location = State()
    confirm = State()
