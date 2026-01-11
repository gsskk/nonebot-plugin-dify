import nonebot_plugin_alconna as alconna
from nonebot import on_command, logger
from nonebot.adapters import Bot, Event
from nonebot.rule import to_me

from ..config import config
from ..core.dify_bot import dify_bot
from ..core import session as session_manager
from ..storage import record_manager
from ..managers import group_memory, private_chat
from ..storage import private_recorder as private_chat_recorder
from ..storage.user_store import user_profile_memory, user_personalization_memory
from ..utils.helpers import get_full_user_id, get_adapter_name
from ..utils.permission import MULTI_PLATFORM_PERM

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


@clear_command.handle()
async def handle_clear(event: Event, bot: Bot):
    """处理 /clear 命令"""
    target = alconna.get_target()
    adapter_name = get_adapter_name(target)
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
    adapter_name = get_adapter_name(target)
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
    adapter_name = get_adapter_name(target)
    if action.result == "check":
        _status = group_memory.get_profiler_status(adapter_name, group_id)
        await profiler_command.finish(f"当前群组画像功能状态：{_status}")
    elif action.result == "on":
        group_memory.set_profiler_status(adapter_name, group_id, True)
        await profiler_command.finish("群组画像功能已开启，我将会更懂你们哦~")
    else:
        group_memory.set_profiler_status(adapter_name, group_id, False)
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

    adapter_name = get_adapter_name(target)
    user_id = event.get_user_id() or "user"

    if action.result == "check":
        _status = private_chat.get_personalization_status(adapter_name, user_id)
        status_text = "已启用" if _status else "已禁用"
        await personalize_command.finish(f"您的私聊个性化功能状态：{status_text}")
    elif action.result == "on":
        current_status = private_chat.get_personalization_status(adapter_name, user_id)
        if current_status:
            await personalize_command.finish("您的私聊个性化功能已经启用。")
        else:
            private_chat.set_personalization_status(adapter_name, user_id, True)
            await personalize_command.finish(
                "✅ 私聊个性化功能已启用！\n\n"
                "我将开始学习您的对话风格和偏好，为您提供更个性化的回复。\n"
                "您可以随时使用 /personalize off 来禁用此功能并清除所有数据。"
            )
    else:  # action.result == "off"
        current_status = private_chat.get_personalization_status(adapter_name, user_id)
        if not current_status:
            await personalize_command.finish("您的私聊个性化功能已经禁用。")
        else:
            # Opt out user and clear all data
            private_chat.opt_out_user(adapter_name, user_id)
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

    adapter_name = get_adapter_name(target)
    user_id = event.get_user_id() or "user"

    # Check if user has enabled personalization
    personalization_enabled = private_chat.get_personalization_status(adapter_name, user_id)
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

    adapter_name = get_adapter_name(target)
    user_id = event.get_user_id() or "user"

    # Check if user has enabled personalization
    personalization_enabled = private_chat.get_personalization_status(adapter_name, user_id)
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
        dify_bot.sessions.clear_session(
            session_id
        )  # Note: Accessed sessions from dify_bot instance. Or use session_manager.clear_session

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
