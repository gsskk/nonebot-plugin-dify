from typing import Dict, List, Any, Optional, get_origin, get_args
import fnmatch
import re
import hashlib

from nonebot import logger

try:
    from nonebot_plugin_alconna import Alconna, command_manager

except ImportError:
    # Fallback/Mock for environments without alconna installed (though it is a dep)
    logger.warning("nonebot_plugin_alconna not found. Tool system will not function.")
    Alconna = Any
    command_manager = Any

from ..config import config

# Mapping from normalized tool name -> original command name
_tool_name_mapping: Dict[str, str] = {}


def _create_overridden_tool_def(cmd_name: str, override: Dict[str, Any], default_desc: str) -> Dict[str, Any]:
    """Generate a single tool definition from override config."""
    # Normalize name for API compatibility
    normalized_name = _normalize_tool_name(cmd_name)

    # Register mapping
    _tool_name_mapping[normalized_name] = cmd_name

    schema = {
        "name": normalized_name,
        "description": override.get("description", default_desc),
        "parameters": override["parameters"],
    }

    return {"type": "function", "function": schema}


def check_tool_user_permission(tool_name: str, full_user_id: str) -> bool:
    """
    Check if user has permission to use the tool based on allowed_users config.
    Uses fnmatch for wildcard pattern matching.

    Args:
        tool_name: The tool/command name
        full_user_id: User's full session ID (e.g., "onebotv11+private+123456789")

    Returns:
        True if user has permission, False otherwise
    """
    override = config.tool_schema_override.get(tool_name)
    if not override:
        return True  # No override = no restriction

    allowed_users = override.get("allowed_users")
    if not allowed_users:
        return True  # No allowed_users = open to all

    # Check if user matches any pattern
    for pattern in allowed_users:
        if fnmatch.fnmatch(full_user_id, pattern):
            logger.debug(f"[Tool Registry] Permission granted: {full_user_id} matches {pattern}")
            return True

    logger.debug(f"[Tool Registry] Permission denied: {full_user_id} not in allowed_users for {tool_name}")
    return False


def get_tool_definitions(full_user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Scan all registered Alconna commands AND traditional on_command handlers,
    then generate JSON Schemas for allowed tools.

    Args:
        full_user_id: If provided, filter tools by user permission (dual-layer filtering)
    """
    if not config.tool_enable:
        logger.debug("[Tool Registry] Tool system disabled (tool_enable=False)")
        return []
        return []

    allowlist = config.tool_allowlist or set()
    logger.debug(f"[Tool Registry] Allowlist: {allowlist}")

    if not allowlist:
        logger.warning("[Tool Registry] TOOL_ALLOWLIST is empty, no tools will be exposed")
        return []

    tools = []
    discovered_names = set()

    # === Part 1: Alconna Commands ===
    try:
        commands = command_manager.get_commands()
        logger.debug(f"[Tool Registry] Found {len(commands)} registered Alconna commands")
        alconna_names = [cmd.name for cmd in commands]
        logger.debug(f"[Tool Registry] Alconna command names: {alconna_names}")

        for cmd in commands:
            if cmd.name not in allowlist:
                continue

            # Permission check: skip tools user cannot access
            if full_user_id and not check_tool_user_permission(cmd.name, full_user_id):
                logger.debug(f"[Tool Registry] Filtered out {cmd.name}: user {full_user_id} not allowed")
                continue

            try:
                # Check for override
                override = config.tool_schema_override.get(cmd.name)
                if override and "parameters" in override:
                    # Alconna uses meta.description, not .help
                    default_desc = (
                        cmd.meta.description if cmd.meta and cmd.meta.description else f"Execute /{cmd.name} command"
                    )
                    tool_def = _create_overridden_tool_def(cmd.name, override, default_desc)
                    tools.append(tool_def)
                    logger.debug(f"[Tool Registry] Using override schema for: {cmd.name}")
                else:
                    schema = _alconna_to_schema(cmd)
                    tool_def = {"type": "function", "function": schema}
                    tools.append(tool_def)
                discovered_names.add(cmd.name)
                logger.debug(f"[Tool Registry] Generated Alconna tool schema for: {cmd.name}")
            except Exception as e:
                logger.warning(f"Failed to generate schema for Alconna command {cmd.name}: {e}")
    except Exception as e:
        logger.warning(f"Failed to get Alconna commands: {e}")

    # === Part 2: Traditional on_command Handlers ===
    try:
        from nonebot import get_loaded_plugins
        from nonebot.rule import CommandRule

        for plugin in get_loaded_plugins():
            for matcher in plugin.matcher:
                # Skip if already discovered via Alconna
                # Check if matcher has CommandRule in its rule checkers
                if not hasattr(matcher, "rule") or not matcher.rule:
                    continue

                for checker in matcher.rule.checkers:
                    dep_call = getattr(checker, "call", None)
                    if dep_call is None:
                        continue

                    # Check if it's a CommandRule
                    if isinstance(dep_call, CommandRule):
                        # CommandRule.cmds is a tuple of command tuples
                        for cmd_tuple in dep_call.cmds:
                            # cmd_tuple is like ("天气",) or ("weather", "w")
                            cmd_name = cmd_tuple[0] if cmd_tuple else None
                            if not cmd_name:
                                continue

                            # Skip if already discovered or not in allowlist
                            if cmd_name in discovered_names:
                                continue
                            if cmd_name not in allowlist:
                                continue

                            # Permission check: skip tools user cannot access
                            if full_user_id and not check_tool_user_permission(cmd_name, full_user_id):
                                logger.debug(
                                    f"[Tool Registry] Filtered out {cmd_name}: user {full_user_id} not allowed"
                                )
                                continue

                            # Check for override
                            override = config.tool_schema_override.get(cmd_name)
                            if override and "parameters" in override:
                                tool_def = _create_overridden_tool_def(
                                    cmd_name, override, f"Execute /{cmd_name} command"
                                )
                                tools.append(tool_def)
                                logger.debug(f"[Tool Registry] Using override schema for on_command: {cmd_name}")
                            else:
                                # Generate simple schema for on_command
                                schema = _on_command_to_schema(cmd_name, plugin.name)

                            tools.append({"type": "function", "function": schema})
                            discovered_names.add(cmd_name)
                            logger.debug(
                                f"[Tool Registry] Generated tool schema for: {cmd_name} (plugin: {plugin.name})"
                            )

    except Exception as e:
        logger.warning(f"Failed to discover on_command handlers: {e}")

    logger.debug(f"[Tool Registry] Total tools exposed: {len(tools)}, names: {list(discovered_names)}")
    return tools


def _on_command_to_schema(cmd_name: str, plugin_name: str = "") -> Dict[str, Any]:
    """Generate a simple schema for traditional on_command handlers."""
    # Normalize the name for OpenAI API compatibility
    normalized_name = _normalize_tool_name(cmd_name)

    return {
        "name": normalized_name,
        "description": f"Execute /{cmd_name} command" + (f" from {plugin_name}" if plugin_name else ""),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": f"Arguments to pass to the /{cmd_name} command (e.g., city name, search term)",
                }
            },
            "required": ["query"],
        },
    }


def _normalize_tool_name(name: str) -> str:
    """
    Normalize a tool name to be compatible with OpenAI function calling API.
    OpenAI requires: start with letter/underscore, alphanumeric + _.-: only, max 64 chars.

    For non-ASCII names (e.g., Chinese), we create a hash-based name and store the mapping.
    """
    global _tool_name_mapping

    # Check if already ASCII-compatible
    if re.match(r"^[a-zA-Z_][a-zA-Z0-9_.:/-]*$", name) and len(name) <= 64:
        _tool_name_mapping[name] = name
        return name

    # For non-ASCII or invalid names, create a normalized version
    # Use a short hash suffix for uniqueness
    hash_suffix = hashlib.md5(name.encode()).hexdigest()[:8]
    normalized = f"cmd_{hash_suffix}"

    _tool_name_mapping[normalized] = name
    logger.debug(f"[Tool Registry] Normalized tool name: '{name}' -> '{normalized}'")

    return normalized


def get_original_tool_name(normalized_name: str) -> str:
    """Get the original command name from a normalized tool name."""
    return _tool_name_mapping.get(normalized_name, normalized_name)


def _map_python_type_to_json_type(py_type: Any) -> Dict[str, Any]:
    """Map Python types to JSON Schema types."""
    origin = get_origin(py_type)
    args = get_args(py_type)

    if origin is list or py_type is list:
        item_schema = _map_python_type_to_json_type(args[0]) if args else {}
        return {"type": "array", "items": item_schema}

    if py_type is int:
        return {"type": "integer"}
    if py_type is float:
        return {"type": "number"}
    if py_type is bool:
        return {"type": "boolean"}
    if py_type is str:
        return {"type": "string"}

    # Simple fallback
    return {"type": "string"}


def _alconna_to_schema(alc: "Alconna") -> Dict[str, Any]:
    """Convert an Alconna object to JSON Schema."""
    name = alc.name
    description = alc.meta.description if alc.meta and alc.meta.description else f"Execute {name} command"

    properties = {}
    required = []

    # 1. Process Main Args (Positional/Named)
    for arg in alc.args:
        # arg is an Arg object
        param_name = arg.name
        param_type = arg.value

        # Determine if optional
        # Alconna Arg doesn't have a simple 'required' flag, it depends on default value.
        # Arg(name='city', value=str, field=Field(default=...))
        # We can inspect arg.field.default
        is_optional = False
        default_val = None

        if hasattr(arg, "field"):
            # inspect._empty is checking against type(inspect._empty) or specific singleton?
            # Let's check string representation or use simple try-catch
            if str(arg.field.default) != "inspect._empty":
                is_optional = True
                default_val = arg.field.default

        if arg.optional:  # Arg has .optional attribute? Let's assume based on inspect script output: optional=False
            is_optional = True

        schema_type = _map_python_type_to_json_type(param_type)
        if default_val is not None and not isinstance(default_val, type):
            schema_type["default"] = str(default_val)  # stringify for safety

        properties[param_name] = schema_type
        if not is_optional:
            required.append(param_name)

    # 2. Process Options
    for opt in alc.options:
        # Skip internal help options
        if opt.name in ("--help", "-h", "--comp", "/?", "-?"):
            continue

        # Option name: "--days" -> "days"
        # If option has alias like "-d", we prefer the long name without dashes
        # Logic: strip leading dashes
        opt_name = opt.name.lstrip("-")

        # Check arguments of the option.
        # Case A: Flag (No args) -> Boolean
        if not opt.args:
            properties[opt_name] = {
                "type": "boolean",
                "description": opt.help_text or f"Flag {opt.name}",
                "default": False,
            }
            # Flags are never required
            continue

        # Case B: Option with Value (Args)
        # We process the FIRST arg of the option as the value for simplicity
        # If Option has multiple args, LLM Tool Call usually passes key-value pairs.
        # Mapping Option with multiple args to a single property is tricky.
        # Strategy: Use the name of the first arg inside option as the property name?
        # NO, usually we want the Option Name to be the property key in tool call.
        # e.g. /weather --days 3 -> tool call: weather(..., days=3)

        first_arg = next(iter(opt.args))
        arg_type = first_arg.value
        schema_type = _map_python_type_to_json_type(arg_type)

        properties[opt_name] = schema_type
        # Options are generally optional

    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }
