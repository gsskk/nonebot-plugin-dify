"""
NoneBot Plugin Dify

接入 Dify API 的 NoneBot 插件
"""

from nonebot import require, logger
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

# 确保依赖的插件已加载
require("nonebot_plugin_alconna")
require("nonebot_plugin_localstore")
require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler

from .config import Config, config
from .core.dify_bot import DifyBot

# 创建 DifyBot 实例
dify_bot = DifyBot()

__version__ = "0.1.14"

__plugin_meta__ = PluginMetadata(
    name="dify插件",
    description="接入dify API",
    homepage="https://github.com/gsskk/nonebot-plugin-dify",
    usage="使用dify云服务或自建dify创建app，然后在配置文件中设置相应dify API",
    type="application",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={
        "author": "gsskk",
        "priority": 1,
        "version": __version__,
    },
)

# 启动时配置检查
if config.image_attach_mode != "off" and not config.image_upload_enable:
    logger.warning(
        "IMAGE_ATTACH_MODE 设置为 '%s'，但 IMAGE_UPLOAD_ENABLE 为 False。"
        "图片缓存功能需要 IMAGE_UPLOAD_ENABLE=true 才能正常工作。",
        config.image_attach_mode,
    )

if config.history_image_mode == "description" and not config.image_description_workflow_api_key:
    logger.warning(
        "HISTORY_IMAGE_MODE 设置为 'description'，但 IMAGE_DESCRIPTION_WORKFLOW_API_KEY 未配置。"
        "图片描述生成功能将无法工作。"
    )

# 导入 handlers 以注册事件处理器和命令
from . import handlers  # noqa: F401, E402

# 导入定时任务相关模块
from .services import data_cleanup
from .utils import image_cache

# --- 定时任务 ---
if config.private_personalization_enable and config.profiler_workflow_api_key:
    import asyncio
    import random

    async def _trigger_private_profiling_session():
        """由cron触发，负责派发具体的用户分析任务"""
        from .managers import private_chat
        from .services.private_profiler import process_user_profiles

        logger.info("开始派发私聊画像分析任务...")
        all_statuses = private_chat.get_all_personalization_statuses()
        enabled_users = []
        for key, status in all_statuses.items():
            if status and "+private+" in key:
                parts = key.split("+")
                if len(parts) == 3:  # format: adapter+private+user_id
                    enabled_users.append((parts[0], parts[2]))

        if not enabled_users:
            logger.info("没有启用个性化功能的私聊用户，任务结束。")
            return

        jitter_minutes = config.private_profiler_schedule_jitter

        if jitter_minutes <= 0:
            logger.info("Jitter被禁用，立即执行所有私聊分析任务...")
            await process_user_profiles(enabled_users)
        else:
            logger.info(f"Jitter已启用，私聊分析任务将在 {jitter_minutes} 分钟内平滑执行。")

            # Group users by adapter to use batch_update_users effectively
            adapter_groups = {}
            for adapter_name, user_id in enabled_users:
                if adapter_name not in adapter_groups:
                    adapter_groups[adapter_name] = []
                adapter_groups[adapter_name].append(user_id)

            async def _delayed_process(adapter, uids):
                delay = random.uniform(0, jitter_minutes * 60)
                await asyncio.sleep(delay)
                from .services.private_profiler import process_user_profiles

                await process_user_profiles([(adapter, uid) for uid in uids])

            for adapter_name, uids in adapter_groups.items():
                asyncio.create_task(_delayed_process(adapter_name, uids))

    scheduler.add_job(
        _trigger_private_profiling_session,
        trigger="cron",
        hour=config.private_profiler_schedule.split(" ")[1],
        minute=config.private_profiler_schedule.split(" ")[0],
        day_of_week=config.private_profiler_schedule.split(" ")[4],
        id="dify_private_profiling_job",
        replace_existing=True,
    )
    logger.info(f"已成功安排私聊画像生成定时任务，触发器: {config.private_profiler_schedule}")

if config.profiler_workflow_api_key:
    import asyncio
    import random

    async def _trigger_group_profiling_session():
        """由cron触发，负责派发具体的群组分析任务"""
        from .managers.group_memory import get_all_profiler_statuses
        from .services.profiler import process_single_group_profile

        logger.info("开始派发群组画像分析任务...")
        all_statuses = get_all_profiler_statuses()
        enabled_groups = []
        for key, status in all_statuses.items():
            if status and "+" in key:
                parts = key.split("+", 1)
                if len(parts) == 2:
                    enabled_groups.append((parts[0], parts[1]))

        if not enabled_groups:
            logger.info("没有需要分析的群组，任务结束。")
            return

        jitter_minutes = config.profiler_schedule_jitter
        if jitter_minutes <= 0:
            logger.info("Jitter被禁用，立即执行所有群组分析任务...")
            await asyncio.gather(
                *[process_single_group_profile(adapter, group_id) for adapter, group_id in enabled_groups]
            )
        else:
            logger.info(f"Jitter已启用，群组分析任务将在 {jitter_minutes} 分钟内平滑执行。")
            for adapter, group_id in enabled_groups:
                delay = random.uniform(0, jitter_minutes * 60)
                await asyncio.sleep(delay)
                asyncio.create_task(process_single_group_profile(adapter, group_id))

    scheduler.add_job(
        _trigger_group_profiling_session,
        trigger="cron",
        hour=config.profiler_schedule.split(" ")[1],
        minute=config.profiler_schedule.split(" ")[0],
        day_of_week=config.profiler_schedule.split(" ")[4],
        id="dify_profiling_job",
        replace_existing=True,
    )
    logger.info(f"已成功安排画像生成定时任务，触发器: {config.profiler_schedule}")

# Add data cleanup task if private personalization is enabled
if config.private_personalization_enable and config.private_data_retention_days > 0:
    scheduler.add_job(
        data_cleanup.run_data_cleanup_job,
        trigger="cron",
        hour=2,
        minute=0,
        id="dify_data_cleanup_job",
        replace_existing=True,
    )
    logger.info(f"已成功安排数据清理定时任务，每日凌晨2点执行，保留 {config.private_data_retention_days} 天数据")


# Add data integrity check if private personalization is enabled
if config.private_personalization_enable:
    scheduler.add_job(
        data_cleanup.run_data_integrity_check,
        trigger="cron",
        hour=1,
        minute=0,
        day_of_week=6,  # Sunday (0=Monday, 6=Sunday)
        id="dify_data_integrity_check_job",
        replace_existing=True,
    )
    logger.info("已成功安排数据完整性检查定时任务，每周日凌晨1点执行")

# Add image cache cleanup task if image caching is enabled
if config.image_attach_mode != "off":
    scheduler.add_job(
        image_cache.clear_expired_cache,
        trigger="interval",
        hours=1,
        id="dify_image_cache_cleanup_job",
        replace_existing=True,
    )
    logger.info("已成功安排图片缓存清理定时任务，每小时执行一次")
