from aiogram.fsm.state import State, StatesGroup


class DriverQuickOrderState(StatesGroup):
    issue = State()
    phone = State()
    location = State()
    confirm = State()
