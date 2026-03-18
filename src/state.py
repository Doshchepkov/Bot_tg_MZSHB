from aiogram.fsm.state import StatesGroup, State


class ProfileStates(StatesGroup):
    NAME = State()
    SEX = State()
    AGE = State()
    CITY = State()
    DESCRIPTION = State()
    PHOTO = State()
    SONG = State()
    AUDIO = State()
    PREFERENCES = State()


class AdminStates(StatesGroup):
    waiting_admin_id = State()
    waiting_recover_id = State()


class BroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()


class MessageStates(StatesGroup):
    awaiting_message = State()
