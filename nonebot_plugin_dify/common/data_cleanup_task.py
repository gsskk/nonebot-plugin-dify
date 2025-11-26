import json
from datetime import datetime, timedelta
from typing import List, Tuple

import nonebot_plugin_localstore as store
from nonebot.log import logger

from ..config import config
from .user_data_store import user_profile_memory, user_personalization_memory
from .private_chat_recorder import _get_private_log_dir


async def run_data_cleanup_job():
    """
    Execute scheduled data cleanup task for expired user data.
    Removes user profiles, personalizations, and chat logs older than retention period.
    """
    logger.info("Starting scheduled data cleanup task...")

    if not config.private_personalization_enable:
        logger.info("Private personalization is disabled, skipping data cleanup")
        return

    if config.private_data_retention_days <= 0:
        logger.info("Data retention is set to unlimited, skipping cleanup")
        return

    retention_days = config.private_data_retention_days
    cutoff_date = datetime.now() - timedelta(days=retention_days)

    logger.info(f"Cleaning up data older than {retention_days} days (before {cutoff_date.strftime('%Y-%m-%d')})")

    cleanup_stats = {"chat_logs_cleaned": 0, "profiles_cleaned": 0, "personalizations_cleaned": 0, "errors": 0}

    try:
        # Clean up chat logs
        await _cleanup_chat_logs(cutoff_date, cleanup_stats)

        # Clean up user profiles and personalizations
        await _cleanup_user_data(cutoff_date, cleanup_stats)

        logger.info(
            f"Data cleanup completed. "
            f"Chat logs: {cleanup_stats['chat_logs_cleaned']}, "
            f"Profiles: {cleanup_stats['profiles_cleaned']}, "
            f"Personalizations: {cleanup_stats['personalizations_cleaned']}, "
            f"Errors: {cleanup_stats['errors']}"
        )

    except Exception as e:
        logger.error(f"Error during data cleanup task: {e}")
        cleanup_stats["errors"] += 1


async def _cleanup_chat_logs(cutoff_date: datetime, stats: dict):
    """Clean up chat log files older than the cutoff date."""
    base_log_dir = store.get_data_dir("nonebot_plugin_dify") / "private_chat_logs"

    if not base_log_dir.exists():
        logger.debug("No private chat logs directory found, skipping chat log cleanup")
        return

    try:
        # Iterate through adapter directories
        for adapter_dir in base_log_dir.iterdir():
            if not adapter_dir.is_dir():
                continue

            adapter_name = adapter_dir.name
            logger.debug(f"Cleaning chat logs for adapter: {adapter_name}")

            # Iterate through date directories
            for date_dir in adapter_dir.iterdir():
                if not date_dir.is_dir():
                    continue

                try:
                    # Parse date from directory name (YYYY-MM-DD format)
                    dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")

                    if dir_date < cutoff_date:
                        # Remove all log files in this date directory
                        files_removed = 0
                        for log_file in date_dir.glob("*.jsonl"):
                            try:
                                log_file.unlink()
                                files_removed += 1
                                logger.debug(f"Removed chat log: {log_file}")
                            except Exception as e:
                                logger.error(f"Error removing chat log {log_file}: {e}")
                                stats["errors"] += 1

                        # Remove empty date directory
                        try:
                            if not any(date_dir.iterdir()):
                                date_dir.rmdir()
                                logger.debug(f"Removed empty date directory: {date_dir}")
                        except Exception as e:
                            logger.error(f"Error removing date directory {date_dir}: {e}")
                            stats["errors"] += 1

                        stats["chat_logs_cleaned"] += files_removed
                        logger.debug(f"Cleaned {files_removed} chat log files from {date_dir.name}")

                except ValueError:
                    logger.warning(f"Invalid date directory name: {date_dir.name}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing date directory {date_dir}: {e}")
                    stats["errors"] += 1

    except Exception as e:
        logger.error(f"Error during chat log cleanup: {e}")
        stats["errors"] += 1


async def _cleanup_user_data(cutoff_date: datetime, stats: dict):
    """Clean up user profiles and personalizations that haven't been updated recently."""
    try:
        # Get list of users to potentially clean up
        users_to_check = await _get_inactive_users(cutoff_date)

        for adapter_name, user_id in users_to_check:
            try:
                # Check if user has any recent activity
                has_recent_activity = await _user_has_recent_activity(adapter_name, user_id, cutoff_date)

                if not has_recent_activity:
                    # Remove user profile and personalization
                    user_profile_memory.delete(adapter_name, user_id)
                    user_personalization_memory.delete(adapter_name, user_id)

                    stats["profiles_cleaned"] += 1
                    stats["personalizations_cleaned"] += 1

                    logger.debug(f"Cleaned user data for {adapter_name}+private+{user_id}")

            except Exception as e:
                logger.error(f"Error cleaning user data for {adapter_name}+{user_id}: {e}")
                stats["errors"] += 1

    except Exception as e:
        logger.error(f"Error during user data cleanup: {e}")
        stats["errors"] += 1


async def _get_inactive_users(cutoff_date: datetime) -> List[Tuple[str, str]]:
    """Get list of users who might need cleanup based on profile/personalization data."""
    users_to_check = []

    try:
        # Check user profiles
        for key in user_profile_memory.user_profiles.keys():
            if "+private+" in key:
                parts = key.split("+private+")
                if len(parts) == 2:
                    adapter_name, user_id = parts
                    users_to_check.append((adapter_name, user_id))

        # Check user personalizations (might have different users)
        for key in user_personalization_memory.user_personalizations.keys():
            if "+private+" in key:
                parts = key.split("+private+")
                if len(parts) == 2:
                    adapter_name, user_id = parts
                    if (adapter_name, user_id) not in users_to_check:
                        users_to_check.append((adapter_name, user_id))

    except Exception as e:
        logger.error(f"Error getting inactive users list: {e}")

    return users_to_check


async def _user_has_recent_activity(adapter_name: str, user_id: str, cutoff_date: datetime) -> bool:
    """Check if a user has any chat activity after the cutoff date."""
    try:
        log_dir = _get_private_log_dir(adapter_name)
        if not log_dir.exists():
            return False

        # Check recent date directories for user activity
        current_date = datetime.now()
        check_date = cutoff_date

        while check_date <= current_date:
            date_str = check_date.strftime("%Y-%m-%d")
            date_dir = log_dir / date_str
            user_log_file = date_dir / f"{user_id}.jsonl"

            if user_log_file.exists():
                # Check if file has any content after cutoff date
                try:
                    with open(user_log_file, "r", encoding="utf-8") as f:
                        for line in f:
                            try:
                                msg = json.loads(line.strip())
                                msg_time = datetime.fromisoformat(msg["timestamp"])
                                if msg_time >= cutoff_date:
                                    return True
                            except (json.JSONDecodeError, KeyError, ValueError):
                                continue
                except Exception as e:
                    logger.error(f"Error reading user log file {user_log_file}: {e}")

            check_date += timedelta(days=1)

        return False

    except Exception as e:
        logger.error(f"Error checking user activity for {adapter_name}+{user_id}: {e}")
        return True  # Err on the side of caution - don't delete if we can't check


async def run_data_integrity_check():
    """
    Run data integrity checks on all user data files.
    This function validates and repairs corrupted data files.
    """
    logger.info("Starting data integrity check...")

    if not config.private_personalization_enable:
        logger.info("Private personalization is disabled, skipping integrity check")
        return

    integrity_stats = {
        "profiles_checked": 0,
        "profiles_repaired": 0,
        "personalizations_checked": 0,
        "personalizations_repaired": 0,
        "chat_logs_checked": 0,
        "chat_logs_repaired": 0,
        "errors": 0,
    }

    try:
        # Check user profile and personalization files
        await _check_user_data_files(integrity_stats)

        # Check chat log files
        await _check_chat_log_files(integrity_stats)

        logger.info(
            f"Data integrity check completed. "
            f"Profiles: {integrity_stats['profiles_checked']} checked, {integrity_stats['profiles_repaired']} repaired. "
            f"Personalizations: {integrity_stats['personalizations_checked']} checked, {integrity_stats['personalizations_repaired']} repaired. "
            f"Chat logs: {integrity_stats['chat_logs_checked']} checked, {integrity_stats['chat_logs_repaired']} repaired. "
            f"Errors: {integrity_stats['errors']}"
        )

    except Exception as e:
        logger.error(f"Error during data integrity check: {e}")
        integrity_stats["errors"] += 1


async def _check_user_data_files(stats: dict):
    """Check integrity of user profile and personalization files."""
    from .data_validator import DataValidator

    try:
        # Check user profiles file
        profile_file = store.get_data_file("nonebot_plugin_dify", "user_profiles.json")
        if profile_file.exists():
            stats["profiles_checked"] += 1
            is_valid, error_msg = DataValidator.validate_json_file(profile_file)
            if not is_valid:
                logger.warning(f"User profiles file validation failed: {error_msg}")
                if DataValidator.repair_json_file(profile_file, backup=True):
                    stats["profiles_repaired"] += 1
                    logger.info("Successfully repaired user profiles file")
                else:
                    logger.error("Failed to repair user profiles file")
                    stats["errors"] += 1

        # Check user personalizations file
        personalization_file = store.get_data_file("nonebot_plugin_dify", "user_personalizations.json")
        if personalization_file.exists():
            stats["personalizations_checked"] += 1
            is_valid, error_msg = DataValidator.validate_json_file(personalization_file)
            if not is_valid:
                logger.warning(f"User personalizations file validation failed: {error_msg}")
                if DataValidator.repair_json_file(personalization_file, backup=True):
                    stats["personalizations_repaired"] += 1
                    logger.info("Successfully repaired user personalizations file")
                else:
                    logger.error("Failed to repair user personalizations file")
                    stats["errors"] += 1

    except Exception as e:
        logger.error(f"Error checking user data files: {e}")
        stats["errors"] += 1


async def _check_chat_log_files(stats: dict):
    """Check integrity of chat log files."""
    from .data_validator import DataValidator

    try:
        base_log_dir = store.get_data_dir("nonebot_plugin_dify") / "private_chat_logs"

        if not base_log_dir.exists():
            logger.debug("No private chat logs directory found, skipping chat log integrity check")
            return

        # Iterate through adapter directories
        for adapter_dir in base_log_dir.iterdir():
            if not adapter_dir.is_dir():
                continue

            # Iterate through date directories
            for date_dir in adapter_dir.iterdir():
                if not date_dir.is_dir():
                    continue

                # Check all JSONL files in this date directory
                for log_file in date_dir.glob("*.jsonl"):
                    stats["chat_logs_checked"] += 1

                    is_valid, error_msg, valid_count = DataValidator.validate_jsonl_file(log_file)
                    if not is_valid:
                        logger.warning(f"Chat log file validation failed for {log_file}: {error_msg}")
                        success, original_lines, repaired_lines = DataValidator.repair_jsonl_file(log_file, backup=True)
                        if success:
                            stats["chat_logs_repaired"] += 1
                            logger.info(
                                f"Successfully repaired chat log {log_file}: {repaired_lines}/{original_lines} lines kept"
                            )
                        else:
                            logger.error(f"Failed to repair chat log file: {log_file}")
                            stats["errors"] += 1

    except Exception as e:
        logger.error(f"Error checking chat log files: {e}")
        stats["errors"] += 1
