import importlib
from nonebot.adapters import Bot, Event
from nonebot.permission import SUPERUSER, Permission
from nonebot import logger

from ..config import config
from .helpers import get_full_user_id


# 动态权限检查器
class MultiPlatformPermission(Permission):
    """跨平台权限检查器，优先检查 SUPERUSER 和 config.system_admin_user_id, 再检查各平台权限"""

    async def __call__(self, bot: Bot, event: Event) -> bool:
        # 首先检查超级用户权限
        if await SUPERUSER(bot, event):
            return True

        # 检查是否为系统管理员
        if config.system_admin_user_id:
            full_user_id = get_full_user_id(event, bot)
            admin_ids = [uid.strip() for uid in config.system_admin_user_id.split(",")]
            if full_user_id in admin_ids:
                logger.info(f"Permission granted by SYSTEM_ADMIN_USER_ID: {full_user_id}")
                return True

        # 动态检查各平台权限
        platform_checks = [self._check_onebot_v11, self._check_telegram, self._check_qq_guild, self._check_discord]

        for check in platform_checks:
            try:
                if await check(bot, event):
                    logger.info(f"Permission granted by {check.__name__}")
                    return True
            except (ImportError, AttributeError, TypeError):
                continue  # 忽略适配器未安装或检查失败的情况

        return False

    async def _check_onebot_v11(self, bot: Bot, event: Event) -> bool:
        """检查 OneBot V11 权限"""
        if bot.type != "OneBot V11":
            return False

        # 动态导入避免未安装适配器时报错
        ob11 = importlib.import_module("nonebot.adapters.onebot.v11")

        if not isinstance(event, ob11.GroupMessageEvent):
            return False

        # 检查群主/管理员权限
        return event.sender.role in ["owner", "admin"]

    async def _check_telegram(self, bot: Bot, event: Event) -> bool:
        """检查 Telegram 权限"""
        if bot.type != "Telegram":
            return False
        logger.debug("检查telegram权限")
        # 动态导入 Telegram 适配器
        tg_permission = importlib.import_module("nonebot.adapters.telegram.permission")
        tg_event = importlib.import_module("nonebot.adapters.telegram.event")

        if not isinstance(event, tg_event.GroupMessageEvent):
            return False

        # 检查群主/管理员权限
        return await tg_permission.CREATOR(bot, event) or await tg_permission.ADMINISTRATOR(bot, event)

    async def _check_qq_guild(self, bot: Bot, event: Event) -> bool:
        """检查 QQ 频道权限"""
        if bot.type != "QQ":
            return False

        # 动态导入 QQ 适配器
        qq_event = importlib.import_module("nonebot.adapters.qq.event")
        qq_permission = importlib.import_module("nonebot.adapters.qq.permission")

        if not isinstance(event, qq_event.GuildMessageEvent):
            return False

        # 检查频道主/管理员权限
        return await qq_permission.GUILD_OWNER(bot, event) or await qq_permission.GUILD_ADMIN(bot, event)

    async def _check_discord(self, bot: Bot, event: Event) -> bool:
        """检查 Discord 权限（基于权限位掩码）"""
        if bot.type != "Discord":
            return False

        try:
            discord = importlib.import_module("nonebot.adapters.discord")
            if not isinstance(event, discord.event.GuildMessageEvent):
                return False

            member = getattr(event, "member", None)
            if not member:
                return False

            # 获取权限值（可能是字符串或整数）
            permissions = getattr(member, "permissions", "0")

            # 确保权限值是整数
            if isinstance(permissions, str):
                try:
                    permissions = int(permissions)
                except ValueError:
                    permissions = 0

            # 定义 Discord 权限位（完整列表见下方）
            ADMINISTRATOR = 0x8  # 管理员（2048）
            MANAGE_GUILD = 0x20  # 管理服务器（32）
            MANAGE_ROLES = 0x10000000  # 管理角色（268435456）

            # 检查权限位
            return bool(permissions & ADMINISTRATOR or permissions & MANAGE_GUILD or permissions & MANAGE_ROLES)

        except ImportError:
            return False  # 忽略适配器未安装的情况


# 创建跨平台权限实例
MULTI_PLATFORM_PERM = MultiPlatformPermission()
