import json
import threading
from pathlib import Path
from typing import Dict

import nonebot_plugin_localstore as store
from nonebot.log import logger

from .user_data_store import user_profile_memory, user_personalization_memory

_private_personalization_file: Path = store.get_data_file("nonebot_plugin_dify", "private_personalization_status.json")

# Thread lock for safe concurrent access
_status_lock = threading.Lock()


def _read_status() -> Dict[str, bool]:
    """Reads personalization status data from JSON file."""
    if not _private_personalization_file.exists():
        return {}
    try:
        return json.loads(_private_personalization_file.read_text("utf-8"))
    except json.JSONDecodeError:
        logger.warning(f"Failed to decode JSON from {_private_personalization_file}, returning empty dict.")
        return {}


def _write_status(data: Dict[str, bool]):
    """Writes personalization status data to JSON file."""
    _private_personalization_file.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")


def set_personalization_status(adapter_name: str, user_id: str, status: bool) -> None:
    """
    Sets the personalization status for a specific user.

    Args:
        adapter_name: The name of the chat adapter (e.g., 'telegram', 'discord')
        user_id: The unique user identifier
        status: True to enable personalization, False to disable
    """
    key = f"{adapter_name}+private+{user_id}"
    with _status_lock:
        all_statuses = _read_status()
        all_statuses[key] = status
        _write_status(all_statuses)
    logger.debug(f"Set personalization status for user {user_id} on {adapter_name}: {status}")


def get_personalization_status(adapter_name: str, user_id: str) -> bool:
    """
    Gets the personalization status for a specific user.

    Args:
        adapter_name: The name of the chat adapter (e.g., 'telegram', 'discord')
        user_id: The unique user identifier

    Returns:
        bool: True if personalization is enabled, False otherwise (default)
    """
    key = f"{adapter_name}+private+{user_id}"
    with _status_lock:
        return _read_status().get(key, False)


def get_all_personalization_statuses() -> Dict[str, bool]:
    """
    Gets all personalization statuses.

    Returns:
        Dict[str, bool]: Dictionary mapping user keys to their personalization status
    """
    with _status_lock:
        return _read_status().copy()


def opt_out_user(adapter_name: str, user_id: str) -> None:
    """
    Completely opts out a user from personalization and removes all their data.
    This includes:
    - Setting personalization status to False
    - Deleting user profile data
    - Deleting user personalization data

    Args:
        adapter_name: The name of the chat adapter (e.g., 'telegram', 'discord')
        user_id: The unique user identifier
    """
    # Disable personalization
    set_personalization_status(adapter_name, user_id, False)

    # Delete all user data
    user_profile_memory.delete(adapter_name, user_id)
    user_personalization_memory.delete(adapter_name, user_id)

    logger.info(f"User {user_id} on {adapter_name} has been completely opted out and all data removed.")
