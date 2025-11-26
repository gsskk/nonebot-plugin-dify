import json
import threading
from pathlib import Path
from typing import Dict

import nonebot_plugin_localstore as store
from nonebot.log import logger

from .data_validator import DataValidator, DataValidationError

_user_profile_file: Path = store.get_data_file("nonebot_plugin_dify", "user_profiles.json")
_user_personalization_file: Path = store.get_data_file("nonebot_plugin_dify", "user_personalizations.json")

# Thread locks for safe concurrent access
_profile_lock = threading.Lock()
_personalization_lock = threading.Lock()


def _read_data(file_path: Path) -> Dict[str, str]:
    """Reads data from a JSON file with validation and repair."""
    if not file_path.exists():
        return {}

    # Validate file integrity first
    is_valid, error_msg = DataValidator.validate_json_file(file_path)
    if not is_valid:
        logger.warning(f"JSON file validation failed for {file_path}: {error_msg}")
        # Attempt to repair the file
        if DataValidator.repair_json_file(file_path, backup=True):
            logger.info(f"Successfully repaired JSON file: {file_path}")
        else:
            logger.error(f"Failed to repair JSON file: {file_path}, returning empty dict")
            return {}

    try:
        data = json.loads(file_path.read_text("utf-8"))
        if not isinstance(data, dict):
            logger.warning(f"JSON file {file_path} does not contain a dictionary, returning empty dict")
            return {}
        return data
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to decode JSON from {file_path}: {e}, returning empty dict.")
        return {}


def _write_data(file_path: Path, data: Dict[str, str]):
    """Writes data to a JSON file."""
    file_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")


class UserProfileMemory:
    """
    Manages persistent storage for individual user profiles.
    User profiles are summaries of a user's chat history and preferences, generated periodically
    to give the AI context about the user's communication style and interests.
    """

    def __init__(self):
        """Initializes the memory by loading existing user profiles from a file."""
        with _profile_lock:
            self.user_profiles: Dict[str, str] = _read_data(_user_profile_file)

    def get(self, adapter_name: str, user_id: str) -> str:
        """Retrieves the profile for a specific user."""
        try:
            validated_adapter = DataValidator.validate_adapter_name(adapter_name)
            validated_user_id = DataValidator.validate_user_id(user_id)
            key = f"{validated_adapter}+private+{validated_user_id}"
            with _profile_lock:
                return self.user_profiles.get(key, "")
        except DataValidationError as e:
            logger.error(f"Invalid parameters for get profile: {e}")
            return ""

    def set(self, adapter_name: str, user_id: str, profile: str):
        """Updates and saves the profile for a specific user."""
        try:
            validated_adapter = DataValidator.validate_adapter_name(adapter_name)
            validated_user_id = DataValidator.validate_user_id(user_id)
            validated_profile = DataValidator.validate_user_profile(profile)

            key = f"{validated_adapter}+private+{validated_user_id}"
            with _profile_lock:
                self.user_profiles[key] = validated_profile
                _write_data(_user_profile_file, self.user_profiles)
            logger.debug(f"User {user_id} profile updated and saved for adapter {adapter_name}.")
        except DataValidationError as e:
            logger.error(f"Failed to set user profile due to validation error: {e}")
            raise

    def delete(self, adapter_name: str, user_id: str):
        """Deletes the profile for a specific user."""
        try:
            validated_adapter = DataValidator.validate_adapter_name(adapter_name)
            validated_user_id = DataValidator.validate_user_id(user_id)
            key = f"{validated_adapter}+private+{validated_user_id}"
            with _profile_lock:
                if key in self.user_profiles:
                    del self.user_profiles[key]
                    _write_data(_user_profile_file, self.user_profiles)
                    logger.debug(f"User {user_id} profile deleted for adapter {adapter_name}.")
        except DataValidationError as e:
            logger.error(f"Invalid parameters for delete profile: {e}")


class UserPersonalizationMemory:
    """
    Manages persistent storage for individual user personalizations.
    This data is used to tailor the AI's behavior to a specific user in private chats.
    """

    def __init__(self):
        """Initializes the memory by loading existing personalizations from a file."""
        with _personalization_lock:
            self.user_personalizations: Dict[str, str] = _read_data(_user_personalization_file)

    def get(self, adapter_name: str, user_id: str) -> str:
        """Retrieves the personalization for a specific user."""
        try:
            validated_adapter = DataValidator.validate_adapter_name(adapter_name)
            validated_user_id = DataValidator.validate_user_id(user_id)
            key = f"{validated_adapter}+private+{validated_user_id}"
            with _personalization_lock:
                return self.user_personalizations.get(key, "")
        except DataValidationError as e:
            logger.error(f"Invalid parameters for get personalization: {e}")
            return ""

    def set(self, adapter_name: str, user_id: str, personalization: str):
        """Updates and saves the personalization for a specific user."""
        try:
            validated_adapter = DataValidator.validate_adapter_name(adapter_name)
            validated_user_id = DataValidator.validate_user_id(user_id)
            validated_personalization = DataValidator.validate_user_personalization(personalization)

            key = f"{validated_adapter}+private+{validated_user_id}"
            with _personalization_lock:
                self.user_personalizations[key] = validated_personalization
                _write_data(_user_personalization_file, self.user_personalizations)
            logger.debug(f"User {user_id} personalization updated and saved for adapter {adapter_name}.")
        except DataValidationError as e:
            logger.error(f"Failed to set user personalization due to validation error: {e}")
            raise

    def delete(self, adapter_name: str, user_id: str):
        """Deletes the personalization for a specific user."""
        try:
            validated_adapter = DataValidator.validate_adapter_name(adapter_name)
            validated_user_id = DataValidator.validate_user_id(user_id)
            key = f"{validated_adapter}+private+{validated_user_id}"
            with _personalization_lock:
                if key in self.user_personalizations:
                    del self.user_personalizations[key]
                    _write_data(_user_personalization_file, self.user_personalizations)
                    logger.debug(f"User {user_id} personalization deleted for adapter {adapter_name}.")
        except DataValidationError as e:
            logger.error(f"Invalid parameters for delete personalization: {e}")


# Global instances
user_profile_memory: UserProfileMemory = UserProfileMemory()
user_personalization_memory: UserPersonalizationMemory = UserPersonalizationMemory()
