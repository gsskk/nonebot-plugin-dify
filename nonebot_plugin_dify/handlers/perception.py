import os
import time
import hashlib
import asyncio
from typing import Dict, Any

import nonebot_plugin_alconna as alconna
import nonebot_plugin_localstore as store
from nonebot import logger, get_driver
from nonebot.adapters import Bot
from nonebot.matcher import current_matcher, current_event
from nonebot.exception import MockApiException

from ..config import config
from ..core import session as session_manager
from ..storage import chat_recorder
from ..storage import private_recorder as private_chat_recorder
from ..managers.private_chat import get_personalization_status as get_private_personalization_status
from ..services.image_description import generate_image_description
from ..utils.helpers import get_full_user_id, get_adapter_name, save_pic
from .message import send_reply_message

# Context variable to track if we're currently sending a perception response
# This prevents self-interception loops
from contextvars import ContextVar

_perception_responding: ContextVar[bool] = ContextVar("perception_responding", default=False)


@Bot.on_calling_api
async def handle_perception(bot: Bot, api: str, data: Dict[str, Any]):
    """处理跨插件感知和拦截"""
    if not config.perception_enabled:
        return

    # 0. 排除 Dify 自身的内部调用 (防止自我拦截导致的死循环)
    if data.get("_dify_internal"):
        return

    # 0.5 排除正在发送感知响应的情况 (防止自我循环)
    if _perception_responding.get():
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

    # 3. 过滤名单与策略判定
    # 3.1 预先提取 User Event 内容 (用于判定基于命令的拦截)
    user_msg_text = ""
    user_has_image = False
    event = None
    try:
        # 尝试获取 Event
        try:
            event = current_event.get()
        except LookupError:
            event = getattr(matcher, "event", None)

        if event:
            if hasattr(event, "get_plain_text"):
                user_msg_text = event.get_plain_text()
            elif hasattr(event, "get_plaintext"):
                user_msg_text = event.get_plaintext()

            if hasattr(event, "message"):
                _user_uni = await alconna.UniMessage.generate(message=event.message, bot=bot)
                user_has_image = _user_uni.has(alconna.Image)
    except Exception:
        pass

    # 3.2 判定拦截与观察
    # A. 插件显式在拦截名单
    is_plugin_intercept = plugin_name in config.perception_intercept_plugins

    # B. 命令强制拦截 (即使插件不在拦截名单)
    is_command_intercept = False
    if user_msg_text:
        target_cmds = config.perception_intercept_commands
        if target_cmds:
            # 1. 直接匹配 (用户配置了完整命令如 "/weather")
            direct_prefixes = tuple(s for s in target_cmds if s)
            if user_msg_text.startswith(direct_prefixes):
                is_command_intercept = True

            # 2. 组合匹配 (用户只配置了命令名如 "weather", 需结合系统命令前缀)
            if not is_command_intercept:
                command_start = get_driver().config.command_start
                # command_start 可能是 None 或空集合，默认为 {"/"} 以防万一
                sys_prefixes = command_start if command_start else {"/"}

                # 生成所有可能的组合: prefix + cmd (e.g., "/" + "weather")
                combined_prefixes = []
                for cmd in target_cmds:
                    for prefix in sys_prefixes:
                        combined_prefixes.append(f"{prefix}{cmd}")

                if combined_prefixes and user_msg_text.startswith(tuple(combined_prefixes)):
                    is_command_intercept = True

            if is_command_intercept:
                logger.info(
                    f"Command '{user_msg_text}' matched intercept list, FORCING interception of plugin {plugin_name}."
                )

    # 最终拦截状态
    is_intercept = is_plugin_intercept or is_command_intercept

    # C. 被动观察 (非拦截状态，且满足被动名单或通配符)
    is_observe = not is_intercept and (
        plugin_name in config.perception_passive_plugins or not config.perception_passive_plugins
    )

    if not (is_intercept or is_observe):
        return

    # 3.3 命令噪音排除 (仅针对被动观察模式)
    # 如果已经被判定为拦截 (is_intercept)，则不过滤命令，因为这正是用户想要的交互。
    # 只有在 Monitor 模式下，我们才需要过滤掉杂七杂八的指令调用。
    if not is_intercept:
        command_start = get_driver().config.command_start
        if user_msg_text and command_start:
            prefixes = tuple(s for s in command_start if s)
            if prefixes and user_msg_text.startswith(prefixes):
                logger.debug(
                    f"Message from unlisted plugin {plugin_name} starts with command prefix {prefixes}, skipping perception."
                )
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

    if not msg_text and not has_image:
        return

    # 6. 获取目标
    try:
        # event 已经在 3.1 获取，这里仅获取 target 和 adapter_name
        target = alconna.get_target()
        adapter_name = get_adapter_name(target)
    except Exception:
        return

    # 6.5 (已上移至 3.1 和 3.3) 提取原用户消息内容并检查是否需要排除
    # 此处仅保留空位，变量 user_msg_text, user_has_image, event 已在上方获取
    pass

    # 6.6 如果是拦截模式，先主动记录用户的原始消息
    if is_intercept and event:
        try:
            # 获取用户ID和昵称
            from ..utils.helpers import get_sender_nickname

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
                image_description = await generate_image_description(img_path, bot.self_id)
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

                async def _send_perception_response():
                    """Wrapper to set context variable before sending perception response"""
                    _perception_responding.set(True)
                    try:
                        await send_reply_message(
                            final_query,
                            full_user_id,
                            session_id,
                            event,
                            bot,
                            target,
                            adapter_name,
                            personalization_enabled=get_private_personalization_status(
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
                            is_perception=True,
                        )
                    finally:
                        _perception_responding.set(False)

                asyncio.create_task(_send_perception_response())
                # 8.2 (新) 媒体透传：如果包含非文本内容（图片等），先主动发送给用户
                # 这样可以避免拦截后图片丢失，实现“图片直通，文字接管”
                try:
                    # 过滤掉纯文本和At，只保留媒体片段 (Image, Video, Audio, File, etc.)
                    media_segments = []
                    has_media = False
                    for seg in uni_msg:
                        if not isinstance(seg, (alconna.Text, alconna.At)):
                            media_segments.append(seg)
                            has_media = True

                    if has_media:
                        logger.info(
                            f"Intercepted message contains media, passing through {len(media_segments)} segments."
                        )
                        media_msg = alconna.UniMessage(media_segments)
                        # 使用 target 和 bot 发送
                        await media_msg.send(target, bot=bot)
                except Exception as e:
                    logger.warning(f"Failed to pass-through media segments: {e}")

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
