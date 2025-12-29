import json
import mimetypes
import os
import re
from typing import List, Optional, Tuple

import httpx
from nonebot import logger
import nonebot_plugin_alconna as alconna

from . import session as session_manager
from .config import config
from .dify_client import DifyClient, ChatClient
from .common.utils import parse_markdown_text
from .common.reply_type import ReplyType
from .common import chat_recorder, record_manager, group_memory_manager
from .common.group_data_store import group_profile_memory, personalization_memory, group_user_memory
from .cache import USER_IMAGE_CACHE
from .common import private_chat_manager, private_chat_recorder
from .common.user_data_store import user_profile_memory, user_personalization_memory


class DifyBot:
    def __init__(self):
        super().__init__()

    async def reply(
        self,
        query,
        full_user_id,
        session_id,
        personalization_enabled: bool = False,
        replied_message: alconna.UniMessage = None,
        replied_image_path: str = None,
        at_user_ids: Optional[List[str]] = None,
        is_linger: bool = False,
        is_proactive: bool = False,
    ):
        logger.info(f"[DIFY] query={query.strip()}")
        logger.debug(f"[DIFY] dify_user={full_user_id}")

        try:
            session = session_manager.get_session(session_id, full_user_id)
            logger.debug(f"[DIFY] session_id={session_id} query={query.strip()}")

            _reply_type_list, _reply_content_list = await self._reply_internal(
                query,
                full_user_id,
                session,
                personalization_enabled,
                replied_message=replied_message,
                replied_image_path=replied_image_path,
                at_user_ids=at_user_ids,
                is_linger=is_linger,
                is_proactive=is_proactive,
            )

            if not _reply_type_list:
                # Linger mode silent handling
                if is_linger:
                    logger.debug("Linger mode: suppressed empty response.")
                    return [], []

                # Proactive mode silent handling
                if is_proactive:
                    logger.debug("Proactive mode: suppressed empty response.")
                    return [], []

                logger.warning(f"Failed to process reply: {_reply_content_list}")
                return [ReplyType.TEXT], [""]

            # Check for <IGNORE> token if lingering
            if is_linger and _reply_type_list == [ReplyType.TEXT] and len(_reply_content_list) == 1:
                content = _reply_content_list[0].strip()
                if not content or "<IGNORE>" in content:
                    logger.debug("Linger mode: suppressed response due to empty content or <IGNORE> token.")
                    return [], []

            # Check for <IGNORE> token if proactive
            if is_proactive and _reply_type_list == [ReplyType.TEXT] and len(_reply_content_list) == 1:
                content = _reply_content_list[0].strip()
                if not content or "<IGNORE>" in content:
                    logger.debug("Proactive mode: suppressed response due to empty content or <IGNORE> token.")
                    return [], []

            return _reply_type_list, _reply_content_list

        except Exception as e:
            logger.error(f"Unexpected error in reply generation: {e}")
            return [ReplyType.TEXT], [""]

    async def _reply_internal(
        self,
        query: str,
        full_user_id: str,
        session: session_manager.Session,
        personalization_enabled: bool = False,
        replied_message=None,
        replied_image_path: str = None,
        at_user_ids: Optional[List[str]] = None,
        is_linger: bool = False,
        is_proactive: bool = False,
    ):
        try:
            session_manager.count_user_message(session)  # 限制一个conversation中消息数
            dify_app_type = config.dify_main_app_type

            all_files = []
            # 1. 处理当前消息的图片
            try:
                current_files = await self._get_upload_files(session)
                if current_files:
                    all_files.extend(current_files)
            except Exception as e:
                logger.warning(f"Failed to get upload files for current message: {e}")

            # 2. 处理引用消息的图片
            if replied_image_path:
                try:
                    replied_files = await self._upload_file_from_path(replied_image_path, session.user)
                    if replied_files:
                        all_files.extend(replied_files)
                except Exception as e:
                    logger.warning(f"Failed to upload replied image: {e}")
                finally:
                    # 清理临时文件
                    if os.path.exists(replied_image_path):
                        os.remove(replied_image_path)

            final_query, conversation_id = await self._build_final_query(
                query,
                full_user_id,
                session,
                personalization_enabled,
                replied_message=replied_message,
                at_user_ids=at_user_ids,
                is_proactive=is_proactive,
            )

            if dify_app_type in ("chatbot", "chatflow"):
                return await self._handle_chatbot(
                    final_query,
                    session,
                    conversation_id,
                    full_user_id.split("+")[-1],
                    full_user_id.split("+")[0],
                    files=all_files,
                )
            elif dify_app_type == "agent":
                return await self._handle_agent(
                    final_query, session, conversation_id, full_user_id.split("+")[-1], full_user_id.split("+")[0]
                )
            elif dify_app_type == "workflow":
                return await self._handle_workflow(
                    final_query, session, full_user_id.split("+")[-1], full_user_id.split("+")[0]
                )
            else:
                logger.error(f"Invalid dify_main_app_type configuration: {dify_app_type}")
                return [ReplyType.TEXT], ["配置错误：dify_main_app_type 必须是 agent、chatbot/chatflow 或 workflow"]

        except Exception as e:
            logger.error(f"Internal reply error: {e}")
            return [ReplyType.TEXT], [""]

    async def _build_final_query(
        self,
        query: str,
        full_user_id: str,
        session: session_manager.Session,
        personalization_enabled: bool = False,
        replied_message=None,
        at_user_ids: Optional[List[str]] = None,
        is_proactive: bool = False,
    ) -> Tuple[str, Optional[str]]:
        """构建包含画像和历史记录的最终查询字符串"""
        adapter_name = self._extract_adapter_name(full_user_id)
        group_id = self._extract_group_id(full_user_id)
        user_id = self._extract_user_id(full_user_id)
        conversation_id = session.conversation_id
        is_private_chat = group_id is None

        # --- 处理被引用的消息 ---
        replied_message_str = ""
        if replied_message:
            replied_text = replied_message.extract_plain_text()
            if replied_message.has(alconna.Image) and config.image_upload_enable:
                # 图片上传将在 _reply_internal 中处理，这里只添加占位符
                replied_message_str = f"<replied_message>\n[image]{replied_text}\n</replied_message>\n"
            elif replied_message.has(alconna.Image):
                replied_message_str = f"<replied_message>\n[image]{replied_text}\n</replied_message>\n"
            else:
                replied_message_str = f"<replied_message>\n{replied_text}\n</replied_message>\n"

        # --- 处理私聊个性化 ---
        if is_private_chat and personalization_enabled:
            query, conversation_id = await self._build_private_chat_query(query, adapter_name, user_id, conversation_id)
            return replied_message_str + query, conversation_id

        # --- 处理群聊（原有逻辑）---
        if not group_id:
            return query, conversation_id

        # --- 加载画像 ---
        group_profile_str = ""
        personalization_str = ""
        sender_persona_str = ""

        # Check if group personalization is enabled
        group_profiler_enabled = group_memory_manager.get_profiler_status(adapter_name, group_id)

        # Check if user has private personalization enabled (for priority handling)
        user_has_private_personalization = False
        if config.private_personalization_enable:
            user_has_private_personalization = private_chat_manager.get_personalization_status(adapter_name, user_id)

        if group_profiler_enabled:
            group_profile = group_profile_memory.get(adapter_name, group_id)
            if group_profile:
                group_profile_str = f"<group_profile>\n{group_profile}\n</group_profile>\n"

            # 注入发送者画像 (Sender Persona)
            try:
                profile = group_user_memory.get_user_profile(adapter_name, group_id, str(user_id))
                if profile:
                    persona_tags = ", ".join(profile.get("persona", []))
                    nickname = profile.get("nickname", "")
                    name_display = f"{nickname}({user_id})" if nickname else user_id
                    if persona_tags:
                        sender_persona_str = f"<sender_persona>\n{name_display}: {persona_tags}\n</sender_persona>\n"
            except Exception as e:
                logger.warning(f"Failed to build sender persona context: {e}")

            # Handle personalization priority: private personalization takes precedence in group chats
            if user_has_private_personalization:
                # Use private personalization data in group chat if available
                private_personalization = user_personalization_memory.get(adapter_name, user_id)
                if private_personalization:
                    personalization_str = f"<personalization>\n{private_personalization}\n</personalization>\n"
                    logger.debug(f"Using private personalization for user {user_id} in group {group_id}")
                else:
                    # Fallback to group personalization if private data is not available
                    group_personalization = personalization_memory.get(adapter_name, group_id)
                    if group_personalization:
                        personalization_str = f"<personalization>\n{group_personalization}\n</personalization>\n"
                        logger.debug(f"Fallback to group personalization for user {user_id} in group {group_id}")
            else:
                # Use group personalization as normal
                group_personalization = personalization_memory.get(adapter_name, group_id)
                if group_personalization:
                    personalization_str = f"<personalization>\n{group_personalization}\n</personalization>\n"

        # --- 获取历史记录 ---
        history_str = ""
        if record_manager.get_record_status(adapter_name, group_id):
            recent_messages = await chat_recorder.get_recent_messages(
                adapter_name, group_id, limit=config.group_chat_history_limit
            )
            # 使用历史记录时，应进行无状态调用，不传递 conversation_id
            conversation_id = None

            if recent_messages:
                filtered_messages = recent_messages.copy()
                removed = False

                for i in range(len(filtered_messages) - 1, -1, -1):  # 从后往前遍历索引
                    m = filtered_messages[i]
                    if (
                        not removed
                        and str(m.get("user_id")) == str(user_id)
                        and str(m.get("message", "")) == str(query)
                    ):
                        filtered_messages.pop(i)  # 删除倒数第一个匹配的消息
                        break

                history_lines = [
                    f"{m.get('nickname', 'user')}({m.get('user_id')}): {m.get('message', '')}"
                    for m in filtered_messages
                ]
                content = chat_recorder.limit_chat_history_length(history_lines, config.group_chat_history_size)
                history_str = f"<history>\n{content}\n</history>\n"

        # --- 注入主动介入提示 ---
        proactive_hint = ""
        if is_proactive:
            proactive_hint = (
                "[System Note: You are a bystander. You are responding because no one else in the group replied after a delay. "
                "If the topic is relevant and you can add value, reply naturally without using '@'. Otherwise, output <IGNORE>.]\n"
            )

        # --- 组合最终查询 ---
        current_query = f"{user_id}: {query}"
        final_query = f"{proactive_hint}{group_profile_str}{sender_persona_str}{personalization_str}{history_str}{replied_message_str}<user_query>\n{current_query}\n</user_query>"

        logger.debug(
            f"[DIFY] 已拼接上下文到查询 (含发送者画像: {bool(sender_persona_str)}, 含群画像: {bool(group_profile_str)}, 主动介入: {is_proactive})"
        )
        return final_query, conversation_id

    async def _build_private_chat_query(
        self, query: str, adapter_name: str, user_id: str, conversation_id: str
    ) -> Tuple[str, Optional[str]]:
        """构建私聊个性化查询字符串"""
        try:
            # --- 加载用户画像和个性化数据 ---
            sender_persona_str = ""
            personalization_str = ""

            try:
                user_profile = user_profile_memory.get(adapter_name, user_id)
                if user_profile:
                    sender_persona_str = f"<sender_persona>\n{user_profile}\n</sender_persona>\n"
            except Exception as e:
                logger.warning(f"Failed to load user profile: {e}")

            try:
                personalization = user_personalization_memory.get(adapter_name, user_id)
                if personalization:
                    personalization_str = f"<personalization>\n{personalization}\n</personalization>\n"
            except Exception as e:
                logger.warning(f"Failed to load user personalization: {e}")

            # --- 获取私聊历史记录 ---
            history_str = ""
            try:
                recent_messages = await private_chat_recorder.get_recent_private_messages(
                    adapter_name, user_id, limit=config.private_chat_history_limit
                )

                if recent_messages:
                    conversation_id = None

                    filtered_messages = []
                    for msg in recent_messages:
                        if not (msg.get("role") == "user" and msg.get("message") == query):
                            filtered_messages.append(msg)

                    if filtered_messages:
                        content = private_chat_recorder.limit_private_chat_history_length(
                            filtered_messages, config.private_chat_history_size
                        )
                        history_str = f"<history>\n{content}\n</history>\n"
            except Exception as e:
                logger.warning(f"Failed to load private chat history: {e}")

            # --- 组合最终查询 ---
            current_query = f"User: {query}"
            final_query = (
                f"{sender_persona_str}{personalization_str}{history_str}<user_query>\n{current_query}\n</user_query>"
            )

            logger.debug(
                f"[DIFY] 已拼接私聊上下文到查询 (含画像: {bool(sender_persona_str or personalization_str)}, 含历史: {bool(history_str)})"
            )

            return final_query, conversation_id

        except Exception as e:
            logger.error(f"Failed to build private chat query: {e}")
            return f"User: {query}", conversation_id

    async def _handle_chatbot(
        self,
        query: str,
        session: session_manager.Session,
        conversation_id: str,
        user_id: str = None,
        adapter_name: str = None,
        files: list = None,
    ):
        try:
            chat_client = ChatClient(config.dify_main_app_api_key, config.dify_api_base)

            response = await chat_client.create_chat_message(
                inputs={},
                query=query,
                user=session.user,
                response_mode="blocking",
                conversation_id=conversation_id,
                files=files,
            )

            if response.status_code != 200:
                error_message = f"请求 Dify 服务时出错 (HTTP {response.status_code})。"
                try:
                    error_data = response.json()
                    detail = error_data.get("message", response.text[:200])
                    error_message += f" 详细信息: {detail}"
                except json.JSONDecodeError:
                    error_message += f" 无法解析错误响应: {response.text[:200]}"
                logger.error(f"Dify API error: status_code={response.status_code}, response={response.text[:200]}")
                return [ReplyType.TEXT], [error_message]

            try:
                rsp_data = response.json()
                logger.debug(f"[DIFY] usage {rsp_data.get('metadata', {}).get('usage', 0)}")

                answer = rsp_data.get("answer", "")
                if not answer:
                    logger.warning("Dify returned empty answer")
                    return [], []

                answer = self._clean_content(answer)
                parsed_content = parse_markdown_text(answer)
                replies_type, replies_context = self._parse_replies(parsed_content)

                if conversation_id is not None and not session.conversation_id:
                    session.conversation_id = rsp_data.get("conversation_id", "")

                return replies_type, replies_context

            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse Dify response: {e}")
                return [ReplyType.TEXT], ["解析 Dify 返回数据时出错，请检查 Dify 应用配置。"]

        except httpx.TimeoutException as e:
            logger.error(f"Dify chatbot API timeout: {e}")
            return [ReplyType.TEXT], ["请求 Dify 服务超时，请稍后再试。"]

        except httpx.RequestError as e:
            logger.error(f"Dify chatbot request error: {e}")
            return [ReplyType.TEXT], ["请求 Dify 服务失败，请检查网络连接或 API 地址。"]

        except Exception as e:
            logger.error(f"Unexpected error in chatbot handler: {e}")
            return [ReplyType.TEXT], ["处理回复时遇到未知错误。"]

    async def _handle_agent(
        self,
        query: str,
        session: session_manager.Session,
        conversation_id: str,
        user_id: str = None,
        adapter_name: str = None,
    ):
        try:
            payload = {
                "inputs": {},
                "query": query,
                "response_mode": "streaming",
                "conversation_id": conversation_id,
                "user": session.user,
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(config.dify_timeout_in_seconds)) as client:
                response = await client.post(
                    f"{config.dify_api_base}/chat-messages",
                    headers=self._get_headers(),
                    json=payload,
                )

            if response.status_code != 200:
                error_message = f"请求 Dify-Agent 服务时出错 (HTTP {response.status_code})。"
                try:
                    error_data = response.json()
                    detail = error_data.get("message", response.text[:200])
                    error_message += f" 详细信息: {detail}"
                except json.JSONDecodeError:
                    error_message += f" 无法解析错误响应: {response.text[:200]}"
                logger.error(
                    f"Dify agent API error: status_code={response.status_code}, response={response.text[:200]}"
                )
                return [ReplyType.TEXT], [error_message]

            try:
                msgs, new_conv_id = self._handle_sse_response(response)
                replies_type, replies_context = self._parse_agent_replies(msgs)

                if conversation_id is not None and not session.conversation_id:
                    session.conversation_id = new_conv_id

                return replies_type, replies_context

            except Exception as e:
                logger.error(f"Failed to parse agent response: {e}")
                return [ReplyType.TEXT], ["解析 Dify-Agent 返回数据时出错，请检查 Dify 应用配置。"]

        except httpx.TimeoutException as e:
            logger.error(f"Dify agent API timeout: {e}")
            return [ReplyType.TEXT], ["请求 Dify-Agent 服务超时，请稍后再试。"]

        except httpx.RequestError as e:
            logger.error(f"Dify agent request error: {e}")
            return [ReplyType.TEXT], ["请求 Dify-Agent 服务失败，请检查网络连接或 API 地址。"]

        except Exception as e:
            logger.error(f"Unexpected error in agent handler: {e}")
            return [ReplyType.TEXT], ["处理 Dify-Agent 回复时遇到未知错误。"]

    async def _handle_workflow(
        self, query: str, session: session_manager.Session, user_id: str = None, adapter_name: str = None
    ):
        try:
            payload = {"inputs": {"query": query}, "response_mode": "blocking", "user": session.user}

            async with httpx.AsyncClient(timeout=httpx.Timeout(config.dify_timeout_in_seconds)) as client:
                response = await client.post(
                    f"{config.dify_api_base}/workflows/run",
                    headers=self._get_headers(),
                    json=payload,
                )

            if response.status_code != 200:
                error_message = f"请求 Dify-Workflow 服务时出错 (HTTP {response.status_code})。"
                try:
                    error_data = response.json()
                    detail = error_data.get("message", response.text[:200])
                    error_message += f" 详细信息: {detail}"
                except json.JSONDecodeError:
                    error_message += f" 无法解析错误响应: {response.text[:200]}"
                logger.error(
                    f"Dify workflow API error: status_code={response.status_code}, response={response.text[:200]}"
                )
                return [ReplyType.TEXT], [error_message]

            try:
                rsp_data = response.json()
                reply_content = rsp_data.get("data", {}).get("outputs", {}).get("text", "")

                if not reply_content:
                    logger.warning("Dify workflow returned empty response")
                    return [], []

                reply_content = self._clean_content(reply_content)
                return [ReplyType.TEXT], [reply_content]

            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse workflow response: {e}")
                return [ReplyType.TEXT], ["解析 Dify-Workflow 返回数据时出错，请检查 Dify 应用配置。"]

        except httpx.TimeoutException as e:
            logger.error(f"Dify workflow API timeout: {e}")
            return [ReplyType.TEXT], ["请求 Dify-Workflow 服务超时，请稍后再试。"]

        except httpx.RequestError as e:
            logger.error(f"Dify workflow request error: {e}")
            return [ReplyType.TEXT], ["请求 Dify-Workflow 服务失败，请检查网络连接或 API 地址。"]

        except Exception as e:
            logger.error(f"Unexpected error in workflow handler: {e}")
            return [ReplyType.TEXT], ["处理 Dify-Workflow 回复时遇到未知错误。"]

    def _parse_replies(self, parsed_content: list) -> Tuple[list, list]:
        replies_type = []
        replies_context = []
        for item in parsed_content:
            type_map = {"image": ReplyType.IMAGE_URL, "file": ReplyType.FILE, "text": ReplyType.TEXT}
            content_map = {
                "image": self._fill_file_base_url(item["content"]),
                "file": self._fill_file_base_url(item["content"]),
                "text": item["content"],
            }
            item_type = item.get("type", "text")
            replies_type.append(type_map.get(item_type, ReplyType.TEXT))
            replies_context.append(content_map.get(item_type, item["content"]))
        return replies_type, replies_context

    def _parse_agent_replies(self, msgs: list) -> Tuple[list, list]:
        replies_type = []
        replies_context = []
        for msg in msgs:
            if msg["type"] == "agent_message":
                replies_type.append(ReplyType.TEXT)
                replies_context.append(msg["content"])
            elif msg["type"] == "message_file":
                replies_type.append(ReplyType.IMAGE_URL)
                replies_context.append(msg["content"]["url"])
        return replies_type, replies_context

    def _clean_content(self, content: str) -> str:
        """
        Clean the content returned by Dify.
        Specifically removes <think>...</think> blocks that might be returned by reasoning models.
        """
        if not content:
            return ""
        # 移除 <think> 标签及其内容。虽然 reasoning model 通常将其放在开头（前缀），
        # 但全局替换更安全，防止异常情况泄露思维链。
        # 使用 strip() 去除可能残留的首尾空白字符。
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    def _extract_adapter_name(self, full_user_id: str) -> str:
        return full_user_id.split("+")[0] if full_user_id else "unknown"

    def _extract_group_id(self, full_user_id: str) -> str | None:
        parts = full_user_id.split("+")
        # 兼容 `adapter+group_id` 和 `adapter+group_id+user_id`
        if len(parts) >= 2 and parts[1] != "private":
            return parts[1]
        return None

    def _extract_user_id(self, full_user_id: str) -> str:
        return full_user_id.split("+")[-1] if full_user_id else "user"

    def _get_headers(self):
        return {"Authorization": f"Bearer {config.dify_main_app_api_key}"}

    async def _get_upload_files(self, session: session_manager.Session):
        session_id = session.id
        img_cache = USER_IMAGE_CACHE.get(session_id)
        if not img_cache:
            return None

        path = img_cache.get("path")
        try:
            return await self._upload_file_from_path(path, session.user)
        finally:
            USER_IMAGE_CACHE.pop(session_id, None)
            if os.path.exists(path):
                os.remove(path)

    async def _upload_file_from_path(self, path: str, user: str):
        if not path or not config.image_upload_enable:
            return None

        dify_client = DifyClient(config.dify_main_app_api_key, config.dify_api_base)
        try:
            with open(path, "rb") as file:
                logger.debug(f"Uploading file {path} to Dify.")
                file_name = os.path.basename(path)
                file_type, _ = mimetypes.guess_type(file_name)
                files = {"file": (file_name, file, file_type)}
                response = await dify_client.file_upload(user=user, files=files)
                response.raise_for_status()
                file_upload_data = response.json()
                logger.debug(f"[DIFY] upload file {file_upload_data}")
                return [{"type": "image", "transfer_method": "local_file", "upload_file_id": file_upload_data["id"]}]
        except Exception as e:
            logger.error(f"Failed to upload file {path}: {e}")
            return None

    def _fill_file_base_url(self, url: str):
        if url.startswith(("http://", "https://")):
            return url
        return f"{config.dify_api_base.replace('/v1', '')}{url}"

    def _handle_sse_response(self, response: httpx.Response):
        events = [self._parse_sse_event(line) for line in response.iter_lines() if line]
        events = [e for e in events if e]

        merged_message = []
        accumulated_agent_message = ""
        conversation_id = None
        for event in events:
            event_name = event["event"]
            if event_name in ("agent_message", "message"):
                accumulated_agent_message += event["answer"]
                conversation_id = conversation_id or event["conversation_id"]
            elif event_name == "message_file":
                self._append_agent_message(accumulated_agent_message, merged_message)
                accumulated_agent_message = ""
                merged_message.append({"type": "message_file", "content": event})
            elif event_name == "message_end":
                self._append_agent_message(accumulated_agent_message, merged_message)
                break
            elif event_name == "error":
                logger.error(f"[DIFY] error: {event}")
                raise Exception(str(event))

        if not conversation_id:
            raise Exception("conversation_id not found in SSE response")

        return merged_message, conversation_id

    def _append_agent_message(self, accumulated_agent_message, merged_message):
        if accumulated_agent_message:
            cleaned_message = self._clean_content(accumulated_agent_message)
            if cleaned_message:
                merged_message.append({"type": "agent_message", "content": cleaned_message})

    def _parse_sse_event(self, line: str):
        try:
            decoded_line = line
            if decoded_line.startswith("data:"):
                return json.loads(decoded_line[5:])
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return None


dify_bot: DifyBot = DifyBot()
