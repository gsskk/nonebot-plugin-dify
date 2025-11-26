from datetime import datetime, timedelta
from typing import List, Tuple

from nonebot.log import logger

from ..config import config
from .user_memory_manager import UserMemoryManager
from .private_chat_manager import get_all_personalization_statuses
from .private_chat_recorder import get_messages_since_private


async def run_private_profiling_job() -> None:
    """
    Execute scheduled task for private chat user profile analysis and updates.
    This task processes all users who have opted-in to personalization and have
    sufficient message history for analysis.
    """
    logger.info("开始执行私聊用户画像和个性化要求生成任务...")

    # Check if private chat personalization is enabled
    if not config.private_personalization_enable:
        logger.info("私聊个性化功能未启用，跳过定时任务")
        return

    # Check if profiler workflow is configured
    if not config.profiler_workflow_api_key:
        logger.warning("未配置画像生成Dify Workflow，跳过定时任务")
        return

    # Get all users who have opted-in to personalization
    all_statuses = get_all_personalization_statuses()

    enabled_users = []
    for key, status in all_statuses.items():
        if status and "+private+" in key:
            parts = key.split("+")
            if len(parts) == 3:  # format: adapter+private+user_id
                adapter_name = parts[0]
                user_id = parts[2]
                enabled_users.append((adapter_name, user_id))

    if not enabled_users:
        logger.info("没有启用个性化功能的私聊用户，任务结束")
        return

    logger.info(f"找到 {len(enabled_users)} 个启用个性化功能的用户")

    # Filter users who have sufficient message history
    users_to_process = await _filter_users_with_sufficient_history(enabled_users)

    if not users_to_process:
        logger.info("没有用户满足最少消息数要求，任务结束")
        return

    logger.info(f"有 {len(users_to_process)} 个用户满足分析条件")

    # Process user profiles in batches to avoid overwhelming the API
    await process_user_profiles(users_to_process)

    logger.info("私聊用户画像和个性化要求生成任务完成")


async def _filter_users_with_sufficient_history(users: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """
    Filter users who have sufficient message history for analysis.

    Args:
        users: List of (adapter_name, user_id) tuples

    Returns:
        List of users who meet the minimum message requirement
    """
    users_to_process = []

    # Check messages from the past 24 hours (same as group chat analysis)
    start_time = datetime.now() - timedelta(hours=24)

    for adapter_name, user_id in users:
        try:
            # Get recent messages for this user
            recent_messages = await get_messages_since_private(adapter_name, user_id, start_time)

            # Count only user messages (not bot responses) for analysis threshold
            user_messages = [msg for msg in recent_messages if msg.get("role") == "user"]

            if len(user_messages) >= config.private_profiler_min_messages:
                users_to_process.append((adapter_name, user_id))
                logger.debug(f"用户 {adapter_name}+{user_id} 有 {len(user_messages)} 条消息，满足分析条件")
            else:
                logger.debug(
                    f"用户 {adapter_name}+{user_id} 只有 {len(user_messages)} 条消息，不满足最少 {config.private_profiler_min_messages} 条的要求"
                )

        except Exception as e:
            logger.error(f"检查用户 {adapter_name}+{user_id} 消息历史时发生错误：{e}")
            continue

    return users_to_process


async def process_user_profiles(users: List[Tuple[str, str]]) -> None:
    """
    Process user profile updates for a list of users using optimized batching.
    Groups users by adapter and uses efficient batch processing with proper error handling.

    Args:
        users: List of (adapter_name, user_id) tuples to process
    """
    # Group users by adapter to optimize processing
    adapter_groups = {}
    for adapter_name, user_id in users:
        if adapter_name not in adapter_groups:
            adapter_groups[adapter_name] = []
        adapter_groups[adapter_name].append(user_id)

    total_success = 0
    total_users = len(users)

    # Process each adapter group using optimized batching
    for adapter_name, user_ids in adapter_groups.items():
        logger.info(f"处理适配器 {adapter_name} 的 {len(user_ids)} 个用户")

        # Use async context manager for efficient connection reuse
        async with UserMemoryManager(adapter_name) as memory_manager:
            # Use batch processing with configurable parameters
            batch_size = min(config.api_batch_size, len(user_ids))
            delay_between_batches = config.api_batch_delay

            success_count, user_count = await memory_manager.batch_update_users(
                user_ids, batch_size=batch_size, delay_between_batches=delay_between_batches
            )

            total_success += success_count
            logger.info(f"适配器 {adapter_name} 处理完成: {success_count}/{user_count} 个用户更新成功")

    logger.info(f"所有用户处理完成: {total_success}/{total_users} 个用户更新成功")


# Removed _safe_update_user_memory as it's now handled by the batch processing in UserMemoryManager
