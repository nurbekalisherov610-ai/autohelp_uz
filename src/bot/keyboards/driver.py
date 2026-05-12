from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

START_ORDER_BUTTON = "Tez yordam chaqirish"
PHONE_BUTTON = "Raqamni yuborish"
LOCATION_BUTTON = "Lokatsiyani yuborish"
CANCEL_BUTTON = "❌ Bekor qilish"

ISSUE_OPTIONS = [
    "Zavod bo'lmayapti",
    "Akkumulyator o'tirgan",
    "Balon yorilgan",
    "Boshqa muammo",
]


def start_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=START_ORDER_BUTTON)]],
        resize_keyboard=True,
    )


def issue_keyboard() -> ReplyKeyboardMarkup:
    kb = [[KeyboardButton(text=option)] for option in ISSUE_OPTIONS]
    kb.append([KeyboardButton(text=CANCEL_BUTTON)])
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def request_phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=PHONE_BUTTON, request_contact=True)],
            [KeyboardButton(text=CANCEL_BUTTON)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def request_location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=LOCATION_BUTTON, request_location=True)],
            [KeyboardButton(text=CANCEL_BUTTON)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Tasdiqlash", callback_data="order_confirm")],
            [InlineKeyboardButton(text="Bekor qilish", callback_data="order_cancel")],
        ]
    )
