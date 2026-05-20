from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

SUPPORTED_LANGUAGES = ("uz", "ru")
DEFAULT_LANGUAGE = "uz"

BUTTONS: dict[str, dict[str, str]] = {
    "start_order": {
        "uz": "🚀 Tez yordam chaqirish",
        "ru": "🚀 Вызвать помощь",
    },
    "order_status": {
        "uz": "📋 Buyurtma holati",
        "ru": "📋 Статус заказа",
    },
    "about": {
        "uz": "ℹ️ Biz haqimizda",
        "ru": "ℹ️ О нас",
    },
    "change_lang": {
        "uz": "🇺🇿/🇷🇺 Tilni o'zgartirish",
        "ru": "🇺🇿/🇷🇺 Сменить язык",
    },
    "phone": {
        "uz": "📞 Raqamni yuborish",
        "ru": "📞 Отправить номер",
    },
    "location": {
        "uz": "📍 Lokatsiyani yuborish",
        "ru": "📍 Отправить локацию",
    },
    "cancel": {
        "uz": "❌ Bekor qilish",
        "ru": "❌ Отменить",
    },
    "confirm": {
        "uz": "✅ Tasdiqlash",
        "ru": "✅ Подтвердить",
    },
}

ISSUE_OPTIONS_BY_LANG: dict[str, list[str]] = {
    "uz": [
        "🛠 Zavod bo'lmayapti",
        "🔋 Akkumulyator o'tirgan",
        "🎈 Balon yorilgan",
        "❓ Boshqa muammo",
    ],
    "ru": [
        "🛠 Не заводится",
        "🔋 Сел аккумулятор",
        "🎈 Пробито колесо",
        "❓ Другая проблема",
    ],
}

START_ORDER_BUTTON = BUTTONS["start_order"][DEFAULT_LANGUAGE]
PHONE_BUTTON = BUTTONS["phone"][DEFAULT_LANGUAGE]
LOCATION_BUTTON = BUTTONS["location"][DEFAULT_LANGUAGE]
CANCEL_BUTTON = BUTTONS["cancel"][DEFAULT_LANGUAGE]
ISSUE_OPTIONS = ISSUE_OPTIONS_BY_LANG[DEFAULT_LANGUAGE]
CANCEL_BUTTONS = set(BUTTONS["cancel"].values())


def normalize_language(language: str | None) -> str:
    if not language:
        return DEFAULT_LANGUAGE
    language = language.lower()
    if language.startswith("ru"):
        return "ru"
    return DEFAULT_LANGUAGE


def button(label: str, language: str | None) -> str:
    lang = normalize_language(language)
    return BUTTONS[label][lang]


def cancel_buttons() -> set[str]:
    return set(BUTTONS["cancel"].values())


def issue_options(language: str | None) -> list[str]:
    return ISSUE_OPTIONS_BY_LANG[normalize_language(language)]


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="language:uz"),
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="language:ru"),
            ]
        ]
    )


def start_keyboard(language: str | None = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=button("start_order", language))],
            [
                KeyboardButton(text=button("order_status", language)),
                KeyboardButton(text=button("about", language)),
            ],
            [KeyboardButton(text=button("change_lang", language))],
        ],
        resize_keyboard=True,
    )


def issue_keyboard(language: str | None = None) -> ReplyKeyboardMarkup:
    kb = [[KeyboardButton(text=option)] for option in issue_options(language)]
    kb.append([KeyboardButton(text=button("cancel", language))])
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def request_phone_keyboard(language: str | None = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=button("phone", language), request_contact=True)],
            [KeyboardButton(text=button("cancel", language))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def request_location_keyboard(language: str | None = None) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=button("location", language), request_location=True)],
            [KeyboardButton(text=button("cancel", language))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def confirm_keyboard(language: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=button("confirm", language), callback_data="order_confirm")],
            [InlineKeyboardButton(text=button("cancel", language), callback_data="order_cancel")],
        ]
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Boshqaruv paneli"), KeyboardButton(text="🆕 Yangi buyurtmalar")],
            [KeyboardButton(text="⏳ Faol buyurtmalar"), KeyboardButton(text="👨‍🔧 Masterlar ro'yxati")],
            [KeyboardButton(text="📥 Buyurtmalar eksporti"), KeyboardButton(text="👥 Foydalanuvchilar")],
        ],
        resize_keyboard=True,
    )


def dispatcher_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Boshqaruv paneli"), KeyboardButton(text="🆕 Yangi buyurtmalar")],
            [KeyboardButton(text="⏳ Faol buyurtmalar")],
        ],
        resize_keyboard=True,
    )


def master_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Mening buyurtmalarim")],
        ],
        resize_keyboard=True,
    )

