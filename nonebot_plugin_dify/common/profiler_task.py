import asyncio

from nonebot.log import logger
from nonebot import get_bot

from ..config import config
from .group_memory_manager import GroupMemoryManager, get_all_profiler_statuses
from .record_manager import get_record_status


async def process_single_group_profile(adapter_name: str, group_id: str):
    """处理单个群组的画像和个性化要求更新"""
    try:
        bot = get_bot()
        bot_name = list(bot.config.nickname)[0] if bot.config.nickname else "bot"
    except Exception:
        logger.warning(f"无法获取 Bot 昵称，群组 {adapter_name}:{group_id} 将使用默认 'bot' 作为 Bot 名称。")
        bot_name = "bot"

    # 只有开启聊天记录时才需要更新画像和个性化要求
    if get_record_status(adapter_name, group_id):
        try:
            await GroupMemoryManager(adapter_name=adapter_name, bot_name=bot_name).update_group_memory(group_id)
        except Exception as e:
            logger.error(f"更新群组 {adapter_name}:{group_id} 画像时出错: {e}")
    else:
        logger.debug(f"群组 {adapter_name}:{group_id} 未开启聊天记录，跳过画像更新。")


async def run_profiling_job():
    """执行画像和个性化要求生成和更新的定时任务"""
    logger.info("开始执行定时画像和个性化要求生成任务...")

    # 检查画像生成功能是否已配置
    if not config.profiler_workflow_api_key:
        logger.warning("未配置画像生成Dify Workflow，跳过定时任务")
        return

    # 获取所有开启了画像功能的群组
    all_statuses = get_all_profiler_statuses()

    enabled_groups = []
    for key, status in all_statuses.items():
        if status and "+" in key:
            parts = key.split("+", 1)
            if len(parts) == 2:
                adapter_name = parts[0]
                group_id = parts[1]
                # 只有开启聊天记录时才需要更新画像和个性化要求
                if get_record_status(adapter_name, group_id):
                    enabled_groups.append((adapter_name, group_id))

    if not enabled_groups:
        logger.info("没有开启画像功能的群组，任务结束")
        return

    # 为每个群组执行画像和个性化要求更新
    tasks = [process_single_group_profile(adapter, group_id) for adapter, group_id in enabled_groups]
    await asyncio.gather(*tasks)

    logger.info("定时画像和个性化要求生成任务完成")
