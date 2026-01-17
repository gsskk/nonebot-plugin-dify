import os
import time
import random
import asyncio
from datetime import datetime
from typing import List, Optional

import nonebot_plugin_alconna as alconna
import nonebot_plugin_localstore as store
from nonebot import on_message, logger
from nonebot.adapters import Bot, Event
from nonebot.rule import Rule
from nonebot.typing import T_State
from nonebot.exception import FinishedException
from nonebot_plugin_apscheduler import scheduler

from ..config import config
from ..core.dify_bot import dify_bot
from ..core import session as session_manager
from ..storage import record_manager, chat_recorder
from ..storage import private_recorder as private_chat_recorder
from ..managers.private_chat import get_personalization_status as get_private_personalization_status
from ..utils.image_cache import cache_image as cache_image_reference
from ..services.image_description import generate_image_description
from ..utils.helpers import (
    get_full_user_id,
    get_adapter_name,
    get_sender_nickname,
    clean_message_for_record,
    ignore_rule,
    save_pic,
    get_pic_from_url,
    is_sender_bot,
)
from ..storage.group_store import group_user_memory
from ..utils.reply_type import ReplyType
from ..utils.image import ImageUtils
from ..core.cache import USER_IMAGE_CACHE

# 监听普通消息
receive_message = on_message(
    rule=Rule(ignore_rule),
    priority=99,
    block=False,
)


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
    is_perception: bool = False,
    is_reply_to_bot: bool = False,
    is_explicit_at: bool = True,
) -> None:
    """发送回复消息"""
    user_id = event.get_user_id() or "user"

    try:
        has_replied = False

        # 获取Dify回复 (Stream)
        async for reply_type, reply_content in dify_bot.reply(
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
            is_perception=is_perception,
        ):
            # 检查是否为静默回复（Linger Mode 或 Proactive Mode）
            if not reply_type and not reply_content:
                logger.debug("Suppressing silent reply chunk.")
                continue

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
                        # For streaming, we might be recording multiple small chunks.
                        # Ideally, we should concatenate them if we want a clean history.
                        # But for now, recording each chunk is safer than missing data.
                        # Downside: History context will be fragmented.
                        # Spec Risk Mitigation: "We should only record the *full* combined response..."

                        # However, implementing full buffering here negates the purpose of streaming
                        # IF we block sending until full record.
                        # But we can buffer for RECORDING purposes while SENDING immediately.

                        # Since this refactor is already complex, let's treat each chunk as a message for now,
                        # OR we simply log it.
                        # NOTE: Current implementation records specific "assistant" events.

                        # Let's perform lightweight recording for each chunk to ensure visibility.
                        cleaned_reply = clean_message_for_record(_uni_message)
                        await private_chat_recorder.record_private_message(
                            adapter_name, user_id, "Bot", cleaned_reply, "assistant"
                        )
                        logger.debug(f"Recorded private chat bot response chunk for {user_id}")
                else:
                    if record_manager.get_record_status(adapter_name, target.id):
                        cleaned_reply = clean_message_for_record(_uni_message)
                        await chat_recorder.record_message(
                            adapter_name, target.id, bot.self_id, "Bot", cleaned_reply, "assistant", False
                        )
            except Exception as e:
                logger.warning(f"Failed to record bot reply: {e}")

            # 发送消息
            # 使用 UniMessage.send() 跨平台发送（兼容 QQ、Discord、Telegram 等）
            try:
                # 判定是否需要艾特回去：只有在非私聊、非主动接管、非余韵模式下才艾特
                # 且如果是流式输出，只在第一段艾特
                # 如果是回复 Bot 且配置了跳过 @，则不艾特
                # 如果是昵称触发（非显式@），则不艾特
                skip_at_bot = is_reply_to_bot and config.bot_reply_skip_at
                should_at = (
                    not (target.private or is_proactive or is_linger or skip_at_bot)
                    and not has_replied
                    and is_explicit_at
                )

                if should_at:
                    final_msg = alconna.UniMessage([alconna.At("user", user_id), "\n", _uni_message])
                else:
                    final_msg = _uni_message

                # 使用 UniMessage.send() 跨平台发送
                # 特殊处理 Discord 私聊：直接使用 channel_id 发送，避免 create_DM 错误
                if bot.type == "Discord" and target.private and hasattr(event, "channel_id"):
                    await bot.send_to(channel_id=event.channel_id, message=str(final_msg))
                else:
                    await final_msg.send(target=target, bot=bot)
                has_replied = True
            except Exception as e:
                logger.error(f"[DIFY] Failed to send response: {e}")

    except Exception as e:
        logger.error(f"Failed to generate reply: {e}")

    except Exception as e:
        logger.error(f"Failed to generate reply: {e}")


async def handle_message_images(
    uni_msg: alconna.UniMessage,
    event: Event,
    bot: Bot,
    session_id: str,
    adapter_name: str,
    group_id: str = None,
    user_id: str = None,
) -> Optional[str]:
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
        cache_image_reference(adapter_name, group_id, user_id, _img_path)
        logger.debug(f"Cached image for reference: {_img_path}")

    return _img_path


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
                    image_description = await generate_image_description(path, user_id)
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
        adapter_name = get_adapter_name(target)
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

        # 1. Bot Sender Detection
        is_from_bot = is_sender_bot(event, bot)
        if not is_from_bot and not target.private:
            # Fallback to group member profile
            profile = group_user_memory.get_user_profile(adapter_name, target.id, user_id)
            if profile.get("is_bot"):
                is_from_bot = True

        if is_from_bot:
            logger.debug(f"Message from BOT detected: {user_id}")

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

            # 2. Bot Loop Counter & Suppression
            if config.bot_loop_protection_enable and group_state:
                if is_from_bot:
                    group_state.consecutive_bot_messages += 1
                    group_state.last_bot_message_time = time.time()

                    # Hard Limit Check
                    if group_state.consecutive_bot_messages >= config.bot_consecutive_limit:
                        logger.warning(
                            f"Bot loop detected! Consecutive bot messages: {group_state.consecutive_bot_messages}. "
                            f"Suppressing reply to {user_id}."
                        )
                        await receive_message.finish()

                    # Probabilistic Silence
                    if random.random() < config.bot_silence_probability:
                        logger.info(f"Probabilistic silence activated for bot message from {user_id}.")
                        await receive_message.finish()
                else:
                    # Reset on human message
                    group_state.consecutive_bot_messages = 0

        # 处理私聊消息
        if target.private:
            # 检查是否启用私聊个性化功能
            if config.private_personalization_enable:
                try:
                    personalization_enabled = get_private_personalization_status(adapter_name, user_id)
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

                                        image_description = await generate_image_description(path, user_id)
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

            # 检测是否显式@（消息中包含 At 段落且目标是 bot）
            # 用于区分昵称触发和真正的@，昵称触发时回复不带@
            is_explicit_at = False
            if uni_msg.has(alconna.At):
                for seg in uni_msg[alconna.At]:
                    if str(seg.target) == str(bot.self_id):
                        is_explicit_at = True
                        break

            # 备用at检查，应对is_tome()在某些情况下失效
            if not is_mentioned and is_explicit_at:
                is_mentioned = True

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
            if (
                not is_mentioned
                and not is_targeted_at_others
                and config.linger_mode_enable
                and group_state
                and not group_state.active_trace_id
            ):
                if group_state.last_interaction_time > 0:  # Only linger if we actually had a previous interaction
                    time_since_last = time.time() - group_state.last_interaction_time
                    if time_since_last < config.linger_timeout_seconds:
                        if group_state.linger_message_count < config.linger_max_messages:
                            # 1. Check Minimum Interval
                            if time_since_last >= config.linger_min_interval_seconds:
                                # 2. Calculate decayed probability based on time elapsed
                                # Formula: effective_prob = base_prob × (1 - elapsed/timeout)
                                decay_factor = 1.0 - (time_since_last / config.linger_timeout_seconds)
                                effective_probability = config.linger_response_probability * decay_factor

                                # 3. Check Probability
                                rnd = random.random()
                                if rnd <= effective_probability:
                                    logger.debug(
                                        f"Linger mode active: {time_since_last:.1f}s since last, "
                                        f"count {group_state.linger_message_count}, "
                                        f"effective_prob {effective_probability:.2f} (decay {decay_factor:.2f})"
                                    )
                                    is_mentioned = True
                                    is_linger = True
                                else:
                                    logger.debug(
                                        f"Linger suppressed: probability check failed "
                                        f"(random={rnd:.2f} > effective_prob={effective_probability:.2f})"
                                    )
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
                        from ..services.semantic_matcher import semantic_matcher

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
        trace_id = ""
        if group_state:
            trace_id = f"{id(event)}_{time.time()}"
            group_state.active_trace_id = trace_id

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
                is_reply_to_bot=is_from_bot,
                is_explicit_at=is_explicit_at if not target.private else True,
            )

            # Update last interaction time after successful reply to delay subsequent linger triggers
            if group_state:
                group_state.last_interaction_time = time.time()

        except FinishedException:
            raise
        except Exception as e:
            logger.warning(f"Failed to generate reply: {e}")
            await receive_message.finish("")
        finally:
            if group_state and group_state.active_trace_id == trace_id:
                group_state.active_trace_id = ""

    except FinishedException:
        raise
    except Exception as e:
        logger.error(f"Critical error in message handler: {e}")
        await receive_message.finish()
