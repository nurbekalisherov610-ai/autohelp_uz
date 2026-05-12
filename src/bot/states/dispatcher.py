from aiogram.fsm.state import State, StatesGroup


class DispatcherAssignMasterState(StatesGroup):
    waiting_for_master_id = State()


class DispatcherCompleteOrderState(StatesGroup):
    waiting_for_amount = State()
