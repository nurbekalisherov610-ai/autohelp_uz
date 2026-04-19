"""
AutoHelp.uz - Master FSM States
Finite State Machine states for the master/mechanic flow.
"""
from aiogram.fsm.state import State, StatesGroup


class MasterOrderStates(StatesGroup):
    """Master order handling states."""
    viewing_order = State()
    updating_status = State()
    entering_amount = State()
    recording_video = State()
