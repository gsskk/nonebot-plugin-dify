import json
import asyncio
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Literal

import nonebot_plugin_localstore as store
from nonebot.log import logger

from ..config import config
from .data_validator import DataValidator, DataValidationError

# Use an asyncio Lock to prevent concurrent file write conflicts
_file_lock = asyncio.Lock()


def _get_private_log_dir(adapter_name: str) -> Path:
    """Get the base directory for private chat logs"""
    return store.get_data_dir("nonebot_plugin_dify") / "private_chat_logs" / adapter_name


def _get_private_log_file_path(adapter_name: str, user_id: str, date: datetime) -> Path:
    """Build log file path based on user ID, adapter name and date"""
    date_str = date.strftime("%Y-%m-%d")
    log_dir = _get_private_log_dir(adapter_name) / date_str
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{user_id}.jsonl"


def _clean_message_for_private_recording(message: str) -> str:
    """
    Clean and preprocess message for private chat recording.

    - Truncate long messages
    - Compress repeated content
    - Desensitize data (if enabled)
    - Normalize whitespace and punctuation
    """
    # 1. Normalize whitespace characters
    cleaned_message = re.sub(r"\s+", " ", message).strip()

    # 2. Compress repeated content
    def compress_repeats(match):
        repeated_str = match.group(1)
        count = len(match.group(0)) // len(repeated_str)
        return f"{repeated_str}*{count}"

    cleaned_message = re.sub(r"(.{2,})\1{2,}", compress_repeats, cleaned_message)

    # 3. Compress punctuation marks
    cleaned_message = re.sub(r"([!?.,。！？，])\1+", r"\1", cleaned_message)

    # 4. Desensitization (if enabled)
    if config.message_desensitization_enable:
        # Phone numbers
        cleaned_message = re.sub(r"1[3-9]\d{9}", "[PHONE]", cleaned_message)
        # Email addresses
        cleaned_message = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", cleaned_message)
        # URLs
        cleaned_message = re.sub(r"https?://[^\s]+", "[URL]", cleaned_message)

    # 5. Truncate message
    max_length = max(config.message_max_length, 3)
    if len(cleaned_message) > max_length:
        cleaned_message = cleaned_message[: max_length - 3] + "..."

    return cleaned_message


async def record_private_message(
    adapter_name: str, user_id: str, nickname: str, message: str, role: Literal["user", "assistant"]
) -> None:
    """
    Asynchronously record a single private chat message to local file.
    Log files are rotated daily.

    Args:
        adapter_name: The name of the chat adapter (e.g., 'telegram', 'discord')
        user_id: The unique user identifier
        nickname: The display name of the user
        message: The message content
        role: Either 'user' or 'assistant'
    """
    try:
        # Validate input parameters
        try:
            validated_adapter = DataValidator.validate_adapter_name(adapter_name)
            validated_user_id = DataValidator.validate_user_id(user_id)
        except DataValidationError as e:
            logger.error(f"Invalid parameters for message recording: {e}")
            return

        now = datetime.now()

        # Clean the message for recording
        try:
            cleaned_message = _clean_message_for_private_recording(message)
        except Exception as e:
            logger.warning(f"Failed to clean message for recording: {e}")
            cleaned_message = message[: config.message_max_length]

        log_entry = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "role": role,
            "user_id": validated_user_id,
            "nickname": nickname,
            "message": cleaned_message,
        }

        # Validate the complete log entry
        try:
            validated_entry = DataValidator.validate_message_data(log_entry)
        except DataValidationError as e:
            logger.error(f"Message data validation failed: {e}")
            return

        file_path = _get_private_log_file_path(validated_adapter, validated_user_id, now)

        async with _file_lock:
            try:
                # Ensure directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)

                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(validated_entry, ensure_ascii=False) + "\n")

                logger.debug(f"Recorded private message for user {user_id} on {adapter_name}")

            except IOError as e:
                logger.error(f"Unable to write private chat log to {file_path}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error writing to file: {e}")

    except Exception as e:
        logger.error(f"Unexpected error recording private message: {e}")


async def get_recent_private_messages(adapter_name: str, user_id: str, limit: int = 20) -> List[Dict]:
    """
    Get recent private chat messages for a user.
    Will read from today's and yesterday's logs if needed.

    Args:
        adapter_name: The name of the chat adapter
        user_id: The unique user identifier
        limit: Maximum number of messages to retrieve

    Returns:
        List[Dict]: List of message dictionaries in chronological order
    """
    if limit <= 0:
        return []

    try:
        # Validate input parameters
        try:
            validated_adapter = DataValidator.validate_adapter_name(adapter_name)
            validated_user_id = DataValidator.validate_user_id(user_id)
        except DataValidationError as e:
            logger.error(f"Invalid parameters for get_recent_private_messages: {e}")
            return []

        messages = []
        today = datetime.now()

        # Try to read from today's log file
        today_file = _get_private_log_file_path(validated_adapter, validated_user_id, today)
        try:
            today_messages = await _read_messages_from_file(today_file, limit)
            messages.extend(today_messages)
        except Exception as e:
            logger.error(f"Failed to read today's messages: {e}")

        # If we need more messages, try yesterday's log file
        if len(messages) < limit:
            yesterday = today - timedelta(days=1)
            yesterday_file = _get_private_log_file_path(validated_adapter, validated_user_id, yesterday)
            remaining_limit = limit - len(messages)
            try:
                yesterday_messages = await _read_messages_from_file(yesterday_file, remaining_limit)
                messages.extend(yesterday_messages)
            except Exception as e:
                logger.error(f"Failed to read yesterday's messages: {e}")

        # Messages are currently in reverse chronological order, restore to forward order
        result = list(reversed(messages[:limit]))

        return result

    except Exception as e:
        logger.error(f"Unexpected error getting recent messages: {e}")
        return []


async def _read_messages_from_file(file_path: Path, limit: int) -> List[Dict]:
    """
    Read and validate messages from a JSONL file.

    Args:
        file_path: Path to the JSONL file
        limit: Maximum number of messages to read

    Returns:
        List[Dict]: List of validated message dictionaries
    """
    if not file_path.exists():
        return []

    # Validate file integrity first
    is_valid, error_msg, valid_count = DataValidator.validate_jsonl_file(file_path)
    if not is_valid:
        logger.warning(f"JSONL file validation failed for {file_path}: {error_msg}")
        # Attempt to repair the file
        success, original_lines, repaired_lines = DataValidator.repair_jsonl_file(file_path, backup=True)
        if success:
            logger.info(f"Successfully repaired JSONL file {file_path}: {repaired_lines}/{original_lines} lines kept")
        else:
            logger.error(f"Failed to repair JSONL file: {file_path}")
            return []

    messages = []
    async with _file_lock:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    if len(messages) >= limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        # Validate message data
                        validated_data = DataValidator.validate_message_data(data)
                        messages.append(validated_data)
                    except (json.JSONDecodeError, DataValidationError) as e:
                        logger.warning(f"Skipping invalid message in {file_path}: {e}")
                        continue
        except IOError as e:
            logger.error(f"Error reading private chat log {file_path}: {e}")

    return messages


async def get_messages_since_private(adapter_name: str, user_id: str, start_time: datetime) -> List[Dict]:
    """
    Get all private chat messages since a specific time point.
    Will check today's and yesterday's log files.

    Args:
        adapter_name: The name of the chat adapter
        user_id: The unique user identifier
        start_time: The starting time point

    Returns:
        List[Dict]: List of message dictionaries in chronological order
    """
    try:
        # Validate input parameters
        validated_adapter = DataValidator.validate_adapter_name(adapter_name)
        validated_user_id = DataValidator.validate_user_id(user_id)
    except DataValidationError as e:
        logger.error(f"Invalid parameters for get_messages_since_private: {e}")
        return []

    messages = []
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    log_files_to_check = []
    # If start time is yesterday or earlier, check yesterday's log
    if start_time.date() <= yesterday.date():
        log_files_to_check.append(_get_private_log_file_path(validated_adapter, validated_user_id, yesterday))
    # Always check today's log
    log_files_to_check.append(_get_private_log_file_path(validated_adapter, validated_user_id, today))

    for file_path in log_files_to_check:
        if not file_path.exists():
            continue

        # Validate file integrity first
        is_valid, error_msg, valid_count = DataValidator.validate_jsonl_file(file_path)
        if not is_valid:
            logger.warning(f"JSONL file validation failed for {file_path}: {error_msg}")
            # Attempt to repair the file
            success, original_lines, repaired_lines = DataValidator.repair_jsonl_file(file_path, backup=True)
            if not success:
                logger.error(f"Failed to repair JSONL file: {file_path}, skipping")
                continue

        async with _file_lock:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                            # Validate message data
                            validated_msg = DataValidator.validate_message_data(msg)
                            msg_time = datetime.fromisoformat(validated_msg["timestamp"])
                            if msg_time >= start_time:
                                messages.append(validated_msg)
                        except (json.JSONDecodeError, DataValidationError, KeyError, ValueError) as e:
                            logger.warning(f"Skipping invalid message in {file_path}: {e}")
                            continue
            except IOError as e:
                logger.error(f"Error reading private chat log {file_path}: {e}")

    # Sort by timestamp to ensure messages are in chronological order
    messages.sort(key=lambda m: m["timestamp"])
    return messages


def clear_user_data(adapter_name: str, user_id: str) -> None:
    """
    Clear all private chat data for a specific user.
    This removes all log files for the user across all dates.

    Args:
        adapter_name: The name of the chat adapter
        user_id: The unique user identifier
    """
    try:
        # Validate input parameters
        try:
            validated_adapter = DataValidator.validate_adapter_name(adapter_name)
            validated_user_id = DataValidator.validate_user_id(user_id)
        except DataValidationError as e:
            logger.error(f"Invalid parameters for clear_user_data: {e}")
            return

        log_dir = _get_private_log_dir(validated_adapter)
        if not log_dir.exists():
            logger.debug(f"No log directory exists for {adapter_name}, nothing to clear")
            return

        deleted_files = 0
        failed_deletions = 0

        try:
            # Search for all log files for this user across all date directories
            for date_dir in log_dir.iterdir():
                if date_dir.is_dir():
                    user_log_file = date_dir / f"{validated_user_id}.jsonl"
                    if user_log_file.exists():
                        try:
                            user_log_file.unlink()
                            deleted_files += 1
                            logger.debug(f"Deleted private chat log: {user_log_file}")
                        except Exception as e:
                            failed_deletions += 1
                            logger.error(f"Failed to delete log file {user_log_file}: {e}")

            # Log the operation result
            if deleted_files > 0:
                logger.info(f"Cleared {deleted_files} private chat log files for user {user_id} on {adapter_name}")

            if failed_deletions > 0:
                logger.error(f"Failed to delete {failed_deletions} log files during user data clearing")

        except Exception as e:
            logger.error(f"Error during user data clearing process: {e}")

    except Exception as e:
        logger.error(f"Unexpected error clearing user data: {e}")


def limit_private_chat_history_length(messages: List[Dict], max_length: int) -> str:
    """
    Limit the total length of private chat history for analysis.
    Prioritizes keeping the most recent messages.

    Args:
        messages: List of message dictionaries
        max_length: Maximum total character length

    Returns:
        str: Formatted chat history string within the length limit
    """
    if not messages:
        return ""

    result_lines = []
    total_length = 0

    for msg in reversed(messages):  # Start from most recent
        # Format message line
        timestamp = msg.get("timestamp", "")
        role = msg.get("role", "unknown")
        nickname = msg.get("nickname", "Unknown")
        message = msg.get("message", "")

        line = f"[{timestamp}] {role.upper()} {nickname}: {message}"
        line_length = len(line) + 1  # +1 for newline

        if total_length + line_length <= max_length:
            result_lines.insert(0, line)  # Insert at beginning to maintain chronological order
            total_length += line_length
        else:
            break

    return "\n".join(result_lines)
