"""
AutoHelp.uz - Client Keyboards
Reply and inline keyboards for the client/driver interface.
"""
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from models.order import ProblemType, PROBLEM_LABELS


def language_keyboard() -> InlineKeyboardMarkup:
    """Language selection keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇿 O'zbek tili", callback_data="lang:uz"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
        ]
    ])


def share_contact_keyboard(lang: str = "uz") -> ReplyKeyboardMarkup:
    """Share phone contact keyboard."""
    texts = {
        "uz": "📞 Telefon raqamni yuborish",
        "ru": "📞 Отправить номер телефона",
    }
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.get(lang, texts["uz"]), request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_menu_keyboard(lang: str = "uz") -> ReplyKeyboardMarkup:
    """Client main menu keyboard."""
    if lang == "ru":
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🆘 Запросить помощь")],
                [KeyboardButton(text="📋 Мои заявки")],
                [KeyboardButton(text="⚙️ Настройки")],
            ],
            resize_keyboard=True,
        )
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🆘 Yordam so'rash")],
            [KeyboardButton(text="📋 Mening buyurtmalarim")],
            [KeyboardButton(text="⚙️ Sozlamalar")],
        ],
        resize_keyboard=True,
    )


def problem_type_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Problem type selection keyboard."""
    buttons = []
    for pt in ProblemType:
        label = PROBLEM_LABELS[pt][lang]
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"problem:{pt.value}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def skip_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Skip button keyboard."""
    texts = {"uz": "⏭ O'tkazib yuborish", "ru": "⏭ Пропустить"}
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.get(lang, texts["uz"]), callback_data="skip")]
    ])


def share_location_keyboard(lang: str = "uz") -> ReplyKeyboardMarkup:
    """Share location keyboard."""
    texts = {"uz": "📍 Joylashuvni yuborish", "ru": "📍 Отправить геолокацию"}
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.get(lang, texts["uz"]), request_location=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def confirm_order_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Confirm/cancel order keyboard."""
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="order:confirm"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="order:cancel"),
            ]
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="order:confirm"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="order:cancel"),
        ]
    ])


def cancel_order_keyboard(order_uid: str, lang: str = "uz") -> InlineKeyboardMarkup:
    """Cancel active order keyboard."""
    texts = {"uz": "❌ Buyurtmani bekor qilish", "ru": "❌ Отменить заявку"}
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=texts.get(lang, texts["uz"]),
            callback_data=f"cancel_order:{order_uid}"
        )]
    ])


def rating_keyboard() -> InlineKeyboardMarkup:
    """Star rating keyboard (1-5)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 ⭐", callback_data="rate:1"),
            InlineKeyboardButton(text="2 ⭐", callback_data="rate:2"),
            InlineKeyboardButton(text="3 ⭐", callback_data="rate:3"),
            InlineKeyboardButton(text="4 ⭐", callback_data="rate:4"),
            InlineKeyboardButton(text="5 ⭐", callback_data="rate:5"),
        ]
    ])


def settings_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Settings menu keyboard."""
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Сменить язык", callback_data="settings:language")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Tilni o'zgartirish", callback_data="settings:language")],
    ])
