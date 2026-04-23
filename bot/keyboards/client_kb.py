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
        is_persistent=False,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder=(
            "Telefon raqamingizni yuboring"
            if lang == "uz"
            else "Отправьте ваш номер"
        ),
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
    cancel = {"uz": "❌ Bekor qilish", "ru": "❌ Отменить"}
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.get(lang, texts["uz"]), request_location=True)],
            [KeyboardButton(text=cancel.get(lang, cancel["uz"]))],
        ],
        is_persistent=False,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder=(
            "Joylashuv tugmasini bosing"
            if lang == "uz"
            else "Нажмите кнопку геолокации"
        ),
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


def review_issue_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Optional post-rating issue picker."""
    labels = {
        "uz": {
            "none": "✅ Muammo yo'q",
            "delay": "🕒 Kechikish",
            "quality": "🔧 Sifat past",
            "price": "💰 Narx bo'yicha e'tiroz",
            "behavior": "🙅 Muomala yomon",
        },
        "ru": {
            "none": "✅ Нет проблем",
            "delay": "🕒 Опоздание",
            "quality": "🔧 Низкое качество",
            "price": "💰 Вопрос по цене",
            "behavior": "🙅 Плохое поведение",
        },
    }
    l = labels.get(lang, labels["uz"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=l["none"], callback_data="review_issue:none")],
        [InlineKeyboardButton(text=l["delay"], callback_data="review_issue:delay")],
        [InlineKeyboardButton(text=l["quality"], callback_data="review_issue:quality")],
        [InlineKeyboardButton(text=l["price"], callback_data="review_issue:price")],
        [InlineKeyboardButton(text=l["behavior"], callback_data="review_issue:behavior")],
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
