import json
from pathlib import Path
from typing import Dict

import nonebot_plugin_localstore as store
from nonebot.log import logger

_group_profile_file: Path = store.get_data_file("nonebot_plugin_dify", "group_profiles.json")
_personalization_file: Path = store.get_data_file("nonebot_plugin_dify", "personalizations.json")


def _read_data(file_path: Path) -> Dict[str, str]:
    """Reads data from a JSON file."""
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text("utf-8"))
    except json.JSONDecodeError:
        logger.warning(f"Failed to decode JSON from {file_path}, returning empty dict.")
        return {}


def _write_data(file_path: Path, data: Dict[str, str]):
    """Writes data to a JSON file."""
    file_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")


class GroupProfileMemory:
    """
    Manages persistent storage for group profiles.
    Group profiles are summaries of a group's chat history, generated periodically
    to give the AI context about the group's general topics and personality.
    """

    def __init__(self):
        """Initializes the memory by loading existing group profiles from a file."""
        self.group_profiles: Dict[str, str] = _read_data(_group_profile_file)

    def get(self, adapter_name: str, group_id: str) -> str:
        """Retrieves the profile for a specific group."""
        key = f"{adapter_name}+{group_id}"
        return self.group_profiles.get(key, "")

    def set(self, adapter_name: str, group_id: str, profile: str):
        """Updates and saves the profile for a specific group."""
        key = f"{adapter_name}+{group_id}"
        self.group_profiles[key] = profile
        _write_data(_group_profile_file, self.group_profiles)
        logger.debug(f"Group {group_id} profile updated and saved for adapter {adapter_name}.")


class PersonalizationMemory:
    """
    Manages persistent storage for group personalizations.
    This data is used to tailor the AI's behavior to a specific group.
    """

    def __init__(self):
        """Initializes the memory by loading existing personalizations from a file."""
        self.personalizations: Dict[str, str] = _read_data(_personalization_file)

    def get(self, adapter_name: str, group_id: str) -> str:
        """Retrieves the personalization for a specific group."""
        key = f"{adapter_name}+{group_id}"
        return self.personalizations.get(key, "")

    def set(self, adapter_name: str, group_id: str, personalization: str):
        """Updates and saves the personalization for a specific group."""
        key = f"{adapter_name}+{group_id}"
        self.personalizations[key] = personalization
        _write_data(_personalization_file, self.personalizations)
        logger.debug(f"Group {group_id} personalization updated and saved for adapter {adapter_name}.")


group_profile_memory: GroupProfileMemory = GroupProfileMemory()
personalization_memory: PersonalizationMemory = PersonalizationMemory()
