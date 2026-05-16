from src.core.config import PLACEHOLDER_CHAT_IDS, get_settings

settings = get_settings()

def get_authorized_admin_ids() -> set[int]:
    """Return the set of telegram IDs that have superadmin privileges."""
    ids = set(settings.parsed_admin_ids)
    if settings.admin_chat_id and settings.admin_chat_id > 0:
        ids.add(settings.admin_chat_id)
    return {i for i in ids if i and i not in PLACEHOLDER_CHAT_IDS}

def get_authorized_dispatcher_ids() -> set[int]:
    """Return the set of telegram IDs that have dispatcher privileges."""
    ids = set(settings.parsed_dispatcher_ids)
    # Superadmins also have dispatcher rights
    ids.update(get_authorized_admin_ids())
    
    if settings.dispatcher_chat_id and settings.dispatcher_chat_id > 0:
        ids.add(settings.dispatcher_chat_id)
    return {i for i in ids if i and i not in PLACEHOLDER_CHAT_IDS}

def get_authorized_dispatcher_chat_ids() -> set[int]:
    """Return the set of chat/group IDs where dispatcher actions are allowed."""
    chats = {settings.dispatcher_group_id, settings.dispatcher_chat_id}
    return {c for c in chats if c and c not in PLACEHOLDER_CHAT_IDS}

def is_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    admins = get_authorized_admin_ids()
    if not admins and settings.app_env == "dev":
        return True
    return user_id in admins

def is_dispatcher(user_id: int | None, chat_id: int | None = None) -> bool:
    """Check if the user OR the current chat is an authorized dispatcher context."""
    if user_id in get_authorized_dispatcher_ids():
        return True
    if chat_id in get_authorized_dispatcher_chat_ids():
        return True
    return False

def is_master(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return user_id in settings.parsed_master_ids
