"""
AutoHelp.uz - Master Keyboards
Inline and reply keyboards for the master/mechanic interface.
"""
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)


def master_main_menu(is_online: bool = False) -> ReplyKeyboardMarkup:
    """Master main menu with availability toggle."""
    toggle_text = "🔴 Offline bo'lish" if is_online else "🟢 Online bo'lish"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⚡ Faol buyurtma")],
            [KeyboardButton(text=toggle_text)],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="⭐ Reytingim")],
        ],
        resize_keyboard=True,
    )


def master_order_response(order_uid: str) -> InlineKeyboardMarkup:
    """Accept/reject incoming order."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Qabul qilaman",
                callback_data=f"master_accept:{order_uid}"
            ),
            InlineKeyboardButton(
                text="❌ Rad etaman",
                callback_data=f"master_reject:{order_uid}"
            ),
        ],
    ])


def master_status_update_keyboard(order_uid: str, current_status: str) -> InlineKeyboardMarkup:
    """
    Progressive status update keyboard.
    Only shows the NEXT valid status transition.
    """
    status_flow = {
        "accepted": ("on_the_way", "🚗 Yo'ldaman"),
        "on_the_way": ("arrived", "📍 Yetib keldim"),
        "arrived": ("in_progress", "🔧 Ish boshladim"),
        "in_progress": ("awaiting_confirm", "✅ Tugatdim"),
    }

    buttons = []
    if current_status in status_flow:
        next_status, label = status_flow[current_status]
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"master_status:{order_uid}:{next_status}"
        )])

    # Always show call client button during active order
    buttons.append([InlineKeyboardButton(
        text="📞 Mijozga qo'ng'iroq",
        callback_data=f"master_call:{order_uid}"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def master_complete_keyboard(order_uid: str) -> InlineKeyboardMarkup:
    """Keyboard after master marks work complete — enter amount."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💰 Summani kiritish",
            callback_data=f"master_amount:{order_uid}"
        )],
    ])
