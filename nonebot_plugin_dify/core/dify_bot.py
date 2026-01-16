import mimetypes
import os
from typing import List, Optional, Tuple, AsyncGenerator


from nonebot import logger
import nonebot_plugin_alconna as alconna

from . import session as session_manager
from ..config import config
from .dify_client import DifyClient
from ..utils.reply_type import ReplyType
from ..tools.driver import get_driver
from ..storage import chat_recorder, record_manager
from ..managers import group_memory
from ..storage.group_store import group_profile_memory, personalization_memory, group_user_memory
from .cache import USER_IMAGE_CACHE
from ..storage import private_recorder as private_chat_recorder
from ..storage.user_store import user_profile_memory, user_personalization_memory
from ..utils import image_cache, prompt_utils


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
        proactive_user_hint: str = None,
        is_perception: bool = False,
    ) -> AsyncGenerator[Tuple[List[ReplyType], List[str]], None]:
        logger.info(f"[DIFY] query={query.strip()}")
        logger.debug(f"[DIFY] dify_user={full_user_id}")

        # If proactive mode is on but no hint is provided, we should probably warn or fallback
        if is_proactive and not proactive_user_hint:
            logger.warning(
                "Proactive mode is enabled but no proactive_user_hint provided. Defaulting to query as context."
            )

        try:
            session = session_manager.get_session(session_id, full_user_id)
            logger.debug(f"[DIFY] session_id={session_id} query={query.strip()}")

            async with session.lock:
                async for _reply_type_list, _reply_content_list in self._reply_internal(
                    query,
                    full_user_id,
                    session,
                    personalization_enabled,
                    replied_message=replied_message,
                    replied_image_path=replied_image_path,
                    at_user_ids=at_user_ids,
                    is_linger=is_linger,
                    is_proactive=is_proactive,
                    proactive_user_hint=proactive_user_hint,
                    is_perception=is_perception,
                ):
                    if not _reply_type_list:
                        continue

                    # Global <IGNORE> token handling (defensive programming)
                    if _reply_type_list == [ReplyType.TEXT]:
                        content = _reply_content_list[0]

                        if "<IGNORE>" in content:
                            # Strip the control token
                            cleaned = content.replace("<IGNORE>", "").strip()

                            if is_linger or is_proactive:
                                # Expected behavior: silence signal in opportunistic modes
                                logger.debug("Suppressed response due to <IGNORE> token (proactive/linger mode).")
                                return
                            else:
                                # Unexpected leakage: log warning, attempt recovery
                                logger.warning(
                                    f"<IGNORE> token leaked in normal mode. Original content: {content[:100]!r}"
                                )
                                if not cleaned:
                                    # Entire response was just <IGNORE>, skip this chunk
                                    continue
                                # Has remaining content, send cleaned version
                                _reply_content_list[0] = cleaned

                        # Skip empty content chunks
                        if not _reply_content_list[0].strip():
                            continue

                    yield _reply_type_list, _reply_content_list

        except Exception as e:
            logger.error(f"Unexpected error in reply generation: {e}")
            yield [ReplyType.TEXT], [""]

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
        proactive_user_hint: str = None,
        is_perception: bool = False,
    ) -> AsyncGenerator[Tuple[List[ReplyType], List[str]], None]:
        try:
            session_manager.count_user_message(session)  # 限制一个conversation中消息数

            all_files = []
            # 1. 处理当前消息的图片
            current_img_path = None
            try:
                # Peek at the cache before it is popped by _get_upload_files
                if session.id in USER_IMAGE_CACHE:
                    current_img_path = USER_IMAGE_CACHE[session.id].get("path")

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

            # 3. 处理图片引用缓存（检测用户是否引用历史图片）
            adapter_name = self._extract_adapter_name(full_user_id)
            group_id = self._extract_group_id(full_user_id)
            user_id = self._extract_user_id(full_user_id)

            # 只有当 IMAGE_UPLOAD_ENABLE=true 且 IMAGE_ATTACH_MODE != off 且没有显式引用图片时才附加缓存图片
            if (
                config.image_upload_enable
                and config.image_attach_mode != "off"
                and not replied_image_path  # Skip if user already replied to an image explicitly
                and image_cache.should_attach_image(query)
            ):
                cached_image_path = image_cache.get_cached_image(adapter_name, group_id, user_id)
                if cached_image_path:
                    # Prevent duplicate attachment if the cached image is the same as the current image
                    is_duplicate = False
                    if current_img_path:
                        try:
                            current_name = os.path.splitext(os.path.basename(current_img_path))[0]
                            cached_name = os.path.basename(cached_image_path)
                            # Check if cached filename follows the pattern ref_{current_name}_{timestamp}.{ext}
                            # Using loose check `ref_{current_name}_` to avoid regex overhead, ensuring simple collision avoidance
                            if f"ref_{current_name}_" in cached_name:
                                is_duplicate = True
                                logger.debug(
                                    f"Skipping cached message image {cached_name} as it is likely a duplicate of the current image."
                                )
                        except Exception as e:
                            logger.warning(f"Error checking for duplicate images: {e}")

                    if not is_duplicate:
                        try:
                            cached_files = await self._upload_file_from_path(cached_image_path, session.user)
                            if cached_files:
                                all_files.extend(cached_files)
                                logger.debug(f"Attached cached image to request: {cached_image_path}")
                        except Exception as e:
                            logger.warning(f"Failed to upload cached image: {e}")

            final_query, conversation_id = await self._build_final_query(
                query,
                full_user_id,
                session,
                personalization_enabled,
                replied_message=replied_message,
                at_user_ids=at_user_ids,
                is_proactive=is_proactive,
                proactive_user_hint=proactive_user_hint,
            )

            dify_api_user = full_user_id
            driver = get_driver()

            # Determine if image is present in context (current or replied)
            has_image = bool(all_files) or bool(replied_image_path)

            async for replies_type, replies_content, meta in driver.chat(
                query=final_query,
                user_id=full_user_id,
                conversation_id=conversation_id,
                files=all_files,
                extra_context=dify_api_user,
                disable_tools=is_perception,
                has_image=has_image,
                raw_query=query,  # Pass original query for isolated tool detection
            ):
                # Handle conversation_id from metadata
                if meta.get("conversation_id"):
                    cid = meta["conversation_id"]
                    if cid and not session.conversation_id:
                        session.conversation_id = cid

                # Handle tool execution result - record to chat history (uses perceived_result format)
                if meta.get("perceived_result"):
                    try:
                        perceived_result_text = meta["perceived_result"]
                        # Record perceived result as assistant message in history
                        if group_id:
                            await chat_recorder.record_message(
                                adapter_name,
                                group_id,
                                "tool_system",
                                "工具系统",
                                perceived_result_text,
                                "assistant",
                                is_mentioned=False,
                                skip_repeat_check=True,
                            )
                        else:
                            # Private chat
                            from ..storage import private_recorder as private_chat_recorder

                            await private_chat_recorder.record_private_message(
                                adapter_name,
                                user_id,
                                "工具系统",
                                perceived_result_text,
                                "assistant",
                                skip_repeat_check=True,
                            )
                        logger.debug("[DIFY] Recorded perceived result to chat history")
                    except Exception as e:
                        logger.warning(f"Failed to record perceived result to history: {e}")

                yield replies_type, replies_content

        except Exception as e:
            logger.error(f"Internal reply error: {e}")
            yield [ReplyType.TEXT], [""]

    async def _build_final_query(
        self,
        query: str,
        full_user_id: str,
        session: session_manager.Session,
        personalization_enabled: bool = False,
        replied_message=None,
        at_user_ids: Optional[List[str]] = None,
        is_proactive: bool = False,
        proactive_user_hint: str = None,
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
        if is_private_chat and (personalization_enabled or is_proactive):
            query, conversation_id = await self._build_private_chat_query(
                query,
                adapter_name,
                user_id,
                conversation_id,
                personalization_enabled=personalization_enabled,
                is_proactive=is_proactive,
                proactive_user_hint=proactive_user_hint,
            )
            return replied_message_str + query, conversation_id

        # --- 处理群聊（原有逻辑）---
        if not group_id:
            return query, conversation_id

        # --- 加载画像 ---
        group_profile_str = ""
        personalization_str = ""
        sender_persona_str = ""

        # Check if group personalization is enabled
        group_profiler_enabled = group_memory.get_profiler_status(adapter_name, group_id)

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

            # Use group personalization in group chats
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

                history_str = prompt_utils.format_history(
                    filtered_messages, config.group_chat_history_size, image_mode=config.history_image_mode
                )

        # --- Construct Context Block using XML ---
        context_parts = []
        if group_profile_str:
            context_parts.append(group_profile_str.strip())  # group_profile_str already contains tags if not empty?
            # Wait, existing code: group_profile_str = f"<group_profile>\n{group_profile}\n</group_profile>\n"
            # It already has tags.

        if sender_persona_str:
            context_parts.append(sender_persona_str.strip())

        if personalization_str:
            context_parts.append(personalization_str.strip())

        if history_str:
            context_parts.append(f"<history>\n{history_str}\n</history>")

        context_block = ""
        if context_parts:
            joined_context = "\n".join(context_parts)
            context_block = f"<context>\n{joined_context}\n</context>\n"

        # --- 注入主动介入提示 ---
        proactive_hint = ""
        if is_proactive:
            proactive_hint = (
                "[System Note: You are a bystander. You are responding because no one else in the group replied after a delay. "
                "If the topic is relevant and you can add value, reply naturally without using '@'. Otherwise, output <IGNORE>.]\n"
            )

        # --- 组合最终查询 ---
        if is_proactive and proactive_user_hint:
            # Proactive Mode:
            # 1. User Query -> System Hint describing what user did.
            # 2. Tool Output (original 'query') -> Placed in context as <perceived_tool_output> or similar,
            #    but since 'query' already contains <perceived_result>, we just prepend it to the context.

            # We treat the original 'query' (which is the tool output) as context.
            # And we treat 'proactive_user_hint' as the fake user query to trigger the LLM.

            # 'query' here is expected to be the <perceived_result> XML block from __init__.py
            perceived_context = query

            final_query = f"{proactive_hint}{context_block}{replied_message_str}{perceived_context}<user_query>\n[System Event: {proactive_user_hint}]\n</user_query>"

            logger.debug(f"[DIFY] Proactive Context Constructed: Hint='{proactive_user_hint}'")
        else:
            # Standard Mode
            current_query = f"{user_id}: {query}"
            final_query = (
                f"{proactive_hint}{context_block}{replied_message_str}<user_query>\n{current_query}\n</user_query>"
            )

        logger.debug("[DIFY] 已拼接上下文到查询 (使用prompt_utils)")
        return final_query, conversation_id

    async def _build_private_chat_query(
        self,
        query: str,
        adapter_name: str,
        user_id: str,
        conversation_id: str,
        personalization_enabled: bool = False,
        is_proactive: bool = False,
        proactive_user_hint: str = None,
    ) -> Tuple[str, Optional[str]]:
        """构建私聊个性化查询字符串"""
        try:
            # --- 加载用户画像和个性化数据 ---
            sender_persona_str = ""
            personalization_str = ""
            history_str = ""

            if personalization_enabled:
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
                            history_str = prompt_utils.format_history(
                                filtered_messages,
                                config.private_chat_history_size,
                                image_mode=config.history_image_mode,
                            )
                except Exception as e:
                    logger.warning(f"Failed to load private chat history: {e}")

            # --- 组合最终查询 ---
            context_parts = []

            if sender_persona_str:
                context_parts.append(sender_persona_str)
            if personalization_str:
                context_parts.append(personalization_str)
            if history_str:
                # Wrap history in <history> tag if not already done by prompt_utils?
                # prompt_utils returns just the lines.
                context_parts.append(f"<history>\n{history_str}\n</history>")

            context_block = ""
            if context_parts:
                joined_context = "\n".join(context_parts)
                context_block = f"<context>\n{joined_context}\n</context>\n"

            if is_proactive and proactive_user_hint:
                # Proactive Mode for Private Chat
                perceived_context = query
                final_query = f"{context_block}{perceived_context}<user_query>\n[System Event: {proactive_user_hint}]\n</user_query>"
            else:
                current_query = f"User: {query}"
                final_query = f"{context_block}<user_query>\n{current_query}\n</user_query>"

            logger.debug("[DIFY] 已拼接私聊上下文到查询 (使用了prompt_utils)")

            return final_query, conversation_id

        except Exception as e:
            logger.error(f"Failed to build private chat query: {e}")
            return f"User: {query}", conversation_id

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


dify_bot: DifyBot = DifyBot()
