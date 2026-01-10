from nonebot import require, on_command, on_message, logger
from nonebot.exception import FinishedException, MockApiException
from nonebot.plugin import PluginMetadata, inherit_supported_adapters
from nonebot.matcher import current_matcher, current_event
from nonebot.adapters import Bot, Event

require("nonebot_plugin_alconna")
require("nonebot_plugin_localstore")
require("nonebot_plugin_apscheduler")

from nonebot import require, get_driver
from nonebot.internal.matcher.matcher import Matcher
from nonebot.rule import Rule, to_me
from nonebot.typing import T_State

import os
from nonebot.permission import SUPERUSER, Permission

from typing import List, Dict, Any
import importlib
import re
import time
import random
from datetime import datetime
from .config import Config, config
from . import session as session_manager
from .dify_bot import DifyBot
from .common.reply_type import ReplyType
from .common import record_manager, chat_recorder, group_memory_manager
from .common import private_chat_manager, private_chat_recorder, data_cleanup_task
from .common.user_data_store import user_profile_memory, user_personalization_memory
from .common.utils import get_pic_from_url, save_pic
from .common import image_reference_cache, image_description_client
from .cache import USER_IMAGE_CACHE

import nonebot_plugin_alconna as alconna
import nonebot_plugin_localstore as store
from nonebot_plugin_apscheduler import scheduler
import asyncio
from .common.image_utils import ImageUtils


dify_bot = DifyBot()

__version__ = "0.1.11"

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
            continue  # Skip images, let has_image flag handle it
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


@Bot.on_calling_api
async def handle_perception(bot: Bot, api: str, data: Dict[str, Any]):
    """处理跨插件感知和拦截"""
    if not config.perception_enabled:
        return

    # 0. 排除 Dify 自身的内部调用 (防止自我拦截导致的死循环)
    if data.get("_dify_internal"):
        return

    # 1. 识别来源插件
    try:
        matcher = current_matcher.get()
        plugin_name = matcher.plugin_name
    except LookupError:
        return

    # 2. 排除自身
    if plugin_name == "nonebot_plugin_dify":
        return

    # 3. 过滤名单
    # 增加调试日志以确认配置项内容
    logger.debug(
        f"Perception Config: passive={config.perception_passive_plugins}, intercept={config.perception_intercept_plugins}"
    )

    is_intercept = plugin_name in config.perception_intercept_plugins
    # 如果在拦截名单里，就不再属于被动观察名单
    is_observe = not is_intercept and (
        plugin_name in config.perception_passive_plugins or not config.perception_passive_plugins
    )

    if not (is_intercept or is_observe):
        return

    # 4. 提取内容
    # 兼容不同适配器的消息字段名 (增加 Telegram 常用字段)
    message_content = (
        data.get("message") or data.get("msg") or data.get("content") or data.get("text") or data.get("caption")
    )
    if not message_content:
        return

    logger.debug(
        f"Perception caught message from {plugin_name}: type={type(message_content)}, content={str(message_content)[:200]}..."
    )

    # 5. 解析消息内容
    msg_text = ""
    has_image = False
    perceived_img_bytes = None

    # 尝试多种手段提取内容，特别是处理超长 Base64 图片
    try:
        # 1. 尝试从原始数据中直接通过正则或特征寻找 Base64 图片
        raw_str = str(message_content)
        if "base64://" in raw_str or "data:image" in raw_str:
            import base64
            import re

            # 匹配 base64:// 或 data:image/...;base64, 之后的内容
            b64_match = re.search(r"(?:base64://|base64,)([\w+/=\s]+)", raw_str)
            if b64_match:
                try:
                    perceived_img_bytes = base64.b64decode(b64_match.group(1).strip())
                    has_image = True
                    logger.debug(f"Perception extracted {len(perceived_img_bytes)} bytes from Base64 string.")
                except Exception as e:
                    logger.debug(f"Perception failed to decode Base64: {e}")

        # 2. 调用 UniMessage 进行结构化解析
        try:
            uni_msg = alconna.UniMessage(message_content)
            if not uni_msg.has(alconna.Image) and not uni_msg.extract_plain_text().strip():
                uni_msg = await alconna.UniMessage.generate(message=message_content, bot=bot)
        except Exception:
            uni_msg = await alconna.UniMessage.generate(message=message_content, bot=bot)

        msg_text = uni_msg.extract_plain_text().strip()
        if not has_image:
            has_image = uni_msg.has(alconna.Image)
            if has_image:
                logger.debug("Perception found image via UniMessage parsing.")
    except Exception as e:
        logger.debug(f"Perception parsing error from {plugin_name}: {e}")
        if not has_image:
            return

    # 5. 解析消息内容
    msg_text = ""
    has_image = False
    perceived_img_bytes = None

    # 尝试多种手段提取内容，特别是处理超长 Base64 图片
    try:
        # 1. 尝试从原始数据中直接通过正则或特征寻找 Base64 图片
        # 很多插件会发送 {"type": "image", "data": {"file": "base64://..."}} 或类似的字符串
        raw_str = str(message_content)
        if "base64://" in raw_str or "data:image" in raw_str:
            import base64
            import re

            # 匹配 base64:// 或 data:image/...;base64, 之后的内容
            b64_match = re.search(r"(?:base64://|base64,)([\w+/=\s]+)", raw_str)
            if b64_match:
                try:
                    perceived_img_bytes = base64.b64decode(b64_match.group(1).strip())
                    has_image = True
                    logger.debug("Successfully extracted image bytes from Base64 string.")
                except Exception:
                    pass

        # 2. 调用 UniMessage 进行结构化解析（提取文字和其他图片）
        try:
            uni_msg = alconna.UniMessage(message_content)
            if not uni_msg.has(alconna.Image) and not uni_msg.extract_plain_text().strip():
                uni_msg = await alconna.UniMessage.generate(message=message_content, bot=bot)
        except Exception:
            uni_msg = await alconna.UniMessage.generate(message=message_content, bot=bot)

        msg_text = uni_msg.extract_plain_text().strip()
        if not has_image:
            has_image = uni_msg.has(alconna.Image)
    except Exception as e:
        logger.debug(f"Perception failed to parse message from {plugin_name}: {e}")
        # 如果彻底解析失败但我们已经拿到了图片，依然继续
        if not has_image:
            return

    if not msg_text and not has_image:
        return

    # 6. 获取目标
    try:
        # 优先从全局上下文获取 Event
        try:
            event = current_event.get()
        except LookupError:
            event = getattr(matcher, "event", None)

        target = alconna.get_target()
        adapter_name = await get_adapter_name(target)
    except Exception:
        return

    # 6.5 提取原用户消息内容并检查是否需要排除 (命令)
    user_msg_text = ""
    user_has_image = False
    if event:
        try:
            if hasattr(event, "get_plain_text"):
                user_msg_text = event.get_plain_text()
            elif hasattr(event, "get_plaintext"):
                user_msg_text = event.get_plaintext()

            if hasattr(event, "message"):
                _user_uni = await alconna.UniMessage.generate(message=event.message, bot=bot)
                user_has_image = _user_uni.has(alconna.Image)
        except Exception:
            pass

        # Check if message is a command (Global Exclusion)
        command_start = get_driver().config.command_start
        if user_msg_text and command_start:
            prefixes = tuple(s for s in command_start if s)
            if prefixes and user_msg_text.startswith(prefixes):
                logger.debug(f"Message starts with command prefix {prefixes}, skipping perception recording.")
                return

    # 6.6 如果是拦截模式，先主动记录用户的原始消息
    if is_intercept and event:
        try:
            # 获取用户ID和昵称
            real_user_id = event.get_user_id() or "user"
            nickname = await get_sender_nickname(event, real_user_id, bot)

            # 记录用户消息
            if target.private:
                await private_chat_recorder.record_private_message(
                    adapter_name,
                    real_user_id,
                    nickname,
                    user_msg_text,
                    "user",
                    has_image=user_has_image,
                    skip_repeat_check=True,
                )
            else:
                await chat_recorder.record_message(
                    adapter_name,
                    target.id,
                    real_user_id,
                    nickname,
                    user_msg_text,
                    "user",
                    is_mentioned=False,
                    has_image=user_has_image,
                    skip_repeat_check=True,
                )
            logger.debug(f"Perception proactively recorded user message: {user_msg_text}")
        except Exception as e:
            logger.warning(f"Failed to record user message in perception: {e}")
            logger.debug(f"Perception proactively recorded user message: {user_msg_text}")
        except Exception as e:
            logger.warning(f"Failed to record user message in perception: {e}")

    # 7. 记录历史 (以 assistant 角色)
    image_description = None
    if has_image and config.history_image_mode == "description":
        try:
            img_path = None
            if perceived_img_bytes:
                # 使用我们之前手动提取的字节
                cache_dir = store.get_cache_dir("nonebot_plugin_dify")
                save_dir = os.path.join(cache_dir, config.image_cache_dir)
                os.makedirs(save_dir, exist_ok=True)

                # 构造一个完整的伪 Image 对象，提供 ID 和名称以满足 save_pic 要求
                import hashlib

                img_id = hashlib.md5(perceived_img_bytes).hexdigest()
                dummy_img = alconna.Image(raw=perceived_img_bytes, id=img_id, name=f"{img_id}.jpg")
                img_path = save_pic(perceived_img_bytes, dummy_img, save_dir)
            else:
                # 从 uni_msg 中正常提取
                imgs = uni_msg[alconna.Image]
                if imgs:
                    img = imgs[0]
                    img_bytes = None
                    if img.raw:
                        img_bytes = img.raw
                    elif img.path:
                        import anyio

                        img_bytes = await anyio.Path(str(img.path)).read_bytes()
                    elif img.url:
                        import httpx

                        async with httpx.AsyncClient() as client:
                            resp = await client.get(img.url, timeout=10.0)
                            if resp.status_code == 200:
                                img_bytes = resp.content

                    if img_bytes:
                        cache_dir = store.get_cache_dir("nonebot_plugin_dify")
                        save_dir = os.path.join(cache_dir, config.image_cache_dir)
                        img_path = save_pic(img_bytes, img, save_dir)

            if img_path:
                image_description = await image_description_client.generate_image_description(img_path, bot.self_id)
        except Exception as e:
            logger.debug(f"Perception failed to generate image description: {e}")

    try:
        if target.private:
            # 私聊记录需要获取目标用户ID
            actual_user_id = target.id
            await private_chat_recorder.record_private_message(
                adapter_name,
                actual_user_id,
                "Bot",
                msg_text,
                "assistant",
                has_image=has_image,
                image_description=image_description,
                skip_repeat_check=True,
            )
        else:
            group_id = target.id
            await chat_recorder.record_message(
                adapter_name,
                group_id,
                bot.self_id,
                "Bot",
                msg_text,
                "assistant",
                is_mentioned=False,
                has_image=has_image,
                image_description=image_description,
                skip_repeat_check=True,
            )
        logger.debug(f"Perceived message from {plugin_name} recorded to history.")

    except Exception as e:
        logger.warning(f"Failed to record perceived message: {e}")

    # 8. 拦截并接管
    if is_intercept:
        try:
            # Event 已经在上面第6步获取到了
            if event:
                full_user_id = get_full_user_id(event, bot)
                session_id = f"s-{full_user_id}"

                # 频率限制保护，防止死循环 (每分钟最多触发 3 次)
                now = time.time()
                session = session_manager.get_session(session_id, full_user_id)
                if now - session.proactive_last_reset > 60:
                    session.proactive_count = 0
                    session.proactive_last_reset = now

                if session.proactive_count >= 3:
                    logger.warning(
                        f"Proactive trigger suppressed for {full_user_id} due to rate limit (loop protection)."
                    )
                    return

                session.proactive_count += 1

                # 标记该事件已被拦截接管，防止主处理器重复触发 (如在 Linger Mode 下)
                setattr(event, "_dify_intercepted", True)

                # 异步发起 Dify 回复
                # 使用标准的 XML 标签封装感知结果，与 dify_bot.py 的风格保持一致
                inner_content = msg_text or (f"感知到图片描述: {image_description}" if image_description else "")
                final_query = f'<perceived_result plugin="{plugin_name}">{inner_content}</perceived_result>'

                # 提取原用户消息内容用于提示 (Safe Mode)
                user_msg_text = ""
                user_has_image = False
                try:
                    if hasattr(event, "get_plain_text"):
                        user_msg_text = event.get_plain_text()
                    elif hasattr(event, "get_plaintext"):
                        user_msg_text = event.get_plaintext()

                    if hasattr(event, "message"):
                        # Convert to UniMessage to safely check for images
                        _user_uni = await alconna.UniMessage.generate(message=event.message, bot=bot)
                        user_has_image = _user_uni.has(alconna.Image)
                except Exception as e:
                    logger.warning(f"Failed to extract original user message content: {e}")

                asyncio.create_task(
                    send_reply_message(
                        final_query,
                        full_user_id,
                        session_id,
                        event,
                        bot,
                        target,
                        adapter_name,
                        personalization_enabled=private_chat_manager.get_personalization_status(
                            adapter_name, getattr(event, "user_id", "user")
                        )
                        if target.private and config.private_personalization_enable
                        else False,
                        is_proactive=True,
                        proactive_user_hint=(
                            f"User sent an image and said: {user_msg_text}"
                            if user_has_image and user_msg_text.strip()
                            else f"User sent: {user_msg_text}"
                            if user_msg_text.strip()
                            else "User sent an image."
                        ),
                    )
                )
                logger.info(f"Intercepted message from {plugin_name}, triggering proactive response.")

                # 阻止原消息发送 (提供更丰富的 Mock 返回以兼容不同适配器)
                raise MockApiException(
                    result={
                        "message_id": 0,
                        "msg_id": 0,
                        "id": "0",
                        "status": "ok",
                        "retcode": 0,
                        "data": {"message_id": 0},
                    }
                )
            else:
                logger.error(f"Interception failed for {plugin_name}: could not retrieve current event.")
        except MockApiException:
            raise
        except Exception as e:
            logger.error(f"Failed to trigger proactive takeover: {e}")


@receive_message.handle()
async def handle_message(bot: Bot, event: Event):
    """处理接收到的消息"""
    # 如果该事件已被跨插件感知逻辑拦截接管，则主处理器不再处理，防止双重回复
    if getattr(event, "_dify_intercepted", False):
        logger.debug("Message already handled by perception takeover, skipping main handler.")
        return

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

        # 获取用户信息（提前获取，因为图片缓存也需要用到）
        user_id = event.get_user_id() or "user"
        full_user_id = get_full_user_id(event, bot)
        session_id = f"s-{full_user_id}"

        # 处理消息中的图片（即使没有文本也要缓存图片，供后续引用）
        if uni_msg.has(alconna.Image):
            try:
                current_group_id = None if target.private else target.id
                await handle_message_images(uni_msg, event, bot, session_id, adapter_name, current_group_id, user_id)
            except Exception as e:
                logger.warning(f"Failed to handle message images: {e}")

        # 忽略空消息（且无图片）
        # 注意：如果有图片，即使没有文字也应该记录历史并处理缓存
        has_img = uni_msg.has(alconna.Image)
        if not msg_text and not has_img:
            # 清理 USER_IMAGE_CACHE（虽然理论上没图就没有cache，但是个好习惯）
            if session_id in USER_IMAGE_CACHE:
                try:
                    cache_item = USER_IMAGE_CACHE.pop(session_id)
                    path = cache_item.get("path")
                    if path and os.path.exists(path):
                        os.remove(path)
                    logger.debug(f"Cleaned up temporary user image cache for session {session_id}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup user image cache: {e}")

            logger.debug("Ignored empty plaintext message (no image).")
            await receive_message.finish()

        # 如果有图没字，给一个空格作为文本，确保后续流程正常
        if not msg_text and has_img:
            msg_text = " "

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
                        # Generate image description for private chat if enabled
                        image_description = None
                        if uni_msg.has(alconna.Image) and config.history_image_mode == "description":
                            try:
                                path = None
                                if session_id and session_id in USER_IMAGE_CACHE:
                                    path = USER_IMAGE_CACHE[session_id].get("path")
                                if path:
                                    # Optimization: Check if image should be processed
                                    action = await asyncio.to_thread(ImageUtils.analyze_image, path)
                                    if action == "skip":
                                        logger.debug(f"Skipping private image description for {path} (optimization)")
                                    else:
                                        if action == "compress":
                                            path = await asyncio.to_thread(ImageUtils.compress_image, path)

                                        image_description = await image_description_client.generate_image_description(
                                            path, user_id
                                        )
                            except Exception as e:
                                logger.warning(f"Failed to generate private image description: {e}")

                        await private_chat_recorder.record_private_message(
                            adapter_name,
                            user_id,
                            nickname,
                            cleaned_message,
                            "user",
                            has_image=uni_msg.has(alconna.Image),
                            image_description=image_description,
                        )
                        logger.debug(f"Recorded private chat user message for {user_id}")
                except Exception as e:
                    logger.warning(f"Failed to check personalization status for user {user_id}: {e}")
                    personalization_enabled = False

            else:
                personalization_enabled = False
                logger.debug("Private chat personalization is globally disabled")

            # 如果该事件已被接管，记录后直接返回，不进行回复
            if getattr(event, "_dify_intercepted", False):
                logger.debug("Message handled by perception request, skipping private reply.")
                return
        else:
            # 处理群聊消息
            is_mentioned = event.is_tome()
            # 备用at检查，应对is_tome()在某些情况下失效
            if not is_mentioned and uni_msg.has(alconna.At):
                for seg in uni_msg[alconna.At]:
                    if str(seg.target) == str(bot.self_id):
                        is_mentioned = True
                        break

            # --- Check for mentions or replies to others ---
            mentions_others = False
            if uni_msg.has(alconna.At):
                for seg in uni_msg[alconna.At]:
                    if str(seg.target) != str(bot.self_id):
                        mentions_others = True
                        break

            is_reply_to_others = False
            if hasattr(event, "reply") and event.reply:
                # Use getattr to be safe across different adapters
                replied_sender = str(getattr(event.reply, "sender", getattr(event.reply, "user_id", "")))
                if replied_sender and replied_sender != str(bot.self_id):
                    is_reply_to_others = True

            is_targeted_at_others = mentions_others or is_reply_to_others

            # --- Priority 2: Linger Mode Check (Group Wide) ---
            if not is_mentioned and not is_targeted_at_others and config.linger_mode_enable and group_state:
                if group_state.last_interaction_time > 0:  # Only linger if we actually had a previous interaction
                    time_since_last = time.time() - group_state.last_interaction_time
                    if time_since_last < config.linger_timeout_seconds:
                        if group_state.linger_message_count < config.linger_max_messages:
                            # 1. Check Minimum Interval
                            if time_since_last >= config.linger_min_interval_seconds:
                                # 2. Check Probability
                                if random.random() <= config.linger_response_probability:
                                    logger.debug(
                                        f"Linger mode active: {time_since_last:.1f}s since last, count {group_state.linger_message_count}"
                                    )
                                    is_mentioned = True
                                    is_linger = True
                                else:
                                    logger.debug("Linger suppressed: probability check failed")
                            else:
                                logger.debug(
                                    f"Linger suppressed: interval {time_since_last:.1f}s < {config.linger_min_interval_seconds}s"
                                )

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
                    await record_group_message(
                        target,
                        event,
                        uni_msg,
                        bot,
                        user_id,
                        adapter_name,
                        is_mentioned,
                        has_image=uni_msg.has(alconna.Image),
                        session_id=session_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to record group message: {e}")

                # 如果该事件已被接管，记录后直接返回，不进行回复
                # 注意：Linger 模式的计数器可能已经增加，这没问题，因为感知回复也被视为一次交互
                if getattr(event, "_dify_intercepted", False):
                    logger.debug("Message handled by perception request, skipping group reply.")
                    return

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
                    await record_group_message(
                        target,
                        event,
                        uni_msg,
                        bot,
                        user_id,
                        adapter_name,
                        is_mentioned,
                        has_image=uni_msg.has(alconna.Image),
                        session_id=session_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to record group message: {e}")

                if getattr(event, "_dify_intercepted", False):
                    logger.debug("Message handled by perception request, skipping group reply.")
                    return

                # 3. Check if we should start a new proactive observation
                if not is_targeted_at_others and config.proactive_mode_enable and group_state:
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
                                gs.linger_message_count = 0  # Reset to allow Linger mode after intervention
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
                # Cleanup cache since we are not replying
                if session_id in USER_IMAGE_CACHE:
                    try:
                        cache_item = USER_IMAGE_CACHE.pop(session_id)
                        path = cache_item.get("path")
                        if path and os.path.exists(path):
                            os.remove(path)
                        logger.debug(f"Cleaned up temporary user image cache for session {session_id}")
                    except Exception as e:
                        logger.warning(f"Failed to cleanup user image cache: {e}")

                logger.debug("Ignored non-mention message in group.")
                await receive_message.finish()

            personalization_enabled = False  # Group personalization is handled separately

        # 注意：图片处理已在消息处理开始时完成（第 386-391 行）

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
    has_image: bool = False,
    session_id: str = None,
) -> None:
    """记录群聊消息"""
    if not record_manager.get_record_status(adapter_name, target.id):
        return

    # Generate image description if enabled
    image_description = None
    if has_image and config.history_image_mode == "description":
        try:
            # Try to get image path from cache
            path = None
            if session_id and session_id in USER_IMAGE_CACHE:
                path = USER_IMAGE_CACHE[session_id].get("path")

            if path:
                # Optimization: Check if image should be processed
                action = await asyncio.to_thread(ImageUtils.analyze_image, path)
                if action == "skip":
                    logger.debug(f"Skipping group image description for {path} (optimization)")
                else:
                    if action == "compress":
                        path = await asyncio.to_thread(ImageUtils.compress_image, path)

                    logger.debug(f"Generating description for image {path}")
                    image_description = await image_description_client.generate_image_description(path, user_id)
            else:
                logger.warning("Cannot generate description: Image path not found in cache")
        except Exception as e:
            logger.warning(f"Failed to generate image description: {e}")

    nickname = await get_sender_nickname(event, user_id, bot)
    a = event.model_dump()
    logger.debug(f"{type(a)}: {a}")

    cleaned_message = clean_message_for_record(uni_msg)
    logger.debug(f"记录群消息: {cleaned_message}")
    await chat_recorder.record_message(
        adapter_name,
        target.id,
        user_id,
        nickname,
        cleaned_message,
        "user",
        is_mentioned,
        has_image=has_image,
        image_description=image_description,
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
    uni_msg: alconna.UniMessage,
    event: Event,
    bot: Bot,
    session_id: str,
    adapter_name: str,
    group_id: str = None,
    user_id: str = None,
) -> str:
    """
    处理消息中的图片

    Returns:
        图片保存路径，如果没有图片则返回 None
    """
    if not uni_msg.has(alconna.Image):
        return None

    imgs = uni_msg[alconna.Image]
    _img = imgs[0]
    _img_bytes = await alconna.image_fetch(event=event, bot=bot, state=T_State(), img=_img)

    if not _img_bytes:
        logger.warning(f"Failed to fetch image from {adapter_name}.")
        return None

    logger.debug(f"Got image {_img.id} from {adapter_name}.")

    # 保存图片到缓存
    cache_dir = store.get_cache_dir("nonebot_plugin_dify")
    save_dir = os.path.join(cache_dir, config.image_cache_dir)
    _img_path = save_pic(_img_bytes, _img, save_dir)

    USER_IMAGE_CACHE[session_id] = {"id": _img.id, "path": _img_path}
    logger.debug(f"Set image cache: {USER_IMAGE_CACHE[session_id]}, local path: {_img_path}.")

    # 缓存图片到 image_reference_cache（用于后续引用分析）
    # 只有当 image_attach_mode != "off" 时才缓存
    if config.image_attach_mode != "off" and user_id:
        image_reference_cache.cache_image(adapter_name, group_id, user_id, _img_path)
        logger.debug(f"Cached image for reference: {_img_path}")

    return _img_path


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
    proactive_user_hint: str = None,
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
            proactive_user_hint=proactive_user_hint,
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

        # 发送消息
        # 在调用 API 时注入内部标记，防止被自身的拦截器二次拦截
        try:
            # 统一使用 call_api 以支持注入自定义元数据 _dify_internal
            local_params = {"_dify_internal": True}

            # 判定是否需要艾特回去：只有在非私聊、非主动接管、非余韵模式下才艾特
            if target.private or is_proactive or is_linger:
                final_msg = _uni_message
            else:
                final_msg = alconna.UniMessage([alconna.At("user", user_id), "\n", _uni_message])

            # 为特定的 bot 导出消息格式
            msg_export = await final_msg.export(bot, fallback=True)
            local_params["message"] = msg_export

            # 手动构造参数以兼容不同适配器（补充您之前的修正逻辑）
            if target.private:
                local_params["message_type"] = "private"
                local_params["user_id"] = int(target.id) if target.id.isdigit() else target.id
            else:
                local_params["message_type"] = "group"
                local_params["group_id"] = int(target.id) if target.id.isdigit() else target.id

            await bot.call_api("send_msg", **local_params)
        except Exception as e:
            logger.error(f"[DIFY] Failed to send response: {e}")

    except Exception as e:
        logger.error(f"Failed to generate reply: {e}")


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

# Add image cache cleanup task if image caching is enabled
if config.image_attach_mode != "off":
    scheduler.add_job(
        image_reference_cache.clear_expired_cache,
        trigger="interval",
        hours=1,
        id="dify_image_cache_cleanup_job",
        replace_existing=True,
    )
    logger.info("已成功安排图片缓存清理定时任务，每小时执行一次")
