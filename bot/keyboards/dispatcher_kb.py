"""
AutoHelp.uz - Dispatcher Keyboards
Inline keyboards for the dispatcher interface.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from models.master import Master
from models.master_specialization import (
    MasterSpecializationType,
    specialization_short_text,
)


def _master_filter_rows(order_uid: str) -> list[list[InlineKeyboardButton]]:
    """Quick filter/search controls for master assignment."""
    return [
        [
            InlineKeyboardButton(
                text="🔎 Usta qidirish",
                callback_data=f"dispatch_search_master:{order_uid}",
            ),
            InlineKeyboardButton(
                text="🔄 Hammasi",
                callback_data=f"dispatch_assign:{order_uid}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="AKB",
                callback_data=f"dispatch_filter:{order_uid}:battery",
            ),
            InlineKeyboardButton(
                text="TIRE",
                callback_data=f"dispatch_filter:{order_uid}:tire",
            ),
            InlineKeyboardButton(
                text="ELEC",
                callback_data=f"dispatch_filter:{order_uid}:electrical",
            ),
        ],
        [
            InlineKeyboardButton(
                text="ENG",
                callback_data=f"dispatch_filter:{order_uid}:engine",
            ),
            InlineKeyboardButton(
                text="BRK",
                callback_data=f"dispatch_filter:{order_uid}:brake",
            ),
            InlineKeyboardButton(
                text="ALL",
                callback_data=f"dispatch_filter:{order_uid}:universal",
            ),
        ],
    ]


def master_selection_keyboard(
    masters: list[Master],
    order_uid: str,
    specialization_map: dict[int, list[MasterSpecializationType]] | None = None,
    preferred_specializations: list[MasterSpecializationType] | None = None,
) -> InlineKeyboardMarkup:
    """
    Build keyboard with available masters for order assignment.
    Shows master name, rating, and status.
    """
    buttons = []
    specialization_map = specialization_map or {}
    preferred = set(preferred_specializations or [])

    for m in masters:
        status_icon = {"online": "🟢", "busy": "🟡", "offline": "🔴"}.get(
            m.status.value, "⚪"
        )
        specs = specialization_map.get(m.id, [MasterSpecializationType.UNIVERSAL])
        spec_tag = specialization_short_text(specs)
        pin = "🎯 " if any(spec in preferred for spec in specs) else ""
        label = f"{pin}{status_icon} {m.full_name} [{spec_tag}] ⭐{m.rating:.1f}"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"assign:{order_uid}:{m.id}"
        )])

    # Add "Suggest best" button at top
    buttons.insert(0, [InlineKeyboardButton(
        text="🤖 Tizim taklifi (eng yaqin/bo'sh usta)",
        callback_data=f"assign_auto:{order_uid}"
    )])
    buttons[1:1] = _master_filter_rows(order_uid)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def dispatcher_order_actions(order_uid: str) -> InlineKeyboardMarkup:
    """Actions for a specific order in dispatcher view."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="👨‍🔧 Usta tayinlash",
                callback_data=f"dispatch_assign:{order_uid}"
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=f"dispatch_cancel:{order_uid}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="📍 Xaritada ko'rish",
                callback_data=f"dispatch_map:{order_uid}"
            ),
            InlineKeyboardButton(
                text="📞 Mijozga qo'ng'iroq",
                callback_data=f"dispatch_call:{order_uid}"
            ),
        ],
    ])


def dispatcher_main_menu() -> InlineKeyboardMarkup:
    """Dispatcher main menu keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Faol buyurtmalar", callback_data="disp:active_orders")],
        [InlineKeyboardButton(text="👨‍🔧 Ustalar holati", callback_data="disp:masters_status")],
        [InlineKeyboardButton(text="📊 Bugungi statistika", callback_data="disp:today_stats")],
        [InlineKeyboardButton(text="⚠️ SLA ogohlantirishlar", callback_data="disp:sla_alerts")],
    ])


def dispatcher_confirm_completion(order_uid: str) -> InlineKeyboardMarkup:
    """Confirm or adjust order completion."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Tasdiqlash",
                callback_data=f"dispatch_confirm:{order_uid}"
            ),
            InlineKeyboardButton(
                text="✏️ Summani o'zgartirish",
                callback_data=f"dispatch_edit_amount:{order_uid}"
            ),
        ],
    ])


def reassign_order_keyboard(order_uid: str) -> InlineKeyboardMarkup:
    """Keyboard shown when a master rejects an order."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔄 Boshqa usta tayinlash",
            callback_data=f"dispatch_assign:{order_uid}"
        )],
    ])
