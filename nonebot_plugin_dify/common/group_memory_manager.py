import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List, Any
import httpx
import re

import nonebot_plugin_localstore as store
from nonebot import get_plugin_config
from nonebot.log import logger

from ..config import Config

# from ..dify_client import DifyClient
from .chat_recorder import get_messages_since, get_at_bot_messages_since, limit_chat_history_length
from .group_data_store import group_profile_memory, personalization_memory, group_user_memory

plugin_config = get_plugin_config(Config)


# --- 路径和状态文件定义 ---


def _get_base_dir() -> Path:
    """获取插件的数据根目录"""
    return store.get_data_dir("nonebot_plugin_dify")


def _get_status_file() -> Path:
    """获取画像功能状态存储文件"""
    path = _get_base_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path / "profiler_status.json"


# --- 状态管理 ---

_status_cache: Optional[Dict[str, bool]] = None


def _load_status_if_needed():
    """如果缓存为空，则从文件加载状态"""
    global _status_cache
    if _status_cache is None:
        status_file = _get_status_file()
        if not status_file.exists():
            _status_cache = {}
            return
        try:
            _status_cache = json.loads(status_file.read_text("utf-8"))
        except json.JSONDecodeError:
            logger.error(f"无法解析 {status_file}，文件可能已损坏。将使用空状态。")
            _status_cache = {}


def _write_status():
    """将缓存中的所有状态写入文件"""
    if _status_cache is None:
        return  # 如果缓存从未加载，则不执行任何操作
    status_file = _get_status_file()
    status_file.write_text(json.dumps(_status_cache, indent=4), encoding="utf-8")


def set_profiler_status(adapter_name: str, group_id: str, status: bool):
    """设置指定群组的画像功能状态，并在启用时应用默认个性化"""
    _load_status_if_needed()
    # 明确检查 _status_cache 是否为字典，以满足类型检查器
    if isinstance(_status_cache, dict):
        _status_cache[f"{adapter_name}+{group_id}"] = status
        _write_status()

        # 当启用画像功能且配置了默认个性化时，应用它
        if status and plugin_config.default_personalization:
            # 只有在当前没有个性化设置时才应用默认值
            if not personalization_memory.get(adapter_name, group_id):
                logger.info(f"为群组 {group_id} 启用画像功能，并设置默认个性化。")
                personalization_memory.set(adapter_name, group_id, plugin_config.default_personalization)


def get_profiler_status(adapter_name: str, group_id: str) -> bool:
    """获取指定群组的画像功能状态，默认为 False"""
    _load_status_if_needed()

    # 明确检查 _status_cache 是否为字典
    if isinstance(_status_cache, dict):
        return _status_cache.get(f"{adapter_name}+{group_id}", False)
    return False


def get_all_profiler_statuses() -> dict:
    _load_status_if_needed()
    if isinstance(_status_cache, dict):
        return _status_cache
    return {}


class GroupMemoryManager:
    def __init__(self, adapter_name: str, bot_name: str):
        self.adapter_name = adapter_name
        self.bot_name = bot_name

    def _get_headers(self):
        return {"Authorization": f"Bearer {plugin_config.profiler_workflow_api_key}"}

    async def _build_xml_input(self, group_id: str) -> str:
        """构建发送给 Dify Workflow 的 XML 输入"""
        # 获取旧的群组画像和个性化要求
        old_group_profile = group_profile_memory.get(self.adapter_name, group_id)
        old_personalization = personalization_memory.get(self.adapter_name, group_id)

        # 获取过去24小时的群聊记录
        # 考虑到定时任务通常每天运行，获取过去24小时的记录是合理的
        start_time = datetime.now() - timedelta(hours=24)
        all_chat_messages = await get_messages_since(self.adapter_name, str(group_id), start_time)
        at_bot_messages = await get_at_bot_messages_since(self.adapter_name, str(group_id), start_time, self.bot_name)

        # 提取聊天记录中涉及的用户 ID 和昵称并获取其现有画像
        involved_users = {}
        for msg in all_chat_messages:
            uid = str(msg["user_id"])
            if uid not in involved_users:
                involved_users[uid] = msg.get("nickname", "")
        for msg in at_bot_messages:
            uid = str(msg["user_id"])
            if uid not in involved_users:
                involved_users[uid] = msg.get("nickname", "")

        user_profiles_xml = ""
        if involved_users:
            profiles_list = []
            for uid, nickname in involved_users.items():
                info = group_user_memory.get_user_profile(self.adapter_name, group_id, uid)
                if info:
                    is_bot_str = " (Bot)" if info.get("is_bot") else ""
                    persona = ", ".join(info.get("persona", []))
                    name_str = f" [{nickname}]" if nickname else ""
                    profiles_list.append(f"- {uid}{name_str}{is_bot_str}: {persona}")
            user_profiles_xml = "\n".join(profiles_list)

        # 将消息转换为可读的字符串格式
        chat_lines = [
            f"[{msg['timestamp']}] {msg.get('nickname', 'user')}({msg['user_id']}): {msg['message']}"
            for msg in all_chat_messages
        ]
        at_bot_lines = [
            f"[{msg['timestamp']}] {msg.get('nickname', 'user')}({msg['user_id']}): {msg['message']}"
            for msg in at_bot_messages
        ]
        chat_history_str = limit_chat_history_length(chat_lines, plugin_config.profiler_chat_history_size)
        at_bot_messages_str = limit_chat_history_length(at_bot_lines, plugin_config.profiler_chat_history_size)

        # 构建 XML 结构
        xml_input = f"""<context>
<group_profile>
{old_group_profile}
</group_profile>

<user_profiles>
{user_profiles_xml}
</user_profiles>

<chat_history>
{chat_history_str}
</chat_history>

<personalization>
<previous>
{old_personalization}
</previous>
<new_at_messages>
{at_bot_messages_str}
</new_at_messages>
</personalization>
</context>"""
        return xml_input

    async def update_group_memory(self, group_id: str):
        """更新群组画像和个性化要求"""
        logger.info(f"开始更新群组 {self.adapter_name}+{group_id} 的画像和个性化要求...")
        try:
            # 获取过去24小时的聊天记录以提取昵称
            start_time = datetime.now() - timedelta(hours=24)
            all_chat_messages = await get_messages_since(self.adapter_name, str(group_id), start_time)
            nicknames = {str(msg["user_id"]): msg.get("nickname", "") for msg in all_chat_messages}

            xml_input = await self._build_xml_input(group_id)
            # logger.debug(f"发送给 Dify Workflow 的输入：\n{xml_input}")

            # 调用 Dify Workflow
            # response = await self.dify_client.run_workflow(inputs={"text": xml_input})
            payload = {
                "inputs": {"query": xml_input},
                "response_mode": "blocking",
                "user": f"{self.adapter_name}+{group_id}",
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{plugin_config.dify_api_base}/workflows/run",
                    headers=self._get_headers(),
                    json=payload,
                    timeout=plugin_config.dify_timeout_in_seconds,
                )

            if response.status_code != 200:
                logger.error(f"Dify Workflow 运行失败或未完成：{response}")
                error_info = f"[DIFY] response text={response.text} status_code={response.status_code}"
                logger.warning(error_info)
                return

            rsp_data = response.json()
            result = rsp_data.get("data", {}).get("outputs", {}).get("text", "")
            if result:
                try:
                    # Dify Workflow 应该返回 JSON 字符串
                    cleaned_result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
                    parsed_result = json.loads(cleaned_result)
                    new_group_profile = parsed_result.get("group_profile", "")
                    new_personalization_summary = parsed_result.get("personalization_summary", "")
                    user_profiles = parsed_result.get("user_profiles", [])

                    if new_group_profile:
                        group_profile_memory.set(self.adapter_name, group_id, new_group_profile)
                        logger.info(f"群组 {group_id} 画像更新成功。")
                    else:
                        logger.warning(f"Dify Workflow 未返回新的群组画像，群组 {group_id} 画像未更新。")

                    if new_personalization_summary:
                        personalization_memory.set(self.adapter_name, group_id, new_personalization_summary)
                        logger.info(f"群组 {group_id} 个性化要求总结更新成功。")
                    else:
                        logger.warning(f"Dify Workflow 未返回新的个性化要求总结，群组 {group_id} 个性化要求未更新。")

                    # Update User Profiles
                    if user_profiles:
                        self._process_user_profiles(group_id, user_profiles, nicknames)
                    else:
                        logger.warning("Dify Workflow 未返回用户画像列表。")

                except json.JSONDecodeError:
                    logger.error(f"Dify Workflow 返回的输出不是有效的 JSON 格式：{result}")
            else:
                logger.warning("Dify Workflow 未返回任何输出。")

        except httpx.TimeoutException:
            print("请求超时")
        except httpx.RequestError as e:
            print(f"请求发生错误: {e}")
        except Exception as e:
            logger.error(f"更新群组 {group_id} 画像和个性化要求时发生错误：{e}", exc_info=True)

        logger.info(f"群组 {group_id} 的画像和个性化要求更新流程结束。")
        return

    def _process_user_profiles(
        self, group_id: str, user_profiles: List[Dict[str, Any]], nicknames: Dict[str, str] = None
    ):
        """Processes and saves user profiles extracted from Dify Workflow response."""
        if not isinstance(user_profiles, list):
            logger.warning(f"user_profiles expected list, got {type(user_profiles)}")
            return

        now_str = datetime.now().isoformat()
        for profile in user_profiles:
            try:
                user_id = profile.get("user_id")
                if not user_id:
                    continue

                # Ensure persona is a list of strings
                persona = profile.get("persona", [])
                if isinstance(persona, str):
                    persona = [persona]
                elif not isinstance(persona, list):
                    persona = []

                is_bot = profile.get("is_bot", False)
                nickname = nicknames.get(str(user_id)) if nicknames else None

                group_user_memory.update_user_profile(
                    self.adapter_name, group_id, str(user_id), persona, bool(is_bot), now_str, nickname
                )
            except Exception as e:
                logger.warning(f"Failed to process user profile for group {group_id}: {e}")
