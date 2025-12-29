import json
from pathlib import Path
from typing import Dict, Any, List

import nonebot_plugin_localstore as store
from nonebot.log import logger

_group_profile_file: Path = store.get_data_file("nonebot_plugin_dify", "group_profiles.json")
_personalization_file: Path = store.get_data_file("nonebot_plugin_dify", "personalizations.json")
_group_user_profile_file: Path = store.get_data_file("nonebot_plugin_dify", "group_user_profiles.json")


def _read_data(file_path: Path) -> Dict[str, Any]:
    """Reads data from a JSON file."""
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text("utf-8"))
    except json.JSONDecodeError:
        logger.warning(f"Failed to decode JSON from {file_path}, returning empty dict.")
        return {}


def _write_data(file_path: Path, data: Dict[str, Any]):
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


class GroupUserMemory:
    """
    Manages persistent storage for group user profiles.
    This data contains individual user personas and bot identifications within a group.
    Structure:
    {
      "adapter+group_id": {
        "user_id": {
          "nickname": "string",
          "persona": ["tag1", "tag2"],
          "is_bot": boolean,
          "last_active": "timestamp"
        }
      }
    }
    """

    def __init__(self):
        """Initializes the memory by loading existing group user profiles from a file."""
        self.group_user_profiles: Dict[str, Dict[str, Any]] = _read_data(_group_user_profile_file)

    def get_group_data(self, adapter_name: str, group_id: str) -> Dict[str, Any]:
        """Retrieves all user profiles for a specific group."""
        key = f"{adapter_name}+{group_id}"
        return self.group_user_profiles.get(key, {})

    def get_user_profile(self, adapter_name: str, group_id: str, user_id: str) -> Dict[str, Any]:
        """Retrieves the profile for a specific user in a group."""
        group_data = self.get_group_data(adapter_name, group_id)
        return group_data.get(user_id, {})

    def update_user_profile(
        self,
        adapter_name: str,
        group_id: str,
        user_id: str,
        persona: List[str],
        is_bot: bool,
        last_active: str,
        nickname: str = None,
    ):
        """
        Updates and saves the profile for a specific user in a group.
        Enforces a limit of 100 users per group by removing the least recently active ones.
        """
        key = f"{adapter_name}+{group_id}"
        if key not in self.group_user_profiles:
            self.group_user_profiles[key] = {}

        # Update user data
        user_data = {
            "persona": persona[:10],  # Limit tags to 10
            "is_bot": is_bot,
            "last_active": last_active,
        }
        if nickname:
            user_data["nickname"] = nickname
        elif user_id in self.group_user_profiles[key]:
            # Keep existing nickname if not provided
            existing_nickname = self.group_user_profiles[key][user_id].get("nickname")
            if existing_nickname:
                user_data["nickname"] = existing_nickname

        self.group_user_profiles[key][user_id] = user_data

        # Enforce 100 users limit
        group_data = self.group_user_profiles[key]
        if len(group_data) > 100:
            # Sort by last_active, older first.
            # Assuming ISO format timestamp strings which are lexicographically sortable.
            # Users with missing last_active are treated as oldest ("").
            sorted_users = sorted(group_data.items(), key=lambda item: item[1].get("last_active", ""))

            # Remove oldest users until count is 100
            users_to_remove = sorted_users[: len(group_data) - 100]
            for uid, _ in users_to_remove:
                del group_data[uid]

        _write_data(_group_user_profile_file, self.group_user_profiles)
        logger.debug(f"User {user_id} profile updated in group {group_id} for adapter {adapter_name}.")


group_profile_memory: GroupProfileMemory = GroupProfileMemory()
personalization_memory: PersonalizationMemory = PersonalizationMemory()
group_user_memory: GroupUserMemory = GroupUserMemory()
