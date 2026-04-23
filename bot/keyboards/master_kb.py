"""
AutoHelp.uz - Master Keyboards
Inline keyboards for the master/mechanic interface.
All master navigation uses inline callbacks — immune to FSM state and throttling.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def master_main_menu(is_online: bool = False) -> InlineKeyboardMarkup:
    """Master dashboard with inline buttons — always responsive."""
    toggle_text = "🔴 Offline bo'lish" if is_online else "🟢 Online bo'lish"
    toggle_data = "master_menu:toggle_offline" if is_online else "master_menu:toggle_online"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Faol buyurtma", callback_data="master_menu:active_order")],
        [InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)],
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="master_menu:stats"),
            InlineKeyboardButton(text="⭐ Reytingim", callback_data="master_menu:rating"),
        ],
    ])


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

    # Always show Cancel button during active order
    buttons.append([InlineKeyboardButton(
        text="❌ Bekor qilish",
        callback_data=f"master_cancel:{order_uid}"
    )])

    # Back to dashboard
    buttons.append([InlineKeyboardButton(
        text="🏠 Bosh sahifa",
        callback_data="master_menu:home"
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


def master_back_keyboard() -> InlineKeyboardMarkup:
    """Simple back-to-dashboard button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Bosh sahifa", callback_data="master_menu:home")],
    ])
