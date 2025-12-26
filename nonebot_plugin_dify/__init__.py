from nonebot import require, on_command, on_message, logger
from nonebot.exception import FinishedException
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")
require("nonebot_plugin_localstore")
require("nonebot_plugin_apscheduler")

from nonebot.adapters import Bot, Event
from nonebot.internal.matcher.matcher import Matcher
from nonebot.rule import Rule, to_me
from nonebot.typing import T_State
import os
from nonebot.permission import SUPERUSER, Permission

from typing import List
import importlib
import re
import time
from datetime import datetime
from .config import Config, config
from . import session as session_manager
from .dify_bot import DifyBot
from .common.reply_type import ReplyType
from .common import record_manager, chat_recorder, group_memory_manager
from .common import private_chat_manager, private_chat_recorder, data_cleanup_task
from .common.user_data_store import user_profile_memory, user_personalization_memory
from .common.utils import get_pic_from_url, save_pic
from .cache import USER_IMAGE_CACHE

import nonebot_plugin_alconna as alconna
import nonebot_plugin_localstore as store
from nonebot_plugin_apscheduler import scheduler


dify_bot = DifyBot()

__version__ = "0.1.9"

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


async def ignore_rule(event: Event) -> bool:
    msg = event.get_plaintext().strip()

    # 消息以忽略词开头
    if next(
        (x for x in config.ignore_prefix if msg.startswith(x)),
        None,
    ):
        return False

    return True


def get_full_user_id(event: Event, bot: Bot) -> str:
    target = alconna.get_target()
    try:
        adapter_name = (
            target.adapter.replace("SupportAdapter.", "").replace(" ", "").lower() if target.adapter else "default"
        )
    except Exception as e:
        # 回退方案
        logger.error(f"Failed to fetch adapter name: {e}")
        adapter_name = getattr(bot, "type", "unknown").lower()

    user_id = event.get_user_id() if event.get_user_id() else "user"

    # 特殊处理Discord
    if adapter_name == "discord" and hasattr(event, "guild_id"):
        target_id = getattr(event, "channel_id", "private")

        has_record = record_manager.get_record_status(adapter_name, target_id)
        if has_record or not config.session_share_in_group:
            return f"discord+{target_id}+{user_id}"
        else:
            return f"discord+{target_id}"

    if target.private:
        full_user_id = f"{adapter_name}+private+{user_id}"
    else:
        target_id = target.id

        share_session = config.session_share_in_group
        has_record = record_manager.get_record_status(adapter_name, target_id)

        if has_record or not share_session:
            full_user_id = f"{adapter_name}+{target_id}+{user_id}"
        else:
            full_user_id = f"{adapter_name}+{target_id}"
    return full_user_id


def clean_message_for_record(message: alconna.UniMessage) -> str:
    """
    清理和预处理 UniMessage，以便记录。

    - 将图片替换为占位符
    - 截断长消息
    - 压缩重复内容
    - 脱敏 (如果启用)
    - 标准化空白和标点
    """
    text_parts = []
    for seg in message:
        if isinstance(seg, alconna.Image):
            text_parts.append("[IMG]")
        else:
            text_parts.append(str(seg))

    full_message = "".join(text_parts)

    # 1. 标准化空白字符
    cleaned_message = re.sub(r"\s+", " ", full_message).strip()

    # 2. 压缩重复内容
    def compress_repeats(match):
        repeated_str = match.group(1)
        count = len(match.group(0)) // len(repeated_str)
        return f"{repeated_str}*{count}"

    cleaned_message = re.sub(r"(.{2,})\1{2,}", compress_repeats, cleaned_message)

    # 3. 压缩标点符号
    cleaned_message = re.sub(r"([!?.,。！？，])\1+", r"\1", cleaned_message)

    # 4. 脱敏处理 (如果启用)
    if config.message_desensitization_enable:
        # 手机号
        cleaned_message = re.sub(r"1[3-9]\d{9}", "[PHONE]", cleaned_message)
        # 邮箱
        cleaned_message = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", cleaned_message)

    # 5. 截断消息
    max_length = max(config.message_max_length, 3)
    if len(cleaned_message) > max_length:
        cleaned_message = cleaned_message[: max_length - 3] + "..."

    return cleaned_message


# 监听普通消息
receive_message: type[Matcher] = on_message(
    rule=Rule(ignore_rule),
    priority=99,
    block=False,
)

# 监听 /clear 命令
clear_command = on_command("clear", force_whitespace=True, priority=90, block=True)

# 监听 /help 命令
help_command = on_command("help", force_whitespace=True, priority=90, block=True)

# 监听 /record [on/off] 命令
record_command = alconna.on_alconna(
    alconna.Alconna("record", alconna.Args["action", ["on", "off", "check"]]),
    permission=MULTI_PLATFORM_PERM,
    use_cmd_start=True,
    auto_send_output=True,
    priority=90,
    block=True,
)

# 监听 /profiler [on/off] 命令
profiler_command = alconna.on_alconna(
    alconna.Alconna("profiler", alconna.Args["action", ["on", "off", "check"]]),
    permission=MULTI_PLATFORM_PERM,
    use_cmd_start=True,
    auto_send_output=True,
    priority=89,
    block=True,
)

# 监听 /personalize [on/off/check] 命令
personalize_command = alconna.on_alconna(
    alconna.Alconna("personalize", alconna.Args["action", ["on", "off", "check"]]),
    use_cmd_start=True,
    auto_send_output=True,
    priority=90,
    block=True,
)

# 监听 /profile 命令
profile_command = on_command("profile", force_whitespace=True, priority=90, block=True)

# 监听 /reset_profile 命令
reset_profile_command = alconna.on_alconna(
    alconna.Alconna("reset_profile", alconna.Args["confirm?", str]),
    use_cmd_start=True,
    auto_send_output=True,
    priority=90,
    block=True,
)

# 监听 /get_my_id 命令 (私聊专用)
get_my_id_command = on_command(
    "get_my_id",
    rule=to_me(),
    force_whitespace=True,
    priority=90,
    block=True,
)


@receive_message.handle()
async def handle_message(bot: Bot, event: Event):
    """处理接收到的消息"""
    try:
        # 获取消息目标适配器
        target = alconna.get_target()
        adapter_name = await get_adapter_name(target)
        logger.debug(f"Message target adapter: {adapter_name}.")

        # 提取被引用的消息
        replied_message = None
        replied_image_path = None
        if hasattr(event, "reply") and event.reply:
            try:
                replied_message = await alconna.UniMessage.generate(message=event.reply.message, bot=bot)
                logger.debug(f"Detected replied message: `{replied_message.extract_plain_text().strip()}`")
                if replied_message.has(alconna.Image):
                    logger.debug("Replied message contains an image.")
                    imgs = replied_message[alconna.Image]
                    _img = imgs[0]
                    from nonebot.typing import T_State

                    _img_bytes = await alconna.image_fetch(event=event, bot=bot, state=T_State(), img=_img)
                    if _img_bytes:
                        cache_dir = store.get_cache_dir("nonebot_plugin_dify")
                        save_dir = os.path.join(cache_dir, config.image_cache_dir)
                        replied_image_path = save_pic(_img_bytes, _img, save_dir)
                        logger.debug(f"Saved replied image to temporary path: {replied_image_path}")
                    else:
                        logger.warning("Failed to fetch replied image bytes.")
            except Exception as e:
                logger.warning(f"Failed to extract replied message: {e}")

        # 生成统一消息对象并提取纯文本
        uni_msg = alconna.UniMessage.generate_without_reply(event=event, bot=bot)
        msg_text = uni_msg.extract_plain_text()

        # 忽略空消息
        if not msg_text:
            logger.debug("Ignored empty plaintext message.")
            await receive_message.finish()

        # 获取用户信息
        user_id = event.get_user_id() or "user"
        full_user_id = get_full_user_id(event, bot)
        session_id = f"s-{full_user_id}"

        # Pre-fetch session to check linger state
        # session = session_manager.get_session(session_id, full_user_id)
        is_linger = False

        # Pre-fetch Group State (if not private)
        group_state = None
        if not target.private:
            group_state_id = f"{adapter_name}+{target.id}"
            group_state = session_manager.get_group_state(group_state_id)

        # 处理私聊消息
        if target.private:
            # 检查是否启用私聊个性化功能
            if config.private_personalization_enable:
                try:
                    personalization_enabled = private_chat_manager.get_personalization_status(adapter_name, user_id)
                    logger.debug(f"Private chat personalization enabled for user {user_id}: {personalization_enabled}")

                    # 记录私聊用户消息（如果启用了个性化）
                    if personalization_enabled:
                        nickname = await get_sender_nickname(event, user_id, bot)
                        cleaned_message = clean_message_for_record(uni_msg)
                        await private_chat_recorder.record_private_message(
                            adapter_name, user_id, nickname, cleaned_message, "user"
                        )
                        logger.debug(f"Recorded private chat user message for {user_id}")
                except Exception as e:
                    logger.warning(f"Failed to check personalization status for user {user_id}: {e}")
                    personalization_enabled = False
            else:
                personalization_enabled = False
                logger.debug("Private chat personalization is globally disabled")
        else:
            # 处理群聊消息
            is_mentioned = event.is_tome()
            # 备用at检查，应对is_tome()在某些情况下失效
            if not is_mentioned and uni_msg.has(alconna.At):
                for seg in uni_msg[alconna.At]:
                    if str(seg.target) == str(bot.self_id):
                        is_mentioned = True
                        break

            # --- Priority 2: Linger Mode Check (Group Wide) ---
            if not is_mentioned and config.linger_mode_enable and group_state:
                if group_state.last_interaction_time > 0:  # Only linger if we actually had a previous interaction
                    time_since_last = time.time() - group_state.last_interaction_time
                    if time_since_last < config.linger_timeout_seconds:
                        if group_state.linger_message_count < config.linger_max_messages:
                            logger.debug(
                                f"Linger mode active: {time_since_last:.1f}s since last, count {group_state.linger_message_count}"
                            )
                            is_mentioned = True
                            is_linger = True

            # --- Handle Active Triggers (At or Linger) ---
            if is_mentioned:
                # 1. Cancel any pending proactive task because the conversation is now active
                if group_state and group_state.proactive_pending_task_id:
                    try:
                        scheduler.remove_job(group_state.proactive_pending_task_id)
                        logger.debug(
                            f"Cancelled proactive task due to active mention: {group_state.proactive_pending_task_id}"
                        )
                    except Exception:
                        pass
                    group_state.proactive_pending_task_id = ""

                # 2. Update group state
                if group_state:
                    group_state.last_interaction_time = time.time()
                    if is_linger:
                        group_state.linger_message_count += 1
                    else:
                        group_state.linger_message_count = 0  # Reset on explicit mention

                # 3. Record and proceed to reply
                try:
                    await record_group_message(target, event, uni_msg, bot, user_id, adapter_name, is_mentioned)
                except Exception as e:
                    logger.warning(f"Failed to record group message: {e}")

            # --- Priority 3: Proactive Intervention Check (Only if not mentioned) ---
            else:
                # 1. Any incoming message breaks the silence, so cancel pending tasks
                if group_state and group_state.proactive_pending_task_id:
                    try:
                        scheduler.remove_job(group_state.proactive_pending_task_id)
                        logger.debug(
                            f"Reset silence watcher because someone spoke: {group_state.proactive_pending_task_id}"
                        )
                    except Exception:
                        pass
                    group_state.proactive_pending_task_id = ""

                # 2. Record the message (as a normal non-mention message)
                try:
                    await record_group_message(target, event, uni_msg, bot, user_id, adapter_name, is_mentioned)
                except Exception as e:
                    logger.warning(f"Failed to record group message: {e}")

                # 3. Check if we should start a new proactive observation
                if config.proactive_mode_enable and group_state:
                    # Cooldown check: Use max(last_interaction_time, created_at) to ensure
                    # a full cooldown period after bot restart or first sight of group.
                    reference_time = max(group_state.last_interaction_time, group_state.created_at)
                    time_since_last = time.time() - reference_time

                    if time_since_last > config.proactive_cooldown_seconds:
                        from .common.semantic_matcher import semantic_matcher

                        if semantic_matcher.check_relevance(msg_text):
                            trigger_time = time.time() + config.proactive_silence_waiting_seconds
                            job_id = f"proactive_trigger_{group_state_id}_{int(time.time())}"

                            async def _proactive_callback(
                                bot_ref=bot,
                                event_ref=event,
                                uni_msg_ref=uni_msg,
                                full_user_id_ref=full_user_id,
                                session_id_ref=session_id,
                                group_state_id_ref=group_state_id,
                                target_ref=target,
                                adapter_name_ref=adapter_name,
                            ):
                                logger.info(f"Proactive intervention triggered for group {group_state_id_ref}")
                                # Fetch fresh group state
                                gs = session_manager.get_group_state(group_state_id_ref)

                                # Mark as active to enforce cooldown
                                gs.last_interaction_time = time.time()
                                gs.proactive_last_trigger_time = time.time()
                                gs.proactive_pending_task_id = ""

                                msg_text = uni_msg_ref.extract_plain_text()
                                try:
                                    await send_reply_message(
                                        msg_text,
                                        full_user_id_ref,
                                        session_id_ref,
                                        event_ref,
                                        bot_ref,
                                        target_ref,
                                        adapter_name_ref,
                                        personalization_enabled=False,
                                        at_user_ids=[],
                                        is_linger=False,
                                        is_proactive=True,
                                    )
                                except Exception as e:
                                    logger.error(f"Proactive reply failed: {e}")

                            scheduler.add_job(
                                _proactive_callback, "date", run_date=datetime.fromtimestamp(trigger_time), id=job_id
                            )
                            group_state.proactive_pending_task_id = job_id
                            logger.debug(
                                f"Scheduled silence watcher {job_id} in {config.proactive_silence_waiting_seconds}s"
                            )

                # 4. Finish processing this message (no immediate reply)
                logger.debug("Ignored non-mention message in group.")
                await receive_message.finish()

            personalization_enabled = False  # Group personalization is handled separately

        # 处理消息中的图片
        try:
            await handle_message_images(uni_msg, event, bot, session_id, adapter_name)
        except Exception as e:
            logger.warning(f"Failed to handle message images: {e}")

        # 提取被提到（At）的用户 ID
        at_user_ids = []
        if uni_msg.has(alconna.At):
            for seg in uni_msg[alconna.At]:
                at_user_ids.append(str(seg.target))

        # 获取回复并发送
        try:
            await send_reply_message(
                msg_text,
                full_user_id,
                session_id,
                event,
                bot,
                target,
                adapter_name,
                personalization_enabled,
                replied_message=replied_message,
                replied_image_path=replied_image_path,
                at_user_ids=at_user_ids,
                is_linger=is_linger,
            )
        except FinishedException:
            raise
        except Exception as e:
            logger.warning(f"Failed to generate reply: {e}")
            await receive_message.finish("")

    except FinishedException:
        raise
    except Exception as e:
        logger.error(f"Critical error in message handler: {e}")
        await receive_message.finish()


async def record_group_message(
    target: alconna.Target,
    event: Event,
    uni_msg: alconna.UniMessage,
    bot: Bot,
    user_id: str,
    adapter_name: str,
    is_mentioned: bool,
) -> None:
    """记录群聊消息"""
    if not record_manager.get_record_status(adapter_name, target.id):
        return

    nickname = await get_sender_nickname(event, user_id, bot)
    a = event.model_dump()
    logger.debug(f"{type(a)}: {a}")

    cleaned_message = clean_message_for_record(uni_msg)
    logger.debug(f"记录群消息: {cleaned_message}")
    await chat_recorder.record_message(
        adapter_name, target.id, user_id, nickname, cleaned_message, "user", is_mentioned
    )


async def get_sender_nickname(event: Event, user_id: str, bot: Bot) -> str:
    """跨平台获取发言人昵称（显示名）"""
    nickname = user_id

    # 1. OneBot V11
    if bot.type == "OneBot V11" and hasattr(event, "sender"):
        sender = event.sender
        nickname = getattr(sender, "card", None) or getattr(sender, "nickname", None) or nickname

    # 2. Telegram
    elif bot.type == "Telegram":
        try:
            from nonebot.adapters.telegram.event import MessageEvent as TGEvent

            if isinstance(event, TGEvent) and hasattr(event, "from_"):
                user = event.from_
                parts = [name for name in [user.first_name, user.last_name] if name]
                if parts:
                    nickname = " ".join(parts)
        except (ImportError, AttributeError):
            pass

    # 3. Discord
    elif bot.type == "Discord" and "GuildMessageEvent" in event.__class__.__name__:
        member = getattr(event, "member", None)
        if member:
            nickname = getattr(member, "nick", None) or getattr(member, "name", None) or nickname

    # 4. QQ Guild
    elif bot.type == "QQ" and "GuildMessageEvent" in event.__class__.__name__:
        member = getattr(event, "member", None)
        if member:
            nickname = getattr(member, "nick", None) or nickname

    # Fallback for other platforms using sender attribute
    elif hasattr(event, "sender"):
        sender = event.sender
        nickname = getattr(sender, "card", None) or getattr(sender, "nickname", None) or nickname

    return str(nickname) if nickname else str(user_id)


async def get_adapter_name(target: alconna.Target) -> str:
    """获取适配器名称"""
    if not target.adapter:
        return "default"
    return target.adapter.replace("SupportAdapter.", "").replace(" ", "").lower()


async def handle_message_images(
    uni_msg: alconna.UniMessage, event: Event, bot: Bot, session_id: str, adapter_name: str
) -> None:
    """处理消息中的图片"""
    if not uni_msg.has(alconna.Image):
        return

    imgs = uni_msg[alconna.Image]
    _img = imgs[0]
    _img_bytes = await alconna.image_fetch(event=event, bot=bot, state=T_State, img=_img)

    if not _img_bytes:
        logger.warning(f"Failed to fetch image from {adapter_name}.")
        return

    logger.debug(f"Got image {_img.id} from {adapter_name}.")

    # 保存图片到缓存
    cache_dir = store.get_cache_dir("nonebot_plugin_dify")
    save_dir = os.path.join(cache_dir, config.image_cache_dir)
    _img_path = save_pic(_img_bytes, _img, save_dir)

    USER_IMAGE_CACHE[session_id] = {"id": _img.id, "path": _img_path}
    logger.debug(f"Set image cache: {USER_IMAGE_CACHE[session_id]}, local path: {_img_path}.")


async def send_reply_message(
    msg_text: str,
    full_user_id: str,
    session_id: str,
    event: Event,
    bot: Bot,
    target: alconna.Target,
    adapter_name: str,
    personalization_enabled: bool = False,
    replied_message: alconna.UniMessage = None,
    replied_image_path: str = None,
    at_user_ids: list[str] = None,
    is_linger: bool = False,
    is_proactive: bool = False,
) -> None:
    """发送回复消息"""
    user_id = event.get_user_id() or "user"

    try:
        # 获取Dify回复
        reply_type, reply_content = await dify_bot.reply(
            msg_text,
            full_user_id,
            session_id,
            personalization_enabled,
            replied_message=replied_message,
            replied_image_path=replied_image_path,
            at_user_ids=at_user_ids,
            is_linger=is_linger,
            is_proactive=is_proactive,
        )

        # 检查是否为静默回复（Linger Mode 或 Proactive Mode）
        if not reply_type and not reply_content:
            logger.debug("Suppressing silent reply.")
            return

        # 构建回复消息
        try:
            _uni_message = await build_reply_message(reply_type, reply_content)
        except Exception as e:
            logger.warning(f"Failed to build reply message: {e}")
            _uni_message = alconna.UniMessage(str(reply_content[0]) if reply_content else "抱歉，回复生成失败。")

        # 发送消息
        try:
            if target.private or is_proactive or is_linger:
                send_msg = await _uni_message.export()
            else:
                send_msg = await alconna.UniMessage([alconna.At("user", user_id), "\n", _uni_message]).export()
        except Exception as e:
            logger.warning(f"Failed to export message: {e}")
            send_msg = str(reply_content[0]) if reply_content else "抱歉，消息发送失败。"

        # 记录机器人回复
        try:
            if target.private:
                if personalization_enabled:
                    cleaned_reply = clean_message_for_record(_uni_message)
                    await private_chat_recorder.record_private_message(
                        adapter_name, user_id, "Bot", cleaned_reply, "assistant"
                    )
                    logger.debug(f"Recorded private chat bot response for {user_id}")
            else:
                if record_manager.get_record_status(adapter_name, target.id):
                    cleaned_reply = clean_message_for_record(_uni_message)
                    await chat_recorder.record_message(
                        adapter_name, target.id, bot.self_id, "Bot", cleaned_reply, "assistant", False
                    )
        except Exception as e:
            logger.warning(f"Failed to record bot reply: {e}")

        await receive_message.finish(send_msg)

    except FinishedException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate reply: {e}")
        await receive_message.finish("")


async def build_reply_message(reply_types: List[ReplyType], reply_contents: List[str]) -> alconna.UniMessage:
    """构建回复消息"""
    _uni_message = alconna.UniMessage()

    for _reply_type, _reply_content in zip(reply_types, reply_contents):
        logger.debug(f"Ready to send {_reply_type}: {type(_reply_content)} {_reply_content}")

        if _reply_type == ReplyType.IMAGE_URL:
            _pic_content = await get_pic_from_url(_reply_content)
            _uni_message += alconna.UniMessage(alconna.Image(raw=_pic_content))
        else:
            _uni_message += alconna.UniMessage(f"{_reply_content}")

    return _uni_message


@clear_command.handle()
async def handle_clear(event: Event, bot: Bot):
    """处理 /clear 命令"""
    target = alconna.get_target()
    adapter_name = await get_adapter_name(target)
    user_id = event.get_user_id() if event.get_user_id() else "user"

    if not target.private:
        group_id = target.id
        if record_manager.get_record_status(adapter_name, group_id):
            send_msg = await alconna.UniMessage("我在记小本本，无法清理上下文！").export()
            await clear_command.finish(send_msg)

    full_user_id = get_full_user_id(event, bot)
    session_id = f"s-{full_user_id}"

    logger.debug(f"Clear session: {session_id}.")
    session_manager.clear_session(session_id)

    _uni_message = alconna.UniMessage("你的上下文已被清理！")

    if target.private:
        send_msg = await _uni_message.export()
    else:
        send_msg = await alconna.UniMessage([alconna.At("user", user_id), "\n" + _uni_message]).export()

    await clear_command.finish(send_msg)


@help_command.handle()
async def handle_help(event: Event):
    """处理 /help 命令"""
    target = alconna.get_target()

    if target.private:
        # Private chat help
        help_text = (
            "📖 **帮助菜单**\n"
            "/clear - 清除Dify上下文\n"
            "/help - 显示本帮助信息\n"
            "/personalize [on|off|check] - 启用/禁用/查看私聊个性化功能\n"
            "/profile - 查看您的个人档案和对话统计\n"
            "/reset_profile [confirm] - 重置个人档案数据\n"
            "💡 你可以直接发送消息，我会回复你！"
        )
        if config.private_personalization_enable:
            help_text += "\n\n🤖 私聊个性化功能可用，使用 /personalize on 启用个性化回复。"
    else:
        # Group chat help
        help_text = (
            "📖 **帮助菜单**\n"
            "/clear - 清除Dify上下文\n"
            "/help - 显示本帮助信息\n"
            "/record [on|off|check] - (管理员)开启/关闭当前群聊记录\n"
            "/profiler [on|off|check] - (管理员)开启/关闭当前群组个性化bot\n"
            "💡 你可以直接 @我 发送消息，我会回复你！"
        )

    await help_command.finish(help_text)


@record_command.handle()
async def handle_record(event: Event, bot: Bot, action: alconna.Match[str]):
    logger.debug(f"设置record: {action}.")
    target = alconna.get_target()
    if target.private:
        await record_command.finish("该功能仅限群组使用。")
    logger.debug(f"Running record_command: 平台 {bot.type}, 用户ID {event.get_user_id()}")

    group_id = target.id
    adapter_name = await get_adapter_name(target)
    if action.result == "check":
        _status = record_manager.get_record_status(adapter_name, group_id)
        await record_command.finish(f"当前小本本状态： {_status}")
    if action.result == "on":
        record_manager.set_record_status(adapter_name, group_id, True)
        await record_command.finish("小本本已准备好，你们的聊天记录我都会乖乖记下来哦~")
    else:
        record_manager.set_record_status(adapter_name, group_id, False)
        await record_command.finish("小本本收起来啦，你们的聊天记录我不会再偷听了！")


@profiler_command.handle()
async def handle_profiler(event: Event, bot: Bot, action: alconna.Match[str]):
    """处理 /profiler 命令"""
    target = alconna.get_target()
    if target.private:
        await profiler_command.finish("该功能仅限群组使用。")

    group_id = target.id
    adapter_name = await get_adapter_name(target)
    if action.result == "check":
        _status = group_memory_manager.get_profiler_status(adapter_name, group_id)
        await profiler_command.finish(f"当前群组画像功能状态：{_status}")
    elif action.result == "on":
        group_memory_manager.set_profiler_status(adapter_name, group_id, True)
        await profiler_command.finish("群组画像功能已开启，我将会更懂你们哦~")
    else:
        group_memory_manager.set_profiler_status(adapter_name, group_id, False)
        await profiler_command.finish("群组画像功能已关闭。")


@personalize_command.handle()
async def handle_personalize(event: Event, bot: Bot, action: alconna.Match[str]):
    """处理 /personalize 命令"""
    target = alconna.get_target()
    if not target.private:
        await personalize_command.finish("该功能仅限私聊使用。")

    # Check if private personalization is globally enabled
    if not config.private_personalization_enable:
        await personalize_command.finish("私聊个性化功能未启用。请联系管理员启用此功能。")

    adapter_name = await get_adapter_name(target)
    user_id = event.get_user_id() or "user"

    if action.result == "check":
        _status = private_chat_manager.get_personalization_status(adapter_name, user_id)
        status_text = "已启用" if _status else "已禁用"
        await personalize_command.finish(f"您的私聊个性化功能状态：{status_text}")
    elif action.result == "on":
        current_status = private_chat_manager.get_personalization_status(adapter_name, user_id)
        if current_status:
            await personalize_command.finish("您的私聊个性化功能已经启用。")
        else:
            private_chat_manager.set_personalization_status(adapter_name, user_id, True)
            await personalize_command.finish(
                "✅ 私聊个性化功能已启用！\n\n"
                "我将开始学习您的对话风格和偏好，为您提供更个性化的回复。\n"
                "您可以随时使用 /personalize off 来禁用此功能并清除所有数据。"
            )
    else:  # action.result == "off"
        current_status = private_chat_manager.get_personalization_status(adapter_name, user_id)
        if not current_status:
            await personalize_command.finish("您的私聊个性化功能已经禁用。")
        else:
            # Opt out user and clear all data
            private_chat_manager.opt_out_user(adapter_name, user_id)
            # Also clear conversation history
            private_chat_recorder.clear_user_data(adapter_name, user_id)
            await personalize_command.finish(
                "❌ 私聊个性化功能已禁用。\n\n"
                "您的所有个性化数据和对话记录已被完全清除。\n"
                "您可以随时使用 /personalize on 重新启用此功能。"
            )


@profile_command.handle()
async def handle_profile(event: Event, bot: Bot):
    """处理 /profile 命令"""
    target = alconna.get_target()
    if not target.private:
        await profile_command.finish("该功能仅限私聊使用。")

    # Check if private personalization is globally enabled
    if not config.private_personalization_enable:
        await profile_command.finish("私聊个性化功能未启用。请联系管理员启用此功能。")

    adapter_name = await get_adapter_name(target)
    user_id = event.get_user_id() or "user"

    # Check if user has enabled personalization
    personalization_enabled = private_chat_manager.get_personalization_status(adapter_name, user_id)
    if not personalization_enabled:
        await profile_command.finish(
            "您尚未启用私聊个性化功能。\n使用 /personalize on 启用后，我将开始为您建立个人档案。"
        )

    # Get user profile and personalization data
    user_profile = user_profile_memory.get(adapter_name, user_id)
    user_personalization = user_personalization_memory.get(adapter_name, user_id)

    # Get conversation statistics
    try:
        recent_messages = await private_chat_recorder.get_recent_private_messages(adapter_name, user_id, limit=100)
        total_messages = len(recent_messages)
        user_messages = len([msg for msg in recent_messages if msg.get("role") == "user"])
        bot_messages = len([msg for msg in recent_messages if msg.get("role") == "assistant"])

        # Get date of first and last message
        if recent_messages:
            first_message_date = recent_messages[0].get("timestamp", "").split("T")[0]
            last_message_date = recent_messages[-1].get("timestamp", "").split("T")[0]
        else:
            first_message_date = "无记录"
            last_message_date = "无记录"
    except Exception as e:
        logger.error(f"Error getting conversation statistics: {e}")
        total_messages = 0
        user_messages = 0
        bot_messages = 0
        first_message_date = "无法获取"
        last_message_date = "无法获取"

    # Build profile display
    profile_text = "👤 **您的个人档案**\n\n"

    # Conversation statistics
    profile_text += "📊 **对话统计**\n"
    profile_text += f"• 总消息数：{total_messages}\n"
    profile_text += f"• 您的消息：{user_messages}\n"
    profile_text += f"• 我的回复：{bot_messages}\n"
    profile_text += f"• 首次对话：{first_message_date}\n"
    profile_text += f"• 最近对话：{last_message_date}\n\n"

    # User profile (AI-generated summary)
    if user_profile:
        profile_text += "🧠 **AI分析的您的特征**\n"
        profile_text += f"{user_profile}\n\n"
    else:
        profile_text += "🧠 **AI分析的您的特征**\n"
        profile_text += "暂无足够数据进行分析。继续与我对话，我将逐渐了解您的偏好。\n\n"

    # Personalization settings (how AI adapts to user)
    if user_personalization:
        profile_text += "🎯 **个性化设置**\n"
        profile_text += f"{user_personalization}\n\n"
    else:
        profile_text += "🎯 **个性化设置**\n"
        profile_text += "暂无个性化设置。随着对话增加，我将学会如何更好地与您交流。\n\n"

    # Footer with management options
    profile_text += "⚙️ **管理选项**\n"
    profile_text += "• /personalize off - 禁用个性化并清除所有数据\n"
    profile_text += "• /reset_profile - 仅清除个人档案数据\n"
    profile_text += "• /clear - 清除当前对话上下文"

    await profile_command.finish(profile_text)


@reset_profile_command.handle()
async def handle_reset_profile(event: Event, bot: Bot, confirm: alconna.Match[str]):
    """处理 /reset_profile 命令"""
    target = alconna.get_target()
    if not target.private:
        await reset_profile_command.finish("该功能仅限私聊使用。")

    # Check if private personalization is globally enabled
    if not config.private_personalization_enable:
        await reset_profile_command.finish("私聊个性化功能未启用。请联系管理员启用此功能。")

    adapter_name = await get_adapter_name(target)
    user_id = event.get_user_id() or "user"

    # Check if user has enabled personalization
    personalization_enabled = private_chat_manager.get_personalization_status(adapter_name, user_id)
    if not personalization_enabled:
        await reset_profile_command.finish("您尚未启用私聊个性化功能。\n使用 /personalize on 启用后才能管理个人档案。")

    # Check if user has any data to reset
    user_profile = user_profile_memory.get(adapter_name, user_id)
    user_personalization = user_personalization_memory.get(adapter_name, user_id)

    try:
        recent_messages = await private_chat_recorder.get_recent_private_messages(adapter_name, user_id, limit=1)
        has_conversation_data = len(recent_messages) > 0
    except Exception:
        has_conversation_data = False

    if not user_profile and not user_personalization and not has_conversation_data:
        await reset_profile_command.finish("您当前没有个人档案数据需要清除。")

    # Check for confirmation
    if not confirm.available or confirm.result != "confirm":
        # Show confirmation prompt
        confirmation_text = (
            "⚠️ **重置个人档案**\n\n"
            "此操作将清除以下数据：\n"
            "• AI分析的您的特征和偏好\n"
            "• 个性化回复设置\n"
            "• 所有对话记录\n"
            "• 当前对话上下文\n\n"
            "⚠️ **注意：此操作不可撤销！**\n\n"
            "如果确认要重置，请使用命令：\n"
            "`/reset_profile confirm`"
        )
        await reset_profile_command.finish(confirmation_text)

    # Perform the reset
    try:
        user_profile_memory.delete(adapter_name, user_id)
        user_personalization_memory.delete(adapter_name, user_id)
        private_chat_recorder.clear_user_data(adapter_name, user_id)

        # Clear current session as well
        full_user_id = get_full_user_id(event, bot)
        session_id = f"s-{full_user_id}"
        dify_bot.sessions.clear_session(session_id)

        await reset_profile_command.finish(
            "✅ **个人档案已重置**\n\n"
            "您的所有个人档案数据和对话记录已被清除。\n"
            "个性化功能仍然启用，我将重新开始学习您的偏好。\n\n"
            "如需完全禁用个性化功能，请使用 /personalize off"
        )
    except Exception as e:
        logger.error(f"Error resetting user profile: {e}")
        await reset_profile_command.finish("❌ 重置个人档案时出现错误，请稍后重试。")


@get_my_id_command.handle()
async def handle_get_my_id(bot: Bot, event: Event):
    """获取并返回用户的跨平台唯一ID"""
    # 仅限私聊
    target = alconna.get_target()
    if not target.private:
        await get_my_id_command.finish("")

    full_user_id = get_full_user_id(event, bot)
    await get_my_id_command.finish(f"您的唯一用户ID是：\n{full_user_id}")


# --- 定时任务 ---
if config.private_personalization_enable and config.profiler_workflow_api_key:
    import asyncio
    import random

    async def _trigger_private_profiling_session():
        """由cron触发，负责派发具体的用户分析任务"""
        from .common import private_chat_manager
        from .common.private_profiler_task import process_user_profiles

        logger.info("开始派发私聊画像分析任务...")
        all_statuses = private_chat_manager.get_all_personalization_statuses()
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
                from .common.private_profiler_task import process_user_profiles

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
        from .common.group_memory_manager import get_all_profiler_statuses
        from .common.profiler_task import process_single_group_profile

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
    # Schedule data cleanup task to run daily at 2 AM (1 hour before profiling)
    scheduler.add_job(
        data_cleanup_task.run_data_cleanup_job,
        trigger="cron",
        hour=2,
        minute=0,
        id="dify_data_cleanup_job",
        replace_existing=True,
    )
    logger.info(f"已成功安排数据清理定时任务，每日凌晨2点执行，保留 {config.private_data_retention_days} 天数据")


# Add data integrity check if private personalization is enabled
if config.private_personalization_enable:
    # Schedule data integrity check to run weekly on Sunday at 1 AM
    scheduler.add_job(
        data_cleanup_task.run_data_integrity_check,
        trigger="cron",
        hour=1,
        minute=0,
        day_of_week=6,  # Sunday (0=Monday, 6=Sunday)
        id="dify_data_integrity_check_job",
        replace_existing=True,
    )
    logger.info("已成功安排数据完整性检查定时任务，每周日凌晨1点执行")
