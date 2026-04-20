"""
AutoHelp.uz - Dispatcher FSM States
Finite State Machine states for the dispatcher flow.
"""
from aiogram.fsm.state import State, StatesGroup


class DispatcherOrderStates(StatesGroup):
    """Dispatcher order management states."""
    viewing_order = State()
    selecting_master = State()
    searching_master = State()
    recording_video = State()
    editing_amount = State()


class DispatcherManageStates(StatesGroup):
    """Dispatcher management states."""
    viewing_masters = State()
    viewing_active_orders = State()
