"""
Core Persona Storage - 不可变的 Bot 人格配置。
此配置由用户手动维护，Profiler Workflow 不会修改。
"""

import yaml
from pathlib import Path
from typing import Optional

import nonebot_plugin_localstore as store
from nonebot.log import logger


from ..config import config as plugin_config

_core_persona_file: Path = store.get_data_file("nonebot_plugin_dify", "core_persona.yaml")
_group_core_personas_file: Path = store.get_data_file("nonebot_plugin_dify", "group_core_personas.yaml")
_private_core_personas_file: Path = store.get_data_file("nonebot_plugin_dify", "private_core_personas.yaml")

_core_persona_cache: Optional[dict] = None
_group_core_personas_cache: Optional[dict] = None
_private_core_personas_cache: Optional[dict] = None

# 模板内容
_GROUP_TEMPLATE = """# 群组核心人设覆盖配置
# 为特定群组设置不同的 Bot 人设，覆盖全局 core_persona.yaml
#
# 格式: adapter+group_id:
#   identity:
#     name: "群专属助手"
#     role: "你的角色描述"
#   core_rules:
#     - "必须遵守的规则"
#   never_do:
#     - "禁止的行为"
#
# 示例:
# qq+123456789:
#   identity:
#     name: "技术讨论群助手"
#     role: "专业的技术问答助手"
#   core_rules:
#     - "回答时引用权威技术文档"
"""

_PRIVATE_TEMPLATE = """# 私聊核心人设覆盖配置
# 为特定用户的私聊设置不同的 Bot 人设，覆盖全局 core_persona.yaml
#
# 格式: adapter+user_id:
#   identity:
#     name: "私聊专属助手"
#     role: "你的角色描述"
#   core_rules:
#     - "必须遵守的规则"
#   never_do:
#     - "禁止的行为"
#
# 示例:
# qq+987654321:
#   identity:
#     name: "个人助理小艾"
#     role: "专属个人助理"
#   core_rules:
#     - "记住用户的偏好和习惯"
"""


def _generate_template_if_missing(file_path: Path, template: str) -> None:
    """若文件不存在，生成带注释的空模板文件。"""
    if file_path.exists():
        return
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(template)
        logger.info(f"已生成核心人设覆盖配置模板: {file_path}")
    except Exception as e:
        logger.warning(f"生成模板文件失败 {file_path}: {e}")


def _load_yaml(file_path: Path) -> dict:
    """加载 YAML 文件，文件不存在或无效时返回空字典。"""
    if not file_path.exists():
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"加载配置文件失败 {file_path}: {e}")
        return {}


def get_core_persona() -> str:
    """获取全局核心人设，格式化为字符串。"""
    global _core_persona_cache
    if _core_persona_cache is None:
        # 如果文件不存在，则从默认配置生成
        if not _core_persona_file.exists() and plugin_config.core_persona_default:
            try:
                logger.info(f"生成默认核心人设配置文件: {_core_persona_file}")
                _core_persona_file.parent.mkdir(parents=True, exist_ok=True)
                with open(_core_persona_file, "w", encoding="utf-8") as f:
                    f.write(plugin_config.core_persona_default)
            except Exception as e:
                logger.warning(f"写入默认核心人设文件失败: {e}")

        _core_persona_cache = _load_yaml(_core_persona_file)
    return _format_core_persona(_core_persona_cache)


def get_group_core_persona(adapter_name: str, group_id: str) -> str:
    """获取群组特定的核心人设，无则回退到全局配置。"""
    global _group_core_personas_cache
    if _group_core_personas_cache is None:
        # 首次访问时生成模板文件
        _generate_template_if_missing(_group_core_personas_file, _GROUP_TEMPLATE)
        _group_core_personas_cache = _load_yaml(_group_core_personas_file)

    key = f"{adapter_name}+{group_id}"
    if key in _group_core_personas_cache:
        return _format_core_persona(_group_core_personas_cache[key])
    return get_core_persona()


def get_private_core_persona(adapter_name: str, user_id: str) -> str:
    """获取私聊用户特定的核心人设，无则回退到全局配置。"""
    global _private_core_personas_cache
    if _private_core_personas_cache is None:
        # 首次访问时生成模板文件
        _generate_template_if_missing(_private_core_personas_file, _PRIVATE_TEMPLATE)
        _private_core_personas_cache = _load_yaml(_private_core_personas_file)

    key = f"{adapter_name}+{user_id}"
    if key in _private_core_personas_cache:
        return _format_core_persona(_private_core_personas_cache[key])
    return get_core_persona()


def get_core_persona_for_profiler(adapter_name: str = None, group_id: str = None, user_id: str = None) -> str:
    """获取用于 Profiler Workflow 注入的核心人设，带有锁定标记。"""
    if adapter_name and group_id:
        # 群聊场景
        persona = get_group_core_persona(adapter_name, group_id)
    elif adapter_name and user_id:
        # 私聊场景
        persona = get_private_core_persona(adapter_name, user_id)
    else:
        persona = get_core_persona()

    if not persona:
        return ""
    return f"[LOCKED - DO NOT MODIFY IN personalization_summary]\n{persona}"


def _format_core_persona(data: dict) -> str:
    """将核心人设字典格式化为提示友好的字符串。"""
    if not data:
        return ""

    parts = []

    # Identity 部分
    identity = data.get("identity", {})
    if identity:
        for key in ["name", "role", "master", "speaking_style"]:
            if identity.get(key):
                label = key.replace("_", " ").title()
                parts.append(f"{label}: {identity[key]}")

    # Rules 部分
    for section, label in [("core_rules", "Core Rules (MUST FOLLOW)"), ("never_do", "NEVER DO")]:
        items = data.get(section, [])
        if items:
            parts.append(f"\n{label}:")
            parts.extend([f"- {item}" for item in items])

    return "\n".join(parts)


def reload_core_persona():
    """强制从磁盘重载配置（用于热更新）。"""
    global _core_persona_cache, _group_core_personas_cache, _private_core_personas_cache
    _core_persona_cache = None
    _group_core_personas_cache = None
    _private_core_personas_cache = None
    logger.info("核心人设配置缓存已清空，下次访问时将重新加载。")
