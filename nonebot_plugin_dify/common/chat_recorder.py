import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Literal

import nonebot_plugin_localstore as store
from nonebot.log import logger

# 使用一个 asyncio Lock 来防止并发写入文件时发生冲突
_file_lock = asyncio.Lock()
# 用于存储每个群组的最后一条消息，以检测复读
_last_messages: Dict[str, str] = {}


def _get_log_dir(adapter_name: str) -> Path:
    """获取聊天记录的基础目录"""
    return store.get_data_dir("nonebot_plugin_dify") / "chat_logs" / adapter_name


def _get_log_file_path(adapter_name: str, group_id: str, date: datetime) -> Path:
    """根据群组ID、adapter名称和日期构建日志文件路径"""
    date_str = date.strftime("%Y-%m-%d")
    log_dir = _get_log_dir(adapter_name) / date_str
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{group_id}.jsonl"


async def record_message(
    adapter_name: str,
    group_id: str,
    user_id: str,
    nickname: str,
    message: str,
    role: Literal["user", "assistant"],
    is_mentioned: bool,
):
    """
    异步地将单条聊天消息记录到本地文件。
    会检测并标记复读消息。
    日志文件会每日轮转。
    """
    now = datetime.now()

    # 检测是否为复读消息
    is_repeat = _last_messages.get(group_id) == message
    _last_messages[group_id] = message  # 更新最后一条消息

    log_entry = {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "role": role,
        "user_id": user_id,
        "nickname": nickname,
        "message": message,
        "is_mentioned": is_mentioned,
        "is_repeat": is_repeat,  # 增加复读标记
    }
    file_path = _get_log_file_path(adapter_name, group_id, now)

    async with _file_lock:
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"无法将聊天记录写入 {file_path}: {e}")


async def get_recent_messages(adapter_name: str, group_id: str, limit: int = 10) -> List[Dict]:
    """
    获取一个群组最近的聊天记录。
    如果需要，会从今天和昨天的日志中读取。
    """
    if limit <= 0:
        return []

    messages = []
    today = datetime.now()

    # 尝试从今天的日志文件中读取
    today_file = _get_log_file_path(adapter_name, group_id, today)
    if today_file.exists():
        async with _file_lock:
            with open(today_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines):
                    if len(messages) >= limit:
                        break
                    try:
                        messages.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        logger.warning(f"跳过格式错误的行 {today_file}: {line}")

    # 如果消息数量不足，尝试从昨天的日志文件中读取
    if len(messages) < limit:
        yesterday = today - timedelta(days=1)
        yesterday_file = _get_log_file_path(adapter_name, group_id, yesterday)
        if yesterday_file.exists():
            async with _file_lock:
                with open(yesterday_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for line in reversed(lines):
                        if len(messages) >= limit:
                            break
                        try:
                            messages.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            logger.warning(f"跳过格式错误的行 {yesterday_file}: {line}")

    # 消息目前是反向时间顺序，将其恢复为正向
    return list(reversed(messages))


async def get_messages_since(adapter_name: str, group_id: str, start_time: datetime) -> List[Dict]:
    """
    获取指定时间点之后的所有聊天记录。
    会检查今天和昨天的日志文件。
    """
    messages = []
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    log_files_to_check = []
    # 如果开始时间在昨天或更早，则检查昨天的日志
    if start_time.date() <= yesterday.date():
        log_files_to_check.append(_get_log_file_path(adapter_name, group_id, yesterday))
    # 总是检查今天的日志
    log_files_to_check.append(_get_log_file_path(adapter_name, group_id, today))

    for file_path in log_files_to_check:
        if not file_path.exists():
            continue

        async with _file_lock:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        msg = json.loads(line.strip())
                        msg_time = datetime.fromisoformat(msg["timestamp"])
                        if msg_time >= start_time:
                            messages.append(msg)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        logger.warning(f"跳过格式错误或时间戳无效的行 {file_path}: {line}")

    # 按时间戳排序，确保消息是正向时间顺序
    messages.sort(key=lambda m: m["timestamp"])
    return messages


async def get_at_bot_messages_since(
    adapter_name: str, group_id: str, start_time: datetime, bot_name: str
) -> List[Dict]:
    """
    获取指定时间点之后所有 @bot 的消息记录。
    """
    all_messages = await get_messages_since(adapter_name, group_id, start_time)
    at_bot_messages = []
    for msg in all_messages:
        # 检查消息是否是用户发送的，并且包含 @bot 的提及
        if msg.get("role") == "user" and msg.get("is_mentioned"):
            at_bot_messages.append(msg)
    return at_bot_messages


def limit_chat_history_length(lines, max_length):
    result = []
    total_length = 0
    for line in reversed(lines):  # 从最后一条开始保留，优先保留最新消息
        line_length = len(line) + 1  # 加1是为了考虑换行符
        if total_length + line_length <= max_length:
            result.insert(0, line)
            total_length += line_length
        else:
            break
    return "\n".join(result)
