"""
AutoHelp.uz - Client FSM States
Finite State Machine states for the client/driver flow.
"""
from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """Client registration flow."""
    waiting_language = State()
    waiting_contact = State()


class OrderCreationStates(StatesGroup):
    """Order creation flow."""
    selecting_problem = State()
    entering_description = State()
    sharing_location = State()
    confirming_order = State()


class ReviewStates(StatesGroup):
    """Review/rating flow after order completion."""
    selecting_rating = State()
    selecting_issue = State()
    entering_comment = State()


class SettingsStates(StatesGroup):
    """Settings flow."""
    main = State()
    changing_language = State()
