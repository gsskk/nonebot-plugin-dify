import time
from dataclasses import dataclass, field
from cachetools import TTLCache
from nonebot import logger

from .config import config


# 1. 用 dataclass 定义会话，清晰简洁
@dataclass
class Session:
    """Represents a user's conversation session."""

    id: str
    user: str
    conversation_id: str = ""
    message_counter: int = 0


@dataclass
class GroupState:
    """Represents the shared state of a group chat for Linger and Proactive modes."""

    id: str  # e.g., "adapter+group_id"
    last_interaction_time: float = 0.0
    linger_message_count: int = 0
    proactive_last_trigger_time: float = 0.0
    proactive_pending_task_id: str = ""
    created_at: float = field(default_factory=time.time)


# 2. 全局的、唯一的缓存实例
# 根据配置决定使用 TTLCache 还是普通字典
SESSION_CACHE = TTLCache(maxsize=1024, ttl=config.session_expires_seconds) if config.session_expires_seconds else {}
GROUP_STATE_CACHE = TTLCache(maxsize=1024, ttl=config.session_expires_seconds) if config.session_expires_seconds else {}


# 3. 简单的、直接的函数式接口
def get_session(session_id: str, user: str) -> Session:
    """
    获取或创建一个会话，并刷新其在缓存中的生命周期。

    Args:
        session_id: The ID of the session.
        user: The user identifier.

    Returns:
        The Session object.
    """
    session = SESSION_CACHE.get(session_id)
    if session is None:
        logger.debug(f"Session {session_id} not in cache or expired, creating a new one.")
        session = Session(id=session_id, user=user)

    # 刷新TTL: 无论会话是新建的还是从缓存中获取的，都将其重新插入缓存
    # 这会有效地刷新其在 TTLCache 中的过期时间，实现“访问即续期”
    SESSION_CACHE[session_id] = session
    return session


def get_group_state(group_state_id: str) -> GroupState:
    """
    获取或创建一个群组状态，并刷新其在缓存中的生命周期。

    Args:
        group_state_id: The ID of the group state (e.g. adapter+group_id).

    Returns:
        The GroupState object.
    """
    state = GROUP_STATE_CACHE.get(group_state_id)
    if state is None:
        logger.debug(f"GroupState {group_state_id} not in cache or expired, creating a new one.")
        state = GroupState(id=group_state_id)

    # 刷新TTL
    GROUP_STATE_CACHE[group_state_id] = state
    return state


def count_user_message(session: Session):
    """
    计算用户消息数量，并在达到阈值时重置会话的 conversation_id。

    Args:
        session: The Session object to process.
    """
    if not config.session_max_messages:
        return

    session.message_counter += 1
    if session.message_counter >= config.session_max_messages:
        logger.info(
            f"Session {session.id} message count reached limit ({config.session_max_messages}), "
            f"conversation_id will be reset."
        )
        session.message_counter = 0
        session.conversation_id = ""


def clear_session(session_id: str):
    """
    从缓存中清除单个会话。

    Args:
        session_id: The ID of the session to clear.
    """
    if session_id in SESSION_CACHE:
        logger.info(f"Clearing session {session_id}")
        try:
            del SESSION_CACHE[session_id]
        except KeyError:
            logger.warning(f"Session {session_id} was already removed, likely due to a race condition.")


def clear_all_sessions():
    """清除缓存中的所有会话。"""
    logger.info("Clearing all sessions")
    SESSION_CACHE.clear()
