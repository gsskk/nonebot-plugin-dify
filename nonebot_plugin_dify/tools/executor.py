import asyncio
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import uuid

from nonebot import logger
from nonebot.adapters import Bot, Event, Message, MessageSegment
from nonebot.exception import ActionFailed
from nonebot.message import handle_event
from nonebot.typing import overrides

try:
    from nonebot_plugin_alconna import command_manager, Alconna
    from nonebot_plugin_alconna.core import Arg
except ImportError:
    command_manager = None
    Alconna = None
    Arg = None

# Dynamic Adapter Support
# We try to import common MessageEvents to inherit from them whenever possible.
# This makes VirtualEvent satisfy isinstance checks (e.g. in Alconna or handlers).
_EventBases = []
_AdapterMessageClasses = {}

try:
    from nonebot.adapters.telegram.event import MessageEvent as TgMessageEvent
    from nonebot.adapters.telegram import Message as TgMessage

    _EventBases.append(TgMessageEvent)
    _AdapterMessageClasses["nonebot.adapters.telegram"] = TgMessage
except ImportError:
    pass

try:
    from nonebot.adapters.onebot.v11 import MessageEvent as OB11MessageEvent
    from nonebot.adapters.onebot.v11 import Message as OB11Message

    _EventBases.append(OB11MessageEvent)
    _AdapterMessageClasses["nonebot.adapters.onebot.v11"] = OB11Message
except ImportError:
    pass

# If no specific adapter event found, fallback to generic Event
if not _EventBases:
    _EventBases.append(Event)

# Filter duplicates and create a mixin base
_EventBase = type("EventBase", tuple(_EventBases), {})

from ..config import config


@dataclass
class ToolExecutionResult:
    result: str
    error: Optional[str] = None
    artifacts: List[Any] = field(default_factory=list)


class CaptureBot(Bot):
    """
    A sandbox bot that captures replies and filters API calls.
    """

    def __init__(self, origin_bot: Bot):
        # reuse origin bot's adapter to keep plugins happy with isinstance checks if they check adapter
        super().__init__(origin_bot.adapter, "dify_capture_bot")
        self.origin_bot = origin_bot
        self.captured_replies: List[str] = []

    @overrides(Bot)
    async def send(
        self,
        event: Event,
        message: Any,
        **kwargs: Any,
    ) -> Any:
        # Capture the message content
        self.captured_replies.append(str(message))
        logger.info(f"[Tool Sandbox] Captured reply: {message}")
        return {"message_id": f"capture_{uuid.uuid4()}"}

    @overrides(Bot)
    async def call_api(self, api: str, **data: Any) -> Any:
        # 1. Allowlist check
        if api in config.tool_sandbox_api_allowlist:
            logger.debug(f"[Tool Sandbox] Passthrough API: {api}")
            return await self.origin_bot.call_api(api, **data)

        # 2. Capture send_* calls
        if api.startswith("send_"):
            msg = data.get("message", "")
            self.captured_replies.append(str(msg))
            logger.info(f"[Tool Sandbox] Captured API reply ({api}): {msg}")
            return {"message_id": f"capture_{uuid.uuid4()}"}

        # 3. Block others
        logger.warning(f"[Tool Sandbox] Blocked dangerous API call: {api}")
        raise ActionFailed(f"API {api} is not allowed in Tool Sandbox.")


class VirtualSegment(MessageSegment):
    """Mock Segment to satisfy is_text check."""

    def __init__(self, text: str):
        super().__init__("text", {"text": text})

    def is_text(self) -> bool:
        return True

    @classmethod
    @overrides(MessageSegment)
    def get_message_class(cls):
        return VirtualMessage

    def __str__(self) -> str:
        return self.data["text"]

    def __repr__(self) -> str:
        return f"VirtualSegment(text={self.data['text']})"


class VirtualMessage(Message):
    """Mock Message that behaves like a list of segments."""

    def __init__(self, text: str):
        super().__init__([VirtualSegment(text)])
        self.text = text

    @classmethod
    @overrides(Message)
    def get_segment_class(cls):
        return VirtualSegment

    def __str__(self) -> str:
        return self.text

    def extract_plain_text(self) -> str:
        return self.text

    def copy(self):
        return VirtualMessage(self.text)


def mock_generic(data: Dict[str, Any], message: Any, user_id: str) -> None:
    """Fallback strategy: Must satisfy ALL inherited Pydantic models"""
    data.setdefault("self_id", 123456)
    data.setdefault("message", message)
    data.setdefault("raw_message", str(message))

    # Satisfy OneBot V11 validation if inherited
    import random

    data.setdefault("message_id", random.randint(10000, 99999999))
    data.setdefault("time", 0)
    data.setdefault("post_type", "message")
    data.setdefault("message_type", "private")
    data.setdefault("sub_type", "friend")

    # Safely handle sender if not OneBot strategy
    if "sender" not in data:
        data["sender"] = {"user_id": 1, "nickname": "ToolUser"}

    data.setdefault("font", 0)

    # Satisfy Telegram validation if inherited
    data.setdefault("date", 0)
    data.setdefault("chat", {"id": 1, "type": "private"})
    if "original_message" not in data:
        data["original_message"] = message

    # OneBot V11 requires user_id (int)
    # If not set (e.g. Telegram strategy triggers), we must provide a fallback
    if "user_id" not in data:
        uid_int = 123456
        if user_id.isdigit():
            uid_int = int(user_id)
        elif "_" in user_id and user_id.split("_")[-1].isdigit():
            uid_int = int(user_id.split("_")[-1])
        data["user_id"] = uid_int


def mock_onebot_v11(data: Dict[str, Any], message: Any, user_id: str) -> None:
    """OneBot V11 Strategy"""
    mock_generic(data, message, user_id)
    # OneBot logic is covered by generic fallback logic above which extracts user_id
    # We can keep specific overrides here if needed, but generics MUST handle the baseline.


def mock_telegram(data: Dict[str, Any], message: Any, user_id: str) -> None:
    """Telegram Strategy"""
    mock_generic(data, message, user_id)

    # Telegram specific logic override
    if "from" not in data and "from_" not in data:
        data["from"] = {"id": 1, "is_bot": False, "first_name": "ToolUser"}


ADAPTER_MOCK_STRATEGIES: Dict[str, Callable] = {
    "OneBot V11": mock_onebot_v11,
    "Telegram": mock_telegram,
}


class VirtualEvent(_EventBase):
    """
    A minimal Virtual Event for triggering matchers.
    Attributes are mocked to simulate a message context.
    Inherits dynamically from found Adapter MessageEvents to pass isinstance checks.
    """

    # Pydantic fields
    _message_str: str = ""
    _user_id: str = "tool_user"
    _session_id: str = "tool_session"
    _virtual_message: Any = None

    def __init__(
        self,
        origin_bot: Bot,
        message_str: str,
        user_id: str = "tool_user",
        session_id: str = "tool_session",
        **data,
    ):
        # 1. Determine Message Class
        mro_str = str(self.__class__.__mro__)
        MsgClass = VirtualMessage

        # Keep this for Message class selection since we dynamic inherited
        if "nonebot.adapters.telegram" in mro_str and "nonebot.adapters.telegram" in _AdapterMessageClasses:
            MsgClass = _AdapterMessageClasses["nonebot.adapters.telegram"]
        elif "nonebot.adapters.onebot.v11" in mro_str and "nonebot.adapters.onebot.v11" in _AdapterMessageClasses:
            MsgClass = _AdapterMessageClasses["nonebot.adapters.onebot.v11"]

        real_message = MsgClass(message_str)

        # 2. Apply Mock Strategy based on Bot Type
        strategy = ADAPTER_MOCK_STRATEGIES.get(origin_bot.type, mock_generic)
        strategy(data, real_message, user_id)

        # 3. Call Pydantic Init
        try:
            super().__init__(**data)
        except Exception as e:
            logger.warning(
                f"[Tool Executor] VirtualEvent pydantic validation failed: {e}. Proceeding with partial init."
            )
            # Fallback
            if "message_id" not in self.__dict__:
                self.__dict__["message_id"] = data.get("message_id", 1)

        # 4. Set Private Attributes
        object.__setattr__(self, "_message_str", message_str)
        object.__setattr__(self, "_user_id", user_id)
        object.__setattr__(self, "_session_id", session_id)
        object.__setattr__(self, "_virtual_message", real_message)

    @overrides(Event)
    def get_type(self) -> str:
        return "message"

    @overrides(Event)
    def get_event_name(self) -> str:
        return "message.dify_tool_call"

    @overrides(Event)
    def get_event_description(self) -> str:
        return f"Virtual Message: {self._message_str}"

    @overrides(Event)
    def get_user_id(self) -> str:
        return self._user_id

    @overrides(Event)
    def get_session_id(self) -> str:
        return self._session_id

    @overrides(Event)
    def get_message(self) -> Any:
        return self._virtual_message

    @overrides(Event)
    def is_tome(self) -> bool:
        return True  # Always treat as directed at bot to trigger command


async def execute_tool(
    tool_name: str,
    tool_args: Dict[str, Any],
    origin_bot: Bot,
    user_id: str,
    full_user_id: str = "",
) -> ToolExecutionResult:
    """
    Execute a tool in the sandbox.
    Supports both Alconna commands and traditional on_command handlers.

    Args:
        tool_name: The tool/command name
        tool_args: Arguments for the tool
        origin_bot: The original Bot instance
        user_id: Short user ID for sandbox
        full_user_id: Full session ID for permission check (fallback security)
    """
    logger.debug(f"[Tool Executor] Starting execution of tool: {tool_name}")
    logger.debug(f"[Tool Executor] Tool arguments: {tool_args}")

    # Fallback permission check (second layer of security)
    if full_user_id:
        from .registry import check_tool_user_permission

        if not check_tool_user_permission(tool_name, full_user_id):
            logger.warning(f"[Tool Executor] Permission denied: {full_user_id} -> {tool_name}")
            return ToolExecutionResult(result="", error=f"权限不足：你没有使用 {tool_name} 的权限")

    # Fallback: Normalize common parameter mismatches (LLM hallucinations)
    # Map common LLM hallucinated names to expected parameter names
    PARAM_ALIASES = {
        "queries": "query",
        "name": "tool",
        "capability": "tool",
        "tool_name": "tool",
        "command": "tool",
        "action": "tool",
        "arguments": "args",
        "params": "args",
        "parameters": "args",
    }
    for alias, canonical in PARAM_ALIASES.items():
        if alias in tool_args and canonical not in tool_args:
            logger.debug(f"[Tool Executor] Applied fallback: {alias} -> {canonical}")
            tool_args[canonical] = tool_args.pop(alias)

    # Handle list arguments (e.g. query=['a', 'b']) -> join with spaces
    for key, value in tool_args.items():
        if isinstance(value, list):
            tool_args[key] = " ".join(str(v) for v in value)
            logger.debug(f"[Tool Executor] Flattened list argument {key}: {tool_args[key]}")

    # 0. Check for Override Format
    override = config.tool_schema_override.get(tool_name)
    override_fmt = override.get("format") if override else None

    # Try Alconna first if no override format provided
    # (If override provided, we skip Alconna/Logic and adhere strictly to format)
    cmd = None
    is_alconna = False

    if override_fmt:
        logger.debug(f"[Tool Executor] Using override format for {tool_name}: {override_fmt}")
        try:
            # Extract all placeholders from format string and default missing ones to ""
            placeholders = re.findall(r"\{(\w+)\}", override_fmt)
            format_args = {p: tool_args.get(p, "") for p in placeholders}
            cmd_str = override_fmt.format(**format_args).strip()
            # Clean up multiple consecutive spaces from empty optional args
            cmd_str = re.sub(r"\s+", " ", cmd_str).strip()
            logger.debug(f"[Tool Executor] Formatted command: {cmd_str}")
        except Exception as e:
            return ToolExecutionResult(result="", error=f"Failed to format command string: {e}")

    else:
        # Standard Auto-Construction Logic
        if command_manager:
            cmd = command_manager.get_command(tool_name)
            if cmd:
                is_alconna = True
                logger.debug(f"[Tool Executor] Found Alconna command: {tool_name}")

        # 1. Reconstruct Command String
        if is_alconna and cmd:
            try:
                cmd_str = _reconstruct_command_string(cmd, tool_args)
            except Exception as e:
                return ToolExecutionResult(result="", error=f"Failed to reconstruct command args: {e}")
        else:
            # Fallback: Simple on_command format
            # Use "query" parameter if available, otherwise join all args
            query = tool_args.get("query", "")
            if not query and tool_args:
                query = " ".join(str(v) for v in tool_args.values())

            # Construct command string with prefix
            from nonebot import get_driver

            command_start = get_driver().config.command_start
            prefix = next(iter(command_start)) if command_start else "/"
            cmd_str = f"{prefix}{tool_name} {query}".strip()
            logger.debug(f"[Tool Executor] Using on_command format: {cmd_str}")

    logger.info(f"[Tool Executor] Running command: {cmd_str}")

    # 2. Setup Sandbox
    # Extract simple user_id from full session ID (e.g., "onebotv11+private+123" -> "123")
    # This enables transparent pass-through: third-party plugins will see the real user ID
    simple_user_id = user_id.split("+")[-1] if "+" in user_id else user_id
    logger.debug(f"[Tool Executor] Setting up CaptureBot sandbox for user: {simple_user_id}")
    capture_bot = CaptureBot(origin_bot)

    # FIX: Use unique session ID suffix to prevent Alconna/NoneBot caching issues
    unique_suffix = str(uuid.uuid4())[:8]
    virtual_event = VirtualEvent(
        origin_bot, cmd_str, user_id=simple_user_id, session_id=f"tool_session_{unique_suffix}"
    )

    # 3. Execute with Timeout
    try:
        # We start handle_event which triggers NoneBot's processing flow
        # This will find the matcher and run it.
        # Note: We rely on the matcher NOT being blocked by permission checks for 'dify_user'.
        # If plugins define permission (SUPERUSER etc), this might fail.
        # Caveat: We cannot easily bypass permissions without modifying the matcher or state.

        await asyncio.wait_for(handle_event(capture_bot, virtual_event), timeout=config.tool_timeout)

        # 4. Collect Results
        if capture_bot.captured_replies:
            result_text = "\n".join(capture_bot.captured_replies)
            logger.debug(f"[Tool Executor] Captured {len(capture_bot.captured_replies)} replies from tool")
            return ToolExecutionResult(result=result_text)
        else:
            logger.debug("[Tool Executor] Tool executed but produced no output")
            return ToolExecutionResult(result="[Tool executed successfully with no output]")

    except asyncio.TimeoutError:
        logger.warning(f"[Tool Executor] Timeout for {tool_name}")
        return ToolExecutionResult(result="", error="Tool execution timed out.")

    except Exception as e:
        logger.error(f"[Tool Executor] Error: {e}")
        return ToolExecutionResult(result="", error=f"Tool execution failed: {e}")


def _reconstruct_command_string(cmd: "Alconna", args: Dict[str, Any]) -> str:
    parts = [cmd.name]  # Or cmd.command? Alconna main name.

    # Process args (positional)
    for arg in cmd.args:
        val = args.get(arg.name)
        if val is not None:
            parts.append(shlex.quote(str(val)))

    # Process options
    for opt in cmd.options:
        # Match property name (stripped dashes)
        prop_name = opt.name.lstrip("-")

        # Case A: Flag (Bool)
        if not opt.args:
            if args.get(prop_name) is True:
                parts.append(opt.name)
        # Case B: Option with Value
        else:
            val = args.get(prop_name)
            if val is not None:
                parts.append(opt.name)
                parts.append(shlex.quote(str(val)))

    return " ".join(parts)
