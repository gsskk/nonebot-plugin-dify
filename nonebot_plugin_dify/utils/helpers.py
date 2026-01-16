import httpx
from nonebot import logger
import asyncio
import re
import os
from typing import List, Dict

import nonebot_plugin_alconna as alconna
from nonebot.adapters import Bot, Event

from ..config import config
from ..storage import record_manager


async def get_pic_from_url(url: str) -> bytes:
    logger.debug(f"Got image url {url} for download.")
    # 兼容域名`multimedia.nt.qq.com.cn`的TLS套件
    # https://github.com/LagrangeDev/Lagrange.Core/issues/315
    if "multimedia.nt.qq.com.cn" in url:
        import ssl

        SSL_CONTEXT = ssl.create_default_context()
        SSL_CONTEXT.set_ciphers("DEFAULT")  # 或设置为特定的密码套件，例如 'TLS_RSA_WITH_AES_128_CBC_SHA'
        SSL_CONTEXT.options |= ssl.OP_NO_SSLv2
        SSL_CONTEXT.options |= ssl.OP_NO_SSLv3
        SSL_CONTEXT.options |= ssl.OP_NO_TLSv1
        SSL_CONTEXT.options |= ssl.OP_NO_TLSv1_1
        SSL_CONTEXT.options |= ssl.OP_NO_COMPRESSION
        logger.debug("Set TLSv1.2 cipher for multimedia.nt.qq.com.cn.")

    async with httpx.AsyncClient() as client:
        for i in range(3):
            try:
                resp = await client.get(url, timeout=20)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                logger.error(f"Error downloading {url}, retry {i}/3: {e}")
                await asyncio.sleep(3)
    raise Exception(f"{url} 下载失败！")


def save_pic(img_bytes, img: alconna.Image, directory):
    # 获取文件名和扩展名
    filename, file_extension = os.path.splitext(img.id)

    # 如果没有扩展名，则根据mimetype来确定后缀
    if not file_extension:
        # 将mimetype转换为文件扩展名
        mimetype_to_extension = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/bmp": ".bmp",
            "image/tiff": ".tiff",
        }
        file_extension = mimetype_to_extension.get(img.mimetype, ".jpg")

    # 最终文件名
    full_filename = filename + file_extension

    # 确保目录存在
    os.makedirs(directory, exist_ok=True)

    # 保存图片
    file_path = os.path.join(directory, full_filename)
    with open(file_path, "wb") as f:
        f.write(img_bytes)

    return file_path


def parse_markdown_text(text: str) -> List[Dict]:
    """
    解析包含图片和文件链接的混合内容文本。code by sonnet3.5
    """

    # 定义正则表达式模式，匹配图片和文件链接的Markdown语法
    # (!\[.*?\]\((.*?)\)) 匹配图片: ![alt text](url)
    # (\[.*?\]\((.*?)\)) 匹配文件链接: [text](url)
    pattern = r"(!\[.*?\]\((.*?)\)|\[.*?\]\((.*?)\))"

    # 使用正则表达式分割文本
    # 这将产生一个列表，其中包含文本、完整匹配、图片URL和文件URL
    parts = re.split(pattern, text)

    # 初始化结果列表和当前文本变量
    result = []
    current_text = ""

    # 遍历分割后的部分，每次跳过4个元素
    # 因为每个匹配项产生4个部分：文本、完整匹配、图片URL（如果有）、文件URL（如果有）
    for i in range(0, len(parts), 4):
        # 如果存在文本部分，添加到当前文本
        if parts[i].strip():
            current_text += parts[i].strip()

        # 检查是否存在匹配项（图片或文件）
        if i + 1 < len(parts) and parts[i + 1]:
            # 如果有累积的文本，添加到结果列表
            if current_text:
                result.append({"type": "text", "content": current_text})
                current_text = ""  # 重置当前文本

            # 检查是否为图片
            if parts[i + 2]:
                result.append({"type": "image", "content": parts[i + 2]})
            # 如果不是图片，则为文件
            elif parts[i + 3]:
                result.append({"type": "file", "content": parts[i + 3]})

    # 处理最后可能剩余的文本
    if current_text:
        result.append({"type": "text", "content": current_text})
    return result


def get_adapter_name(target: alconna.Target) -> str:
    """获取适配器名称"""
    if not target.adapter:
        return "default"
    return target.adapter.replace("SupportAdapter.", "").replace(" ", "").lower()


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

    # 特殊处理Discord（注意：私聊事件也有 guild_id 属性，但值为 None）
    if adapter_name == "discord" and getattr(event, "guild_id", None):
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


async def ignore_rule(event: Event) -> bool:
    msg = event.get_plaintext().strip()

    # 消息以忽略词开头
    if next(
        (x for x in config.ignore_prefix if msg.startswith(x)),
        None,
    ):
        return False

    return True


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


def is_sender_bot(event: Event, bot: Bot) -> bool:
    """跨平台检测消息发送者是否为 Bot"""
    # 1. OneBot V11
    if hasattr(event, "sender") and hasattr(event.sender, "is_bot"):
        return bool(getattr(event.sender, "is_bot", False))

    # 2. Telegram
    if hasattr(event, "from_") and hasattr(event.from_, "is_bot"):
        return bool(getattr(event.from_, "is_bot", False))

    # 3. Discord
    if hasattr(event, "author") and hasattr(event.author, "bot"):
        return bool(getattr(event.author, "bot", False))

    # 4. Universal Fallback (if sender is dict or object with is_bot)
    if hasattr(event, "sender"):
        sender = event.sender
        if isinstance(sender, dict):
            return bool(sender.get("is_bot", False))
        elif hasattr(sender, "is_bot"):
            return bool(getattr(sender, "is_bot", False))

    return False
