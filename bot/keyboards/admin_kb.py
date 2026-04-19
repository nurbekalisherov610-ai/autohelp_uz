"""
AutoHelp.uz - Admin Keyboards
Complete keyboard set for the admin dashboard.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_main_menu() -> InlineKeyboardMarkup:
    """Admin main menu — CEO overview."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Dashboard", callback_data="admin:dashboard"),
            InlineKeyboardButton(text="⚡ Faol buyurtmalar", callback_data="admin:active_orders"),
        ],
        [
            InlineKeyboardButton(text="📋 Buyurtmalar", callback_data="admin:orders"),
            InlineKeyboardButton(text="⭐ Sharhlar", callback_data="admin:reviews"),
        ],
        [
            InlineKeyboardButton(text="👨‍🔧 Ustalar", callback_data="admin:masters"),
            InlineKeyboardButton(text="👥 Dispetcherlar", callback_data="admin:dispatchers"),
        ],
        [
            InlineKeyboardButton(text="📊 Hisobotlar", callback_data="admin:reports"),
            InlineKeyboardButton(text="📥 Excel eksport", callback_data="admin:export"),
        ],
        [
            InlineKeyboardButton(text="📝 Audit log", callback_data="admin:audit"),
        ],
    ])


def admin_back_button() -> InlineKeyboardMarkup:
    """Simple back button to main menu."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="admin:menu")],
    ])


def admin_orders_filter() -> InlineKeyboardMarkup:
    """Order filter keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🆕 Yangi", callback_data="admin_filter:new"),
            InlineKeyboardButton(text="⚡ Faollar", callback_data="admin_filter:active"),
        ],
        [
            InlineKeyboardButton(text="✅ Tugallangan", callback_data="admin_filter:completed"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="admin_filter:cancelled"),
        ],
        [
            InlineKeyboardButton(text="📋 Barchasi", callback_data="admin_filter:all"),
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:menu")],
    ])


def admin_master_actions(master_id: int) -> InlineKeyboardMarkup:
    """Actions for a specific master."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data=f"admin_master_stats:{master_id}"),
        ],
        [
            InlineKeyboardButton(text="✅ Faollashtirish", callback_data=f"admin_master_activate:{master_id}"),
            InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"admin_master_deactivate:{master_id}"),
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:masters")],
    ])


def admin_export_options() -> InlineKeyboardMarkup:
    """Excel export options."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Buyurtmalar", callback_data="export:orders"),
            InlineKeyboardButton(text="⭐ Sharhlar", callback_data="export:reviews"),
        ],
        [
            InlineKeyboardButton(text="👨‍🔧 Ustalar", callback_data="export:masters"),
            InlineKeyboardButton(text="💰 Moliya", callback_data="export:finance"),
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:menu")],
    ])


def admin_reports_period() -> InlineKeyboardMarkup:
    """Report period selection."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Bugun", callback_data="report:today"),
            InlineKeyboardButton(text="📅 Hafta", callback_data="report:week"),
        ],
        [
            InlineKeyboardButton(text="📅 Bu oy", callback_data="report:month"),
            InlineKeyboardButton(text="📅 Bu yil", callback_data="report:year"),
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin:menu")],
    ])
