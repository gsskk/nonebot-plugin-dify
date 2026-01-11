import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, Any

from nonebot.log import logger


class DataValidationError(Exception):
    """Custom exception for data validation errors."""

    pass


class DataValidator:
    """
    Data validation and integrity checking utilities for private chat personalization.
    Provides validation for user profiles, personalizations, and chat messages.
    """

    # Maximum lengths for various data fields
    MAX_PROFILE_LENGTH = 5000
    MAX_PERSONALIZATION_LENGTH = 2000
    MAX_MESSAGE_LENGTH = 10000
    MAX_NICKNAME_LENGTH = 100
    MAX_USER_ID_LENGTH = 100
    MAX_ADAPTER_NAME_LENGTH = 50

    # Valid roles for chat messages
    VALID_ROLES = {"user", "assistant"}

    # Valid adapter name pattern (alphanumeric and common separators)
    ADAPTER_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

    # Valid user ID pattern (alphanumeric, underscores, hyphens, and some special chars)
    USER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_@.-]+$")

    @classmethod
    def validate_user_profile(cls, profile: str) -> str:
        """
        Validate and sanitize user profile data.

        Args:
            profile: User profile string to validate

        Returns:
            str: Validated and sanitized profile

        Raises:
            DataValidationError: If validation fails
        """
        if not isinstance(profile, str):
            raise DataValidationError(f"Profile must be a string, got {type(profile)}")

        # Remove null bytes and control characters except newlines and tabs
        sanitized = cls._sanitize_text(profile)

        # Check length
        if len(sanitized) > cls.MAX_PROFILE_LENGTH:
            logger.warning(f"Profile truncated from {len(sanitized)} to {cls.MAX_PROFILE_LENGTH} characters")
            sanitized = sanitized[: cls.MAX_PROFILE_LENGTH].rstrip()

        # Ensure it's not empty after sanitization
        if not sanitized.strip():
            raise DataValidationError("Profile cannot be empty after sanitization")

        return sanitized

    @classmethod
    def validate_user_personalization(cls, personalization: str) -> str:
        """
        Validate and sanitize user personalization data.

        Args:
            personalization: Personalization string to validate

        Returns:
            str: Validated and sanitized personalization

        Raises:
            DataValidationError: If validation fails
        """
        if not isinstance(personalization, str):
            raise DataValidationError(f"Personalization must be a string, got {type(personalization)}")

        # Remove null bytes and control characters except newlines and tabs
        sanitized = cls._sanitize_text(personalization)

        # Check length
        if len(sanitized) > cls.MAX_PERSONALIZATION_LENGTH:
            logger.warning(
                f"Personalization truncated from {len(sanitized)} to {cls.MAX_PERSONALIZATION_LENGTH} characters"
            )
            sanitized = sanitized[: cls.MAX_PERSONALIZATION_LENGTH].rstrip()

        # Ensure it's not empty after sanitization
        if not sanitized.strip():
            raise DataValidationError("Personalization cannot be empty after sanitization")

        return sanitized

    @classmethod
    def validate_adapter_name(cls, adapter_name: str) -> str:
        """
        Validate adapter name.

        Args:
            adapter_name: Adapter name to validate

        Returns:
            str: Validated adapter name

        Raises:
            DataValidationError: If validation fails
        """
        if not isinstance(adapter_name, str):
            raise DataValidationError(f"Adapter name must be a string, got {type(adapter_name)}")

        adapter_name = adapter_name.strip()

        if not adapter_name:
            raise DataValidationError("Adapter name cannot be empty")

        if len(adapter_name) > cls.MAX_ADAPTER_NAME_LENGTH:
            raise DataValidationError(f"Adapter name too long: {len(adapter_name)} > {cls.MAX_ADAPTER_NAME_LENGTH}")

        if not cls.ADAPTER_NAME_PATTERN.match(adapter_name):
            raise DataValidationError(f"Invalid adapter name format: {adapter_name}")

        return adapter_name.lower()

    @classmethod
    def validate_user_id(cls, user_id: str) -> str:
        """
        Validate user ID.

        Args:
            user_id: User ID to validate

        Returns:
            str: Validated user ID

        Raises:
            DataValidationError: If validation fails
        """
        if not isinstance(user_id, str):
            raise DataValidationError(f"User ID must be a string, got {type(user_id)}")

        user_id = user_id.strip()

        if not user_id:
            raise DataValidationError("User ID cannot be empty")

        if len(user_id) > cls.MAX_USER_ID_LENGTH:
            raise DataValidationError(f"User ID too long: {len(user_id)} > {cls.MAX_USER_ID_LENGTH}")

        if not cls.USER_ID_PATTERN.match(user_id):
            raise DataValidationError(f"Invalid user ID format: {user_id}")

        return user_id

    @classmethod
    def validate_message_data(cls, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate chat message data structure.

        Args:
            message_data: Message data dictionary to validate

        Returns:
            Dict[str, Any]: Validated message data

        Raises:
            DataValidationError: If validation fails
        """
        if not isinstance(message_data, dict):
            raise DataValidationError(f"Message data must be a dictionary, got {type(message_data)}")

        required_fields = {"timestamp", "role", "user_id", "nickname", "message"}
        missing_fields = required_fields - set(message_data.keys())
        if missing_fields:
            raise DataValidationError(f"Missing required fields: {missing_fields}")

        validated_data = {}

        # Validate timestamp
        timestamp = message_data["timestamp"]
        if not isinstance(timestamp, str):
            raise DataValidationError(f"Timestamp must be a string, got {type(timestamp)}")

        try:
            # Try to parse timestamp to ensure it's valid
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            validated_data["timestamp"] = timestamp
        except ValueError as e:
            raise DataValidationError(f"Invalid timestamp format: {timestamp}, error: {e}")

        # Validate role
        role = message_data["role"]
        if not isinstance(role, str):
            raise DataValidationError(f"Role must be a string, got {type(role)}")

        if role not in cls.VALID_ROLES:
            raise DataValidationError(f"Invalid role: {role}, must be one of {cls.VALID_ROLES}")

        validated_data["role"] = role

        # Validate user_id
        validated_data["user_id"] = cls.validate_user_id(message_data["user_id"])

        # Validate nickname
        nickname = message_data["nickname"]
        if not isinstance(nickname, str):
            raise DataValidationError(f"Nickname must be a string, got {type(nickname)}")

        nickname = cls._sanitize_text(nickname)
        if len(nickname) > cls.MAX_NICKNAME_LENGTH:
            nickname = nickname[: cls.MAX_NICKNAME_LENGTH].rstrip()

        if not nickname.strip():
            nickname = "Unknown"

        validated_data["nickname"] = nickname

        # Validate message
        message = message_data["message"]
        if not isinstance(message, str):
            raise DataValidationError(f"Message must be a string, got {type(message)}")

        message = cls._sanitize_text(message)
        if len(message) > cls.MAX_MESSAGE_LENGTH:
            logger.warning(f"Message truncated from {len(message)} to {cls.MAX_MESSAGE_LENGTH} characters")
            message = message[: cls.MAX_MESSAGE_LENGTH].rstrip()

        if not message.strip():
            raise DataValidationError("Message cannot be empty after sanitization")

        validated_data["message"] = message

        return validated_data

    @classmethod
    def validate_json_file(cls, file_path: Path) -> Tuple[bool, Optional[str]]:
        """
        Validate JSON file integrity.

        Args:
            file_path: Path to JSON file to validate

        Returns:
            Tuple[bool, Optional[str]]: (is_valid, error_message)
        """
        if not file_path.exists():
            return True, None  # Non-existent files are considered valid (will be created)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()

            if not content:
                return True, None  # Empty files are valid (will be initialized)

            # Try to parse JSON
            data = json.loads(content)

            # Validate that it's a dictionary for profile/personalization files
            if not isinstance(data, dict):
                return False, f"JSON file must contain a dictionary, got {type(data)}"

            # Validate keys format for user data files
            for key in data.keys():
                if not isinstance(key, str):
                    return False, f"All keys must be strings, found {type(key)}: {key}"

                # Check if it's a user data key (adapter+private+user_id format)
                if "+private+" in key:
                    parts = key.split("+private+")
                    if len(parts) != 2:
                        return False, f"Invalid user data key format: {key}"

                    try:
                        cls.validate_adapter_name(parts[0])
                        cls.validate_user_id(parts[1])
                    except DataValidationError as e:
                        return False, f"Invalid key format '{key}': {e}"

            return True, None

        except json.JSONDecodeError as e:
            return False, f"Invalid JSON format: {e}"
        except Exception as e:
            return False, f"Error validating file: {e}"

    @classmethod
    def validate_jsonl_file(cls, file_path: Path) -> Tuple[bool, Optional[str], int]:
        """
        Validate JSONL (JSON Lines) file integrity.

        Args:
            file_path: Path to JSONL file to validate

        Returns:
            Tuple[bool, Optional[str], int]: (is_valid, error_message, valid_lines_count)
        """
        if not file_path.exists():
            return True, None, 0

        try:
            valid_lines = 0
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue  # Skip empty lines

                    try:
                        # Parse JSON line
                        data = json.loads(line)

                        # Validate message data structure
                        cls.validate_message_data(data)
                        valid_lines += 1

                    except json.JSONDecodeError as e:
                        return False, f"Invalid JSON on line {line_num}: {e}", valid_lines
                    except DataValidationError as e:
                        return False, f"Invalid message data on line {line_num}: {e}", valid_lines

            return True, None, valid_lines

        except Exception as e:
            return False, f"Error validating JSONL file: {e}", 0

    @classmethod
    def repair_json_file(cls, file_path: Path, backup: bool = True) -> bool:
        """
        Attempt to repair a corrupted JSON file.

        Args:
            file_path: Path to JSON file to repair
            backup: Whether to create a backup before repair

        Returns:
            bool: True if repair was successful
        """
        if not file_path.exists():
            return True  # Nothing to repair

        try:
            # Create backup if requested
            if backup:
                backup_path = file_path.with_suffix(f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                backup_path.write_bytes(file_path.read_bytes())
                logger.info(f"Created backup: {backup_path}")

            # Try to read and parse the file
            content = file_path.read_text(encoding="utf-8").strip()

            if not content:
                # Empty file - initialize with empty dict
                file_path.write_text("{}", encoding="utf-8")
                logger.info(f"Initialized empty JSON file: {file_path}")
                return True

            # Try to parse JSON
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    # File is valid, just rewrite it cleanly
                    file_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
                    logger.info(f"Cleaned up JSON file: {file_path}")
                    return True
                else:
                    # Not a dict, reset to empty dict
                    file_path.write_text("{}", encoding="utf-8")
                    logger.warning(f"Reset non-dict JSON file to empty dict: {file_path}")
                    return True
            except json.JSONDecodeError:
                # Try to salvage what we can
                logger.warning(f"Attempting to salvage corrupted JSON file: {file_path}")

                # Reset to empty dict as last resort
                file_path.write_text("{}", encoding="utf-8")
                logger.warning(f"Reset corrupted JSON file to empty dict: {file_path}")
                return True

        except Exception as e:
            logger.error(f"Failed to repair JSON file {file_path}: {e}")
            return False

    @classmethod
    def repair_jsonl_file(cls, file_path: Path, backup: bool = True) -> Tuple[bool, int, int]:
        """
        Attempt to repair a corrupted JSONL file by removing invalid lines.

        Args:
            file_path: Path to JSONL file to repair
            backup: Whether to create a backup before repair

        Returns:
            Tuple[bool, int, int]: (success, original_lines, valid_lines)
        """
        if not file_path.exists():
            return True, 0, 0

        try:
            # Create backup if requested
            if backup:
                backup_path = file_path.with_suffix(f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
                backup_path.write_bytes(file_path.read_bytes())
                logger.info(f"Created backup: {backup_path}")

            # Read and validate lines
            valid_lines = []
            original_lines = 0

            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    original_lines += 1
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        # Parse and validate JSON line
                        data = json.loads(line)
                        validated_data = cls.validate_message_data(data)
                        valid_lines.append(json.dumps(validated_data, ensure_ascii=False))
                    except (json.JSONDecodeError, DataValidationError) as e:
                        logger.warning(f"Removing invalid line {line_num} from {file_path}: {e}")
                        continue

            # Write back valid lines
            with open(file_path, "w", encoding="utf-8") as f:
                for line in valid_lines:
                    f.write(line + "\n")

            logger.info(f"Repaired JSONL file {file_path}: {len(valid_lines)}/{original_lines} lines kept")
            return True, original_lines, len(valid_lines)

        except Exception as e:
            logger.error(f"Failed to repair JSONL file {file_path}: {e}")
            return False, 0, 0

    @classmethod
    def _sanitize_text(cls, text: str) -> str:
        """
        Sanitize text by removing null bytes and control characters.
        Preserves newlines, tabs, and carriage returns.

        Args:
            text: Text to sanitize

        Returns:
            str: Sanitized text
        """
        # Remove null bytes
        text = text.replace("\x00", "")

        # Remove control characters except \n, \r, \t
        sanitized = ""
        for char in text:
            code = ord(char)
            if code >= 32 or char in "\n\r\t":
                sanitized += char

        return sanitized
