from abc import ABC, abstractmethod
from typing import AsyncGenerator, Tuple, List, Optional, Dict, Any
import json
import httpx
import re
import asyncio

from nonebot import logger
from ..config import config
from ..utils.reply_type import ReplyType
from ..utils.streaming import StreamingBuffer
from ..utils.helpers import parse_markdown_text
from ..core.dify_client import ChatClient


class LLMDriver(ABC):
    @abstractmethod
    def chat(
        self,
        query: str,
        user_id: str,
        conversation_id: str,
        files: Optional[list] = None,
        extra_context: Optional[str] = None,  # For passing session.user (full identifier)
        disable_tools: bool = False,  # Disable tool detection for proactive/perception
    ) -> AsyncGenerator[Tuple[List[ReplyType], List[str], Dict[str, Any]], None]:
        """
        Chat with the backend.

        Args:
            query: The user input text (or constructed prompt).
            user_id: The unique user identifier (for session tracking).
            conversation_id: The conversation ID (if any).
            files: List of files to upload/attach.
            extra_context: Additional context needed by specific drivers (e.g. 'user' field for Dify).

        Yields:
            Tuple of (ReplyType List, Content List, Metadata Dict).
        """
        pass


class DifyAppDriver(LLMDriver):
    """
    Driver for Dify App (Chatflow/Chatbot/Agent/Workflow).
    Wraps the legacy logic from DifyBot.
    - Chatflow/Chatbot shares the same handler (_handle_chatbot).
    """

    async def chat(
        self,
        query: str,
        user_id: str,
        conversation_id: str,
        files: Optional[list] = None,
        extra_context: Optional[str] = None,  # Dify API requires 'user' field
        disable_tools: bool = False,  # Not used by DifyAppDriver
    ) -> AsyncGenerator[Tuple[List[ReplyType], List[str], Dict[str, Any]], None]:
        dify_user = extra_context or user_id
        dify_app_type = config.dify_main_app_type

        try:
            if dify_app_type in ("chatbot", "chatflow"):
                async for res in self._handle_chatbot(query, conversation_id, dify_user, files):
                    yield res
            elif dify_app_type == "agent":
                async for res in self._handle_agent(query, conversation_id, dify_user, files):
                    yield res
            elif dify_app_type == "workflow":
                # Workflows don't support conversation_id usually, but support files now
                async for res in self._handle_workflow(query, dify_user, files):
                    yield res
            else:
                logger.error(f"Invalid dify_main_app_type configuration: {dify_app_type}")
                yield (
                    [ReplyType.TEXT],
                    ["配置错误：dify_main_app_type 必须是 chatflow(推荐)、chatbot、agent 或 workflow"],
                    {},
                )
        except Exception as e:
            logger.error(f"Internal reply error in DifyAppDriver: {e}")
            yield [ReplyType.TEXT], [""], {}

    # --- Ported Logic from DifyBot ---

    async def _handle_chatbot(
        self,
        query: str,
        conversation_id: str,
        user: str,
        files: list = None,
    ):
        try:
            chat_client = ChatClient(config.dify_main_app_api_key, config.dify_api_base)

            if config.dify_stream_enable:
                async for res in self._handle_streaming_request(
                    f"{config.dify_api_base}/chat-messages",
                    {
                        "inputs": {},
                        "query": query,
                        "response_mode": "streaming",
                        "conversation_id": conversation_id,
                        "user": user,
                        "files": files,
                    },
                ):
                    yield res
                return

            # Non-streaming fallback
            response = await chat_client.create_chat_message(
                inputs={},
                query=query,
                user=user,
                response_mode="blocking",
                conversation_id=conversation_id,
                files=files,
            )

            if response.status_code != 200:
                yield [ReplyType.TEXT], [self._format_error(response, "请求 Dify 服务时出错")], {}
                return

            try:
                rsp_data = response.json()
                logger.debug(f"[DIFY] usage {rsp_data.get('metadata', {}).get('usage', 0)}")

                answer = rsp_data.get("answer", "")
                if not answer:
                    logger.warning("Dify returned empty answer")
                    yield [], [], {}
                    return

                answer = self._clean_content(answer)
                parsed_content = parse_markdown_text(answer)
                yield (*self._parse_replies(parsed_content), {})

            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse Dify response: {e}")
                yield [ReplyType.TEXT], ["解析 Dify 返回数据时出错，请检查 Dify 应用配置。"], {}

        except httpx.TimeoutException as e:
            logger.error(f"Dify chatbot API timeout: {e}")
            yield [ReplyType.TEXT], ["请求 Dify 服务超时，请稍后再试。"], {}

        except httpx.RequestError as e:
            logger.error(f"Dify chatbot request error: {e}")
            yield [ReplyType.TEXT], ["请求 Dify 服务失败，请检查网络连接或 API 地址。"], {}
        except Exception as e:
            logger.error(f"Unexpected error in chatbot handler: {e}")
            yield [ReplyType.TEXT], ["处理回复时遇到未知错误。"], {}

    async def _handle_agent(
        self,
        query: str,
        conversation_id: str,
        user: str,
        files: list = None,
    ):
        try:
            payload = {
                "inputs": {},
                "query": query,
                "response_mode": "streaming",
                "conversation_id": conversation_id,
                "user": user,
                "files": files,
            }

            if config.dify_stream_enable:
                async for res in self._handle_streaming_request(f"{config.dify_api_base}/chat-messages", payload):
                    yield res
                return

            # Legacy "False Streaming"
            async with httpx.AsyncClient(timeout=httpx.Timeout(config.dify_api_timeout)) as client:
                response = await client.post(
                    f"{config.dify_api_base}/chat-messages",
                    headers=self._get_headers(),
                    json=payload,
                )

            if response.status_code != 200:
                yield [ReplyType.TEXT], [self._format_error(response, "请求 Dify-Agent 服务时出错")], {}
                return

            try:
                msgs, _ = self._handle_sse_response(response)
                yield (*self._parse_agent_replies(msgs), {})

            except Exception as e:
                logger.error(f"Failed to parse agent response: {e}")
                yield [ReplyType.TEXT], ["解析 Dify-Agent 返回数据时出错，请检查 Dify 应用配置。"], {}

        except httpx.TimeoutException as e:
            logger.error(f"Dify agent API timeout: {e}")
            yield [ReplyType.TEXT], ["请求 Dify-Agent 服务超时，请稍后再试。"], {}

        except httpx.RequestError as e:
            logger.error(f"Dify agent request error: {e}")
            yield [ReplyType.TEXT], ["请求 Dify-Agent 服务失败，请检查网络连接或 API 地址。"], {}
        except Exception as e:
            logger.error(f"Unexpected error in agent handler: {e}")
            yield [ReplyType.TEXT], ["处理 Dify-Agent 回复时遇到未知错误。"], {}

    async def _handle_workflow(self, query: str, user: str, files: list = None):
        try:
            payload = {
                "inputs": {"query": query},
                "response_mode": "blocking",
                "user": user,
                "files": files,
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(config.dify_api_timeout)) as client:
                response = await client.post(
                    f"{config.dify_api_base}/workflows/run",
                    headers=self._get_headers(),
                    json=payload,
                )

            if response.status_code != 200:
                yield [ReplyType.TEXT], [self._format_error(response, "请求 Dify-Workflow 服务时出错")], {}
                return

            try:
                rsp_data = response.json()
                reply_content = rsp_data.get("data", {}).get("outputs", {}).get("text", "")

                if not reply_content:
                    logger.warning("Dify workflow returned empty response")
                    yield [], [], {}
                    return

                reply_content = self._clean_content(reply_content)
                yield [ReplyType.TEXT], [reply_content], {}

            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to parse workflow response: {e}")
                yield [ReplyType.TEXT], ["解析 Dify-Workflow 返回数据时出错，请检查 Dify 应用配置。"], {}

        except httpx.TimeoutException as e:
            logger.error(f"Dify workflow API timeout: {e}")
            yield [ReplyType.TEXT], ["请求 Dify-Workflow 服务超时，请稍后再试。"], {}
        except httpx.RequestError as e:
            logger.error(f"Dify workflow request error: {e}")
            yield [ReplyType.TEXT], ["请求 Dify-Workflow 服务失败，请检查网络连接或 API 地址。"], {}
        except Exception as e:
            logger.error(f"Unexpected error in workflow handler: {e}")
            yield [ReplyType.TEXT], ["处理 Dify-Workflow 回复时遇到未知错误。"], {}

    async def _handle_streaming_request(self, url: str, payload: dict):
        streaming_buffer = StreamingBuffer(min_char=config.dify_stream_min_char)
        last_yield_time = 0

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(config.dify_api_timeout)) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers=self._get_headers(),
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        yield [ReplyType.TEXT], [f"Stream Error: {response.status_code}"], {}
                        return

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue

                        try:
                            data = json.loads(line[5:])
                            event = data.get("event")

                            if event in ("agent_message", "message"):
                                answer = data.get("answer", "")
                                if not answer:
                                    continue

                                for segment in streaming_buffer.process(answer):
                                    now = asyncio.get_event_loop().time()
                                    if now - last_yield_time < config.dify_stream_min_interval:
                                        await asyncio.sleep(config.dify_stream_min_interval - (now - last_yield_time))

                                    yield [ReplyType.TEXT], [segment], {}
                                    last_yield_time = asyncio.get_event_loop().time()

                            elif event == "message_file":
                                # Immediately yield images
                                url = self._fill_file_base_url(data.get("url"))
                                yield [ReplyType.IMAGE_URL], [url], {}

                            elif event == "error":
                                logger.error(f"Stream error event: {data}")
                                yield [ReplyType.TEXT], [f"Error: {data.get('message', 'Unknown error')}"], {}

                            elif event == "message_end":
                                break

                        except json.JSONDecodeError:
                            continue

                    for segment in streaming_buffer.flush():
                        yield [ReplyType.TEXT], [segment], {}

        except Exception as e:
            logger.error(f"Streaming request failed: {e}")
            yield [ReplyType.TEXT], [f"Streaming Interrupted: {e}"], {}

    # --- Helpers ---
    def _get_headers(self):
        return {"Authorization": f"Bearer {config.dify_main_app_api_key}"}

    def _clean_content(self, content: str) -> str:
        if not content:
            return ""
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    def _format_error(self, response, context_msg):
        error_message = f"{context_msg} (HTTP {response.status_code})。"
        try:
            error_data = response.json()
            detail = error_data.get("message", response.text[:200])
            error_message += f" 详细信息: {detail}"
        except json.JSONDecodeError:
            error_message += f" 无法解析错误响应: {response.text[:200]}"
        return error_message

    def _fill_file_base_url(self, url: str) -> str:
        if url and url.startswith("/"):
            return f"{config.dify_api_base}{url}"
        return url

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

    def _handle_sse_response(self, response):
        # Extremely simplified SSE parser for legacy agent block mode
        # DifyBot._handle_sse_response is distinct, let's copy relevant logic if possible
        # Or just trust that streaming handler covers most cases now.
        # But for correctness, let's implement a simple blocking SSE parser
        # that mimics _handle_sse_response logic from dify_bot.py

        msgs = []
        conversation_id = ""

        try:  # Added try block here
            for line in response.iter_lines():
                line = line.decode("utf-8") if isinstance(line, bytes) else line
                if not line or not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:])
                    event = data.get("event")
                    if event == "agent_message":
                        msgs.append({"type": "agent_message", "content": data.get("answer", "")})
                        if not conversation_id:
                            conversation_id = data.get("conversation_id", "")
                    elif event == "message_file":
                        msgs.append({"type": "message_file", "content": data.get("url")})
                except json.JSONDecodeError:  # This except is for the inner try
                    continue
        except Exception:  # This except is for the outer try
            pass
        return msgs, conversation_id


def get_driver() -> LLMDriver:
    """Factory to get the appropriate driver based on configuration."""
    if config.tool_enable:
        return ToolAugmentedDifyDriver()
    return DifyAppDriver()


class ToolAugmentedDifyDriver(LLMDriver):
    """
    Two-stage driver that:
    1. Uses OpenAI to detect and execute tools
    2. Passes tool results (if any) to DifyAppDriver for personalized response
    """

    def __init__(self):
        self.dify_driver = DifyAppDriver()
        self.api_key = config.tool_model_api_key
        self.base_url = config.tool_model_base_url
        self.model_name = config.tool_model_name

    def _get_client(self):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.error("OpenAI library not found. Please install it with 'pip install openai'.")
            raise RuntimeError("OpenAI library missing")
        return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def _detect_and_execute_tools(self, query: str, user_id: str, full_user_id: str = "") -> Optional[str]:
        """
        Use OpenAI to detect if tools are needed.
        If yes, execute tools and return formatted result string.
        If no, return None.

        Args:
            query: The user query for tool detection
            user_id: Short user ID for logging/sandbox
            full_user_id: Full session ID for permission filtering (e.g., "onebotv11+private+123")
        """
        from .registry import get_tool_definitions
        from .executor import execute_tool

        # Pass full_user_id to filter tools by permission
        tools = get_tool_definitions(full_user_id if full_user_id else None)
        if not tools:
            logger.debug("[ToolAugmented] No tools available, skipping tool detection")
            return None

        logger.debug(f"[ToolAugmented] Found {len(tools)} tool definitions: {[t['function']['name'] for t in tools]}")

        try:
            import nonebot

            origin_bot = nonebot.get_bot()
        except Exception:
            logger.warning("No Bot instance found. Tool execution might fail.")
            origin_bot = None

        client = self._get_client()

        # Build messages for tool detection (simple single-turn)
        messages = [
            {
                "role": "system",
                "content": """You are a tool detection assistant.
Your ONLY job is to decide if a tool should be called. You do NOT generate final answers.

Rules:
1. Call a tool ONLY if user's intent is CLEAR and a tool can directly help.
2. DO NOT GUESS. If unsure whether a tool applies, DO NOT call it.
3. For image-related queries (e.g. "who is this?"), prefer NO tool unless you are 100% certain.
4. For ambiguous or casual chat, return NO tool call.
5. Keep tool parameters minimal and precise. Use 2-4 keywords max for search.

If no tool is needed, respond with EMPTY content (no tool calls, no text).""",
            },
            {"role": "user", "content": query},
        ]

        try:
            # Non-streaming call for tool detection
            response = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )

            choice = response.choices[0]

            # Check if tool calls were made
            if not choice.message.tool_calls:
                # No tools needed
                logger.debug("[ToolAugmented] OpenAI decided no tools needed")
                return None

            logger.debug(f"[ToolAugmented] OpenAI requested {len(choice.message.tool_calls)} tool call(s)")

            # Execute tools
            tool_results = []
            for tc in choice.message.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                # Convert normalized name back to original command name
                from .registry import get_original_tool_name

                original_name = get_original_tool_name(func_name)

                logger.info(
                    f"[ToolAugmented] Executing tool: {original_name} (normalized: {func_name}) with args: {func_args}"
                )

                if origin_bot:
                    result_obj = await execute_tool(
                        original_name, func_args, origin_bot, user_id, full_user_id=full_user_id
                    )
                    tool_result = result_obj.result
                    if result_obj.error:
                        tool_result = f"Error: {result_obj.error}"
                        logger.warning(f"[ToolAugmented] Tool '{original_name}' returned error: {result_obj.error}")
                    else:
                        logger.debug(
                            f"[ToolAugmented] Tool '{original_name}' result: {tool_result[:200]}..."
                            if len(tool_result) > 200
                            else f"[ToolAugmented] Tool '{original_name}' result: {tool_result}"
                        )
                else:
                    tool_result = "Error: Bot instance not found, cannot execute command."
                    logger.error("[ToolAugmented] Cannot execute tool: no Bot instance")

                tool_results.append({"tool": original_name, "result": tool_result})

            # Format tool results using perceived_result format (matches intercept pattern)
            formatted_results = []
            for tr in tool_results:
                formatted_results.append(
                    f'<perceived_result plugin="tool:{tr["tool"]}">{tr["result"]}</perceived_result>'
                )

            return "\n".join(formatted_results)

        except Exception as e:
            logger.error(f"[ToolAugmented] Tool detection/execution failed: {e}")
            return None

    async def chat(
        self,
        query: str,
        user_id: str,
        conversation_id: str,
        files: Optional[list] = None,
        extra_context: Optional[str] = None,
        disable_tools: bool = False,
        has_image: bool = False,
        raw_query: Optional[str] = None,
    ) -> AsyncGenerator[Tuple[List[ReplyType], List[str], Dict[str, Any]], None]:
        """
        Two-stage flow:
        1. Detect and execute tools via OpenAI
        2. Pass augmented query to Dify for personalized response
        """
        # Stage 1: Tool detection and execution (skip if disabled or image present)
        skip_tools = disable_tools
        if not skip_tools and has_image and config.tool_skip_on_image:
            logger.debug("[ToolAugmented] Skipping tool detection: message contains image")
            skip_tools = True

        if skip_tools:
            logger.debug("[ToolAugmented] Tools disabled for this request (proactive/perception mode or image skip)")
            tool_result = None
        else:
            # Determine detection query: raw_query if isolation enabled (default), else full query
            detection_query = query
            if not config.tool_use_context and raw_query:
                detection_query = raw_query
                logger.debug("[ToolAugmented] Using raw query for tool detection (context isolation enabled)")

            tool_result = await self._detect_and_execute_tools(
                detection_query, user_id, full_user_id=extra_context or ""
            )

        # Stage 2: Build final query for Dify
        if tool_result:
            # Augment query with tool results
            augmented_query = f"{tool_result}\n\n用户原始消息：{query}"
            logger.info("[ToolAugmented] Augmented query with tool results")
        else:
            # No tools needed, pass original query
            augmented_query = query

        # Stage 3: Call Dify for final response
        first_yield = True
        async for types, contents, meta in self.dify_driver.chat(
            query=augmented_query,
            user_id=user_id,
            conversation_id=conversation_id,
            files=files,
            extra_context=extra_context,
        ):
            # Include perceived_result in metadata for the first yield (for history recording)
            if first_yield and tool_result:
                meta["perceived_result"] = tool_result
                first_yield = False
            yield types, contents, meta


class ContextManager:
    def __init__(self, max_len: int = 20):
        self._store: Dict[str, List[Dict[str, Any]]] = {}
        self.max_len = max_len

    def get(self, user_id: str) -> List[Dict[str, Any]]:
        if user_id not in self._store:
            self._store[user_id] = []
        return self._store[user_id]

    def add(self, user_id: str, message: Dict[str, Any]):
        history = self.get(user_id)
        history.append(message)
        # Trim history
        if len(history) > self.max_len:
            self._store[user_id] = history[-self.max_len :]

    def clear(self, user_id: str):
        if user_id in self._store:
            del self._store[user_id]


# Global memory store for OpenAI mode
ctx_manager = ContextManager()


class OpenAIDriver(LLMDriver):
    """
    Driver for OpenAI-compatible APIs (Tool System Enabled).
    """

    def __init__(self):
        self.api_key = config.tool_model_api_key
        self.base_url = config.tool_model_base_url
        self.model_name = config.tool_model_name

    def _get_client(self):
        # Lazy import to avoid hard dependency if tool_enable is False
        try:
            from openai import AsyncOpenAI
        except ImportError:
            logger.error("OpenAI library not found. Please install it with 'pip install openai'.")
            raise RuntimeError("OpenAI library missing")

        return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def chat(
        self,
        query: str,
        user_id: str,
        conversation_id: str,
        files: Optional[list] = None,
        extra_context: Optional[str] = None,
        disable_tools: bool = False,
    ) -> AsyncGenerator[Tuple[List[ReplyType], List[str]], None]:
        # Lazy import dependencies to avoid circular imports during module load
        from .registry import get_tool_definitions
        from .executor import execute_tool

        # We need the ORIGIN_BOT to pass to the executor.
        # Currently the driver interface doesn't strictly provide it, but we can try to get it
        # via nonebot.get_bot() if available, or assume it's passed somehow.
        # Phase 3 integration will likely pass `bot` instance via extra_context or new arg.
        # For now, let's try to get a bot instance.
        try:
            import nonebot

            # Try to get any bot. In multi-bot setup this might be wrong, logic needs refinement in Integration phase.
            # Ideally DifyBot/Driver caller passes the specific bot instance.
            # Let's assume for now we can get the bot from user_id if it's formatted as "adapter+group+user".
            # But here we just need *a* bot instance to initialize CaptureBot.
            origin_bot = nonebot.get_bot()
        except Exception:
            logger.warning("No Bot instance found. Tool execution might fail if it relies on Bot API.")
            origin_bot = None

        client = self._get_client()

        # 1. Append User Message
        user_msg = {"role": "user", "content": query}
        ctx_manager.add(user_id, user_msg)

        # Tools setup
        tools = get_tool_definitions()
        # If no tools allowed/enabled, set to None
        tools_param = tools if tools else None

        # Max turns to prevent infinite loops
        max_turns = 5
        current_turn = 0

        while current_turn < max_turns:
            current_turn += 1

            # 2. Call API
            try:
                # Prepare call args
                call_args = {
                    "model": self.model_name,
                    "messages": ctx_manager.get(user_id),  # Refresh messages as we might have added tool outputs
                    "stream": True,
                }
                if tools_param:
                    call_args["tools"] = tools_param
                    call_args["tool_choice"] = "auto"

                completion = await client.chat.completions.create(**call_args)

                full_content = ""

                # Streaming with Tools is complex in OpenAI SDK.
                # Tool calls come in chunks. We need to assemble them.
                # For simplicity in this iteration, let's use NON-STREAMING for Tool Calls?
                # No, standard is streaming.
                # Implementing a robust aggregator for streaming tool calls:

                current_tool_call = {}  # index -> {id, type, function: {name, arguments}}

                async for chunk in completion:
                    delta = chunk.choices[0].delta

                    # Handle Content
                    if delta.content:
                        content = delta.content
                        full_content += content
                        yield [ReplyType.TEXT], [content], {}

                    # Handle Tool Calls
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in current_tool_call:
                                current_tool_call[idx] = {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                }

                            if tc.id:
                                current_tool_call[idx]["id"] = tc.id

                            if tc.function:
                                if tc.function.name:
                                    current_tool_call[idx]["function"]["name"] += tc.function.name
                                if tc.function.arguments:
                                    current_tool_call[idx]["function"]["arguments"] += tc.function.arguments

                # Process accumulated tool calls
                if current_tool_call:
                    # Validation: Convert dict to list sorted by index
                    tool_calls = [current_tool_call[k] for k in sorted(current_tool_call.keys())]

                    # Append Assistant Message with Tool Calls to history
                    # OpenAI requires the assistant message to have 'tool_calls' field
                    asst_msg = {
                        "role": "assistant",
                        "content": full_content or None,  # Content can be null if only tool calls
                        "tool_calls": tool_calls,
                    }
                    ctx_manager.add(user_id, asst_msg)

                    # Execute Tools
                    for tc in tool_calls:
                        func_name = tc["function"]["name"]
                        func_args_str = tc["function"]["arguments"]
                        call_id = tc["id"]

                        try:
                            func_args = json.loads(func_args_str)
                        except json.JSONDecodeError:
                            func_args = {}  # Should safely fail in executor

                        yield [ReplyType.TEXT], [f"\n[Executing Tool: {func_name}]"], {}

                        if origin_bot:
                            # Execute
                            result_obj = await execute_tool(func_name, func_args, origin_bot, user_id)
                            tool_result = result_obj.result
                            if result_obj.error:
                                tool_result = f"Error: {result_obj.error}"
                        else:
                            tool_result = "Error: Bot instance not found, cannot execute command."

                        # Append Tool Result to history
                        ctx_manager.add(user_id, {"role": "tool", "tool_call_id": call_id, "content": tool_result})

                    # Loop back to continue generation (with tool outputs in history)
                    continue

                # If no tool calls, we are done
                if full_content:
                    ctx_manager.add(user_id, {"role": "assistant", "content": full_content})
                break

            except Exception as e:
                logger.error(f"OpenAI Driver Error: {e}")
                err_msg = f"Error: {str(e)}"
                yield [ReplyType.TEXT], [err_msg], {}
                # If critical error, break loop
                break
